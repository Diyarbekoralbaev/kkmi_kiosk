"""Application (murajat) categorization — global list managed by super-admin.

Categories are NOT per-org for now: every kiosk's AI agent and every gov
admin sees the same 10-ish domains (housing, land, employment, …). That
keeps the AI prompt size predictable and lets cross-org analytics work
uniformly. The model carries Karakalpak/Uzbek/Russian display strings in
`name_translations` so the kiosk/UI can render in whichever language is
active without a round-trip.

The agent supplies a `category_slug` when calling submit_application; the
backend resolves slug → id and stores `Application.category_id`. Reviewers
can change the category from the gov-panel if the agent guessed wrong.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin


SUPPORTED_LOCALES: tuple[str, ...] = ("uz", "kk", "ru")
"""Same locales as Organization.name_translations — keep in lockstep."""


class ApplicationCategory(Base, TimestampMixin):
    __tablename__ = "application_categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True
    )
    """Stable identifier the AI agent passes (`housing`, `land`, etc.).
    Never user-facing — display always goes through `name_translations`."""
    name_translations: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, nullable=False, server_default="{}"
    )
    """{"uz": "Uy-jay", "kk": "Үй-жай", "ru": "Жилищный"}. Use the helper
    `localized_category_name(cat, locale)` to resolve with fallback."""
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Display order in dropdowns + pie chart slices. Lower = first."""
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """Soft delete — categories that have historical applications attached
    can't be hard-deleted (Application.category_id FK is SET NULL on row
    delete, but admins may want the option to keep history's slug visible
    while hiding the category from new submissions)."""


def localized_category_name(cat: ApplicationCategory, locale: str = "kk") -> str:
    """Pick the display name for a category. Falls back through the
    supported locale list before bailing to the slug — used by the gov
    dashboard pie chart legend and the agent prompt's category list."""
    t = cat.name_translations or {}
    v = t.get(locale)
    if isinstance(v, str) and v.strip():
        return v
    for k in SUPPORTED_LOCALES:
        alt = t.get(k)
        if isinstance(alt, str) and alt.strip():
            return alt
    return cat.slug


def category_translations_for_response(cat: ApplicationCategory) -> dict[str, str]:
    """Coerce stored translations into a complete uz/kk/ru dict for JSON
    responses; missing slots fall back to slug so clients never see null."""
    t = cat.name_translations or {}
    out: dict[str, str] = {}
    for k in SUPPORTED_LOCALES:
        v = t.get(k)
        out[k] = v if isinstance(v, str) and v.strip() else cat.slug
    return out


# Seed data for migration 0016. Imported by the migration to populate the
# table; also imported by `core/seed.py` so dev environments get the same
# list without needing to run migrations. Keep in sync with the agent
# prompt's category list in seed.py DEFAULT_SECTIONS.
DEFAULT_CATEGORIES: list[dict[str, Any]] = [
    {
        "slug": "housing",
        "order": 10,
        "translations": {
            "uz": "Uy-jay",
            "kk": "Үй-жай",
            "ru": "Жилищный",
        },
    },
    {
        "slug": "land",
        "order": 20,
        "translations": {
            "uz": "Yer ajratish",
            "kk": "Жер ажыратыў",
            "ru": "Земельный",
        },
    },
    {
        "slug": "construction",
        "order": 30,
        "translations": {
            "uz": "Qurilish",
            "kk": "Қурылыс",
            "ru": "Строительство",
        },
    },
    {
        "slug": "utilities",
        "order": 40,
        "translations": {
            "uz": "Kommunal",
            "kk": "Коммунал",
            "ru": "Коммунальный",
        },
    },
    {
        "slug": "employment",
        "order": 50,
        "translations": {
            "uz": "Ish bandlik",
            "kk": "Жумыс бентлик",
            "ru": "Трудоустройство",
        },
    },
    {
        "slug": "education",
        "order": 60,
        "translations": {
            "uz": "Ta'lim",
            "kk": "Билимлендириў",
            "ru": "Образование",
        },
    },
    {
        "slug": "health",
        "order": 70,
        "translations": {
            "uz": "Sog'liq",
            "kk": "Денсаўлық",
            "ru": "Здравоохранение",
        },
    },
    {
        "slug": "social",
        "order": 80,
        "translations": {
            "uz": "Ijtimoiy",
            "kk": "Социаллық",
            "ru": "Социальный",
        },
    },
    {
        "slug": "business",
        "order": 90,
        "translations": {
            "uz": "Tadbirkorlik",
            "kk": "Исбилерменлик",
            "ru": "Предпринимательство",
        },
    },
    {
        "slug": "other",
        "order": 999,
        "translations": {
            "uz": "Boshqa",
            "kk": "Басқа",
            "ru": "Прочее",
        },
    },
]
