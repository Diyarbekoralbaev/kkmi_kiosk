"""Kiosk diagnostics — the kiosk uploads its local crash.log here on startup
(after a crash + watchdog restart) so we can see the exact exception/stack
remotely without physical access to the machine. Device-auth; nothing stored —
the content is just logged (structlog) with the device id + correlation id.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/kiosk", tags=["kiosk:diag"])


class CrashLogIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


@router.post("/crashlog", status_code=204)
async def upload_crashlog(
    body: CrashLogIn,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> None:
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)
    # Log line-by-line so the structured log stays readable in the aggregator.
    logger.warning(
        "kiosk_crashlog",
        device_id=str(device.id),
        chars=len(body.text),
        crashlog=body.text,
    )
