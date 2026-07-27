using System;
using System.ComponentModel;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Kiosk.App.Localization;
using Kiosk.App.Net;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>Voice-assistant page with the 3D robot character. Robot is the
/// listening indicator (chest glow + bob animation driven by playback FFT
/// via Robot.Analyser). MicOrb is hidden by MainWindow while this page is
/// active. Voice session lifecycle:
///   - Loaded → wire analyser, StartAsync (idempotent), arm silence timer.
///   - Unloaded → tear down analyser + timer. Stop the runtime ONLY if we're
///     going back to Home; if the agent navigated us to Submit/Qabul to
///     complete a flow, keep the WS alive so the user can still talk.
///   - 30 s with no input-level / no transcript activity → bounce to Home.
/// </summary>
public partial class AiPage : UserControl
{
    private DispatcherTimer? _silenceTimer;
    private DateTime _lastActivityUtc = DateTime.UtcNow;
    private static readonly TimeSpan SilenceTimeout = TimeSpan.FromSeconds(30);

    public AiPage()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private async void OnLoaded(object? sender, RoutedEventArgs e)
    {
        // Cache the runtime reference once — Current is a static set on
        // KioskRuntime construction and cleared in DisposeAsync, so reading
        // it multiple times in quick succession is racy in theory. One
        // local copy keeps the rest of the method on a stable instance.
        var rt = KioskRuntime.Current;

        // Chest glow / bob animation tap into the playback chain's FFT.
        Robot.Analyser = rt?.Analyser;

        // Idempotent subscription: AiPage is not cached (a fresh instance
        // per visit per SessionStore.CurrentView), but the -= guard is
        // still useful if Loaded ever fires twice on the same instance
        // (e.g. visual-tree reattach).
        SessionStore.Current.PropertyChanged -= OnSessionChanged;
        SessionStore.Current.PropertyChanged += OnSessionChanged;
        UpdateStatus();

        // Auto-start the voice session. Robot is the mic; no manual MicOrb
        // tap needed. Idempotent in KioskRuntime so a re-entry doesn't
        // double-open audio devices.
        try
        {
            if (rt is not null && !rt.IsActive)
                await rt.StartAsync(SessionStore.MenuFor(KioskPage.Ai));
            // Re-wire the analyser after StartAsync — rt.Analyser only
            // exists once AudioPlayback is constructed inside StartAsync.
            Robot.Analyser = rt?.Analyser;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[ai-page] start failed: {ex.Message}");
        }

        _lastActivityUtc = DateTime.UtcNow;
        _silenceTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(5) };
        _silenceTimer.Tick += OnSilenceTick;
        _silenceTimer.Start();
    }

    private async void OnUnloaded(object? sender, RoutedEventArgs e)
    {
        if (_silenceTimer is not null)
        {
            _silenceTimer.Stop();
            _silenceTimer.Tick -= OnSilenceTick;
            _silenceTimer = null;
        }
        SessionStore.Current.PropertyChanged -= OnSessionChanged;
        Robot.Analyser = null;

        // Only close the WS + audio when returning to Home. If the agent
        // navigated us to Submit/Qabul mid-flow, keep the session alive so
        // the user can still talk to it (MicOrb returns to handle stop).
        if (SessionStore.Current.CurrentPage == KioskPage.Home)
        {
            try
            {
                if (KioskRuntime.Current is not null && KioskRuntime.Current.IsActive)
                    await KioskRuntime.Current.StopAsync();
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[ai-page] stop failed: {ex.Message}");
            }
        }
    }

    private void OnSilenceTick(object? sender, EventArgs e)
    {
        // Defensive against the cross-thread race between this tick (UI
        // dispatcher) and OnSessionChanged updating _lastActivityUtc when
        // IsSpeaking flips. If the visitor IS speaking at this exact tick,
        // treat as activity and reset the countdown — never auto-leave the
        // AI page while the user is mid-utterance.
        if (SessionStore.Current.IsSpeaking)
        {
            _lastActivityUtc = DateTime.UtcNow;
            return;
        }
        if ((DateTime.UtcNow - _lastActivityUtc) < SilenceTimeout) return;
        _silenceTimer?.Stop();
        SessionStore.Current.Navigate(KioskPage.Home);
    }

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs e)
    {
        // Any conversational signal resets the silence countdown.
        if (e.PropertyName == nameof(SessionStore.IsSpeaking)
            || e.PropertyName == nameof(SessionStore.LiveTranscript)
            || e.PropertyName == nameof(SessionStore.InputLevel))
        {
            _lastActivityUtc = DateTime.UtcNow;
        }
        if (e.PropertyName == nameof(SessionStore.ConnectionState)
            || e.PropertyName == nameof(SessionStore.IsSpeaking))
        {
            Dispatcher.UIThread.Post(UpdateStatus);
        }
    }

    private void UpdateStatus()
    {
        var s = SessionStore.Current;
        // Two states only — the chest glow conveys speaking/listening visually;
        // the status pill just confirms we're connected.
        var key = s.ConnectionState == ConnectionState.Connected
            ? "AiPageStatusListening"
            : "AiPageStatusConnecting";
        StatusText.Text = LocalizationService.Get(key);
    }
}
