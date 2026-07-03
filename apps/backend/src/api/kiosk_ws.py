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

from ..ai.appointments import mask_phone
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
from ..ai.prompt_builder import load_agent_config
from ..core.config import get_settings
from ..core.connection_registry import registry
from ..core.db import AsyncSessionLocal
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import AppError, ProviderError
from ..domain.device import Device
from ..domain.organization import Organization, name_translations_for_response
from ..domain.session import VoiceSession

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["kiosk"])

# Personal fields that ride along with a NEW / «men emas» citizen's appeal
# (confirmed=false). For a confirmed existing citizen only phone + text are sent.
_MURAJAT_PERSONAL = (
    "first_name", "last_name", "birth_date", "gender",
    "district_id", "quarter_id", "address",
)


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

    settings = get_settings()
    _use_kaa = settings.voice_backend == "kaa" and bool(settings.kaa_ws_url)

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
    # Last previewed murajat field set (phone/text/confirmed + personal fields).
    # Echoed/fallen-back-to on submit so a value the agent omits between preview
    # and submit doesn't blank the forwarded appeal. The state-echo / fallback
    # pattern specifically prevents the "agent forgets the phone was already
    # given, re-asks or invents one" failure mode after long sessions.
    last_preview: dict[str, Any] = {}
    # Cross-flow "what the visitor actually gave". The agent does NOT reliably
    # re-pass an already-collected value into a later preview/submit call — it
    # gave the phone two turns ago and omits it now. `_phone` remembers the last
    # non-empty phone and falls back to it so the preview + the forwarded appeal
    # always carry what the visitor said.
    coll: dict[str, str] = {"phone": ""}

    def _phone(arg: object) -> str:
        p = str(arg or "").strip()
        if p:
            coll["phone"] = p
        return coll["phone"]

    def _murajat_fields(
        args: dict[str, Any], fallback: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Assemble the upstream appeal field set from a preview/submit call,
        falling back to the last preview for anything the agent omitted. Personal
        fields ride along only for a new / «men emas» citizen (confirmed=false)."""
        fb = fallback or {}

        def pick(k: str) -> Any:
            v = args.get(k)
            if v is None or (isinstance(v, str) and not v.strip()):
                return fb.get(k)
            return v

        confirmed = args.get("confirmed")
        if confirmed is None:
            confirmed = fb.get("confirmed")
        out: dict[str, Any] = {
            "phone": _phone(args.get("phone")) or str(fb.get("phone", "")),
            "text": str(pick("text") or "").strip(),
            "confirmed": bool(confirmed),
        }
        if not out["confirmed"]:
            for k in _MURAJAT_PERSONAL:
                val = pick(k)
                if val is not None and val != "":
                    out[k] = val
        return out

    audio_state = AudioPipelineState()

    # Load the org row once at WS open — used for the org name on the murajat
    # success talon. Re-fetched on each reconnect so live admin edits propagate.
    async with AsyncSessionLocal() as _ses:
        _org_row = (
            await _ses.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one_or_none()

    gemini = (
        KaaVoiceSession(config=agent_config, ws_url=settings.kaa_ws_url)
        if _use_kaa
        else GeminiLiveSession(config=agent_config)
    )
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
    _VALID_SCREENS = {"home", "submit", "contacts", "ai"}

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
        elif ev.name == "lookup_citizen":
            phone = _phone(ev.args.get("phone"))
            resp: dict[str, Any] = {"status": "ok", "exists": False, "full_name": ""}
            try:
                from ..core import murajat
                data = await murajat.lookup_personal(phone)
                personal = data.get("personal") or {}
                resp = {
                    "status": "ok",
                    "exists": bool(data.get("exists")),
                    "full_name": str(personal.get("full_name") or "").strip(),
                }
            except Exception:
                # Upstream down → let the agent proceed as a new citizen.
                logger.warning("lookup_citizen_failed", phone_len=len(phone))
            await gemini.send_tool_response(ev.call_id, ev.name, resp)
        elif ev.name == "get_quarters":
            try:
                from ..core import murajat
                did = int(ev.args.get("district_id"))
                quarters = await murajat.quarters_for_district(did)
                resp = {"status": "ok", "district_id": did, "quarters": quarters}
            except Exception:
                logger.warning("get_quarters_failed")
                resp = {"status": "error", "code": "E_UP_001", "quarters": []}
            await gemini.send_tool_response(ev.call_id, ev.name, resp)
        elif ev.name == "preview_murajat":
            fields = _murajat_fields(ev.args)
            last_preview.clear()
            last_preview.update(fields)
            logger.info(
                "preview_murajat",
                phone_len=len(str(fields.get("phone", ""))),
                confirmed=fields.get("confirmed"),
                text_len=len(str(fields.get("text", ""))),
            )
            with contextlib_suppress():
                await ws.send_json(
                    {
                        "type": "murajat_preview",
                        "text": str(fields.get("text", "")),
                        "phone": str(fields.get("phone", "")),
                        "confirmed": bool(fields.get("confirmed")),
                        "first_name": str(fields.get("first_name", "")),
                        "last_name": str(fields.get("last_name", "")),
                    }
                )
            await gemini.send_tool_response(
                ev.call_id, ev.name,
                {
                    "status": "ok",
                    "shown": True,
                    "next_step": (
                        "card is now on screen — ask «Дурыс па?» and on visitor "
                        "affirmation call submit_murajat with the SAME values"
                    ),
                },
            )
        elif ev.name == "submit_murajat":
            fields = _murajat_fields(ev.args, fallback=last_preview)
            if not fields.get("phone") or not fields.get("text"):
                await gemini.send_tool_response(
                    ev.call_id, ev.name,
                    {"status": "error", "code": "missing_fields"},
                )
                return
            try:
                from ..core import murajat
                data = await murajat.submit_appeal(fields)
                appeal = data.get("appeal") or {}
                appeal_no = str(appeal.get("appeal_number") or "")
                with contextlib_suppress():
                    await ws.send_json(
                        {
                            "type": "murajat_submitted",
                            "appeal_number": appeal_no,
                            "phone_masked": mask_phone(str(fields.get("phone", ""))),
                            "org_name_translations": (
                                name_translations_for_response(_org_row)
                                if _org_row else {}
                            ),
                        }
                    )
                last_preview.clear()
                coll["phone"] = ""
                await gemini.send_tool_response(
                    ev.call_id, ev.name,
                    {
                        "status": "ok",
                        "submitted": True,
                        "appeal_number": appeal_no,
                        "next_step": (
                            f"appeal filed (number {appeal_no}). tell the visitor "
                            "their appeal number and that the Council will contact "
                            "them, then end the turn"
                        ),
                    },
                )
            except Exception:
                logger.exception("submit_murajat_failed")
                await gemini.send_tool_response(
                    ev.call_id, ev.name, {"status": "error", "code": "E_UP_001"}
                )
                with contextlib_suppress():
                    await ws.send_json(
                        {"type": "error", "code": "E_UP_001", "message": "submit_failed"}
                    )
        else:
            logger.warning("unknown_tool_call", name=ev.name)
            await gemini.send_tool_response(
                ev.call_id, ev.name, {"status": "error", "code": "unknown_tool"}
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
                # JSON envelope from the kiosk. Supported type:
                #   - `user_text`: free-form text the kiosk wants forwarded to
                #     the agent as a user turn (e.g. when the visitor taps
                #     "Tasdiqlayman" on the voice-preview card, the kiosk sends
                #     the affirmative phrase here so the agent then fires
                #     submit_murajat naturally).
                # Anything else is ignored — server VAD owns turn detection.
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                msg_type = str(payload.get("type", ""))
                if msg_type == "user_text":
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
