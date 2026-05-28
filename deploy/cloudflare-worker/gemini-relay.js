/**
 * Gemini Live WSS relay — Cloudflare Worker
 *
 * Bypasses the Moscow → Frankfurt HTTP CONNECT proxy chain entirely.
 * Backend connects to this Worker via plain wss:// (no proxy), Worker
 * forwards to Gemini Live API at Cloudflare's edge.
 *
 * Auth: backend MUST send `X-Kiosk-Auth: <RELAY_TOKEN>` header (a Worker
 * secret). Without it the Worker rejects 401 — keeps our Gemini API key
 * (which travels in the URL query string) from being abused.
 *
 * Health: a plain GET (no Upgrade header) returns 200 "ok" — used by
 * the backend to probe Worker availability.
 *
 * Placement: enable Smart Placement → Service mode with hostname
 * `generativelanguage.googleapis.com` so the Worker runs near Google's
 * edge (US) and egresses from a non-blocked region.
 */
export default {
  async fetch(request, env) {
    // 1. Auth gate — Worker secret RELAY_TOKEN must match
    const auth = request.headers.get('X-Kiosk-Auth');
    if (!env.RELAY_TOKEN || auth !== env.RELAY_TOKEN) {
      return new Response('Unauthorized\n', { status: 401 });
    }

    // 2. Health check — non-WS GET
    if (request.headers.get('Upgrade')?.toLowerCase() !== 'websocket') {
      return new Response('ok\n', { status: 200 });
    }

    // 3. Build upstream URL — preserve path + query (the ?key=... goes through unchanged)
    // Workers' fetch() API requires https:// (not wss://) for the upstream URL;
    // the Upgrade header on the request body is what triggers the WS handshake.
    const url = new URL(request.url);
    const upstreamUrl = 'https://generativelanguage.googleapis.com' + url.pathname + url.search;

    // 4. Forward WS-relevant headers only. The Workers runtime regenerates
    //    Sec-WebSocket-Key, Sec-WebSocket-Version, and Sec-WebSocket-Extensions
    //    automatically — forwarding the client's values has no effect, so we
    //    only carry the subprotocol negotiation through.
    const fwd = new Headers();
    fwd.set('Upgrade', 'websocket');
    fwd.set('Connection', 'Upgrade');
    const subproto = request.headers.get('Sec-WebSocket-Protocol');
    if (subproto) fwd.set('Sec-WebSocket-Protocol', subproto);

    // 5. Open upstream WS
    let upstream;
    try {
      upstream = await fetch(upstreamUrl, { headers: fwd });
    } catch (e) {
      return new Response('upstream fetch error: ' + (e?.message || e), { status: 502 });
    }
    if (!upstream.webSocket) {
      return new Response('upstream did not upgrade (status ' + upstream.status + ')', { status: 502 });
    }

    // 6. Create downstream WS pair (client-facing).
    //    binaryType MUST be assigned BEFORE accept() per CF docs — otherwise
    //    the first frames after accept may dispatch as Blob (default since
    //    the 2026-03-17 compatibility date).
    //    Note: accept({ allowHalfOpen: true }) is documented at
    //    developers.cloudflare.com/workers/runtime-apis/websockets but the
    //    @cloudflare/workers-types definition lags and rejects the argument
    //    at compile time, so we stick with no-arg accept() — duplicate
    //    close() calls are silently ignored by the runtime, same behavior.
    upstream.webSocket.binaryType = 'arraybuffer';
    upstream.webSocket.accept();

    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    server.binaryType = 'arraybuffer';
    server.accept();

    // 7. Bidirectional relay with mutual close
    const closeUpstream = (code, reason) => {
      try { upstream.webSocket.close(code, reason); } catch (_) {}
    };
    const closeServer = (code, reason) => {
      try { server.close(code, reason); } catch (_) {}
    };

    // Defensive: if a Blob still slips through (e.g. compat date < 2026-03-17,
    // or runtime change), convert to ArrayBuffer before forwarding so audio
    // frames don't get .toString()'d to "[object Blob]" by WebSocket.send.
    const relay = async (dst, data) => {
      if (typeof Blob !== 'undefined' && data instanceof Blob) {
        data = await data.arrayBuffer();
      }
      dst.send(data);
    };
    server.addEventListener('message', async (e) => {
      try { await relay(upstream.webSocket, e.data); }
      catch (_) { closeUpstream(1011, 'relay send fail'); closeServer(1011, 'relay send fail'); }
    });
    upstream.webSocket.addEventListener('message', async (e) => {
      try { await relay(server, e.data); }
      catch (_) { closeUpstream(1011, 'relay send fail'); closeServer(1011, 'relay send fail'); }
    });

    server.addEventListener('close', (e) => closeUpstream(e.code || 1000, e.reason || ''));
    upstream.webSocket.addEventListener('close', (e) => closeServer(e.code || 1000, e.reason || ''));

    server.addEventListener('error', () => closeUpstream(1011, 'client error'));
    upstream.webSocket.addEventListener('error', () => closeServer(1011, 'upstream error'));

    // 8. Return 101 with the client end of the pair + propagate selected subprotocol.
    //    Workers does NOT auto-echo Sec-WebSocket-Protocol from upstream into
    //    the downstream response — we must set it explicitly so the kiosk
    //    side completes subprotocol negotiation cleanly.
    const respHeaders = new Headers();
    const acceptedSubproto = upstream.headers.get('Sec-WebSocket-Protocol');
    if (acceptedSubproto) respHeaders.set('Sec-WebSocket-Protocol', acceptedSubproto);
    return new Response(null, {
      status: 101,
      webSocket: client,
      headers: respHeaders,
    });
  },
};
