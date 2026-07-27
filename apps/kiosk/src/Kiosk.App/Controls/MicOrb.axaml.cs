using System;
using System.ComponentModel;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media;
using Avalonia.Threading;
using Kiosk.App.Localization;
using Kiosk.App.Net;
using Kiosk.App.State;

namespace Kiosk.App.Controls;

/// <summary>
/// Bottom-center persistent voice indicator. Mirrors the MicOrb from the old
/// kiosk_ui (React) port: shows connection state via colour + label, pulses
/// outward when the local VAD reports speech, and scales with the captured
/// audio RMS so the user gets immediate visual feedback that the mic is hot.
///
/// Pure indicator (no toggle). Voice on a kiosk is always-on once enrolled —
/// the user starts a conversation by speaking.
/// </summary>
public partial class MicOrb : UserControl
{
    private readonly DispatcherTimer _anim;

    public MicOrb()
    {
        InitializeComponent();
        DataContext = SessionStore.Current;

        _anim = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(33) };
        _anim.Tick += (_, _) => Tick();
        Loaded += (_, _) =>
        {
            _anim.Start();
            SessionStore.Current.PropertyChanged += OnSessionChanged;
            ApplyState();
        };
        Unloaded += (_, _) =>
        {
            _anim.Stop();
            SessionStore.Current.PropertyChanged -= OnSessionChanged;
        };
    }

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SessionStore.ConnectionState) ||
            e.PropertyName == nameof(SessionStore.IsSpeaking))
            ApplyState();
    }

    private void ApplyState()
    {
        var s = SessionStore.Current;
        var rt = KioskRuntime.Current;
        var isOff = rt is null || !rt.IsActive;

        if (isOff)
        {
            // Idle: tap to start. Accent ring so it reads as a CTA, not an error.
            Core.Background = Palette.Brush("KioskPrimary");
            Core.BorderBrush = Palette.Brush("KioskAccent");
            StatusLabel.Text = LocalizationService.Get("MicTapToStart");
            return;
        }
        if (s.ConnectionState != ConnectionState.Connected)
        {
            // Deliberately off-palette greys: "not connected" must not look
            // like any live brand state.
            Core.Background = new SolidColorBrush(Color.Parse("#374151"));
            Core.BorderBrush = new SolidColorBrush(Color.Parse("#4b5563"));
            StatusLabel.Text = LocalizationService.Get(
                s.ConnectionState == ConnectionState.Disconnected
                    ? "MicDisconnected"
                    : "MicConnecting");
            return;
        }
        if (s.IsSpeaking)
        {
            Core.Background = Palette.Brush("KioskPrimary");
            Core.BorderBrush = Palette.Brush("KioskPrimary");
            StatusLabel.Text = LocalizationService.Get("MicSpeaking");
        }
        else
        {
            Core.Background = Palette.Brush("KioskPrimaryDark");
            Core.BorderBrush = Palette.Brush("KioskPrimary");
            StatusLabel.Text = LocalizationService.Get("MicListening");
        }
    }

    private void Tick()
    {
        // PulseRing radius pulses with input RMS; clamp so quiet rooms still show 1.0.
        var level = SessionStore.Current.InputLevel;
        var scale = 1.0 + Math.Clamp(level, 0f, 0.5f) * 1.4;
        PulseRing.RenderTransform = new ScaleTransform(scale, scale);
    }

    /// <summary>Tap to start the voice session, tap again to stop. Stopping closes the
    /// WS + Gemini Live session, so the kiosk burns no tokens while idle.</summary>
    private async void OnPressed(object? sender, PointerPressedEventArgs e)
    {
        var rt = KioskRuntime.Current;
        if (rt is null) return;

        // Disable double-fire while the toggle is in flight.
        IsEnabled = false;
        string? startError = null;
        try
        {
            if (rt.IsActive)
            {
                StatusLabel.Text = LocalizationService.Get("MicStopping");
                await rt.StopAsync();
            }
            else
            {
                StatusLabel.Text = LocalizationService.Get("MicStarting");
                try
                {
                    // The menu is bound at connect time, so it has to come
                    // from wherever the visitor already is.
                    await rt.StartAsync(
                        SessionStore.MenuFor(SessionStore.Current.CurrentPage));
                }
                catch (Exception ex)
                {
                    // Silent mic failures are exactly the "kioskga 17 tumanga
                    // qatnamasligi uchun" scenario: user taps, sees nothing,
                    // has no idea why. Persist the full exception to
                    // crash.log alongside settings.json so the operator can
                    // diagnose without our help (or send us the file).
                    startError = ex.Message;
                    Console.Error.WriteLine("[mic] voice start failed: " + ex);
                    try
                    {
                        var logDir = System.IO.Path.GetDirectoryName(
                            Kiosk.App.Settings.KioskSettings.SettingsPath) ?? ".";
                        System.IO.Directory.CreateDirectory(logDir);
                        var path = System.IO.Path.Combine(logDir, "crash.log");
                        System.IO.File.AppendAllText(path,
                            $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] [mic-start] {ex}\n\n");
                    }
                    catch { /* nowhere safer to write to */ }
                }
            }
        }
        finally
        {
            IsEnabled = true;
            // If start failed, KEEP the error visible long enough to read
            // (5 s) before ApplyState resets the label to "Tap to start".
            // Without this the user just saw "Starting..." flicker and then
            // the orb back to idle — indistinguishable from a no-op tap.
            if (startError is not null)
            {
                StatusLabel.Text = $"{LocalizationService.Get("MicError")}: {Truncate(startError, 50)}";
                _ = Task.Delay(TimeSpan.FromSeconds(5)).ContinueWith(_ =>
                    Avalonia.Threading.Dispatcher.UIThread.Post(ApplyState));
            }
            else
            {
                ApplyState();
            }
        }
    }

    private static string Truncate(string s, int max) =>
        s.Length <= max ? s : s[..max] + "…";
}
