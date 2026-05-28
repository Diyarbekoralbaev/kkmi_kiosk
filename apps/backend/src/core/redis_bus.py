"""Process-wide Redis pub/sub used to broadcast revoke + release events.

Why Redis: lets multiple uvicorn workers (or future backend replicas)
coordinate. When super-admin clicks revoke, the API handler that wins the
HTTP request needs to close WS connections that may live on a different
worker. Publishing to Redis fans out to every worker's subscriber loop.

If REDIS_URL points to a real Redis, we use it. If Redis is unreachable at
startup, we fall back to a local-process bus — fine for single-worker dev
and won't crash the backend, just won't cross-broadcast.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import redis.asyncio as aioredis
import structlog

from .config import get_settings

logger = structlog.get_logger(__name__)

DEVICE_REVOKED_CHANNEL = "device.revoked"
RELEASE_PUBLISHED_CHANNEL = "release.published"

Subscriber = Callable[[str], Awaitable[None]]


class RedisBus:
    """Tiny async wrapper. publish() and subscribe() — that's it.

    Each subscriber gets every message on the channel (after subscription).
    Publishing to a channel with no subscribers is a no-op (Redis behavior).
    """

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._subscribers: dict[str, list[Subscriber]] = {}
        self._listener_task: asyncio.Task[None] | None = None
        self._connected = False

    async def connect(self) -> None:
        if self._connected:
            return
        url = get_settings().redis_url
        try:
            self._redis = aioredis.from_url(url, decode_responses=True)
            await self._redis.ping()
            self._pubsub = self._redis.pubsub()
            self._connected = True
            logger.info("redis_bus_connected", url=url)
        except Exception as e:
            logger.warning("redis_bus_unavailable", url=url, error=str(e))
            self._connected = False

    async def publish(self, channel: str, payload: str) -> None:
        if not self._connected:
            # Local fallback so single-worker dev still works without Redis.
            await self._dispatch_local(channel, payload)
            return
        try:
            await self._redis.publish(channel, payload)  # type: ignore[union-attr]
        except Exception as e:
            logger.warning("redis_publish_failed", channel=channel, error=str(e))
            await self._dispatch_local(channel, payload)

    async def subscribe(self, channel: str, handler: Subscriber) -> None:
        self._subscribers.setdefault(channel, []).append(handler)
        if not self._connected or self._pubsub is None:
            return
        await self._pubsub.subscribe(channel)
        if self._listener_task is None:
            self._listener_task = asyncio.create_task(self._listen())

    async def _dispatch_local(self, channel: str, payload: str) -> None:
        for h in self._subscribers.get(channel, []):
            try:
                await h(payload)
            except Exception:
                logger.exception("redis_local_handler_failed", channel=channel)

    async def _listen(self) -> None:
        assert self._pubsub is not None
        async for msg in self._pubsub.listen():
            if msg.get("type") != "message":
                continue
            channel = msg.get("channel")
            data = msg.get("data")
            if isinstance(channel, bytes):
                channel = channel.decode()
            if isinstance(data, bytes):
                data = data.decode()
            for h in self._subscribers.get(channel, []):
                try:
                    await h(data)
                except Exception:
                    logger.exception("redis_handler_failed", channel=channel)

    async def close(self) -> None:
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except (asyncio.CancelledError, Exception):
                pass
            self._listener_task = None
        if self._pubsub is not None:
            try:
                await self._pubsub.aclose()
            except Exception:
                pass
            self._pubsub = None
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None
        self._connected = False


# Module-global singleton — lifecycle managed by FastAPI lifespan.
bus = RedisBus()
