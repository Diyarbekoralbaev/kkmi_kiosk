using System;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using Kiosk.App.Identity;
using Kiosk.App.Net;
using Velopack;

namespace Kiosk.App.Update;

/// <summary>
/// Force-update flow:
///   1. <see cref="Bootstrap"/> at the very top of Main() so Velopack can
///      handle its own --squirrel-* command-line modes.
///   2. <see cref="CheckAsync"/> hits the backend's signed update endpoint.
///      Returns a small struct describing what (if anything) is available.
///   3. <see cref="ApplyAsync"/> downloads the manifest + nupkg, verifies
///      SHA-256, and hands off to Velopack's <c>WaitExitThenApplyUpdates</c>.
///
/// Auth: every backend call goes through <see cref="SignedHttpClient"/>, so
/// revoked kiosks fail at the auth gate and never see new builds.
///
/// Dev mode (no enrolled creds yet, or backend unreachable): all methods
/// no-op cleanly so the app still boots into the enrollment dialog.
/// </summary>
public static class Updater
{
    public sealed class UpdateInfo
    {
        public string ReleaseId { get; init; } = "";
        public string Version { get; init; } = "";
        public string FileSha256 { get; init; } = "";
        public long FileSize { get; init; }
        public string FileName { get; init; } = "";
        public string DownloadPath { get; init; } = "";
        // Velopack feed manifest fetched alongside the .nupkg. Without it,
        // SimpleFileSource.CheckForUpdatesAsync returns null and the apply
        // step silently no-ops. Both fields are populated when the backend
        // has the manifest on disk (it pulls it from the GH release on sync).
        public string? ManifestPath { get; init; }
        public string? ManifestName { get; init; }
        public bool Mandatory { get; init; }
        public string? ReleaseNotes { get; init; }
    }

    public static void Bootstrap()
    {
        VelopackApp.Build().Run();
    }

    /// <summary>Hits /api/kiosk/updates/check. Returns null if no update is
    /// available, the device isn't enrolled, the call fails, OR the
    /// reported version is not strictly newer than the installed one.
    /// The backend's /check is naïve — it always returns the latest
    /// published row regardless of which version the kiosk is on, so the
    /// version comparison MUST happen client-side. Without this, a kiosk
    /// at HEAD would still see "available=true" for an older published row,
    /// flash UpdatingPage, download 30 MB, and fall through to "Yangılaw
    /// ótpedi" (Velopack's own no-op).</summary>
    public static async Task<UpdateInfo?> CheckAsync(CancellationToken ct = default)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            using var resp = await SignedHttpClient
                .GetAsync(creds.BackendUrl, "/api/kiosk/updates/check", ct)
                .ConfigureAwait(false);
            if (!resp.IsSuccessStatusCode) return null;
            var body = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            var dto = JsonSerializer.Deserialize(body, UpdateJsonContext.Default.UpdateCheckDto);
            if (dto is null || !dto.Available) return null;
            if (!IsStrictlyNewer(dto.Version)) return null;
            return new UpdateInfo
            {
                ReleaseId = dto.ReleaseId ?? "",
                Version = dto.Version ?? "",
                FileSha256 = dto.FileSha256 ?? "",
                FileSize = dto.FileSize ?? 0,
                FileName = dto.FileName ?? "kiosk-update.bin",
                DownloadPath = dto.DownloadUrl ?? "",
                ManifestPath = dto.ManifestUrl,
                ManifestName = dto.ManifestName,
                Mandatory = dto.Mandatory,
                ReleaseNotes = dto.ReleaseNotes,
            };
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[update] check failed: {ex.Message}");
            return null;
        }
    }

    /// <summary>True if <paramref name="availableVersion"/> is strictly newer
    /// than the running assembly's version. The build pipeline stamps both
    /// AssemblyVersion and PackageVersion from the same `Version` MSBuild
    /// property (publish.win.sh), so they're directly comparable.</summary>
    private static bool IsStrictlyNewer(string? availableVersion)
    {
        if (string.IsNullOrWhiteSpace(availableVersion)) return false;
        if (!Version.TryParse(availableVersion, out var available)) return true;
        var installed = typeof(Updater).Assembly.GetName().Version;
        if (installed is null) return true;
        // Normalize 3-part vs 4-part: a parsed "0.26130.1118" has Revision=-1
        // while AssemblyName.Version is always 4-part with Revision=0.
        // Pad the shorter side so equal versions compare as equal.
        var a = new Version(available.Major, available.Minor,
                            available.Build < 0 ? 0 : available.Build,
                            available.Revision < 0 ? 0 : available.Revision);
        var i = new Version(installed.Major, installed.Minor,
                            installed.Build < 0 ? 0 : installed.Build,
                            installed.Revision < 0 ? 0 : installed.Revision);
        return a > i;
    }

    /// <summary>Download the manifest + nupkg, verify SHA-256, queue Velopack
    /// apply. Returns true ONLY if Velopack accepted the asset and queued an
    /// apply via <c>WaitExitThenApplyUpdates</c>; the caller exits the app on
    /// true so the Velopack helper can apply, and stays running on false so
    /// the user isn't trapped in a "100% then quit" loop.</summary>
    public static async Task<bool> ApplyAsync(
        UpdateInfo info,
        Action<double>? progress = null,
        CancellationToken ct = default)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return false;

        var tmpDir = Path.Combine(Path.GetTempPath(), "kiosk-updates");
        Directory.CreateDirectory(tmpDir);
        // Wipe leftovers from prior aborted runs so SimpleFileSource only sees
        // this release's files. Stale manifests/packages would otherwise make
        // CheckForUpdatesAsync return the wrong asset (or none).
        foreach (var stale in Directory.GetFiles(tmpDir))
        {
            try { File.Delete(stale); } catch { }
        }
        var localPath = Path.Combine(tmpDir, info.FileName);

        try
        {
            using var http = PinnedHttpClient.Create();

            // 1) Manifest (releases.{channel}.json) — Velopack feed pointer.
            //    Without this in tmpDir, CheckForUpdatesAsync returns null.
            if (!string.IsNullOrEmpty(info.ManifestPath) && !string.IsNullOrEmpty(info.ManifestName))
            {
                var mUrl = creds.BackendUrl.TrimEnd('/') + info.ManifestPath;
                var mAuth = await SignedHttpClient.BuildAuthHeaderAsync(creds.BackendUrl, creds.DeviceId, ct);
                using var mReq = new HttpRequestMessage(HttpMethod.Get, mUrl);
                mReq.Headers.TryAddWithoutValidation("X-Kiosk-Auth", mAuth);
                using var mResp = await http.SendAsync(mReq, ct);
                if (!mResp.IsSuccessStatusCode)
                {
                    Console.Error.WriteLine($"[update] manifest fetch failed: {(int)mResp.StatusCode}");
                    return false;
                }
                var manifestBytes = await mResp.Content.ReadAsByteArrayAsync(ct);
                await File.WriteAllBytesAsync(
                    Path.Combine(tmpDir, info.ManifestName),
                    manifestBytes, ct);
            }
            else
            {
                // No manifest published for this release — Velopack apply
                // will fail and we'd loop. Bail out cleanly so the user stays
                // on their current version with the kiosk usable.
                Console.Error.WriteLine("[update] no manifest_url in /check response — cannot apply via Velopack");
                return false;
            }

            // 2) The .nupkg payload, with running SHA-256 + progress.
            var url = creds.BackendUrl.TrimEnd('/') + info.DownloadPath;
            var auth = await SignedHttpClient.BuildAuthHeaderAsync(creds.BackendUrl, creds.DeviceId, ct);
            using var req = new HttpRequestMessage(HttpMethod.Get, url);
            req.Headers.TryAddWithoutValidation("X-Kiosk-Auth", auth);
            using var resp = await http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct);
            if (!resp.IsSuccessStatusCode) return false;

            var hasher = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            await using (var srv = await resp.Content.ReadAsStreamAsync(ct))
            await using (var dst = File.Create(localPath))
            {
                var buf = new byte[1 << 16];
                long total = 0;
                int n;
                while ((n = await srv.ReadAsync(buf, ct)) > 0)
                {
                    await dst.WriteAsync(buf.AsMemory(0, n), ct);
                    hasher.AppendData(buf, 0, n);
                    total += n;
                    if (info.FileSize > 0)
                        progress?.Invoke(total / (double)info.FileSize);
                }
            }
            var actualSha = Convert.ToHexString(hasher.GetHashAndReset()).ToLowerInvariant();
            if (!string.Equals(actualSha, info.FileSha256, StringComparison.OrdinalIgnoreCase))
            {
                Console.Error.WriteLine(
                    $"[update] SHA mismatch — refusing to apply. expected={info.FileSha256} got={actualSha}");
                try { File.Delete(localPath); } catch { }
                return false;
            }

            // 3) Hand off to Velopack via local feed. SimpleFileSource reads
            //    the manifest + .nupkg files we just wrote. CheckForUpdatesAsync
            //    returns the asset only if (a) the manifest is well-formed and
            //    (b) the listed version is newer than the installed one.
            //    `applied` is the result the caller acts on.
            var applied = false;
            try
            {
                var mgr = new UpdateManager(new Velopack.Sources.SimpleFileSource(new DirectoryInfo(tmpDir)));
                var asset = await mgr.CheckForUpdatesAsync();
                if (asset is not null)
                {
                    await mgr.DownloadUpdatesAsync(asset);
                    mgr.WaitExitThenApplyUpdates(asset);
                    applied = true;
                }
                else
                {
                    Console.Error.WriteLine("[update] velopack returned null asset — already on this version or manifest format mismatch");
                }
            }
            catch (Exception velo)
            {
                // Velopack rejects bad manifests / mismatched packages. Log,
                // return false so the caller doesn't quit the kiosk pointlessly.
                Console.Error.WriteLine($"[update] velopack apply failed: {velo.Message}");
            }
            return applied;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[update] apply failed: {ex.Message}");
            return false;
        }
    }
}

internal sealed record UpdateCheckDto
{
    [JsonPropertyName("available")] public bool Available { get; init; }
    [JsonPropertyName("version")] public string? Version { get; init; }
    [JsonPropertyName("release_id")] public string? ReleaseId { get; init; }
    [JsonPropertyName("file_sha256")] public string? FileSha256 { get; init; }
    [JsonPropertyName("file_size")] public long? FileSize { get; init; }
    [JsonPropertyName("file_name")] public string? FileName { get; init; }
    [JsonPropertyName("download_url")] public string? DownloadUrl { get; init; }
    [JsonPropertyName("manifest_url")] public string? ManifestUrl { get; init; }
    [JsonPropertyName("manifest_name")] public string? ManifestName { get; init; }
    [JsonPropertyName("mandatory")] public bool Mandatory { get; init; }
    [JsonPropertyName("release_notes")] public string? ReleaseNotes { get; init; }
}

[JsonSerializable(typeof(UpdateCheckDto))]
internal partial class UpdateJsonContext : JsonSerializerContext { }
