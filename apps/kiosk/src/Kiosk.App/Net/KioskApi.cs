using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using Kiosk.App.Identity;

namespace Kiosk.App.Net;

public sealed record CreateApplicationRequest
{
    [JsonPropertyName("topic")] public string Topic { get; init; } = "";
    [JsonPropertyName("body")] public string Body { get; init; } = "";
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
}

public sealed record CreateApplicationResponse
{
    [JsonPropertyName("application_id")] public string ApplicationId { get; init; } = "";
    [JsonPropertyName("topic")] public string Topic { get; init; } = "";
    [JsonPropertyName("body")] public string Body { get; init; } = "";
    [JsonPropertyName("phone_masked")] public string PhoneMasked { get; init; } = "";
    [JsonPropertyName("status")] public string Status { get; init; } = "";
    [JsonPropertyName("org_name_translations")]
    public Dictionary<string, string> OrgNameTranslations { get; init; } = new();
}

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
    public System.Collections.Generic.Dictionary<string, string> OrgNameTranslations { get; init; }
        = new System.Collections.Generic.Dictionary<string, string>();
}

/// <summary>
/// HTTP client for kiosk-side writes (murajaat, appointment, feedback). Each
/// request is signed with the device's TPM-bound private key via
/// <see cref="SignedHttpClient"/>.
/// </summary>
public static class KioskApi
{
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

    /// <summary>POST /api/kiosk/applications — manual murajaat (citizen
    /// appeal) submission. Triggered by the ManualSubmitPage after
    /// the visitor types topic + body on the on-screen keyboard and
    /// enters phone on the numeric keypad. No category — the Council's
    /// appeal flow doesn't categorize. Returns null on failure; backend
    /// logs the real error.</summary>
    public static async Task<CreateApplicationResponse?> CreateApplicationAsync(
        string topic, string body, string phone)
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
