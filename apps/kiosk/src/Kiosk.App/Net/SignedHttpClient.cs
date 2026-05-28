using System;
using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Threading;
using System.Threading.Tasks;
using Kiosk.App.Identity;

namespace Kiosk.App.Net;

/// <summary>Thrown when an auth-gated backend call comes back 401/403 —
/// the kiosk's identity was revoked (status=revoked or device key
/// revoked_at set) and no further API call will succeed until re-enroll.
/// Triggers the global <see cref="SignedHttpClient.DeviceRevoked"/> event
/// so the host UI (MainWindow) can render the red overlay.</summary>
public sealed class DeviceRevokedException : Exception
{
    public DeviceRevokedException(string message) : base(message) { }
}

/// <summary>
/// HTTP client that signs every outgoing request with the device's TPM key.
///
/// For each request:
///   1. Fetch a fresh nonce: GET /api/kiosk/auth/challenge?device_id=...
///   2. Sign the raw nonce bytes with the TPM private key (ECDSA P-256, SHA-256).
///   3. Set header X-Kiosk-Auth: device_id.nonce_b64.signature_b64
///   4. Send the actual request.
///
/// **Revocation handling:** any 401/403 from either the challenge endpoint
/// OR the real request fires <see cref="DeviceRevoked"/> and wipes the
/// local key store. Subscribers (MainWindow) flip the red overlay. This
/// way *every* HTTP path enforces revoke — not just the ProbeAuthAsync
/// heartbeat — so an admin pressing Revoke locks the kiosk regardless
/// of which screen the visitor is on.
/// </summary>
public static class SignedHttpClient
{
    /// <summary>Fires when ANY signed request comes back 401/403. Subscribers
    /// should marshal to the UI thread; this event is raised from whichever
    /// worker thread completed the HTTP call.</summary>
    public static event Action? DeviceRevoked;

    private static int _revokeFiredAlready;

    /// <summary>Idempotent: only wipes + fires once per process lifetime. The
    /// MainWindow subscription handles the rest (red overlay + voice stop).</summary>
    private static void HandleAuthFailure()
    {
        // Wipe credentials so a restart lands in the enrollment dialog, not
        // back into a half-broken authenticated state.
        try { DeviceKeyStore.Clear(); } catch { }
        if (System.Threading.Interlocked.Exchange(ref _revokeFiredAlready, 1) == 0)
            DeviceRevoked?.Invoke();
    }

    /// <summary>GET with auto-signed auth header. Returns the raw response.
    /// On 401/403 the global DeviceRevoked event has already fired by the
    /// time this returns.</summary>
    public static Task<HttpResponseMessage> GetAsync(
        string backendUrl, string path, CancellationToken ct = default)
        => SendNoBodyAsync(backendUrl, path, HttpMethod.Get, ct);

    /// <summary>POST with no body (e.g. heartbeat). For typed POSTs use the
    /// generic overload with a JsonTypeInfo so the AOT build stays
    /// reflection-free.</summary>
    public static Task<HttpResponseMessage> PostJsonAsync<T>(
        string backendUrl, string path, T? payload, CancellationToken ct = default)
        => payload is null
            ? SendNoBodyAsync(backendUrl, path, HttpMethod.Post, ct)
            : throw new InvalidOperationException(
                "Use PostJsonAsync(typeInfo, ...) overload for typed bodies — needed for Native AOT.");

    public static async Task<HttpResponseMessage> PostJsonAsync<T>(
        string backendUrl,
        string path,
        T payload,
        System.Text.Json.Serialization.Metadata.JsonTypeInfo<T> typeInfo,
        CancellationToken ct = default)
    {
        var creds = DeviceKeyStore.Load()
            ?? throw new InvalidOperationException("not enrolled");
        var authHeader = await BuildAuthHeaderAsync(backendUrl, creds.DeviceId, ct);

        using var http = PinnedHttpClient.Create();
        var url = backendUrl.TrimEnd('/') + path;
        var req = new HttpRequestMessage(HttpMethod.Post, url);
        req.Headers.TryAddWithoutValidation("X-Kiosk-Auth", authHeader);
        req.Content = JsonContent.Create(payload, typeInfo);
        var resp = await http.SendAsync(req, ct).ConfigureAwait(false);
        TripIfAuthFailure(resp);
        return resp;
    }

    private static async Task<HttpResponseMessage> SendNoBodyAsync(
        string backendUrl, string path, HttpMethod method, CancellationToken ct)
    {
        var creds = DeviceKeyStore.Load()
            ?? throw new InvalidOperationException("not enrolled");
        var authHeader = await BuildAuthHeaderAsync(backendUrl, creds.DeviceId, ct);

        using var http = PinnedHttpClient.Create();
        var url = backendUrl.TrimEnd('/') + path;
        var req = new HttpRequestMessage(method, url);
        req.Headers.TryAddWithoutValidation("X-Kiosk-Auth", authHeader);
        var resp = await http.SendAsync(req, ct).ConfigureAwait(false);
        TripIfAuthFailure(resp);
        return resp;
    }

    private static void TripIfAuthFailure(HttpResponseMessage resp)
    {
        if (resp.StatusCode == HttpStatusCode.Unauthorized ||
            resp.StatusCode == HttpStatusCode.Forbidden)
        {
            HandleAuthFailure();
        }
    }

    /// <summary>Fetch + sign a challenge, return the X-Kiosk-Auth header value.
    /// Public so KioskClient (WebSocket) can re-use the same flow on upgrade.
    /// Throws <see cref="DeviceRevokedException"/> if the challenge endpoint
    /// rejects the device — at that point we can't even build a valid header,
    /// so the caller gets a definitive signal instead of an opaque
    /// HttpRequestException.</summary>
    public static async Task<string> BuildAuthHeaderAsync(
        string backendUrl, string deviceId, CancellationToken ct = default)
    {
        using var http = PinnedHttpClient.Create();
        var challengeUrl = $"{backendUrl.TrimEnd('/')}/api/kiosk/auth/challenge?device_id={deviceId}";
        using var resp = await http.GetAsync(challengeUrl, ct).ConfigureAwait(false);
        if (resp.StatusCode == HttpStatusCode.Unauthorized ||
            resp.StatusCode == HttpStatusCode.Forbidden)
        {
            HandleAuthFailure();
            throw new DeviceRevokedException($"challenge rejected ({(int)resp.StatusCode})");
        }
        resp.EnsureSuccessStatusCode();
        var ch = await resp.Content.ReadFromJsonAsync(
            KioskJsonContext.Default.AuthChallengeResponse, ct).ConfigureAwait(false)
            ?? throw new InvalidOperationException("challenge_empty");
        var nonceB64 = ch.Nonce;
        var nonceBytes = Base64UrlDecode(nonceB64);

        var sig = await CryptoProviderFactory.Current.SignAsync(nonceBytes).ConfigureAwait(false);
        var sigB64 = Base64UrlEncode(sig);
        return $"{deviceId}.{nonceB64}.{sigB64}";
    }

    private static byte[] Base64UrlDecode(string s)
    {
        var pad = (4 - s.Length % 4) % 4;
        return Convert.FromBase64String(s.Replace('-', '+').Replace('_', '/') + new string('=', pad));
    }

    private static string Base64UrlEncode(byte[] bytes) =>
        Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
}
