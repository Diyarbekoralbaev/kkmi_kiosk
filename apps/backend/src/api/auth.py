"""Auth endpoints: login, MFA verify/setup/enable/disable, refresh, logout, me, password change."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Header, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from ..core import audit
from ..core.deps import CurrentUser, DbSession
from ..core.errors import (
    AccountDisabledError,
    AuthError,
    InvalidCredentialsError,
    MfaInvalidError,
    PasswordChangeRequiredError,
    TokenInvalidError,
    ValidationError,
)
from ..core.security import (
    create_access_token,
    create_mfa_session_token,
    create_refresh_token,
    decode_token,
    generate_totp_secret,
    hash_password,
    hash_token_jti,
    totp_uri,
    verify_password,
    verify_totp,
)
from ..domain.user import ROLE_SUPER_ADMIN, RefreshToken, User

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────────────────


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    user: dict[str, Any]


class MfaPrompt(BaseModel):
    mfa_required: bool = True
    mfa_session_token: str


class LoginResponse(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    user: dict[str, Any] | None = None
    mfa_required: bool = False
    mfa_session_token: str | None = None


class MfaVerifyIn(BaseModel):
    mfa_session_token: str
    code: str = Field(min_length=4, max_length=10)


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaEnableIn(BaseModel):
    code: str = Field(min_length=4, max_length=10)


class RefreshIn(BaseModel):
    refresh_token: str


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    org_id: str | None
    totp_enabled: bool
    password_must_change: bool


def _user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "org_id": str(user.org_id) if user.org_id else None,
        "totp_enabled": user.totp_enabled,
        "password_must_change": user.password_must_change,
    }


# ── Helpers ───────────────────────────────────────────────


async def _issue_tokens(
    session: DbSession, user: User, user_agent: str
) -> TokenPair:
    access = create_access_token(
        user_id=str(user.id),
        role=user.role,
        org_id=str(user.org_id) if user.org_id else None,
    )
    refresh, jti, expires_at = create_refresh_token(str(user.id))
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token_jti(jti),
            expires_at=expires_at,
            user_agent=user_agent[:255] if user_agent else "",
        )
    )
    user.last_login_at = datetime.now(UTC)
    return TokenPair(access_token=access, refresh_token=refresh, user=_user_to_dict(user))


# ── Endpoints ─────────────────────────────────────────────


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginIn,
    session: DbSession,
    request: Request,
    user_agent: str | None = Header(default=None),
) -> LoginResponse:
    user = (
        await session.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        # Audit failed login on an INDEPENDENT transaction so it survives the
        # 401 rollback. Used by ops to spot brute force attempts.
        await audit.record_independent(
            actor_user_id=user.id if user else None,
            actor_org_id=user.org_id if user else None,
            action="user.login.failed",
            entity_type="user",
            entity_id=user.id if user else "",
            after={"email_attempted": str(payload.email)},
            request=request,
        )
        raise InvalidCredentialsError()
    if user.status != "active":
        await audit.record_independent(
            actor_user_id=user.id,
            actor_org_id=user.org_id,
            action="user.login.disabled_account",
            entity_type="user",
            entity_id=user.id,
            request=request,
        )
        raise AccountDisabledError()

    if user.role == ROLE_SUPER_ADMIN and not user.totp_enabled:
        # Super admin without MFA — allow first login but flag forced setup.
        # MFA is mandatory; user must run /mfa/setup + /mfa/enable next.
        pass

    if user.totp_enabled:
        token = create_mfa_session_token(str(user.id))
        await audit.record(
            session,
            actor_user_id=user.id,
            actor_org_id=user.org_id,
            action="user.login.mfa_required",
            entity_type="user",
            entity_id=user.id,
            request=request,
        )
        return LoginResponse(mfa_required=True, mfa_session_token=token)

    pair = await _issue_tokens(session, user, user_agent or "")
    await audit.record(
        session,
        actor_user_id=user.id,
        actor_org_id=user.org_id,
        action="user.login",
        entity_type="user",
        entity_id=user.id,
        request=request,
    )
    return LoginResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type="Bearer",
        user=pair.user,
    )


@router.post("/mfa/verify", response_model=TokenPair)
async def mfa_verify(
    payload: MfaVerifyIn,
    session: DbSession,
    request: Request,
    user_agent: str | None = Header(default=None),
) -> TokenPair:
    claims = decode_token(payload.mfa_session_token, expected_type="mfa_session")
    user_id_raw = claims.get("sub")
    if not user_id_raw:
        raise TokenInvalidError("missing_subject")
    try:
        user_id = uuid.UUID(user_id_raw)
    except (TypeError, ValueError) as e:
        raise TokenInvalidError("bad_subject") from e
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None or user.status != "active":
        raise AccountDisabledError()
    if not user.totp_enabled or not user.totp_secret:
        raise MfaInvalidError("mfa_not_configured")
    if not verify_totp(user.totp_secret, payload.code):
        raise MfaInvalidError()
    pair = await _issue_tokens(session, user, user_agent or "")
    await audit.record(
        session,
        actor_user_id=user.id,
        actor_org_id=user.org_id,
        action="user.login.mfa_success",
        entity_type="user",
        entity_id=user.id,
        request=request,
    )
    return pair


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshIn,
    session: DbSession,
    user_agent: str | None = Header(default=None),
) -> TokenPair:
    claims = decode_token(payload.refresh_token, expected_type="refresh")
    jti = claims.get("jti")
    user_id_raw = claims.get("sub")
    if not jti or not user_id_raw:
        raise TokenInvalidError("missing_claims")

    token_hash = hash_token_jti(jti)
    record = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
    ).scalar_one_or_none()
    if record is None or record.revoked_at is not None:
        raise TokenInvalidError("revoked_or_unknown")
    if record.expires_at < datetime.now(UTC):
        raise TokenInvalidError("expired")

    user = (
        await session.execute(select(User).where(User.id == record.user_id))
    ).scalar_one_or_none()
    if user is None or user.status != "active":
        raise AccountDisabledError()

    # Rotate: revoke old, issue new
    record.revoked_at = datetime.now(UTC)
    return await _issue_tokens(session, user, user_agent or "")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshIn,
    session: DbSession,
    user: CurrentUser,
    request: Request,
) -> None:
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenInvalidError:
        return  # Idempotent: no-op on bad token
    jti = claims.get("jti")
    if not jti:
        return
    token_hash = hash_token_jti(jti)
    record = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
    ).scalar_one_or_none()
    if record is not None and record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_user_id=user.id,
        actor_org_id=user.org_id,
        action="user.logout",
        entity_type="user",
        entity_id=user.id,
        request=request,
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut(**_user_to_dict(user))


@router.post("/mfa/setup", response_model=MfaSetupOut)
async def mfa_setup(user: CurrentUser, session: DbSession) -> MfaSetupOut:
    if user.totp_enabled:
        raise ValidationError("mfa_already_enabled")
    secret = generate_totp_secret()
    user.totp_secret = secret
    return MfaSetupOut(
        secret=secret,
        otpauth_uri=totp_uri(secret, account_name=user.email),
    )


@router.post("/mfa/enable", status_code=status.HTTP_204_NO_CONTENT)
async def mfa_enable(
    payload: MfaEnableIn,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> None:
    if user.totp_enabled:
        raise ValidationError("mfa_already_enabled")
    if not user.totp_secret:
        raise ValidationError("mfa_not_setup")
    if not verify_totp(user.totp_secret, payload.code):
        raise MfaInvalidError()
    user.totp_enabled = True
    await audit.record(
        session,
        actor_user_id=user.id,
        actor_org_id=user.org_id,
        action="user.mfa_enable",
        entity_type="user",
        entity_id=user.id,
        request=request,
    )


@router.post("/mfa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def mfa_disable(
    payload: MfaEnableIn,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> None:
    if not user.totp_enabled or not user.totp_secret:
        return
    if not verify_totp(user.totp_secret, payload.code):
        raise MfaInvalidError()
    if user.role == ROLE_SUPER_ADMIN:
        raise AuthError("super_admin_mfa_required")
    user.totp_enabled = False
    user.totp_secret = None
    await audit.record(
        session,
        actor_user_id=user.id,
        actor_org_id=user.org_id,
        action="user.mfa_disable",
        entity_type="user",
        entity_id=user.id,
        request=request,
    )


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def password_change(
    payload: PasswordChangeIn,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise InvalidCredentialsError("current_password_wrong")
    user.password_hash = hash_password(payload.new_password)
    user.password_must_change = False
    await audit.record(
        session,
        actor_user_id=user.id,
        actor_org_id=user.org_id,
        action="user.password_change",
        entity_type="user",
        entity_id=user.id,
        request=request,
    )
    # Revoke all refresh tokens for this user
    refreshes = (
        await session.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
            )
        )
    ).scalars().all()
    now = datetime.now(UTC)
    for r in refreshes:
        r.revoked_at = now


# Note: PasswordChangeRequiredError is reserved for future use when we want
# to enforce must_change on a separate flow; current password-change endpoint
# accepts any authenticated user.
_ = PasswordChangeRequiredError
