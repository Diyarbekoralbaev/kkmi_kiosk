"""GET /health/deep — deep dependency checks for the status page.

Polled by Gatus over the docker network (http://backend:8000/health/deep).
Each component is checked independently with its own timeout; one failing
check never breaks the others or the endpoint as a whole. The response
carries NO secrets — only a component name, ok/error-type, and small
counters — but it still reveals infra topology, so when HEALTH_DEEP_TOKEN
is set (prod) the endpoint requires a matching X-Health-Token header.
Ungated in dev (token empty).

This is the check that today's incident showed `/health` could not catch:
`/health` returned 200 while the Gemini relay WS was dead. Here we actually
exercise the relay handshake, the telegram relay, redis, disk, and TLS.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import ssl
import time
from datetime import datetime, timedelta, timezone

import httpx
import websockets
from fastapi import APIRouter, Header, Response, status
from sqlalchemy import func, select, text

from ..core.config import get_settings
from ..core.deps import DbSession
from ..domain.device import Device

router = APIRouter(tags=["health"])

# A kiosk counts as "online" if it checked in within this window.
_KIOSK_ONLINE_WINDOW_MIN = 5
# Public host whose leaf cert expiry we sample for the TLS check.
_TLS_HOST = "kenes-api.kioska.dbc.uz"
# Disk fullness above this fraction trips the disk check.
_DISK_WARN_PCT = 85.0
# Direct (no-relay) Gemini Live endpoint — mirrors ai/gemini_live.py.
_GEMINI_ENDPOINT = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)

# Components that count toward the overall status. `kiosks` is intentionally
# excluded — it is informational ("last online"), never an outage signal.
_CRITICAL = ("postgres", "redis", "gemini", "telegram", "tls", "disk")

# The status page renders one row per component, so Gatus polls this endpoint
# once per component (≈7×). Without caching that would fire 7 Gemini WS
# handshakes every interval. Cache the full result briefly + a lock so a burst
# of pollers triggers at most one real run per TTL.
_CACHE_TTL_SECONDS = 30.0
_cache: dict = {"ts": 0.0, "data": None}
_cache_lock = asyncio.Lock()


async def _check_postgres(session) -> dict:
    t = time.perf_counter()
    try:
        await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=5)
        return {"ok": True, "latency_ms": round((time.perf_counter() - t) * 1000)}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


async def _check_redis() -> dict:
    import redis.asyncio as aioredis

    t = time.perf_counter()
    r = None
    try:
        r = aioredis.from_url(get_settings().redis_url)
        await asyncio.wait_for(r.ping(), timeout=5)
        return {"ok": True, "latency_ms": round((time.perf_counter() - t) * 1000)}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass


async def _check_gemini() -> dict:
    """Open the Gemini Live WS (through the relay if configured) and close it
    immediately — no model turn, so it's cheap and doesn't touch quota. This
    is the exact path that silently broke today."""
    s = get_settings()
    key = s.google_api_key.get_secret_value() if s.google_api_key else ""
    if not key:
        return {"ok": False, "error": "no_api_key"}
    relay = os.environ.get("GEMINI_RELAY_URL", "").rstrip("/")
    token = os.environ.get("GEMINI_RELAY_TOKEN", "")
    headers = None
    if relay and token:
        if relay.startswith("https://"):
            relay = "wss://" + relay[len("https://"):]
        elif relay.startswith("http://"):
            relay = "ws://" + relay[len("http://"):]
        url = (
            f"{relay}/ws/google.ai.generativelanguage.v1beta."
            f"GenerativeService.BidiGenerateContent?key={key}"
        )
        headers = {"X-Kiosk-Auth": token}
    else:
        url = f"{_GEMINI_ENDPOINT}?key={key}"
    t = time.perf_counter()
    try:
        ws = await asyncio.wait_for(
            websockets.connect(
                url, subprotocols=["gemini-live"], additional_headers=headers
            ),
            timeout=8,
        )
        await ws.close()
        return {
            "ok": True,
            "latency_ms": round((time.perf_counter() - t) * 1000),
            "via": "relay" if headers else "direct",
        }
    except (asyncio.TimeoutError, TimeoutError):
        return {"ok": False, "error": "ws_handshake_timeout"}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


async def _check_telegram() -> dict:
    """getMe through the same relay path the bot uses. Unconfigured token =
    not a failure (dev/staging) — reported ok with a note."""
    s = get_settings()
    token = s.telegram_bot_token.get_secret_value() if s.telegram_bot_token else ""
    if not token:
        return {"ok": True, "note": "disabled"}
    base = (s.telegram_api_base or "https://api.telegram.org").rstrip("/")
    relay_token = (
        s.telegram_relay_token.get_secret_value() if s.telegram_relay_token else ""
    )
    headers = {"X-Relay-Auth": relay_token} if relay_token else None
    t = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{base}/bot{token}/getMe", headers=headers)
        if r.status_code == 200 and r.json().get("ok") is True:
            return {"ok": True, "latency_ms": round((time.perf_counter() - t) * 1000)}
        return {"ok": False, "error": f"status_{r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def _check_tls_sync(host: str, port: int = 443) -> dict:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=6) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
        # notAfter format: 'May 18 09:08:10 2026 GMT'
        exp = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
        days = (exp - datetime.now(timezone.utc)).days
        return {"ok": days > 14, "days_left": days}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


async def _check_tls() -> dict:
    return await asyncio.to_thread(_check_tls_sync, _TLS_HOST)


def _check_disk_sync(path: str = "/") -> dict:
    try:
        u = shutil.disk_usage(path)
        pct = round(u.used / u.total * 100, 1)
        return {"ok": pct < _DISK_WARN_PCT, "used_pct": pct, "free_gb": round(u.free / 1e9, 1)}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


async def _check_disk() -> dict:
    return await asyncio.to_thread(_check_disk_sync, "/")


async def _check_backup() -> dict:
    """Reads the last-success epoch the nightly restic→R2 backup writes to
    redis (key `kiosk:last_backup_ts`). Missing or older than ~26h (one
    missed night) = the backup silently stopped — the exact 'we didn't know'
    failure class this whole status page exists to prevent."""
    import redis.asyncio as aioredis

    r = None
    try:
        r = aioredis.from_url(get_settings().redis_url)
        raw = await asyncio.wait_for(r.get("kiosk:last_backup_ts"), timeout=5)
        if raw is None:
            return {"ok": False, "error": "no_backup_recorded"}
        age_h = round((time.time() - int(raw)) / 3600, 1)
        return {"ok": age_h < 26, "age_hours": age_h}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass


async def _check_kiosks(session) -> dict:
    """Informational only — never flips overall status. Counts active devices
    that checked in within the online window."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_KIOSK_ONLINE_WINDOW_MIN)
        total = (
            await session.execute(
                select(func.count()).select_from(Device).where(Device.status == "active")
            )
        ).scalar() or 0
        online = (
            await session.execute(
                select(func.count())
                .select_from(Device)
                .where(Device.status == "active", Device.last_seen_at >= cutoff)
            )
        ).scalar() or 0
        return {"ok": True, "online": int(online), "total": int(total)}
    except Exception as e:
        # Still ok=True: a kiosk-count query error must not page anyone.
        return {"ok": True, "error": type(e).__name__, "online": 0, "total": 0}


@router.get("/health/deep")
async def health_deep(
    session: DbSession,
    response: Response,
    x_health_token: str | None = Header(default=None),
) -> dict:
    s = get_settings()
    expected = s.health_deep_token.get_secret_value() if s.health_deep_token else ""
    if expected and x_health_token != expected:
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return {"status": "unauthorized"}

    now = time.monotonic()
    if _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL_SECONDS:
        return _cache["data"]

    async with _cache_lock:
        # Re-check inside the lock: a concurrent caller may have just refreshed.
        now = time.monotonic()
        if _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL_SECONDS:
            return _cache["data"]

        # Session-bound checks run sequentially — an AsyncSession is NOT safe
        # to use from two coroutines at once. They're sub-millisecond anyway.
        postgres = await _check_postgres(session)
        kiosks = await _check_kiosks(session)
        # Independent network checks run concurrently.
        redis_r, gemini_r, telegram_r, tls_r, disk_r, backup_r = await asyncio.gather(
            _check_redis(),
            _check_gemini(),
            _check_telegram(),
            _check_tls(),
            _check_disk(),
            _check_backup(),
        )
        components = {
            "postgres": postgres,
            "redis": redis_r,
            "gemini": gemini_r,
            "telegram": telegram_r,
            "tls": tls_r,
            "disk": disk_r,
            "backup": backup_r,
            "kiosks": kiosks,
        }
        overall = "ok" if all(components[c].get("ok") for c in _CRITICAL) else "degraded"
        result = {"status": overall, "components": components}
        _cache["ts"] = time.monotonic()
        _cache["data"] = result
        return result
