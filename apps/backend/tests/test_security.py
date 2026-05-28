"""Pure-unit tests for security primitives — no DB, no app needed."""
from __future__ import annotations

from src.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_totp_secret,
    hash_password,
    hash_token_jti,
    random_password,
    random_slug_password,
    verify_password,
    verify_totp,
)


def test_password_hash_and_verify_roundtrip() -> None:
    h = hash_password("hunter2-very-long")
    assert verify_password("hunter2-very-long", h)
    assert not verify_password("hunter2", h)


def test_random_password_unique_and_correct_length() -> None:
    a = random_password(20)
    b = random_password(20)
    assert a != b
    assert len(a) == 20


def test_random_slug_password_dashed_format() -> None:
    p = random_slug_password(20)
    parts = p.split("-")
    assert len(parts) == 5
    assert all(len(seg) == 4 for seg in parts)


def test_access_token_roundtrip() -> None:
    tok = create_access_token(user_id="u1", role="super_admin", org_id=None)
    payload = decode_token(tok, expected_type="access")
    assert payload["sub"] == "u1"
    assert payload["role"] == "super_admin"
    assert payload["org_id"] is None
    assert payload["type"] == "access"


def test_refresh_token_carries_jti() -> None:
    tok, jti, expires_at = create_refresh_token("u2")
    payload = decode_token(tok, expected_type="refresh")
    assert payload["jti"] == jti
    assert payload["sub"] == "u2"
    assert hash_token_jti(jti) == hash_token_jti(jti)
    assert expires_at is not None


def test_totp_verify_known_secret() -> None:
    import pyotp

    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code)
    assert not verify_totp(secret, "000000")
