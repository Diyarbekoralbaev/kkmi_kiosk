"""Per-org weather widget — Open-Meteo (free, no API key).

Why Open-Meteo: zero-key onboarding, no per-tenant secret management,
generous free tier (~10k req/day). Backend caches per-org for 15 min so
each kiosk's heartbeat doesn't fan out to the upstream — at 30s heartbeat
interval × 17 districts × 2 calls/min = ~2k req/min uncached → would hit
rate limits. Cache keeps it well under 1 req/15 min per org.

Returned shape (also the heartbeat field shape):
    {"city": "Нөкис", "temp_c": 28, "fetched_at": "2026-05-12T15:43:00Z"}

Returns None when:
  - Org has no latitude/longitude/city_name configured
  - Upstream is unreachable AND the last successful fetch was >2 h ago

A stale cached value is preferred over None when upstream blips — the
kiosk header just hides the row when value is None, which is uglier than
a slightly-out-of-date number. But we cap "stale" at 2 h: longer than
that and we'd rather show nothing than a clearly-wrong temperature.

Open-Meteo is reachable directly from every region we've shipped to so
far (Servercore Tashkent, MSK). No proxy plumbing — keep it simple. If
a future region geo-blocks Open-Meteo, add a per-call proxy param here
similar to gemini_live.py's GEMINI_PROXY.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.organization import Organization

logger = structlog.get_logger(__name__)

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_CACHE_TTL_SECONDS = 15 * 60
_STALE_MAX_SECONDS = 2 * 60 * 60
_FETCH_TIMEOUT_SECONDS = 5.0


@dataclass
class _CacheEntry:
    fetched_at: float
    payload: dict
    inflight: asyncio.Lock = field(default_factory=asyncio.Lock)


# In-process cache. Module-level singleton — survives across heartbeat
# requests in the same worker. With uvicorn workers > 1 each gets its own
# copy; that's fine, just means up to N×rate-limit hits per TTL.
_cache: dict[uuid.UUID, _CacheEntry] = {}
_cache_lock = asyncio.Lock()


def _proxy() -> str | None:
    """Returns None today — Open-Meteo is reachable direct from every
    region we ship to. Kept as a hook so a future per-region proxy is
    a one-line change here, not a re-plumb of the whole module."""
    return None


async def get_weather(session: AsyncSession, org_id: uuid.UUID) -> dict | None:
    """Resolve the org's geo, return a fresh-or-cached weather dict.
    None if the org has no geo set, or every fetch attempt has failed AND
    we have no cache fresher than _STALE_MAX_SECONDS."""
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None or org.latitude is None or org.longitude is None or not org.city_name:
        return None

    now = time.monotonic()
    async with _cache_lock:
        entry = _cache.get(org_id)
    if entry is not None and (now - entry.fetched_at) < _CACHE_TTL_SECONDS:
        return entry.payload

    # Serialize concurrent refreshes for the same org so we don't dogpile.
    if entry is None:
        async with _cache_lock:
            entry = _cache.get(org_id)
            if entry is None:
                entry = _CacheEntry(fetched_at=0.0, payload={})
                _cache[org_id] = entry

    async with entry.inflight:
        # Re-check after acquiring — another coroutine may have refreshed.
        if (time.monotonic() - entry.fetched_at) < _CACHE_TTL_SECONDS and entry.payload:
            return entry.payload

        proxy = _proxy()
        try:
            t0 = time.monotonic()
            async with httpx.AsyncClient(
                timeout=_FETCH_TIMEOUT_SECONDS,
                proxy=proxy,
            ) as client:
                resp = await client.get(
                    _OPEN_METEO_URL,
                    params={
                        "latitude": org.latitude,
                        "longitude": org.longitude,
                        "current": "temperature_2m",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            temp = data.get("current", {}).get("temperature_2m")
            if temp is None:
                raise ValueError("no current.temperature_2m in response")
            payload = {
                "city": org.city_name,
                "temp_c": int(round(float(temp))),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            entry.payload = payload
            entry.fetched_at = time.monotonic()
            logger.info(
                "weather_fetch_ok",
                org_id=str(org_id),
                city=org.city_name,
                temp_c=payload["temp_c"],
                elapsed_ms=elapsed_ms,
                via_proxy=bool(proxy),
            )
            return payload
        except Exception as e:
            stale_age_s = (time.monotonic() - entry.fetched_at) if entry.payload else None
            logger.warning(
                "weather_fetch_failed",
                org_id=str(org_id),
                error=str(e),
                via_proxy=bool(proxy),
                stale_age_s=int(stale_age_s) if stale_age_s is not None else None,
            )
            # Stale-cache fallback, capped at 2h. Beyond that, returning
            # the cached value is worse UX than hiding the widget — the
            # displayed temperature would be from yesterday.
            if entry.payload and stale_age_s is not None and stale_age_s < _STALE_MAX_SECONDS:
                return entry.payload
            return None
