using System;
using System.ComponentModel;
using System.Net;
using System.Net.Http.Json;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Kiosk.App.Identity;
using Kiosk.App.Localization;
using Kiosk.App.Net;
using Kiosk.App.Pages;
using Kiosk.App.State;
using Kiosk.App.Update;

namespace Kiosk.App;

public partial class MainWindow : Window
{
    private readonly KioskRuntime _runtime = new();
    private DispatcherTimer? _idleTimer;
    // Bumped from 30 s and now also reset by voice activity. The previous
    // version only reset on touch/keypress, so an active voice conversation
    // would get its in-progress submit nuked mid-dialog.
    private static readonly TimeSpan IdleTimeout = TimeSpan.FromMinutes(2);

    public MainWindow()
    {
        InitializeComponent();
        DataContext = SessionStore.Current;
        Opened += OnOpened;
        Closed += OnClosed;

        // Any user input resets the idle timer.
        AddHandler(InputElement.PointerPressedEvent, (_, _) => RestartIdleTimer(), Avalonia.Interactivity.RoutingStrategies.Tunnel);
        AddHandler(InputElement.KeyDownEvent, OnKeyDownIntercept, Avalonia.Interactivity.RoutingStrategies.Tunnel);

        // Admin hot-zone: 5 taps in the top-left corner within 3 s → PIN dialog
        // → choice dialog (Exit / Settings / Cancel). Replaces the old
        // 3-second long-press, which proved unreliable on glossy touchscreens
        // (jitter / lift-off mid-hold cancelled the timer).
        AdminHotZone.PointerPressed += OnAdminPress;

        // Centralized revoke handler. Every signed HTTP call funnels 401/403
        // here — whichever endpoint surfaces it first (heartbeat, officials,
        // update check, appointment submit) trips the red overlay so the
        // visitor sees the kiosk is locked, not just an empty page.
        SignedHttpClient.DeviceRevoked += OnDeviceRevoked;
    }

    private void OnDeviceRevoked()
    {
        Dispatcher.UIThread.Post(() =>
        {
            try { _ = _runtime.StopAsync(); } catch { }
            SessionStore.Current.OnDeviceRevoked();
        });
    }

    private const int AdminTapTarget = 5;
    private static readonly TimeSpan AdminTapWindow = TimeSpan.FromSeconds(3);
    private int _adminTapCount;
    private DateTime _adminFirstTap;
    private bool _adminFlowOpen;

    /// <summary>Block escape hatches that would let a visitor leave the kiosk
    /// app: Alt+F4 (close), Ctrl+Esc (Start menu), Alt+Tab (window switch),
    /// LWin/RWin (Start menu). The Win key is best-effort — true lockdown
    /// of OS chrome lives in scripts/install-windows.ps1 (Assigned Access).</summary>
    private void OnKeyDownIntercept(object? sender, KeyEventArgs e)
    {
        RestartIdleTimer();
        if (e.Key == Key.F4 && e.KeyModifiers.HasFlag(KeyModifiers.Alt)) e.Handled = true;
        else if (e.Key == Key.Escape && e.KeyModifiers.HasFlag(KeyModifiers.Control)) e.Handled = true;
        else if (e.Key == Key.LWin || e.Key == Key.RWin) e.Handled = true;
        else if (e.Key == Key.Tab && e.KeyModifiers.HasFlag(KeyModifiers.Alt)) e.Handled = true;
    }

    private void OnAdminPress(object? sender, PointerPressedEventArgs e)
    {
        if (_adminFlowOpen) return;
        var now = DateTime.UtcNow;
        if (_adminTapCount == 0 || (now - _adminFirstTap) > AdminTapWindow)
        {
            _adminTapCount = 1;
            _adminFirstTap = now;
            return;
        }
        _adminTapCount++;
        if (_adminTapCount >= AdminTapTarget)
        {
            _adminTapCount = 0;
            _ = ShowAdminFlowAsync();
        }
    }

    private async Task ShowAdminFlowAsync()
    {
        if (_adminFlowOpen) return;
        _adminFlowOpen = true;
        try
        {
            var pinDialog = new AdminPinDialog();
            await pinDialog.ShowDialog(this);
            if (!pinDialog.Authorized) return;

            var choice = new AdminChoiceDialog();
            await choice.ShowDialog(this);
            switch (choice.Result)
            {
                case AdminChoice.Exit:
                    // Clean shutdown — Velopack hooks (Updater.Bootstrap)
                    // already ran at startup, so this just closes the window.
                    Dispatcher.UIThread.Post(() =>
                    {
                        if (Avalonia.Application.Current?.ApplicationLifetime is
                            Avalonia.Controls.ApplicationLifetimes.IClassicDesktopStyleApplicationLifetime desktop)
                        {
                            desktop.Shutdown(0);
                        }
                    });
                    break;

                case AdminChoice.Settings:
                    // Free audio devices so AdminSettings's mic/speaker
                    // pickers see every option; new selection takes effect
                    // on the next MicOrb tap.
                    try { await _runtime.StopAsync(); } catch { }
                    var settings = new AdminSettingsWindow();
                    await settings.ShowDialog(this);
                    break;

                case AdminChoice.None:
                default:
                    break;
            }
        }
        finally
        {
            _adminFlowOpen = false;
        }
    }

    private void OnOpened(object? sender, EventArgs e)
    {
        // Lockdown: ONLY in Release builds. In DEBUG we keep a normal
        // resizable window so the developer can see their terminal,
        // debugger, etc. On Linux/X11 setting WindowState=FullScreen via
        // XAML often doesn't take effect when SystemDecorations=None — the
        // WM treats the window as a popup. Applying programmatically after
        // the window is realized works reliably on both X11 and Win32.
        if (!DebugFlags.IsDebugBuild)
        {
            // Avalonia 12 renamed: property + enum are both WindowDecorations.
            WindowDecorations = Avalonia.Controls.WindowDecorations.None;
            WindowState = WindowState.FullScreen;
            CanResize = false;
            Topmost = true;
        }

        // Hydrate the header's org name from the last persisted heartbeat
        // BEFORE ProbeAuthAsync runs. Without this, every cold start shows
        // an empty branding gap for ~1 s while waiting for the network probe.
        try
        {
            var creds = DeviceKeyStore.Load();
            if (creds is not null && !string.IsNullOrWhiteSpace(creds.OrgName))
            {
                SessionStore.Current.UpdateOrgBranding(
                    creds.OrgNameTranslations, creds.OrgName);
                SessionStore.Current.UpdateContactInfo(
                    creds.OrgAddressTranslations,
                    creds.OrgEmail,
                    creds.OrgWorkHoursTranslations,
                    creds.HelplinePhone);
            }
        }
        catch { /* corrupt creds get force-cleared elsewhere */ }

        // Voice session is OFF by default — user taps the MicOrb to start it.
        // That keeps the kiosk idle (no Gemini tokens burned) when no one is at it.
        // _runtime.Current is already set by its constructor so the orb can find it.

        // Force-update gate: if a newer release is published, pull it down and
        // hand off to Velopack BEFORE the user can do anything. Mandatory
        // releases block the kiosk until the update is applied; non-mandatory
        // releases still install but the user could (in future) skip.
        _ = RunUpdateGateAsync();

        // Probe the backend with a heartbeat right at startup. If the device key
        // was revoked while the kiosk was off, surface the red overlay immediately
        // — without this the user would happily tap the MicOrb only to find out.
        _ = ProbeAuthAsync();

        _idleTimer = new DispatcherTimer { Interval = IdleTimeout };
        _idleTimer.Tick += (_, _) =>
        {
            // After 2 min of total inactivity, drop back to home AND stop the voice
            // session if it's still running — saves Gemini quota when someone walks
            // away mid-conversation.
            SessionStore.Current.ResetIdle();
            _ = _runtime.StopAsync();
        };
        _idleTimer.Start();

        // Voice activity (user speaking OR agent just spoke) also resets the
        // idle timer — otherwise a conversation that goes past the timeout
        // gets reset to home mid-flow.
        SessionStore.Current.PropertyChanged += OnSessionPropertyChanged;
    }

    private void OnSessionPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        // Any meaningful conversation signal counts as activity.
        if (e.PropertyName == nameof(SessionStore.IsSpeaking) ||
            e.PropertyName == nameof(SessionStore.LiveTranscript) ||
            e.PropertyName == nameof(SessionStore.SubmitStep) ||
            e.PropertyName == nameof(SessionStore.CurrentPage))
        {
            RestartIdleTimer();
        }
        // Hide the MicOrb on the AI assistant page — the robot's chest glow
        // is the listening indicator there. Show it everywhere else.
        if (e.PropertyName == nameof(SessionStore.CurrentPage))
        {
            MicOrb.IsVisible = SessionStore.Current.CurrentPage != KioskPage.Ai;
        }
    }

    private async void OnClosed(object? sender, EventArgs e)
    {
        _idleTimer?.Stop();
        SessionStore.Current.PropertyChanged -= OnSessionPropertyChanged;
        SignedHttpClient.DeviceRevoked -= OnDeviceRevoked;
        await _runtime.DisposeAsync();
    }

    /// <summary>Dict equality by content. Used to decide whether the
    /// heartbeat brought a fresh org_name_translations payload that we
    /// should persist back to DeviceCredentials.</summary>
    private static bool TranslationDictsEqual(
        System.Collections.Generic.IReadOnlyDictionary<string, string>? a,
        System.Collections.Generic.IReadOnlyDictionary<string, string>? b)
    {
        if (a is null && b is null) return true;
        a ??= new System.Collections.Generic.Dictionary<string, string>();
        b ??= new System.Collections.Generic.Dictionary<string, string>();
        if (a.Count != b.Count) return false;
        foreach (var kvp in a)
        {
            if (!b.TryGetValue(kvp.Key, out var v) || v != kvp.Value) return false;
        }
        return true;
    }

    private void RestartIdleTimer()
    {
        if (_idleTimer is null) return;
        _idleTimer.Stop();
        _idleTimer.Start();
    }

    /// <summary>Check the backend for a newer release and apply if available.
    /// Runs on every startup. Mandatory releases lock voice until done; the
    /// MicOrb is gated on SessionStore.IsUpdating during the flow.</summary>
    private async Task RunUpdateGateAsync()
    {
        try
        {
            var info = await Updater.CheckAsync();
            if (info is null) return;

            // Swap content to the full-screen updating overlay.
            var page = new UpdatingPage();
            page.SetVersion(info.Version);
            page.SetStatus(info.Mandatory
                ? LocalizationService.Get("UpdatingMandatory")
                : LocalizationService.Get("UpdatingApplying"));
            Dispatcher.UIThread.Post(() => Content = page);

            var ok = await Updater.ApplyAsync(info, page.SetProgress);
            if (ok)
            {
                page.SetStatus(LocalizationService.Get("UpdatingApplying"));
                // Velopack's WaitExitThenApplyUpdates needs us to actually
                // exit. Avalonia shutdown path closes the window and lets
                // the helper run.
                Dispatcher.UIThread.Post(() =>
                {
                    if (Avalonia.Application.Current?.ApplicationLifetime is
                        Avalonia.Controls.ApplicationLifetimes.IClassicDesktopStyleApplicationLifetime desktop)
                    {
                        desktop.Shutdown(0);
                    }
                });
            }
            else
            {
                page.SetStatus(LocalizationService.Get("UpdatingFailed"));
                // Wait a few seconds so the operator can see the message,
                // then restore normal UI.
                await Task.Delay(TimeSpan.FromSeconds(4));
                Dispatcher.UIThread.Post(RestoreMainContent);
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[update] gate failed: {ex.Message}");
            // Don't block startup on a broken update path.
        }
    }

    private void RestoreMainContent()
    {
        // Re-bind the original ContentControl tree (defined in MainWindow.axaml)
        // by forcing a re-read of the DataContext root.
        var origRoot = (Avalonia.Markup.Xaml.AvaloniaXamlLoader.Load(
            new Uri("avares://Kiosk.App/MainWindow.axaml"))) as Window;
        if (origRoot is not null) Content = origRoot.Content;
    }

    /// <summary>POST /api/kiosk/heartbeat with a TPM-signed nonce. Any 401/403
    /// (including from the challenge endpoint, which now also rejects revoked
    /// devices) triggers <see cref="SignedHttpClient.DeviceRevoked"/> internally
    /// → MainWindow's OnDeviceRevoked handler flips the red overlay. Network
    /// errors are still "transient" — the operator might just have flaky
    /// internet — so we swallow non-DeviceRevoked exceptions.
    ///
    /// On a successful heartbeat we also pick up <c>org_name</c> so the header
    /// can show the right hokimligi without needing a separate endpoint.</summary>
    private static async Task ProbeAuthAsync()
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return;
        try
        {
            using var resp = await SignedHttpClient.PostJsonAsync<object?>(
                creds.BackendUrl, "/api/kiosk/heartbeat", null);
            // TripIfAuthFailure inside SignedHttpClient already fired
            // DeviceRevoked on 401/403; success path falls through.
            if (resp.IsSuccessStatusCode)
            {
                try
                {
                    var hb = await resp.Content.ReadFromJsonAsync(
                        KioskJsonContext.Default.HeartbeatResponse);
                    if (hb is not null && !string.IsNullOrWhiteSpace(hb.OrgName))
                    {
                        // Weather text composed once here so the header
                        // doesn't have to do string formatting on every
                        // binding refresh. Sign convention: prefix "+"
                        // for non-negative; native minus for negatives.
                        var weatherText = "";
                        if (hb.Weather is { } w && !string.IsNullOrWhiteSpace(w.City))
                        {
                            var sign = w.TempC >= 0 ? "+" : "";
                            weatherText = $"{w.City} · {sign}{w.TempC}°";
                        }

                        var translationsSnapshot = hb.OrgNameTranslations;
                        var addressSnapshot = hb.AddressTranslations;
                        var workHoursSnapshot = hb.WorkHoursTranslations;
                        var emailSnapshot = hb.Email ?? "";
                        var helplineSnapshot = hb.HelplinePhone ?? "";
                        Dispatcher.UIThread.Post(() =>
                        {
                            SessionStore.Current.UpdateOrgBranding(
                                translationsSnapshot, hb.OrgName);
                            SessionStore.Current.WeatherText = weatherText;
                            SessionStore.Current.UpdateContactInfo(
                                addressSnapshot,
                                emailSnapshot,
                                workHoursSnapshot,
                                helplineSnapshot);
                        });

                        // Persist to DeviceCredentials so the NEXT cold start
                        // shows the org name immediately, before any network
                        // probe completes. Compare via dictionary equality so
                        // we only re-write when something actually changed
                        // (avoids churn on the encrypted credentials file).
                        var dictChanged =
                            !TranslationDictsEqual(creds.OrgNameTranslations, translationsSnapshot);
                        var addressChanged =
                            !TranslationDictsEqual(creds.OrgAddressTranslations, addressSnapshot);
                        var hoursChanged =
                            !TranslationDictsEqual(creds.OrgWorkHoursTranslations, workHoursSnapshot);
                        if (creds.OrgName != hb.OrgName
                            || creds.OrgSlug != hb.OrgSlug
                            || dictChanged
                            || addressChanged
                            || hoursChanged
                            || creds.OrgEmail != emailSnapshot
                            || creds.HelplinePhone != helplineSnapshot)
                        {
                            creds.OrgName = hb.OrgName;
                            creds.OrgSlug = hb.OrgSlug;
                            creds.OrgNameTranslations = translationsSnapshot
                                ?? new System.Collections.Generic.Dictionary<string, string>();
                            creds.OrgAddressTranslations = addressSnapshot
                                ?? new System.Collections.Generic.Dictionary<string, string>();
                            creds.OrgWorkHoursTranslations = workHoursSnapshot
                                ?? new System.Collections.Generic.Dictionary<string, string>();
                            creds.OrgEmail = emailSnapshot;
                            creds.HelplinePhone = helplineSnapshot;
                            try { DeviceKeyStore.Save(creds); }
                            catch { /* disk full or DPAPI failure — non-fatal */ }
                        }
                    }
                }
                catch { /* malformed body — UI stays on previous OrgName */ }
            }
        }
        catch (DeviceRevokedException)
        {
            // Already handled by SignedHttpClient — event fired, key store wiped.
        }
        catch
        {
            // Transient — backend down or network blip. The user's tap will retry.
        }
    }

    private void NavHome(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.Navigate(KioskPage.Home);

    private void NavQabul(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.Navigate(KioskPage.Qabul);

    private void NavSubmit(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.Navigate(KioskPage.Submit);

    private void NavContacts(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.Navigate(KioskPage.Contacts);
}
