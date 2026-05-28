"""Citizen-submitted murajaat (application) record."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin

STATUS_NEW = "new"
STATUS_IN_PROGRESS = "in_progress"
STATUS_RESOLVED = "resolved"
STATUS_RETURNED = "returned"
"""Returned to the citizen — phone unreachable, information incomplete, etc.
Reviewer flips here when the request can't be processed as-is and needs the
visitor to supply more info. From `returned` an admin re-opens to `new` or
`in_progress` once the citizen has been contacted again."""
STATUS_ARCHIVED = "archived"
ALL_STATUSES = (
    STATUS_NEW,
    STATUS_IN_PROGRESS,
    STATUS_RESOLVED,
    STATUS_RETURNED,
    STATUS_ARCHIVED,
)

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    STATUS_NEW: {STATUS_IN_PROGRESS, STATUS_RETURNED, STATUS_ARCHIVED},
    STATUS_IN_PROGRESS: {
        STATUS_RESOLVED,
        STATUS_RETURNED,
        STATUS_ARCHIVED,
        STATUS_NEW,
    },
    STATUS_RESOLVED: {STATUS_ARCHIVED, STATUS_IN_PROGRESS},
    STATUS_RETURNED: {STATUS_NEW, STATUS_IN_PROGRESS, STATUS_ARCHIVED},
    STATUS_ARCHIVED: set(),
}


class Application(Base, TimestampMixin):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_org_status_created", "org_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voice_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=STATUS_NEW, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("application_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """Domain category (housing, land, utilities, etc.). Populated by the AI
    agent at submit time via `category_slug`; reviewer can correct it in the
    gov-panel detail view. Drives dashboard category dynamics."""
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
