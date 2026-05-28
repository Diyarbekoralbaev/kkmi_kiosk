"""Inbound audio pipeline for /ws/kiosk/voice.

Ports the proven AVA / old-kiosk_voice.py audio stages so multi-turn voice
actually works:

  raw 16k PCM → DC-offset removal → TTS gating (silence bytes while agent
                speaks, NEVER drop frames) → energy-based upstream squelch
                (replace non-speech with zeros) → forward to Gemini

DIAGNOSTIC LOGGING is emitted once per second showing per-frame nonzero/zero
byte counts and squelch state — so we can tell whether actual speech is
reaching Gemini or whether the squelch is killing everything.
"""
from __future__ import annotations

import audioop
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

_logger = structlog.get_logger(__name__)

# Squelch tuned for an indoor government-kiosk environment (~30–40 dBA
# ambient, USB conference mic ~1 m from visitor, PipeWire echo_cancel_source
# in the input chain — see AudioCapture.PickInputDevice). Values informed by
# the VAD research session in [[gemini-cf-worker-relay]]'s memory + the
# 2024 Tandfonline study on elderly speech response windows.
#
# BASE_RMS 120 ≈ −48 dBFS — admits soft elderly speech (~−30 dBFS at the
# mic) without opening on HVAC/foot traffic (~−55 dBFS). The NOISE_FACTOR
# multiplier still floats the gate ~8 dB above each room's measured EMA
# noise floor, so the absolute value only matters in very quiet rooms.
SQUELCH_BASE_RMS = 120
SQUELCH_NOISE_FACTOR = 2.5
SQUELCH_ALPHA = 0.06
SQUELCH_MIN_SPEECH_FRAMES = 2
# 9 × 32 ms = ~290 ms tail. Just under Gemini's 300 ms server-side
# silenceDurationMs so the backend doesn't gate the stream before Gemini
# closes the turn (would otherwise cut audio while VAD still listening).
SQUELCH_END_SILENCE_FRAMES = 9

# After the agent stops speaking, drop any further outbound audio for this
# many ms so the speaker tail doesn't leak into the next user turn. The
# previous 600 ms was a pre-AEC legacy from the old AVA SIP stack; PipeWire's
# echo_cancel_source clears residual echo within ~100 ms, so 150 ms is a
# comfortable safety margin. This is the biggest single recovered chunk of
# voice-to-voice latency (saves ~450 ms on multi-turn flows).
OUTPUT_SUPPRESS_MS = 150


@dataclass
class AudioPipelineState:
    """Per-WS audio pipeline state. One instance per connected kiosk."""

    audio_capture_enabled: bool = True
    tts_playing: bool = False
    tts_started_ts: float = 0.0
    output_suppress_until: float = 0.0
    squelch: dict[str, Any] = field(default_factory=dict)

    # Diagnostic counters
    _next_log_ts: float = 0.0
    _nonzero_bytes: int = 0
    _zero_bytes: int = 0
    _frames_seen: int = 0
    _was_capture_enabled: bool = True
    _was_squelch_speaking: bool = False


def remove_dc_offset(pcm_bytes: bytes) -> bytes:
    """Subtract the running mean of the frame so the mic's DC bias doesn't
    skew downstream RMS / VAD calculations."""
    if not pcm_bytes:
        return pcm_bytes
    try:
        mean = int(audioop.avg(pcm_bytes, 2))
        if mean:
            return audioop.bias(pcm_bytes, 2, -mean)
    except Exception:
        pass
    return pcm_bytes


def apply_upstream_squelch(state: AudioPipelineState, pcm_bytes: bytes) -> bytes:
    """Replace non-speech frames with zeros (energy-based, EMA noise floor + hysteresis).

    Lifted verbatim from AVA engine.py via the old kiosk_voice.py. The squelch
    gates room noise without dropping the stream; Gemini sees continuous audio
    where user-speech regions carry real samples and silence regions are zeros.
    """
    sq = state.squelch
    try:
        energy = int(audioop.rms(pcm_bytes, 2)) if pcm_bytes else 0
    except Exception:
        energy = 0

    speaking = bool(sq.get("speaking", False))
    speech_frames = int(sq.get("speech_frames", 0) or 0)
    silence_frames = int(sq.get("silence_frames", 0) or 0)
    noise_ema = float(sq.get("noise_ema", 0.0) or 0.0)

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

    sq["speaking"] = speaking
    sq["speech_frames"] = speech_frames
    sq["silence_frames"] = silence_frames
    sq["noise_ema"] = noise_ema

    sq["last_energy"] = energy
    if not speaking:
        return b"\x00" * len(pcm_bytes)
    return pcm_bytes


def process_inbound(state: AudioPipelineState, pcm_bytes: bytes) -> bytes:
    """Run the full inbound pipeline: DC-offset → TTS gating → squelch.

    Always returns a buffer of the same length as the input. Caller should
    forward the result to Gemini even if it's all zeros — silence keeps the
    server VAD's turn-detection state consistent.
    """
    pcm_bytes = remove_dc_offset(pcm_bytes)
    if not state.audio_capture_enabled:
        pcm_bytes = b"\x00" * len(pcm_bytes)
    pcm_bytes = apply_upstream_squelch(state, pcm_bytes)

    # ── Diagnostic log: per-second nonzero/zero byte ratio + state edges ──
    state._frames_seen += 1
    nonzero = sum(1 for b in pcm_bytes if b != 0)
    state._nonzero_bytes += nonzero
    state._zero_bytes += len(pcm_bytes) - nonzero
    now = time.time()
    if now >= state._next_log_ts:
        sq_speaking = bool(state.squelch.get("speaking", False))
        _logger.info(
            "audio_pipeline",
            frames=state._frames_seen,
            nonzero=state._nonzero_bytes,
            zero=state._zero_bytes,
            capture_enabled=state.audio_capture_enabled,
            squelch_speaking=sq_speaking,
            tts_playing=state.tts_playing,
            noise_ema=int(state.squelch.get("noise_ema", 0)),
            last_energy=int(state.squelch.get("last_energy", 0)),
        )
        state._next_log_ts = now + 1.0
        state._frames_seen = 0
        state._nonzero_bytes = 0
        state._zero_bytes = 0
    return pcm_bytes


def on_agent_audio_chunk(state: AudioPipelineState) -> None:
    """Called when the model emits an audio chunk: enter TTS-active state."""
    if not state.tts_playing:
        state.tts_playing = True
        state.tts_started_ts = time.time()
    state.audio_capture_enabled = False


def on_agent_audio_done(state: AudioPipelineState) -> None:
    """Called on Gemini's turn_complete: open a 600 ms suppression window
    so the room echo tail can't be mistaken for the start of a new user turn."""
    state.tts_playing = False
    state.audio_capture_enabled = True
    state.tts_started_ts = 0.0
    state.output_suppress_until = time.time() + (OUTPUT_SUPPRESS_MS / 1000.0)


def is_output_suppressed(state: AudioPipelineState) -> bool:
    """True while we're inside the post-TTS echo-tail suppression window."""
    return state.output_suppress_until > time.time()
