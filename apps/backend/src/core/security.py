"""Password hashing, JWT issuance/verification, TOTP MFA, secret helpers."""
from __future__ import annotations

import hashlib
import secrets
import string
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
import pyotp
from passlib.context import CryptContext

from .config import get_settings
from .errors import TokenExpiredError, TokenInvalidError

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")
_settings = get_settings()


# ── Passwords ──────────────────────────────────────────────


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd.verify(plain, hashed)
    except Exception:
        return False


def random_password(length: int = 20) -> str:
    """Cryptographically random password (mixed alphanumeric)."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def random_slug_password(length: int = 16) -> str:
    """4-block dash-separated password (e.g. 'Xk9p-Qm3w-Rt8z-Bn2v') for org credentials."""
    block_count = max(1, length // 4)
    blocks: list[str] = []
    for _ in range(block_count):
        block = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(4))
        blocks.append(block)
    return "-".join(blocks)


# ── JWT ────────────────────────────────────────────────────

TokenType = Literal["access", "refresh", "mfa_session"]


def _now() -> datetime:
    return datetime.now(UTC)


def _create_token(
    subject: str,
    token_type: TokenType,
    ttl: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = _now()
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        _settings.jwt_secret.get_secret_value(),
        algorithm=_settings.jwt_algorithm,
    )


def create_access_token(user_id: str, role: str, org_id: str | None) -> str:
    return _create_token(
        subject=user_id,
        token_type="access",
        ttl=timedelta(minutes=_settings.jwt_access_ttl_minutes),
        extra_claims={"role": role, "org_id": org_id},
    )


def create_refresh_token(user_id: str) -> tuple[str, str, datetime]:
    """Returns (jwt, jti, expires_at)."""
    now = _now()
    expires_at = now + timedelta(days=_settings.jwt_refresh_ttl_days)
    jti = secrets.token_urlsafe(32)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
    }
    token = jwt.encode(
        payload,
        _settings.jwt_secret.get_secret_value(),
        algorithm=_settings.jwt_algorithm,
    )
    return token, jti, expires_at


def create_mfa_session_token(user_id: str) -> str:
    return _create_token(
        subject=user_id,
        token_type="mfa_session",
        ttl=timedelta(minutes=5),
    )


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            _settings.jwt_secret.get_secret_value(),
            algorithms=[_settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenExpiredError(cause=e) from e
    except jwt.InvalidTokenError as e:
        raise TokenInvalidError(cause=e) from e
    if payload.get("type") != expected_type:
        raise TokenInvalidError("token_type_mismatch")
    return payload


def hash_token_jti(jti: str) -> str:
    """Hash the refresh token jti for DB storage."""
    return hashlib.sha256(jti.encode()).hexdigest()


# ── Device enrollment / device keys ─────────────────────────


def random_enrollment_code() -> str:
    """Human-typeable enrollment code: XXXX-XXXX-XXXX (12 chars from base32 minus I/O/0/1)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def random_device_key() -> str:
    """32 random bytes URL-safe base64 (~43 chars). Embedded in the kiosk's DPAPI store."""
    return secrets.token_urlsafe(32)


def hash_device_secret(secret: str) -> str:
    """SHA-256 hex of an enrollment code or device key.

    Both inputs are high-entropy (random or near-random) so a slow KDF is unnecessary;
    fast hash lets us look up by exact match via a unique index.
    """
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


# ── TOTP MFA ────────────────────────────────────────────────


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, account_name: str, issuer: str = "Kiosk Gov") -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False
