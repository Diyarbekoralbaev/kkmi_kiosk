"""HEMIS mirror status for the gov panel.

Staff need to know whether the timetable on the kiosk is current. Without this
a stale mirror is invisible: the kiosk keeps answering confidently from
week-old data and nobody finds out until a student is sent to a cancelled
class.

Read-only. The sync itself runs as a nightly job (`python -m src.hemis_sync`),
deliberately not triggerable from here — a sweep takes ~95 s against the
institute's live API and a button would invite someone to hammer it.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from ...core.deps import DbSession, OrgAdmin
from ...domain.hemis import (
    HemisGroup,
    HemisLesson,
    HemisSpecialty,
    HemisSyncState,
)

router = APIRouter(prefix="/api/gov/hemis", tags=["gov:hemis"])


class SyncStateOut(BaseModel):
    resource: str
    status: str
    item_count: int
    error: str
    last_run_at: str | None


class HemisStatusOut(BaseModel):
    sweeps: list[SyncStateOut]
    counts: dict[str, int]
    """Row counts of the mirrored tables — the quickest "is there data at all"
    signal when a sweep reports ok but wrote nothing."""


@router.get("", response_model=HemisStatusOut)
async def hemis_status(session: DbSession, _admin: OrgAdmin) -> HemisStatusOut:
    rows = (
        await session.execute(
            select(HemisSyncState).order_by(HemisSyncState.resource)
        )
    ).scalars()

    counts: dict[str, Any] = {}
    for label, model in (
        ("lessons", HemisLesson),
        ("groups", HemisGroup),
        ("specialties", HemisSpecialty),
    ):
        counts[label] = (
            await session.execute(select(func.count()).select_from(model))
        ).scalar() or 0

    return HemisStatusOut(
        sweeps=[
            SyncStateOut(
                resource=r.resource,
                status=r.status,
                item_count=r.item_count,
                error=r.error,
                last_run_at=r.last_run_at.isoformat() if r.last_run_at else None,
            )
            for r in rows
        ],
        counts=counts,
    )
