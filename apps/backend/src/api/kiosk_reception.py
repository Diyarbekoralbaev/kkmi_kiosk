"""Kiosk touch-flow reception (qabul) booking.

Touch twin of the voice flow's `submit_reception` tool: same table, same
reference format, same printed talon. Whether the visitor tapped or spoke is not
something the staff should have to care about.

The predecessor of this module existed but was never wired into `main.py`, so
the endpoint was unreachable and the whole booking path was dead. It is
registered here.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..ai.appointments import build_verify_url, create_appointment, reference_no
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import NotFoundError
from ..domain.ai_config import OrgKbOfficial
from ..domain.appointment import SOURCE_KIOSK
from ..domain.organization import Organization

router = APIRouter(prefix="/api/kiosk", tags=["kiosk:reception"])


class CreateReceptionIn(BaseModel):
    official_id: str
    full_name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=4, max_length=32)
    reason: str = Field(default="", max_length=2000)


class CreateReceptionOut(BaseModel):
    reference: str
    verify_url: str
    reception_day: str
    reception_time: str


@router.post("/reception", response_model=CreateReceptionOut, status_code=201)
async def create_reception(
    body: CreateReceptionIn,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> CreateReceptionOut:
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)

    try:
        official_pk = uuid.UUID(body.official_id)
    except ValueError as e:
        raise NotFoundError("official_not_found") from e

    # Scoped to the device's org: a stale or guessed id must never reach another
    # tenant's leadership row.
    official = (
        await session.execute(
            select(OrgKbOfficial).where(
                OrgKbOfficial.id == official_pk,
                OrgKbOfficial.org_id == device.org_id,
            )
        )
    ).scalar_one_or_none()
    if official is None:
        raise NotFoundError("official_not_found")

    org = (
        await session.execute(
            select(Organization).where(Organization.id == device.org_id)
        )
    ).scalar_one()

    created = await create_appointment(
        session,
        org=org,
        visitor_name=body.full_name,
        visitor_phone=body.phone,
        topic_summary=body.reason,
        source=SOURCE_KIOSK,
        official_id=official.id,
    )
    return CreateReceptionOut(
        reference=reference_no(created.appointment),
        verify_url=build_verify_url(created.appointment.verification_token),
        reception_day=official.reception_day,
        reception_time=official.reception_time,
    )
