"""Gov: org staff management (org_admin + reviewer users).

Reviewers are created here too — distinguished by `role` on POST. The
gov-panel calls `?role=reviewer` to populate the "assign to" dropdown
on murajat/qabul detail pages.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select

from ...core import audit
from ...core.deps import CurrentOrg, DbSession, OrgAdmin
from ...core.errors import ConflictError, NotFoundError, PermissionDeniedError
from ...core.security import hash_password, random_password
from ...domain.user import (
    ORG_ROLES,
    ROLE_ORG_ADMIN,
    ROLE_REVIEWER,
    User,
)

router = APIRouter(prefix="/api/gov/staff", tags=["gov:staff"])


class StaffOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    status: str
    totp_enabled: bool
    last_login_at: str | None
    created_at: str


class StaffListOut(BaseModel):
    items: list[StaffOut]
    total: int


class StaffCreateIn(BaseModel):
    email: EmailStr
    full_name: str = Field(default="", max_length=255)
    role: str = Field(default=ROLE_ORG_ADMIN)

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        # Only org-level roles can be assigned via this endpoint; super_admin
        # is created out-of-band from env bootstrap.
        if v not in ORG_ROLES:
            raise ValueError("role must be org_admin or reviewer")
        return v


class StaffUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    status: str | None = None
    role: str | None = None

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ("active", "disabled"):
            raise ValueError("status must be active or disabled")
        return v

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ORG_ROLES:
            raise ValueError("role must be org_admin or reviewer")
        return v


class StaffCreatedOut(StaffOut):
    temp_password: str


class PasswordResetOut(BaseModel):
    temp_password: str


def _to_out(u: User) -> StaffOut:
    return StaffOut(
        id=str(u.id),
        email=u.email,
        full_name=u.full_name,
        role=u.role,
        status=u.status,
        totp_enabled=u.totp_enabled,
        last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
        created_at=u.created_at.isoformat(),
    )


@router.get("", response_model=StaffListOut)
async def list_staff(
    session: DbSession,
    _: OrgAdmin,
    org: CurrentOrg,
    role: str | None = Query(default=None),
) -> StaffListOut:
    stmt = select(User).where(User.org_id == org.id)
    cstmt = select(func.count()).select_from(User).where(User.org_id == org.id)
    if role is not None:
        if role not in ORG_ROLES:
            return StaffListOut(items=[], total=0)
        stmt = stmt.where(User.role == role)
        cstmt = cstmt.where(User.role == role)
    rows = (
        await session.execute(stmt.order_by(User.created_at.desc()))
    ).scalars().all()
    total = (await session.execute(cstmt)).scalar_one()
    return StaffListOut(items=[_to_out(u) for u in rows], total=int(total))


@router.post("", response_model=StaffCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_staff(
    payload: StaffCreateIn,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
) -> StaffCreatedOut:
    existing = (
        await session.execute(select(User).where(User.email == str(payload.email)))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("email_taken")
    temp = random_password(length=16)
    user = User(
        email=str(payload.email),
        password_hash=hash_password(temp),
        full_name=payload.full_name,
        role=payload.role,
        org_id=org.id,
        status="active",
        password_must_change=True,
    )
    session.add(user)
    await session.flush()
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="staff.create",
        entity_type="user",
        entity_id=user.id,
        after={"email": user.email, "role": user.role},
        request=request,
    )
    return StaffCreatedOut(**_to_out(user).model_dump(), temp_password=temp)


def _ensure_org_member(target: User | None, org_id: uuid.UUID) -> User:
    if target is None or target.org_id != org_id:
        raise NotFoundError()
    return target


@router.patch("/{user_id}", response_model=StaffOut)
async def update_staff(
    user_id: uuid.UUID,
    payload: StaffUpdateIn,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
) -> StaffOut:
    target = _ensure_org_member(
        (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none(),
        org.id,
    )
    if target.id == actor.id and payload.status == "disabled":
        raise PermissionDeniedError("cannot_disable_self")
    if target.id == actor.id and payload.role is not None and payload.role != target.role:
        # Admins can't demote themselves and lose access to the panel.
        raise PermissionDeniedError("cannot_change_own_role")
    before: dict[str, Any] = {
        "full_name": target.full_name,
        "status": target.status,
        "role": target.role,
    }
    if payload.full_name is not None:
        target.full_name = payload.full_name
    if payload.status is not None:
        target.status = payload.status
    if payload.role is not None:
        target.role = payload.role
    after = {
        "full_name": target.full_name,
        "status": target.status,
        "role": target.role,
    }
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="staff.update",
        entity_type="user",
        entity_id=target.id,
        before=before,
        after=after,
        request=request,
    )
    return _to_out(target)


@router.post("/{user_id}/password/reset", response_model=PasswordResetOut)
async def reset_staff_password(
    user_id: uuid.UUID,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
) -> PasswordResetOut:
    target = _ensure_org_member(
        (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none(),
        org.id,
    )
    temp = random_password(length=16)
    target.password_hash = hash_password(temp)
    target.password_must_change = True
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="staff.password_reset",
        entity_type="user",
        entity_id=target.id,
        request=request,
    )
    return PasswordResetOut(temp_password=temp)
