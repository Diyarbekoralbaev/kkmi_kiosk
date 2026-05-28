"""Public challenge endpoint for kiosk ECDSA auth.

Kiosk hits this before every signed request to obtain a fresh single-use
nonce. The nonce alone is not a credential — without the kiosk's TPM-bound
private key, an attacker can't sign it. We rate-limit anyway to keep the
auth_challenges table from getting hammered.
"""
from __future__ import annotations

import base64
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from ..core.deps import DbSession
from ..core.errors import AuthError
from ..core.rate_limit import client_ip, limiter
from ..domain.device import AuthChallenge, Device

router = APIRouter(prefix="/api/kiosk/auth", tags=["kiosk:auth"])

CHALLENGE_TTL_SECONDS = 10


class ChallengeOut(BaseModel):
    nonce: str
    expires_at: str


@router.get("/challenge", response_model=ChallengeOut)
async def issue_challenge(
    device_id: uuid.UUID,
    session: DbSession,
    request: Request,
) -> ChallengeOut:
    """Issue a single-use ECDSA nonce for a known active device."""
    if not limiter.allow(
        "kiosk_challenge", client_ip(request),
        max_per_window=120, window_seconds=60,
    ):
        # 120/min/IP is generous — under normal use a kiosk hits this 1-2x/min.
        # The cap exists only to keep table-bloat attackers in check.
        raise AuthError("rate_limited")

    device = (
        await session.execute(select(Device).where(Device.id == device_id))
    ).scalar_one_or_none()
    if device is None or device.status != "active":
        # Generic message — don't leak which devices exist.
        raise AuthError("device_inactive")

    nonce_bytes = secrets.token_bytes(32)
    nonce_b64 = base64.urlsafe_b64encode(nonce_bytes).rstrip(b"=").decode("ascii")
    expires_at = datetime.now(UTC) + timedelta(seconds=CHALLENGE_TTL_SECONDS)
    session.add(
        AuthChallenge(
            id=uuid.uuid4(),
            device_id=device.id,
            nonce_b64=nonce_b64,
            expires_at=expires_at,
            created_at=datetime.now(UTC),
        )
    )
    return ChallengeOut(nonce=nonce_b64, expires_at=expires_at.isoformat())
