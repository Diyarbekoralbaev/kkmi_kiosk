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

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Header, Query

from ..core import schedule as schedule_q
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.timezone import today_local

router = APIRouter(prefix="/api/kiosk/schedule", tags=["kiosk:schedule"])

@router.get("/faculties")
async def faculties(
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    return {"items": await schedule_q.faculties(session)}


@router.get("/groups")
async def groups(
    session: DbSession,
    faculty_id: int | None = Query(default=None),
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    return {"items": await schedule_q.groups(session, faculty_id=faculty_id)}


@router.get("/lessons")
async def lessons(
    session: DbSession,
    group_id: int = Query(),
    scope: str = Query(default="today"),
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    if scope not in schedule_q.SCOPES:
        scope = "today"
    day_from, day_to = await schedule_q.scope_range(session, group_id, scope)
    items = await schedule_q.lessons_for_group(session, group_id, day_from, day_to)

    empty_reason = ""
    if not items:
        # "Free day" and "the academic year isn't loaded" look identical on
        # screen but need opposite explanations — and over the summer break the
        # second is the normal case, so it must not read as a broken kiosk.
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
