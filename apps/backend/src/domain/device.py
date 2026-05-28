"""Kiosk device record + enrollment codes + per-device keys (Slice 1 of kiosk plan)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin


class Device(Base, TimestampMixin):
    __tablename__ = "devices"
    __table_args__ = (
        Index("ix_devices_org_status", "org_id", "status"),
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
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    location: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    fingerprint: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    cert_serial: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    """pending | active | revoked"""
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DeviceEnrollmentCode(Base, TimestampMixin):
    """Short-lived (10 min) single-use code that a kiosk exchanges for a device key."""

    __tablename__ = "device_enrollment_codes"
    __table_args__ = (
        Index("ix_device_enrollment_codes_device_id", "device_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DeviceKey(Base, TimestampMixin):
    """ECDSA P-256 public key registered for a device.

    The matching private key lives inside the kiosk's TPM (Microsoft Platform
    Crypto Provider on Windows) and never leaves the chip. The server only ever
    sees this public PEM and uses it to verify ECDSA signatures over per-request
    nonces. Multiple keys may exist per device (history); only one with
    revoked_at IS NULL is currently active.
    """

    __tablename__ = "device_keys"
    __table_args__ = (
        Index("ix_device_keys_device_id", "device_id"),
        Index("ix_device_keys_device_revoked", "device_id", "revoked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuthChallenge(Base):
    """Single-use ECDSA nonce issued to a kiosk for a signed request.

    The nonce is a 32-byte URL-safe base64 string. The kiosk signs it with its
    TPM private key; the server verifies the signature using the device's
    public_key_pem, marks used_at to prevent replay. Expired/used rows are
    safe to drop — currently retained for audit until a periodic cleanup job
    is added.

    Note: this table doesn't use TimestampMixin — created_at suffices and
    updated_at would just be used_at, which is its own column.
    """

    __tablename__ = "auth_challenges"
    __table_args__ = (
        Index("ix_auth_challenges_device_id", "device_id"),
        Index("ix_auth_challenges_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    nonce_b64: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
