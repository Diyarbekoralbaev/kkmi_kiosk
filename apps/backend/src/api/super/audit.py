"""Super admin: read audit log."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from ...core.deps import DbSession, SuperAdmin
from ...domain.audit import AuditLog

router = APIRouter(prefix="/api/super/audit", tags=["super:audit"])


class AuditOut(BaseModel):
    id: str
    actor_user_id: str | None
    actor_org_id: str | None
    action: str
    entity_type: str
    entity_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip_address: str
    user_agent: str
    created_at: str


class AuditListOut(BaseModel):
    items: list[AuditOut]
    total: int


@router.get("", response_model=AuditListOut)
async def list_audit(
    session: DbSession,
    _: SuperAdmin,
    actor_user_id: uuid.UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AuditListOut:
    stmt = select(AuditLog)
    cstmt = select(func.count()).select_from(AuditLog)
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
        cstmt = cstmt.where(AuditLog.actor_user_id == actor_user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
        cstmt = cstmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
        cstmt = cstmt.where(AuditLog.entity_type == entity_type)
    if since:
        stmt = stmt.where(AuditLog.created_at >= since)
        cstmt = cstmt.where(AuditLog.created_at >= since)
    if until:
        stmt = stmt.where(AuditLog.created_at <= until)
        cstmt = cstmt.where(AuditLog.created_at <= until)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(cstmt)).scalar_one()
    items = [
        AuditOut(
            id=str(r.id),
            actor_user_id=str(r.actor_user_id) if r.actor_user_id else None,
            actor_org_id=str(r.actor_org_id) if r.actor_org_id else None,
            action=r.action,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            before=r.before,
            after=r.after,
            ip_address=r.ip_address,
            user_agent=r.user_agent,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
    return AuditListOut(items=items, total=int(total))
