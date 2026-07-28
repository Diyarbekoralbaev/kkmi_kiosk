"""Authenticated kiosk WebSocket endpoint.

Audio path: kiosk → 16kHz PCM mono Int16 LE binary frames.
Outbound:   24kHz PCM mono Int16 LE binary frames.
Control:    JSON text frames in both directions.

Auth: signed-nonce header set by the kiosk just before connect (same mechanism
as every other kiosk endpoint). Org resolution derives from the device.

Menu scoping: the kiosk appends `?menu=<name>` for the tile the visitor tapped.
That one value picks the prompt's focus block AND the declared tool set — see
ai/tools.MENU_TOOLS. It arrives on a URL, so it is untrusted: anything unknown
falls back to the general assistant.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..ai.appointments import (
    build_verify_url,
    create_appointment,
    normalize_phone,
    reference_no,
)
from ..ai.audio_pipeline import (
    AudioPipelineState,
    is_output_suppressed,
    on_agent_audio_chunk,
    on_agent_audio_done,
    process_inbound,
)
from ..ai.gemini_live import (
    AudioDone,
    AudioOut,
    GeminiLiveSession,
    ProviderClosed,
    ProviderErrorEvent,
    ToolCallEvent,
    Transcript,
)
from ..ai.kaa_voice import KaaVoiceSession
from ..ai.prompt_builder import (
    format_language_block,
    load_agent_config,
    normalize_lang,
    normalize_menu,
)
from ..ai.tools import MENUS
from ..core import schedule as schedule_q
from ..core.config import get_settings
from ..core.connection_registry import registry
from ..core.db import AsyncSessionLocal
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import AppError, ProviderError
from ..core.timezone import today_local
from ..domain.ai_config import OrgKbOfficial
from ..domain.application import KIND_MURAJAAT, STATUS_NEW, Application
from ..domain.device import Device
from ..domain.organization import Organization
from ..domain.session import VoiceSession

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["kiosk"])

# Screens navigate_to_screen may ask for. The tool's JSON-schema enum is the
# real source of truth; this is a server-side backstop against a model misfire.
# "home" is the safe fallback.
_VALID_SCREENS = {"home", "contacts", *MENUS}


@router.websocket("/ws/kiosk/voice")
async def kiosk_voice(ws: WebSocket) -> None:
    auth_header = ws.headers.get(AUTH_HEADER_NAME)
    try:
        async with AsyncSessionLocal() as auth_session:
            async with auth_session.begin():
                device = await resolve_device_from_signed_request(
                    auth_session, auth_header
                )
    except AppError as e:
        # Reject pre-accept; the kiosk surfaces this as a connection failure.
        logger.info("kiosk_ws_rejected", code=e.code)
        await ws.close(code=1008)
        return

    await ws.accept()
    call_id = f"kiosk-{uuid.uuid4().hex[:12]}"
    menu = normalize_menu(ws.query_params.get("menu"))
    # The language the visitor picked on the kiosk. It has to arrive at connect
    # time, not later: the agent speaks FIRST (see the [START] turn below), so
    # by the time a mid-session message could tell it, it has already greeted
    # the visitor in the wrong language.
    lang = normalize_lang(ws.query_params.get("lang"))
    structlog.contextvars.bind_contextvars(
        call_id=call_id, device_id=str(device.id), menu=menu, lang=lang
    )
    logger.info("kiosk_ws_connected")

    org_id = device.org_id
    device_id = device.id

    # Register this socket so super-admin revoke can force-close it.
    await registry.register(device_id, ws)

    async with AsyncSessionLocal() as session:
        agent_config = await load_agent_config(session, org_id, menu, lang)

    settings = get_settings()
    _use_kaa = settings.voice_backend == "kaa" and bool(settings.kaa_ws_url)

    started_at = datetime.now(UTC)
    session_pk = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                VoiceSession(
                    id=session_pk,
                    org_id=org_id,
                    device_id=device_id,
                    call_id=call_id,
                    started_at=started_at,
                    provider=("kaa" if _use_kaa else "google_live"),
                    model=agent_config.model,
                )
            )
            d = (
                await session.execute(select(Device).where(Device.id == device_id))
            ).scalar_one()
            d.last_seen_at = started_at

    transcript_lines: list[str] = []
    error_code: str | None = None

    # Gemini 3.1 Live never sets `finished`/`isFinal` on its transcription
    # objects — every chunk arrives as a partial. Appending only on ev.final
    # therefore recorded NOTHING, and every voice_sessions.transcript came out
    # empty (the gov panel's session view had nothing to show). Accumulate per
    # speaker and flush at the turn boundary instead.
    #
    # The buffer keeps the RAW text: Gemini streams word fragments whose leading
    # space is the only thing separating words, so stripping each chunk before
    # concatenating glues the sentence into "xushkelibsiz".
    transcript_buf: dict[str, str] = {"user": "", "assistant": ""}

    def _flush_transcript() -> None:
        # user first, then assistant: that is the order a turn actually happens.
        for spk in ("user", "assistant"):
            line = transcript_buf[spk].strip()
            if line:
                transcript_lines.append(f"[{spk}] {line}")
            transcript_buf[spk] = ""

    # What the agent last put on screen for review. `submit_*` falls back to it
    # for any field the model omits in between — after a long exchange it
    # routinely drops a value collected several turns ago, and without the echo
    # the filed record would silently lose that field.
    last_preview: dict[str, dict[str, Any]] = {"murojat": {}, "reception": {}}

    # Group ids the agent was actually offered by find_group. show_schedule
    # refuses anything else: a hallucinated id would send the visitor to the
    # wrong room, the worst failure this flow has.
    offered_groups: set[int] = set()

    audio_state = AudioPipelineState()

    gemini = (
        KaaVoiceSession(config=agent_config, ws_url=settings.kaa_ws_url)
        if _use_kaa
        else GeminiLiveSession(config=agent_config)
    )
    try:
        await gemini.start()
    except ProviderError as e:
        await ws.send_json(
            {"type": "error", "code": e.code, "message": e.public_message}
        )
        await ws.close(code=1011)
        await _finalize_session(
            session_pk, started_at, transcript_lines, error_code=e.code
        )
        return

    inbound_task = asyncio.create_task(gemini.run())

    # Gemini Live waits for client input before its first response, and audio
    # alone is an unreliable trigger. `[START]` is the empty user turn that
    # licenses the agent to greet; what it says comes from the prompt.
    await gemini.send_text("[START]")

    async def _push(payload: dict[str, Any]) -> None:
        with contextlib_suppress():
            await ws.send_json(payload)

    async def _handle_event(ev: Any) -> None:
        nonlocal error_code
        if isinstance(ev, AudioOut):
            # Drop tail audio inside the post-TTS echo-suppression window so the
            # speaker tail can't be re-heard by the mic on the next turn.
            if is_output_suppressed(audio_state):
                return
            on_agent_audio_chunk(audio_state)
            with contextlib_suppress():
                await ws.send_bytes(ev.pcm)
        elif isinstance(ev, Transcript):
            raw = ev.text or ""
            speaker = ev.speaker if ev.speaker in transcript_buf else "assistant"
            if raw.strip():
                transcript_buf[speaker] += raw
                await _push(
                    {
                        "type": "transcript",
                        "text": raw.strip(),
                        "final": ev.final,
                        "speaker": speaker,
                    }
                )
            if ev.final:
                _flush_transcript()
        elif isinstance(ev, AudioDone):
            on_agent_audio_done(audio_state)
            # End of the agent's turn — the reliable boundary, since the
            # provider does not mark transcripts final.
            _flush_transcript()
            await _push({"type": "audio_done"})
        elif isinstance(ev, ToolCallEvent):
            await _dispatch_tool(ev)
        elif isinstance(ev, ProviderClosed):
            await _push({"type": "disconnected"})
        elif isinstance(ev, ProviderErrorEvent):
            error_code = ev.code
            await _push(
                {"type": "error", "code": ev.code, "message": "provider_error"}
            )

    def _merge(
        kind: str, args: dict[str, Any], fields: tuple[str, ...]
    ) -> dict[str, Any]:
        """Field set for a preview/submit pair, falling back to the last preview
        for anything the model dropped in between."""
        prev = last_preview[kind]
        out: dict[str, Any] = {}
        for key in fields:
            value = args.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                value = prev.get(key)
            out[key] = "" if value is None else value
        return out

    # ── Schedule helpers ─────────────────────────────────────────────────────

    async def _schedule_payload(group_id: int, scope: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as s:
            day_from, day_to = await schedule_q.scope_range(s, group_id, scope)
            group = await schedule_q.group_by_id(s, group_id)
            lessons = await schedule_q.lessons_for_group(s, group_id, day_from, day_to)
            empty_reason = ""
            if not lessons:
                # "No class that day" and "the year isn't loaded" look identical
                # on screen but need opposite explanations — and over the summer
                # break the second is the normal case, so it must not read as a
                # broken kiosk.
                today = today_local()
                upcoming = await schedule_q.lessons_for_group(
                    s, group_id, today, today + timedelta(days=365)
                )
                empty_reason = (
                    "no_lessons_that_day" if upcoming else "year_not_published"
                )
        return {
            "group": group or {"id": group_id, "name": ""},
            "scope": scope,
            "range": {"from": day_from.isoformat(), "to": day_to.isoformat()},
            "lessons": lessons,
            "empty_reason": empty_reason,
        }

    # ── Tool dispatch ────────────────────────────────────────────────────────

    async def _dispatch_tool(ev: ToolCallEvent) -> None:
        name = ev.name
        args = ev.args or {}

        if name == "navigate_to_screen":
            screen = str(args.get("screen", "home"))
            if screen not in _VALID_SCREENS:
                screen = "home"
            await _push({"type": "navigate", "screen": screen})
            await gemini.send_tool_response(
                ev.call_id, name, {"status": "ok", "screen": screen}
            )

        elif name == "show_info_card":
            bullets = [
                str(b).strip() for b in (args.get("bullets") or []) if str(b).strip()
            ][:6]
            title = str(args.get("title", "")).strip()
            await _push({"type": "show_info_card", "title": title, "bullets": bullets})
            await gemini.send_tool_response(
                ev.call_id, name, {"status": "ok", "shown": True}
            )

        elif name == "find_group":
            query = str(args.get("query", "")).strip()
            async with AsyncSessionLocal() as s:
                candidates = await schedule_q.find_groups(s, query)
            # Only ids the agent was actually offered become usable.
            offered_groups.update(int(c["id"]) for c in candidates)
            await _push(
                {"type": "show_group_choices", "query": query, "items": candidates}
            )
            logger.info("find_group", query_len=len(query), hits=len(candidates))
            await gemini.send_tool_response(
                ev.call_id,
                name,
                {
                    "status": "ok",
                    "candidates": candidates,
                    "next_step": (
                        "confirm the group aloud before calling show_schedule"
                        if candidates
                        else "no match — ask the visitor to repeat the group name"
                    ),
                },
            )

        elif name == "show_schedule":
            try:
                group_id = int(args.get("group_id"))
            except (TypeError, ValueError):
                await gemini.send_tool_response(
                    ev.call_id, name, {"status": "error", "code": "bad_group_id"}
                )
                return
            if group_id not in offered_groups:
                # The model invented an id, or skipped find_group entirely.
                logger.warning("show_schedule_unoffered_group", group_id=group_id)
                await gemini.send_tool_response(
                    ev.call_id,
                    name,
                    {
                        "status": "error",
                        "code": "group_not_confirmed",
                        "next_step": "call find_group first and confirm the match",
                    },
                )
                return
            scope = str(args.get("scope", "today"))
            if scope not in schedule_q.SCOPES:
                scope = "today"
            payload = await _schedule_payload(group_id, scope)
            await _push({"type": "show_schedule", **payload})
            await gemini.send_tool_response(
                ev.call_id, name, {"status": "ok", **payload}
            )

        elif name == "show_directions":
            async with AsyncSessionLocal() as s:
                items = await schedule_q.specialties(s)
            await _push({"type": "show_directions", "items": items})
            await gemini.send_tool_response(
                ev.call_id, name, {"status": "ok", "items": items}
            )

        elif name == "show_direction":
            try:
                specialty_id = int(args.get("specialty_id"))
            except (TypeError, ValueError):
                await gemini.send_tool_response(
                    ev.call_id, name, {"status": "error", "code": "bad_specialty_id"}
                )
                return
            async with AsyncSessionLocal() as s:
                items = await schedule_q.specialties(s)
            item = next((i for i in items if i["id"] == specialty_id), None)
            if item is None:
                await gemini.send_tool_response(
                    ev.call_id, name, {"status": "error", "code": "not_found"}
                )
                return
            await _push({"type": "show_direction", "item": item})
            await gemini.send_tool_response(
                ev.call_id, name, {"status": "ok", "item": item}
            )

        elif name == "show_leadership":
            items = await _leadership(org_id)
            await _push({"type": "show_leadership", "items": items})
            await gemini.send_tool_response(
                ev.call_id, name, {"status": "ok", "items": items}
            )

        elif name == "preview_murojat":
            fields = _merge("murojat", args, ("full_name", "phone", "topic", "text"))
            last_preview["murojat"] = dict(fields)
            logger.info(
                "preview_murojat",
                phone_len=len(str(fields["phone"])),
                text_len=len(str(fields["text"])),
            )
            await _push({"type": "murojat_preview", **fields})
            await gemini.send_tool_response(
                ev.call_id,
                name,
                {
                    "status": "ok",
                    "shown": True,
                    "next_step": (
                        "the card is on screen — ask whether it is correct, and "
                        "on a clear yes call submit_murojat with the same values"
                    ),
                },
            )

        elif name == "submit_murojat":
            fields = _merge("murojat", args, ("full_name", "phone", "topic", "text"))
            if not fields["text"] or not fields["phone"]:
                await gemini.send_tool_response(
                    ev.call_id, name, {"status": "error", "code": "missing_fields"}
                )
                return
            try:
                reference = await _store_murojat(org_id, session_pk, fields)
            except Exception:
                logger.exception("submit_murojat_failed")
                await gemini.send_tool_response(
                    ev.call_id, name, {"status": "error", "code": "E_DB_001"}
                )
                await _push(
                    {"type": "error", "code": "E_DB_001", "message": "submit_failed"}
                )
                return
            last_preview["murojat"] = {}
            await _push(
                {
                    "type": "murojat_submitted",
                    "reference": reference,
                    "full_name": fields["full_name"],
                }
            )
            await gemini.send_tool_response(
                ev.call_id,
                name,
                {
                    "status": "ok",
                    "reference": reference,
                    "next_step": (
                        f"appeal filed (reference {reference}). Read the reference "
                        "back and say staff will contact them."
                    ),
                },
            )

        elif name == "preview_reception":
            fields = _merge(
                "reception", args, ("official_id", "full_name", "phone", "reason")
            )
            official = await _official(org_id, str(fields["official_id"]))
            if official is None:
                await gemini.send_tool_response(
                    ev.call_id,
                    name,
                    {
                        "status": "error",
                        "code": "unknown_official",
                        "next_step": "call show_leadership and pick from that list",
                    },
                )
                return
            last_preview["reception"] = dict(fields)
            await _push({"type": "reception_preview", **fields, "official": official})
            await gemini.send_tool_response(
                ev.call_id,
                name,
                {
                    "status": "ok",
                    "shown": True,
                    "official": official,
                    "next_step": (
                        "ask whether it is correct, and on a clear yes call "
                        "submit_reception with the same values"
                    ),
                },
            )

        elif name == "submit_reception":
            fields = _merge(
                "reception", args, ("official_id", "full_name", "phone", "reason")
            )
            official = await _official(org_id, str(fields["official_id"]))
            if official is None:
                await gemini.send_tool_response(
                    ev.call_id, name, {"status": "error", "code": "unknown_official"}
                )
                return
            if not fields["phone"]:
                await gemini.send_tool_response(
                    ev.call_id, name, {"status": "error", "code": "missing_fields"}
                )
                return
            try:
                booked = await _store_reception(org_id, session_pk, fields)
            except Exception:
                logger.exception("submit_reception_failed")
                await gemini.send_tool_response(
                    ev.call_id, name, {"status": "error", "code": "E_DB_001"}
                )
                return
            last_preview["reception"] = {}
            await _push({"type": "reception_submitted", **booked, "official": official})
            await gemini.send_tool_response(
                ev.call_id,
                name,
                {
                    "status": "ok",
                    **booked,
                    "official": official,
                    "next_step": (
                        "read back the reference and the reception day/time; the "
                        "ticket is printing"
                    ),
                },
            )

        else:
            # Reachable if the model hallucinates a tool from another menu.
            logger.warning("unknown_tool_call", name=name)
            await gemini.send_tool_response(
                ev.call_id, name, {"status": "error", "code": "unknown_tool"}
            )

    async def _consume_events() -> None:
        # CRITICAL: one handler exception must NOT kill this task, or the kiosk
        # silently stops receiving audio for the rest of the session. Catch per
        # event so a tool bug becomes a warning, not a dead session.
        async for ev in gemini.events():
            try:
                await _handle_event(ev)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "kiosk_ws_event_handler_failed", event_type=type(ev).__name__
                )

    consumer_task = asyncio.create_task(_consume_events())

    async def _periodic_revoke_recheck() -> None:
        """Defensive: re-validate the device every 60 s in case the registry
        missed a revoke (e.g. a backend restart between revoke and reconnect)."""
        while True:
            await asyncio.sleep(60)
            try:
                async with AsyncSessionLocal() as s:
                    async with s.begin():
                        d = (
                            await s.execute(
                                select(Device).where(Device.id == device_id)
                            )
                        ).scalar_one_or_none()
                        if d is None or d.status != "active":
                            logger.info(
                                "ws_recheck_failed_closing", device_id=str(device_id)
                            )
                            await ws.close(code=1008, reason="device_inactive")
                            return
            except Exception:
                logger.exception("ws_recheck_error")
                # Soft-fail: don't tear down on a transient DB hiccup.

    recheck_task = asyncio.create_task(_periodic_revoke_recheck())

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data: bytes | None = msg.get("bytes")
            text: str | None = msg.get("text")
            if data is not None:
                # Full inbound pipeline (DC-offset → TTS gating → squelch).
                # Same length out; non-speech regions become zeros.
                processed = process_inbound(audio_state, data)
                await gemini.send_audio(processed, sample_rate=16000)
            elif text:
                # `user_text` lets a touch action speak for the visitor — e.g.
                # tapping "Confirm" on a preview card sends the affirmative so
                # the agent fires submit_* naturally. Anything else is ignored;
                # server VAD owns turn detection.
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                msg_type = str(payload.get("type", ""))
                if msg_type == "user_text":
                    user_text = str(payload.get("text", "")).strip()
                    if user_text:
                        await gemini.send_text(user_text)
                elif msg_type == "ui_language":
                    # The visitor tapped a different language mid-session. The
                    # system prompt is fixed once the provider session opens, so
                    # the switch is delivered as a side-channel instruction
                    # rather than a reconnect — reconnecting would drop the
                    # conversation and re-greet from scratch.
                    #
                    # Previously this envelope was received and silently
                    # dropped: the kiosk sent it on every language change and
                    # the agent never heard about it, so the buttons had no
                    # effect on speech at all.
                    new_lang = normalize_lang(payload.get("language"))
                    logger.info("ui_language_changed", new_lang=new_lang)
                    await gemini.send_text(
                        f"[SYSTEM] {format_language_block(new_lang)} "
                        "Continue the conversation in that language from now on. "
                        "Do not greet again."
                    )
    except WebSocketDisconnect:
        logger.info("kiosk_ws_disconnected")
    except Exception:
        logger.exception("kiosk_ws_error")
        error_code = "E_INT_999"
    finally:
        # A visitor who walks off mid-answer leaves the last turn unflushed.
        _flush_transcript()
        await registry.unregister(device_id, ws)
        await gemini.close()
        for task in (inbound_task, consumer_task, recheck_task):
            task.cancel()
        # `await task` on a cancelled task raises CancelledError, which derives
        # from BaseException — so contextlib.suppress(Exception) does NOT catch
        # it. The previous version awaited each task inside that suppressor, so
        # the very first one propagated out of this finally block and
        # _finalize_session never ran: every session row was left with a NULL
        # ended_at, NULL duration and an empty transcript. gather with
        # return_exceptions collects the cancellations instead of raising.
        await asyncio.gather(
            inbound_task, consumer_task, recheck_task, return_exceptions=True
        )
        await _finalize_session(session_pk, started_at, transcript_lines, error_code)


# ── DB helpers (each owns its session; called from the event loop) ────────────


def _official_dict(o: OrgKbOfficial) -> dict[str, Any]:
    return {
        "id": str(o.id),
        "name": o.name,
        "position": o.position,
        "reception_day": o.reception_day,
        "reception_time": o.reception_time,
    }


async def _leadership(org_id: uuid.UUID) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(OrgKbOfficial)
                .where(OrgKbOfficial.org_id == org_id)
                .order_by(OrgKbOfficial.order, OrgKbOfficial.name)
            )
        ).scalars()
        return [_official_dict(o) for o in rows]


async def _official(org_id: uuid.UUID, official_id: str) -> dict[str, Any] | None:
    """Resolve an official id the model passed back. Scoped to the device's org
    so a malformed or stale id can never reach another tenant's record."""
    try:
        pk = uuid.UUID(official_id)
    except (ValueError, AttributeError, TypeError):
        return None
    async with AsyncSessionLocal() as s:
        o = (
            await s.execute(
                select(OrgKbOfficial).where(
                    OrgKbOfficial.id == pk, OrgKbOfficial.org_id == org_id
                )
            )
        ).scalar_one_or_none()
    return _official_dict(o) if o is not None else None


async def _store_murojat(
    org_id: uuid.UUID, session_pk: uuid.UUID, fields: dict[str, Any]
) -> str:
    """Insert the appeal; return its human-facing reference."""
    app_id = uuid.uuid4()
    async with AsyncSessionLocal() as s:
        async with s.begin():
            s.add(
                Application(
                    id=app_id,
                    org_id=org_id,
                    session_id=session_pk,
                    applicant_name=str(fields["full_name"]).strip()[:255],
                    topic=(str(fields["topic"]).strip() or "Murojat")[:500],
                    body=str(fields["text"]).strip(),
                    phone=normalize_phone(str(fields["phone"])),
                    status=STATUS_NEW,
                    kind=KIND_MURAJAAT,
                )
            )
    return f"M-{app_id.hex[:8].upper()}"


async def _store_reception(
    org_id: uuid.UUID, session_pk: uuid.UUID, fields: dict[str, Any]
) -> dict[str, Any]:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            org = (
                await s.execute(select(Organization).where(Organization.id == org_id))
            ).scalar_one()
            created = await create_appointment(
                s,
                org=org,
                visitor_name=str(fields["full_name"]),
                visitor_phone=str(fields["phone"]),
                topic_summary=str(fields["reason"]),
                source="kiosk",
                official_id=uuid.UUID(str(fields["official_id"])),
                voice_session_id=session_pk,
            )
            return {
                "reference": reference_no(created.appointment),
                "verify_url": build_verify_url(created.appointment.verification_token),
            }


async def _finalize_session(
    session_pk: uuid.UUID,
    started_at: datetime,
    transcript_lines: list[str],
    error_code: str | None,
) -> None:
    ended_at = datetime.now(UTC)
    duration = int((ended_at - started_at).total_seconds())
    transcript = "\n".join(transcript_lines)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            row = (
                await s.execute(
                    select(VoiceSession).where(VoiceSession.id == session_pk)
                )
            ).scalar_one_or_none()
            if row is None:
                return
            row.ended_at = ended_at
            row.duration_seconds = duration
            row.transcript = transcript
            row.error_code = error_code


def contextlib_suppress():
    """Tiny helper: contextlib.suppress(Exception). Keeps call sites short."""
    return contextlib.suppress(Exception)
