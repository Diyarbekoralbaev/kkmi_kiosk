"""Organization (tenant) + first-run kiosk credentials."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base, TimestampMixin

# Supported display-name locales. Kept in sync with the kiosk's
# LocalizationService and the backend's RECEIPT_STRINGS. Adding a new
# language: add it here, add a key to every org's name_translations dict,
# add the strings table to RECEIPT_STRINGS, add an .axaml on the kiosk.
ORG_NAME_LOCALES: tuple[str, ...] = ("uz", "kk", "ru")

if TYPE_CHECKING:
    from .user import User


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    """Canonical/fallback display name. Treat as legacy — prefer
    `name_translations[locale]` for anything user-facing. Audit log and any
    pre-translation code paths still read this column directly."""
    name_translations: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, nullable=False, server_default="{}"
    )
    """{"uz": ..., "kk": ..., "ru": ...}. Resolved via `localized_name()`."""
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    """active | suspended"""
    max_devices: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    locale: Mapped[str] = mapped_column(String(8), default="kk", nullable=False)
    # Geo for the kiosk's weather widget (Open-Meteo). All optional: if any
    # field is null the kiosk header just doesn't render a weather row.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    city_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Helpline / contact phone shown in the kiosk footer band — per-org so
    # different hokimligi can advertise their own front-desk number.
    helpline_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Kiosk Contacts page address (street). Per-locale because the address
    # itself reads differently in uz/kk/ru (script + ordering of "ko'chasi"
    # vs "гүзәри" vs "улица").
    address_translations: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, nullable=False, server_default="{}"
    )
    # Single org-wide email. Plain string (email addresses don't translate).
    email: Mapped[str] = mapped_column(
        String(255), default="", nullable=False, server_default=""
    )
    # Working hours line, per-locale ("Du-Ju 09:00-18:00" / "Дү-Жу..." / "Пн-Пт...").
    work_hours_translations: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, nullable=False, server_default="{}"
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    credentials: Mapped[OrgCredentials | None] = relationship(
        "OrgCredentials",
        back_populates="organization",
        uselist=False,
        cascade="all, delete-orphan",
    )
    users: Mapped[list[User]] = relationship(
        "User",
        back_populates="organization",
        foreign_keys="User.org_id",
    )


class OrgCredentials(Base, TimestampMixin):
    """Org-level shared credentials used at kiosk first-run enrollment.

    Issued and rotated by the super admin. Plain-text password is shown to the
    super admin exactly once on creation/regeneration and never persisted in
    plain form. Schema present in this rebuild; the `/enroll` endpoint that
    consumes it lands in the next plan (kiosk C# Avalonia).
    """

    __tablename__ = "org_credentials"
    __table_args__ = (UniqueConstraint("username"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    last_rotated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped[Organization] = relationship(
        "Organization", back_populates="credentials"
    )


def localized_name(org: Organization, locale: str = "kk") -> str:
    """Pick the org display name for the given locale, falling back to the
    legacy `name` column when the translations dict is empty or missing the
    requested locale. Unknown locales are coerced to "kk" upstream
    (api/public/qabul receipt_pdf does the allow-list check) but we
    defensively fall back here too.
    """
    t = org.name_translations or {}
    v = t.get(locale)
    if isinstance(v, str) and v.strip():
        return v
    # Try the other known locales before bailing to the canonical name.
    for k in ORG_NAME_LOCALES:
        alt = t.get(k)
        if isinstance(alt, str) and alt.strip():
            return alt
    return org.name


def name_translations_for_response(org: Organization) -> dict[str, str]:
    """Coerce the persisted translations into a stable shape for JSON
    responses: always contains every locale in ORG_NAME_LOCALES, falling
    back to `org.name` for any missing slot so the client never has to
    juggle null/missing values. Clients should still prefer this over
    `name` directly because the value here is freshly resolved."""
    t = org.name_translations or {}
    out: dict[str, str] = {}
    for k in ORG_NAME_LOCALES:
        v = t.get(k)
        out[k] = v if isinstance(v, str) and v.strip() else org.name
    return out


def _translations_for_response(
    raw: dict[str, str] | None, fallback: str = ""
) -> dict[str, str]:
    """Same shape guarantee as name_translations_for_response but for
    non-name fields (address, work_hours): every locale present, missing
    slots filled from any other non-empty locale or the supplied fallback.
    Returns {} keys default to empty string when no locale has a value —
    the kiosk renders an empty Contacts row rather than crashing."""
    t = raw or {}
    first_nonempty = ""
    for k in ORG_NAME_LOCALES:
        v = t.get(k)
        if isinstance(v, str) and v.strip():
            first_nonempty = v
            break
    out: dict[str, str] = {}
    for k in ORG_NAME_LOCALES:
        v = t.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v
        else:
            out[k] = first_nonempty or fallback
    return out


def address_translations_for_response(org: Organization) -> dict[str, str]:
    return _translations_for_response(org.address_translations)


def work_hours_translations_for_response(org: Organization) -> dict[str, str]:
    return _translations_for_response(org.work_hours_translations)


def contact_info_for_response(org: Organization) -> dict[str, object]:
    """One blob containing everything the kiosk needs to render its Contacts
    page + footer helpline band. Used by /heartbeat and /enroll so the kiosk
    can swap to a new org's contact info without a restart."""
    return {
        "address_translations": address_translations_for_response(org),
        "email": org.email or "",
        "work_hours_translations": work_hours_translations_for_response(org),
        "helpline_phone": org.helpline_phone or "",
    }
