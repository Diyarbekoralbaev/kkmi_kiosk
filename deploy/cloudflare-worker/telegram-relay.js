/**
 * Telegram Bot API relay — Cloudflare Worker
 *
 * Bypasses Moscow → api.telegram.org outbound block. Backend POSTs to
 * this Worker, Worker forwards verbatim to https://api.telegram.org
 * preserving method + path + query + body, and streams the upstream
 * response back unchanged.
 *
 * Bot token is NOT stored in the Worker — it travels in the request
 * path (`/bot{TOKEN}/sendMessage`) the same way the backend would call
 * api.telegram.org directly. The Worker is a dumb HTTP forwarder.
 *
 * Auth: backend MUST send `X-Relay-Auth: <RELAY_TOKEN>` header (a
 * Worker secret). Without it the Worker rejects 401 — stops rando
 * traffic from running up our CF bill.
 *
 * Health: GET / (or any path) without X-Relay-Auth → 401. With auth
 * but path empty/`/health` → 200 "ok". Used by backend liveness probe.
 *
 * Placement: no Smart Placement needed — api.telegram.org is reachable
 * from every CF colo, no geo-egress trick required (unlike Gemini).
 *
 * Pinned compatibility_date 2026-03-12 (per past CF dated-default flap;
 * keeps the Worker on known-good Request/Response semantics).
 */
export default {
  async fetch(request, env) {
    // 1. Auth gate — Worker secret RELAY_TOKEN must match. Done before
    //    anything else so unauthenticated traffic doesn't even reach
    //    the URL parser.
    const auth = request.headers.get('X-Relay-Auth');
    if (!env.RELAY_TOKEN || auth !== env.RELAY_TOKEN) {
      return new Response('Unauthorized\n', { status: 401 });
    }

    const url = new URL(request.url);

    // 2. Health probe — backend pings these to confirm the Worker is up
    //    before flipping TELEGRAM_API_BASE. Returns 200 "ok" so a simple
    //    `httpx.get(url + "/health")` succeeds.
    if (url.pathname === '/' || url.pathname === '/health') {
      return new Response('ok\n', { status: 200 });
    }

    // 3. Build upstream URL — preserve the entire path + query string.
    //    The backend calls e.g. `/bot8801.../sendMessage?...` and that
    //    must reach api.telegram.org unchanged.
    const upstreamUrl = 'https://api.telegram.org' + url.pathname + url.search;

    // 4. Forward headers, stripping ones that don't belong upstream:
    //    - X-Relay-Auth: our own gate, Telegram doesn't care
    //    - Host: CF sets this automatically for the upstream fetch
    //    - CF-*: Cloudflare-internal metadata
    const fwd = new Headers(request.headers);
    fwd.delete('X-Relay-Auth');
    fwd.delete('Host');
    for (const k of [...fwd.keys()]) {
      if (k.toLowerCase().startsWith('cf-')) fwd.delete(k);
    }

    // 5. Forward. `redirect: 'manual'` so a Telegram redirect (rare)
    //    propagates to the backend instead of being silently chased
    //    inside the Worker.
    try {
      const upstream = await fetch(upstreamUrl, {
        method: request.method,
        headers: fwd,
        body:
          request.method === 'GET' || request.method === 'HEAD'
            ? undefined
            : request.body,
        redirect: 'manual',
      });
      // Stream the upstream body straight back. Headers are copied
      // through so the backend sees the same Content-Type, Retry-After,
      // etc. as a direct call would surface.
      return new Response(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers: upstream.headers,
      });
    } catch (e) {
      return new Response(
        'upstream fetch error: ' + (e?.message || String(e)) + '\n',
        { status: 502 },
      );
    }
  },
};
