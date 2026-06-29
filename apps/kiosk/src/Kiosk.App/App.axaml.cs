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
            // Keep the kiosk alive through the Intel UHD OpenGL FBO bug. On this
            // GPU/driver Avalonia intermittently throws OpenGlException ("Unable
            // to configure OpenGL FBO ... GL_NO_ERROR") from the render commit
            // when the 3D robot page is shown. Left unhandled it bubbles up as a
            // terminal AppDomain exception and the whole app exits. Catching it
            // here at the dispatcher (e.Handled = true) lets the render loop
            // carry on — the robot may drop a frame but voice + UI keep working.
            // 3D is kept (no ANGLE, no 2D) per the operator's requirement.
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
