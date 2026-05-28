"""Kiosk binary release record.

Each row is one shipped or candidate Windows .exe (or .nupkg/Velopack bundle).
Super-admin uploads via the panel or syncs from GitHub Releases. The kiosk
asks /api/kiosk/updates/check on every startup; if the latest published
release in the `stable` channel is newer than its own version, it downloads
+ verifies SHA-256 + applies via Velopack and restarts.

Status model:
  - draft       — uploaded but NOT visible to kiosks. Operator can preview.
  - published   — visible to all kiosks via /updates/check. Active update.
  - unpublished — was published, now retracted. Kiosks already on this
                  version stay; new updates won't roll out from this row.

Only ONE published row per channel at a time is the convention; UI enforces
"unpublish current" before "publish new".
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin

CHANNEL_STABLE = "stable"
CHANNEL_RC = "rc"
CHANNEL_DEV = "dev"
ALL_CHANNELS = (CHANNEL_STABLE, CHANNEL_RC, CHANNEL_DEV)

STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_UNPUBLISHED = "unpublished"
ALL_STATUSES = (STATUS_DRAFT, STATUS_PUBLISHED, STATUS_UNPUBLISHED)

SOURCE_MANUAL = "manual"
SOURCE_GITHUB = "github"


class KioskRelease(Base, TimestampMixin):
    __tablename__ = "kiosk_releases"
    __table_args__ = (
        Index("ix_kiosk_releases_channel_status", "channel", "status"),
        Index("ix_kiosk_releases_published_at", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    """Semantic version string (e.g. 0.2.0). Compared lexically by the kiosk —
    so make sure releases are tagged with strict 0-padded x.y.z."""

    channel: Mapped[str] = mapped_column(String(16), default=CHANNEL_STABLE, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_DRAFT, nullable=False)

    # On-disk path RELATIVE to settings.releases_dir. Joined when serving.
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    release_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mandatory: Mapped[bool] = mapped_column(default=False, nullable=False)
    """If true, kiosks block voice until they've installed this version."""

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(16), default=SOURCE_MANUAL, nullable=False)
    """`manual` (super-admin upload) | `github` (sync from GitHub Releases)."""

    github_release_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
