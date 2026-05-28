"""Gov admin: voice sessions list + detail."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from ...core.deps import CurrentOrg, DbSession, OrgAdmin
from ...core.errors import NotFoundError
from ...domain.session import VoiceSession

router = APIRouter(prefix="/api/gov/sessions", tags=["gov:sessions"])


class SessionOut(BaseModel):
    id: str
    call_id: str
    started_at: str
    ended_at: str | None
    duration_seconds: int | None
    transcript: str
    error_code: str | None
    provider: str
    model: str | None


class SessionListOut(BaseModel):
    items: list[SessionOut]
    total: int


def _to_out(s: VoiceSession) -> SessionOut:
    return SessionOut(
        id=str(s.id),
        call_id=s.call_id,
        started_at=s.started_at.isoformat(),
        ended_at=s.ended_at.isoformat() if s.ended_at else None,
        duration_seconds=s.duration_seconds,
        transcript=s.transcript,
        error_code=s.error_code,
        provider=s.provider,
        model=s.model,
    )


@router.get("", response_model=SessionListOut)
async def list_sessions(
    session: DbSession,
    _: OrgAdmin,
    org: CurrentOrg,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> SessionListOut:
    stmt = select(VoiceSession).where(VoiceSession.org_id == org.id)
    cstmt = (
        select(func.count())
        .select_from(VoiceSession)
        .where(VoiceSession.org_id == org.id)
    )
    if since:
        stmt = stmt.where(VoiceSession.started_at >= since)
        cstmt = cstmt.where(VoiceSession.started_at >= since)
    if until:
        stmt = stmt.where(VoiceSession.started_at <= until)
        cstmt = cstmt.where(VoiceSession.started_at <= until)
    stmt = stmt.order_by(VoiceSession.started_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(cstmt)).scalar_one()
    return SessionListOut(items=[_to_out(s) for s in rows], total=int(total))


@router.get("/{session_id}", response_model=SessionOut)
async def get_session_detail(
    session_id: uuid.UUID, session: DbSession, _: OrgAdmin, org: CurrentOrg
) -> SessionOut:
    row = (
        await session.execute(
            select(VoiceSession).where(
                VoiceSession.id == session_id, VoiceSession.org_id == org.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError()
    return _to_out(row)
