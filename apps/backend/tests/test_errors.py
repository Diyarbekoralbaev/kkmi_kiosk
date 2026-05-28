"""Opaque error code mapping must never leak internals."""
from __future__ import annotations

from src.core.errors import (
    AppError,
    AuthError,
    ConflictError,
    InvalidCredentialsError,
    NotFoundError,
    ValidationError,
)


def test_app_error_has_code_and_default_message() -> None:
    err = AppError()
    assert err.code == "E_INT_999"
    assert err.public_message
    assert err.http_status >= 500


def test_invalid_credentials_specific_code() -> None:
    err = InvalidCredentialsError()
    assert err.code == "E_AUTH_002"
    assert err.http_status == 401


def test_not_found_404() -> None:
    err = NotFoundError()
    assert err.http_status == 404


def test_conflict_409() -> None:
    err = ConflictError()
    assert err.http_status == 409


def test_validation_400() -> None:
    err = ValidationError()
    assert err.http_status == 400


def test_messages_are_user_facing_no_internals() -> None:
    """All public_message values must look like user-facing strings, not exception types."""
    for cls in (AuthError, InvalidCredentialsError, NotFoundError, ConflictError, ValidationError):
        msg = cls.default_message
        assert "Traceback" not in msg
        assert "Exception" not in msg
        assert msg
