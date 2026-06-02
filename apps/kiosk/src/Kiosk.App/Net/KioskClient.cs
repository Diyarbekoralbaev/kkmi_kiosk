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
    private readonly SemaphoreSlim _sendLock = new(1, 1);
    private CancellationTokenSource? _cts;
    private Task? _runTask;
    private ClientWebSocket? _activeWs;

    public ConnectionState State { get; private set; } = ConnectionState.Disconnected;

    // Inbound events (raised on the receive thread; UI consumers must marshal to UI thread).
    public event Action<byte[]>? AudioReceived;
    public event Action<TranscriptMessage>? TranscriptReceived;
    public event Action<NavigateMessage>? NavigateReceived;
    public event Action<ApplicationPreviewMessage>? PreviewReceived;
    public event Action<ApplicationSubmittedMessage>? SubmittedReceived;
    public event Action<AppointmentProgressMessage>? AppointmentProgressReceived;
    public event Action<AppointmentPreviewMessage>? AppointmentPreviewReceived;
    public event Action<AppointmentSubmittedMessage>? AppointmentSubmittedReceived;
    public event Action<FeedbackPreviewMessage>? FeedbackPreviewReceived;
    public event Action<FeedbackSubmittedMessage>? FeedbackSubmittedReceived;
    public event Action? AudioDoneReceived;
    public event Action<ServerErrorMessage>? ErrorReceived;
    public event Action<ConnectionState>? StateChanged;

    /// <summary>Fires when the WS upgrade is rejected with HTTP 401/403, i.e.
    /// the device was revoked or the key is invalid. Caller should surface a
    /// "this device needs to be re-enrolled" UI instead of a transient offline overlay.</summary>
    public event Action? Unauthorized;

    public KioskClient(string backendUrl, string deviceId)
    {
        _backendUrl = backendUrl;
        _deviceId = deviceId;
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
    /// `language` must be "kk", "uz", or "ru" — the backend's allow-list.</summary>
    public Task<bool> SendUiLanguageAsync(string language, CancellationToken ct = default)
    {
        var safe = (language ?? "").Trim().ToLowerInvariant();
        if (safe != "kk" && safe != "uz" && safe != "ru") safe = "kk";
        var json = "{\"type\":\"ui_language\",\"language\":\"" + safe + "\"}";
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
                var wsUri = new Uri(HttpToWs(_backendUrl) + "/ws/kiosk/voice");
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
                case "application_preview":
                    var p = JsonSerializer.Deserialize(json, KioskJsonContext.Default.ApplicationPreviewMessage);
                    if (p is not null) PreviewReceived?.Invoke(p);
                    break;
                case "application_submitted":
                    var s = JsonSerializer.Deserialize(json, KioskJsonContext.Default.ApplicationSubmittedMessage);
                    if (s is not null) SubmittedReceived?.Invoke(s);
                    break;
                case "appointment_progress":
                    var apg = JsonSerializer.Deserialize(json, KioskJsonContext.Default.AppointmentProgressMessage);
                    if (apg is not null) AppointmentProgressReceived?.Invoke(apg);
                    break;
                case "appointment_preview":
                    var ap = JsonSerializer.Deserialize(json, KioskJsonContext.Default.AppointmentPreviewMessage);
                    if (ap is not null) AppointmentPreviewReceived?.Invoke(ap);
                    break;
                case "appointment_submitted":
                    var asm = JsonSerializer.Deserialize(json, KioskJsonContext.Default.AppointmentSubmittedMessage);
                    if (asm is not null) AppointmentSubmittedReceived?.Invoke(asm);
                    break;
                case "feedback_preview":
                    var fp = JsonSerializer.Deserialize(json, KioskJsonContext.Default.FeedbackPreviewMessage);
                    if (fp is not null) FeedbackPreviewReceived?.Invoke(fp);
                    break;
                case "feedback_submitted":
                    var fs = JsonSerializer.Deserialize(json, KioskJsonContext.Default.FeedbackSubmittedMessage);
                    if (fs is not null) FeedbackSubmittedReceived?.Invoke(fs);
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
