"""
Test script for kiosk voice WebSocket endpoint.
Records mic audio, sends to backend, plays response.

Usage: python test_kiosk_voice.py
"""

import asyncio
import json
import signal
import sys
import wave
import io
import time

try:
    import websockets
except ImportError:
    print("pip install websockets")
    sys.exit(1)

try:
    import sounddevice as sd
    import numpy as np
except ImportError:
    print("pip install sounddevice numpy")
    sys.exit(1)

WS_URL = "ws://localhost:3003/ws/kiosk/voice"
INPUT_RATE = 16000
OUTPUT_RATE = 24000
CHUNK_MS = 20
CHUNK_SAMPLES = int(INPUT_RATE * CHUNK_MS / 1000)  # 320 samples per 20ms

running = True


def list_devices():
    print("\n--- Audio Devices ---")
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0:
            print(f"  [{i}] INPUT:  {d['name']} ({d['max_input_channels']}ch, {int(d['default_samplerate'])}Hz)")
        if d['max_output_channels'] > 0:
            print(f"  [{i}] OUTPUT: {d['name']} ({d['max_output_channels']}ch, {int(d['default_samplerate'])}Hz)")
    print()


async def main():
    global running

    list_devices()

    # Pick input device
    default_input = sd.default.device[0]
    inp = input(f"Input device [{default_input}]: ").strip()
    input_device = int(inp) if inp else default_input

    default_output = sd.default.device[1]
    out = input(f"Output device [{default_output}]: ").strip()
    output_device = int(out) if out else default_output

    print(f"\nConnecting to {WS_URL} ...")

    async with websockets.connect(WS_URL) as ws:
        print("Connected! Speak now. Ctrl+C to stop.\n")

        # Audio output buffer
        play_queue = asyncio.Queue()

        # --- Mic capture thread → WebSocket ---
        audio_buffer = asyncio.Queue()

        # Query device capabilities
        mic_info = sd.query_devices(input_device)
        mic_rate = int(mic_info['default_samplerate'])
        mic_channels = max(1, mic_info['max_input_channels'])
        print(f"  Mic: {mic_info['name']}, {mic_channels}ch, {mic_rate}Hz → resample to {INPUT_RATE}Hz mono")

        def mic_callback(indata, frames, time_info, status):
            if status:
                print(f"  [mic] {status}", file=sys.stderr)
            mono = indata[:, 0]
            # Resample if needed
            if mic_rate != INPUT_RATE:
                ratio = INPUT_RATE / mic_rate
                n_out = int(len(mono) * ratio)
                indices = np.arange(n_out) / ratio
                indices = np.clip(indices, 0, len(mono) - 1)
                mono = np.interp(indices, np.arange(len(mono)), mono)
            pcm16 = (mono * 32767).astype(np.int16)
            audio_buffer.put_nowait(pcm16.tobytes())

        mic_stream = sd.InputStream(
            samplerate=mic_rate,
            channels=mic_channels,
            dtype='float32',
            blocksize=int(mic_rate * CHUNK_MS / 1000),
            device=input_device,
            callback=mic_callback,
        )

        # --- Speaker playback with ring buffer ---
        import collections
        import threading

        play_buf = collections.deque()
        play_lock = threading.Lock()

        def play_callback(outdata, frames, time_info, status):
            with play_lock:
                available = len(play_buf)
                if available >= frames:
                    for i in range(frames):
                        outdata[i, 0] = play_buf.popleft()
                elif available > 0:
                    for i in range(available):
                        outdata[i, 0] = play_buf.popleft()
                    outdata[available:, 0] = 0.0
                else:
                    outdata.fill(0)

        speaker_stream = sd.OutputStream(
            samplerate=OUTPUT_RATE,
            channels=1,
            dtype='float32',
            blocksize=1024,
            device=output_device,
            callback=play_callback,
        )

        mic_stream.start()
        speaker_stream.start()

        # --- Send mic audio to WebSocket ---
        async def send_loop():
            while running:
                try:
                    data = await asyncio.wait_for(audio_buffer.get(), timeout=0.1)
                    await ws.send(data)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    print(f"  [send] error: {e}")
                    break

        # --- Receive from WebSocket ---
        async def recv_loop():
            while running:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    if isinstance(msg, bytes):
                        # Audio from Gemini — decode int16 → float32, push to ring buffer
                        pcm16 = np.frombuffer(msg, dtype=np.int16)
                        float_samples = pcm16.astype(np.float32) / 32767.0
                        with play_lock:
                            play_buf.extend(float_samples)
                    else:
                        data = json.loads(msg)
                        if data.get("type") == "transcript":
                            text = data.get("text", "")
                            if text.strip():
                                print(f"  [transcript] {text}")
                        elif data.get("type") == "audio_done":
                            print("  [turn complete]")
                        elif data.get("type") == "disconnected":
                            print(f"  [disconnected] {data.get('reason', '')}")
                            break
                        elif data.get("type") == "barge_in":
                            print("  [barge-in detected]")
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed:
                    print("  [ws closed]")
                    break
                except Exception as e:
                    print(f"  [recv] error: {e}")
                    break

        def handle_signal(*args):
            global running
            running = False
            print("\nStopping...")

        signal.signal(signal.SIGINT, handle_signal)

        await asyncio.gather(send_loop(), recv_loop())

        mic_stream.stop()
        speaker_stream.stop()
        mic_stream.close()
        speaker_stream.close()

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
