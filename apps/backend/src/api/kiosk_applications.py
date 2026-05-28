"""Kiosk-side manual murajaat (appeal) + feedback submission.

Murajat: visitor taps the Murajat tile → topic + body via on-screen keyboard →
phone via numeric keypad → preview → submit. Shares
`ai.applications.create_application` with the voice flow (kind=murajaat); only
`source` differs ("kiosk_manual" vs "kiosk_voice").

Feedback: the Fikr tile → pick type (shaǵım/usınıs/minnetdarshılıq) → text +
phone. Rides on the same `applications` table via the `kind` discriminator.

No categories, no officials — the Council intake is simpler than the Hokimiyat
version this was cloned from.
"""
from __future__ import annotations

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..ai.applications import create_application, create_feedback
from ..ai.appointments import mask_phone, normalize_phone
from ..core import audit
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import NotFoundError, ValidationError
from ..domain.application import ALL_FEEDBACK_TYPES
from ..domain.organization import Organization, name_translations_for_response

router = APIRouter(prefix="/api/kiosk/applications", tags=["kiosk:applications"])
feedback_router = APIRouter(prefix="/api/kiosk/feedback", tags=["kiosk:feedback"])


class CreateApplicationIn(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=10_000)
    phone: str = Field(min_length=4, max_length=32)


class CreateApplicationOut(BaseModel):
    application_id: str
    topic: str
    body: str
    phone_masked: str
    status: str
    # Localized org name (uz/kk/ru) for the on-screen success talon header.
    org_name_translations: dict[str, str] = {}


async def _active_org(session: DbSession, x_kiosk_auth: str | None) -> Organization:
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)
    org = await session.get(Organization, device.org_id)
    if org is None or getattr(org, "status", "active") != "active":
        raise NotFoundError("org_not_found")
    return org


@router.post("", response_model=CreateApplicationOut, status_code=201)
async def create_kiosk_application(
    body: CreateApplicationIn,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> CreateApplicationOut:
    org = await _active_org(session, x_kiosk_auth)

    phone_norm = normalize_phone(body.phone)
    topic_clean = body.topic.strip()
    body_clean = body.body.strip()

    app = await create_application(
        session,
        org_id=org.id,
        topic=topic_clean,
        body=body_clean,
        phone=phone_norm,
        source="kiosk_manual",
    )

    await audit.record(
        session,
        actor_user_id=None,
        actor_org_id=org.id,
        action="application.create",
        entity_type="application",
        entity_id=app.id,
        after={
            "topic": topic_clean,
            "phone_masked": mask_phone(phone_norm),
            "kind": "murajaat",
            "source": "kiosk_manual",
        },
    )

    return CreateApplicationOut(
        application_id=str(app.id),
        topic=app.topic,
        body=app.body,
        phone_masked=mask_phone(phone_norm),
        status=app.status,
        org_name_translations=name_translations_for_response(org),
    )


class CreateFeedbackIn(BaseModel):
    feedback_type: str = Field(max_length=16)  # complaint | suggestion | gratitude
    text: str = Field(min_length=1, max_length=10_000)
    phone: str = Field(min_length=4, max_length=32)


class CreateFeedbackOut(BaseModel):
    feedback_id: str
    feedback_type: str
    phone_masked: str
    status: str
    org_name_translations: dict[str, str] = {}


@feedback_router.post("", response_model=CreateFeedbackOut, status_code=201)
async def create_kiosk_feedback(
    body: CreateFeedbackIn,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> CreateFeedbackOut:
    org = await _active_org(session, x_kiosk_auth)

    ftype = body.feedback_type.strip()
    if ftype not in ALL_FEEDBACK_TYPES:
        raise ValidationError("invalid_feedback_type")
    phone_norm = normalize_phone(body.phone)

    fb = await create_feedback(
        session,
        org_id=org.id,
        feedback_type=ftype,
        text=body.text.strip(),
        phone=phone_norm,
        source="kiosk_manual",
    )

    await audit.record(
        session,
        actor_user_id=None,
        actor_org_id=org.id,
        action="feedback.create",
        entity_type="application",
        entity_id=fb.id,
        after={
            "feedback_type": ftype,
            "phone_masked": mask_phone(phone_norm),
            "kind": "feedback",
            "source": "kiosk_manual",
        },
    )

    return CreateFeedbackOut(
        feedback_id=str(fb.id),
        feedback_type=ftype,
        phone_masked=mask_phone(phone_norm),
        status=fb.status,
        org_name_translations=name_translations_for_response(org),
    )
