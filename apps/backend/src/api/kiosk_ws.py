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

from ..ai.appointments import (
    create_appointment,
    mask_phone,
    reference_no,
    render_appointment_artifacts,
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
from ..ai.prompt_builder import load_agent_config
from ..core import audit, telegram
from ..core.connection_registry import registry
from ..core.db import AsyncSessionLocal
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import AppError, ProviderError
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
        "phone": None,
    }
    # Last previewed feedback (type/text/phone) — mirrors last_preview.
    last_feedback: dict[str, str] = {}
    # Cross-flow "what the visitor actually gave". Gemini does NOT reliably
    # re-pass an already-collected value into a later preview_*/submit_* tool
    # call — it gave the phone two turns ago and omits it now — which left the
    # on-screen preview card (and the saved row) with a blank phone. These
    # helpers remember the last non-empty value and fall back to it, so the
    # preview + the DB row always carry what the visitor said. `_topic_q` does
    # the same for the qabul reason via appt_state.
    coll: dict[str, str] = {"phone": ""}

    def _phone(arg: object) -> str:
        p = str(arg or "").strip()
        if p:
            coll["phone"] = p
        return coll["phone"]

    def _topic_q(arg: object) -> str:
        p = str(arg or "").strip()
        if p:
            appt_state["topic"] = p
        return str(appt_state.get("topic") or "")

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
    _VALID_SCREENS = {"home", "qabul", "submit", "feedback", "contacts", "ai"}

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
            topic = str(ev.args.get("topic", "")).strip() or last_preview.get("topic", "")
            body = str(ev.args.get("body", "")).strip() or last_preview.get("body", "")
            phone = _phone(ev.args.get("phone")) or last_preview.get("phone", "")
            last_preview.update({"topic": topic, "body": body, "phone": phone})
            logger.info("preview_application", phone_len=len(phone), topic_len=len(topic))
            with contextlib_suppress():
                await ws.send_json(
                    {
                        "type": "application_preview",
                        "topic": topic,
                        "body": body,
                        "phone": phone,
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
                        "submit_application with the SAME 3 values"
                    ),
                    "preview_args": {
                        "topic": topic,
                        "body_chars": len(body),
                        "phone": phone,
                    },
                },
            )
        elif ev.name == "submit_application":
            topic = str(ev.args.get("topic", "")).strip() or last_preview.get("topic", "")
            body = str(ev.args.get("body", "")).strip() or last_preview.get("body", "")
            phone = _phone(ev.args.get("phone")) or last_preview.get("phone", "")
            new_id: uuid.UUID | None = None
            try:
                async with AsyncSessionLocal() as s:
                    async with s.begin():
                        # Shared helper so voice + manual flows produce
                        # identical Application rows (kind=murajaat).
                        from ..ai.applications import create_application
                        app = await create_application(
                            s,
                            org_id=org_id,
                            topic=topic,
                            body=body,
                            phone=phone,
                            source="kiosk_voice",
                            voice_session_id=session_pk,
                        )
                        new_id = app.id
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
                                "kind": "murajaat",
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
                        }
                    )
                # Fan out to the Telegram murajaat channel (no-op if the bot
                # isn't configured). Fire-and-forget; `app` is detached after
                # commit but its loaded attrs are readable, and _org_row was
                # loaded at WS open.
                if _org_row is not None:
                    telegram.post_murajaat_async(app, _org_row)
                # Successful submission completes the murajat flow —
                # clear last_preview + the collected phone so a fresh request
                # in the same session starts from a clean slate.
                last_preview.clear()
                coll["phone"] = ""
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
            except Exception:
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
        elif ev.name == "preview_feedback":
            await _dispatch_preview_feedback(ev)
        elif ev.name == "submit_feedback":
            await _dispatch_submit_feedback(ev)
        else:
            logger.warning("unknown_tool_call", name=ev.name)
            await gemini.send_tool_response(
                ev.call_id, ev.name, {"status": "error", "code": "unknown_tool"}
            )

    def _appt_state_echo() -> dict[str, object]:
        """Snapshot of qabul flow collected state for the tool-response echo,
        so the agent never has to recall earlier-in-session values from audio
        context. Phone is the only required field; topic (reason) is
        optional."""
        next_required = "phone" if appt_state.get("phone") is None else None
        return {
            "collected_so_far": dict(appt_state),
            "next_required": next_required,
        }

    async def _dispatch_appointment_progress(ev: ToolCallEvent) -> None:
        """Stepper-only signal — emit a JSON envelope so the kiosk lights the
        next step. No DB write. Updates `appt_state` and echoes it back."""
        stage = str(ev.args.get("stage", "")).strip()
        if stage not in ("topic", "phone"):
            await gemini.send_tool_response(
                ev.call_id, ev.name,
                {"status": "error", "code": "bad_stage", **_appt_state_echo()},
            )
            return

        envelope: dict[str, object] = {"type": "appointment_progress", "stage": stage}
        if stage == "topic":
            envelope["topic"] = _topic_q(ev.args.get("topic"))
        elif stage == "phone":
            phone = _phone(ev.args.get("phone"))
            if phone:
                appt_state["phone"] = phone
            envelope["phone_masked"] = mask_phone(phone)

        with contextlib_suppress():
            await ws.send_json(envelope)
        await gemini.send_tool_response(
            ev.call_id, ev.name,
            {"status": "ok", **_appt_state_echo()},
        )

    async def _dispatch_preview_appointment(ev: ToolCallEvent) -> None:
        # Resolve from session state — Gemini often omits the phone/topic it
        # collected earlier, which left the preview card blank.
        topic = _topic_q(ev.args.get("topic"))
        phone = _phone(ev.args.get("phone"))
        if phone:
            appt_state["phone"] = phone
        logger.info("preview_appointment", phone_len=len(phone), topic_len=len(topic))
        with contextlib_suppress():
            await ws.send_json(
                {
                    "type": "appointment_preview",
                    "topic": topic,
                    "phone_masked": mask_phone(phone),
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
                "phone_masked": mask_phone(phone),
                **_appt_state_echo(),
            },
        )

    async def _dispatch_submit_appointment(ev: ToolCallEvent) -> None:
        topic = _topic_q(ev.args.get("topic"))
        phone = _phone(ev.args.get("phone"))
        if not phone:
            await gemini.send_tool_response(
                ev.call_id, ev.name,
                {"status": "error", "code": "missing_fields", **_appt_state_echo()},
            )
            return
        try:
            async with AsyncSessionLocal() as s:
                async with s.begin():
                    org = (
                        await s.execute(
                            select(Organization).where(Organization.id == org_id)
                        )
                    ).scalar_one()
                    created = await create_appointment(
                        s,
                        org=org,
                        visitor_phone=phone,
                        topic_summary=topic,
                        source="kiosk",
                        voice_session_id=session_pk,
                    )
                    await audit.record(
                        s,
                        actor_user_id=None,
                        actor_org_id=org_id,
                        action="appointment.create",
                        entity_type="appointment",
                        entity_id=created.appointment.id,
                        after={
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
        # PDF + QR are CPU-bound; render OUTSIDE the committed transaction.
        # render_appointment_artifacts returns empty bytes on failure — the
        # kiosk handles the missing-artifact case gracefully. `locale` follows
        # the kiosk's last `ui_language`; falls back to org.locale.
        pdf_bytes, qr_bytes = render_appointment_artifacts(
            appt, created.org, created.verify_url, locale=ui_language,
        )
        with contextlib_suppress():
            await ws.send_json(
                {
                    "type": "appointment_submitted",
                    "appointment_id": str(appt.id),
                    "reference_no": reference_no(appt),
                    "phone_masked": mask_phone(appt.visitor_phone),
                    "topic": appt.topic_summary,
                    "verification_url": created.verify_url,
                    "qr_png_base64": base64.b64encode(qr_bytes).decode("ascii"),
                    "receipt_pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                    "org_name_translations": name_translations_for_response(
                        created.org
                    ),
                }
            )
        # Fan out to the Telegram qabul channel (no-op if the bot isn't
        # configured). Uses reference_no — no official/date for the Council.
        telegram.post_qabul_async(appt, created.org)
        # Reset qabul state so the same session can start a fresh registration.
        appt_state["topic"] = None
        appt_state["phone"] = None
        coll["phone"] = ""
        await gemini.send_tool_response(
            ev.call_id, ev.name,
            {
                "status": "ok",
                "submitted": True,
                "reference_no": reference_no(appt),
                "next_step": (
                    "qabul registration saved. tell the visitor the Council "
                    "will call them back, then a brief farewell"
                ),
            },
        )

    async def _dispatch_preview_feedback(ev: ToolCallEvent) -> None:
        ftype = str(ev.args.get("feedback_type", "")).strip() or last_feedback.get("feedback_type", "")
        text = str(ev.args.get("text", "")).strip() or last_feedback.get("text", "")
        phone = _phone(ev.args.get("phone")) or last_feedback.get("phone", "")
        last_feedback.update({"feedback_type": ftype, "text": text, "phone": phone})
        logger.info("preview_feedback", phone_len=len(phone), text_len=len(text), ftype=ftype)
        with contextlib_suppress():
            await ws.send_json(
                {
                    "type": "feedback_preview",
                    "feedback_type": ftype,
                    "text": text,
                    "phone": phone,
                }
            )
        await gemini.send_tool_response(
            ev.call_id, ev.name,
            {
                "status": "ok",
                "shown": True,
                "next_step": (
                    "card on screen — ask «Дурыс па?» and on affirmation "
                    "call submit_feedback with the same values"
                ),
            },
        )

    async def _dispatch_submit_feedback(ev: ToolCallEvent) -> None:
        ftype = str(ev.args.get("feedback_type", "")).strip() or last_feedback.get("feedback_type", "")
        text = str(ev.args.get("text", "")).strip() or last_feedback.get("text", "")
        phone = _phone(ev.args.get("phone")) or last_feedback.get("phone", "")
        if ftype not in ("complaint", "suggestion", "gratitude") or not text:
            await gemini.send_tool_response(
                ev.call_id, ev.name, {"status": "error", "code": "missing_fields"}
            )
            return
        new_id: uuid.UUID | None = None
        try:
            async with AsyncSessionLocal() as s:
                async with s.begin():
                    from ..ai.applications import create_feedback
                    fb = await create_feedback(
                        s,
                        org_id=org_id,
                        feedback_type=ftype,
                        text=text,
                        phone=phone,
                        source="kiosk_voice",
                        voice_session_id=session_pk,
                    )
                    new_id = fb.id
                    await audit.record(
                        s,
                        actor_user_id=None,
                        actor_org_id=org_id,
                        action="feedback.create",
                        entity_type="application",
                        entity_id=new_id,
                        after={
                            "feedback_type": ftype,
                            "phone_masked": mask_phone(phone),
                            "kind": "feedback",
                            "source": "kiosk_voice",
                            "session_id": str(session_pk),
                        },
                    )
            with contextlib_suppress():
                await ws.send_json(
                    {
                        "type": "feedback_submitted",
                        "id": str(new_id),
                        "feedback_type": ftype,
                        "text": text,
                        "phone": phone,
                    }
                )
            # Fan out to the Telegram feedback channel (no-op if unconfigured).
            if _org_row is not None:
                telegram.post_feedback_async(fb, ftype, _org_row)
            last_feedback.clear()
            coll["phone"] = ""
            await gemini.send_tool_response(
                ev.call_id, ev.name,
                {
                    "status": "ok",
                    "submitted": True,
                    "id": str(new_id),
                    "next_step": "feedback saved. brief thanks, then end the turn",
                },
            )
        except Exception:
            logger.exception("submit_feedback_failed")
            await gemini.send_tool_response(
                ev.call_id, ev.name, {"status": "error", "code": "E_DB_001"}
            )
            with contextlib_suppress():
                await ws.send_json(
                    {"type": "error", "code": "E_DB_001", "message": "save_failed"}
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
