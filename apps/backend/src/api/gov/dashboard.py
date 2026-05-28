"""Gov admin: dashboard KPI."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from ...core.deps import CurrentOrg, DbSession, OrgAdmin
from ...domain.application import (
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    STATUS_RESOLVED,
    Application,
)
from ...domain.session import VoiceSession

router = APIRouter(prefix="/api/gov/dashboard", tags=["gov:dashboard"])


class DashboardOut(BaseModel):
    today_applications: int
    today_sessions: int
    pending_count: int
    in_progress_count: int
    resolved_this_week: int
    avg_session_seconds: float
    recent_applications: list[dict]
    recent_sessions: list[dict]


@router.get("", response_model=DashboardOut)
async def dashboard(
    session: DbSession, _: OrgAdmin, org: CurrentOrg
) -> DashboardOut:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)

    today_apps = (
        await session.execute(
            select(func.count())
            .select_from(Application)
            .where(Application.org_id == org.id, Application.created_at >= today)
        )
    ).scalar_one()

    today_sessions = (
        await session.execute(
            select(func.count())
            .select_from(VoiceSession)
            .where(VoiceSession.org_id == org.id, VoiceSession.started_at >= today)
        )
    ).scalar_one()

    pending = (
        await session.execute(
            select(func.count())
            .select_from(Application)
            .where(Application.org_id == org.id, Application.status == STATUS_NEW)
        )
    ).scalar_one()
    in_progress = (
        await session.execute(
            select(func.count())
            .select_from(Application)
            .where(
                Application.org_id == org.id, Application.status == STATUS_IN_PROGRESS
            )
        )
    ).scalar_one()
    resolved_week = (
        await session.execute(
            select(func.count())
            .select_from(Application)
            .where(
                Application.org_id == org.id,
                Application.status == STATUS_RESOLVED,
                Application.resolved_at >= week_ago,
            )
        )
    ).scalar_one()

    avg_dur = (
        await session.execute(
            select(func.coalesce(func.avg(VoiceSession.duration_seconds), 0))
            .where(
                VoiceSession.org_id == org.id,
                VoiceSession.started_at >= today,
                VoiceSession.duration_seconds.is_not(None),
            )
        )
    ).scalar_one()

    recent_apps = (
        await session.execute(
            select(Application)
            .where(Application.org_id == org.id)
            .order_by(Application.created_at.desc())
            .limit(5)
        )
    ).scalars().all()

    recent_sess = (
        await session.execute(
            select(VoiceSession)
            .where(VoiceSession.org_id == org.id)
            .order_by(VoiceSession.started_at.desc())
            .limit(5)
        )
    ).scalars().all()

    return DashboardOut(
        today_applications=int(today_apps),
        today_sessions=int(today_sessions),
        pending_count=int(pending),
        in_progress_count=int(in_progress),
        resolved_this_week=int(resolved_week),
        avg_session_seconds=float(avg_dur or 0.0),
        recent_applications=[
            {
                "id": str(a.id),
                "topic": a.topic,
                "status": a.status,
                "phone": a.phone,
                "created_at": a.created_at.isoformat(),
            }
            for a in recent_apps
        ],
        recent_sessions=[
            {
                "id": str(s.id),
                "call_id": s.call_id,
                "started_at": s.started_at.isoformat(),
                "duration_seconds": s.duration_seconds,
            }
            for s in recent_sess
        ],
    )
