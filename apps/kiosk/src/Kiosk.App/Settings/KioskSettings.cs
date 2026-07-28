using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.Json.Serialization;
using Kiosk.App.Net;

namespace Kiosk.App.Settings;

/// <summary>
/// Local kiosk preferences (audio devices, printer, volume). Persisted as
/// JSON in:
///   <c>~/.config/kiosk/settings.json</c> on Linux,
///   <c>%APPDATA%\Kiosk\settings.json</c> on Windows.
///
/// Loaded once at app startup; mutated only from the AdminSettingsPage and
/// saved back on every change. Other components should read via
/// <see cref="Current"/>; do not subscribe — settings rarely change at runtime
/// and the small set of consumers polls on use.
/// </summary>
public sealed class KioskSettings
{
    [JsonPropertyName("audio_input_device")] public string? AudioInputDevice { get; set; }
    [JsonPropertyName("audio_output_device")] public string? AudioOutputDevice { get; set; }
    [JsonPropertyName("printer_name")] public string? PrinterName { get; set; }
    [JsonPropertyName("auto_print_receipts")] public bool AutoPrintReceipts { get; set; } = true;
    [JsonPropertyName("speaker_volume")] public float SpeakerVolume { get; set; } = 0.85f;
    [JsonPropertyName("admin_pin_hash")] public string AdminPinHash { get; set; } = ""; // empty = default PIN "0205"
    [JsonPropertyName("preferred_language")] public string PreferredLanguage { get; set; } = "kk";

    public static KioskSettings Current { get; private set; } = Load();

    public static string SettingsPath
    {
        get
        {
            string baseDir;
            if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            {
                baseDir = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                return Path.Combine(baseDir, "Kiosk", "settings.json");
            }
            else
            {
                baseDir = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                return Path.Combine(baseDir, ".config", "kiosk", "settings.json");
            }
        }
    }

    public static KioskSettings Load()
    {
        try
        {
            var path = SettingsPath;
            if (!File.Exists(path)) return new KioskSettings();
            var json = File.ReadAllText(path);
            return JsonSerializer.Deserialize(json, KioskJsonContext.Default.KioskSettings) ?? new KioskSettings();
        }
        catch
        {
            return new KioskSettings();
        }
    }

    public void Save()
    {
        try
        {
            var path = SettingsPath;
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var json = JsonSerializer.Serialize(this, KioskJsonContext.Default.KioskSettings);
            File.WriteAllText(path, json);
            Current = this;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[settings] save failed: {ex.Message}");
        }
    }
}
