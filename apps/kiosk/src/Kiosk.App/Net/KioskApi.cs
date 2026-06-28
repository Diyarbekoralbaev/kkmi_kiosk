using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using Kiosk.App.Identity;

namespace Kiosk.App.Net;

// ── Appeal (murajat) — the backend forwards it to cabinet.murajat.uz ──
public sealed record AppealRequest
{
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
    [JsonPropertyName("text")] public string Text { get; init; } = "";
    [JsonPropertyName("confirmed")] public bool Confirmed { get; init; }
    // Personal fields — sent only for a new / «men emas» citizen
    // (confirmed=false). null fields are omitted (WhenWritingNull in the
    // JSON context) so a confirmed citizen's request stays phone+text only.
    [JsonPropertyName("first_name")] public string? FirstName { get; init; }
    [JsonPropertyName("last_name")] public string? LastName { get; init; }
    [JsonPropertyName("birth_date")] public string? BirthDate { get; init; }
    [JsonPropertyName("gender")] public int? Gender { get; init; }
    [JsonPropertyName("district_id")] public int? DistrictId { get; init; }
    [JsonPropertyName("quarter_id")] public int? QuarterId { get; init; }
    [JsonPropertyName("address")] public string? Address { get; init; }
}

public sealed record AppealResponse
{
    [JsonPropertyName("appeal_number")] public string AppealNumber { get; init; } = "";
    [JsonPropertyName("status")] public string Status { get; init; } = "";
}

// ── Citizen lookup by phone (cabinet shape, proxied verbatim) ──
public sealed record PersonalDto
{
    [JsonPropertyName("id")] public long Id { get; init; }
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
    [JsonPropertyName("first_name")] public string FirstName { get; init; } = "";
    [JsonPropertyName("last_name")] public string LastName { get; init; } = "";
    [JsonPropertyName("full_name")] public string FullName { get; init; } = "";
    [JsonPropertyName("birth_date")] public string BirthDate { get; init; } = "";
    // Cabinet returns these as strings ("1"), not ints.
    [JsonPropertyName("gender")] public string Gender { get; init; } = "";
    [JsonPropertyName("district_id")] public string DistrictId { get; init; } = "";
    [JsonPropertyName("quarter_id")] public string QuarterId { get; init; } = "";
    [JsonPropertyName("address")] public string Address { get; init; } = "";
}

public sealed record PersonalLookupResponse
{
    [JsonPropertyName("exists")] public bool Exists { get; init; }
    [JsonPropertyName("personal")] public PersonalDto? Personal { get; init; }
}

// ── Districts + quarters reference (kiosk caches in-memory for the form) ──
public sealed record DistrictDto
{
    [JsonPropertyName("id")] public int Id { get; init; }
    [JsonPropertyName("name_uz")] public string NameUz { get; init; } = "";
    [JsonPropertyName("name_oz")] public string NameOz { get; init; } = "";
    [JsonPropertyName("name_ru")] public string NameRu { get; init; } = "";
    [JsonPropertyName("name_qq")] public string NameQq { get; init; } = "";
}

public sealed record QuarterDto
{
    [JsonPropertyName("id")] public int Id { get; init; }
    [JsonPropertyName("district_id")] public int DistrictId { get; init; }
    [JsonPropertyName("name_uz")] public string NameUz { get; init; } = "";
    [JsonPropertyName("name_oz")] public string NameOz { get; init; } = "";
    [JsonPropertyName("name_ru")] public string NameRu { get; init; } = "";
    [JsonPropertyName("name_qq")] public string NameQq { get; init; } = "";
}

public sealed record LocationsResponse
{
    [JsonPropertyName("districts")] public List<DistrictDto> Districts { get; init; } = new();
    [JsonPropertyName("quarters")] public List<QuarterDto> Quarters { get; init; } = new();
}

/// <summary>
/// HTTP client for the kiosk's manual murajat flow. The backend proxies every
/// call to the external Council cabinet (cabinet.murajat.uz); nothing is stored
/// in our DB. Each request is signed with the device's TPM-bound key via
/// <see cref="SignedHttpClient"/>.
/// </summary>
public static class KioskApi
{
    /// <summary>POST /api/kiosk/appeal — submit the appeal. For a confirmed
    /// existing citizen pass phone + text + Confirmed=true; for a new citizen
    /// pass Confirmed=false plus all personal fields. Returns null on failure;
    /// backend logs the real error.</summary>
    public static async Task<AppealResponse?> SubmitAppealAsync(AppealRequest req)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            var resp = await SignedHttpClient.PostJsonAsync(
                creds.BackendUrl, "/api/kiosk/appeal",
                req, KioskJsonContext.Default.AppealRequest);
            if (!resp.IsSuccessStatusCode)
            {
                Console.Error.WriteLine($"[api] SubmitAppealAsync HTTP {(int)resp.StatusCode}");
                return null;
            }
            return await resp.Content.ReadFromJsonAsync(KioskJsonContext.Default.AppealResponse);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] SubmitAppealAsync: {ex.Message}");
            return null;
        }
    }

    /// <summary>GET /api/kiosk/personal?phone= — look up a citizen so the form
    /// can ask «Siz {name} misiz?». Returns null on failure (treat as not
    /// found and collect full details).</summary>
    public static async Task<PersonalLookupResponse?> LookupPersonalAsync(string phone)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            var resp = await SignedHttpClient.GetAsync(
                creds.BackendUrl, $"/api/kiosk/personal?phone={Uri.EscapeDataString(phone)}");
            if (!resp.IsSuccessStatusCode)
            {
                Console.Error.WriteLine($"[api] LookupPersonalAsync HTTP {(int)resp.StatusCode}");
                return null;
            }
            return await resp.Content.ReadFromJsonAsync(KioskJsonContext.Default.PersonalLookupResponse);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] LookupPersonalAsync: {ex.Message}");
            return null;
        }
    }

    /// <summary>GET /api/kiosk/locations — districts + quarters for the form's
    /// dropdowns. Fetched once on open and cached in memory. Returns null on
    /// failure.</summary>
    public static async Task<LocationsResponse?> GetLocationsAsync()
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            var resp = await SignedHttpClient.GetAsync(creds.BackendUrl, "/api/kiosk/locations");
            if (!resp.IsSuccessStatusCode)
            {
                Console.Error.WriteLine($"[api] GetLocationsAsync HTTP {(int)resp.StatusCode}");
                return null;
            }
            return await resp.Content.ReadFromJsonAsync(KioskJsonContext.Default.LocationsResponse);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] GetLocationsAsync: {ex.Message}");
            return null;
        }
    }
}
