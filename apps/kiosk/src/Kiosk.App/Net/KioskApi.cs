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

public sealed record CrashLogRequest
{
    [JsonPropertyName("text")] public string Text { get; init; } = "";
}

// ── Qabul (reception registration) — backend persists + returns a talon ──
public sealed record CreateAppointmentRequest
{
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
    // Optional issue summary captured via on-screen keyboard. The Council
    // calls the citizen back, so there's no official to pick and the topic
    // is the only context they leave besides the phone number.
    [JsonPropertyName("topic")] public string Topic { get; init; } = "";
}

public sealed record CreateAppointmentResponse
{
    [JsonPropertyName("appointment_id")] public string AppointmentId { get; init; } = "";
    [JsonPropertyName("reference_no")] public string ReferenceNo { get; init; } = "";
    [JsonPropertyName("phone_masked")] public string PhoneMasked { get; init; } = "";
    [JsonPropertyName("verification_token")] public string VerificationToken { get; init; } = "";
    // Base64 of the QR PNG bytes — mirrors the WS voice-flow envelope
    // (`appointment_submitted.qr_png_base64`). Empty string if the backend
    // failed to render.
    [JsonPropertyName("qr_png_base64")] public string QrPngBase64 { get; init; } = "";
    // Localized org names so the success talon doesn't have to wait for
    // the next heartbeat to reflect a freshly-renamed org.
    [JsonPropertyName("org_name_translations")]
    public Dictionary<string, string> OrgNameTranslations { get; init; } = new();
}

// ── Feedback (shaǵım / usınıs / minnetdarshılıq) ──
public sealed record CreateFeedbackRequest
{
    /// <summary>One of: "complaint", "suggestion", "gratitude".</summary>
    [JsonPropertyName("feedback_type")] public string FeedbackType { get; init; } = "";
    [JsonPropertyName("text")] public string Text { get; init; } = "";
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
}

public sealed record CreateFeedbackResponse
{
    [JsonPropertyName("feedback_id")] public string FeedbackId { get; init; } = "";
    [JsonPropertyName("feedback_type")] public string FeedbackType { get; init; } = "";
    [JsonPropertyName("phone_masked")] public string PhoneMasked { get; init; } = "";
    [JsonPropertyName("status")] public string Status { get; init; } = "";
    [JsonPropertyName("org_name_translations")]
    public Dictionary<string, string> OrgNameTranslations { get; init; } = new();
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

    /// <summary>POST /api/kiosk/crashlog — upload the local crash.log after a
    /// crash + watchdog restart so we can see the exact exception remotely.
    /// Fire-and-forget; never throws.</summary>
    public static async Task UploadCrashLogAsync(string text)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null || string.IsNullOrWhiteSpace(text)) return;
        try
        {
            await SignedHttpClient.PostJsonAsync(
                creds.BackendUrl, "/api/kiosk/crashlog",
                new CrashLogRequest { Text = text }, KioskJsonContext.Default.CrashLogRequest);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] UploadCrashLogAsync: {ex.Message}");
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

    /// <summary>POST /api/kiosk/appointments — reception registration.
    /// The Joqarı Keńes (Council) has no officials and no scheduled date;
    /// the citizen leaves a phone (+ optional issue summary) and the
    /// Council calls them back. Returns null on failure; backend logs the
    /// real error.</summary>
    public static async Task<CreateAppointmentResponse?> CreateAppointmentAsync(
        string phone, string topic = "")
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            var req = new CreateAppointmentRequest
            {
                Phone = phone,
                Topic = topic,
            };
            var resp = await SignedHttpClient.PostJsonAsync(
                creds.BackendUrl, "/api/kiosk/appointments",
                req, KioskJsonContext.Default.CreateAppointmentRequest);
            if (!resp.IsSuccessStatusCode)
            {
                Console.Error.WriteLine($"[api] CreateAppointmentAsync HTTP {(int)resp.StatusCode}");
                return null;
            }
            return await resp.Content.ReadFromJsonAsync(KioskJsonContext.Default.CreateAppointmentResponse);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] CreateAppointmentAsync: {ex.Message}");
            return null;
        }
    }

    /// <summary>POST /api/kiosk/feedback — citizen feedback (complaint /
    /// suggestion / gratitude). Triggered by ManualFeedbackPage after the
    /// visitor picks a type, types the text on the on-screen keyboard, and
    /// enters phone on the numeric keypad. Returns null on failure; backend
    /// logs the real error.</summary>
    public static async Task<CreateFeedbackResponse?> CreateFeedbackAsync(
        string feedbackType, string text, string phone)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            var req = new CreateFeedbackRequest
            {
                FeedbackType = feedbackType,
                Text = text,
                Phone = phone,
            };
            var resp = await SignedHttpClient.PostJsonAsync(
                creds.BackendUrl, "/api/kiosk/feedback",
                req, KioskJsonContext.Default.CreateFeedbackRequest);
            if (!resp.IsSuccessStatusCode)
            {
                Console.Error.WriteLine($"[api] CreateFeedbackAsync HTTP {(int)resp.StatusCode}");
                return null;
            }
            return await resp.Content.ReadFromJsonAsync(KioskJsonContext.Default.CreateFeedbackResponse);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] CreateFeedbackAsync: {ex.Message}");
            return null;
        }
    }
}
