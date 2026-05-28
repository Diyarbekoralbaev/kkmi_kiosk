using System;
using System.Runtime.InteropServices;
using System.Threading.Channels;
using PortAudioSharp;
using PaStream = PortAudioSharp.Stream;

namespace Kiosk.App.Audio;

/// <summary>
/// Captures microphone audio at 16 kHz Int16 mono and pushes 512-sample (32 ms)
/// frames into a Channel for downstream consumers (WS upstream + UI animation).
///
/// PortAudio on Linux talks to the default ALSA/PipeWire input. On Windows
/// it picks the default WASAPI/MME device.
///
/// Echo cancellation chain (top-down, where the speaker's own audio gets removed):
///
///   1. OS-level (first, cheap, automatic):
///        - Linux: PipeWire's <c>echo_cancel_source</c> via module-echo-cancel,
///          reached by preferring the "pulse" device in <see cref="PickInputDevice"/>.
///        - Windows: WASAPI default capture — the OS communications mixer
///          handles AEC when the device is wired up via Sound Control Panel.
///   2. Backend (final gate before Gemini):
///        - <c>audio_pipeline.process_inbound</c>: DC-offset removal, TTS
///          muting (zeros mic while the agent speaks), EMA energy squelch,
///          and a 600 ms post-TTS output-suppression window so the speaker
///          tail can't leak into the next user turn.
///   3. Client-side: none. No adaptive filter (LMS/RLS/Speex) in this app.
///          A future slice can add WASAPI Communications-mode wiring via
///          PaWasapiStreamInfo if OS-level AEC proves insufficient in the
///          field.
/// </summary>
public sealed class AudioCapture : IDisposable
{
    public const int SampleRate = 16000;
    public const int FramesPerBuffer = 512;

    private readonly Channel<short[]> _channel = Channel.CreateUnbounded<short[]>(
        new UnboundedChannelOptions { SingleReader = true, SingleWriter = true });
    private readonly PaStream _stream;
    private readonly PaStream.Callback _callback;
    private bool _disposed;

    public ChannelReader<short[]> Frames => _channel.Reader;

    public AudioCapture(int? deviceIndex = null)
    {
        PortAudioLifecycle.Init();
        var device = deviceIndex ?? PickInputDevice();
        if (device == PortAudio.NoDevice)
        {
            PortAudioLifecycle.Terminate();
            throw new InvalidOperationException("no audio input device");
        }
        var info = PortAudio.GetDeviceInfo(device);
        var input = new StreamParameters
        {
            device = device,
            channelCount = 1,
            sampleFormat = SampleFormat.Int16,
            suggestedLatency = info.defaultLowInputLatency,
            hostApiSpecificStreamInfo = IntPtr.Zero,
        };
        _callback = OnAudioCallback;
        _stream = new PaStream(input, null, SampleRate, FramesPerBuffer, StreamFlags.NoFlag, _callback, IntPtr.Zero);
    }

    public void Start() => _stream.Start();

    public void Stop()
    {
        if (!_stream.IsStopped) _stream.Stop();
    }

    private StreamCallbackResult OnAudioCallback(
        IntPtr input, IntPtr _output, uint frameCount,
        ref StreamCallbackTimeInfo timeInfo, StreamCallbackFlags statusFlags, IntPtr _userData)
    {
        if (input == IntPtr.Zero) return StreamCallbackResult.Continue;
        var pcm = new short[frameCount];
        Marshal.Copy(input, pcm, 0, (int)frameCount);
        // Channel write must not allocate or block — TryWrite is bounded-time on unbounded.
        _channel.Writer.TryWrite(pcm);
        return StreamCallbackResult.Continue;
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        try { Stop(); } catch { }
        _stream.Dispose();
        _channel.Writer.TryComplete();
        PortAudioLifecycle.Terminate();
    }

    /// <summary>
    /// Picks an input device with these preferences:
    ///   1. KIOSK_AUDIO_INPUT env var (numeric index) — operator override.
    ///   2. The "pulse" device when present — routes through the user's
    ///      PulseAudio/PipeWire default source (e.g., echo_cancel_source on
    ///      a PipeWire AEC setup), which is what we actually want.
    ///   3. PortAudio's reported DefaultInputDevice as a last resort.
    /// Production deploys can pin a specific device via the env var or by
    /// later wiring up a settings UI.
    /// </summary>
    private static int PickInputDevice()
    {
        var envOverride = Environment.GetEnvironmentVariable("KIOSK_AUDIO_INPUT");
        if (!string.IsNullOrEmpty(envOverride) && int.TryParse(envOverride, out var idx))
            return idx;

        // Operator-pinned device from admin settings. Stored as the device's
        // DisplayName ("Microphone (USB) [WASAPI]") which both (a) survives
        // PortAudio device-index churn from USB reorder / sound server
        // restart, and (b) disambiguates the same physical mic that appears
        // under multiple Windows host APIs. FindIndexByDisplayName also
        // accepts a legacy name-only pin (settings.json written before the
        // host-API suffix was introduced) so an upgrade doesn't re-prompt.
        var pinnedName = Settings.KioskSettings.Current.AudioInputDevice;
        if (!string.IsNullOrEmpty(pinnedName))
        {
            var pinnedIdx = AudioDeviceList.FindIndexByDisplayName(pinnedName, input: true);
            if (pinnedIdx >= 0) return pinnedIdx;
        }

        for (int i = 0; i < PortAudio.DeviceCount; i++)
        {
            var info = PortAudio.GetDeviceInfo(i);
            if (info.maxInputChannels > 0 &&
                string.Equals(info.name, "pulse", StringComparison.OrdinalIgnoreCase))
                return i;
        }
        return PortAudio.DefaultInputDevice;
    }
}
