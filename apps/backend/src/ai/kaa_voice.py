"""Karakalpak voice transport — bridges the kiosk WS to the local
STT→LLM→TTS WebSocket server (Pipecat: Omnilingual STT + Gemini 2.5
Flash-Lite + OmniVoice TTS) instead of Gemini Live.

Presents the SAME interface as ``GeminiLiveSession`` (start / run / events /
send_audio / send_text / send_tool_response / close, yielding the same event
dataclasses), so ``kiosk_ws.py`` uses it interchangeably behind the
``VOICE_BACKEND`` flag — the kiosk-facing protocol is unchanged.

Audio matches the kiosk natively: 16 kHz PCM in, 24 kHz PCM out — no resample.
Each connection's ``setup`` carries our DB system prompt + tool schemas; tool
calls arrive as ``{"type":"tool_call"}`` and we answer with
``{"type":"tool_result"}``. There is no auto-greeting (the server speaks only
after the visitor talks) and no agent transcript (only the user's STT
transcript is relayed). The server has no end-of-turn marker for TTS, so we
synthesize ``AudioDone`` after a short audio gap — the kiosk uses it to end the
"speaking" state and open its post-TTS echo-suppression window.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
import websockets

from ..core.errors import ProviderError
from .gemini_live import (
    AudioDone,
    AudioOut,
    Event,
    ProviderClosed,
    ProviderErrorEvent,
    ToolCallEvent,
    Transcript,
)
from .prompt_builder import AgentConfig
from .tools import declarations_for

logger = structlog.get_logger(__name__)

# TTS chunks arrive with no end-of-turn marker; this much silence ends the turn.
_AUDIO_DONE_GAP_SEC = 0.5


@dataclass
class KaaVoiceSession:
    config: AgentConfig
    ws_url: str

    _ws: Any = field(default=None, init=False)
    _q: asyncio.Queue[Event] = field(default_factory=asyncio.Queue, init=False)
    _closed: bool = field(default=False, init=False)
    _speaking: bool = field(default=False, init=False)
    _last_audio: float = field(default=0.0, init=False)
    _watch_task: Any = field(default=None, init=False)

    async def start(self) -> None:
        try:
            self._ws = await websockets.connect(
                self.ws_url,
                max_size=10 * 1024 * 1024,
                open_timeout=15,
                ping_interval=20,
                ping_timeout=20,
            )
            await self._ws.send(
                json.dumps(
                    {
                        "type": "setup",
                        "system_prompt": self.config.system_prompt,
                        "tools": declarations_for(self.config.enabled_tools),
                    },
                    ensure_ascii=False,
                )
            )
            raw = await asyncio.wait_for(self._ws.recv(), timeout=15)
            msg = json.loads(raw) if isinstance(raw, str) else {}
            if msg.get("type") != "ready":
                raise ProviderError("kaa_not_ready")
            logger.info(
                "kaa_session_ready", url=self.ws_url, tools=len(self.config.enabled_tools)
            )
        except ProviderError:
            raise
        except Exception as e:
            logger.error(
                "kaa_connect_failed",
                url=self.ws_url,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise ProviderError(cause=e) from e

    async def run(self) -> None:
        self._watch_task = asyncio.create_task(self._audio_done_watch())
        try:
            async for message in self._ws:
                if isinstance(message, (bytes, bytearray)):
                    self._speaking = True
                    self._last_audio = time.monotonic()
                    await self._q.put(AudioOut(pcm=bytes(message)))
                    continue
                try:
                    ev = json.loads(message)
                except Exception:
                    continue
                t = ev.get("type")
                if t == "transcript":
                    text = str(ev.get("text", "") or "")
                    if text:
                        await self._q.put(
                            Transcript(
                                text=text, final=True, speaker=str(ev.get("role", "user"))
                            )
                        )
                elif t == "tool_call":
                    await self._q.put(
                        ToolCallEvent(
                            name=str(ev.get("name", "")),
                            args=dict(ev.get("args", {}) or {}),
                            call_id=str(ev.get("id", "")),
                        )
                    )
                elif t == "error":
                    await self._q.put(
                        ProviderErrorEvent(code=str(ev.get("error", "kaa_error")))
                    )
        except Exception as e:
            logger.warning(
                "kaa_recv_ended", error=str(e), error_type=type(e).__name__
            )
        finally:
            await self._q.put(ProviderClosed())

    async def _audio_done_watch(self) -> None:
        while not self._closed:
            await asyncio.sleep(0.15)
            if self._speaking and (time.monotonic() - self._last_audio) >= _AUDIO_DONE_GAP_SEC:
                self._speaking = False
                await self._q.put(AudioDone())

    async def events(self):
        while True:
            ev = await self._q.get()
            yield ev
            if isinstance(ev, ProviderClosed):
                break

    async def send_audio(self, pcm: bytes, sample_rate: int = 16000) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(pcm)
        except Exception:
            pass

    async def send_text(self, text: str) -> None:
        # The Kaa server is audio-only (STT drives each turn) — no text
        # injection. Greeting is off and confirmations come via the visitor's
        # speech, so this is a no-op (covers the "[START]" kickoff + user_text).
        logger.info("kaa_send_text_noop", text_len=len(text or ""))

    async def send_tool_response(
        self, call_id: str, name: str, result: dict[str, Any]
    ) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(
                json.dumps(
                    {"type": "tool_result", "id": call_id, "result": result},
                    ensure_ascii=False,
                )
            )
        except Exception as e:
            logger.warning("kaa_tool_result_failed", name=name, error=str(e))

    async def close(self) -> None:
        self._closed = True
        if self._watch_task is not None:
            self._watch_task.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
