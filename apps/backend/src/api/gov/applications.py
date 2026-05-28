"""Gov: applications list, detail, status transitions, assignment.

Permissions:
- org_admin sees ALL the org's applications and can change anything.
- reviewer sees ONLY rows where assigned_user_id == their user id and can
  only transition the status to `resolved` or `returned` (i.e. the two
  end-states of their workflow). All other admin actions raise 403.

Reviewer scoping is enforced inside each handler — `OrgMember` lets both
roles in, then we branch on `is_reviewer(user)` to filter the SQL and to
gate the patch payload.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from ...core import audit
from ...core.deps import (
    CurrentOrgAnyMember,
    DbSession,
    OrgMember,
    is_reviewer,
)
from ...core.errors import NotFoundError, PermissionDeniedError, ValidationError
from ...domain.application import (
    ALL_STATUSES,
    ALLOWED_TRANSITIONS,
    STATUS_RESOLVED,
    STATUS_RETURNED,
    Application,
)
from ...domain.category import ApplicationCategory
from ...domain.user import ROLE_REVIEWER, User

router = APIRouter(prefix="/api/gov/applications", tags=["gov:applications"])


REVIEWER_TARGET_STATUSES: set[str] = {STATUS_RESOLVED, STATUS_RETURNED}
"""Statuses a reviewer is allowed to PATCH to. Anything outside this set
(re-opening, archiving, etc.) is admin-only."""


class ApplicationOut(BaseModel):
    id: str
    topic: str
    body: str
    phone: str
    status: str
    kind: str
    feedback_type: str | None
    session_id: str | None
    category_id: str | None
    category_slug: str | None
    assigned_user_id: str | None
    resolved_at: str | None
    resolution_note: str
    created_at: str
    updated_at: str


class ApplicationListOut(BaseModel):
    items: list[ApplicationOut]
    total: int


class ApplicationUpdateIn(BaseModel):
    status: str | None = None
    assigned_user_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    resolution_note: str | None = Field(default=None, max_length=10_000)

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ALL_STATUSES:
            raise ValueError("invalid status")
        return v


def _to_out(a: Application, slug_lookup: dict[uuid.UUID, str]) -> ApplicationOut:
    return ApplicationOut(
        id=str(a.id),
        topic=a.topic,
        body=a.body,
        phone=a.phone,
        status=a.status,
        kind=a.kind,
        feedback_type=a.feedback_type,
        session_id=str(a.session_id) if a.session_id else None,
        category_id=str(a.category_id) if a.category_id else None,
        category_slug=slug_lookup.get(a.category_id) if a.category_id else None,
        assigned_user_id=str(a.assigned_user_id) if a.assigned_user_id else None,
        resolved_at=a.resolved_at.isoformat() if a.resolved_at else None,
        resolution_note=a.resolution_note,
        created_at=a.created_at.isoformat(),
        updated_at=a.updated_at.isoformat(),
    )


async def _slug_lookup(session) -> dict[uuid.UUID, str]:
    """One round-trip mapping id → slug so the list/detail response can
    inline `category_slug` without N+1 selects. Cheap (~10 rows)."""
    rows = (
        await session.execute(
            select(ApplicationCategory.id, ApplicationCategory.slug)
        )
    ).all()
    return {row[0]: row[1] for row in rows}


@router.get("", response_model=ApplicationListOut)
async def list_applications(
    session: DbSession,
    user: OrgMember,
    org: CurrentOrgAnyMember,
    status_filter: str | None = Query(default=None, alias="status"),
    kind: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=255),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    category_id: uuid.UUID | None = Query(default=None),
    assigned_user_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ApplicationListOut:
    stmt = select(Application).where(Application.org_id == org.id)
    cstmt = (
        select(func.count()).select_from(Application).where(Application.org_id == org.id)
    )
    if is_reviewer(user):
        # Reviewers only see their own assignments.
        stmt = stmt.where(Application.assigned_user_id == user.id)
        cstmt = cstmt.where(Application.assigned_user_id == user.id)
    elif assigned_user_id is not None:
        stmt = stmt.where(Application.assigned_user_id == assigned_user_id)
        cstmt = cstmt.where(Application.assigned_user_id == assigned_user_id)
    if status_filter:
        stmt = stmt.where(Application.status == status_filter)
        cstmt = cstmt.where(Application.status == status_filter)
    if kind:
        stmt = stmt.where(Application.kind == kind)
        cstmt = cstmt.where(Application.kind == kind)
    if search:
        like = f"%{search.lower()}%"
        cond = or_(
            func.lower(Application.topic).like(like),
            func.lower(Application.body).like(like),
            Application.phone.like(f"%{search}%"),
        )
        stmt = stmt.where(cond)
        cstmt = cstmt.where(cond)
    if since:
        stmt = stmt.where(Application.created_at >= since)
        cstmt = cstmt.where(Application.created_at >= since)
    if until:
        stmt = stmt.where(Application.created_at <= until)
        cstmt = cstmt.where(Application.created_at <= until)
    if category_id is not None:
        stmt = stmt.where(Application.category_id == category_id)
        cstmt = cstmt.where(Application.category_id == category_id)
    stmt = stmt.order_by(Application.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(cstmt)).scalar_one()
    slugs = await _slug_lookup(session)
    return ApplicationListOut(
        items=[_to_out(a, slugs) for a in rows], total=int(total)
    )


@router.get("/{app_id}", response_model=ApplicationOut)
async def get_application(
    app_id: uuid.UUID,
    session: DbSession,
    user: OrgMember,
    org: CurrentOrgAnyMember,
) -> ApplicationOut:
    a = (
        await session.execute(
            select(Application).where(
                Application.id == app_id, Application.org_id == org.id
            )
        )
    ).scalar_one_or_none()
    if a is None:
        raise NotFoundError()
    if is_reviewer(user) and a.assigned_user_id != user.id:
        # Reviewer can't peek at unassigned items.
        raise NotFoundError()
    slugs = await _slug_lookup(session)
    return _to_out(a, slugs)


@router.patch("/{app_id}", response_model=ApplicationOut)
async def update_application(
    app_id: uuid.UUID,
    payload: ApplicationUpdateIn,
    session: DbSession,
    user: OrgMember,
    org: CurrentOrgAnyMember,
    request: Request,
) -> ApplicationOut:
    a = (
        await session.execute(
            select(Application).where(
                Application.id == app_id, Application.org_id == org.id
            )
        )
    ).scalar_one_or_none()
    if a is None:
        raise NotFoundError()

    reviewer = is_reviewer(user)
    if reviewer:
        # Hard guards on reviewer permissions:
        # 1. Can only touch their own assignments.
        if a.assigned_user_id != user.id:
            raise PermissionDeniedError("not_assigned_to_you")
        # 2. Can't re-assign or change category — that's admin work.
        if payload.assigned_user_id is not None:
            raise PermissionDeniedError("reviewer_cannot_reassign")
        if payload.category_id is not None:
            raise PermissionDeniedError("reviewer_cannot_recategorize")
        # 3. Status transitions limited to resolved/returned.
        if (
            payload.status is not None
            and payload.status != a.status
            and payload.status not in REVIEWER_TARGET_STATUSES
        ):
            raise PermissionDeniedError("reviewer_status_restricted")

    before: dict[str, Any] = {
        "status": a.status,
        "assigned_user_id": str(a.assigned_user_id) if a.assigned_user_id else None,
        "category_id": str(a.category_id) if a.category_id else None,
        "resolution_note": a.resolution_note,
    }

    if payload.status is not None and payload.status != a.status:
        allowed = ALLOWED_TRANSITIONS.get(a.status, set())
        if payload.status not in allowed:
            raise ValidationError(
                f"cannot transition from {a.status} to {payload.status}"
            )
        a.status = payload.status
        if payload.status == STATUS_RESOLVED:
            a.resolved_at = datetime.now(UTC)

    if payload.assigned_user_id is not None:
        # Verify the assignee belongs to this org. Reviewers AND admins
        # are both valid assignees (admin can assign to themselves to
        # take ownership of an issue).
        assignee = (
            await session.execute(
                select(User).where(
                    User.id == payload.assigned_user_id, User.org_id == org.id
                )
            )
        ).scalar_one_or_none()
        if assignee is None:
            raise ValidationError("assignee_not_in_org")
        if assignee.role not in (ROLE_REVIEWER, "org_admin"):
            raise ValidationError("assignee_invalid_role")
        a.assigned_user_id = payload.assigned_user_id

    if payload.category_id is not None:
        cat = (
            await session.execute(
                select(ApplicationCategory).where(
                    ApplicationCategory.id == payload.category_id,
                    ApplicationCategory.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if cat is None:
            raise ValidationError("category_not_found")
        a.category_id = cat.id

    if payload.resolution_note is not None:
        a.resolution_note = payload.resolution_note

    after = {
        "status": a.status,
        "assigned_user_id": str(a.assigned_user_id) if a.assigned_user_id else None,
        "category_id": str(a.category_id) if a.category_id else None,
        "resolution_note": a.resolution_note,
    }
    await audit.record(
        session,
        actor_user_id=user.id,
        actor_org_id=org.id,
        action="application.update",
        entity_type="application",
        entity_id=a.id,
        before=before,
        after=after,
        request=request,
    )
    slugs = await _slug_lookup(session)
    return _to_out(a, slugs)
