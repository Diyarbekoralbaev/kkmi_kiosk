"""FastAPI dependencies for auth + tenant scoping."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.organization import Organization
from ..domain.user import (
    ORG_ROLES,
    ROLE_ORG_ADMIN,
    ROLE_REVIEWER,
    ROLE_SUPER_ADMIN,
    User,
)
from .db import get_session
from .errors import (
    AccountDisabledError,
    AuthError,
    PermissionDeniedError,
    TokenInvalidError,
)
from .security import decode_token

DbSession = Annotated[AsyncSession, Depends(get_session)]


async def _resolve_user(session: AsyncSession, token: str) -> User:
    payload = decode_token(token, expected_type="access")
    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise TokenInvalidError("missing_subject")
    try:
        user_id = uuid.UUID(user_id_raw)
    except (ValueError, TypeError) as e:
        raise TokenInvalidError("bad_subject") from e
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise TokenInvalidError("user_not_found")
    if user.status != "active":
        raise AccountDisabledError()
    return user


async def current_user(
    session: DbSession,
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization:
        raise AuthError("missing_authorization")
    if not authorization.lower().startswith("bearer "):
        raise AuthError("malformed_authorization")
    token = authorization.split(" ", 1)[1].strip()
    return await _resolve_user(session, token)


CurrentUser = Annotated[User, Depends(current_user)]


async def require_super_admin(user: CurrentUser) -> User:
    if user.role != ROLE_SUPER_ADMIN:
        raise PermissionDeniedError("super_admin_required")
    return user


async def require_org_admin(user: CurrentUser) -> User:
    if user.role != ROLE_ORG_ADMIN:
        raise PermissionDeniedError("org_admin_required")
    if user.org_id is None:
        raise PermissionDeniedError("org_id_missing")
    return user


async def require_org_member(user: CurrentUser) -> User:
    """Either org_admin or reviewer. Both belong to an org and can interact
    with that org's data (with reviewer scoped to assigned items via the
    individual endpoint logic). Used by endpoints that BOTH roles need:
    the murajat/qabul detail pages, the staff "who am I" probe, etc."""
    if user.role not in ORG_ROLES:
        raise PermissionDeniedError("org_member_required")
    if user.org_id is None:
        raise PermissionDeniedError("org_id_missing")
    return user


SuperAdmin = Annotated[User, Depends(require_super_admin)]
OrgAdmin = Annotated[User, Depends(require_org_admin)]
OrgMember = Annotated[User, Depends(require_org_member)]


async def _resolve_org(session: AsyncSession, org_id: uuid.UUID) -> Organization:
    org = (
        await session.execute(
            select(Organization).where(Organization.id == org_id)
        )
    ).scalar_one_or_none()
    if org is None or org.status != "active":
        raise PermissionDeniedError("org_inactive")
    return org


async def current_org(
    session: DbSession, user: OrgAdmin
) -> Organization:
    if user.org_id is None:
        raise PermissionDeniedError("org_id_missing")
    return await _resolve_org(session, user.org_id)


async def current_org_any_member(
    session: DbSession, user: OrgMember
) -> Organization:
    """Same as current_org but accepts reviewers too. Used by endpoints
    that share data between the two org-level roles."""
    if user.org_id is None:
        raise PermissionDeniedError("org_id_missing")
    return await _resolve_org(session, user.org_id)


CurrentOrg = Annotated[Organization, Depends(current_org)]
CurrentOrgAnyMember = Annotated[Organization, Depends(current_org_any_member)]


def is_reviewer(user: User) -> bool:
    return user.role == ROLE_REVIEWER


async def session_iter() -> AsyncIterator[AsyncSession]:
    async for s in get_session():
        yield s
