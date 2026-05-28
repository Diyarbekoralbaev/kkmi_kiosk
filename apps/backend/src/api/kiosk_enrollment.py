"""Public kiosk enrollment + heartbeat + read-only endpoints.

Auth model (see core/device_auth.py for full picture):

  - `POST /api/kiosk/enroll`    — exchanges a one-time enrollment code for a
    device_id. The kiosk sends its ECDSA P-256 public key (generated inside
    its TPM); the server stores the public PEM. **No shared secret.**
  - `POST /api/kiosk/heartbeat` — every 30 s. Auth: X-Kiosk-Auth signed nonce.
  - `GET  /api/kiosk/officials` — read-only KB list. Same auth.
"""
from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ..core import audit
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import AuthError, ValidationError
from ..core.security import hash_device_secret
from ..ai.weather import get_weather
from ..domain.ai_config import OrgKbOfficial
from ..domain.device import Device, DeviceEnrollmentCode, DeviceKey
from ..domain.organization import (
    Organization,
    address_translations_for_response,
    name_translations_for_response,
    work_hours_translations_for_response,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/kiosk", tags=["kiosk"])


class EnrollIn(BaseModel):
    enrollment_code: str = Field(min_length=12, max_length=20)
    public_key_pem: str = Field(min_length=64, max_length=1024)
    tpm_attested: bool = False

    @field_validator("public_key_pem")
    @classmethod
    def pem_shape(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("-----BEGIN PUBLIC KEY-----"):
            raise ValueError("expected SubjectPublicKeyInfo PEM")
        if "-----END PUBLIC KEY-----" not in v:
            raise ValueError("PEM not terminated")
        return v


class EnrollOut(BaseModel):
    device_id: str
    # Branding info handed back at enrollment time so a freshly-enrolled
    # kiosk shows the right hokimligi name BEFORE its first heartbeat lands.
    org_name: str = ""
    org_slug: str = ""
    # Localized variants (uz/kk/ru) — kiosk picks one based on its current
    # UI language. Legacy `org_name` stays for kiosks predating this field.
    org_name_translations: dict[str, str] = {}
    # Contacts page data — same fields as heartbeat. Sent at enrollment so
    # the kiosk renders correct contact info on first boot before its first
    # heartbeat lands.
    address_translations: dict[str, str] = {}
    email: str = ""
    work_hours_translations: dict[str, str] = {}
    helpline_phone: str = ""


class WeatherDto(BaseModel):
    city: str
    temp_c: int
    fetched_at: str


class HeartbeatOut(BaseModel):
    ok: bool = True
    # Branding info: kiosk renders org_name in the header so the visitor sees
    # which hokimligi they're at. Sent on every heartbeat so a rename in the
    # super-panel propagates without re-enrollment.
    org_name: str = ""
    org_slug: str = ""
    # Localized variants. Sent on every heartbeat so super-panel edits to
    # any language propagate within one heartbeat tick (≈30 s).
    org_name_translations: dict[str, str] = {}
    # Optional weather widget data (Open-Meteo via ai/weather.py, 15 min
    # backend cache). None if the org has no lat/lon configured or every
    # fetch attempt failed and no cached value exists.
    weather: WeatherDto | None = None
    # Per-org helpline phone shown in the kiosk's footer band. Empty
    # string → footer hides the help row entirely.
    helpline_phone: str = ""
    # Contacts page data. Sent on every heartbeat so super-panel edits to
    # any contact field propagate within one heartbeat tick (≈30 s).
    address_translations: dict[str, str] = {}
    email: str = ""
    work_hours_translations: dict[str, str] = {}


def _normalize_code(raw: str) -> str:
    """`xxxxxxxxxxxx` / `xxxx-xxxx-xxxx` / lowercase → `XXXX-XXXX-XXXX`."""
    flat = raw.replace("-", "").replace(" ", "").upper()
    if len(flat) != 12:
        raise ValidationError("invalid_enrollment_code")
    return f"{flat[:4]}-{flat[4:8]}-{flat[8:]}"


@router.post("/enroll", response_model=EnrollOut)
async def enroll(
    payload: EnrollIn,
    session: DbSession,
    request: Request,
) -> EnrollOut:
    code = _normalize_code(payload.enrollment_code)
    record = (
        await session.execute(
            select(DeviceEnrollmentCode).where(
                DeviceEnrollmentCode.code_hash == hash_device_secret(code)
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if record is None:
        raise AuthError("enrollment_code_invalid")
    if record.used_at is not None:
        raise AuthError("enrollment_code_used")
    if record.expires_at < now:
        raise AuthError("enrollment_code_expired")

    device = (
        await session.execute(select(Device).where(Device.id == record.device_id))
    ).scalar_one_or_none()
    if device is None or device.status == "revoked":
        raise AuthError("device_not_available")

    record.used_at = now
    # Old keys (if any) stay revoked — we never reuse the same DeviceKey row.
    # The new public key is appended; resolve_device_from_signed_request picks
    # the most recent unrevoked one.
    session.add(
        DeviceKey(
            device_id=device.id,
            public_key_pem=payload.public_key_pem,
        )
    )
    device.status = "active"
    device.last_seen_at = now

    await audit.record(
        session,
        actor_user_id=None,
        actor_org_id=device.org_id,
        action="device.enroll",
        entity_type="device",
        entity_id=device.id,
        request=request,
        after={"tpm_attested": payload.tpm_attested},
    )
    org = (
        await session.execute(select(Organization).where(Organization.id == device.org_id))
    ).scalar_one_or_none()
    return EnrollOut(
        device_id=str(device.id),
        org_name=org.name if org else "",
        org_slug=org.slug if org else "",
        org_name_translations=name_translations_for_response(org) if org else {},
        address_translations=address_translations_for_response(org) if org else {},
        email=(org.email or "") if org else "",
        work_hours_translations=(
            work_hours_translations_for_response(org) if org else {}
        ),
        helpline_phone=(org.helpline_phone or "") if org else "",
    )


@router.post("/heartbeat", response_model=HeartbeatOut)
async def heartbeat(
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> HeartbeatOut:
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)
    device.last_seen_at = datetime.now(UTC)
    org = (
        await session.execute(select(Organization).where(Organization.id == device.org_id))
    ).scalar_one_or_none()

    weather_payload = await get_weather(session, device.org_id)
    weather_dto = WeatherDto(**weather_payload) if weather_payload else None

    return HeartbeatOut(
        org_name=org.name if org else "",
        org_slug=org.slug if org else "",
        org_name_translations=name_translations_for_response(org) if org else {},
        weather=weather_dto,
        helpline_phone=(org.helpline_phone or "") if org else "",
        address_translations=address_translations_for_response(org) if org else {},
        email=(org.email or "") if org else "",
        work_hours_translations=(
            work_hours_translations_for_response(org) if org else {}
        ),
    )


# ── Read-only data the kiosk renders on its UI ────────────────────────────


class OfficialOut(BaseModel):
    id: str
    name: str
    position: str
    responsibilities: str
    reception_day: str
    reception_time: str
    order: int
    # 'chief' = the hokim itself, 'deputy' = orinbasar. Kiosk Home tiles
    # split into "Hokim jeke qabili" / "Hokim orinbasari qabili" and
    # filter on this field before rendering.
    role: str = "deputy"
    # True iff a photo has been uploaded for this official. Kiosk uses
    # this to decide between fetching /api/public/officials/{id}/photo.jpg
    # and rendering an initials-circle fallback.
    has_photo: bool = False


@router.get("/officials", response_model=list[OfficialOut])
async def list_officials_for_kiosk(
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> list[OfficialOut]:
    """Officials list for the device's org. Auth: signed-nonce header."""
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)
    rows = (
        await session.execute(
            select(OrgKbOfficial)
            .where(OrgKbOfficial.org_id == device.org_id)
            .order_by(OrgKbOfficial.order, OrgKbOfficial.created_at)
        )
    ).scalars().all()
    return [
        OfficialOut(
            id=str(r.id),
            name=r.name,
            position=r.position,
            responsibilities=r.responsibilities,
            reception_day=r.reception_day,
            reception_time=r.reception_time,
            order=r.order,
            role=r.role,
            has_photo=bool(r.photo_path),
        )
        for r in rows
    ]
