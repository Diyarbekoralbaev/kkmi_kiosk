using System;
using System.IO;
using System.Net.WebSockets;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace Kiosk.App.Net;

public enum ConnectionState
{
    Disconnected,
    Connecting,
    Connected,
    Reconnecting,
}

/// <summary>
/// WebSocket client for /ws/kiosk/voice.
///
/// - Authenticates via `Authorization: Bearer &lt;device_key&gt;` on the upgrade request
///   (set via ClientWebSocketOptions.SetRequestHeader; the server validates pre-accept
///   in api/kiosk_ws.py and returns HTTP 403 on mismatch).
/// - Two message kinds:
///     - Binary (PCM Int16 LE 24 kHz mono) → AudioReceived event.
///     - Text (JSON envelope) → routed by `type` to a typed event.
/// - SendAudioAsync writes 16 kHz PCM frames; thread-safe via semaphore.
/// - Auto-reconnect with exponential backoff (1, 2, 5, 5, 5, 5… s).
/// </summary>
public sealed class KioskClient : IAsyncDisposable
{
    private static readonly int[] ReconnectDelaysMs = { 1000, 2000, 5000, 5000, 5000 };

    private readonly string _backendUrl;
    private readonly string _deviceId;
    /// <summary>Which home tile the visitor opened. Sent as `?menu=` on the WS
    /// URL; the backend uses it to pick the prompt's focus block and the tool
    /// set the agent may call.</summary>
    private readonly string _menu;
    /// <summary>UI language at connect time, sent as `?lang=`. It has to be on
    /// the URL rather than a message after connect: the agent speaks first, so
    /// anything sent later arrives after it has already greeted the visitor in
    /// the wrong language.</summary>
    private readonly string _lang;
    private readonly SemaphoreSlim _sendLock = new(1, 1);
    private CancellationTokenSource? _cts;
    private Task? _runTask;
    private ClientWebSocket? _activeWs;

    public ConnectionState State { get; private set; } = ConnectionState.Disconnected;

    // Inbound events (raised on the receive thread; UI consumers must marshal to UI thread).
    public event Action<byte[]>? AudioReceived;
    public event Action<TranscriptMessage>? TranscriptReceived;
    public event Action<NavigateMessage>? NavigateReceived;
    public event Action<MurojatPreviewMessage>? MurojatPreviewReceived;
    public event Action<MurojatSubmittedMessage>? MurojatSubmittedReceived;
    public event Action<ScheduleMessage>? ScheduleReceived;
    public event Action<GroupChoicesMessage>? GroupChoicesReceived;
    public event Action<DirectionsMessage>? DirectionsReceived;
    public event Action<DirectionMessage>? DirectionReceived;
    public event Action<CoursesMessage>? CoursesReceived;
    public event Action<CourseGroupsMessage>? CourseGroupsReceived;
    public event Action<BooksMessage>? BooksReceived;
    public event Action<BookSectionsMessage>? BookSectionsReceived;
    public event Action<LeadershipMessage>? LeadershipReceived;
    public event Action<ReceptionPreviewMessage>? ReceptionPreviewReceived;
    public event Action<ReceptionSubmittedMessage>? ReceptionSubmittedReceived;
    public event Action<InfoCardMessage>? InfoCardReceived;
    public event Action? AudioDoneReceived;
    public event Action<ServerErrorMessage>? ErrorReceived;
    public event Action<ConnectionState>? StateChanged;

    /// <summary>Fires when the WS upgrade is rejected with HTTP 401/403, i.e.
    /// the device was revoked or the key is invalid. Caller should surface a
    /// "this device needs to be re-enrolled" UI instead of a transient offline overlay.</summary>
    public event Action? Unauthorized;

    public KioskClient(string backendUrl, string deviceId, string menu, string lang)
    {
        _backendUrl = backendUrl;
        _deviceId = deviceId;
        _menu = menu;
        _lang = lang;
    }

    public void Start()
    {
        if (_runTask is not null) return;
        _cts = new CancellationTokenSource();
        _runTask = Task.Run(() => RunLoop(_cts.Token));
    }

    public async ValueTask DisposeAsync()
    {
        _cts?.Cancel();
        if (_runTask is not null)
        {
            try { await _runTask.ConfigureAwait(false); } catch { }
        }
        _activeWs?.Dispose();
        _sendLock.Dispose();
    }

    /// <summary>
    /// Sends a 16 kHz Int16 LE mono PCM frame. Returns false if the WS isn't currently open;
    /// callers may drop the frame or buffer their own.
    /// </summary>
    public async Task<bool> SendAudioAsync(ReadOnlyMemory<byte> pcm, CancellationToken ct = default)
    {
        var ws = _activeWs;
        if (ws is null || ws.State != WebSocketState.Open) return false;
        await _sendLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (ws.State != WebSocketState.Open) return false;
            await ws.SendAsync(pcm, WebSocketMessageType.Binary, endOfMessage: true, ct)
                    .ConfigureAwait(false);
            return true;
        }
        catch
        {
            return false;
        }
        finally
        {
            _sendLock.Release();
        }
    }

    /// <summary>Manual VAD: signal that the user just started speaking (Gemini opens a turn).</summary>
    public Task<bool> SendTurnStartAsync(CancellationToken ct = default) =>
        SendJsonAsync("{\"type\":\"turn_start\"}", ct);

    /// <summary>Manual VAD: signal that the user just finished speaking (Gemini processes + responds).</summary>
    public Task<bool> SendTurnEndAsync(CancellationToken ct = default) =>
        SendJsonAsync("{\"type\":\"turn_end\"}", ct);

    /// <summary>Tell the backend which UI language the visitor is currently
    /// using. The backend pins this to the session and uses it at receipt-
    /// render time so the printed talon matches the language the visitor
    /// interacted with. Send once on connect + whenever language changes.
    /// `language` must be "uz", "kk", "ru" or "en" — the backend's allow-list.
/// The backend also re-pins the agent's speaking language on receipt.</summary>
    public Task<bool> SendUiLanguageAsync(string language, CancellationToken ct = default)
    {
        // "en" was missing from this list, so every English session was
        // silently rewritten to Karakalpak. Default is uz, matching the kiosk's
        // own default language.
        var safe = (language ?? "").Trim().ToLowerInvariant();
        if (safe != "kk" && safe != "uz" && safe != "ru" && safe != "en") safe = "kk";
        var json = "{\"type\":\"ui_language\",\"language\":\"" + safe + "\"}";
        return SendJsonAsync(json, ct);
    }

    /// <summary>Tell the backend where the visitor has got to by touch, so the
    /// agent stops asking for things already on their screen. Short free text:
    /// each one becomes a turn in the model's context, so callers send it on
    /// level changes only, never per tap.</summary>
    public Task<bool> SendUiStateAsync(string where, CancellationToken ct = default)
    {
        var clean = (where ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"")
            .Replace("\n", " ").Replace("\r", " ");
        if (clean.Length > 200) clean = clean[..200];
        var json = "{\"type\":\"ui_state\",\"where\":\"" + clean + "\"}";
        return SendJsonAsync(json, ct);
    }

    /// <summary>Forward arbitrary text to Gemini as a user turn — used by the
    /// voice-preview confirm/reject buttons so the agent reacts as if the
    /// visitor said the word out loud. Backend wraps it with turnComplete
    /// so Gemini closes the turn and replies.</summary>
    public Task<bool> SendUserTextAsync(string text, CancellationToken ct = default)
    {
        var clean = (text ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"")
            .Replace("\n", " ").Replace("\r", " ");
        var json = "{\"type\":\"user_text\",\"text\":\"" + clean + "\"}";
        return SendJsonAsync(json, ct);
    }

    private async Task<bool> SendJsonAsync(string json, CancellationToken ct)
    {
        var ws = _activeWs;
        if (ws is null || ws.State != WebSocketState.Open) return false;
        var bytes = Encoding.UTF8.GetBytes(json);
        await _sendLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (ws.State != WebSocketState.Open) return false;
            await ws.SendAsync(bytes, WebSocketMessageType.Text, endOfMessage: true, ct)
                    .ConfigureAwait(false);
            return true;
        }
        catch { return false; }
        finally { _sendLock.Release(); }
    }

    private async Task RunLoop(CancellationToken ct)
    {
        var attempt = 0;
        while (!ct.IsCancellationRequested)
        {
            SetState(attempt == 0 ? ConnectionState.Connecting : ConnectionState.Reconnecting);
            ClientWebSocket? ws = null;
            try
            {
                ws = new ClientWebSocket();
                // Same TLS pin rule as HttpClient — wss:// connections must
                // present the baked leaf cert SHA-256 in production.
                ws.Options.RemoteCertificateValidationCallback =
                    (sender, cert, chain, errors) =>
                        PinnedHttpClient.ValidateRemoteCertificate(
                            new Uri(HttpToWs(_backendUrl)),
                            cert as X509Certificate2,
                            chain,
                            errors);

                // Signed-nonce auth: fetch fresh challenge, sign with TPM key,
                // set as header on the upgrade request. The server validates
                // pre-accept and closes 1008 on any failure.
                var authHeader = await SignedHttpClient
                    .BuildAuthHeaderAsync(_backendUrl, _deviceId, ct)
                    .ConfigureAwait(false);
                ws.Options.SetRequestHeader("X-Kiosk-Auth", authHeader);
                var wsUri = new Uri(
                    HttpToWs(_backendUrl)
                    + "/ws/kiosk/voice?menu="
                    + Uri.EscapeDataString(_menu)
                    + "&lang="
                    + Uri.EscapeDataString(_lang));
                await ws.ConnectAsync(wsUri, ct).ConfigureAwait(false);

                _activeWs = ws;
                SetState(ConnectionState.Connected);
                attempt = 0;

                await ReceiveLoop(ws, ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                // 401/403 on the WS upgrade = device key revoked or unknown.
                // .NET surfaces this as a WebSocketException whose message
                // includes the HTTP status, e.g. "...status code '403'...".
                var msg = ex.Message ?? "";
                if (msg.Contains("'403'") || msg.Contains("'401'"))
                {
                    Unauthorized?.Invoke();
                    // Hold the loop in a long sleep — pointless to retry until
                    // the operator re-enrolls the kiosk. Cancellation still wakes us.
                    try { await Task.Delay(TimeSpan.FromMinutes(5), ct).ConfigureAwait(false); }
                    catch (OperationCanceledException) { break; }
                    continue;
                }
                // network / other transient — fall through to normal backoff.
            }
            finally
            {
                _activeWs = null;
                ws?.Dispose();
                SetState(ConnectionState.Disconnected);
            }

            if (ct.IsCancellationRequested) break;

            var delay = ReconnectDelaysMs[Math.Min(attempt, ReconnectDelaysMs.Length - 1)];
            attempt++;
            try { await Task.Delay(delay, ct).ConfigureAwait(false); }
            catch (OperationCanceledException) { break; }
        }
    }

    private async Task ReceiveLoop(ClientWebSocket ws, CancellationToken ct)
    {
        var buffer = new byte[16 * 1024];
        using var msg = new MemoryStream();
        while (!ct.IsCancellationRequested && ws.State == WebSocketState.Open)
        {
            msg.SetLength(0);
            WebSocketReceiveResult result;
            do
            {
                result = await ws.ReceiveAsync(buffer, ct).ConfigureAwait(false);
                if (result.MessageType == WebSocketMessageType.Close) return;
                msg.Write(buffer, 0, result.Count);
            } while (!result.EndOfMessage);

            var payload = msg.ToArray();
            if (result.MessageType == WebSocketMessageType.Binary)
                AudioReceived?.Invoke(payload);
            else
                DispatchJson(Encoding.UTF8.GetString(payload));
        }
    }

    private void DispatchJson(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            if (!doc.RootElement.TryGetProperty("type", out var typeProp)) return;
            var type = typeProp.GetString();
            switch (type)
            {
                case "transcript":
                    var t = JsonSerializer.Deserialize(json, KioskJsonContext.Default.TranscriptMessage);
                    if (t is not null) TranscriptReceived?.Invoke(t);
                    break;
                case "navigate":
                    var n = JsonSerializer.Deserialize(json, KioskJsonContext.Default.NavigateMessage);
                    if (n is not null) NavigateReceived?.Invoke(n);
                    break;
                case "murojat_preview":
                    var p = JsonSerializer.Deserialize(json, KioskJsonContext.Default.MurojatPreviewMessage);
                    if (p is not null) MurojatPreviewReceived?.Invoke(p);
                    break;
                case "murojat_submitted":
                    var s = JsonSerializer.Deserialize(json, KioskJsonContext.Default.MurojatSubmittedMessage);
                    if (s is not null) MurojatSubmittedReceived?.Invoke(s);
                    break;
                case "show_schedule":
                    var sch = JsonSerializer.Deserialize(json, KioskJsonContext.Default.ScheduleMessage);
                    if (sch is not null) ScheduleReceived?.Invoke(sch);
                    break;
                case "show_group_choices":
                    var gc = JsonSerializer.Deserialize(json, KioskJsonContext.Default.GroupChoicesMessage);
                    if (gc is not null) GroupChoicesReceived?.Invoke(gc);
                    break;
                case "show_directions":
                    var ds = JsonSerializer.Deserialize(json, KioskJsonContext.Default.DirectionsMessage);
                    if (ds is not null) DirectionsReceived?.Invoke(ds);
                    break;
                case "show_direction":
                    var d1 = JsonSerializer.Deserialize(json, KioskJsonContext.Default.DirectionMessage);
                    if (d1 is not null) DirectionReceived?.Invoke(d1);
                    break;
                case "show_courses":
                    var cs = JsonSerializer.Deserialize(json, KioskJsonContext.Default.CoursesMessage);
                    if (cs is not null) CoursesReceived?.Invoke(cs);
                    break;
                case "show_course_groups":
                    var cg = JsonSerializer.Deserialize(json, KioskJsonContext.Default.CourseGroupsMessage);
                    if (cg is not null) CourseGroupsReceived?.Invoke(cg);
                    break;
                case "show_books":
                    var bk = JsonSerializer.Deserialize(json, KioskJsonContext.Default.BooksMessage);
                    if (bk is not null) BooksReceived?.Invoke(bk);
                    break;
                case "show_sections":
                    var bs = JsonSerializer.Deserialize(json, KioskJsonContext.Default.BookSectionsMessage);
                    if (bs is not null) BookSectionsReceived?.Invoke(bs);
                    break;
                case "show_leadership":
                    var ld = JsonSerializer.Deserialize(json, KioskJsonContext.Default.LeadershipMessage);
                    if (ld is not null) LeadershipReceived?.Invoke(ld);
                    break;
                case "reception_preview":
                    var rp = JsonSerializer.Deserialize(json, KioskJsonContext.Default.ReceptionPreviewMessage);
                    if (rp is not null) ReceptionPreviewReceived?.Invoke(rp);
                    break;
                case "reception_submitted":
                    var rs = JsonSerializer.Deserialize(json, KioskJsonContext.Default.ReceptionSubmittedMessage);
                    if (rs is not null) ReceptionSubmittedReceived?.Invoke(rs);
                    break;
                case "show_info_card":
                    var ic = JsonSerializer.Deserialize(json, KioskJsonContext.Default.InfoCardMessage);
                    if (ic is not null) InfoCardReceived?.Invoke(ic);
                    break;
                case "audio_done":
                    AudioDoneReceived?.Invoke();
                    break;
                case "error":
                    var e = JsonSerializer.Deserialize(json, KioskJsonContext.Default.ServerErrorMessage);
                    if (e is not null) ErrorReceived?.Invoke(e);
                    break;
                case "disconnected":
                    // Server is closing — receive loop will exit on next iteration.
                    break;
            }
        }
        catch
        {
            // Malformed payload from server; ignore.
        }
    }

    private void SetState(ConnectionState s)
    {
        if (s == State) return;
        State = s;
        StateChanged?.Invoke(s);
    }

    private static string HttpToWs(string url) =>
        url.StartsWith("https://", StringComparison.OrdinalIgnoreCase) ? "wss://" + url.Substring("https://".Length)
        : url.StartsWith("http://", StringComparison.OrdinalIgnoreCase)  ? "ws://"  + url.Substring("http://".Length)
        : url;
}
