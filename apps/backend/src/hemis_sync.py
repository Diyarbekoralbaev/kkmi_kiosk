"""Mirror HEMIS into Postgres. Entry point: `python -m src.hemis_sync`.

Run nightly from cron/a compose sidecar, not from the FastAPI lifespan: prod
runs uvicorn with several workers and each one would kick off its own sweep.

Four upstream sweeps:

    departments  →  hemis_departments      (faculties + kafedras + offices)
    specialties  →  hemis_specialties      (degree programmes)
    groups       →  hemis_groups           (incl. groups with no lessons yet)
    schedule     →  hemis_lessons  +  subjects / employees / auditoriums /
                                        lesson_pairs / training_types / semesters

The six reference tables are DERIVED from the schedule payload rather than
fetched separately: every schedule row already embeds the full nested objects,
so deriving them costs nothing and saves six extra sweeps.

Full sweep, not incremental — a deliberate change from the original plan.
`schedule-list` does support `updated_at_from`, but HEMIS exposes no deletion
feed, so an incremental run leaves cancelled classes on screen forever. That is
the one failure a kiosk must not have: a student walks to a room for a lesson
that was called off. A full sweep of the current academic year is ~570 pages
≈ 95 s at 6 req/s, which is nothing for a nightly job, and it gets deletions
right by construction: rows are stamped with the run timestamp and anything
left un-stamped afterwards is gone upstream, so it is deleted here too.

`--since` is available for a fast manual top-up when someone just wants
today's edits and can accept the ghost-row caveat.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .core import hemis
from .core.db import AsyncSessionLocal
from .core.logging import setup_logging
from .core.timezone import LOCAL_TZ
from .domain.hemis import (
    HemisAuditorium,
    HemisDepartment,
    HemisEmployee,
    HemisGroup,
    HemisLesson,
    HemisLessonPair,
    HemisSemester,
    HemisSpecialty,
    HemisSubject,
    HemisSyncState,
    HemisTrainingType,
)

logger = structlog.get_logger(__name__)

CHUNK = 1000


def _s(value: Any, default: str = "") -> str:
    """Upstream mixes None, ints and padded strings in the same field."""
    if value is None:
        return default
    return str(value).strip()


def _i(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _upsert(
    session: AsyncSession, model: Any, rows: list[dict[str, Any]], pk: list[str]
) -> int:
    """Chunked INSERT ... ON CONFLICT DO UPDATE. Returns rows written."""
    if not rows:
        return 0
    written = 0
    for start in range(0, len(rows), CHUNK):
        chunk = rows[start : start + CHUNK]
        stmt = insert(model).values(chunk)
        update_cols = {
            c: stmt.excluded[c] for c in chunk[0] if c not in pk and c != "created_at"
        }
        await session.execute(
            stmt.on_conflict_do_update(index_elements=pk, set_=update_cols)
        )
        written += len(chunk)
    return written


async def _mark(
    session: AsyncSession,
    resource: str,
    *,
    status: str,
    count: int = 0,
    error: str = "",
    run_at: datetime | None = None,
) -> None:
    now = datetime.now(UTC)
    await session.execute(
        insert(HemisSyncState)
        .values(
            resource=resource,
            status=status,
            item_count=count,
            error=error[:2000],
            last_run_at=run_at or now,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["resource"],
            set_={
                "status": status,
                "item_count": count,
                "error": error[:2000],
                "last_run_at": run_at or now,
                "updated_at": now,
            },
        )
    )


# ── Reference sweeps ──────────────────────────────────────────────────────────


async def sync_departments(session: AsyncSession, stamp: datetime) -> int:
    # active=all: a renamed/retired kafedra still appears on last term's
    # schedule, and a lesson pointing at a missing department renders blank.
    items = await hemis.fetch_all("department-list", {"active": "all"})
    rows = [
        {
            "id": _i(d.get("id")),
            "name": _s(d.get("name")),
            "code": _s(d.get("code")),
            "structure_type_code": _s((d.get("structureType") or {}).get("code")),
            "structure_type_name": _s((d.get("structureType") or {}).get("name")),
            "parent_id": _i((d.get("parent") or {}).get("id"))
            if isinstance(d.get("parent"), dict)
            else _i(d.get("parent")),
            "active": bool(d.get("active", True)),
            "created_at": stamp,
            "updated_at": stamp,
        }
        for d in items
        if _i(d.get("id")) is not None
    ]
    return await _upsert(session, HemisDepartment, rows, ["id"])


async def sync_specialties(session: AsyncSession, stamp: datetime) -> int:
    items = await hemis.fetch_all("specialty-list")
    rows = [
        {
            "id": _i(s.get("id")),
            "code": _s(s.get("code")),
            "name": _s(s.get("name")),
            "department_id": _i((s.get("department") or {}).get("id")),
            "education_type_code": _s((s.get("educationType") or {}).get("code")),
            "education_type_name": _s((s.get("educationType") or {}).get("name")),
            "active": bool(s.get("active", True)),
            "created_at": stamp,
            "updated_at": stamp,
        }
        for s in items
        if _i(s.get("id")) is not None
    ]
    return await _upsert(session, HemisSpecialty, rows, ["id"])


async def sync_groups(session: AsyncSession, stamp: datetime) -> int:
    items = await hemis.fetch_all("group-list")
    rows = [
        {
            "id": _i(g.get("id")),
            "name": _s(g.get("name")),
            "department_id": _i((g.get("department") or {}).get("id")),
            "specialty_id": _i((g.get("specialty") or {}).get("id")),
            "specialty_name": _s((g.get("specialty") or {}).get("name")),
            "education_lang_code": _s((g.get("educationLang") or {}).get("code")),
            "education_lang_name": _s((g.get("educationLang") or {}).get("name")),
            "curriculum_id": _i(g.get("_curriculum")),
            "active": bool(g.get("active", True)),
            "created_at": stamp,
            "updated_at": stamp,
        }
        for g in items
        if _i(g.get("id")) is not None
    ]
    return await _upsert(session, HemisGroup, rows, ["id"])


# ── Schedule sweep + derived reference tables ─────────────────────────────────


def _derive_refs(items: list[dict[str, Any]], stamp: datetime) -> dict[str, list[dict]]:
    """Pull the six reference tables out of the schedule payload's nested
    objects. Deduped by key, last write wins."""
    subjects: dict[int, dict] = {}
    employees: dict[int, dict] = {}
    auditoriums: dict[str, dict] = {}
    pairs: dict[str, dict] = {}
    types: dict[str, dict] = {}
    semesters: dict[str, dict] = {}

    for it in items:
        subj = it.get("subject") or {}
        if (sid := _i(subj.get("id"))) is not None:
            subjects[sid] = {
                "id": sid,
                "name": _s(subj.get("name")),
                "code": _s(subj.get("code")),
                "created_at": stamp,
                "updated_at": stamp,
            }

        emp = it.get("employee") or {}
        if (eid := _i(emp.get("id"))) is not None:
            employees[eid] = {
                "id": eid,
                "name": _s(emp.get("name")),
                "created_at": stamp,
                "updated_at": stamp,
            }

        aud = it.get("auditorium") or {}
        if code := _s(aud.get("code")):
            auditoriums[code] = {
                "code": code,
                "name": _s(aud.get("name")),
                "building": _s((aud.get("building") or {}).get("name")),
                "kind": _s((aud.get("auditoriumType") or {}).get("name")),
                "volume": _i(aud.get("volume")),
                "created_at": stamp,
                "updated_at": stamp,
            }

        pair = it.get("lessonPair") or {}
        if code := _s(pair.get("code")):
            pairs[code] = {
                "code": code,
                "name": _s(pair.get("name")),
                "start_time": _s(pair.get("start_time")),
                "end_time": _s(pair.get("end_time")),
                "created_at": stamp,
                "updated_at": stamp,
            }

        ttype = it.get("trainingType") or {}
        if code := _s(ttype.get("code")):
            types[code] = {
                "code": code,
                "name": _s(ttype.get("name")),
                "created_at": stamp,
                "updated_at": stamp,
            }

        sem = it.get("semester") or {}
        if code := _s(sem.get("code")):
            semesters[code] = {
                "code": code,
                "name": _s(sem.get("name")),
                "created_at": stamp,
                "updated_at": stamp,
            }

    return {
        "subjects": list(subjects.values()),
        "employees": list(employees.values()),
        "auditoriums": list(auditoriums.values()),
        "pairs": list(pairs.values()),
        "types": list(types.values()),
        "semesters": list(semesters.values()),
    }


def _lesson_row(it: dict[str, Any], stamp: datetime) -> dict[str, Any] | None:
    ts = it.get("lesson_date")
    if not ts:
        return None
    # HEMIS sends a Unix epoch; the kiosk asks "what do I have today", so the
    # calendar date must be resolved in Asia/Tashkent, not UTC.
    local = datetime.fromtimestamp(int(ts), LOCAL_TZ)
    pair = it.get("lessonPair") or {}
    upstream_updated = it.get("updated_at")
    return {
        "id": _i(it.get("id")),
        "lesson_date": local.date(),
        "weekday": local.isoweekday(),
        "pair_code": _s(pair.get("code")),
        "start_time": _s(pair.get("start_time")),
        "end_time": _s(pair.get("end_time")),
        "subject_id": _i((it.get("subject") or {}).get("id")),
        "group_id": _i((it.get("group") or {}).get("id")),
        "employee_id": _i((it.get("employee") or {}).get("id")),
        "auditorium_code": _s((it.get("auditorium") or {}).get("code")),
        "faculty_id": _i((it.get("faculty") or {}).get("id")),
        "department_id": _i((it.get("department") or {}).get("id")),
        "training_type_code": _s((it.get("trainingType") or {}).get("code")),
        "semester_code": _s((it.get("semester") or {}).get("code")),
        "week_id": _i(it.get("_week")),
        "hemis_updated_at": (
            datetime.fromtimestamp(int(upstream_updated), UTC)
            if upstream_updated
            else None
        ),
        "created_at": stamp,
        "updated_at": stamp,
    }


async def sync_schedule(
    session: AsyncSession, stamp: datetime, *, since: datetime | None = None
) -> int:
    params: dict[str, Any] = {}
    if since is not None:
        params["updated_at_from"] = int(since.timestamp())
    items = await hemis.fetch_all("schedule-list", params)

    refs = _derive_refs(items, stamp)
    await _upsert(session, HemisSubject, refs["subjects"], ["id"])
    await _upsert(session, HemisEmployee, refs["employees"], ["id"])
    await _upsert(session, HemisAuditorium, refs["auditoriums"], ["code"])
    await _upsert(session, HemisLessonPair, refs["pairs"], ["code"])
    await _upsert(session, HemisTrainingType, refs["types"], ["code"])
    await _upsert(session, HemisSemester, refs["semesters"], ["code"])
    logger.info(
        "hemis_refs_derived",
        subjects=len(refs["subjects"]),
        employees=len(refs["employees"]),
        auditoriums=len(refs["auditoriums"]),
    )

    rows = [r for it in items if (r := _lesson_row(it, stamp)) and r["id"] is not None]
    written = await _upsert(session, HemisLesson, rows, ["id"])

    if since is None:
        # Full sweep: anything not touched by this run is gone upstream.
        # Guarded on a non-empty fetch so an upstream hiccup that returns zero
        # rows can never wipe the mirror.
        if rows:
            result = await session.execute(
                delete(HemisLesson).where(HemisLesson.updated_at < stamp)
            )
            removed = result.rowcount or 0
            if removed:
                logger.info("hemis_lessons_pruned", removed=removed)
        else:
            logger.warning("hemis_schedule_empty_skipping_prune")

    return written


# ── Orchestration ─────────────────────────────────────────────────────────────

SWEEPS = ("departments", "specialties", "groups", "schedule")


async def run_sync(*, since: datetime | None = None, only: str | None = None) -> int:
    """Returns a process exit code: 0 all good, 1 if any sweep failed."""
    if not hemis.is_configured():
        logger.error("hemis_not_configured", hint="set HEMIS_API_BASE and HEMIS_TOKEN")
        return 1

    sweeps = [only] if only else list(SWEEPS)
    failed = 0

    for name in sweeps:
        stamp = datetime.now(UTC)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await _mark(session, name, status="running", run_at=stamp)
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    if name == "departments":
                        count = await sync_departments(session, stamp)
                    elif name == "specialties":
                        count = await sync_specialties(session, stamp)
                    elif name == "groups":
                        count = await sync_groups(session, stamp)
                    elif name == "schedule":
                        count = await sync_schedule(session, stamp, since=since)
                    else:
                        raise ValueError(f"unknown sweep: {name}")
                    await _mark(session, name, status="ok", count=count, run_at=stamp)
            logger.info("hemis_sweep_ok", resource=name, count=count)
        except Exception as e:
            failed += 1
            logger.exception("hemis_sweep_failed", resource=name)
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await _mark(
                        session,
                        name,
                        status="error",
                        error=f"{type(e).__name__}: {e}",
                        run_at=stamp,
                    )

    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Mirror HEMIS into Postgres.")
    ap.add_argument(
        "--since-days",
        type=int,
        default=None,
        help=(
            "Incremental top-up: only rows changed in the last N days. Faster, "
            "but cannot see upstream deletions — cancelled classes linger. Omit "
            "for the correct full sweep."
        ),
    )
    ap.add_argument(
        "--only",
        choices=SWEEPS,
        default=None,
        help="Run a single sweep instead of all four.",
    )
    args = ap.parse_args()

    setup_logging()
    since = (
        datetime.now(UTC) - timedelta(days=args.since_days)
        if args.since_days is not None
        else None
    )
    return asyncio.run(run_sync(since=since, only=args.only))


if __name__ == "__main__":
    raise SystemExit(main())
