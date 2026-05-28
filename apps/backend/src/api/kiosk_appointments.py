"""Kiosk-side manual appointment booking.

Used by the on-screen flow (officials list → topic via on-screen
keyboard → numeric keypad → submit). The voice flow goes through
`kiosk_ws._dispatch_submit_appointment`; both end up calling
`ai.appointments.create_appointment(...)`, so behavior (queue number
assignment, receipt PDF generation, audit log) is identical.

Topic is collected on the kiosk via a new SectionEnterTopic on
QabulPage and submitted alongside official_id + phone. The payload
field is optional with a default of "" so older kiosk binaries that
predate the topic step keep working unchanged.

Response also embeds the QR PNG as base64 so the on-screen talon can render
the QR without a second HTTP round-trip. The WS voice flow does the same
via `appointment_submitted.qr_png_base64`; the two clients now hydrate
their SessionStore identically.
"""
from __future__ import annotations

import base64
import uuid

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..ai.appointments import (
    create_appointment,
    mask_phone,
    normalize_phone,
)
from ..ai.receipt import format_date_kk, render_qr_png
from ..core import audit, telegram
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import NotFoundError, ValidationError
from ..domain.ai_config import OrgKbOfficial
from ..domain.organization import Organization, name_translations_for_response

router = APIRouter(prefix="/api/kiosk/appointments", tags=["kiosk:appointments"])


class CreateAppointmentIn(BaseModel):
    official_id: uuid.UUID
    phone: str = Field(min_length=4, max_length=32)
    # Optional with default — older kiosks that don't include the topic
    # step still work. New kiosks send the visitor-typed issue summary.
    topic: str = Field(default="", max_length=500)


class CreateAppointmentOut(BaseModel):
    appointment_id: str
    queue_number: int
    official_name: str
    official_position: str
    scheduled_date: str
    scheduled_date_human: str
    reception_time: str
    phone_masked: str
    verification_token: str
    qr_png_base64: str = ""
    # Localized org name (uz/kk/ru) for the on-screen talon header. Mirrors
    # what HeartbeatOut carries; the kiosk picks one based on its UI lang.
    org_name_translations: dict[str, str] = {}


@router.post("", response_model=CreateAppointmentOut, status_code=201)
async def create_kiosk_appointment(
    body: CreateAppointmentIn,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> CreateAppointmentOut:
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)

    org = await session.get(Organization, device.org_id)
    if org is None or getattr(org, "status", "active") != "active":
        raise NotFoundError("org_not_found")

    ofc = (
        await session.execute(
            select(OrgKbOfficial).where(
                OrgKbOfficial.id == body.official_id,
                OrgKbOfficial.org_id == org.id,
            )
        )
    ).scalar_one_or_none()
    if ofc is None:
        raise ValidationError("official_not_in_org")

    phone_norm = normalize_phone(body.phone)
    topic_clean = body.topic.strip()
    created = await create_appointment(
        session,
        org=org,
        official=ofc,
        visitor_phone=phone_norm,
        topic_summary=topic_clean,
        source="kiosk",
    )
    appt = created.appointment
    # Audit row in the same transaction — per CLAUDE.md every write
    # endpoint records an audit. Phone goes in via the no-op mask_phone
    # for call-site consistency with the WS voice flow.
    await audit.record(
        session,
        actor_user_id=None,
        actor_org_id=org.id,
        action="appointment.create",
        entity_type="appointment",
        entity_id=appt.id,
        after={
            "official_id": str(ofc.id),
            "official_name": ofc.name,
            "queue_number": appt.queue_number,
            "scheduled_date": appt.scheduled_date.isoformat(),
            "phone_masked": mask_phone(phone_norm),
            "topic": topic_clean,
            "source": "kiosk_manual",
        },
    )
    # Fan out to the operator's Telegram qabul channel. Uses the
    # backend-rendered Karakalpak Cyrillic date string so the post
    # matches what the visitor sees on the talon.
    telegram.post_qabul_async(appt, ofc, org, format_date_kk(appt.scheduled_date))
    # Render QR after the transaction so the row-lock is released before
    # the ~20 ms qrcode draw. A render failure isn't fatal — the kiosk
    # falls back to the verification_token (it could call the public
    # /appointments/qr/{token}.png endpoint), so we swallow the exception.
    try:
        qr_bytes = render_qr_png(created.verify_url)
        qr_b64 = base64.b64encode(qr_bytes).decode("ascii")
    except Exception:
        qr_b64 = ""
    return CreateAppointmentOut(
        appointment_id=str(appt.id),
        queue_number=appt.queue_number,
        official_name=ofc.name,
        official_position=ofc.position,
        scheduled_date=appt.scheduled_date.isoformat(),
        scheduled_date_human=format_date_kk(appt.scheduled_date),
        reception_time=ofc.reception_time,
        phone_masked=mask_phone(phone_norm),
        verification_token=appt.verification_token,
        qr_png_base64=qr_b64,
        org_name_translations=name_translations_for_response(org),
    )
