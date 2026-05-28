"""Gov: qabul (appointment) list, detail, status transitions, assignment, outcome.

Mirrors the application API's permission model:
- org_admin sees ALL the org's appointments and can change anything,
  including assigning a reviewer to handle the in-person reception.
- reviewer sees ONLY their assigned appointments and can record the
  outcome (`result_note`) + transition status to completed/no_show.

The reviewer cannot re-assign, cancel, or re-open a completed appointment —
those are admin-only.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from ...ai.appointments import build_verify_url, mask_phone, reference_no
from ...core import audit
from ...core.deps import (
    CurrentOrgAnyMember,
    DbSession,
    OrgMember,
    is_reviewer,
)
from ...core.errors import NotFoundError, PermissionDeniedError, ValidationError
from ...domain.appointment import (
    ALL_STATUSES,
    ALLOWED_TRANSITIONS,
    STATUS_COMPLETED,
    STATUS_NO_SHOW,
    Appointment,
)
from ...domain.user import ROLE_REVIEWER, User

router = APIRouter(prefix="/api/gov/appointments", tags=["gov:appointments"])


REVIEWER_TARGET_STATUSES: set[str] = {STATUS_COMPLETED, STATUS_NO_SHOW}
"""Statuses a reviewer can transition the appointment to. Cancellation is
admin-only (it's a public-facing decision)."""


class AppointmentOut(BaseModel):
    id: str
    visitor_phone: str
    visitor_phone_masked: str
    topic_summary: str
    reference_no: str
    status: str
    source: str
    session_id: str | None
    verification_url: str
    assigned_user_id: str | None
    assigned_at: str | None
    result_note: str
    created_at: str
    updated_at: str


class AppointmentListOut(BaseModel):
    items: list[AppointmentOut]
    total: int


class AppointmentUpdateIn(BaseModel):
    status: str | None = None
    assigned_user_id: uuid.UUID | None = None
    result_note: str | None = Field(default=None, max_length=10_000)

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ALL_STATUSES:
            raise ValueError("invalid status")
        return v


def _to_out(a: Appointment) -> AppointmentOut:
    return AppointmentOut(
        id=str(a.id),
        visitor_phone=a.visitor_phone,
        visitor_phone_masked=mask_phone(a.visitor_phone),
        topic_summary=a.topic_summary,
        reference_no=reference_no(a),
        status=a.status,
        source=a.source,
        session_id=str(a.session_id) if a.session_id else None,
        verification_url=build_verify_url(a.verification_token),
        assigned_user_id=str(a.assigned_user_id) if a.assigned_user_id else None,
        assigned_at=a.assigned_at.isoformat() if a.assigned_at else None,
        result_note=a.result_note,
        created_at=a.created_at.isoformat(),
        updated_at=a.updated_at.isoformat(),
    )


@router.get("", response_model=AppointmentListOut)
async def list_appointments(
    session: DbSession,
    user: OrgMember,
    org: CurrentOrgAnyMember,
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=255),
    assigned_user_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AppointmentListOut:
    stmt = select(Appointment).where(Appointment.org_id == org.id)
    cstmt = (
        select(func.count())
        .select_from(Appointment)
        .where(Appointment.org_id == org.id)
    )
    if is_reviewer(user):
        stmt = stmt.where(Appointment.assigned_user_id == user.id)
        cstmt = cstmt.where(Appointment.assigned_user_id == user.id)
    elif assigned_user_id is not None:
        stmt = stmt.where(Appointment.assigned_user_id == assigned_user_id)
        cstmt = cstmt.where(Appointment.assigned_user_id == assigned_user_id)
    if status_filter:
        stmt = stmt.where(Appointment.status == status_filter)
        cstmt = cstmt.where(Appointment.status == status_filter)
    if search:
        like = f"%{search}%"
        cond = or_(
            Appointment.visitor_phone.like(like),
            func.lower(Appointment.topic_summary).like(f"%{search.lower()}%"),
        )
        stmt = stmt.where(cond)
        cstmt = cstmt.where(cond)

    stmt = stmt.order_by(Appointment.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(cstmt)).scalar_one()
    return AppointmentListOut(
        items=[_to_out(a) for a in rows],
        total=int(total),
    )


@router.get("/{appt_id}", response_model=AppointmentOut)
async def get_appointment(
    appt_id: uuid.UUID,
    session: DbSession,
    user: OrgMember,
    org: CurrentOrgAnyMember,
) -> AppointmentOut:
    a = (
        await session.execute(
            select(Appointment).where(
                Appointment.id == appt_id, Appointment.org_id == org.id
            )
        )
    ).scalar_one_or_none()
    if a is None:
        raise NotFoundError()
    if is_reviewer(user) and a.assigned_user_id != user.id:
        raise NotFoundError()
    return _to_out(a)


@router.patch("/{appt_id}", response_model=AppointmentOut)
async def update_appointment(
    appt_id: uuid.UUID,
    payload: AppointmentUpdateIn,
    session: DbSession,
    user: OrgMember,
    org: CurrentOrgAnyMember,
    request: Request,
) -> AppointmentOut:
    a = (
        await session.execute(
            select(Appointment).where(
                Appointment.id == appt_id, Appointment.org_id == org.id
            )
        )
    ).scalar_one_or_none()
    if a is None:
        raise NotFoundError()

    reviewer = is_reviewer(user)
    if reviewer:
        if a.assigned_user_id != user.id:
            raise PermissionDeniedError("not_assigned_to_you")
        if payload.assigned_user_id is not None:
            raise PermissionDeniedError("reviewer_cannot_reassign")
        if (
            payload.status is not None
            and payload.status != a.status
            and payload.status not in REVIEWER_TARGET_STATUSES
        ):
            raise PermissionDeniedError("reviewer_status_restricted")

    before: dict[str, Any] = {
        "status": a.status,
        "assigned_user_id": str(a.assigned_user_id) if a.assigned_user_id else None,
        "result_note": a.result_note,
    }

    if payload.status is not None and payload.status != a.status:
        allowed = ALLOWED_TRANSITIONS.get(a.status, set())
        if payload.status not in allowed:
            raise ValidationError(
                f"cannot transition from {a.status} to {payload.status}"
            )
        a.status = payload.status

    if payload.assigned_user_id is not None:
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
        if a.assigned_user_id != payload.assigned_user_id:
            a.assigned_user_id = payload.assigned_user_id
            a.assigned_at = datetime.now(UTC)

    if payload.result_note is not None:
        a.result_note = payload.result_note

    after = {
        "status": a.status,
        "assigned_user_id": str(a.assigned_user_id) if a.assigned_user_id else None,
        "result_note": a.result_note,
    }
    await audit.record(
        session,
        actor_user_id=user.id,
        actor_org_id=org.id,
        action="appointment.update",
        entity_type="appointment",
        entity_id=a.id,
        before=before,
        after=after,
        request=request,
    )
    return _to_out(a)
