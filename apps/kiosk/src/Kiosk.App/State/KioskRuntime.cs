using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Avalonia.Threading;
using Kiosk.App.Audio;
using Kiosk.App.Identity;
using Kiosk.App.Localization;
using Kiosk.App.Net;

namespace Kiosk.App.State;

/// <summary>
/// Single-instance orchestrator: owns the KioskClient (WS), AudioCapture (mic),
/// AudioPlayback (speaker), and the VAD gate. Wires events → SessionStore on
/// the UI thread.
///
/// Lifecycle:
///   StartAsync(menu) → loads device creds, opens audio devices, connects WS, starts capture pump.
///   StopAsync()   → reverse, idempotent.
///
/// One process = one KioskRuntime; instantiated by App in MainWindow handoff.
/// </summary>
public sealed class KioskRuntime : IAsyncDisposable
{
    public static KioskRuntime? Current { get; private set; }

    private KioskClient? _ws;
    private AudioCapture? _capture;
    private AudioPlayback? _playback;
    private CancellationTokenSource? _cts;
    private Task? _vadPumpTask;

    // RMS hysteresis state — replaces Silero VAD's role of animating the
    // MicOrb pulse. Backend audio_pipeline.py owns the actual conversation
    // gating; this is informational UI only.
    //   Onset:   rms ≥ 0.025  → speaking
    //   Release: rms < 0.015 for 5 consecutive frames (~160 ms) → silent
    private const float SpeakingOnsetRms = 0.025f;
    private const float SpeakingReleaseRms = 0.015f;
    private const int SpeakingHangoverFrames = 5;
    private bool _speakingForUi;
    private int _quietFrames;

    public AnalyserNode? Analyser => _playback?.Analyser;
    public string BackendUrl { get; private set; } = "";
    public string DeviceId { get; private set; } = "";
    /// <summary>Menu the current session was opened with. Read-only record of
    /// what was negotiated at connect time — changing it mid-session has no
    /// effect, the server bound its tool set when the socket opened.</summary>
    public string Menu { get; private set; } = "";

    /// <summary>True while the WS + audio devices are live. Toggled by Start/StopAsync.</summary>
    public bool IsActive { get; private set; }

    public KioskRuntime()
    {
        // Make this instance reachable from controls (MicOrb, pages) the moment
        // it's constructed — even before the user starts the voice session —
        // so they can call StartAsync/StopAsync via Current.
        Current = this;
        // Forward language changes to the backend so the printed receipt
        // matches the visitor's current UI locale even if they switch
        // mid-session. Static event, no need to unsubscribe — process
        // lifetime matches runtime lifetime.
        LocalizationService.LanguageChanged += lang =>
            _ = SendUiLanguageAsync(LocalizationService.LangCode(lang));
    }

    /// <summary>Send the visitor's current UI language to the backend so
    /// it can pick the right receipt locale at submission time. Safe to
    /// call before the WS is open — the underlying client no-ops.</summary>
    public Task SendUiLanguageAsync(string? langCode = null)
    {
        var code = langCode ?? LocalizationService.LangCode(LocalizationService.Current);
        return _ws?.SendUiLanguageAsync(code) ?? Task.FromResult(false);
    }

    /// <summary>Forward an explicit text turn to Gemini via the backend —
    /// used by the voice-preview confirm/reject buttons.</summary>
    public Task SendUserTextAsync(string text)
    {
        return _ws?.SendUserTextAsync(text) ?? Task.FromResult(false);
    }

    /// <summary>Start the voice loop: open audio devices, connect WS, begin capture pump.
    /// No-op if already active. Idempotent on rapid taps.
    ///
    /// <paramref name="menu"/> is the home tile the visitor opened. It travels
    /// on the WS URL and decides, server-side, which prompt focus block and
    /// which tools the agent gets — so it must be set BEFORE connecting, not
    /// negotiated afterwards.</summary>
    /// <summary>Serialises start/stop. Two callers now race for the same
    /// runtime — the page-change handler in MainWindow and AiPage's own Loaded
    /// — and both await inside, so the plain `IsActive` check is not enough to
    /// stop two Gemini sessions being opened at once.</summary>
    private readonly SemaphoreSlim _startGate = new(1, 1);

    public async Task StartAsync(string menu)
    {
        await _startGate.WaitAsync();
        try
        {
            await StartCoreAsync(menu);
        }
        finally
        {
            _startGate.Release();
        }
    }

    private async Task StartCoreAsync(string menu)
    {
        // A session already running for a DIFFERENT screen is worse than none:
        // the menu is baked into the WS URL, so the agent would still be
        // holding the timetable's tools and the timetable's focus block while
        // the visitor stands in front of the library. Swap it out.
        if (IsActive && !string.Equals(Menu, menu, StringComparison.Ordinal))
            await StopAsync();
        if (IsActive) return;

        var creds = DeviceKeyStore.Load();
        if (creds is null) throw new InvalidOperationException("no device credentials");
        BackendUrl = creds.BackendUrl;
        DeviceId = creds.DeviceId;
        Menu = menu;

        _playback = new AudioPlayback();
        _playback.Start();

        _capture = new AudioCapture();

        _ws = new KioskClient(
            creds.BackendUrl, creds.DeviceId, menu,
            LocalizationService.LangCode(LocalizationService.Current));
        WireWsEvents(_ws);
        _ws.Start();

        _cts = new CancellationTokenSource();
        _vadPumpTask = Task.Run(() => RunVadPump(_cts.Token));
        _capture.Start();

        IsActive = true;
        Dispatcher.UIThread.Post(() => SessionStore.Current.IsVoiceActive = true);
        await Task.CompletedTask;
    }

    /// <summary>Stop the voice loop: close WS (frees the Gemini Live session and stops
    /// burning tokens), tear down audio devices. Safe to call on an already-stopped runtime.</summary>
    public async Task StopAsync()
    {
        if (!IsActive) return;
        IsActive = false;

        _cts?.Cancel();
        if (_vadPumpTask is not null)
        {
            try { await _vadPumpTask.ConfigureAwait(false); } catch { }
            _vadPumpTask = null;
        }
        _cts?.Dispose();
        _cts = null;

        try { _capture?.Dispose(); } catch { }
        _capture = null;

        // Reset hysteresis state so the next session starts fresh.
        _speakingForUi = false;
        _quietFrames = 0;

        if (_ws is not null)
        {
            try { await _ws.DisposeAsync().ConfigureAwait(false); } catch { }
            _ws = null;
        }

        try { _playback?.Dispose(); } catch { }
        _playback = null;

        // Reflect the off-state in the UI (orb returns to "Sózlewge basıń",
        // offline overlay gets cleared, mic indicators reset).
        Avalonia.Threading.Dispatcher.UIThread.Post(() =>
        {
            SessionStore.Current.IsVoiceActive = false;
            SessionStore.Current.ShowOfflineOverlay = false;
            SessionStore.Current.ConnectionState = ConnectionState.Disconnected;
            SessionStore.Current.IsSpeaking = false;
            SessionStore.Current.InputLevel = 0f;
        });
    }

    public Task ToggleAsync(string menu) => IsActive ? StopAsync() : StartAsync(menu);

    private void OnUnauthorized()
    {
        // Server rejected our key — either the device was revoked, or our
        // local creds are stale. Wipe everything and fall to the "needs
        // re-enrollment" overlay. DeviceKeyStore.Clear() also destroys the
        // TPM key so the next enroll generates a brand-new keypair.
        try { DeviceKeyStore.Clear(); } catch { }
        Dispatcher.UIThread.Post(() => SessionStore.Current.OnDeviceRevoked());
        // Stop the runtime so we don't keep spinning the WS retry loop. The
        // RevokedOverlay.axaml takes over the UI; the user clicks "Janadan
        // kód kiritsin" to launch enrollment again.
        _ = StopAsync();
    }

    /// <summary>Debug-mode counter: bytes of audio received from server in the last 1 s window.</summary>
    private int _debugReceivedBytes;

    /// <summary>UTC timestamp of the most recent audio frame received from the agent.
    /// While this is fresh (within HalfDuplexHoldoff), the mic is muted to prevent
    /// the agent's own playback from leaking back into Gemini and corrupting turn detection.</summary>
    private DateTime _lastAgentFrameUtc = DateTime.MinValue;
    private static readonly TimeSpan HalfDuplexHoldoff = TimeSpan.FromMilliseconds(400);

    private void WireWsEvents(KioskClient ws)
    {
        ws.AudioReceived += pcm =>
        {
            _playback?.EnqueuePcm(pcm);
            _lastAgentFrameUtc = DateTime.UtcNow;
            System.Threading.Interlocked.Add(ref _debugReceivedBytes, pcm.Length);
        };

        ws.StateChanged += s =>
        {
            Dispatcher.UIThread.Post(() => SessionStore.Current.OnConnectionChanged(s));
            // Re-announce our UI language every time the socket re-connects.
            // Backend treats the value as authoritative for receipt locale.
            if (s == ConnectionState.Connected)
                _ = SendUiLanguageAsync();
        };
        ws.Unauthorized += OnUnauthorized;
        ws.NavigateReceived += n => Dispatcher.UIThread.Post(() => SessionStore.Current.OnNavigate(n.Screen));
        ws.TranscriptReceived += t => Dispatcher.UIThread.Post(() => SessionStore.Current.OnTranscript(t.Text, t.Final, t.Speaker));
        ws.MurojatPreviewReceived += p => Dispatcher.UIThread.Post(() => SessionStore.Current.OnMurojatPreview(p));
        ws.MurojatSubmittedReceived += s => Dispatcher.UIThread.Post(() => SessionStore.Current.OnMurojatSubmitted(s));
        ws.ScheduleReceived += s => Dispatcher.UIThread.Post(() => SessionStore.Current.OnSchedule(s));
        ws.GroupChoicesReceived += g => Dispatcher.UIThread.Post(() => SessionStore.Current.OnGroupChoices(g));
        ws.DirectionsReceived += d => Dispatcher.UIThread.Post(() => SessionStore.Current.OnDirections(d));
        ws.DirectionReceived += d => Dispatcher.UIThread.Post(() => SessionStore.Current.OnDirection(d));
        ws.BooksReceived += b => Dispatcher.UIThread.Post(() => SessionStore.Current.OnBooks(b));
        ws.BookSectionsReceived += b => Dispatcher.UIThread.Post(() => SessionStore.Current.OnBookSections(b));
        ws.LeadershipReceived += l => Dispatcher.UIThread.Post(() => SessionStore.Current.OnLeadership(l));
        ws.ReceptionPreviewReceived += r => Dispatcher.UIThread.Post(() => SessionStore.Current.OnReceptionPreview(r));
        ws.ReceptionSubmittedReceived += r => Dispatcher.UIThread.Post(() => SessionStore.Current.OnReceptionSubmitted(r));
        ws.InfoCardReceived += c => Dispatcher.UIThread.Post(() => SessionStore.Current.OnInfoCard(c));
        ws.AudioDoneReceived += () => Dispatcher.UIThread.Post(() => SessionStore.Current.OnAudioDone());
        ws.ErrorReceived += e => Dispatcher.UIThread.Post(() => SessionStore.Current.OnServerError(e.Code, e.Message));
    }

    private async Task RunVadPump(CancellationToken ct)
    {
        if (_capture is null || _ws is null) return;
        // 512 samples = AudioCapture.FramesPerBuffer at 16 kHz Int16 mono.
        var bytes = new byte[AudioCapture.FramesPerBuffer * 2];
        var lastUiUpdate = DateTime.MinValue;

        // KIOSK_DEBUG=1 → per-second console line with RMS + WS state.
        // Use when "agent doesn't respond": rules out a silent mic vs a
        // broken WS connection.
        var debug = Environment.GetEnvironmentVariable("KIOSK_DEBUG") == "1";
        var frameCount = 0;
        long debugSumRms = 0;
        var lastConsoleLog = DateTime.UtcNow;
        var sentFrames = 0;

        // First 5 seconds in debug mode → dump captured PCM to /tmp/kiosk-capture.wav
        // so the operator can play it back and hear whether the mic actually captured
        // intelligible voice (vs. chipmunked / silent / wrong device).
        var dumpSeconds = debug ? 5 : 0;
        var dumpStart = DateTime.UtcNow;
        var dumpBuffer = new System.Collections.Generic.List<byte>(16000 * 2 * dumpSeconds);
        var dumpDone = dumpSeconds == 0;

        await foreach (var pcm in _capture.Frames.ReadAllAsync(ct))
        {
            if (pcm.Length != AudioCapture.FramesPerBuffer) continue;
            frameCount++;
            var now = DateTime.UtcNow;

            long sumSq = 0;
            for (int i = 0; i < pcm.Length; i++) sumSq += pcm[i] * pcm[i];
            var rms = MathF.Sqrt(sumSq / (float)pcm.Length) / 32768f;

            // Hysteresis: prevents the MicOrb pulse from flickering on the
            // edge of conversational silence. Pure-RMS replacement for the
            // Silero VAD's `prob`. Onset crosses up at SpeakingOnsetRms;
            // release needs SpeakingHangoverFrames consecutive frames below
            // SpeakingReleaseRms (so ~160 ms quiet before the orb settles).
            if (!_speakingForUi && rms >= SpeakingOnsetRms)
            {
                _speakingForUi = true;
                _quietFrames = 0;
            }
            else if (_speakingForUi)
            {
                if (rms < SpeakingReleaseRms)
                {
                    if (++_quietFrames >= SpeakingHangoverFrames) _speakingForUi = false;
                }
                else
                {
                    _quietFrames = 0;
                }
            }

            if (debug)
            {
                debugSumRms += (long)(rms * 1000);

                // PCM accumulator for the WAV dump.
                if (!dumpDone)
                {
                    for (int i = 0; i < pcm.Length; i++)
                    {
                        var s = pcm[i];
                        dumpBuffer.Add((byte)(s & 0xff));
                        dumpBuffer.Add((byte)((s >> 8) & 0xff));
                    }
                    if ((now - dumpStart).TotalSeconds >= dumpSeconds)
                    {
                        WriteWav("/tmp/kiosk-capture.wav", dumpBuffer.ToArray(), 16000);
                        Console.WriteLine($"[mic] wrote /tmp/kiosk-capture.wav ({dumpBuffer.Count} bytes). play with: aplay /tmp/kiosk-capture.wav");
                        dumpBuffer.Clear();
                        dumpDone = true;
                    }
                }

                if ((now - lastConsoleLog).TotalSeconds >= 1)
                {
                    var avgRmsMilli = debugSumRms / Math.Max(1, frameCount);
                    var rxBytes = System.Threading.Interlocked.Exchange(ref _debugReceivedBytes, 0);
                    Console.WriteLine($"[mic] frames/s={frameCount} avgRms={avgRmsMilli / 1000.0:F3} speaking={_speakingForUi} ws={_ws.State} sent={sentFrames} rxBytes={rxBytes}");
                    lastConsoleLog = now;
                    debugSumRms = 0;
                    frameCount = 0;
                    sentFrames = 0;
                }
            }

            // Backend pipeline (audio_pipeline.py) does ALL gating: DC-offset
            // removal, TTS muting (zeros while agent speaks), energy squelch
            // (zeros during silence). Gemini's server VAD with HIGH/HIGH+500ms
            // sensitivity reads the resulting continuous stream. We just send
            // every frame raw. The RMS hysteresis above is UI-only.
            if ((now - lastUiUpdate).TotalMilliseconds >= 33)
            {
                lastUiUpdate = now;
                var speakingForUi = _speakingForUi;
                Avalonia.Threading.Dispatcher.UIThread.Post(() =>
                {
                    SessionStore.Current.InputLevel = rms;
                    SessionStore.Current.IsSpeaking = speakingForUi;
                });
            }

            for (int i = 0; i < pcm.Length; i++)
            {
                var s = pcm[i];
                bytes[i * 2 + 0] = (byte)(s & 0xff);
                bytes[i * 2 + 1] = (byte)((s >> 8) & 0xff);
            }
            if (await _ws.SendAudioAsync(bytes, ct).ConfigureAwait(false))
                sentFrames++;
        }
    }

    /// <summary>Writes a minimal RIFF/WAV header so /tmp/kiosk-capture.wav plays in any tool.</summary>
    private static void WriteWav(string path, byte[] pcm, int sampleRate)
    {
        using var fs = new System.IO.FileStream(path, System.IO.FileMode.Create);
        using var bw = new System.IO.BinaryWriter(fs);
        // RIFF header
        bw.Write(System.Text.Encoding.ASCII.GetBytes("RIFF"));
        bw.Write(36 + pcm.Length);
        bw.Write(System.Text.Encoding.ASCII.GetBytes("WAVE"));
        // fmt chunk (PCM, mono, sampleRate, 16-bit)
        bw.Write(System.Text.Encoding.ASCII.GetBytes("fmt "));
        bw.Write(16);                          // chunk size
        bw.Write((short)1);                    // PCM
        bw.Write((short)1);                    // channels
        bw.Write(sampleRate);                  // sample rate
        bw.Write(sampleRate * 2);              // byte rate
        bw.Write((short)2);                    // block align
        bw.Write((short)16);                   // bits per sample
        // data chunk
        bw.Write(System.Text.Encoding.ASCII.GetBytes("data"));
        bw.Write(pcm.Length);
        bw.Write(pcm);
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync().ConfigureAwait(false);
        if (ReferenceEquals(Current, this)) Current = null;
    }
}
