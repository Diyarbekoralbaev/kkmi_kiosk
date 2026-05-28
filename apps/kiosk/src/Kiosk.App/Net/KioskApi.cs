using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using Kiosk.App.Identity;

namespace Kiosk.App.Net;

public sealed record Official
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("position")] public string Position { get; init; } = "";
    [JsonPropertyName("responsibilities")] public string Responsibilities { get; init; } = "";
    [JsonPropertyName("reception_day")] public string ReceptionDay { get; init; } = "";
    [JsonPropertyName("reception_time")] public string ReceptionTime { get; init; } = "";
    [JsonPropertyName("order")] public int Order { get; init; }
    // "chief" = the single hokim; "deputy" = orinbasar. Kiosk Home tiles
    // pre-filter QabulPage's officials list by this value.
    [JsonPropertyName("role")] public string Role { get; init; } = "deputy";
    // True iff a photo has been uploaded for this official. Drives the
    // QabulPage avatar — photo when true, initials-circle fallback when
    // false. Photo URL is built client-side as:
    // {BackendUrl}/api/public/officials/{Id}/photo.jpg
    [JsonPropertyName("has_photo")] public bool HasPhoto { get; init; }
}

public sealed record CreateApplicationRequest
{
    [JsonPropertyName("topic")] public string Topic { get; init; } = "";
    [JsonPropertyName("body")] public string Body { get; init; } = "";
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
    [JsonPropertyName("category_slug")] public string CategorySlug { get; init; } = "other";
}

public sealed record CreateApplicationResponse
{
    [JsonPropertyName("application_id")] public string ApplicationId { get; init; } = "";
    [JsonPropertyName("topic")] public string Topic { get; init; } = "";
    [JsonPropertyName("body")] public string Body { get; init; } = "";
    [JsonPropertyName("phone_masked")] public string PhoneMasked { get; init; } = "";
    [JsonPropertyName("category_slug")] public string CategorySlug { get; init; } = "";
    [JsonPropertyName("category_resolved")] public bool CategoryResolved { get; init; }
    [JsonPropertyName("status")] public string Status { get; init; } = "";
    [JsonPropertyName("org_name_translations")]
    public Dictionary<string, string> OrgNameTranslations { get; init; } = new();
}

public sealed record CreateAppointmentRequest
{
    [JsonPropertyName("official_id")] public string OfficialId { get; init; } = "";
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
    // Manual-flow topic captured via on-screen keyboard. Backend
    // accepts an optional field (default "") so older kiosk binaries
    // still work after we redeploy the backend ahead of the kiosk.
    [JsonPropertyName("topic")] public string Topic { get; init; } = "";
}

public sealed record CreateAppointmentResponse
{
    [JsonPropertyName("appointment_id")] public string AppointmentId { get; init; } = "";
    [JsonPropertyName("queue_number")] public int QueueNumber { get; init; }
    [JsonPropertyName("official_name")] public string OfficialName { get; init; } = "";
    [JsonPropertyName("official_position")] public string OfficialPosition { get; init; } = "";
    [JsonPropertyName("scheduled_date")] public string ScheduledDate { get; init; } = "";
    [JsonPropertyName("scheduled_date_human")] public string ScheduledDateHuman { get; init; } = "";
    [JsonPropertyName("reception_time")] public string ReceptionTime { get; init; } = "";
    [JsonPropertyName("phone_masked")] public string PhoneMasked { get; init; } = "";
    [JsonPropertyName("verification_token")] public string VerificationToken { get; init; } = "";
    // Base64 of the QR PNG bytes — mirrors the WS voice-flow envelope
    // (`appointment_submitted.qr_png_base64`). Empty string if the backend
    // failed to render (the kiosk falls back to a blank QR cell rather
    // than crashing). Decoded by QabulPage.OnConfirmClicked into the
    // SessionStore.AppointmentQrPng byte[] that <Image x:Name="QrImage" />
    // listens to via PropertyChanged.
    [JsonPropertyName("qr_png_base64")] public string QrPngBase64 { get; init; } = "";
    // Localized org names so the success talon doesn't have to wait for
    // the next heartbeat to reflect a freshly-renamed org.
    [JsonPropertyName("org_name_translations")]
    public System.Collections.Generic.Dictionary<string, string> OrgNameTranslations { get; init; }
        = new System.Collections.Generic.Dictionary<string, string>();
}

/// <summary>
/// HTTP client for kiosk-side reads (officials, etc.). Each request is signed
/// with the device's TPM-bound private key via <see cref="SignedHttpClient"/>.
/// </summary>
public static class KioskApi
{
    public static async Task<List<Official>> GetOfficialsAsync()
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return new List<Official>();
        try
        {
            var resp = await SignedHttpClient.GetAsync(creds.BackendUrl, "/api/kiosk/officials");
            if (!resp.IsSuccessStatusCode) return new List<Official>();
            var list = await resp.Content.ReadFromJsonAsync(KioskJsonContext.Default.ListOfficial);
            return list ?? new List<Official>();
        }
        catch
        {
            return new List<Official>();
        }
    }

    /// <summary>POST /api/kiosk/appointments — manual booking.
    /// `topic` carries the visitor-typed issue summary from the new
    /// on-screen keyboard step in QabulPage. Returns null on failure;
    /// backend logs the real error.</summary>
    public static async Task<CreateAppointmentResponse?> CreateAppointmentAsync(
        string officialId, string phone, string topic = "")
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            var req = new CreateAppointmentRequest
            {
                OfficialId = officialId,
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

    /// <summary>POST /api/kiosk/applications — manual murajaat (citizen
    /// complaint) submission. Triggered by the ManualSubmitPage after
    /// the visitor types topic + body on the on-screen keyboard and
    /// enters phone on the numeric keypad. Category defaults to "other"
    /// — the manual flow doesn't ask the visitor to categorize. Returns
    /// null on failure; backend logs the real error.</summary>
    public static async Task<CreateApplicationResponse?> CreateApplicationAsync(
        string topic, string body, string phone, string categorySlug = "other")
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            var req = new CreateApplicationRequest
            {
                Topic = topic,
                Body = body,
                Phone = phone,
                CategorySlug = categorySlug,
            };
            var resp = await SignedHttpClient.PostJsonAsync(
                creds.BackendUrl, "/api/kiosk/applications",
                req, KioskJsonContext.Default.CreateApplicationRequest);
            if (!resp.IsSuccessStatusCode)
            {
                Console.Error.WriteLine($"[api] CreateApplicationAsync HTTP {(int)resp.StatusCode}");
                return null;
            }
            return await resp.Content.ReadFromJsonAsync(KioskJsonContext.Default.CreateApplicationResponse);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] CreateApplicationAsync: {ex.Message}");
            return null;
        }
    }
}
