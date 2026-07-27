"""AI agent config.

The AI prompt is GLOBAL and STATIC across all orgs — only super-admin edits it.
- SystemAiDefaults: singleton row. Holds the model/voice tuning + `default_sections`
  (JSONB list of {section_key, content, order}) read at every WS connect by
  prompt_builder. Also holds `default_tools` (which tool calls are enabled) and
  `default_officials` (seed data for new orgs only — actual officials live in
  OrgKbOfficial per-org).
- OrgKbOfficial: per-org list of hokim/orinbosarlar. Org-specific data.

There are no per-org prompt sections, screens, tools, or model tuning. Those
existed before and were dropped by the "global static prompt" migration —
they were tabbed-up complexity that the product never used.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin

# The prompt is assembled as BASE + one FOCUS block, chosen by the menu the
# visitor entered from (see ai/prompt_builder.load_agent_config). Splitting it
# this way keeps the prompt short: with all six flows described at once the
# model started blending them — offering to file an appeal when asked about a
# timetable — and the guardrails fell out of attention.
BASE_SECTION_KEYS = (
    "identity",
    "language",
    "tone",
    "guardrails",
    "institute_kb",
)

FOCUS_SECTION_KEYS = (
    "focus_maslahatchi",
    "focus_library",
    "focus_abituriyent",
    "focus_murojat",
    "focus_jadval",
    "focus_qabul",
)

SECTION_KEYS = BASE_SECTION_KEYS + FOCUS_SECTION_KEYS


def focus_key(menu: str) -> str:
    """Menu name → its prompt section key ("jadval" → "focus_jadval")."""
    return f"focus_{menu}"


DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class SystemAiDefaults(Base, TimestampMixin):
    """Singleton (id always 1). Holds the global prompt + tuning."""

    __tablename__ = "system_ai_defaults"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    voice: Mapped[str] = mapped_column(String(64), nullable=False)
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.3)
    top_p: Mapped[float] = mapped_column(nullable=False, default=0.85)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=8192)
    response_modalities: Mapped[str] = mapped_column(
        String(32), default="audio", nullable=False
    )
    default_sections: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    """[{section_key, content, order}, ...] — read by prompt_builder at every WS connect."""
    default_tools: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    """[{tool_key, enabled}, ...]"""
    default_officials: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    """Seed for new orgs. Real officials are per-org rows in OrgKbOfficial."""


class OrgKbOfficial(Base, TimestampMixin):
    """Hokim / orinbasar / official record. Structured KB entry, per-org."""

    __tablename__ = "org_kb_officials"
    __table_args__ = (
        Index("ix_org_kb_officials_org_order", "org_id", "order"),
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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[str] = mapped_column(String(255), nullable=False)
    responsibilities: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reception_day: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    reception_time: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 'chief' = the single hokim; 'deputy' = orinbasar. Kiosk home tiles
    # filter on this so the two reception flows ("Hokim jeke" vs
    # "Hokim orinbasari qabuli") show only the matching subset.
    role: Mapped[str] = mapped_column(String(16), default="deputy", nullable=False)
    # Bare filename (no directory) under settings.photos_dir, e.g.
    # "abc-uuid.jpg". Empty = no photo uploaded; kiosk renders an
    # initials-circle fallback instead.
    photo_path: Mapped[str] = mapped_column(String(255), default="", nullable=False)
