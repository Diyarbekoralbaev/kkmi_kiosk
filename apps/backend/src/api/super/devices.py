"""Super admin: devices CRUD + enrollment code issuance + revoke."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field
import structlog
from sqlalchemy import func, select

from ...core import audit
from ...core.deps import DbSession, SuperAdmin
from ...core.errors import NotFoundError, ValidationError
from ...core.security import (
    hash_device_secret,
    random_enrollment_code,
)
from ...domain.device import Device, DeviceEnrollmentCode, DeviceKey
from ...domain.organization import Organization

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/super/devices", tags=["super:devices"])

# Enrollment codes are short-lived to limit window for code theft.
_ENROLLMENT_CODE_TTL = timedelta(minutes=10)


class DeviceOut(BaseModel):
    id: str
    org_id: str
    name: str
    location: str
    status: str
    cert_serial: str | None
    last_seen_at: str | None
    created_at: str


class DeviceListOut(BaseModel):
    items: list[DeviceOut]
    total: int


class DeviceCreateIn(BaseModel):
    org_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    location: str = Field(default="", max_length=255)


class DeviceCreatedOut(DeviceOut):
    enrollment_code: str
    enrollment_expires_at: str


class EnrollmentCodeOut(BaseModel):
    enrollment_code: str
    enrollment_expires_at: str


def _to_out(d: Device) -> DeviceOut:
    return DeviceOut(
        id=str(d.id),
        org_id=str(d.org_id),
        name=d.name,
        location=d.location,
        status=d.status,
        cert_serial=d.cert_serial,
        last_seen_at=d.last_seen_at.isoformat() if d.last_seen_at else None,
        created_at=d.created_at.isoformat(),
    )


@router.get("", response_model=DeviceListOut)
async def list_devices(
    session: DbSession,
    _: SuperAdmin,
    org_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DeviceListOut:
    stmt = select(Device)
    cstmt = select(func.count()).select_from(Device)
    if org_id:
        stmt = stmt.where(Device.org_id == org_id)
        cstmt = cstmt.where(Device.org_id == org_id)
    if status_filter:
        stmt = stmt.where(Device.status == status_filter)
        cstmt = cstmt.where(Device.status == status_filter)
    stmt = stmt.order_by(Device.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(cstmt)).scalar_one()
    return DeviceListOut(items=[_to_out(d) for d in rows], total=int(total))


@router.post("", response_model=DeviceCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_device(
    payload: DeviceCreateIn,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> DeviceCreatedOut:
    org = (
        await session.execute(
            select(Organization).where(Organization.id == payload.org_id)
        )
    ).scalar_one_or_none()
    if org is None:
        raise NotFoundError("org_not_found")

    # Pre-generate the UUID so we can reference it in the enrollment code row
    # without an extra flush (mapped_column default=uuid.uuid4 fires at flush time).
    device_id = uuid.uuid4()
    device = Device(
        id=device_id,
        org_id=payload.org_id,
        name=payload.name,
        location=payload.location,
        status="pending",
    )
    session.add(device)

    code = random_enrollment_code()
    expires_at = datetime.now(UTC) + _ENROLLMENT_CODE_TTL
    session.add(
        DeviceEnrollmentCode(
            device_id=device_id,
            code_hash=hash_device_secret(code),
            expires_at=expires_at,
        )
    )

    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=device.org_id,
        action="device.create",
        entity_type="device",
        entity_id=device.id,
        request=request,
        after={
            "name": device.name,
            "location": device.location,
            "org_id": str(device.org_id),
        },
    )

    return DeviceCreatedOut(
        id=str(device.id),
        org_id=str(device.org_id),
        name=device.name,
        location=device.location,
        status=device.status,
        cert_serial=None,
        last_seen_at=None,
        created_at=datetime.now(UTC).isoformat(),
        enrollment_code=code,
        enrollment_expires_at=expires_at.isoformat(),
    )


@router.post("/{device_id}/enrollment-code", response_model=EnrollmentCodeOut)
async def regenerate_enrollment_code(
    device_id: uuid.UUID,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> EnrollmentCodeOut:
    device = (
        await session.execute(select(Device).where(Device.id == device_id))
    ).scalar_one_or_none()
    if device is None:
        raise NotFoundError()
    if device.status == "revoked":
        raise ValidationError("device_revoked")

    # Invalidate any unused codes so only the freshest one works.
    now = datetime.now(UTC)
    open_codes = (
        await session.execute(
            select(DeviceEnrollmentCode).where(
                DeviceEnrollmentCode.device_id == device_id,
                DeviceEnrollmentCode.used_at.is_(None),
            )
        )
    ).scalars().all()
    for c in open_codes:
        c.used_at = now

    code = random_enrollment_code()
    expires_at = now + _ENROLLMENT_CODE_TTL
    session.add(
        DeviceEnrollmentCode(
            device_id=device_id,
            code_hash=hash_device_secret(code),
            expires_at=expires_at,
        )
    )

    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=device.org_id,
        action="device.enrollment_code_regenerate",
        entity_type="device",
        entity_id=device.id,
        request=request,
    )
    return EnrollmentCodeOut(
        enrollment_code=code,
        enrollment_expires_at=expires_at.isoformat(),
    )


@router.post("/{device_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    device_id: uuid.UUID,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> None:
    d = (
        await session.execute(select(Device).where(Device.id == device_id))
    ).scalar_one_or_none()
    if d is None:
        raise NotFoundError()
    d.status = "revoked"

    # Revoke all keys + invalidate any open enrollment codes.
    now = datetime.now(UTC)
    keys = (
        await session.execute(
            select(DeviceKey).where(
                DeviceKey.device_id == d.id, DeviceKey.revoked_at.is_(None)
            )
        )
    ).scalars().all()
    for k in keys:
        k.revoked_at = now
    open_codes = (
        await session.execute(
            select(DeviceEnrollmentCode).where(
                DeviceEnrollmentCode.device_id == d.id,
                DeviceEnrollmentCode.used_at.is_(None),
            )
        )
    ).scalars().all()
    for c in open_codes:
        c.used_at = now

    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=d.org_id,
        action="device.revoke",
        entity_type="device",
        entity_id=d.id,
        request=request,
    )

    # Force-close any active WS for this device. Registry publishes on Redis;
    # all backend workers (incl. this one) react and call ws.close(1008).
    # Non-blocking — done within the request's transaction so that the kiosk's
    # next packet hits a closed socket rather than seeing stale auth.
    from ...core.connection_registry import registry
    n_closed = await registry.revoke_device(d.id)
    if n_closed:
        logger.info("device_revoke_closed_active_ws", device_id=str(d.id), count=n_closed)
