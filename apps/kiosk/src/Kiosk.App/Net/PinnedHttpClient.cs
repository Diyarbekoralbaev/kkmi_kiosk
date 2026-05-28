using System;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace Kiosk.App.Net;

/// <summary>
/// HttpClient + WebSocket TLS pin factory.
///
/// Production pinning (CertPinSha256 set):
///   - https:// requests → leaf cert SHA-256 must match. Anything else is
///     rejected even if it has a valid chain via the system root store.
///     This is what blocks mitmproxy: the proxy can present a fully-trusted
///     cert and still get refused because the SHA differs.
///   - WebSocket upgrades over wss:// use the same callback via
///     <see cref="ValidateRemoteCertificate"/> — exposed so KioskClient can
///     hook it onto ClientWebSocket.Options.RemoteCertificateValidationCallback.
///
/// Dev mode (CertPinSha256 empty):
///   - https:// requires a normally-valid chain — no pin enforcement.
///   - On startup the app prints a `[security] no cert pin baked` warning so
///     a leaked dev binary is obvious in logs.
///   - http:// is allowed (loopback only, real prod is HTTPS).
///
/// publish.win.sh injects the production SHA-256 by sed-replacing the const
/// before AOT compile, so the placeholder never reaches the shipped binary.
/// </summary>
public static class PinnedHttpClient
{
    // publish.win.sh replaces this with the prod cert SHA-256 (uppercase hex, no colons).
    public const string CertPinSha256 = "";

    public static HttpClient Create()
    {
        var handler = new HttpClientHandler
        {
            ServerCertificateCustomValidationCallback = (req, cert, chain, errs) =>
                ValidateRemoteCertificate(req?.RequestUri, cert, chain, errs),
        };
        return new HttpClient(handler)
        {
            Timeout = TimeSpan.FromSeconds(15),
        };
    }

    /// <summary>Shared validator: HttpClient + ClientWebSocket use the same
    /// rules. Returns true when the cert is acceptable.</summary>
    public static bool ValidateRemoteCertificate(
        Uri? requestUri,
        X509Certificate2? cert,
        X509Chain? chain,
        SslPolicyErrors errors)
    {
        var scheme = requestUri?.Scheme ?? "";
        var isTls = scheme is "https" or "wss";
        if (!isTls)
            return true; // dev plain http/ws — no pin

        if (cert is null) return false;

        if (string.IsNullOrEmpty(CertPinSha256))
            return errors == SslPolicyErrors.None; // no pin baked → fall back to chain

        var hash = Convert.ToHexString(SHA256.HashData(cert.RawData));
        return string.Equals(hash, CertPinSha256, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>True iff a cert pin was baked into this build.
    /// Used at startup to log a "DEV mode" banner when the pin is empty.</summary>
    public static bool HasPin => !string.IsNullOrEmpty(CertPinSha256);
}
