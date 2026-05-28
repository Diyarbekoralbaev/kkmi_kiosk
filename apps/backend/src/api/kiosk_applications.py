"""Kiosk-side manual application (murajat) submission.

Used by the on-screen manual flow on the kiosk: visitor taps the
Murojaat tile → topic via on-screen keyboard → body multi-line via
keyboard → phone via numeric keypad → preview → submit. Lands here.

Mirrors the structure of `kiosk_appointments.py`: same signed-nonce
auth, same `create_*` helper pattern, same audit row shape. The voice
flow's `submit_application` tool dispatch in `kiosk_ws.py` also calls
`create_application()` so both paths produce identical Application
rows — the only difference is the `source` field ("kiosk_voice" vs
"kiosk_manual") and the absence of a `voice_session_id`.

Category defaults to "other" on the wire — the manual flow does not
ask the visitor to categorize their request (operator decision: keep
the visitor flow short; reviewers correct categories in the panel
later).
"""
from __future__ import annotations

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..ai.applications import create_application
from ..ai.appointments import mask_phone, normalize_phone
from ..core import audit, telegram
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import NotFoundError
from ..domain.organization import Organization, name_translations_for_response

router = APIRouter(prefix="/api/kiosk/applications", tags=["kiosk:applications"])


class CreateApplicationIn(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=10_000)
    phone: str = Field(min_length=4, max_length=32)
    # Default "other" so the manual flow can skip the category picker.
    # Backend resolves unknown slugs to NULL silently — same as voice.
    category_slug: str = Field(default="other", max_length=32)


class CreateApplicationOut(BaseModel):
    application_id: str
    topic: str
    body: str
    phone_masked: str
    category_slug: str
    # True when the slug resolved to a real category_id; False when it
    # fell back to NULL (slug unknown or soft-deleted). Lets the kiosk
    # know whether the visitor's request will appear under the picked
    # category in the gov-panel or whether a reviewer needs to triage.
    category_resolved: bool
    status: str
    # Localized org name (uz/kk/ru) for the on-screen success talon
    # header — mirrors what CreateAppointmentOut carries.
    org_name_translations: dict[str, str] = {}


@router.post("", response_model=CreateApplicationOut, status_code=201)
async def create_kiosk_application(
    body: CreateApplicationIn,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> CreateApplicationOut:
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)

    org = await session.get(Organization, device.org_id)
    if org is None or getattr(org, "status", "active") != "active":
        raise NotFoundError("org_not_found")

    phone_norm = normalize_phone(body.phone)
    topic_clean = body.topic.strip()
    body_clean = body.body.strip()
    category_slug = body.category_slug.strip() or "other"

    app = await create_application(
        session,
        org_id=org.id,
        topic=topic_clean,
        body=body_clean,
        phone=phone_norm,
        category_slug=category_slug,
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
            "category_slug": category_slug,
            "category_resolved": app.category_id is not None,
            "source": "kiosk_manual",
        },
    )

    # Fan out to the operator's Telegram murajat channel. Fire-and-forget
    # — never blocks the citizen's response, never raises.
    telegram.post_murajaat_async(app, category_slug, org)

    return CreateApplicationOut(
        application_id=str(app.id),
        topic=app.topic,
        body=app.body,
        phone_masked=mask_phone(phone_norm),
        category_slug=category_slug,
        category_resolved=app.category_id is not None,
        status=app.status,
        org_name_translations=name_translations_for_response(org),
    )
