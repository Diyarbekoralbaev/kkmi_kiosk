"""In-memory token-bucket rate limiter for public endpoints.

This is a single-process best-effort guard meant for v1. With multiple uvicorn
workers each gets its own bucket — fine for slowing automation, not for hard
caps. Production should swap to Redis (drop-in via the same `RateLimiter` API).
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock


class RateLimiter:
    """Sliding-window counter keyed by `bucket:key`.

    `allow(bucket, key, max_per_window, window_seconds)` returns True if the
    caller is below the cap, False if they should be 429'd. Old entries are
    pruned lazily on each call so memory stays bounded.
    """

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = Lock()

    def allow(
        self, bucket: str, key: str, *, max_per_window: int, window_seconds: float
    ) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        bucket_key = (bucket, key)
        with self._lock:
            dq = self._hits.setdefault(bucket_key, deque())
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= max_per_window:
                return False
            dq.append(now)
            return True


# Module-global singleton — fine because the data is per-process.
limiter = RateLimiter()


def client_ip(request) -> str:
    """Best-effort client IP from `X-Forwarded-For` or peer.

    Behind a properly-configured reverse proxy XFF is set; falls back to the
    socket peer (loopback in dev). Used only for rate-limit keying — not
    security-critical.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"
