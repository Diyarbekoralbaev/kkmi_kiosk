"""Read layer over the HEMIS mirror.

Everything the kiosk and the AI tools ask about schedules, groups, faculties
and specialties goes through here. All queries hit our own Postgres — see
`domain/hemis.py` for why the data is mirrored rather than fetched live.

Reference names (subject, teacher, room, lesson type) are LEFT JOINed: the
mirror deliberately has no foreign keys, so a lesson can point at a group or
employee that upstream has not published yet. A missing name renders as an
empty string instead of dropping the lesson — a student would rather see
"08:30 · room 2-201" with a blank subject than not see the class at all.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.hemis import (
    HemisAuditorium,
    HemisDepartment,
    HemisEmployee,
    HemisGroup,
    HemisLesson,
    HemisSpecialty,
    HemisSubject,
    HemisTrainingType,
)
from .timezone import today_local

# HEMIS models faculties, kafedras and rectorate offices in one table;
# structureType.code "11" is the faculty subset the kiosk drills down from.
FACULTY_STRUCTURE_CODE = "11"


# ── Fuzzy group matching ──────────────────────────────────────────────────────
#
# Group names upstream are free-text and inconsistent: "120 A lesh ENG",
# "Joqarı miyirbiykelik isi-233", "PEDIATRIYA-209 RUS QOSPA", "tashxis 1-kurs
# (uzb)". A student says "bir yuz yigirma A" or "pediatriya 209"; speech
# recognition then adds its own spelling variance. Exact matching is hopeless,
# so the voice path proposes candidates and the agent confirms one aloud.
#
# Scored in Python over the full group list rather than in SQL: 998 rows is
# nothing to sort, and it avoids requiring the pg_trgm extension (which needs
# superuser to install and would not exist on a locked-down managed Postgres).

_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "s", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ә": "a", "ғ": "g", "қ": "q", "ң": "n", "ө": "o", "ү": "u", "ұ": "u",
    "ҳ": "h", "ҷ": "j", "ў": "o",
}

# Latin letters that NFKD does NOT decompose, so the a-z filter would delete
# them outright. That is not cosmetic: "Medicinalıq ximiya kafedrası" would
# normalize to "medicinal q ximiya kafedras" — the dotless ı splits a word in
# two and the trailing one vanishes. Karakalpak and Uzbek Latin use these
# throughout the institute's HEMIS data, so they are mapped explicitly.
# (Accented forms — á ǵ ń ó ú ş ç ğ — do decompose and are handled by NFKD.)
_LATIN_FOLD = {
    "ı": "i", "ɪ": "i", "İ": "i",
    "ø": "o", "đ": "d", "ł": "l", "ħ": "h", "ŋ": "n",
}

# Apostrophe variants are DELETED, not turned into a separator: Uzbek Latin
# writes "Qoraqalpogʻiston" and "o'zbek", which must fold to "qoraqalpogiston"
# and "ozbek" — inserting a space there would break every token match.
_APOSTROPHES = "'’‘ʻʼ`´"

_FOLD_TABLE = str.maketrans(
    {**_CYRILLIC_TO_LATIN, **_LATIN_FOLD, **dict.fromkeys(_APOSTROPHES, "")}
)


def _normalize(text: str) -> str:
    """Fold a group name (or a spoken query) to a comparable form.

    Cyrillic is transliterated to Latin because the same group is written both
    ways across the institute's data and speech, and diacritics are stripped so
    "Joqarı" and "Joqari" match.
    """
    s = (text or "").strip().lower()
    s = s.translate(_FOLD_TABLE)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _score(query: str, candidate: str) -> float:
    """0..1 similarity, biased toward the tokens a student actually says.

    A group name carries a lot of noise the speaker omits ("lesh", "QOSPA",
    the language suffix), so plain string similarity under-scores a correct
    match. Token containment is therefore weighted heavily, and digit runs —
    the part a student is most likely to say exactly, e.g. "209" — count
    double.

    A digit match alone is NOT evidence. Group numbers repeat across
    programmes, so "davolash 101" would otherwise score 0.61 against
    "Pediatriya isi 101 QQ" — a confident-looking wrong timetable, the worst
    outcome this function can produce. When the query names something in words
    and none of those words appear in the candidate, the score is damped below
    any usable threshold.
    """
    q, c = _normalize(query), _normalize(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0

    q_tokens = q.split()
    c_tokens = set(c.split())
    if not q_tokens:
        return 0.0

    hits = weight = 0.0
    alpha_tokens = alpha_hits = 0
    for tok in q_tokens:
        is_digit = tok.isdigit()
        w = 2.0 if is_digit else 1.0
        weight += w
        if not is_digit:
            alpha_tokens += 1
        matched = tok in c_tokens or any(tok in ct for ct in c_tokens)
        if matched:
            hits += w
            if not is_digit:
                alpha_hits += 1
    containment = hits / weight if weight else 0.0

    score = 0.7 * containment + 0.3 * SequenceMatcher(None, q, c).ratio()
    if alpha_tokens and not alpha_hits:
        score *= 0.4
    return score


def _group_dict(g: HemisGroup) -> dict[str, Any]:
    return {
        "id": g.id,
        "name": g.name,
        "faculty_id": g.department_id,
        "specialty_id": g.specialty_id,
        "specialty": g.specialty_name,
        "language": g.education_lang_name,
    }


# ── Queries ───────────────────────────────────────────────────────────────────


async def faculties(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(HemisDepartment)
            .where(
                HemisDepartment.structure_type_code == FACULTY_STRUCTURE_CODE,
                HemisDepartment.active.is_(True),
            )
            .order_by(HemisDepartment.name)
        )
    ).scalars()
    return [{"id": d.id, "name": d.name.strip(), "code": d.code} for d in rows]


async def groups(
    session: AsyncSession, *, faculty_id: int | None = None
) -> list[dict[str, Any]]:
    stmt = select(HemisGroup).where(HemisGroup.active.is_(True))
    if faculty_id is not None:
        stmt = stmt.where(HemisGroup.department_id == faculty_id)
    rows = (await session.execute(stmt.order_by(HemisGroup.name))).scalars()
    return [_group_dict(g) for g in rows]


async def find_groups(
    session: AsyncSession, query: str, *, limit: int = 3, threshold: float = 0.45
) -> list[dict[str, Any]]:
    """Best fuzzy matches for a spoken group name, best first.

    Returns [] rather than a bad guess when nothing clears the threshold — the
    agent must then ask again instead of showing a stranger's timetable.
    """
    if not (query or "").strip():
        return []
    rows = (
        await session.execute(select(HemisGroup).where(HemisGroup.active.is_(True)))
    ).scalars()
    scored = [(_score(query, g.name), g) for g in rows]
    scored = [(s, g) for s, g in scored if s >= threshold]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [{**_group_dict(g), "score": round(s, 3)} for s, g in scored[:limit]]


async def group_by_id(session: AsyncSession, group_id: int) -> dict[str, Any] | None:
    g = (
        await session.execute(select(HemisGroup).where(HemisGroup.id == group_id))
    ).scalar_one_or_none()
    return _group_dict(g) if g else None


SCOPES = ("today", "tomorrow", "week", "last_taught_week")


async def scope_range(
    session: AsyncSession, group_id: int, scope: str
) -> tuple[date, date]:
    """Resolve a scope name to an inclusive date range for one group.

    `last_taught_week` is the group's most recent week that actually has
    classes — NOT a fixed offset. The first version subtracted 365 days, which
    looked reasonable and was wrong the moment it mattered: asked over the
    summer break it landed in the *previous* summer and returned nothing, so
    the fallback offered to a visitor was as empty as the thing it replaced.
    """
    today = today_local()
    if scope == "today":
        return today, today
    if scope == "tomorrow":
        nxt = today + timedelta(days=1)
        return nxt, nxt
    if scope == "last_taught_week":
        last = (
            await session.execute(
                select(func.max(HemisLesson.lesson_date)).where(
                    HemisLesson.group_id == group_id,
                    HemisLesson.lesson_date <= today,
                )
            )
        ).scalar()
        if last is None:
            # Group has no past lessons at all; hand back this week so the
            # caller's empty-reason logic runs normally instead of guessing.
            start = today - timedelta(days=today.weekday())
            return start, start + timedelta(days=6)
        start = last - timedelta(days=last.weekday())
        return start, start + timedelta(days=6)
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


async def lessons_for_group(
    session: AsyncSession, group_id: int, day_from: date, day_to: date
) -> list[dict[str, Any]]:
    """Lessons for one group over an inclusive date range, in timetable order."""
    stmt = (
        select(
            HemisLesson,
            HemisSubject.name,
            HemisEmployee.name,
            HemisAuditorium.name,
            HemisAuditorium.building,
            HemisTrainingType.name,
        )
        .outerjoin(HemisSubject, HemisSubject.id == HemisLesson.subject_id)
        .outerjoin(HemisEmployee, HemisEmployee.id == HemisLesson.employee_id)
        .outerjoin(
            HemisAuditorium, HemisAuditorium.code == HemisLesson.auditorium_code
        )
        .outerjoin(
            HemisTrainingType,
            HemisTrainingType.code == HemisLesson.training_type_code,
        )
        .where(
            HemisLesson.group_id == group_id,
            HemisLesson.lesson_date >= day_from,
            HemisLesson.lesson_date <= day_to,
        )
        .order_by(HemisLesson.lesson_date, HemisLesson.start_time)
    )
    out: list[dict[str, Any]] = []
    for lesson, subject, teacher, room, building, kind in await session.execute(stmt):
        out.append(
            {
                "id": lesson.id,
                "date": lesson.lesson_date.isoformat(),
                "weekday": lesson.weekday,
                "start": lesson.start_time,
                "end": lesson.end_time,
                "subject": subject or "",
                "teacher": teacher or "",
                "room": room or "",
                "building": building or "",
                "kind": kind or "",
            }
        )
    return out


async def specialties(session: AsyncSession) -> list[dict[str, Any]]:
    """Degree programmes, grouped-by-faculty friendly. Feeds AI Abituriyent."""
    stmt = (
        select(HemisSpecialty, HemisDepartment.name)
        .outerjoin(
            HemisDepartment, HemisDepartment.id == HemisSpecialty.department_id
        )
        .where(HemisSpecialty.active.is_(True))
        .order_by(HemisSpecialty.education_type_code, HemisSpecialty.name)
    )
    out: list[dict[str, Any]] = []
    for spec, faculty in await session.execute(stmt):
        out.append(
            {
                "id": spec.id,
                "code": spec.code,
                "name": spec.name,
                "faculty": (faculty or "").strip(),
                "education_type": spec.education_type_name,
            }
        )
    return out
