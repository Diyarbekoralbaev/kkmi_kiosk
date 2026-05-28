"""Authenticated kiosk WebSocket endpoint.

Audio path: kiosk → 16kHz PCM mono Int16 LE binary frames.
Outbound:   24kHz PCM mono Int16 LE binary frames.
Control:    JSON text frames in both directions.

Auth: `Authorization: Bearer <device_key>` (issued via /api/kiosk/enroll).
Org resolution: derived from the authenticated device's org_id.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

import base64

from ..ai.appointments import create_appointment, mask_phone, render_appointment_artifacts
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
from ..ai.prompt_builder import load_agent_config
from ..ai.receipt import format_date_kk
from ..core import audit, telegram
from ..core.connection_registry import registry
from ..core.db import AsyncSessionLocal
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import AppError, ProviderError
from ..domain.ai_config import OrgKbOfficial
# Application row insert + category_slug resolution moved to
# ai/applications.create_application() so voice + manual flows share
# the same helper. Imports removed here.
from ..domain.device import Device
from ..domain.organization import Organization, name_translations_for_response
from ..domain.session import VoiceSession

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["kiosk"])


@router.websocket("/ws/kiosk/voice")
async def kiosk_voice(ws: WebSocket) -> None:
    # WS upgrade carries the signed-nonce header set by the kiosk client just
    # before connect (see SignedHttpClient on the C# side). The same auth
    # mechanism every other kiosk endpoint uses.
    auth_header = ws.headers.get(AUTH_HEADER_NAME)
    try:
        async with AsyncSessionLocal() as auth_session:
            async with auth_session.begin():
                device = await resolve_device_from_signed_request(
                    auth_session, auth_header
                )
    except AppError as e:
        # Reject pre-accept; the kiosk client surfaces this as a connection failure.
        logger.info("kiosk_ws_rejected", code=e.code)
        await ws.close(code=1008)
        return

    await ws.accept()
    call_id = f"kiosk-{uuid.uuid4().hex[:12]}"
    structlog.contextvars.bind_contextvars(call_id=call_id, device_id=str(device.id))
    logger.info("kiosk_ws_connected")

    org_id = device.org_id
    device_id = device.id

    # Register this socket so super-admin revoke can force-close it.
    await registry.register(device_id, ws)

    # Load agent config from DB
    async with AsyncSessionLocal() as session:
        agent_config = await load_agent_config(session, org_id)

    # Persist session row up-front + bump device.last_seen_at
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
                    provider="google_live",
                    model=agent_config.model,
                )
            )
            d = (
                await session.execute(select(Device).where(Device.id == device_id))
            ).scalar_one()
            d.last_seen_at = started_at

    transcript_lines: list[str] = []
    error_code: str | None = None
    last_preview: dict[str, str] = {}
    # Per-session collected state for the qabul flow. Filled incrementally by
    # appointment_progress stage calls + the preview/submit handlers. Echoed
    # back in every tool response so Gemini can read "what I've collected so
    # far" without having to recall it from drift-prone audio context. The
    # state-echo pattern is documented in Anthropic's context-engineering
    # post and the Fora Soft production voice-agent guide; for our case it
    # specifically prevents the "agent forgets phone was already given,
    # re-asks or invents one" failure mode after long sessions.
    appt_state: dict[str, str | None] = {
        "topic": None,
        "official_id": None,
        "official_name": None,
        "phone": None,
    }
    audio_state = AudioPipelineState()

    # Track the kiosk's current UI language for receipt rendering. Defaults
    # to the org's configured locale (kk/uz/ru) until the kiosk sends a
    # `ui_language` envelope. Re-fetch the latest org row to pick up live
    # admin edits — cheap, single column lookup.
    async with AsyncSessionLocal() as _ses:
        _org_row = (
            await _ses.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one_or_none()
    ui_language: str = (
        (_org_row.locale if _org_row and _org_row.locale else "kk").lower()
    )

    gemini = GeminiLiveSession(config=agent_config)
    try:
        await gemini.start()
    except ProviderError as e:
        await ws.send_json({"type": "error", "code": e.code, "message": e.public_message})
        await ws.close(code=1011)
        await _finalize_session(
            session_pk, started_at, transcript_lines, error_code=e.code
        )
        return

    inbound_task = asyncio.create_task(gemini.run())

    # Kick off the agent's first turn with a single neutral start signal.
    # Gemini Live waits for any client input before producing its first
    # response, and audio alone is unreliable to act as that trigger.
    # The prompt's `greeting` section is what the agent says back; this
    # `[START]` is just the empty user turn that licenses it to begin.
    # There are NO per-screen context messages — page navigation is silent.
    await gemini.send_text("[START]")

    async def _handle_event(ev: Any) -> None:
        nonlocal error_code
        if isinstance(ev, AudioOut):
            # Drop tail audio inside the post-TTS echo-suppression window
            # so the speaker tail can't be re-heard by the mic on the next turn.
            if is_output_suppressed(audio_state):
                return
            on_agent_audio_chunk(audio_state)
            with contextlib_suppress():
                await ws.send_bytes(ev.pcm)
        elif isinstance(ev, Transcript):
            text = (ev.text or "").strip()
            if text:
                if ev.final:
                    transcript_lines.append(f"[{ev.speaker}] {text}")
                with contextlib_suppress():
                    await ws.send_json(
                        {
                            "type": "transcript",
                            "text": text,
                            "final": ev.final,
                            "speaker": ev.speaker,
                        }
                    )
        elif isinstance(ev, AudioDone):
            on_agent_audio_done(audio_state)
            with contextlib_suppress():
                await ws.send_json({"type": "audio_done"})
        elif isinstance(ev, ToolCallEvent):
            await _dispatch_tool(ev)
        elif isinstance(ev, ProviderClosed):
            with contextlib_suppress():
                await ws.send_json({"type": "disconnected"})
        elif isinstance(ev, ProviderErrorEvent):
            error_code = ev.code
            with contextlib_suppress():
                await ws.send_json(
                    {"type": "error", "code": ev.code, "message": "provider_error"}
                )

    # Screen names the agent's `navigate_to_screen` tool may legitimately ask
    # for. The tool's JSON-schema enum is already the source of truth, but we
    # keep a server-side allow-list as a small belt-and-suspenders against a
    # model misfire. "home" is the safe fallback.
    _VALID_SCREENS = {"home", "reception", "qabul", "submit", "contacts", "ai"}

    async def _dispatch_tool(ev: ToolCallEvent) -> None:
        if ev.name == "navigate_to_screen":
            screen = str(ev.args.get("screen", "home"))
            if screen not in _VALID_SCREENS:
                screen = "home"
            with contextlib_suppress():
                await ws.send_json({"type": "navigate", "screen": screen})
            await gemini.send_tool_response(
                ev.call_id, ev.name, {"status": "ok", "screen": screen}
            )
        elif ev.name == "preview_application":
            topic = str(ev.args.get("topic", "")).strip()
            body = str(ev.args.get("body", "")).strip()
            phone = str(ev.args.get("phone", "")).strip()
            category_slug = str(ev.args.get("category_slug", "other")).strip() or "other"
            last_preview.update(
                {"topic": topic, "body": body, "phone": phone, "category_slug": category_slug}
            )
            with contextlib_suppress():
                await ws.send_json(
                    {
                        "type": "application_preview",
                        "topic": topic,
                        "body": body,
                        "phone": phone,
                        "category_slug": category_slug,
                    }
                )
            await gemini.send_tool_response(
                ev.call_id, ev.name,
                {
                    "status": "ok",
                    "shown": True,
                    "next_step": (
                        "card is now on screen — ask «Мәтин дурыс па?» "
                        "and on visitor affirmation call "
                        "submit_application with the SAME 4 values"
                    ),
                    "preview_args": {
                        "topic": topic,
                        "body_chars": len(body),
                        "phone": phone,
                        "category_slug": category_slug,
                    },
                },
            )
        elif ev.name == "submit_application":
            topic = str(ev.args.get("topic", "")).strip()
            body = str(ev.args.get("body", "")).strip()
            phone = str(ev.args.get("phone", "")).strip()
            category_slug = str(ev.args.get("category_slug", "other")).strip() or "other"
            new_id: uuid.UUID | None = None
            try:
                async with AsyncSessionLocal() as s:
                    async with s.begin():
                        # Delegate to the shared helper so voice + manual
                        # flows produce identical Application rows. The
                        # helper assigns the UUID + handles category_slug
                        # resolution (unknown slug → NULL fallback).
                        from ..ai.applications import create_application
                        app = await create_application(
                            s,
                            org_id=org_id,
                            topic=topic,
                            body=body,
                            phone=phone,
                            category_slug=category_slug,
                            source="kiosk_voice",
                            voice_session_id=session_pk,
                        )
                        new_id = app.id
                        # Per CLAUDE.md: all write endpoints record audit.
                        # Phone goes through the no-op mask_phone for
                        # call-site consistency.
                        await audit.record(
                            s,
                            actor_user_id=None,
                            actor_org_id=org_id,
                            action="application.create",
                            entity_type="application",
                            entity_id=new_id,
                            after={
                                "topic": topic,
                                "phone_masked": mask_phone(phone),
                                "category_slug": category_slug,
                                "category_resolved": app.category_id is not None,
                                "source": "kiosk_voice",
                                "session_id": str(session_pk),
                            },
                        )
                with contextlib_suppress():
                    await ws.send_json(
                        {
                            "type": "application_submitted",
                            "id": str(new_id),
                            "topic": topic,
                            "body": body,
                            "phone": phone,
                            "category_slug": category_slug,
                        }
                    )
                # Fan out to the operator's Telegram murajat channel.
                # Fire-and-forget; `app` is detached at this point but
                # SQLAlchemy keeps its already-loaded attributes
                # readable. _org_row was loaded at WS open and is fine
                # for the post header (org name doesn't change often).
                if _org_row is not None:
                    telegram.post_murajaat_async(app, category_slug, _org_row)
                # Successful submission completes the murajat flow —
                # clear last_preview so a fresh request in the same
                # session starts from a clean slate.
                last_preview.clear()
                await gemini.send_tool_response(
                    ev.call_id, ev.name,
                    {
                        "status": "ok",
                        "submitted": True,
                        "id": str(new_id),
                        "next_step": (
                            "murajaat filed. brief acknowledgement to "
                            "the visitor, then end the turn"
                        ),
                    },
                )
            except Exception as e:
                logger.exception("submit_application_failed")
                await gemini.send_tool_response(
                    ev.call_id, ev.name, {"status": "error", "code": "E_DB_001"}
                )
                with contextlib_suppress():
                    await ws.send_json(
                        {"type": "error", "code": "E_DB_001", "message": "save_failed"}
                    )
        elif ev.name == "appointment_progress":
            await _dispatch_appointment_progress(ev)
        elif ev.name == "preview_appointment":
            await _dispatch_preview_appointment(ev)
        elif ev.name == "submit_appointment":
            await _dispatch_submit_appointment(ev)
        else:
            logger.warning("unknown_tool_call", name=ev.name)
            await gemini.send_tool_response(
                ev.call_id, ev.name, {"status": "error", "code": "unknown_tool"}
            )

    async def _resolve_official(
        s, official_id_raw: str
    ) -> tuple[OrgKbOfficial, Organization] | None:
        """Look up the official by id, scoped to the current device's org.

        Returns None if the id is malformed or the official belongs to another
        org — we never want a kiosk to address an official it can't see.
        """
        try:
            ofc_uuid = uuid.UUID(official_id_raw)
        except (ValueError, TypeError):
            return None
        ofc = (
            await s.execute(
                select(OrgKbOfficial).where(
                    OrgKbOfficial.id == ofc_uuid,
                    OrgKbOfficial.org_id == org_id,
                )
            )
        ).scalar_one_or_none()
        if ofc is None:
            return None
        org = (
            await s.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one()
        return ofc, org

    def _appt_state_echo() -> dict[str, object]:
        """Snapshot of qabul flow collected state for the tool-response
        echo. The agent reads this from the function result, so it never
        has to recall earlier-in-session values from audio context.
        `next_required` is the most-useful field: it tells the agent
        exactly what to ask for next without the agent inferring it from
        prose rules. None of the values here are PII — phone is stored
        un-masked since the agent already had it."""
        next_required = None
        if appt_state.get("topic") is None:
            next_required = "topic"
        elif appt_state.get("official_id") is None:
            next_required = "official_id"
        elif appt_state.get("phone") is None:
            next_required = "phone"
        return {
            "collected_so_far": dict(appt_state),
            "next_required": next_required,
        }

    async def _dispatch_appointment_progress(ev: ToolCallEvent) -> None:
        """Stepper-only signal — emit a JSON envelope so the kiosk can light
        the next step without waiting for the full preview. Doesn't write to
        the DB; if the AI mis-fires, nothing breaks. Also updates `appt_state`
        and echoes it back to Gemini in the tool response."""
        stage = str(ev.args.get("stage", "")).strip()
        if stage not in ("topic", "official", "phone"):
            await gemini.send_tool_response(
                ev.call_id, ev.name,
                {"status": "error", "code": "bad_stage", **_appt_state_echo()},
            )
            return

        envelope: dict[str, object] = {"type": "appointment_progress", "stage": stage}
        if stage == "topic":
            topic_val = str(ev.args.get("topic", "")).strip()
            envelope["topic"] = topic_val
            if topic_val:
                appt_state["topic"] = topic_val
        elif stage == "official":
            official_id = str(ev.args.get("official_id", "")).strip()
            resolved = None
            scheduled = None
            try:
                async with AsyncSessionLocal() as s:
                    resolved = await _resolve_official(s, official_id)
                    if resolved is not None:
                        ofc, _ = resolved
                        # Cap-aware scheduling: if the next reception day
                        # already has 25 active appointments, this rolls
                        # forward by 7 days until a free day is found, so
                        # the date we tell the visitor matches what
                        # submit_appointment will eventually book.
                        from ..ai.appointments import (
                            compute_next_available_reception_date,
                        )
                        scheduled = await compute_next_available_reception_date(
                            s, ofc
                        )
            except Exception:
                logger.exception("appointment_progress_lookup_failed")
                resolved = None
            if resolved is None or scheduled is None:
                await gemini.send_tool_response(
                    ev.call_id, ev.name,
                    {
                        "status": "error",
                        "code": "official_not_found",
                        **_appt_state_echo(),
                    },
                )
                return
            ofc, _ = resolved
            envelope["official_id"] = str(ofc.id)
            envelope["official_name"] = ofc.name
            envelope["official_position"] = ofc.position
            envelope["scheduled_date_human"] = format_date_kk(scheduled)
            envelope["reception_time"] = ofc.reception_time
            appt_state["official_id"] = str(ofc.id)
            appt_state["official_name"] = ofc.name
        elif stage == "phone":
            phone_raw = str(ev.args.get("phone", "")).strip()
            envelope["phone_masked"] = mask_phone(phone_raw)
            if phone_raw:
                appt_state["phone"] = phone_raw

        with contextlib_suppress():
            await ws.send_json(envelope)
        await gemini.send_tool_response(
            ev.call_id, ev.name,
            {"status": "ok", **_appt_state_echo()},
        )

    async def _dispatch_preview_appointment(ev: ToolCallEvent) -> None:
        official_id = str(ev.args.get("official_id", "")).strip()
        topic = str(ev.args.get("topic", "")).strip()
        phone = str(ev.args.get("phone", "")).strip()
        resolved = None
        scheduled = None
        try:
            async with AsyncSessionLocal() as s:
                resolved = await _resolve_official(s, official_id)
                if resolved is not None:
                    ofc, _ = resolved
                    # Cap-aware: roll forward to the next day with < 25
                    # active appointments. The on-screen card the visitor
                    # is about to confirm must match the day
                    # submit_appointment will actually book.
                    from ..ai.appointments import (
                        compute_next_available_reception_date,
                    )
                    scheduled = await compute_next_available_reception_date(
                        s, ofc
                    )
        except Exception:
            logger.exception("preview_appointment_lookup_failed")
            resolved = None
        if resolved is None or scheduled is None:
            await gemini.send_tool_response(
                ev.call_id, ev.name,
                {
                    "status": "error",
                    "code": "official_not_found",
                    **_appt_state_echo(),
                },
            )
            return
        ofc, _ = resolved
        # Sync appt_state with the values that just came through preview —
        # the agent may have skipped appointment_progress for one or more
        # stages, but the preview tool carries the full triple. Treat
        # preview as the canonical state.
        if topic:
            appt_state["topic"] = topic
        appt_state["official_id"] = str(ofc.id)
        appt_state["official_name"] = ofc.name
        if phone:
            appt_state["phone"] = phone
        scheduled_human = format_date_kk(scheduled)
        with contextlib_suppress():
            await ws.send_json(
                {
                    "type": "appointment_preview",
                    "official_id": str(ofc.id),
                    "official_name": ofc.name,
                    "official_position": ofc.position,
                    "scheduled_date": scheduled.isoformat(),
                    "scheduled_date_human": scheduled_human,
                    "reception_time": ofc.reception_time,
                    "phone_masked": mask_phone(phone),
                    "topic": topic,
                }
            )
        await gemini.send_tool_response(
            ev.call_id, ev.name,
            {
                "status": "ok",
                "shown": True,
                "next_step": (
                    "screen card is now visible — ask «Мағлыўматлар "
                    "дурыс па?» and on visitor affirmation call "
                    "submit_appointment with the same values"
                ),
                "official_name": ofc.name,
                "official_position": ofc.position,
                "scheduled_date_human": scheduled_human,
                "reception_time": ofc.reception_time,
                "phone_masked": mask_phone(phone),
                **_appt_state_echo(),
            },
        )

    async def _dispatch_submit_appointment(ev: ToolCallEvent) -> None:
        official_id = str(ev.args.get("official_id", "")).strip()
        topic = str(ev.args.get("topic", "")).strip()
        phone = str(ev.args.get("phone", "")).strip()
        if not topic or not phone:
            await gemini.send_tool_response(
                ev.call_id, ev.name,
                {
                    "status": "error",
                    "code": "missing_fields",
                    **_appt_state_echo(),
                },
            )
            return
        try:
            async with AsyncSessionLocal() as s:
                async with s.begin():
                    resolved = await _resolve_official(s, official_id)
                    if resolved is None:
                        await gemini.send_tool_response(
                            ev.call_id, ev.name,
                            {
                                "status": "error",
                                "code": "official_not_found",
                                **_appt_state_echo(),
                            },
                        )
                        return
                    ofc, org = resolved
                    created = await create_appointment(
                        s,
                        org=org,
                        official=ofc,
                        visitor_phone=phone,
                        topic_summary=topic,
                        source="kiosk",
                        voice_session_id=session_pk,
                    )
                    # Per CLAUDE.md: writes must call audit.record. The kiosk
                    # WS path was skipping this for appointments created via
                    # the AI tool flow. Phone goes in masked.
                    await audit.record(
                        s,
                        actor_user_id=None,
                        actor_org_id=org_id,
                        action="appointment.create",
                        entity_type="appointment",
                        entity_id=created.appointment.id,
                        after={
                            "official_id": str(ofc.id),
                            "official_name": ofc.name,
                            "queue_number": created.appointment.queue_number,
                            "scheduled_date": created.appointment.scheduled_date.isoformat(),
                            "phone_masked": mask_phone(phone),
                            "topic": topic,
                            "source": "kiosk_voice",
                            "session_id": str(session_pk),
                        },
                    )
        except Exception:
            logger.exception("submit_appointment_failed")
            await gemini.send_tool_response(
                ev.call_id, ev.name,
                {"status": "error", "code": "E_DB_001"},
            )
            with contextlib_suppress():
                await ws.send_json(
                    {"type": "error", "code": "E_DB_001", "message": "save_failed"}
                )
            return

        appt = created.appointment
        # PDF + QR are CPU-bound (~120 ms). Render OUTSIDE the DB transaction
        # we just exited so the row lock on (official_id, scheduled_date) is
        # released first. render_appointment_artifacts returns empty bytes on
        # internal failure — the kiosk's silent base64 catch (now logged in
        # SessionStore.cs) handles the missing-artifact case gracefully.
        # `locale` follows whatever language the kiosk last announced via
        # `ui_language`; falls back to org.locale.
        pdf_bytes, qr_bytes = render_appointment_artifacts(
            appt, created.official, created.org, created.verify_url,
            locale=ui_language,
        )
        with contextlib_suppress():
            await ws.send_json(
                {
                    "type": "appointment_submitted",
                    "appointment_id": str(appt.id),
                    "queue_number": appt.queue_number,
                    "scheduled_date": appt.scheduled_date.isoformat(),
                    "scheduled_date_human": format_date_kk(appt.scheduled_date),
                    "reception_time": created.official.reception_time,
                    "official_name": created.official.name,
                    "official_position": created.official.position,
                    "official_role": created.official.role or "",
                    "phone_masked": mask_phone(appt.visitor_phone),
                    "topic": appt.topic_summary,
                    "verification_url": created.verify_url,
                    "qr_png_base64": base64.b64encode(qr_bytes).decode("ascii"),
                    "receipt_pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                    # Localized org name so the kiosk talon header
                    # ("HOKIMIYAT") swaps language without a round-trip.
                    "org_name_translations": name_translations_for_response(
                        created.org
                    ),
                }
            )
        # Fan out to the operator's Telegram qabul channel — uses the
        # backend-rendered Karakalpak Cyrillic date string so the post
        # matches what's printed on the talon. Fire-and-forget; tracks
        # any failure in the structured log.
        telegram.post_qabul_async(
            appt, created.official, created.org,
            format_date_kk(appt.scheduled_date),
        )
        # Successful submission completes the qabul flow — reset
        # appt_state so the same session can start a fresh booking
        # without leaking previous values into the next flow's state echo.
        appt_state["topic"] = None
        appt_state["official_id"] = None
        appt_state["official_name"] = None
        appt_state["phone"] = None
        await gemini.send_tool_response(
            ev.call_id, ev.name,
            {
                "status": "ok",
                "submitted": True,
                "queue_number": appt.queue_number,
                "scheduled_date_human": format_date_kk(appt.scheduled_date),
                "next_step": (
                    "qabul booked. read the queue number to the visitor "
                    "and say a brief farewell"
                ),
            },
        )

    async def _consume_events() -> None:
        # CRITICAL: a single handler exception MUST NOT kill this task —
        # otherwise the kiosk silently stops receiving audio chunks for the
        # rest of the session. Catch + log per-event so a tool-dispatch bug,
        # a transient send-failure, or a misshaped Gemini event becomes a
        # warning instead of a session-killer.
        async for ev in gemini.events():
            try:
                await _handle_event(ev)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "kiosk_ws_event_handler_failed",
                    event_type=type(ev).__name__,
                )

    consumer_task = asyncio.create_task(_consume_events())

    async def _periodic_revoke_recheck() -> None:
        """Defensive: re-validate the device every 60 s in case the registry
        miss happened (e.g. backend restart between revoke and this WS reconnect).
        On any auth error → close the socket; the registry will unregister it
        in the finally block."""
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
                            logger.info("ws_recheck_failed_closing", device_id=str(device_id))
                            await ws.close(code=1008, reason="device_inactive")
                            return
            except Exception:
                logger.exception("ws_recheck_error")
                # Soft-fail: don't tear down the connection on transient DB hiccups.

    recheck_task = asyncio.create_task(_periodic_revoke_recheck())

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data: bytes | None = msg.get("bytes")
            text: str | None = msg.get("text")
            if data is not None:
                # Run the full inbound pipeline (DC-offset → TTS gating → squelch).
                # Result is always the same length; non-speech regions become zeros.
                processed = process_inbound(audio_state, data)
                await gemini.send_audio(processed, sample_rate=16000)
            elif text:
                # JSON envelope from the kiosk. Supported types:
                #   - `ui_language`: visitor's current UI locale (kk|uz|ru).
                #     Used at receipt-render time for label + date strings.
                #   - `user_text`: free-form text the kiosk wants forwarded
                #     to Gemini as a user turn (e.g. when the visitor taps
                #     "Tasdiqlayman" on the voice-preview card, the kiosk
                #     sends the affirmative phrase here so the agent then
                #     fires submit_appointment naturally).
                # Anything else is ignored — server VAD (gemini_live setup)
                # owns turn detection for audio; old turn_start/turn_end
                # paths are dead.
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                msg_type = str(payload.get("type", ""))
                if msg_type == "ui_language":
                    lang = str(payload.get("language", "")).strip().lower()
                    if lang in ("kk", "uz", "ru"):
                        ui_language = lang
                elif msg_type == "user_text":
                    user_text = str(payload.get("text", "")).strip()
                    if user_text:
                        await gemini.send_text(user_text)
    except WebSocketDisconnect:
        logger.info("kiosk_ws_disconnected")
    except Exception:
        logger.exception("kiosk_ws_error")
        error_code = "E_INT_999"
    finally:
        await registry.unregister(device_id, ws)
        await gemini.close()
        for task in (inbound_task, consumer_task, recheck_task):
            task.cancel()
            with contextlib_suppress():
                await task
        await _finalize_session(session_pk, started_at, transcript_lines, error_code)


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
