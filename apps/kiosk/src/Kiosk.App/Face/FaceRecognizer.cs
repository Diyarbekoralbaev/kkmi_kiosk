using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using FaceAiSharp;
using Kiosk.App.Net;
using OpenCvSharp;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;

namespace Kiosk.App.Face;

/// <summary>A person recognized by the local camera, with the cosine score.</summary>
public sealed record RecognizedPerson(string Name, string Title, double Score);

/// <summary>
/// On-device face recognition for the "greet the boss by name" feature.
///
/// Pipeline (all local, no cloud): SCRFD detects + locates the face, ArcFace
/// turns the aligned crop into a 512-d embedding, comparison is a cosine dot
/// product (≥ 0.42 ⇒ same person — FaceAiSharp's published threshold).
///
/// The enrolled set is the gov-panel "Руководство" (OrgKbOfficial) persons:
/// we GET /api/kiosk/officials, fetch each one's photo, and embed it once.
/// At AI-button time the camera grabs a couple of frames and matches against
/// that cached set. Nothing here may ever throw into the voice path — face
/// recognition is a nicety, a failure just means a generic greeting.
///
/// Native AOT note: FaceAiSharp's bundle factory resolves model paths via
/// Assembly.Location, which is empty under AOT. We therefore construct the
/// models with explicit paths off AppContext.BaseDirectory\onnx\ (proven by
/// the --face-test diagnostic).
/// </summary>
public static class FaceRecognizer
{
    public const double MatchThreshold = 0.42;

    private static readonly object _gate = new();
    private static ScrfdDetector? _det;
    private static ArcFaceEmbeddingsGenerator? _rec;
    private static List<(string Name, string Title, float[] Emb)> _enrolled = new();
    private static Task<int>? _syncTask;

    public static int EnrolledCount
    {
        get { lock (_gate) { return _enrolled.Count; } }
    }

    private static void EnsureModels()
    {
        if (_det != null && _rec != null) return;
        lock (_gate)
        {
            if (_det != null && _rec != null) return;
            var onnxDir = Path.Combine(AppContext.BaseDirectory, "onnx");
            var detPath = Path.Combine(onnxDir, "scrfd_2.5g_kps.onnx");
            var recPath = Path.Combine(onnxDir, "arcfaceresnet100-11-int8.onnx");
            _det = new ScrfdDetector(
                new ScrfdDetectorOptions { ModelPath = detPath }, null);
            _rec = new ArcFaceEmbeddingsGenerator(
                new ArcFaceEmbeddingsGeneratorOptions { ModelPath = recPath }, null);
        }
    }

    /// <summary>Embedding of the largest detected face, or null if no face.</summary>
    public static float[]? EmbedLargestFace(Image<Rgb24> img)
    {
        EnsureModels();
        var faces = _det!.DetectFaces(img);
        if (faces.Count == 0) return null;
        var face = faces.OrderByDescending(f => f.Box.Width * f.Box.Height).First();
        if (face.Landmarks is null) return null;
        // AlignFaceUsingLandmarks mutates the image in place — work on a clone
        // so the caller's image (and the detection coords) stay intact. Use the
        // 2-arg IFaceEmbeddingsGenerator overload (the concrete class also
        // exposes a 3-arg static one that would otherwise hide it).
        using var work = img.Clone();
        ((IFaceEmbeddingsGenerator)_rec!).AlignFaceUsingLandmarks(work, face.Landmarks);
        return _rec!.GenerateEmbedding(work);
    }

    public static double Dot(float[] a, float[] b)
        => FaceAiSharp.Extensions.GeometryExtensions.Dot(a, b);

    /// <summary>Sync the "Руководство" persons + build their face embeddings.
    /// Runs at most once per process via EnsureSyncedAsync; retries on failure.
    /// Returns the number of usable enrolled faces.</summary>
    public static async Task<int> SyncAsync(string backendUrl, CancellationToken ct = default)
    {
        EnsureModels();
        OfficialDto[] officials;
        using (var resp = await SignedHttpClient.GetAsync(backendUrl, "/api/kiosk/officials", ct)
                   .ConfigureAwait(false))
        {
            resp.EnsureSuccessStatusCode();
            var json = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            officials = JsonSerializer.Deserialize(json, KioskJsonContext.Default.OfficialDtoArray)
                        ?? Array.Empty<OfficialDto>();
        }

        var fresh = new List<(string, string, float[])>();
        using var http = PinnedHttpClient.Create();
        foreach (var o in officials)
        {
            if (!o.HasPhoto || string.IsNullOrEmpty(o.Id)) continue;
            try
            {
                var url = backendUrl.TrimEnd('/') + $"/api/public/officials/{o.Id}/photo.jpg";
                var bytes = await http.GetByteArrayAsync(url, ct).ConfigureAwait(false);
                using var img = Image.Load<Rgb24>(bytes);
                var emb = EmbedLargestFace(img);
                if (emb != null) fresh.Add((o.Name, o.Position, emb));
            }
            catch
            {
                // One bad/faceless photo must not abort the whole sync.
            }
        }

        lock (_gate) { _enrolled = fresh; }
        return fresh.Count;
    }

    /// <summary>Sync once per process. Concurrent callers share the same task;
    /// a failed sync is discarded so a later call can retry.</summary>
    public static Task<int> EnsureSyncedAsync(string backendUrl, CancellationToken ct = default)
    {
        lock (_gate)
        {
            if (_syncTask is { IsFaulted: false }) return _syncTask;
            _syncTask = SyncAsync(backendUrl, ct);
            var captured = _syncTask;
            // Drop a faulted task so the next session retries the sync.
            _ = captured.ContinueWith(t =>
            {
                if (t.IsFaulted) lock (_gate) { if (_syncTask == captured) _syncTask = null; }
            }, TaskScheduler.Default);
            return _syncTask;
        }
    }

    /// <summary>Open the default camera, grab frames for up to <paramref name="seconds"/>,
    /// and return the first enrolled person matching above threshold. Returns
    /// null on no camera, no face, or no confident match. Synchronous (call via
    /// Task.Run); never throws.</summary>
    public static RecognizedPerson? RecognizeFromCamera(int seconds = 2, double threshold = MatchThreshold)
    {
        List<(string Name, string Title, float[] Emb)> enrolled;
        lock (_gate) { enrolled = _enrolled; }
        if (enrolled.Count == 0) return null;

        try
        {
            EnsureModels();
            using var cap = new VideoCapture(0);
            if (!cap.IsOpened()) return null;

            var deadline = DateTime.UtcNow.AddSeconds(seconds);
            using var mat = new Mat();
            while (DateTime.UtcNow < deadline)
            {
                if (!cap.Read(mat) || mat.Empty()) continue;
                if (!Cv2.ImEncode(".bmp", mat, out byte[] buf)) continue;
                float[]? emb;
                using (var img = Image.Load<Rgb24>(buf))
                    emb = EmbedLargestFace(img);
                if (emb == null) continue;

                (string Name, string Title, double Score) best = ("", "", -1);
                foreach (var e in enrolled)
                {
                    var d = Dot(emb, e.Emb);
                    if (d > best.Score) best = (e.Name, e.Title, d);
                }
                if (best.Score >= threshold)
                    return new RecognizedPerson(best.Name, best.Title, best.Score);
            }
        }
        catch
        {
            // Camera/driver/AOT hiccup → just no greeting.
        }
        return null;
    }

    /// <summary>One-shot recognize-first used at AI-session start: make sure the
    /// enrolled set is synced (bounded), then look at the camera (bounded).
    /// Total wall-clock is capped so the voice session never stalls; any error
    /// yields null (generic greeting).</summary>
    public static async Task<RecognizedPerson?> RecognizeForGreetingAsync(
        string backendUrl, int cameraSeconds = 2)
    {
        try
        {
            // Bound the first-run network sync so AI start can't hang on it.
            try { await EnsureSyncedAsync(backendUrl).WaitAsync(TimeSpan.FromSeconds(3)).ConfigureAwait(false); }
            catch { /* sync slow/offline → match against whatever is cached */ }

            return await Task.Run(() => RecognizeFromCamera(cameraSeconds)).ConfigureAwait(false);
        }
        catch
        {
            return null;
        }
    }
}
