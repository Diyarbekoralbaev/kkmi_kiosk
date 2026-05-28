"""Audit log writer — every write endpoint calls `record(...)`.

Audit writes commit on a SEPARATE transaction so they survive request rollbacks
(e.g. failed-login audits must persist even though the response is 401 and the
request session rolls back). Pass `session=None` to use the independent path,
or pass an existing session to inline the audit row in the same transaction
(useful when you want both the entity write and the audit row to commit/rollback
together — e.g., creating an org).
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.audit import AuditLog
from .db import AsyncSessionLocal

logger = structlog.get_logger(__name__)


def _client_meta(request: Request | None) -> tuple[str, str]:
    if request is None:
        return "", ""
    ip = ""
    if request.client:
        ip = request.client.host
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    ua = request.headers.get("user-agent", "")[:255]
    return ip, ua


async def record(
    session: AsyncSession | None,
    *,
    actor_user_id: uuid.UUID | None,
    actor_org_id: uuid.UUID | None,
    action: str,
    entity_type: str = "",
    entity_id: str | uuid.UUID = "",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Write one audit row.

    If `session` is provided, the row is added to that session (will commit/rollback
    with the surrounding transaction).

    For audit-on-failure paths (e.g. failed login) callers should set
    `commit_independently=True` via `record_independent(...)`.
    """
    ip, ua = _client_meta(request)
    entry = AuditLog(
        actor_user_id=actor_user_id,
        actor_org_id=actor_org_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else "",
        before=before,
        after=after,
        ip_address=ip,
        user_agent=ua,
    )
    if session is not None:
        session.add(entry)
        await session.flush()
        return
    # Independent transaction — caller wants this row to persist even if their
    # request transaction rolls back.
    try:
        async with AsyncSessionLocal() as s:
            async with s.begin():
                s.add(entry)
    except Exception:
        logger.exception("audit_independent_write_failed", action=action)


async def record_independent(
    *,
    actor_user_id: uuid.UUID | None,
    actor_org_id: uuid.UUID | None,
    action: str,
    entity_type: str = "",
    entity_id: str | uuid.UUID = "",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Audit row that commits in its own transaction. Use for failure paths."""
    await record(
        None,
        actor_user_id=actor_user_id,
        actor_org_id=actor_org_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        request=request,
    )
