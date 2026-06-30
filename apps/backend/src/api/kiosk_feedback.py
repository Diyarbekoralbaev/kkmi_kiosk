"""Kiosk-side manual feedback submission.

The Fikr tile → pick type (shaǵım/usınıs/minnetdarshılıq) → text + phone. Rides
on the `applications` table via the `kind` discriminator. Shares
`ai.applications.create_feedback` with the voice flow; only `source` differs
("kiosk_manual" vs "kiosk_voice").
"""
from __future__ import annotations

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..ai.applications import create_feedback
from ..ai.appointments import mask_phone, normalize_phone
from ..core import audit, telegram
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import NotFoundError, ValidationError
from ..domain.application import ALL_FEEDBACK_TYPES
from ..domain.organization import Organization, name_translations_for_response

router = APIRouter(prefix="/api/kiosk/feedback", tags=["kiosk:feedback"])


async def _active_org(session: DbSession, x_kiosk_auth: str | None) -> Organization:
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)
    org = await session.get(Organization, device.org_id)
    if org is None or getattr(org, "status", "active") != "active":
        raise NotFoundError("org_not_found")
    return org


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


@router.post("", response_model=CreateFeedbackOut, status_code=201)
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

    telegram.post_feedback_async(fb, ftype, org)

    return CreateFeedbackOut(
        feedback_id=str(fb.id),
        feedback_type=ftype,
        phone_masked=mask_phone(phone_norm),
        status=fb.status,
        org_name_translations=name_translations_for_response(org),
    )
