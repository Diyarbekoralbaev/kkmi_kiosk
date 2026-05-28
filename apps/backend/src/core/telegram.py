"""Telegram broadcast bot — posts every new murajaat and qabul to two
channels so the back-office staff see arrivals in real time.

Architecture (operator decision, May 2026):
  - One bot (`@nukus_gov_notify_bot`) is admin in two broadcast channels.
  - Channel 1 = all murajaatlar, regardless of category / official.
  - Channel 2 = all qabul bookings.
  - No per-category routing, no status-change notifications — only the
    initial create event.
  - Posts are fire-and-forget from the kiosk submit path: an
    `asyncio.create_task(...)` queues the HTTP call after the audit row
    is committed, so a Telegram outage cannot block a citizen's
    submission.

If `TELEGRAM_BOT_TOKEN` is unset, every public function becomes a no-op
(dev and staging stay clean without needing real bot credentials).
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import structlog

from ..domain.ai_config import OrgKbOfficial
from ..domain.appointment import Appointment
from ..domain.application import Application
from ..domain.organization import Organization
from .config import get_settings
from .timezone import now_local

logger = structlog.get_logger(__name__)

# Telegram Bot API. `sendMessage` is enough for our broadcast use case —
# no media, no inline keyboards, no edits. Body capped at 4096 chars.
#
# `_api_base()` is read from settings so prod can redirect to a CF
# Worker relay (api.telegram.org is blocked from the Moscow IP). The
# Worker forwards method+path+body verbatim, so flipping the base URL
# is the only change needed on the call site.
_SEND_TIMEOUT_SECONDS = 8.0


def _is_configured() -> bool:
    """True iff the bot is fully wired (token + at least one channel).
    Falsy → every public function logs and returns without an HTTP call,
    so dev / staging deployments don't try to call api.telegram.org."""
    s = get_settings()
    token = s.telegram_bot_token.get_secret_value() if s.telegram_bot_token else ""
    return bool(token)


async def _send(chat_id: str, text: str) -> None:
    """Single sendMessage HTTP call. Logs failures with the response
    body for diagnosis but never raises — caller is fire-and-forget and
    has no way to retry usefully (the citizen's submit already succeeded).

    parse_mode is intentionally absent: we ship plain text so we don't
    have to escape Markdown / HTML metacharacters in visitor-typed
    topic/body strings (a `*` or `_` in a topic would crash MarkdownV2
    rendering)."""
    if not chat_id:
        return
    s = get_settings()
    token = s.telegram_bot_token.get_secret_value()
    if not token:
        return
    api_base = s.telegram_api_base.rstrip("/") or "https://api.telegram.org"
    url = f"{api_base}/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:4000],  # Telegram hard cap is 4096; trim with a safety margin
        "disable_web_page_preview": True,
        "disable_notification": False,
    }
    # CF Worker relay (prod) gates traffic via X-Relay-Auth; direct calls
    # to api.telegram.org ignore the header. Always set it when the
    # token is configured so a misconfigured base URL still gets past
    # the gate — easier than conditionally branching on the URL.
    relay_token = s.telegram_relay_token.get_secret_value()
    headers = {"X-Relay-Auth": relay_token} if relay_token else None
    try:
        async with httpx.AsyncClient(timeout=_SEND_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.warning(
                    "telegram_send_failed",
                    chat_id=chat_id,
                    status=resp.status_code,
                    body=resp.text[:500],
                )
            else:
                logger.info(
                    "telegram_send_ok", chat_id=chat_id, text_len=len(text)
                )
    except Exception as ex:  # network down, DNS, Cloudflare blip — log + drop
        logger.warning(
            "telegram_send_exception",
            chat_id=chat_id,
            error=str(ex),
            error_type=type(ex).__name__,
        )


def _short_id(value: uuid.UUID | str) -> str:
    """First 8 chars of a UUID for human-readable reference. Full ID is
    in the audit log + gov-panel; the short form is enough for staff to
    find the row in the panel via search."""
    s = str(value)
    return s[:8] if len(s) >= 8 else s


def _now_str() -> str:
    """Timestamp tag on every post — Tashkent local time (UTC+5), so staff see
    the real arrival time, not the server's UTC clock (which was 5h behind)."""
    return now_local().strftime("%d-%m-%Y %H:%M")


def _format_murajaat(
    app: Application,
    category_slug: str,
    org: Organization,
) -> str:
    """Plain-text post body. Slug is passed in as a string so this
    module doesn't need a DB session to load ApplicationCategory — the
    caller already has the slug from the request payload."""
    lines = [
        "📋 ЖАҢА МҮРӘЖАТ",
        "",
        f"Тема: {app.topic}",
        f"Категория: {category_slug or 'other'}",
        "",
        "Мазмуны:",
        app.body,
        "",
        f"📞 Телефон: {app.phone}",
        f"🕐 {_now_str()}",
        f"🆔 #{_short_id(app.id)}",
        f"🏢 {org.name}",
    ]
    return "\n".join(lines)


def _format_qabul(
    appt: Appointment,
    official: OrgKbOfficial,
    org: Organization,
    scheduled_date_human: str,
) -> str:
    role_label = "Ҳәким" if (official.role or "") == "chief" else "Орынбасар"
    lines = [
        "📅 ЖАҢА ҚАБЫЛ",
        "",
        f"{role_label}: {official.position}",
        f"            {official.name}",
        "",
        f"Тема: {appt.topic_summary or '—'}",
        f"Сана: {scheduled_date_human}",
        f"Ўақыты: {official.reception_time or '—'}",
        f"Гезек: №{appt.queue_number:03d}",
        "",
        f"📞 Телефон: {appt.visitor_phone}",
        f"🕐 Жазылды: {_now_str()}",
        f"🆔 #{_short_id(appt.id)}",
        f"🏢 {org.name}",
    ]
    return "\n".join(lines)


# ── Public fire-and-forget API ──────────────────────────────────────────


def post_murajaat_async(
    app: Application,
    category_slug: str,
    org: Organization,
) -> None:
    """Schedule a Telegram post for a freshly-created Application. The
    caller is expected to call this AFTER the DB transaction commits —
    posting a row that later rolls back would leave the channel out of
    sync. Returns immediately (does NOT await the HTTP call)."""
    if not _is_configured():
        return
    s = get_settings()
    if not s.telegram_murajat_channel_id:
        return
    text = _format_murajaat(app, category_slug, org)
    asyncio.create_task(_send(s.telegram_murajat_channel_id, text))


def post_qabul_async(
    appt: Appointment,
    official: OrgKbOfficial,
    org: Organization,
    scheduled_date_human: str,
) -> None:
    """Schedule a Telegram post for a freshly-created Appointment.
    See post_murajaat_async for the post-commit ordering note."""
    if not _is_configured():
        return
    s = get_settings()
    if not s.telegram_qabul_channel_id:
        return
    text = _format_qabul(appt, official, org, scheduled_date_human)
    asyncio.create_task(_send(s.telegram_qabul_channel_id, text))
