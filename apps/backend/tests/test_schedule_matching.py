"""Fuzzy group-name matching — the riskiest pure function in the schedule path.

Group names upstream are free-text and inconsistent ("120 A lesh ENG",
"PEDIATRIYA-209 RUS QOSPA", "Joqarı miyirbiykelik isi-233"), students say them
loosely, and speech recognition adds more variance. The candidates below are
verbatim from the institute's live HEMIS data.

The negative cases matter more than the positive ones: showing a confidently
wrong timetable is worse than admitting no match, because the student walks to
the wrong room and only finds out when the class does not happen.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.core.schedule import SCOPES, _normalize, _score, scope_range

# Verbatim sample of real group names.
CANDIDATES = [
    "120 A lesh ENG",
    "120 lesh RUS",
    "110A lesh QQ",
    "107 lesh  QQ",
    "PEDIATRIYA-209 RUS QOSPA",
    "Pediatriya-207 Uz",
    "Pediatriya isi 101 QQ",
    "Pediatriya-101A QQ",
    "Stomatologiya-232 Rus",
    "Stomatologiya-231 Uz",
    "Joqarı miyirbiykelik isi-233",
    "Joqarı miyirbiykelik isi-234",
    "tashxis 1-kurs",
    "Sogliqni saqlash 1-kurs",
]

THRESHOLD = 0.45


def best(query: str) -> tuple[float, str]:
    scored = sorted(((_score(query, c), c) for c in CANDIDATES), reverse=True)
    return scored[0]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("120 A lesh ENG", "120 A lesh ENG"),
        ("120 A", "120 A lesh ENG"),
        ("pediatriya 209", "PEDIATRIYA-209 RUS QOSPA"),
        ("pediatriya 209 rus", "PEDIATRIYA-209 RUS QOSPA"),
        ("stomatologiya 232", "Stomatologiya-232 Rus"),
        ("joqari miyirbiykelik 233", "Joqarı miyirbiykelik isi-233"),
        ("tashxis 1-kurs", "tashxis 1-kurs"),
    ],
)
def test_matches_expected_group(query: str, expected: str) -> None:
    score, name = best(query)
    assert name == expected
    assert score >= THRESHOLD


def test_cyrillic_query_matches_latin_group() -> None:
    """The same group is written in Cyrillic and Latin across the institute's
    data, and visitors speak both."""
    score, name = best("Стоматология 232")
    assert name == "Stomatologiya-232 Rus"
    assert score >= THRESHOLD


def test_unmatched_words_are_not_rescued_by_a_digit() -> None:
    """"Davolash ishi" is a specialty; its groups are named "... lesh ...", so
    no group contains "davolash". Group numbers repeat across programmes, so a
    bare digit match would otherwise surface Pediatriya-101 — a plausible-
    looking wrong timetable."""
    score, _ = best("davolash 101")
    assert score < THRESHOLD


def test_spelled_out_number_does_not_match() -> None:
    """The agent must convert spoken numerals to digits before searching;
    if it does not, we would rather find nothing than guess."""
    score, _ = best("bir yuz yigirma A")
    assert score < THRESHOLD


def test_normalize_folds_script_and_punctuation() -> None:
    assert _normalize("PEDIATRIYA-209 RUS QOSPA") == "pediatriya 209 rus qospa"
    assert _normalize("Joqarı miyirbiykelik isi-233") == "joqari miyirbiykelik isi 233"
    # Cyrillic transliterates onto the same form as the Latin spelling.
    assert _normalize("Стоматология") == _normalize("Stomatologiya")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Dotless ı is not decomposable by NFKD, so an a-z filter alone deletes
        # it — which used to split this kafedra name into "medicinal q ... kafedras".
        ("Medicinalıq ximiya kafedrası", "medicinaliq ximiya kafedrasi"),
        ("Bılımlendırıw sapasın támiyinlew bólimi", "bilimlendiriw sapasin tamiyinlew bolimi"),
        # Small-capital ɪ appears in real HEMIS department names.
        ("Emlew isleri boyɪnsha prorektor", "emlew isleri boyinsha prorektor"),
        # Uzbek Latin apostrophes must vanish, not become a word break.
        ("Qoraqalpogʻiston tibbiyot instituti", "qoraqalpogiston tibbiyot instituti"),
        ("o'zbek tili", "ozbek tili"),
        # Accented Karakalpak letters fold through NFKD.
        ("Ózbektili, tiller hám jámiyetlik pánler", "ozbektili tiller ham jamiyetlik panler"),
    ],
)
def test_normalize_keeps_karakalpak_and_uzbek_latin(raw: str, expected: str) -> None:
    assert _normalize(raw) == expected


def test_dotless_i_spelling_variants_match_each_other() -> None:
    """A student types/says "joqari"; HEMIS stores "Joqarı". Both must land on
    the same group."""
    assert _score("joqari miyirbiykelik 233", "Joqarı miyirbiykelik isi-233") >= 0.9
    assert _score("joqarı miyirbiykelik 233", "Joqarı miyirbiykelik isi-233") >= 0.9


def test_identical_name_scores_one() -> None:
    assert _score("120 A lesh ENG", "120 A lesh ENG") == 1.0


def test_empty_query_scores_zero() -> None:
    assert _score("", "120 A lesh ENG") == 0.0


# ── Scope resolution ──────────────────────────────────────────────────────────
#
# `date` and `week_of` never touch the database, so they are pure enough to
# test here. `last_taught_week` is not — it asks Postgres for the group's most
# recent lesson — and is covered by the live smoke run in DEPLOY.md.


async def test_date_scope_returns_exactly_that_day() -> None:
    day = date(2026, 5, 11)
    assert await scope_range(None, 1, "date", day) == (day, day)  # type: ignore[arg-type]


async def test_week_of_snaps_to_the_monday_of_that_week() -> None:
    """The kiosk's date picker hands over whatever day was tapped; a visitor
    who picks Thursday and asks for the week means Mon–Sun around it."""
    thursday = date(2026, 5, 14)
    assert await scope_range(None, 1, "week_of", thursday) == (  # type: ignore[arg-type]
        date(2026, 5, 11),
        date(2026, 5, 17),
    )


async def test_week_of_is_stable_when_the_anchor_is_already_monday() -> None:
    monday = date(2026, 5, 11)
    assert await scope_range(None, 1, "week_of", monday) == (  # type: ignore[arg-type]
        monday,
        date(2026, 5, 17),
    )


def test_picker_scopes_are_declared() -> None:
    """The endpoint validates against SCOPES before dispatching; a scope the
    kiosk sends but SCOPES omits silently degrades to "today"."""
    assert {"date", "week_of", "last_taught_week"} <= set(SCOPES)
