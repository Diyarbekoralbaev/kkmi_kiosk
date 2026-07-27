"""Raw-WebSocket Gemini Live wrapper.

Why raw WS instead of google-genai SDK: SDK 1.73.1 with Gemini 3.1 silently
breaks multi-turn — turn 1 works, turn 2+ Gemini receives audio but never
generates input_transcript or response. The proven AVA / old-kiosk_voice.py
implementation talks the bidiGenerateContent protocol directly and works.
This module ports that wire format 1:1.

External API kept identical to the old SDK version so kiosk_ws.py is
unchanged: GeminiLiveSession.start / run / events / send_audio / send_text /
send_tool_response / close. Same dataclass events.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

from ..core.config import get_settings
from ..core.errors import ProviderError
from .prompt_builder import AgentConfig
from .tools import declarations_for

logger = structlog.get_logger(__name__)

GEMINI_LIVE_ENDPOINT = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)

# Buffer raw mic frames into 20 ms chunks before forwarding to Gemini —
# the "Golden Baseline" used by the working old-kiosk_voice.py path.
_PROVIDER_INPUT_RATE = 16000
_FRAME_INTERVAL_SEC = 0.02
_FRAME_BYTES = int(_PROVIDER_INPUT_RATE * 2 * _FRAME_INTERVAL_SEC)  # 640


# ── Event types yielded to the WS handler ──


@dataclass
class AudioOut:
    pcm: bytes
    sample_rate: int = 24000


@dataclass
class Transcript:
    text: str
    final: bool
    speaker: str  # "user" | "assistant"


@dataclass
class ToolCallEvent:
    name: str
    args: dict[str, Any]
    call_id: str


@dataclass
class AudioDone:
    pass


@dataclass
class ProviderClosed:
    reason: str = ""


@dataclass
class ProviderErrorEvent:
    code: str
    message: str = ""


Event = AudioOut | Transcript | ToolCallEvent | AudioDone | ProviderClosed | ProviderErrorEvent


@dataclass
class GeminiLiveSession:
    config: AgentConfig
    on_event: Any = field(default=None)

    _events: asyncio.Queue[Event] = field(default_factory=asyncio.Queue)
    _ws: Any = field(default=None)
    _setup_complete: asyncio.Event = field(default_factory=asyncio.Event)
    _closed: bool = False
    _input_buffer: bytearray = field(default_factory=bytearray)
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _recv_task: asyncio.Task | None = None
    _audio_byte_total: int = 0
    _audio_log_due: float = 0.0

    # ── Lifecycle ──

    async def start(self) -> None:
        api_key = get_settings().google_api_key.get_secret_value()
        if not api_key:
            raise ProviderError("google_api_key_missing")

        # Preferred transport: a Cloudflare Worker relay (set via GEMINI_RELAY_URL +
        # GEMINI_RELAY_TOKEN). The Worker accepts plain wss:// from us and forwards
        # to Gemini's bidi endpoint at Cloudflare's edge. This sidesteps the
        # Moscow→Frankfurt HTTP CONNECT proxy chain entirely — that chain was
        # losing 40–60% of WS handshakes due to packet loss on the long path,
        # and Python websockets has trouble recovering from those mid-handshake
        # failures (it raises InvalidProxyMessage rather than retrying cleanly).
        #
        # Fallback path (legacy): GEMINI_PROXY → HTTP CONNECT proxy. Kept so an
        # env without the Worker still talks to Gemini, and so we can roll back
        # by simply unsetting GEMINI_RELAY_URL.
        relay_url = os.environ.get("GEMINI_RELAY_URL", "").rstrip("/")
        relay_token = os.environ.get("GEMINI_RELAY_TOKEN", "")
        extra_headers: dict[str, str] | None = None
        proxy: str | None = None
        if relay_url and relay_token:
            # Accept either https:// or wss:// in the env — normalize to wss://
            # since websockets.connect() rejects anything else.
            if relay_url.startswith("https://"):
                relay_url = "wss://" + relay_url[len("https://") :]
            elif relay_url.startswith("http://"):
                relay_url = "ws://" + relay_url[len("http://") :]
            url = (
                f"{relay_url}/ws/"
                "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
                f"?key={api_key}"
            )
            extra_headers = {"X-Kiosk-Auth": relay_token}
            logger.info("gemini_transport_relay", relay=relay_url)
        else:
            url = f"{GEMINI_LIVE_ENDPOINT}?key={api_key}"
            proxy = (
                os.environ.get("GEMINI_PROXY")
                or os.environ.get("HTTPS_PROXY")
                or None
            )
            logger.info("gemini_transport_proxy", proxy=proxy or "direct")
        # Retry the WS handshake. The Moscow ↔ Frankfurt ↔ Google path
        # through the upstream HTTP CONNECT proxy is intermittently lossy
        # (curl one-shot works ~100% but the larger TLS+WS handshake bursts
        # fail in ~40–60% of attempts — observed via 20× sequential probes).
        # A single attempt is not enough. With ~60% per-attempt success,
        # 5 retries put the cumulative success rate around 99%, at a worst
        # case of ~40 s before we raise — well below the WS request budget.
        attempts = 5
        attempt_timeout = 8.0
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._ws = await websockets.connect(
                    url,
                    subprotocols=["gemini-live"],
                    max_size=10 * 1024 * 1024,
                    # Heartbeat: WS-protocol pings every 20 s. Cloudflare's
                    # edge closes any WS with 100 s of total bidirectional
                    # silence (non-configurable on Free/Pro per
                    # websocket.org/guides/infrastructure/cloudflare). A real
                    # user who pauses mid-conversation can easily exceed that,
                    # so we keep traffic flowing via library-level pings —
                    # they're invisible to Gemini (handled by the WS layer at
                    # Cloudflare and Google), and 20 s well below the 100 s
                    # ceiling with margin for jitter.
                    ping_interval=20,
                    ping_timeout=20,
                    proxy=proxy,
                    additional_headers=extra_headers,
                    open_timeout=attempt_timeout,
                )
                if attempt > 1:
                    logger.info(
                        "gemini_connect_retry_succeeded",
                        attempt=attempt,
                        attempts=attempts,
                    )
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                logger.warning(
                    "gemini_connect_attempt_failed",
                    attempt=attempt,
                    attempts=attempts,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                if attempt < attempts:
                    await asyncio.sleep(0.5)
        if last_exc is not None:
            logger.error(
                "gemini_connect_failed",
                attempts=attempts,
                error=str(last_exc),
                proxy=proxy,
            )
            raise ProviderError(cause=last_exc) from last_exc

        # CRITICAL: start the receive loop BEFORE sending setup. The setupComplete
        # ack frame arrives almost immediately after our setup is sent — if no
        # one is reading, _setup_complete event never fires and start() deadlocks.
        self._recv_task = asyncio.create_task(self._recv_loop(), name="gemini-recv")

        await self._send_setup()

        try:
            await asyncio.wait_for(self._setup_complete.wait(), timeout=10.0)
        except TimeoutError as e:
            raise ProviderError("gemini_setup_timeout") from e

        logger.info("gemini_session_ready", model=self.config.model)

    async def _send_setup(self) -> None:
        """Build + send the setup message in the wire format Gemini accepts.

        Matches archive/old_src/providers/google_live.py exactly: model under
        "models/", camelCase generation_config, voice via prebuiltVoiceConfig,
        realtimeInputConfig with HIGH/HIGH/500 ms server VAD.
        """
        model = self.config.model
        if not model.startswith("models/"):
            model = f"models/{model}"

        is_31 = "3.1" in self.config.model and "live" in self.config.model

        if is_31:
            generation_config: dict[str, Any] = {
                "responseModalities": [self.config.response_modalities.upper()],
                "speechConfig": {
                    "voice_config": {
                        "prebuilt_voice_config": {"voice_name": self.config.voice}
                    }
                },
                "temperature": self.config.temperature,
                "topP": self.config.top_p,
                "topK": self.config.top_k,
            }
        else:
            generation_config = {
                "responseModalities": [self.config.response_modalities.upper()],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": self.config.voice}
                    }
                },
                "temperature": self.config.temperature,
                "maxOutputTokens": self.config.max_output_tokens,
                "topP": self.config.top_p,
                "topK": self.config.top_k,
            }

        system_instruction: dict[str, Any] = {
            "parts": [{"text": self.config.system_prompt}]
        }
        if is_31:
            system_instruction["role"] = "user"

        setup: dict[str, Any] = {
            "model": model,
            "generationConfig": generation_config,
            "systemInstruction": system_instruction,
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
            # VAD tuned per the kiosk research round (see [[gemini-cf-worker-relay]]
            # memory + audio_pipeline.py comments). Trade-offs:
            #  - silenceDurationMs 300: at the edge of the "natural pause"
            #    band (Stivers 2009, mode 0 ms, ceiling ~300 ms). Saves
            #    ~200 ms voice-to-voice vs the old 500 ms.
            #  - endOfSpeechSensitivity LOW: complements the shorter window.
            #    HIGH + 300 ms is double-strict and clips elderly thinking
            #    pauses; LOW gives the VAD a bit more tolerance, the 300 ms
            #    floor still keeps total gap snappy.
            #  - startOfSpeechSensitivity HIGH: onset detection is cheap to
            #    keep aggressive — false-positive onset just makes the agent
            #    listen a frame too early, which is fine.
            #  - activityHandling START_OF_ACTIVITY_INTERRUPTS: enables soft
            #    barge-in so a visitor can correct the agent mid-readback
            #    ("Yo'q, ismim X" while agent is reading a name back).
            #    Paired with the 150 ms post-TTS suppression and PipeWire AEC
            #    so speaker bleed can't self-interrupt.
            "realtimeInputConfig": {
                "automaticActivityDetection": {
                    "disabled": False,
                    "startOfSpeechSensitivity": "START_SENSITIVITY_HIGH",
                    "endOfSpeechSensitivity": "END_SENSITIVITY_LOW",
                    "prefixPaddingMs": 20,
                    "silenceDurationMs": 300,
                },
                "activityHandling": "START_OF_ACTIVITY_INTERRUPTS",
            },
        }

        if self.config.enabled_tools:
            decls = declarations_for(self.config.enabled_tools)
            setup["tools"] = [{"functionDeclarations": decls}]

        await self._send_raw({"setup": setup})

    # ── Outbound ──

    async def _send_raw(self, message: dict[str, Any]) -> None:
        if self._ws is None or self._closed:
            return
        try:
            async with self._send_lock:
                await self._ws.send(json.dumps(message))
        except Exception as e:
            logger.warning("gemini_send_failed", error=str(e))

    async def send_audio(self, pcm: bytes, sample_rate: int = 16000) -> None:
        """Buffer + forward 16 kHz PCM to Gemini in 20 ms chunks (640 bytes)."""
        if self._ws is None or self._closed or not self._setup_complete.is_set():
            return
        if sample_rate != _PROVIDER_INPUT_RATE:
            # The kiosk only ever sends 16k mono Int16; bail loudly if not.
            logger.warning("gemini_unexpected_rate", rate=sample_rate)
            return

        self._input_buffer.extend(pcm)

        is_31 = "3.1" in self.config.model and "live" in self.config.model
        rt_key = "realtime_input" if is_31 else "realtimeInput"
        # Only the envelope key went snake_case in 3.1 — the inner blob field
        # stayed camelCase on both API versions. (This was previously written
        # as a ternary with two identical branches, which read as if the two
        # versions differed. They don't.)
        mime_key = "mimeType"

        while len(self._input_buffer) >= _FRAME_BYTES:
            chunk = bytes(self._input_buffer[:_FRAME_BYTES])
            del self._input_buffer[:_FRAME_BYTES]
            audio_b64 = base64.b64encode(chunk).decode("ascii")
            message = {
                rt_key: {
                    "audio": {
                        mime_key: f"audio/pcm;rate={_PROVIDER_INPUT_RATE}",
                        "data": audio_b64,
                    }
                }
            }
            await self._send_raw(message)

            self._audio_byte_total += len(chunk)
            now = time.monotonic()
            if now >= self._audio_log_due:
                logger.info("gemini_audio_sent", bytes_since_last=self._audio_byte_total)
                self._audio_byte_total = 0
                self._audio_log_due = now + 1.0

    async def send_text(self, text: str) -> None:
        """Inject a side-channel text turn (e.g. the [START] signal at WS open
        or a user_text relay from the kiosk's voice-preview buttons).

        CRITICAL: must mark the synthetic user turn as complete. Otherwise
        Gemini 3.1 Live treats `realtime_input.text` as a partial input and
        waits for VAD-detected speech-end before producing any response —
        i.e. the agent stays silent until the visitor speaks first. The
        legacy `clientContent` path already sets `turnComplete=True`; the
        3.1 path was missing the equivalent flag.
        """
        if self._ws is None or self._closed or not self._setup_complete.is_set():
            return
        is_31 = "3.1" in self.config.model and "live" in self.config.model
        if is_31:
            # Gemini 3.1 Live realtime_input.text does NOT accept turn_complete
            # — adding it returns 1007 "Unknown name turn_complete at
            # 'realtime_input': Cannot find field." We send the text without
            # an explicit turn-end marker; server VAD owns turn boundaries.
            msg = {"realtime_input": {"text": text}}
        else:
            msg = {
                "clientContent": {
                    "turns": [{"role": "user", "parts": [{"text": text}]}],
                    "turnComplete": True,
                }
            }
        await self._send_raw(msg)

    async def send_tool_response(
        self, call_id: str, name: str, payload: dict[str, Any]
    ) -> None:
        if self._ws is None or self._closed:
            return
        msg = {
            "toolResponse": {
                "functionResponses": [
                    {"id": call_id, "name": name, "response": payload}
                ]
            }
        }
        await self._send_raw(msg)

    # ── Inbound ──

    async def run(self) -> None:
        """Wait for the receive loop (started in start()) to finish."""
        if self._recv_task is None:
            return
        try:
            await self._recv_task
        except asyncio.CancelledError:
            raise

    async def _recv_loop(self) -> None:
        """The actual WS receive pump. Started by start() before setup is sent."""
        if self._ws is None:
            return
        try:
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                except Exception:
                    logger.warning("gemini_bad_json", preview=str(raw[:80]))
                    continue
                await self._handle_server_message(data)
        except ConnectionClosed as e:
            logger.info("gemini_ws_closed", code=e.code, reason=str(e.reason)[:200])
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("gemini_recv_error", error=str(e))
            await self._emit(ProviderErrorEvent(code="E_PRV_001", message="recv_error"))
        finally:
            await self._emit(ProviderClosed())

    async def _handle_server_message(self, data: dict[str, Any]) -> None:
        if "setupComplete" in data:
            self._setup_complete.set()
            logger.info("gemini_setup_complete")
            return
        if "serverContent" in data:
            await self._handle_server_content(data["serverContent"])
            return
        if "toolCall" in data:
            await self._handle_tool_call(data["toolCall"])
            return
        if "goAway" in data:
            logger.warning("gemini_go_away", reason=str(data.get("goAway"))[:200])
            return

    async def _handle_server_content(self, sc: dict[str, Any]) -> None:
        # Audio chunks are nested under modelTurn.parts[].inlineData.data (base64).
        model_turn = sc.get("modelTurn") or {}
        for part in model_turn.get("parts", []) or []:
            inline = part.get("inlineData") or {}
            data = inline.get("data")
            if not data:
                continue
            try:
                pcm = base64.b64decode(data)
            except Exception:
                continue
            logger.info("gemini_audio_chunk", bytes=len(pcm))
            await self._emit(AudioOut(pcm=pcm))

        it = sc.get("inputTranscription") or {}
        if it.get("text"):
            logger.info(
                "gemini_input_transcript",
                text=it.get("text", ""),
                final=bool(it.get("finished") or it.get("isFinal")),
            )
            await self._emit(
                Transcript(
                    text=it.get("text") or "",
                    final=bool(it.get("finished") or it.get("isFinal")),
                    speaker="user",
                )
            )

        ot = sc.get("outputTranscription") or {}
        if ot.get("text"):
            logger.info(
                "gemini_output_transcript",
                text=ot.get("text", ""),
                final=bool(ot.get("finished") or ot.get("isFinal")),
            )
            await self._emit(
                Transcript(
                    text=ot.get("text") or "",
                    final=bool(ot.get("finished") or ot.get("isFinal")),
                    speaker="assistant",
                )
            )

        if sc.get("interrupted"):
            logger.info("gemini_interrupted")

        if sc.get("generationComplete"):
            logger.info("gemini_generation_complete")

        if sc.get("turnComplete"):
            logger.info("gemini_turn_complete")
            await self._emit(AudioDone())

    async def _handle_tool_call(self, tc: dict[str, Any]) -> None:
        for fc in tc.get("functionCalls", []) or []:
            # Diagnostic instrumentation for Gemini 3-series.
            # `thought_signature` is documented for the REST API
            # `generateContent` path but its presence in the bidi Live
            # protocol's `toolCall` messages is undocumented. Some
            # third-party clients (Ollama, livekit-agents-js) hit
            # multi-turn function-call degradation when the signature
            # is dropped; if we ever see one here we'll need to echo it
            # back in send_tool_response. Log the raw fc keys at debug
            # level so a tail of prod logs reveals the field's
            # presence/absence without bloating normal output.
            extra_keys = sorted(k for k in fc.keys() if k not in {"name", "args", "id"})
            if extra_keys:
                logger.debug(
                    "gemini_tool_call_extra_keys",
                    name=fc.get("name"),
                    extra_keys=extra_keys,
                    has_thought_signature="thought_signature" in fc
                        or "thoughtSignature" in fc,
                )
            await self._emit(
                ToolCallEvent(
                    name=str(fc.get("name", "")),
                    args=dict(fc.get("args") or {}),
                    call_id=str(fc.get("id", "")),
                )
            )

    # ── Event queue ──

    async def _emit(self, event: Event) -> None:
        await self._events.put(event)
        if self.on_event:
            with contextlib.suppress(Exception):
                await self.on_event(event)

    async def events(self) -> AsyncIterator[Event]:
        while not self._closed:
            ev = await self._events.get()
            yield ev

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._recv_task is not None and not self._recv_task.done():
            self._recv_task.cancel()
            # CancelledError derives from BaseException, so suppress(Exception)
            # does NOT catch it — awaiting the cancelled task here used to throw
            # straight out of close(), out of the WS handler's finally block,
            # and skip session finalisation entirely (every voice_sessions row
            # kept a NULL ended_at and an empty transcript).
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await self._recv_task
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        self._ws = None
