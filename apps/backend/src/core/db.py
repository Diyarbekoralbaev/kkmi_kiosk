"""SQLAlchemy async engine + session factory + Base model."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map: dict[Any, Any] = {}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    """Common created_at / updated_at columns.

    Defaults are PYTHON-SIDE on purpose. When `onupdate=func.now()` is server-side,
    SQLAlchemy expires the attribute after flush, so any code path that does
    `session.flush()` (e.g. audit.record) followed by `obj.updated_at` triggers
    an async DB reload — and if you happen to be outside an async greenlet at
    that moment you get `MissingGreenlet: greenlet_spawn has not been called`.
    Doing the timestamp client-side avoids the expire-on-flush trap entirely
    and the column still reflects every UPDATE because SQLAlchemy emits the
    Python value into the UPDATE statement.

    The DB still keeps `server_default` from the initial migration so any rows
    inserted via raw SQL also get a sane value — that's a no-op in normal use.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )


_settings = get_settings()
engine = create_async_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=_settings.log_level == "DEBUG",
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: provide an AsyncSession that auto-commits or rolls back."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
