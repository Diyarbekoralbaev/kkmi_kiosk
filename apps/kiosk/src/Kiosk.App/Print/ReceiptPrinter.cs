using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;

namespace Kiosk.App.Print;

/// <summary>
/// Cross-platform PDF print helper. Receipt is rendered as a thin 80mm
/// PDF on the backend and printed by the kiosk through the OS spooler.
///
/// Windows (the production target): the kiosk bundles SumatraPDF.exe
/// (portable, ~19 MB, in Assets/) and invokes it as
///     SumatraPDF.exe -print-to "<printer>" -silent <pdf>
/// SumatraPDF respects the printer name argument and prints headlessly.
/// We tried <c>Start-Process -Verb Print</c> first, but on machines where
/// Edge is the default PDF handler it ignores the printer argument and
/// dumps the job on the default printer (or fails silently with non-zero
/// exit when no handler is registered) — which is exactly what bit POS-80
/// kiosks. SumatraPDF doesn't depend on file associations at all.
///
/// Linux: <c>lp -d &lt;printer&gt; -o media=A6 &lt;file&gt;</c> via CUPS.
/// Used in dev only — kiosks ship Windows.
///
/// Returns true on a clean spool, false otherwise. Never throws.
/// </summary>
public static class ReceiptPrinter
{
    public static async Task<bool> PrintAsync(byte[] pdfBytes, string? printerName)
    {
        if (pdfBytes is null || pdfBytes.Length == 0) return false;

        var tmpPath = Path.Combine(Path.GetTempPath(), $"qabul-{Guid.NewGuid():N}.pdf");
        try
        {
            await File.WriteAllBytesAsync(tmpPath, pdfBytes).ConfigureAwait(false);

            if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
                return await PrintOnWindowsAsync(tmpPath, printerName).ConfigureAwait(false);
            if (RuntimeInformation.IsOSPlatform(OSPlatform.Linux))
                return await PrintOnLinuxAsync(tmpPath, printerName).ConfigureAwait(false);

            Console.Error.WriteLine($"[print] unsupported OS, dropped {pdfBytes.Length} bytes");
            return false;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[print] error: {ex.Message}");
            return false;
        }
        finally
        {
            // Defer cleanup so the spooler has time to read the file. Best-effort.
            _ = Task.Run(async () =>
            {
                await Task.Delay(TimeSpan.FromSeconds(20)).ConfigureAwait(false);
                try { File.Delete(tmpPath); } catch { }
            });
        }
    }

    private static async Task<bool> PrintOnWindowsAsync(string pdfPath, string? printerName)
    {
        var sumatraPath = Path.Combine(AppContext.BaseDirectory, "Assets", "SumatraPDF.exe");
        if (File.Exists(sumatraPath))
        {
            var psi = new ProcessStartInfo(sumatraPath)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            // SumatraPDF arg layout:
            //   -print-to "<printer>"   target specific printer
            //   -print-to-default       target the OS default printer
            //   -silent                 suppress UI / dialogs
            //   <pdf>                   file to print
            // -print-settings can override paper size / orientation if
            // ever needed; we leave defaults so the printer driver picks
            // its own media (POS-80 driver knows it's 80mm).
            if (!string.IsNullOrWhiteSpace(printerName))
            {
                psi.ArgumentList.Add("-print-to");
                psi.ArgumentList.Add(printerName);
            }
            else
            {
                psi.ArgumentList.Add("-print-to-default");
            }
            psi.ArgumentList.Add("-silent");
            psi.ArgumentList.Add(pdfPath);

            using var p = Process.Start(psi);
            if (p is null)
            {
                Console.Error.WriteLine("[print] SumatraPDF Process.Start returned null");
                return false;
            }
            // Bounded wait — SumatraPDF should hand off to the spooler in
            // well under a second. If it hangs (rare driver issue) we want
            // to give up rather than freeze the visitor's next interaction.
            using var cts = new System.Threading.CancellationTokenSource(TimeSpan.FromSeconds(15));
            try
            {
                await p.WaitForExitAsync(cts.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                Console.Error.WriteLine("[print] SumatraPDF timed out, killing");
                try { p.Kill(); } catch { }
                return false;
            }
            if (p.ExitCode != 0)
            {
                var err = await p.StandardError.ReadToEndAsync().ConfigureAwait(false);
                Console.Error.WriteLine($"[print] SumatraPDF exit={p.ExitCode} stderr={err}");
                return false;
            }
            return true;
        }

        // Fallback: SumatraPDF.exe missing (someone stripped Assets or
        // the binary is running outside the publish dir). Fall back to
        // the old Verb=Print approach so we degrade rather than crash.
        Console.Error.WriteLine($"[print] SumatraPDF not found at {sumatraPath}, falling back to Verb=Print");
        var script = string.IsNullOrWhiteSpace(printerName)
            ? $"Start-Process -FilePath '{pdfPath}' -Verb Print"
            : $"Start-Process -FilePath '{pdfPath}' -Verb Print -ArgumentList '\"{printerName}\"'";
        var fallback = new ProcessStartInfo("powershell")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        fallback.ArgumentList.Add("-NoProfile");
        fallback.ArgumentList.Add("-Command");
        fallback.ArgumentList.Add(script);
        using var pf = Process.Start(fallback);
        if (pf is null) return false;
        await pf.WaitForExitAsync().ConfigureAwait(false);
        return pf.ExitCode == 0;
    }

    private static async Task<bool> PrintOnLinuxAsync(string pdfPath, string? printerName)
    {
        var psi = new ProcessStartInfo("lp")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        if (!string.IsNullOrWhiteSpace(printerName))
        {
            psi.ArgumentList.Add("-d");
            psi.ArgumentList.Add(printerName);
        }
        // No -o media= so the driver chooses the right paper. 80mm thermal
        // CUPS drivers (zj-58 / pos-80 / brother-ql etc.) are pre-configured.
        psi.ArgumentList.Add(pdfPath);

        using var p = Process.Start(psi);
        if (p is null) return false;
        await p.WaitForExitAsync().ConfigureAwait(false);
        if (p.ExitCode != 0)
        {
            Console.Error.WriteLine(
                $"[print] lp failed exit={p.ExitCode} err={await p.StandardError.ReadToEndAsync()}");
            return false;
        }
        return true;
    }

    /// <summary>List system printers via OS tooling. Linux: <c>lpstat -e</c>.
    /// Windows: PowerShell <c>Get-Printer | Select-Object -ExpandProperty Name</c>.
    /// Returns an empty list on failure or unsupported OS.</summary>
    public static async Task<string[]> ListPrintersAsync()
    {
        try
        {
            ProcessStartInfo psi;
            if (RuntimeInformation.IsOSPlatform(OSPlatform.Linux))
            {
                psi = new ProcessStartInfo("lpstat")
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };
                psi.ArgumentList.Add("-e");
            }
            else if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            {
                psi = new ProcessStartInfo("powershell")
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };
                psi.ArgumentList.Add("-NoProfile");
                psi.ArgumentList.Add("-Command");
                psi.ArgumentList.Add("Get-Printer | Select-Object -ExpandProperty Name");
            }
            else
            {
                return Array.Empty<string>();
            }

            using var p = Process.Start(psi);
            if (p is null) return Array.Empty<string>();
            var stdout = await p.StandardOutput.ReadToEndAsync().ConfigureAwait(false);
            await p.WaitForExitAsync().ConfigureAwait(false);
            return stdout
                .Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        }
        catch
        {
            return Array.Empty<string>();
        }
    }
}
