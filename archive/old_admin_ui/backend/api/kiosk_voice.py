"""
Kiosk Voice WebSocket endpoint.

Ports AVA's engine.py audio pipeline to a WebSocket transport for Flutter kiosks.
Flutter sends 16kHz PCM16 audio, receives 24kHz PCM16 audio back.

Pipeline (ported from AVA engine.py _audiosocket_handle_audio):
    inbound → DC offset removal → TTS gating (silence bytes, not drop)
            → energy-based barge-in detection
            → upstream squelch (EMA noise floor + hysteresis)
            → provider.send_audio()

    provider AgentAudio event → output suppression check (post-barge-in)
                              → WebSocket binary frame to Flutter
"""

import json
import os
import sys
import time
import audioop
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# Add project root to path so we can import src/
# Container: /app/project (from PROJECT_ROOT env)
# Local: parent.parent.parent.parent (admin_ui/backend/api/ → project root)
_project_root = os.getenv("PROJECT_ROOT") or str(
    Path(__file__).resolve().parent.parent.parent.parent
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.providers.google_live import GoogleLiveProvider
from src.config import GoogleProviderConfig
from src.config.loaders import load_yaml_with_local_override, resolve_config_path

# Session persistence
from kiosk_session_store import get_store as get_session_store

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── AVA-matched constants (engine.py:5555-5618, ai-agent.yaml) ────────────

# Upstream squelch (energy-based VAD)
SQUELCH_BASE_RMS = 200
SQUELCH_NOISE_FACTOR = 2.5
SQUELCH_ALPHA = 0.06
SQUELCH_MIN_SPEECH_FRAMES = 2
SQUELCH_END_SILENCE_FRAMES = 15

# Barge-in (config/ai-agent.yaml barge_in section)
BARGE_IN_ENERGY_THRESHOLD = 1800
BARGE_IN_INITIAL_PROTECTION_MS = 200
BARGE_IN_COOLDOWN_MS = 500

# Output suppression window after barge-in (prevents echo tail)
OUTPUT_SUPPRESS_MS = 600


@dataclass
class KioskSession:
    """Per-WebSocket session state — ported from CallSession audio-relevant fields."""
    call_id: str
    provider: Optional[GoogleLiveProvider] = None
    # TTS gating
    audio_capture_enabled: bool = True
    tts_playing: bool = False
    tts_started_ts: float = 0.0
    last_barge_in_ts: float = 0.0
    # VAD state (upstream_squelch, output_suppression)
    vad_state: Dict[str, Any] = field(default_factory=dict)
    provider_session_active: bool = False


# ─── Config loader ──────────────────────────────────────────────────────────


def _load_provider_config() -> GoogleProviderConfig:
    """Load google_live provider config from ai-agent.yaml + .env.

    Kiosk overrides only audio format (WebSocket vs AudioSocket), nothing else.
    VAD sensitivity, model, temperature, voice — all from AVA-matched yaml.
    """
    config_path = resolve_config_path("config/ai-agent.yaml")
    raw = load_yaml_with_local_override(config_path)

    provider_raw = (raw.get("providers") or {}).get("google_live") or {}
    context_raw = (raw.get("contexts") or {}).get("default") or {}

    # Context prompt/greeting override (same as Asterisk engine)
    if context_raw.get("greeting"):
        provider_raw["greeting"] = context_raw["greeting"]
    if context_raw.get("prompt"):
        provider_raw["instructions"] = context_raw["prompt"]

    # Kiosk transport format: 16kHz PCM16 in, 24kHz PCM16 out (no resample/encode)
    provider_raw["target_sample_rate_hz"] = 24000
    provider_raw["target_encoding"] = "pcm16"
    provider_raw["input_encoding"] = "pcm16"
    provider_raw["input_sample_rate_hz"] = 16000

    return GoogleProviderConfig(**provider_raw)


# ─── Audio pipeline ─────────────────────────────────────────────────────────


def _remove_dc_offset(pcm_bytes: bytes) -> bytes:
    """Remove DC offset — AVA engine.py:5333."""
    try:
        mean = int(audioop.avg(pcm_bytes, 2))
        if mean:
            return audioop.bias(pcm_bytes, 2, -mean)
    except Exception:
        pass
    return pcm_bytes


def _check_barge_in(session: KioskSession, pcm_bytes: bytes) -> bool:
    """Energy-based barge-in detection — AVA engine.py:5354-5393.

    Returns True if user speech energy exceeds threshold after initial protection window.
    """
    if session.tts_started_ts <= 0:
        return False
    elapsed_ms = int((time.time() - session.tts_started_ts) * 1000)
    if elapsed_ms < BARGE_IN_INITIAL_PROTECTION_MS:
        return False
    # Cooldown from last barge-in
    cooldown_elapsed = int((time.time() - session.last_barge_in_ts) * 1000)
    if cooldown_elapsed < BARGE_IN_COOLDOWN_MS:
        return False
    try:
        energy = audioop.rms(pcm_bytes, 2)
    except Exception:
        return False
    return energy > BARGE_IN_ENERGY_THRESHOLD


def _apply_upstream_squelch(session: KioskSession, pcm_bytes: bytes) -> bytes:
    """Upstream squelch — replaces non-speech frames with silence.

    Ported verbatim from AVA engine.py:5555-5618.
    Uses EMA-based noise floor + hysteresis to classify speech vs silence,
    then zero-fills non-speech frames (keeps stream continuous for Gemini VAD).
    """
    state = session.vad_state.setdefault("upstream_squelch", {})

    try:
        energy = int(audioop.rms(pcm_bytes, 2)) if pcm_bytes else 0
    except Exception:
        energy = 0

    speaking = bool(state.get("speaking", False))
    speech_frames = int(state.get("speech_frames", 0) or 0)
    silence_frames = int(state.get("silence_frames", 0) or 0)
    noise_ema = float(state.get("noise_ema", 0.0) or 0.0)

    # Update noise floor (only when not speaking)
    if not speaking:
        if noise_ema <= 0.0:
            noise_ema = float(energy)
        else:
            noise_ema = (1.0 - SQUELCH_ALPHA) * noise_ema + SQUELCH_ALPHA * float(energy)

    threshold = max(float(SQUELCH_BASE_RMS), noise_ema * SQUELCH_NOISE_FACTOR)
    raw_speech = energy > threshold

    if raw_speech:
        speech_frames += 1
        silence_frames = 0
        if not speaking and speech_frames >= SQUELCH_MIN_SPEECH_FRAMES:
            speaking = True
    else:
        silence_frames += 1
        speech_frames = 0
        if speaking and silence_frames >= SQUELCH_END_SILENCE_FRAMES:
            speaking = False

    state.update({
        "speaking": speaking,
        "speech_frames": speech_frames,
        "silence_frames": silence_frames,
        "noise_ema": noise_ema,
        "last_energy": energy,
        "last_threshold": int(threshold),
    })

    if not speaking:
        return b"\x00" * len(pcm_bytes)
    return pcm_bytes


async def _apply_barge_in(session: KioskSession, websocket: WebSocket) -> None:
    """Interrupt TTS and open output suppression window."""
    session.audio_capture_enabled = True
    session.last_barge_in_ts = time.time()
    session.tts_playing = False
    session.vad_state["output_suppression"] = {
        "until_ts": time.time() + (OUTPUT_SUPPRESS_MS / 1000.0),
    }
    try:
        await websocket.send_json({"type": "barge_in"})
    except Exception:
        pass
    logger.info("Barge-in applied: %s", session.call_id)


async def _on_inbound_audio(
    session: KioskSession, websocket: WebSocket, audio_bytes: bytes
) -> None:
    """Process inbound Flutter audio frame.

    AVA engine.py:5161 _audiosocket_handle_audio ported to WebSocket transport.
    Audio is already 16kHz PCM16 — no wire-format decode needed.
    """
    if not audio_bytes:
        return

    # STAGE 1: DC offset removal
    pcm_bytes = _remove_dc_offset(audio_bytes)

    # STAGE 2: TTS gating
    # Barge-in disabled — during TTS, send silence bytes (keeps stream continuous
    # for Gemini VAD but prevents echo/false-interrupt from room noise).
    if not session.audio_capture_enabled:
        pcm_bytes = b"\x00" * len(pcm_bytes)

    # STAGE 3: Upstream squelch (noise filter; replaces silence/noise with zeros)
    pcm_bytes = _apply_upstream_squelch(session, pcm_bytes)

    # STAGE 4: Forward to provider (no resample — already 16kHz PCM16)
    if session.provider and session.provider_session_active:
        try:
            await session.provider.send_audio(
                pcm_bytes, sample_rate=16000, encoding="pcm16"
            )
        except Exception as e:
            logger.debug("send_audio failed: %s", e)


async def _handle_provider_event(
    session: KioskSession, websocket: WebSocket, event: dict
) -> None:
    """Handle events from GoogleLiveProvider — port of engine.py on_provider_event."""
    etype = event.get("type")

    try:
        if etype == "AgentAudio":
            # Output suppression check (post-barge-in echo tail)
            sup = session.vad_state.get("output_suppression", {})
            if sup.get("until_ts", 0) > time.time():
                return  # Drop — still in suppression window

            # Mark TTS active — gate inbound audio from being forwarded
            if not session.tts_playing:
                session.tts_playing = True
                session.tts_started_ts = time.time()
            session.audio_capture_enabled = False

            await websocket.send_bytes(event["data"])

        elif etype == "AgentAudioDone":
            session.tts_playing = False
            session.audio_capture_enabled = True
            session.tts_started_ts = 0.0
            session.vad_state.pop("output_suppression", None)
            await websocket.send_json({"type": "audio_done"})

        elif etype == "Transcript":
            await websocket.send_json({
                "type": "transcript",
                "text": event.get("text", ""),
                "final": event.get("final", False),
                "speaker": event.get("speaker", "assistant"),
            })

        elif etype == "ProviderBargeIn":
            # Barge-in disabled for kiosk — ignore
            pass

        elif etype == "ProviderDisconnected":
            await websocket.send_json({
                "type": "disconnected",
                "reason": event.get("reason", ""),
            })
    except Exception as e:
        logger.debug("Event handler error (%s): %s", etype, e)


# ─── WebSocket endpoint ────────────────────────────────────────────────────


@router.websocket("/ws/kiosk/voice")
async def kiosk_voice(websocket: WebSocket):
    await websocket.accept()

    config = _load_provider_config()
    session = KioskSession(call_id=f"kiosk-{id(websocket)}")
    store = get_session_store()
    store.create_session(
        session_id=session.call_id,
        provider="google_live",
        model=config.llm_model,
    )

    async def on_event(event: dict):
        # Persist transcripts
        etype = event.get("type")
        if etype == "Transcript":
            text = (event.get("text") or "").strip()
            if text and event.get("final", False):
                # Attribute user vs assistant
                speaker = event.get("speaker") or ("assistant" if event.get("assistant") else "user")
                try:
                    store.append_transcript(session.call_id, text, speaker=speaker)
                except Exception:
                    pass
        # Forward kiosk navigation tool calls to the UI
        if etype == "KioskNavigate":
            try:
                await websocket.send_json({
                    "type": "navigate",
                    "screen": event.get("screen", "home"),
                })
            except Exception:
                logger.debug("Failed to forward KioskNavigate to UI", exc_info=True)
            return
        await _handle_provider_event(session, websocket, event)

    provider = GoogleLiveProvider(config=config, on_event=on_event)
    # Prevent AttributeError in google_live.py:1850 (engine usually injects this)
    provider._session_store = None
    provider._ari_client = None
    session.provider = provider

    try:
        logger.info("Kiosk voice session starting: %s", session.call_id)

        context: Dict[str, Any] = {}
        if config.instructions:
            context["system_instruction"] = config.instructions

        # Register the kiosk navigation tool directly (bypasses engine ToolAdapter).
        context["raw_tools"] = [
            {
                "name": "navigate_to_screen",
                "description": (
                    "Open a specific screen of the kiosk UI. Call this whenever "
                    "the visitor asks to see, open, or show a section of the "
                    "kiosk (reception schedule, submit application, contacts), "
                    "or when it naturally fits your response to guide them. "
                    "Always call this BEFORE speaking the intro line for that "
                    "section so the UI is ready when you start talking."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "screen": {
                            "type": "string",
                            "enum": ["home", "reception", "submit", "contacts"],
                            "description": (
                                "home = main menu; "
                                "reception = hokim/orinbasar qabul kunleri; "
                                "submit = murajaat jollaw dialogi; "
                                "contacts = baylanis telefonlari."
                            ),
                        }
                    },
                    "required": ["screen"],
                },
            }
        ]

        await provider.start_session(call_id=session.call_id, context=context)
        session.provider_session_active = True
        logger.info("Kiosk voice session active: %s", session.call_id)

        while True:
            data = await websocket.receive()
            msg_type = data.get("type")
            if msg_type == "websocket.disconnect":
                break
            if data.get("bytes"):
                await _on_inbound_audio(session, websocket, data["bytes"])
            elif data.get("text"):
                # Control messages from the kiosk UI (JSON text frames)
                try:
                    msg = json.loads(data["text"])
                except Exception:
                    continue
                mtype = msg.get("type")
                if mtype == "screen_context":
                    screen = str(msg.get("screen", "home"))
                    ctx_text = f"[CTX:{screen}]"
                    try:
                        await provider.send_text_turn(ctx_text)
                        logger.info(
                            "Kiosk screen context forwarded",
                            extra={"call_id": session.call_id, "screen": screen},
                        )
                    except Exception:
                        logger.debug(
                            "Kiosk screen context forward failed",
                            extra={"call_id": session.call_id},
                            exc_info=True,
                        )

    except WebSocketDisconnect:
        logger.info("Kiosk voice disconnected: %s", session.call_id)
    except Exception as e:
        logger.error("Kiosk voice error: %s", e, exc_info=True)
        try:
            store.close_session(session.call_id, error=str(e))
        except Exception:
            pass
    finally:
        session.provider_session_active = False
        if provider:
            try:
                await provider.stop_session()
            except Exception:
                pass
        # Always close session (if not already closed by error handler)
        try:
            store.close_session(session.call_id)
        except Exception:
            pass
        logger.info("Kiosk voice cleaned up: %s", session.call_id)
