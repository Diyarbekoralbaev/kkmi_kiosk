"""Startup bootstrap: ensure system_ai_defaults + super admin from env."""
from __future__ import annotations

import structlog
from sqlalchemy import select, text

from ..domain.user import ROLE_SUPER_ADMIN, User
from .config import (
    INSECURE_DEFAULT_BASE_URL,
    INSECURE_DEFAULT_DSN,
    INSECURE_DEFAULT_SECRET,
    Settings,
    get_settings,
)
from .db import AsyncSessionLocal
from .security import hash_password
from .seed import (
    ensure_default_institute_org,
    ensure_system_ai_defaults,
)

logger = structlog.get_logger(__name__)


def _check_secrets(settings: Settings) -> None:
    """Refuse to start in production if any prod-required setting is still
    a dev placeholder. CORS origins, base URL, and DB DSN are all checked
    in addition to the JWT secret + super-admin password."""
    is_prod = settings.env.lower() == "production"

    violations: dict[str, bool] = {
        "jwt_secret": settings.jwt_secret.get_secret_value() == INSECURE_DEFAULT_SECRET,
        "super_admin_password": (
            settings.super_admin_password.get_secret_value() == INSECURE_DEFAULT_SECRET
        ),
        "public_base_url_not_https": (
            is_prod and not settings.public_base_url.startswith("https://")
        ),
        "public_base_url_default": settings.public_base_url == INSECURE_DEFAULT_BASE_URL,
        "database_url_default": settings.database_url == INSECURE_DEFAULT_DSN,
        "cors_origins_localhost": (
            is_prod
            and any("localhost" in o or "127.0.0.1" in o for o in settings.cors_origins)
        ),
    }
    bad = [k for k, v in violations.items() if v]
    if bad:
        msg = (
            "Insecure / dev-only defaults detected: "
            + ", ".join(bad)
            + ". Set strong values in your .env or compose env."
        )
        if is_prod:
            raise RuntimeError(msg)
        logger.warning("insecure_defaults_in_use", violations=bad)


async def run() -> None:
    settings = get_settings()
    _check_secrets(settings)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Serialize first-boot seeding across uvicorn workers. With
            # `--workers 2` in prod, both workers run this lifespan
            # concurrently and would both INSERT system_ai_defaults(id=1) →
            # the loser hits a UniqueViolation and its startup crashes (then
            # restarts idempotently). A transaction-scoped advisory lock makes
            # the second worker wait, by which point the idempotent existence
            # checks below short-circuit. Released automatically at commit.
            await session.execute(text("SELECT pg_advisory_xact_lock(728193)"))
            await ensure_system_ai_defaults(session)
            await ensure_default_institute_org(session)

            existing_super = (
                await session.execute(
                    select(User).where(User.role == ROLE_SUPER_ADMIN).limit(1)
                )
            ).scalar_one_or_none()
            if existing_super is None:
                user = User(
                    email=settings.super_admin_email,
                    password_hash=hash_password(
                        settings.super_admin_password.get_secret_value()
                    ),
                    full_name="Super Admin",
                    role=ROLE_SUPER_ADMIN,
                    org_id=None,
                    status="active",
                    totp_enabled=False,
                    password_must_change=False,
                )
                session.add(user)
                await session.flush()
                logger.info(
                    "bootstrap_super_admin_created",
                    email=settings.super_admin_email,
                    user_id=str(user.id),
                )
            else:
                logger.info("bootstrap_super_admin_exists")
