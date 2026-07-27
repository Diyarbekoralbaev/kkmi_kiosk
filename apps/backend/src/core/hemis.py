"""Read-only client for the institute's HEMIS REST API (student.kkmi.uz/rest).

Only the "1. Backend API" `/v1/data/*` list endpoints are used, plus the
unauthenticated `/v1/public/university-profile`. Every one of them returns the
same envelope:

    {"success": true, "error": null,
     "data": {"items": [...],
              "pagination": {"totalCount", "pageSize", "pageCount", "page"}},
     "code": 200}

`fetch_all` walks that pagination and hands back deduped items. The retry,
rate-limit and dedupe behaviour here mirrors the standalone fetch script that
was validated against the live API (114k schedule rows over 570 pages):

  - `limit=200` is the documented maximum.
  - Upstream allows 10 req/s; we stay at 6 and share one limiter process-wide,
    because tripping their limiter costs more than the throughput gains.
  - 429 / 5xx / connection resets are transient — the server drops parallel
    connections under load — so they get exponential backoff.
  - 401 / 403 are a token problem; retrying just burns quota, so they raise.
  - Pages are fetched concurrently and the DB can change mid-walk, so the same
    row can appear on two pages. Dedupe by id.

This module never writes to the DB — `hemis_sync` owns persistence.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import structlog

from .config import get_settings
from .errors import ServiceUnavailableError, UpstreamError

logger = structlog.get_logger(__name__)

PAGE_SIZE = 200
MAX_RETRY = 5


class _RateLimiter:
    """Process-wide floor on the interval between requests.

    Deliberately not a token bucket: a bucket would let a burst of workers fire
    N requests at once after an idle gap, which is exactly the shape that trips
    upstream's limiter at the start of a sync.
    """

    def __init__(self, per_second: float) -> None:
        self._interval = 1.0 / per_second
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._next < now:
                self._next = now
            delay = self._next - now
            self._next += self._interval
        if delay > 0:
            await asyncio.sleep(delay)


_limiter: _RateLimiter | None = None


def _get_limiter() -> _RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = _RateLimiter(get_settings().hemis_rate_limit)
    return _limiter


def is_configured() -> bool:
    s = get_settings()
    return bool(s.hemis_api_base and s.hemis_token.get_secret_value())


def _require_config() -> tuple[str, str]:
    s = get_settings()
    base = (s.hemis_api_base or "").rstrip("/")
    token = s.hemis_token.get_secret_value()
    if not base or not token:
        raise ServiceUnavailableError("hemis_not_configured")
    return base, token


def _client(base: str, token: str | None = None) -> httpx.AsyncClient:
    headers = {"Accept": "application/json", "User-Agent": "kkmi-kiosk/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(
        base_url=base, timeout=get_settings().hemis_timeout, headers=headers
    )


class _AuthRejectedError(Exception):
    """Token rejected — never worth retrying."""


async def _get_page(
    client: httpx.AsyncClient, path: str, params: dict[str, Any]
) -> dict[str, Any]:
    """One page, with backoff. Returns the envelope's `data` object."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRY):
        await _get_limiter().wait()
        try:
            r = await client.get(path, params=params)
            if r.status_code in (401, 403):
                raise _AuthRejectedError(f"status_{r.status_code}")
            r.raise_for_status()
            body = r.json()
            if not body.get("success"):
                raise RuntimeError(f"hemis_error: {body.get('error')}")
            return body.get("data") or {}
        except _AuthRejectedError:
            raise
        except Exception as e:
            last_exc = e
            if attempt < MAX_RETRY - 1:
                await asyncio.sleep(2**attempt)
    raise UpstreamError(cause=last_exc) from last_exc


async def fetch_all(
    resource: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Every item of a `/v1/data/<resource>` list endpoint, deduped by id.

    Page 1 is fetched first to learn the page count, then the rest run
    concurrently under the shared rate limiter. A page that still fails after
    its retries drops that page rather than the whole sync — the caller sees a
    short count and the next nightly run picks the rows back up.
    """
    base, token = _require_config()
    path = f"/v1/data/{resource}"
    query = {"limit": PAGE_SIZE, **(params or {})}

    async with _client(base, token) as client:
        first = await _get_page(client, path, {**query, "page": 1})
        pagination = first.get("pagination") or {}
        page_count = int(pagination.get("pageCount") or 1)
        total = int(pagination.get("totalCount") or 0)
        pages: list[list[dict[str, Any]]] = [first.get("items") or []]

        if page_count > 1:
            sem = asyncio.Semaphore(get_settings().hemis_concurrency)

            async def one(page: int) -> list[dict[str, Any]]:
                async with sem:
                    try:
                        data = await _get_page(client, path, {**query, "page": page})
                        return data.get("items") or []
                    except Exception as e:
                        logger.warning(
                            "hemis_page_failed",
                            resource=resource,
                            page=page,
                            error=str(e),
                            error_type=type(e).__name__,
                        )
                        return []

            pages.extend(
                await asyncio.gather(*(one(p) for p in range(2, page_count + 1)))
            )

    seen: set[Any] = set()
    items: list[dict[str, Any]] = []
    for page_items in pages:
        for it in page_items:
            key = it.get("id") or it.get("code")
            if key in seen:
                continue
            seen.add(key)
            items.append(it)

    if total and len(items) < total:
        logger.warning(
            "hemis_fetch_incomplete",
            resource=resource,
            fetched=len(items),
            expected=total,
        )
    logger.info("hemis_fetched", resource=resource, count=len(items), expected=total)
    return items


async def university_profile() -> dict[str, Any]:
    """`/v1/public/university-profile` — unauthenticated. Carries the official
    name, address, contact line and the full specialty list, which is what the
    AI Abituriyent menu answers from."""
    base = (get_settings().hemis_api_base or "").rstrip("/")
    if not base:
        raise ServiceUnavailableError("hemis_not_configured")
    try:
        async with _client(base) as client:
            r = await client.get("/v1/public/university-profile")
        r.raise_for_status()
        body = r.json()
    except Exception as e:
        logger.warning(
            "hemis_profile_failed", error=str(e), error_type=type(e).__name__
        )
        raise UpstreamError(cause=e) from e
    return body.get("data") or {}
