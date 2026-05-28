using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Kiosk.App.Net;

namespace Kiosk.App.Identity;

/// <summary>
/// Public-key auth metadata stored on the kiosk after enrollment.
///
/// What's here: backend URL + assigned device_id. **No private key** — that
/// lives in the TPM (or, on Linux dev, on disk via SoftCryptoProvider).
/// Even if an attacker reads this file in plaintext, they get nothing they
/// can authenticate with, because authentication requires signing per-request
/// nonces with the TPM-bound private key.
///
/// File location:
///   - Windows: DPAPI-encrypted (CurrentUser scope) at %APPDATA%\KioskGov\credentials.dat.
///   - Linux (dev only): plain JSON at $XDG_DATA_HOME/joqari-kenes/credentials.json (0600).
/// </summary>
public sealed class DeviceCredentials
{
    [JsonPropertyName("backend_url")] public string BackendUrl { get; set; } = "";
    [JsonPropertyName("device_id")] public string DeviceId { get; set; } = "";

    // Org branding info — written here once the kiosk receives org_name
    // from the heartbeat response. Persisting it avoids the visible "no
    // org name" gap on subsequent cold starts (heartbeat is once-on-open
    // and can take a beat). The super-panel renaming the org propagates
    // on the next heartbeat that lands with a different value.
    [JsonPropertyName("org_name")] public string OrgName { get; set; } = "";
    [JsonPropertyName("org_slug")] public string OrgSlug { get; set; } = "";
    /// <summary>Localized variants. Persisted so the kiosk header renders in
    /// the right language across cold starts before the first heartbeat lands.
    /// Empty dict in older stores; consumer falls back to OrgName.</summary>
    [JsonPropertyName("org_name_translations")]
    public Dictionary<string, string> OrgNameTranslations { get; set; } = new();

    /// <summary>Contacts page data — persisted so the ContactsPage shows real
    /// values on the very first frame after a cold start. Refreshed on every
    /// heartbeat (≈30 s) so super-panel edits propagate without restart.
    /// Older stores have empty dicts; the kiosk renders empty rows rather
    /// than crashing.</summary>
    [JsonPropertyName("org_address_translations")]
    public Dictionary<string, string> OrgAddressTranslations { get; set; } = new();

    [JsonPropertyName("org_email")] public string OrgEmail { get; set; } = "";

    [JsonPropertyName("org_work_hours_translations")]
    public Dictionary<string, string> OrgWorkHoursTranslations { get; set; } = new();

    /// <summary>Front-desk phone shown on the Contacts page AND the footer band.
    /// Driven by heartbeat; persisted alongside the org name.</summary>
    [JsonPropertyName("helpline_phone")] public string HelplinePhone { get; set; } = "";
}

public static class DeviceKeyStore
{
    public static string StorePath { get; } = ResolvePath();

    private static string ResolvePath()
    {
        if (OperatingSystem.IsWindows())
        {
            var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            return Path.Combine(appData, "KioskGov", "credentials.dat");
        }
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return Path.Combine(local, "joqari-kenes", "credentials.json");
    }

    public static bool HasKey() => File.Exists(StorePath);

    public static DeviceCredentials? Load()
    {
        if (!File.Exists(StorePath)) return null;
        try
        {
            var bytes = File.ReadAllBytes(StorePath);
            var json = OperatingSystem.IsWindows()
                ? Encoding.UTF8.GetString(
                    ProtectedData.Unprotect(bytes, optionalEntropy: null, scope: DataProtectionScope.CurrentUser))
                : Encoding.UTF8.GetString(bytes);
            return JsonSerializer.Deserialize(json, KioskJsonContext.Default.DeviceCredentials);
        }
        catch
        {
            // Corrupted store / wrong DPAPI scope. Force re-enrollment.
            return null;
        }
    }

    public static void Save(DeviceCredentials creds)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(StorePath)!);
        var json = JsonSerializer.Serialize(creds, KioskJsonContext.Default.DeviceCredentials);
        var bytes = Encoding.UTF8.GetBytes(json);
        if (OperatingSystem.IsWindows())
        {
            var encrypted = ProtectedData.Protect(bytes, optionalEntropy: null, scope: DataProtectionScope.CurrentUser);
            File.WriteAllBytes(StorePath, encrypted);
        }
        else
        {
            File.WriteAllBytes(StorePath, bytes);
            File.SetUnixFileMode(StorePath, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        }
    }

    /// <summary>Wipes BOTH the on-disk credentials and the TPM keypair.
    /// Called on revocation: server-side the device is dead, and we
    /// destroy the matching private key so nothing can ever sign with
    /// it again — even before a re-enrollment.</summary>
    public static void Clear()
    {
        if (File.Exists(StorePath)) File.Delete(StorePath);
        try { CryptoProviderFactory.Current.DeleteKey(); }
        catch (Exception ex) { Console.Error.WriteLine($"[security] DeleteKey failed: {ex.Message}"); }
    }
}
