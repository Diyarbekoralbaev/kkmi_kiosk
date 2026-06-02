using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Avalonia;
using Kiosk.App.Audio;
using Kiosk.App.Identity;
using Kiosk.App.Net;
using Kiosk.App.Update;

namespace Kiosk.App;

class Program
{
    /// <summary>
    /// Entry point. Modes:
    ///   - `--enroll &lt;backend-url&gt; &lt;enrollment-code&gt;` runs headless enrollment.
    ///     Used by deployers to pre-provision a kiosk via SSH/RDP without using the on-screen
    ///     keyboard. Exit 0 on success, non-zero with stderr on failure.
    ///   - `--ws-test [seconds]` connects with stored creds, prints counts of inbound
    ///     events, exits 0 if at least connected. For slice-4 smoke tests.
    ///   - no args (or any other) launches the GUI. The App chooses MainWindow vs
    ///     EnrollmentWindow based on whether DeviceKeyStore.HasKey().
    /// </summary>
    [STAThread]
    public static int Main(string[] args)
    {
        // Crash logging FIRST. AppDomain.UnhandledException catches anything
        // the app doesn't handle, but Avalonia's startup path tends to die
        // before reaching the dispatcher (XAML compile/AOT trim mismatches
        // surface in OnFrameworkInitializationCompleted), so we ALSO wrap
        // Main in try/catch. Logs go next to settings.json so the operator
        // can find them without spelunking through %TEMP%.
        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
            WriteCrashLog("unhandled", e.ExceptionObject as Exception);
        TaskScheduler.UnobservedTaskException += (_, e) =>
            WriteCrashLog("unobserved-task", e.Exception);

        try
        {
            // Velopack hooks (--squirrel-install, --squirrel-firstrun, etc.) must run
            // before any UI is created.
            Updater.Bootstrap();

            // Make the security posture obvious in dev — production is silent.
            if (!Net.PinnedHttpClient.HasPin)
            {
                Console.Error.WriteLine(
                    "[security] no cert pin baked — DEV mode. " +
                    "Production builds inject KIOSK_CERT_PIN_SHA256 via publish.win.sh.");
            }

            // Update gate runs from MainWindow.OnOpened so we can show a
            // full-screen overlay during apply. Old fire-and-forget call is gone.

            if (args.Length >= 1 && args[0] == "--enroll")
                return RunHeadlessEnroll(args).GetAwaiter().GetResult();
            if (args.Length >= 1 && args[0] == "--ws-test")
                return RunWsTest(args).GetAwaiter().GetResult();
            if (args.Length >= 1 && args[0] == "--audio-test")
                return RunAudioTest(args).GetAwaiter().GetResult();
            if (args.Length >= 1 && args[0] == "--audio-devices")
                return RunAudioDevices();
            if (args.Length >= 1 && args[0] == "--test-i18n")
                return RunI18nTest();
            if (args.Length >= 1 && args[0] == "--mic-diag")
                return RunMicDiag();

            BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
            return 0;
        }
        catch (Exception ex)
        {
            WriteCrashLog("main", ex);
            return 1;
        }
    }

    /// <summary>Append-only crash log next to the kiosk's settings.json.
    /// On Windows: %APPDATA%\Kiosk\crash.log. On Linux: ~/.config/kiosk/crash.log.
    /// Safe to call from any thread; failures are swallowed because there's
    /// nowhere safer to write to if even the log path is broken.</summary>
    private static void WriteCrashLog(string tag, Exception? ex)
    {
        try
        {
            var path = Path.Combine(
                Path.GetDirectoryName(Kiosk.App.Settings.KioskSettings.SettingsPath) ?? ".",
                "crash.log");
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var entry = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] [{tag}] {ex}\n\n";
            File.AppendAllText(path, entry);
            Console.Error.WriteLine(entry);
        }
        catch { /* nothing to do — disk full / readonly / whatever */ }
    }

    private static async Task<int> RunHeadlessEnroll(string[] args)
    {
        if (args.Length < 3)
        {
            Console.Error.WriteLine("usage: --enroll <backend-url> <enrollment-code>");
            return 2;
        }
        var result = await EnrollmentService.EnrollAsync(args[1], args[2]);
        if (!result.Success)
        {
            Console.Error.WriteLine($"enrollment failed: {result.Error}");
            return 1;
        }
        Console.WriteLine($"enrolled: device_id={result.Credentials!.DeviceId}");
        Console.WriteLine($"stored at {DeviceKeyStore.StorePath}");
        return 0;
    }

    private static async Task<int> RunWsTest(string[] args)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null)
        {
            Console.Error.WriteLine("no stored credentials — run --enroll first");
            return 2;
        }
        var seconds = args.Length >= 2 && int.TryParse(args[1], out var s) ? s : 10;

        await using var client = new KioskClient(creds.BackendUrl, creds.DeviceId);
        var audioFrames = 0;
        var audioBytes = 0L;
        var transcripts = 0;
        var lastState = ConnectionState.Disconnected;
        client.StateChanged += s2 =>
        {
            lastState = s2;
            Console.WriteLine($"[{DateTime.Now:HH:mm:ss}] state={s2}");
        };
        client.AudioReceived += pcm => { Interlocked.Increment(ref audioFrames); Interlocked.Add(ref audioBytes, pcm.Length); };
        client.TranscriptReceived += t => { Interlocked.Increment(ref transcripts); Console.WriteLine($"[transcript {t.Speaker} final={t.Final}] {t.Text}"); };
        client.NavigateReceived += n => Console.WriteLine($"[navigate] {n.Screen}");
        client.PreviewReceived += p => Console.WriteLine($"[preview] {p.Topic}");
        client.SubmittedReceived += sub => Console.WriteLine($"[submitted] {sub.Id}");
        client.AudioDoneReceived += () => Console.WriteLine($"[audio_done]");
        client.ErrorReceived += e => Console.WriteLine($"[error] {e.Code} {e.Message}");

        client.Start();
        await Task.Delay(TimeSpan.FromSeconds(seconds));
        Console.WriteLine($"summary: state={lastState} audio_frames={audioFrames} audio_bytes={audioBytes} transcripts={transcripts}");
        return lastState == ConnectionState.Connected ? 0 : 1;
    }

    private static async Task<int> RunAudioTest(string[] args)
    {
        var seconds = args.Length >= 2 && int.TryParse(args[1], out var s) ? s : 8;

        using var capture = new AudioCapture();

        // RMS-only speech detection (the same hysteresis the runtime uses
        // for MicOrb). Lets the operator confirm the mic actually captures
        // voice without dragging ONNX runtime into the diagnostic build.
        const float onsetRms = 0.025f;
        const float releaseRms = 0.015f;
        var totalFrames = 0;
        var speechFrames = 0;
        var speaking = false;
        var quietCount = 0;

        var consumer = Task.Run(async () =>
        {
            await foreach (var pcm in capture.Frames.ReadAllAsync())
            {
                if (pcm.Length != AudioCapture.FramesPerBuffer) continue;
                Interlocked.Increment(ref totalFrames);

                long sumSq = 0;
                for (int i = 0; i < pcm.Length; i++) sumSq += pcm[i] * pcm[i];
                var rms = MathF.Sqrt(sumSq / (float)pcm.Length) / 32768f;

                if (!speaking && rms >= onsetRms) { speaking = true; quietCount = 0; }
                else if (speaking)
                {
                    if (rms < releaseRms) { if (++quietCount >= 5) speaking = false; }
                    else quietCount = 0;
                }
                if (speaking) Interlocked.Increment(ref speechFrames);

                if (totalFrames % 16 == 0) // every ~0.5 s
                {
                    Console.WriteLine($"[t={totalFrames * 32}ms] rms={rms:F4} speaking={speaking}");
                }
            }
        });

        capture.Start();
        Console.WriteLine($"speak now — capturing {seconds}s...");
        await Task.Delay(TimeSpan.FromSeconds(seconds));
        capture.Stop();
        await Task.Delay(200); // let the channel drain

        var pct = totalFrames == 0 ? 0 : 100 * speechFrames / totalFrames;
        Console.WriteLine($"summary: total_frames={totalFrames} speech_frames={speechFrames} ({pct}%)");
        return totalFrames > 0 ? 0 : 1;
    }

    /// <summary>Headless verifier for the i18n resource swap. Loads App.axaml
    /// (so MergedDictionaries are populated), then exercises
    /// LocalizationService.SetLanguage and prints what each dict resolves
    /// "HomeGreeting" to. CI/dev can run this without a display to confirm
    /// that the language toggle works end-to-end before pushing to 17 kiosks.</summary>
    private static int RunI18nTest()
    {
        var builder = AppBuilder.Configure<App>().UsePlatformDetect();
        builder.SetupWithoutStarting();

        var app = Avalonia.Application.Current!;
        Console.WriteLine($"MergedDictionaries.Count = {app.Resources.MergedDictionaries.Count}");
        for (int i = 0; i < app.Resources.MergedDictionaries.Count; i++)
        {
            var d = app.Resources.MergedDictionaries[i];
            Console.WriteLine($"  [{i}] type={d.GetType().FullName}");
        }

        var langs = new[] { Localization.Language.Uz, Localization.Language.Ru, Localization.Language.Kk };
        var fail = 0;
        foreach (var lang in langs)
        {
            Localization.LocalizationService.SetLanguage(lang);
            // Use HomeQuestion — present in all 3 dicts post-redesign and
            // contains a language-distinctive token (помочь/yordam/жәрдем)
            // that makes the per-language assertion robust to refresh.
            var question = Localization.LocalizationService.Get("HomeQuestion");
            var expected = lang switch
            {
                Localization.Language.Ru => "помочь",
                Localization.Language.Kk => "жәрдем",
                _ => "yordam",
            };
            var ok = question.Contains(expected);
            Console.WriteLine($"SetLanguage({lang}) → HomeQuestion='{question}' expect~='{expected}' → {(ok ? "PASS" : "FAIL")}");
            if (!ok) fail++;
        }
        return fail == 0 ? 0 : 1;
    }

    /// <summary>Operator-facing mic diagnostic. Iterates every input device,
    /// tries to open it at 16 kHz mono Int16 (the kiosk's canonical format),
    /// captures ~1 s, computes peak RMS, prints everything. Saves the same
    /// output to crash.log so the operator can email it back to the
    /// developer without copy-pasting cmd window contents.
    ///
    /// Usage on Windows:
    ///   cd "%LOCALAPPDATA%\Kiosk\current"
    ///   Kiosk.App.exe --mic-diag</summary>
    private static int RunMicDiag()
    {
        var lines = new System.Collections.Generic.List<string>();
        void Log(string s) { Console.WriteLine(s); lines.Add(s); }

        Log($"=== mic-diag {DateTime.Now:yyyy-MM-dd HH:mm:ss} ===");
        Log($"OS: {Environment.OSVersion}");

        var inputs = Kiosk.App.Audio.AudioDeviceList.EnumerateInputs();
        Log($"input devices (loopback filtered): {inputs.Count}");
        foreach (var d in inputs)
            Log($"  [{d.Index}] {d.DisplayName}");

        foreach (var d in inputs)
        {
            Log("");
            Log($"--- testing [{d.Index}] {d.DisplayName} ---");
            try
            {
                using var capture = new Kiosk.App.Audio.AudioCapture(deviceIndex: d.Index);
                capture.Start();
                var sw = System.Diagnostics.Stopwatch.StartNew();
                var frameCount = 0;
                var maxRms = 0f;
                while (sw.Elapsed < TimeSpan.FromSeconds(1))
                {
                    while (capture.Frames.TryRead(out var pcm))
                    {
                        frameCount++;
                        long sumSq = 0;
                        for (int i = 0; i < pcm.Length; i++) sumSq += pcm[i] * pcm[i];
                        var rms = MathF.Sqrt(sumSq / (float)pcm.Length) / 32768f;
                        if (rms > maxRms) maxRms = rms;
                    }
                    Thread.Sleep(20);
                }
                capture.Stop();
                Log($"  open: OK   frames={frameCount}   peakRms={maxRms:F4} ({(int)(maxRms * 100)}%)");
            }
            catch (Exception ex)
            {
                var inner = ex.InnerException?.Message ?? ex.Message;
                Log($"  open: FAIL   {ex.GetType().Name}: {inner}");
            }
        }

        // Drop the report next to settings.json + crash.log so the operator
        // finds it without cmd-window scrollback hunting.
        try
        {
            var path = System.IO.Path.Combine(
                System.IO.Path.GetDirectoryName(Kiosk.App.Settings.KioskSettings.SettingsPath) ?? ".",
                "mic-diag.log");
            System.IO.File.WriteAllText(path, string.Join("\n", lines) + "\n");
            Console.WriteLine($"\nfull report: {path}");
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"could not write report: {ex.Message}");
        }
        return 0;
    }

    private static int RunAudioDevices()
    {
        Console.WriteLine("=== inputs ===");
        foreach (var d in Kiosk.App.Audio.AudioDeviceList.EnumerateInputs())
            Console.WriteLine($"  [{d.Index}] {d.DisplayName}");
        Console.WriteLine("=== outputs ===");
        foreach (var d in Kiosk.App.Audio.AudioDeviceList.EnumerateOutputs())
            Console.WriteLine($"  [{d.Index}] {d.DisplayName}");
        return 0;
    }

    public static AppBuilder BuildAvaloniaApp()
        => AppBuilder.Configure<App>()
            .UsePlatformDetect()
            // Force WGL (desktop OpenGL) as the preferred Win32 renderer.
            // Default order is [AngleEgl, Software], but ANGLE silently
            // refuses our `#version 330 core` shader (it's an OpenGL ES 3.0
            // backend that expects `#version 300 es`); the RobotControl
            // surface then renders nothing and we see the parent Border's
            // white background. WGL gives us a real desktop GL 3.3+ context
            // so the existing PbrShader compiles. Software stays as a last
            // resort so the rest of the UI still draws on hardware with no
            // GL support at all. See Avalonia#18713 + discussion#15055.
            .With(new Avalonia.Win32PlatformOptions
            {
                RenderingMode = new[]
                {
                    Avalonia.Win32RenderingMode.Wgl,
                    Avalonia.Win32RenderingMode.AngleEgl,
                    Avalonia.Win32RenderingMode.Software,
                },
            })
#if DEBUG
            .WithDeveloperTools()
#endif
            .WithInterFont()
            .LogToTrace();
}
