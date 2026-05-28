"""Citizen-booked qabul (reception appointment) record.

The visitor states their issue — the AI picks the appropriate official from the
KB, asks for confirmation + phone, then writes one of these. No time slots:
each (official, scheduled_date) gets a sequential queue_number assigned at
insert time. Receipt PDF + QR are generated on submit and embedded in the WS
envelope so the kiosk can print + display without a second round trip.
"""
from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"
STATUS_NO_SHOW = "no_show"
ALL_STATUSES = (STATUS_PENDING, STATUS_COMPLETED, STATUS_CANCELLED, STATUS_NO_SHOW)

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    STATUS_PENDING: {STATUS_COMPLETED, STATUS_CANCELLED, STATUS_NO_SHOW},
    STATUS_COMPLETED: {STATUS_PENDING},
    STATUS_CANCELLED: set(),
    STATUS_NO_SHOW: {STATUS_PENDING},
}

SOURCE_KIOSK = "kiosk"
SOURCE_ONLINE = "online"
ALL_SOURCES = (SOURCE_KIOSK, SOURCE_ONLINE)


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint(
            "official_id",
            "scheduled_date",
            "queue_number",
            name="uq_appointments_official_date_queue",
        ),
        Index("ix_appointments_org_date", "org_id", "scheduled_date"),
        Index("ix_appointments_org_status_created", "org_id", "status", "created_at"),
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
    official_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org_kb_officials.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voice_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    visitor_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    topic_summary: Mapped[str] = mapped_column(Text, nullable=False)

    scheduled_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    queue_number: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(String(32), default=STATUS_PENDING, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default=SOURCE_KIOSK, nullable=False)

    verification_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )

    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    """Reviewer / responsible person who handles the in-person reception and
    records the outcome in `result_note`. Set by admin from the gov-panel
    appointment detail page."""
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    """Free-text outcome the reviewer enters after the visitor has been seen.
    Drives the gov-panel detail view and audit trail."""
