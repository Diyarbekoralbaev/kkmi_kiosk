"""Kiosk-side manual qabul (reception) registration.

Visitor taps the Qabul tile → optional reason via on-screen keyboard → phone
via numeric keypad → confirm → submit. No official, no date, no queue — Council
staff call the citizen back. Shares `ai.appointments.create_appointment` with
the voice flow. Response embeds the QR PNG + reference number so the on-screen
talon renders without a second round-trip.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..ai.appointments import (
    create_appointment,
    mask_phone,
    normalize_phone,
    reference_no,
)
from ..ai.receipt import render_qr_png
from ..core import audit, telegram
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import NotFoundError
from ..domain.organization import Organization, name_translations_for_response

router = APIRouter(prefix="/api/kiosk/appointments", tags=["kiosk:appointments"])


class CreateAppointmentIn(BaseModel):
    phone: str = Field(min_length=4, max_length=32)
    # Optional reason for the reception. Empty is allowed.
    topic: str = Field(default="", max_length=500)


class CreateAppointmentOut(BaseModel):
    appointment_id: str
    reference_no: str
    phone_masked: str
    verification_token: str
    qr_png_base64: str = ""
    # Localized org name (uz/kk/ru) for the on-screen talon header.
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

    phone_norm = normalize_phone(body.phone)
    topic_clean = body.topic.strip()
    created = await create_appointment(
        session,
        org=org,
        visitor_phone=phone_norm,
        topic_summary=topic_clean,
        source="kiosk",
    )
    appt = created.appointment
    await audit.record(
        session,
        actor_user_id=None,
        actor_org_id=org.id,
        action="appointment.create",
        entity_type="appointment",
        entity_id=appt.id,
        after={
            "phone_masked": mask_phone(phone_norm),
            "topic": topic_clean,
            "source": "kiosk_manual",
        },
    )
    # Telegram broadcast (no-op if the bot isn't configured).
    telegram.post_qabul_async(appt, org)
    # Render QR after the transaction (caller's DbSession commits on return).
    try:
        qr_bytes = render_qr_png(created.verify_url)
        qr_b64 = base64.b64encode(qr_bytes).decode("ascii")
    except Exception:
        qr_b64 = ""
    return CreateAppointmentOut(
        appointment_id=str(appt.id),
        reference_no=reference_no(appt),
        phone_masked=mask_phone(phone_norm),
        verification_token=appt.verification_token,
        qr_png_base64=qr_b64,
        org_name_translations=name_translations_for_response(org),
    )
