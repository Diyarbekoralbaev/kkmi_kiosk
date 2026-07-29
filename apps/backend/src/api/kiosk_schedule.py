"""Kiosk touch-flow reads over the HEMIS mirror.

The voice flow gets this data through tool calls on the WS; the touch flow needs
the same data over plain HTTP so a visitor can drill down faculty → group →
timetable without saying a word. Both read the same mirror, so the two surfaces
can never disagree.

Read-only and device-authenticated. Nothing here is per-visitor: group
timetables and degree programmes are public information, which is exactly why
the kiosk can show them without identifying anyone.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Header, Query

from ..core import schedule as schedule_q
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import NotFoundError
from ..core.timezone import today_local

router = APIRouter(prefix="/api/kiosk/schedule", tags=["kiosk:schedule"])

@router.get("/faculties")
async def faculties(
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    return {"items": await schedule_q.faculties(session)}


@router.get("/courses")
async def courses(
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    """Bachelor courses 1-6 with group counts — the first drill-down step."""
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    return {"items": await schedule_q.courses(session)}


@router.get("/groups")
async def groups(
    session: DbSession,
    faculty_id: int | None = Query(default=None),
    course: int | None = Query(default=None, ge=1, le=6),
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    return {
        "items": await schedule_q.groups(
            session, faculty_id=faculty_id, course=course
        )
    }


@router.get("/week")
async def week(
    session: DbSession,
    group_id: int = Query(),
    on_date: date | None = Query(default=None, alias="date"),
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    """A group's whole week: per-day counts for the strip, plus every lesson.

    Falls back to the group's last taught week when no date is given, for the
    same reason the page does — over the summer break the current week is empty
    for every group in the institute.
    """
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    if on_date is None:
        start, _ = await schedule_q.scope_range(
            session, group_id, "last_taught_week"
        )
        on_date = start
    return await schedule_q.week_for_group(session, group_id, on_date)


@router.get("/lessons")
async def lessons(
    session: DbSession,
    group_id: int = Query(),
    scope: str = Query(default="today"),
    on_date: date | None = Query(default=None, alias="date"),
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    if scope not in schedule_q.SCOPES:
        scope = "today"
    # `date`/`week_of` are meaningless without a day to anchor them; rather than
    # 422 on a malformed URL the kiosk built, fall back to the scope that needs
    # no anchor. A visitor gets today's timetable instead of an error screen.
    if scope in ("date", "week_of") and on_date is None:
        scope = "today"
    day_from, day_to = await schedule_q.scope_range(session, group_id, scope, on_date)
    items = await schedule_q.lessons_for_group(session, group_id, day_from, day_to)

    empty_reason = ""
    if not items:
        # Three different situations render as the same blank list and need
        # three different sentences: a free day, a group HEMIS has never
        # published a timetable for (703 of 946), and the summer gap before the
        # next year is loaded. Only the last one is worth telling a visitor to
        # come back for.
        if not await schedule_q.has_any_lessons(session, group_id):
            empty_reason = "group_has_no_schedule"
        else:
            today = today_local()
            upcoming = await schedule_q.lessons_for_group(
                session, group_id, today, today + timedelta(days=365)
            )
            empty_reason = "no_lessons_that_day" if upcoming else "year_not_published"

    return {
        "group": await schedule_q.group_by_id(session, group_id),
        "scope": scope,
        "lessons": items,
        "empty_reason": empty_reason,
    }


@router.get("/directions")
async def directions(
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    """Degree programmes for the applicants menu."""
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    return {"items": await schedule_q.specialties(session)}


@router.get("/directions/{specialty_id}")
async def direction_detail(
    specialty_id: int,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    """One programme, including the subjects it is actually taught through."""
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    item = await schedule_q.specialty_detail(session, specialty_id)
    if item is None:
        raise NotFoundError()
    return {"item": item}
