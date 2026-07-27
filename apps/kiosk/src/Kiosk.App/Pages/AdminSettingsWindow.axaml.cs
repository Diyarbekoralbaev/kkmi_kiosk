using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Kiosk.App.Audio;
using Kiosk.App.Localization;
using Kiosk.App.Print;
using Kiosk.App.Settings;

namespace Kiosk.App.Pages;

public partial class AdminSettingsWindow : Window
{
    private readonly KioskSettings _draft;
    // Sentinel returned by ComboBox.SelectedItem when nothing is chosen.
    private const string AutoPickLabel = "(automatik)";

    public AdminSettingsWindow()
    {
        InitializeComponent();
        // Edit a copy so Cancel actually reverts. The live KioskSettings.Current
        // singleton is replaced atomically on Save.
        _draft = new KioskSettings
        {
            AudioInputDevice = KioskSettings.Current.AudioInputDevice,
            AudioOutputDevice = KioskSettings.Current.AudioOutputDevice,
            PrinterName = KioskSettings.Current.PrinterName,
            AutoPrintReceipts = KioskSettings.Current.AutoPrintReceipts,
            SpeakerVolume = KioskSettings.Current.SpeakerVolume,
            AdminPinHash = KioskSettings.Current.AdminPinHash,
        };
        Opened += async (_, _) => await PopulateAsync();
        VolumeSlider.ValueChanged += (_, _) =>
        {
            VolumeLabel.Text = $"{(int)(VolumeSlider.Value * 100)}%";
        };
    }

    private async Task PopulateAsync()
    {
        // Audio devices — enumerated under PortAudio init/terminate ref-count
        // so it's safe to call when the runtime is off (the usual case from
        // the long-press entry point). DisplayName embeds the host API
        // ("Mic [WASAPI]" vs "Mic [MME]") so duplicate hardware entries
        // disambiguate cleanly in the dropdown.
        var inputs = AudioDeviceList.EnumerateInputs();
        var outputs = AudioDeviceList.EnumerateOutputs();

        FillDeviceCombo(MicCombo, inputs.Select(i => i.DisplayName), _draft.AudioInputDevice);
        FillDeviceCombo(SpeakerCombo, outputs.Select(i => i.DisplayName), _draft.AudioOutputDevice);

        // Printers — OS spooler. Async so the UI doesn't lock during slow
        // CUPS lookups (lpstat can take >100 ms on first call).
        var printers = await ReceiptPrinter.ListPrintersAsync();
        FillDeviceCombo(PrinterCombo, printers, _draft.PrinterName);

        AutoPrintCheck.IsChecked = _draft.AutoPrintReceipts;
        VolumeSlider.Value = _draft.SpeakerVolume;
        VolumeLabel.Text = $"{(int)(_draft.SpeakerVolume * 100)}%";
        StatusText.IsVisible = false;
    }

    private static void FillDeviceCombo(ComboBox combo, IEnumerable<string> names, string? current)
    {
        var items = new List<string> { AutoPickLabel };
        items.AddRange(names);
        combo.ItemsSource = items;
        if (!string.IsNullOrEmpty(current) && items.Contains(current))
            combo.SelectedItem = current;
        else
            combo.SelectedIndex = 0;
    }

    /// <summary>Captures from the currently-selected mic for 3 s and reports
    /// the peak RMS back in the UI. The whole point is to let the operator
    /// VERIFY that a chosen device actually delivers audio — on Windows the
    /// same physical mic appears 3-4 times across host APIs and only some
    /// of those entries actually work depending on driver / exclusivity.
    ///
    /// We do NOT touch <see cref="KioskRuntime"/> — that owns the live
    /// runtime stream. We open a one-shot PortAudio capture, drain a few
    /// frames, and dispose. Safe to run with the voice runtime stopped
    /// (the usual case from the admin entry point).</summary>
    private async void OnTestMic(object? sender, RoutedEventArgs e)
    {
        var displayName = PickedOrNull(MicCombo);
        if (string.IsNullOrEmpty(displayName))
        {
            MicTestStatus.Foreground = Palette.Brush("KioskError");
            MicTestStatus.Text = LocalizationService.Get("MicTestNoDevice");
            return;
        }

        var deviceIdx = AudioDeviceList.FindIndexByDisplayName(displayName, input: true);
        if (deviceIdx < 0)
        {
            MicTestStatus.Foreground = Palette.Brush("KioskError");
            MicTestStatus.Text = LocalizationService.Get("MicTestErrorOpen");
            return;
        }

        TestMicButton.IsEnabled = false;
        MicTestStatus.Foreground = Palette.Brush("KioskPrimary");
        MicTestStatus.Text = LocalizationService.Get("MicTestSpeakNow");

        // Capture every step to crash.log so a "test shows 0%" report can be
        // diagnosed remotely without a screen share. The same log captures
        // exception InnerException — TypeInitializationException's outer
        // message is generic ("Type initializer threw"), the real reason
        // (DllNotFoundException, PaError, etc.) lives inside.
        var diagLines = new List<string>
        {
            $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] test mic: '{displayName}' idx={deviceIdx}",
        };
        var frameCount = 0;
        var maxRms = 0f;

        try
        {
            using var capture = new AudioCapture(deviceIndex: deviceIdx);
            capture.Start();
            diagLines.Add("  open: OK");

            var sw = Stopwatch.StartNew();
            var testDuration = TimeSpan.FromSeconds(3);
            var lastUiTick = TimeSpan.Zero;
            while (sw.Elapsed < testDuration)
            {
                while (capture.Frames.TryRead(out var pcm))
                {
                    frameCount++;
                    long sumSq = 0;
                    for (int i = 0; i < pcm.Length; i++) sumSq += pcm[i] * pcm[i];
                    var rms = MathF.Sqrt(sumSq / (float)pcm.Length) / 32768f;
                    if (rms > maxRms) maxRms = rms;
                }
                if (sw.Elapsed - lastUiTick > TimeSpan.FromMilliseconds(80))
                {
                    lastUiTick = sw.Elapsed;
                    var remaining = (int)(testDuration - sw.Elapsed).TotalSeconds + 1;
                    MicTestStatus.Text = $"{LocalizationService.Get("MicTestSpeakNow")}  ({remaining}s, peak {(int)(maxRms * 100)}%)";
                }
                await Task.Delay(20);
            }

            capture.Stop();
            diagLines.Add($"  frames={frameCount}   peakRms={maxRms:F4} ({(int)(maxRms * 100)}%)");

            // 1% peak RMS = roughly "speaking voice at a normal distance".
            // Below that the OS-level AEC + Gemini's server VAD are unlikely
            // to find anything either, so we call it a fail. The frames-but-
            // zero-peak case is the smoking gun for Windows mic privacy
            // being toggled OFF — stream opens, callback fires, samples are
            // all zero. Surface a specific hint for that.
            if (maxRms >= 0.01f)
            {
                MicTestStatus.Foreground = Palette.Brush("KioskSuccess");
                MicTestStatus.Text = $"{LocalizationService.Get("MicTestPass")}  (peak {(int)(maxRms * 100)}%)";
            }
            else
            {
                MicTestStatus.Foreground = Palette.Brush("KioskError");
                var hint = frameCount > 0
                    ? "  (frames received but all silent — check Windows Privacy → Microphone → Allow desktop apps)"
                    : "  (no frames — device may be busy)";
                MicTestStatus.Text = $"{LocalizationService.Get("MicTestSilent")}{hint}";
            }
        }
        catch (Exception ex)
        {
            // TypeInitializationException-style wrappers hide the real cause;
            // walk the InnerException chain and surface the deepest message.
            var realEx = ex;
            while (realEx.InnerException is not null) realEx = realEx.InnerException;
            diagLines.Add($"  open: FAIL   {ex.GetType().Name}: {realEx.Message}");
            diagLines.Add($"  stack: {ex}");
            MicTestStatus.Foreground = Palette.Brush("KioskError");
            MicTestStatus.Text = $"{LocalizationService.Get("MicTestErrorOpen")}: {realEx.Message}";
        }
        finally
        {
            TestMicButton.IsEnabled = true;
            try
            {
                var logDir = Path.GetDirectoryName(KioskSettings.SettingsPath) ?? ".";
                Directory.CreateDirectory(logDir);
                File.AppendAllText(Path.Combine(logDir, "crash.log"),
                    string.Join("\n", diagLines) + "\n\n");
            }
            catch { /* nowhere safer to write */ }
        }
    }

    private async void OnTestPrint(object? sender, RoutedEventArgs e)
    {
        var printer = PickedOrNull(PrinterCombo);
        StatusText.Text = "Test bosılmaqta...";
        StatusText.IsVisible = true;
        // Tiny one-page PDF so we don't need ReportLab here. Plain text via
        // PostScript-like header — most CUPS printers accept text/plain too,
        // but PDF is safer.
        var bytes = MinimalTestPdf("KIOSK TEST PRINT — " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
        var ok = await ReceiptPrinter.PrintAsync(bytes, printer);
        StatusText.Text = ok ? "Test jiberildi (printerge qarań)." : "Test jiberilmedi (printer joq yamasa qatelik).";
    }

    /// <summary>Generates a minimal valid 1-page PDF sized for 80mm thermal
    /// receipt printers (POS-80 class). MediaBox = 80mm × 50mm in points
    /// (227 × 142 ≈ 80mm × 50mm). One short line of text at the top so the
    /// operator visually confirms the printer is awake. The xref offsets
    /// don't have to be byte-accurate; SumatraPDF tolerates a slightly off
    /// /startxref so long as the stream is valid — but we still build a
    /// real xref for correctness with stricter readers.</summary>
    private static byte[] MinimalTestPdf(string text)
    {
        var sanitized = text.Replace("(", "[").Replace(")", "]");
        // 80mm = 226.77pt, 50mm = 141.73pt. Round to 227 × 142 — close enough
        // for an 80mm thermal driver. Text positioned 14pt from left,
        // ~125pt from bottom (≈ 6mm from top of a 50mm page).
        var content = $"BT /F1 11 Tf 14 125 Td (KIOSK TEST PRINT) Tj 0 -16 Td ({sanitized}) Tj ET";
        var contentLen = content.Length;
        var pdf =
            "%PDF-1.4\n" +
            "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n" +
            "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n" +
            "3 0 obj << /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> " +
            "/MediaBox [0 0 227 142] /Contents 5 0 R >> endobj\n" +
            "4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n" +
            $"5 0 obj << /Length {contentLen} >> stream\n{content}\nendstream endobj\n" +
            "xref\n0 6\n0000000000 65535 f \n0000000010 00000 n \n0000000060 00000 n \n0000000111 00000 n \n0000000212 00000 n \n0000000275 00000 n \n" +
            "trailer << /Size 6 /Root 1 0 R >>\nstartxref\n400\n%%EOF\n";
        return System.Text.Encoding.ASCII.GetBytes(pdf);
    }

    private static string? PickedOrNull(ComboBox combo)
    {
        var s = combo.SelectedItem as string;
        if (string.IsNullOrEmpty(s) || s == AutoPickLabel) return null;
        return s;
    }

    private void OnSave(object? sender, RoutedEventArgs e)
    {
        _draft.AudioInputDevice = PickedOrNull(MicCombo);
        _draft.AudioOutputDevice = PickedOrNull(SpeakerCombo);
        _draft.PrinterName = PickedOrNull(PrinterCombo);
        _draft.AutoPrintReceipts = AutoPrintCheck.IsChecked == true;
        _draft.SpeakerVolume = (float)VolumeSlider.Value;
        _draft.Save();
        Close();
    }

    private void OnCancel(object? sender, RoutedEventArgs e) => Close();

    private void OnExit(object? sender, RoutedEventArgs e)
    {
        // Close this window, then shut down the whole app cleanly. The
        // five-tap admin path also offers Exit; this Quit button is here as
        // a redundant escape hatch for operators already in Settings.
        Close();
        if (Avalonia.Application.Current?.ApplicationLifetime is
            Avalonia.Controls.ApplicationLifetimes.IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.Shutdown(0);
        }
    }
}
