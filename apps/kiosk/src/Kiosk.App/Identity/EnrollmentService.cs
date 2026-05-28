using System;
using System.Net.Http;
using System.Net.Http.Json;
using System.Threading.Tasks;
using Kiosk.App.Net;

namespace Kiosk.App.Identity;

/// <summary>
/// Headless enrollment used by both the GUI dialog and the `--enroll` CLI mode.
///
/// Flow:
///   1. Make sure the TPM keypair exists (CryptoProviderFactory.Current).
///      If TPM 2.0 is missing on a Windows box, this throws
///      <see cref="TpmNotAvailableException"/> with a Karakalpak message
///      suitable for direct UI display.
///   2. POST /api/kiosk/enroll with the code + the public PEM (no shared
///      secret returned by the server — we don't need one).
///   3. Save the assigned device_id + backend URL to DeviceKeyStore.
/// </summary>
public static class EnrollmentService
{
    public sealed record EnrollResult(bool Success, string? Error, DeviceCredentials? Credentials);

    public static async Task<EnrollResult> EnrollAsync(string backendUrl, string enrollmentCode)
    {
        if (string.IsNullOrWhiteSpace(backendUrl) || string.IsNullOrWhiteSpace(enrollmentCode))
            return new EnrollResult(false, "missing_input", null);

        // Ensure the TPM-bound keypair exists. Hard-fail on Windows without TPM 2.0.
        var crypto = CryptoProviderFactory.Current;
        try
        {
            crypto.EnsureKeypair();
        }
        catch (TpmNotAvailableException ex)
        {
            return new EnrollResult(false, ex.Message, null);
        }
        catch (Exception ex)
        {
            return new EnrollResult(false, $"crypto_init_failed: {ex.Message}", null);
        }

        var publicKeyPem = crypto.GetPublicKeyPem();
        var tpmAttested = crypto is TpmCryptoProvider; // future: full TPM attestation report

        using var http = PinnedHttpClient.Create();
        var url = backendUrl.TrimEnd('/') + "/api/kiosk/enroll";
        try
        {
            using var resp = await http.PostAsJsonAsync(url, new EnrollRequest
            {
                EnrollmentCode = enrollmentCode,
                PublicKeyPem = publicKeyPem,
                TpmAttested = tpmAttested,
            }, KioskJsonContext.Default.EnrollRequest);
            if (!resp.IsSuccessStatusCode)
            {
                ApiError? err = null;
                try { err = await resp.Content.ReadFromJsonAsync(KioskJsonContext.Default.ApiError); } catch { }
                return new EnrollResult(false,
                    err is not null && !string.IsNullOrEmpty(err.Message)
                        ? $"{err.Code} {err.Message}"
                        : $"HTTP {(int)resp.StatusCode}",
                    null);
            }

            var enrolled = await resp.Content.ReadFromJsonAsync(KioskJsonContext.Default.EnrollResponse);
            if (enrolled is null || string.IsNullOrEmpty(enrolled.DeviceId))
                return new EnrollResult(false, "empty_response", null);

            var creds = new DeviceCredentials
            {
                BackendUrl = backendUrl.TrimEnd('/'),
                DeviceId = enrolled.DeviceId,
                // Backend hands back the org's display name + slug as part of
                // /enroll so a freshly-enrolled kiosk renders the right
                // hokimligi name from cold start, without waiting for the
                // first heartbeat.
                OrgName = enrolled.OrgName,
                OrgSlug = enrolled.OrgSlug,
                OrgNameTranslations = enrolled.OrgNameTranslations
                    ?? new System.Collections.Generic.Dictionary<string, string>(),
                // Same rationale for contact info — Contacts page would
                // otherwise show empty fields until the first heartbeat.
                OrgAddressTranslations = enrolled.AddressTranslations
                    ?? new System.Collections.Generic.Dictionary<string, string>(),
                OrgEmail = enrolled.Email ?? "",
                OrgWorkHoursTranslations = enrolled.WorkHoursTranslations
                    ?? new System.Collections.Generic.Dictionary<string, string>(),
                HelplinePhone = enrolled.HelplinePhone ?? "",
            };
            DeviceKeyStore.Save(creds);
            return new EnrollResult(true, null, creds);
        }
        catch (HttpRequestException ex) { return new EnrollResult(false, $"network: {ex.Message}", null); }
        catch (TaskCanceledException) { return new EnrollResult(false, "timeout", null); }
        catch (Exception ex) { return new EnrollResult(false, $"unexpected: {ex.Message}", null); }
    }
}
