"""Device authentication via ECDSA P-256 challenge-response.

Flow per request:
  1. Kiosk asks server for a fresh nonce: GET /api/kiosk/auth/challenge?device_id=...
  2. Server stores nonce in `auth_challenges` (10 s TTL, single-use).
  3. Kiosk signs the raw nonce bytes with its TPM-bound private key.
  4. Kiosk sends the actual request with header
        X-Kiosk-Auth: <device_id>.<nonce_b64>.<sig_b64>
  5. Server verifies: nonce row exists + unused + unexpired + matches device →
     ECDSA verify with the device's stored public key → mark used.

Replay attempts re-use a nonce → fail at step 5 (used_at already set).
Stolen device key replay → impossible: there's no shared secret. The server
only ever holds the public key.
"""
from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.device import AuthChallenge, Device, DeviceKey
from .errors import AuthError

AUTH_HEADER_NAME = "x-kiosk-auth"


def _b64decode_padded(s: str) -> bytes:
    """URL-safe base64 decode that tolerates missing padding."""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def parse_auth_header(value: str) -> tuple[uuid.UUID, str, bytes]:
    """`<device_id>.<nonce_b64>.<sig_b64>` → (device_uuid, nonce_b64, sig_bytes)."""
    parts = value.split(".")
    if len(parts) != 3:
        raise AuthError("malformed_auth_header")
    device_id_str, nonce_b64, sig_b64 = parts
    try:
        device_uuid = uuid.UUID(device_id_str)
        sig = _b64decode_padded(sig_b64)
    except (ValueError, TypeError) as e:
        raise AuthError("auth_header_decode_failed") from e
    if not nonce_b64 or len(nonce_b64) > 64:
        raise AuthError("malformed_auth_header")
    return device_uuid, nonce_b64, sig


async def resolve_device_from_signed_request(
    session: AsyncSession, header: str | None
) -> Device:
    """Validate an X-Kiosk-Auth header end-to-end and return the Device.

    Single transaction: nonce is marked used the moment we successfully verify
    its signature. Any subsequent request reusing the same nonce fails.
    """
    if not header:
        raise AuthError("missing_auth_header")
    device_uuid, nonce_b64, sig = parse_auth_header(header.strip())

    now = datetime.now(UTC)

    challenge = (
        await session.execute(
            select(AuthChallenge).where(
                AuthChallenge.nonce_b64 == nonce_b64,
                AuthChallenge.device_id == device_uuid,
            )
        )
    ).scalar_one_or_none()
    if challenge is None:
        raise AuthError("nonce_invalid")
    if challenge.used_at is not None:
        raise AuthError("nonce_used")
    if challenge.expires_at < now:
        raise AuthError("nonce_expired")

    device = (
        await session.execute(select(Device).where(Device.id == device_uuid))
    ).scalar_one_or_none()
    if device is None or device.status != "active":
        raise AuthError("device_inactive")

    dk = (
        await session.execute(
            select(DeviceKey)
            .where(
                DeviceKey.device_id == device_uuid,
                DeviceKey.revoked_at.is_(None),
            )
            .order_by(DeviceKey.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if dk is None:
        raise AuthError("no_active_key")

    # Verify the signature matches the nonce.
    nonce_bytes = _b64decode_padded(nonce_b64)
    try:
        pub_key = serialization.load_pem_public_key(dk.public_key_pem.encode("ascii"))
    except Exception as e:
        raise AuthError("public_key_load_failed") from e
    if not isinstance(pub_key, ec.EllipticCurvePublicKey):
        raise AuthError("public_key_wrong_type")
    try:
        pub_key.verify(sig, nonce_bytes, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as e:
        raise AuthError("signature_invalid") from e

    challenge.used_at = now
    return device
