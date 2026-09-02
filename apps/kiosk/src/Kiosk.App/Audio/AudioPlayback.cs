using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using PortAudioSharp;
using PaStream = PortAudioSharp.Stream;

namespace Kiosk.App.Audio;

/// <summary>
/// 24 kHz Int16 mono playback driven by a queue of incoming PCM. Used to play
/// audio frames received from /ws/kiosk/voice (Gemini → kiosk direction).
///
/// `EnqueuePcm` pushes raw bytes (the WS binary frame, Int16 LE). The
/// PortAudio output callback drains the queue at the playback rate, padding
/// with silence if the queue is empty (no glitches on momentary starvation).
/// </summary>
public sealed class AudioPlayback : IDisposable
{
    public const int SampleRate = 24000;
    public const int FramesPerBuffer = 480; // 20 ms at 24 kHz

    private readonly Queue<short> _queue = new();
    private readonly object _lock = new();
    private readonly PaStream _stream;
    private readonly PaStream.Callback _callback;
    private bool _disposed;


    public AudioPlayback(int? deviceIndex = null)
    {
        PortAudioLifecycle.Init();
        var device = deviceIndex ?? PickOutputDevice();
        if (device == PortAudio.NoDevice)
        {
            PortAudioLifecycle.Terminate();
            throw new InvalidOperationException("no audio output device");
        }
        var info = PortAudio.GetDeviceInfo(device);
        var output = new StreamParameters
        {
            device = device,
            channelCount = 1,
            sampleFormat = SampleFormat.Int16,
            suggestedLatency = info.defaultLowOutputLatency,
            hostApiSpecificStreamInfo = IntPtr.Zero,
        };
        _callback = OnAudioCallback;
        _stream = new PaStream(null, output, SampleRate, FramesPerBuffer, StreamFlags.NoFlag, _callback, IntPtr.Zero);
    }

    public void Start() => _stream.Start();
    public void Stop()
    {
        if (!_stream.IsStopped) _stream.Stop();
    }

    /// <summary>Pushes raw Int16 LE PCM bytes (mono, 24 kHz) for playback.</summary>
    public void EnqueuePcm(ReadOnlySpan<byte> pcmBytes)
    {
        // Two bytes per sample, LE.
        if ((pcmBytes.Length & 1) != 0) return; // ignore odd-length junk

        lock (_lock)
        {
            for (int i = 0; i < pcmBytes.Length; i += 2)
            {
                short s = (short)(pcmBytes[i] | (pcmBytes[i + 1] << 8));
                _queue.Enqueue(s);
            }
        }
    }

    /// <summary>Drops any queued audio. Call when the agent stops speaking mid-utterance.</summary>
    public void Flush()
    {
        lock (_lock) _queue.Clear();
    }

    private StreamCallbackResult OnAudioCallback(
        IntPtr _input, IntPtr output, uint frameCount,
        ref StreamCallbackTimeInfo timeInfo, StreamCallbackFlags statusFlags, IntPtr _userData)
    {
        var samples = new short[frameCount];
        lock (_lock)
        {
            int n = (int)frameCount;
            int avail = _queue.Count < n ? _queue.Count : n;
            for (int i = 0; i < avail; i++) samples[i] = _queue.Dequeue();
            // Remaining samples already 0 (silence) by array init.
        }
        Marshal.Copy(samples, 0, output, samples.Length);
        return StreamCallbackResult.Continue;
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        try { Stop(); } catch { }
        _stream.Dispose();
        PortAudioLifecycle.Terminate();
    }

    /// <summary>
    /// Symmetric with AudioCapture.PickInputDevice — prefer the "pulse" backend
    /// so playback routes through the user's actual default sink (echo_cancel_sink
    /// on a PipeWire AEC setup) instead of ALSA's "default" PCM which can map to
    /// a 32-channel surround device that drops mono playback.
    /// </summary>
    private static int PickOutputDevice()
    {
        var envOverride = Environment.GetEnvironmentVariable("KIOSK_AUDIO_OUTPUT");
        if (!string.IsNullOrEmpty(envOverride) && int.TryParse(envOverride, out var idx))
            return idx;

        var pinnedName = Settings.KioskSettings.Current.AudioOutputDevice;
        if (!string.IsNullOrEmpty(pinnedName))
        {
            for (int i = 0; i < PortAudio.DeviceCount; i++)
            {
                var info = PortAudio.GetDeviceInfo(i);
                if (info.maxOutputChannels > 0 &&
                    string.Equals(info.name, pinnedName, StringComparison.OrdinalIgnoreCase))
                    return i;
            }
        }

        for (int i = 0; i < PortAudio.DeviceCount; i++)
        {
            var info = PortAudio.GetDeviceInfo(i);
            if (info.maxOutputChannels > 0 &&
                string.Equals(info.name, "pulse", StringComparison.OrdinalIgnoreCase))
                return i;
        }
        return PortAudio.DefaultOutputDevice;
    }
}
