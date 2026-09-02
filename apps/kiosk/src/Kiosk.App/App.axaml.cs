using System;
using System.IO;
using System.Threading;
using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Threading;
using Kiosk.App.Identity;
using Kiosk.App.Localization;
using Kiosk.App.Settings;

namespace Kiosk.App;

public partial class App : Application
{
    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            // A UI-thread exception must never take the kiosk down in front of
            // a visitor: unhandled, it becomes a terminal AppDomain fault and
            // the app exits. Handling it here lets the render loop drop a frame
            // and carry on, and the throttled log still reaches us via the
            // crash-log upload on next start.
            //
            // This was written for the Intel OpenGL FBO exception the 3D robot
            // page raised. That page now draws a still image, so the specific
            // fault is gone — but the guard stays: a kiosk with no keyboard,
            // reached only over a remote desktop, should not be one exception
            // away from a black screen.
            Dispatcher.UIThread.UnhandledException += OnUiThreadException;

            // Load the saved UI language BEFORE building MainWindow so every
            // {DynamicResource} in XAML resolves correctly on first render.
            LocalizationService.SetLanguage(
                LocalizationService.Parse(KioskSettings.Current.PreferredLanguage));

            // First-run enrollment vs normal kiosk launch. The store check is fast
            // (file exists?) and never triggers a DPAPI decrypt failure path here —
            // failure to decrypt later just routes back to enrollment.
            desktop.MainWindow = DeviceKeyStore.HasKey()
                ? new MainWindow()
                : new EnrollmentWindow();
        }

        base.OnFrameworkInitializationCompleted();
    }

    private static int _glErrorCount;

    private static void OnUiThreadException(
        object? sender, DispatcherUnhandledExceptionEventArgs e)
    {
        // Kiosk resilience: an unhandled exception on the UI thread must NEVER
        // hard-quit the kiosk in front of a citizen. Swallow it (the render loop
        // drops a frame and carries on), and log it — throttled — so a persistent
        // fault can't spin crash.log at frame rate. This covers the known Intel
        // UHD OpenGL FBO crash AND any transient navigation/render glitch.
        // Non-UI-thread faults still reach the AppDomain handler (crash.log), and
        // the crash log is uploaded to the backend on next start for diagnosis.
        e.Handled = true;
        var n = Interlocked.Increment(ref _glErrorCount);
        var kind = e.Exception.GetType().Name;
        if (n <= 10)
            LogLine($"swallowed UI exception #{n} [{kind}]: {e.Exception.Message}");
        else if (n % 600 == 0)
            LogLine($"UI exceptions x{n} (throttled), last [{kind}]: {e.Exception.Message}");
    }

    private static void LogLine(string msg)
    {
        try
        {
            var dir = Path.GetDirectoryName(KioskSettings.SettingsPath) ?? ".";
            Directory.CreateDirectory(dir);
            File.AppendAllText(
                Path.Combine(dir, "crash.log"),
                $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] [gl-guard] {msg}\n");
        }
        catch { /* logging must never crash the render path */ }
    }
}
