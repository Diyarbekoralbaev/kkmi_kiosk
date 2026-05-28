"""Tracks active kiosk WS connections so super-admin revoke can force-close them.

Lifecycle (per WS):
  - on accept:  await registry.register(device_id, ws)
  - on close:   await registry.unregister(device_id, ws)

Force-close path:
  - super_devices.revoke endpoint marks DB rows revoked
  - then publishes the device_id on Redis channel `device.revoked`
  - every backend worker's subscriber receives the event and closes any local
    WS for that device_id with code 1008 ("policy violation")

This is single-process safe (publishing to your own subscriber works) and
multi-worker safe via Redis fanout.
"""
from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict

import structlog
from fastapi import WebSocket

from .redis_bus import DEVICE_REVOKED_CHANNEL, bus

logger = structlog.get_logger(__name__)


class ConnectionRegistry:
    def __init__(self) -> None:
        # device_id (str) → set of WebSocket. Multiple connections can exist
        # if the kiosk is reconnecting and the old socket hasn't shut down yet.
        self._sockets: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def register(self, device_id: uuid.UUID, ws: WebSocket) -> None:
        async with self._lock:
            self._sockets[str(device_id)].add(ws)

    async def unregister(self, device_id: uuid.UUID, ws: WebSocket) -> None:
        async with self._lock:
            sockets = self._sockets.get(str(device_id))
            if sockets is None:
                return
            sockets.discard(ws)
            if not sockets:
                self._sockets.pop(str(device_id), None)

    async def revoke_device(self, device_id: uuid.UUID) -> int:
        """Publish a revoke event so every worker (incl. this one) closes
        any open WS for the device. Returns the count of sockets closed
        in the *local* process (others close async via subscriber)."""
        await bus.publish(DEVICE_REVOKED_CHANNEL, str(device_id))
        return await self._close_local(str(device_id))

    async def _close_local(self, device_id: str) -> int:
        async with self._lock:
            sockets = list(self._sockets.get(device_id, ()))
        n = 0
        for ws in sockets:
            try:
                await ws.close(code=1008, reason="device_revoked")
                n += 1
            except Exception:
                pass
        return n

    async def _on_revoke_event(self, device_id_str: str) -> None:
        """Subscriber callback — fired by RedisBus on incoming messages."""
        try:
            uuid.UUID(device_id_str)  # validate
        except ValueError:
            return
        n = await self._close_local(device_id_str)
        if n > 0:
            logger.info("ws_force_closed_on_revoke", device_id=device_id_str, count=n)

    async def attach_to_bus(self) -> None:
        """Wire the bus subscriber. Call once at backend startup."""
        await bus.subscribe(DEVICE_REVOKED_CHANNEL, self._on_revoke_event)


# Module-global, used by kiosk_ws.py + super/devices.py.
registry = ConnectionRegistry()
