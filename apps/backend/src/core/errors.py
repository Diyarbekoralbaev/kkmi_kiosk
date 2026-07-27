"""Opaque error codes — clients never see internal exception messages.

Real exceptions go to structlog with full trace + correlation_id.
Clients receive { code, message } where message is a Karakalpak human string.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import structlog
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)
_stdlib = logging.getLogger("kkmi.errors")


class AppError(Exception):
    """Base for all expected, opaque-coded errors."""

    code: str = "E_INT_999"
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message: str = "Texnikalıq qátelik. Keyin urınıp kóriń."

    def __init__(
        self,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message or self.default_message)
        self.public_message = message or self.default_message
        self.details = details or {}
        self.cause = cause


# ── Auth errors (E_AUTH_xxx) ──
class AuthError(AppError):
    code = "E_AUTH_001"
    http_status = status.HTTP_401_UNAUTHORIZED
    default_message = "Kirisiwde qátelik."


class InvalidCredentialsError(AuthError):
    code = "E_AUTH_002"
    default_message = "Email yaki paról nadurıs."


class TokenExpiredError(AuthError):
    code = "E_AUTH_003"
    default_message = "Sessiya múddetí pitti, qaytadan kirilegniz."


class TokenInvalidError(AuthError):
    code = "E_AUTH_004"
    default_message = "Kirisiw belgisi nadurıs."


class MfaRequiredError(AuthError):
    code = "E_AUTH_005"
    http_status = status.HTTP_200_OK  # special: not really an error, just MFA prompt
    default_message = "MFA kodı kerek."


class MfaInvalidError(AuthError):
    code = "E_AUTH_006"
    default_message = "MFA kodı nadurıs."


class AccountDisabledError(AuthError):
    code = "E_AUTH_007"
    http_status = status.HTTP_403_FORBIDDEN
    default_message = "Akkawnt ózshelashtirilgen."


class PasswordChangeRequiredError(AuthError):
    code = "E_AUTH_008"
    default_message = "Birinshi kirisiwde paról ózgertiwińiz kerek."


# ── Permission errors ──
class PermissionDeniedError(AppError):
    code = "E_PERM_001"
    http_status = status.HTTP_403_FORBIDDEN
    default_message = "Sizde bul ámeldi orinlawǵa ruxsat joq."


# ── Validation ──
class ValidationError(AppError):
    code = "E_VAL_001"
    http_status = status.HTTP_400_BAD_REQUEST
    default_message = "Berilgen mağlıwmat nadurıs."


class NotFoundError(AppError):
    code = "E_VAL_002"
    http_status = status.HTTP_404_NOT_FOUND
    default_message = "Tabilmadı."


class ConflictError(AppError):
    code = "E_VAL_003"
    http_status = status.HTTP_409_CONFLICT
    default_message = "Konflikt: bul mağlıwmat allaqashan bar."


# ── Rate limit ──
class RateLimitError(AppError):
    code = "E_RATE_001"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS
    default_message = "Júdá kóp soraw, biraz kútiniz."


# ── DB / infra ──
class InternalError(AppError):
    code = "E_INT_999"
    http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message = "Texnikalıq qátelik. Keyin urınıp kóriń."


class DatabaseError(AppError):
    code = "E_DB_001"
    http_status = status.HTTP_500_INTERNAL_SERVER_ERROR


class UpstreamError(AppError):
    """Outbound dependency failure (GitHub API, etc) — surface as 502."""
    code = "E_UP_001"
    http_status = status.HTTP_502_BAD_GATEWAY
    default_message = "Sırtqı xizmet ushırasıp atır."


class ServiceUnavailableError(AppError):
    """The endpoint exists but the feature is disabled in this deploy
    (e.g. webhook secret not set)."""
    code = "E_CFG_001"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    default_message = "Funksiya sazlanbağan."
    default_message = "Mağlıwmatlar bazası qátelegi."


# ── Provider (Gemini Live) ──
class ProviderError(AppError):
    code = "E_PRV_001"
    http_status = status.HTTP_502_BAD_GATEWAY
    default_message = "AI xızmeti waqıtsha qol jetimsiz."


def _correlation_id(request: Request | None) -> str:
    if request is not None:
        existing = request.headers.get("x-correlation-id")
        if existing:
            return existing
    return uuid.uuid4().hex


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    cid = _correlation_id(request)
    logger.warning(
        "app_error",
        code=exc.code,
        message=str(exc),
        details=exc.details,
        path=request.url.path,
        method=request.method,
        correlation_id=cid,
    )
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "code": exc.code,
            "message": exc.public_message,
            "correlation_id": cid,
        },
        headers={"X-Correlation-Id": cid},
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    cid = _correlation_id(request)
    if exc.status_code == 404:
        code = NotFoundError.code
        msg = NotFoundError.default_message
    elif exc.status_code == 405:
        code = "E_VAL_004"
        msg = "Metod ruxsat etilmegen."
    elif exc.status_code == 401:
        code = AuthError.code
        msg = AuthError.default_message
    elif exc.status_code == 403:
        code = PermissionDeniedError.code
        msg = PermissionDeniedError.default_message
    else:
        code = InternalError.code
        msg = InternalError.default_message
    logger.warning(
        "http_exception",
        status=exc.status_code,
        path=request.url.path,
        correlation_id=cid,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "message": msg, "correlation_id": cid},
        headers={"X-Correlation-Id": cid},
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    cid = _correlation_id(request)
    logger.warning(
        "validation_error",
        path=request.url.path,
        errors=exc.errors(),
        correlation_id=cid,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": ValidationError.code,
            "message": ValidationError.default_message,
            "correlation_id": cid,
        },
        headers={"X-Correlation-Id": cid},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    cid = _correlation_id(request)
    _stdlib.exception(
        "unhandled_exception path=%s method=%s correlation_id=%s",
        request.url.path,
        request.method,
        cid,
    )
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        exc_type=type(exc).__name__,
        correlation_id=cid,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": InternalError.code,
            "message": InternalError.default_message,
            "correlation_id": cid,
        },
        headers={"X-Correlation-Id": cid},
    )
