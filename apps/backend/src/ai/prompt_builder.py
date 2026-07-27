"""Assemble the system prompt for one kiosk WS session.

Source of truth is the singleton `system_ai_defaults` row, edited by the super
admin. Its `default_sections` JSONB holds every section; this module picks the
BASE ones plus the ONE focus block matching the menu the visitor tapped, and
returns the tool set scoped to that same menu.

Why menu-scoped rather than one prompt with everything: with all six flows
described at once the model blended them — offering to file an appeal when
asked about a timetable, calling `show_schedule` mid-appeal — and the
guardrails drifted out of attention as the prompt grew. One flow at a time
keeps the prompt short and the behaviour predictable.

Two blocks are computed per session rather than stored:

  - "CURRENT TIME" at the top: today's date and weekday, so "tomorrow" and
    "next week" resolve against the real calendar instead of a guess.
  - "INSTITUTE CONTACT" after the static sections: the org's phone, email,
    address and hours, so the agent stops inventing contact details.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.seed import ensure_system_ai_defaults
from ..core.timezone import now_local
from ..domain.ai_config import BASE_SECTION_KEYS, focus_key
from ..domain.organization import (
    Organization,
    address_translations_for_response,
    work_hours_translations_for_response,
)
from .tools import DEFAULT_MENU, MENUS, tools_for_menu

logger = structlog.get_logger(__name__)


@dataclass
class AgentConfig:
    system_prompt: str
    model: str
    voice: str
    temperature: float
    top_p: float
    top_k: int
    max_output_tokens: int
    response_modalities: str
    enabled_tools: list[str]
    menu: str


def normalize_menu(raw: str | None) -> str:
    """Coerce whatever arrived on the WS URL to a known menu."""
    menu = (raw or "").strip().lower()
    return menu if menu in MENUS else DEFAULT_MENU


def _format_today_block(now: datetime | None = None) -> str:
    """Today's date and weekday in institute-local time.

    Without this the model has no calendar at all, and "tomorrow's timetable"
    silently becomes whichever day it feels like. Local time, not UTC: at 02:00
    Tashkent the UTC date is still yesterday, which would show the wrong day's
    classes to the night-shift cleaner who taps the screen.
    """
    local = now or now_local()
    return (
        "===== CURRENT TIME =====\n"
        f"Today is {local.date().isoformat()} ({local.strftime('%A')}), "
        f"local time {local.strftime('%H:%M')} in Nukus (UTC+5).\n"
        "Resolve \"today\", \"tomorrow\" and \"this week\" against this date."
    )


def _pick(d: dict[str, str], preferred: str = "uz") -> str:
    """Institute records are predominantly Uzbek Latin, so that is the
    fallback order for a prompt block the model reads once."""
    v = d.get(preferred)
    if isinstance(v, str) and v.strip():
        return v
    for k in ("uz", "en", "ru", "kk"):
        alt = d.get(k)
        if isinstance(alt, str) and alt.strip():
            return alt
    return ""


def _format_org_contact_block(org: Organization) -> str:
    """The institute's real contact details.

    Present so the agent has somewhere to read them FROM. Without it the model
    fills the gap with plausible-looking invented numbers, which is worse than
    saying it does not know. Empty fields render as "—" rather than being
    omitted, so the agent never sees a half-empty section and completes it
    itself.
    """
    address = _pick(address_translations_for_response(org)) or "—"
    hours = _pick(work_hours_translations_for_response(org)) or "—"
    phone = (org.helpline_phone or "").strip() or "—"
    email = (org.email or "").strip() or "—"
    return (
        "===== INSTITUTE CONTACT =====\n"
        f"Phone: {phone}\n"
        f"Email: {email}\n"
        f"Address: {address}\n"
        f"Working hours: {hours}\n"
        "Give ONLY these details. If one of them is «—», say the institute has "
        "not published it rather than offering another number."
    )


async def load_agent_config(
    session: AsyncSession, org_id: uuid.UUID, menu: str | None = None
) -> AgentConfig:
    defaults = await ensure_system_ai_defaults(session)
    resolved_menu = normalize_menu(menu)

    by_key = {
        str(s.get("section_key", "")): s for s in (defaults.default_sections or [])
    }

    wanted = [*BASE_SECTION_KEYS, focus_key(resolved_menu)]
    chosen = [by_key[k] for k in wanted if k in by_key]
    chosen.sort(key=lambda s: int(s.get("order", 0)))

    missing = [k for k in wanted if k not in by_key]
    if missing:
        # A section the super admin deleted, or a menu with no focus block yet.
        # The session still runs on whatever is left rather than failing — a
        # silent kiosk is worse than a slightly thinner prompt.
        logger.warning(
            "prompt_sections_missing", menu=resolved_menu, missing=missing
        )

    pieces: list[str] = [_format_today_block()]
    pieces.extend(
        content for s in chosen if (content := str(s.get("content", "")).strip())
    )

    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is not None:
        pieces.append(_format_org_contact_block(org))

    # The menu decides which tools are RELEVANT; the super admin's `enabled`
    # flag can still switch one off globally (e.g. to stop taking appeals for a
    # week). A tool_key absent from default_tools is treated as enabled so a
    # newly added tool works before anyone touches the panel.
    disabled = {
        str(t.get("tool_key", ""))
        for t in (defaults.default_tools or [])
        if not t.get("enabled", True)
    }
    enabled_tools = [t for t in tools_for_menu(resolved_menu) if t not in disabled]

    return AgentConfig(
        system_prompt="\n\n".join(pieces),
        model=defaults.model,
        voice=defaults.voice,
        temperature=defaults.temperature,
        top_p=defaults.top_p,
        top_k=defaults.top_k,
        max_output_tokens=defaults.max_output_tokens,
        response_modalities=defaults.response_modalities,
        enabled_tools=enabled_tools,
        menu=resolved_menu,
    )
