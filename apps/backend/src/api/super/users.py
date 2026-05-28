"""Super admin: users management."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select

from ...core import audit
from ...core.deps import DbSession, SuperAdmin
from ...core.errors import ConflictError, NotFoundError, ValidationError
from ...core.security import hash_password, random_password
from ...domain.user import ALL_ROLES, ROLE_ORG_ADMIN, ROLE_SUPER_ADMIN, User

router = APIRouter(prefix="/api/super/users", tags=["super:users"])


class UserCreateIn(BaseModel):
    email: EmailStr
    full_name: str = Field(default="", max_length=255)
    role: str
    org_id: uuid.UUID | None = None

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        if v not in ALL_ROLES:
            raise ValueError(f"role must be one of {ALL_ROLES}")
        return v


class UserUpdateIn(BaseModel):
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
        if v not in ALL_ROLES:
            raise ValueError(f"role must be one of {ALL_ROLES}")
        return v


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    org_id: str | None
    status: str
    totp_enabled: bool
    password_must_change: bool
    last_login_at: str | None
    created_at: str


class UserCreatedOut(UserOut):
    temp_password: str


class UserListOut(BaseModel):
    items: list[UserOut]
    total: int


def _to_out(u: User) -> UserOut:
    return UserOut(
        id=str(u.id),
        email=u.email,
        full_name=u.full_name,
        role=u.role,
        org_id=str(u.org_id) if u.org_id else None,
        status=u.status,
        totp_enabled=u.totp_enabled,
        password_must_change=u.password_must_change,
        last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
        created_at=u.created_at.isoformat(),
    )


@router.get("", response_model=UserListOut)
async def list_users(
    session: DbSession,
    _: SuperAdmin,
    role: str | None = Query(default=None),
    org_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> UserListOut:
    stmt = select(User)
    cstmt = select(func.count()).select_from(User)
    if role:
        stmt = stmt.where(User.role == role)
        cstmt = cstmt.where(User.role == role)
    if org_id:
        stmt = stmt.where(User.org_id == org_id)
        cstmt = cstmt.where(User.org_id == org_id)
    stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(cstmt)).scalar_one()
    return UserListOut(items=[_to_out(u) for u in rows], total=int(total))


@router.post("", response_model=UserCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateIn,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> UserCreatedOut:
    if payload.role == ROLE_ORG_ADMIN and payload.org_id is None:
        raise ValidationError("org_admin_requires_org_id")
    if payload.role == ROLE_SUPER_ADMIN and payload.org_id is not None:
        raise ValidationError("super_admin_must_have_no_org")

    existing = (
        await session.execute(select(User).where(User.email == str(payload.email)))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("email_taken")

    temp_password = random_password(length=16)
    user = User(
        email=str(payload.email),
        password_hash=hash_password(temp_password),
        full_name=payload.full_name,
        role=payload.role,
        org_id=payload.org_id,
        status="active",
        password_must_change=True,
    )
    session.add(user)
    await session.flush()
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        after={"email": user.email, "role": user.role, "org_id": str(user.org_id or "")},
        request=request,
    )
    return UserCreatedOut(**_to_out(user).model_dump(), temp_password=temp_password)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, session: DbSession, _: SuperAdmin) -> UserOut:
    u = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise NotFoundError()
    return _to_out(u)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateIn,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> UserOut:
    u = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise NotFoundError()
    before: dict[str, Any] = {
        "full_name": u.full_name,
        "status": u.status,
        "role": u.role,
    }
    if payload.full_name is not None:
        u.full_name = payload.full_name
    if payload.status is not None:
        u.status = payload.status
    if payload.role is not None:
        u.role = payload.role
    after = {"full_name": u.full_name, "status": u.status, "role": u.role}
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="user.update",
        entity_type="user",
        entity_id=u.id,
        before=before,
        after=after,
        request=request,
    )
    return _to_out(u)


class PasswordResetOut(BaseModel):
    temp_password: str


@router.post("/{user_id}/password/reset", response_model=PasswordResetOut)
async def reset_password(
    user_id: uuid.UUID,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> PasswordResetOut:
    u = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise NotFoundError()
    temp = random_password(length=16)
    u.password_hash = hash_password(temp)
    u.password_must_change = True
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="user.password_reset",
        entity_type="user",
        entity_id=u.id,
        request=request,
    )
    return PasswordResetOut(temp_password=temp)
