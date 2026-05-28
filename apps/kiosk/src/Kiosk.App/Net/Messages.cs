using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Kiosk.App.Net;

/// <summary>
/// Wire DTOs that mirror the backend's Pydantic schemas. Property names use
/// snake_case via JsonPropertyName so the .NET source generator can serialize
/// without reflection (AOT-friendly in slice 13).
/// </summary>
public sealed record EnrollRequest
{
    [JsonPropertyName("enrollment_code")] public string EnrollmentCode { get; init; } = "";
    [JsonPropertyName("public_key_pem")] public string PublicKeyPem { get; init; } = "";
    [JsonPropertyName("tpm_attested")] public bool TpmAttested { get; init; }
}

public sealed record EnrollResponse
{
    [JsonPropertyName("device_id")] public string DeviceId { get; init; } = "";
    [JsonPropertyName("org_name")] public string OrgName { get; init; } = "";
    [JsonPropertyName("org_slug")] public string OrgSlug { get; init; } = "";
    /// <summary>{"uz": "...", "kk": "...", "ru": "..."} — localized display
    /// names. Older backends omit this; consumers fall back to OrgName.</summary>
    [JsonPropertyName("org_name_translations")]
    public Dictionary<string, string> OrgNameTranslations { get; init; } = new();
    /// <summary>Localized street address — kiosk Contacts page row 1.</summary>
    [JsonPropertyName("address_translations")]
    public Dictionary<string, string> AddressTranslations { get; init; } = new();
    [JsonPropertyName("email")] public string Email { get; init; } = "";
    /// <summary>Localized working hours line — Contacts page row 4.</summary>
    [JsonPropertyName("work_hours_translations")]
    public Dictionary<string, string> WorkHoursTranslations { get; init; } = new();
    [JsonPropertyName("helpline_phone")] public string HelplinePhone { get; init; } = "";
}

public sealed record AuthChallengeResponse
{
    [JsonPropertyName("nonce")] public string Nonce { get; init; } = "";
    [JsonPropertyName("expires_at")] public string ExpiresAt { get; init; } = "";
}

public sealed record WeatherDto
{
    [JsonPropertyName("city")] public string City { get; init; } = "";
    [JsonPropertyName("temp_c")] public int TempC { get; init; }
    [JsonPropertyName("fetched_at")] public string FetchedAt { get; init; } = "";
}

public sealed record HeartbeatResponse
{
    [JsonPropertyName("ok")] public bool Ok { get; init; }
    [JsonPropertyName("org_name")] public string OrgName { get; init; } = "";
    [JsonPropertyName("org_slug")] public string OrgSlug { get; init; } = "";
    /// <summary>Localized variants. Sent on every heartbeat so super-panel
    /// renames in any language reach the kiosk within one tick.</summary>
    [JsonPropertyName("org_name_translations")]
    public Dictionary<string, string> OrgNameTranslations { get; init; } = new();
    // null when org has no geo configured or every weather fetch failed.
    [JsonPropertyName("weather")] public WeatherDto? Weather { get; init; }
    [JsonPropertyName("helpline_phone")] public string HelplinePhone { get; init; } = "";
    /// <summary>Localized street address — kiosk Contacts page row 1.</summary>
    [JsonPropertyName("address_translations")]
    public Dictionary<string, string> AddressTranslations { get; init; } = new();
    [JsonPropertyName("email")] public string Email { get; init; } = "";
    /// <summary>Localized working hours line — Contacts page row 4.</summary>
    [JsonPropertyName("work_hours_translations")]
    public Dictionary<string, string> WorkHoursTranslations { get; init; } = new();
}

public sealed record ApiError
{
    [JsonPropertyName("code")] public string Code { get; init; } = "";
    [JsonPropertyName("message")] public string Message { get; init; } = "";
    [JsonPropertyName("correlation_id")] public string CorrelationId { get; init; } = "";
}

// ── Inbound WS JSON envelopes (server → client) ─────────────────────────────

public sealed record NavigateMessage
{
    [JsonPropertyName("screen")] public string Screen { get; init; } = "home";
}

public sealed record TranscriptMessage
{
    [JsonPropertyName("text")] public string Text { get; init; } = "";
    [JsonPropertyName("final")] public bool Final { get; init; }
    [JsonPropertyName("speaker")] public string Speaker { get; init; } = "";
}

public sealed record ApplicationPreviewMessage
{
    [JsonPropertyName("topic")] public string Topic { get; init; } = "";
    [JsonPropertyName("body")] public string Body { get; init; } = "";
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
}

public sealed record ApplicationSubmittedMessage
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("topic")] public string Topic { get; init; } = "";
    [JsonPropertyName("body")] public string Body { get; init; } = "";
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
}

public sealed record AppointmentProgressMessage
{
    /// <summary>One of: "topic", "official", "phone".</summary>
    [JsonPropertyName("stage")] public string Stage { get; init; } = "";
    [JsonPropertyName("topic")] public string? Topic { get; init; }
    [JsonPropertyName("official_id")] public string? OfficialId { get; init; }
    [JsonPropertyName("official_name")] public string? OfficialName { get; init; }
    [JsonPropertyName("official_position")] public string? OfficialPosition { get; init; }
    [JsonPropertyName("scheduled_date_human")] public string? ScheduledDateHuman { get; init; }
    [JsonPropertyName("reception_time")] public string? ReceptionTime { get; init; }
    [JsonPropertyName("phone_masked")] public string? PhoneMasked { get; init; }
}

public sealed record AppointmentPreviewMessage
{
    [JsonPropertyName("official_id")] public string OfficialId { get; init; } = "";
    [JsonPropertyName("official_name")] public string OfficialName { get; init; } = "";
    [JsonPropertyName("official_position")] public string OfficialPosition { get; init; } = "";
    [JsonPropertyName("scheduled_date")] public string ScheduledDate { get; init; } = "";
    [JsonPropertyName("scheduled_date_human")] public string ScheduledDateHuman { get; init; } = "";
    [JsonPropertyName("reception_time")] public string ReceptionTime { get; init; } = "";
    [JsonPropertyName("phone_masked")] public string PhoneMasked { get; init; } = "";
    [JsonPropertyName("topic")] public string Topic { get; init; } = "";
}

public sealed record AppointmentSubmittedMessage
{
    [JsonPropertyName("appointment_id")] public string AppointmentId { get; init; } = "";
    [JsonPropertyName("queue_number")] public int QueueNumber { get; init; }
    [JsonPropertyName("scheduled_date")] public string ScheduledDate { get; init; } = "";
    [JsonPropertyName("scheduled_date_human")] public string ScheduledDateHuman { get; init; } = "";
    [JsonPropertyName("reception_time")] public string ReceptionTime { get; init; } = "";
    [JsonPropertyName("official_name")] public string OfficialName { get; init; } = "";
    [JsonPropertyName("official_position")] public string OfficialPosition { get; init; } = "";
    /// <summary>"chief" or "deputy". Drives which subtitle (Shaxsiy / O'rinbosar)
    /// the on-screen success talon renders — must match the printed receipt.
    /// Empty in older backend builds; SessionStore tolerates the absence.</summary>
    [JsonPropertyName("official_role")] public string OfficialRole { get; init; } = "";
    [JsonPropertyName("phone_masked")] public string PhoneMasked { get; init; } = "";
    [JsonPropertyName("topic")] public string Topic { get; init; } = "";
    [JsonPropertyName("verification_url")] public string VerificationUrl { get; init; } = "";
    [JsonPropertyName("qr_png_base64")] public string QrPngBase64 { get; init; } = "";
    [JsonPropertyName("receipt_pdf_base64")] public string ReceiptPdfBase64 { get; init; } = "";
    /// <summary>Localized org names so the success-talon header swaps to the
    /// right language without waiting for the next heartbeat.</summary>
    [JsonPropertyName("org_name_translations")]
    public Dictionary<string, string> OrgNameTranslations { get; init; } = new();
}

public sealed record ServerErrorMessage
{
    [JsonPropertyName("code")] public string Code { get; init; } = "";
    [JsonPropertyName("message")] public string Message { get; init; } = "";
}

// Outbound JSON envelopes (turn_start / turn_end) are tiny static literals
// sent by KioskClient directly — no record types needed.
