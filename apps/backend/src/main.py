"""FastAPI application entry."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import auth as auth_router
from .api import health as health_router
from .api import health_deep as health_deep_router
from .api import kiosk_applications as kiosk_applications_router
from .api import kiosk_auth as kiosk_auth_router
from .api import kiosk_diag as kiosk_diag_router
from .api import kiosk_enrollment as kiosk_enrollment_router
from .api import kiosk_library as kiosk_library_router
from .api import kiosk_reception as kiosk_reception_router
from .api import kiosk_schedule as kiosk_schedule_router
from .api import kiosk_updates as kiosk_updates_router
from .api import kiosk_ws as kiosk_ws_router
from .api.gov import applications as gov_applications_router
from .api.gov import appointments as gov_appointments_router
from .api.gov import books as gov_books_router
from .api.gov import categories as gov_categories_router
from .api.gov import dashboard as gov_dashboard_router
from .api.gov import dashboard_monthly as gov_dashboard_monthly_router
from .api.gov import hemis as gov_hemis_router
from .api.gov import officials as gov_officials_router
from .api.gov import sessions as gov_sessions_router
from .api.gov import staff as gov_staff_router
from .api.public import qabul as public_qabul_router
from .api.super import ai_defaults as super_ai_defaults_router
from .api.super import audit as super_audit_router
from .api.super import categories as super_categories_router
from .api.super import devices as super_devices_router
from .api.super import orgs as super_orgs_router
from .api.super import releases as super_releases_router
from .api.super import users as super_users_router
from .core import bootstrap
from .core.config import get_settings
from .core.connection_registry import registry as ws_registry
from .core.errors import (
    AppError,
    app_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from .core.logging import setup_logging
from .core.redis_bus import bus as redis_bus

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    logger.info("startup_begin")
    try:
        await bootstrap.run()
        # Connect the Redis bus + wire the connection registry's revoke
        # subscriber. Bus tolerates an unreachable Redis (logs warning, falls
        # back to local fan-out) so single-worker dev still works without it.
        await redis_bus.connect()
        await ws_registry.attach_to_bus()
    except Exception:
        logger.exception("bootstrap_failed")
        raise
    logger.info("startup_complete")
    yield
    logger.info("shutdown")
    await redis_bus.close()


def create_app() -> FastAPI:
    settings = get_settings()
    is_prod = settings.env.lower() == "production"
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        default_response_class=JSONResponse,
        # Hide schema + interactive docs in production — info disclosure surface
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-Id"],
    )

    @app.middleware("http")
    async def _correlation_id_mw(request: Request, call_next):
        cid = request.headers.get("x-correlation-id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=cid,
            path=request.url.path,
            method=request.method,
        )
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = cid
        return response

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.include_router(health_router.router)
    app.include_router(health_deep_router.router)
    app.include_router(auth_router.router)
    app.include_router(super_orgs_router.router)
    app.include_router(super_users_router.router)
    app.include_router(super_devices_router.router)
    app.include_router(super_audit_router.router)
    app.include_router(super_ai_defaults_router.router)
    app.include_router(super_categories_router.router)
    app.include_router(super_releases_router.router)
    app.include_router(gov_dashboard_router.router)
    app.include_router(gov_dashboard_monthly_router.router)
    app.include_router(gov_applications_router.router)
    app.include_router(gov_appointments_router.router)
    app.include_router(gov_categories_router.router)
    app.include_router(gov_sessions_router.router)
    app.include_router(gov_officials_router.router)
    app.include_router(gov_hemis_router.router)
    app.include_router(gov_staff_router.router)
    app.include_router(gov_books_router.router)
    app.include_router(kiosk_auth_router.router)
    app.include_router(kiosk_enrollment_router.router)
    app.include_router(kiosk_applications_router.router)
    app.include_router(kiosk_schedule_router.router)
    app.include_router(kiosk_library_router.router)
    app.include_router(kiosk_reception_router.router)
    app.include_router(kiosk_diag_router.router)
    app.include_router(kiosk_updates_router.router)
    app.include_router(kiosk_ws_router.router)
    app.include_router(public_qabul_router.router)

    @app.get("/", status_code=status.HTTP_200_OK)
    async def root() -> dict[str, str]:
        return {"app": settings.app_name, "version": "0.1.0"}

    return app


app = create_app()
