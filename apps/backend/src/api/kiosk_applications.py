"""Kiosk touch-flow appeal (murojat) submission.

The visitor fills the on-screen form — name → phone → text — and the kiosk POSTs
it here. This is the touch twin of the voice flow in `kiosk_ws.py`; both write
the same `applications` row, so staff see one queue in the gov panel regardless
of how the appeal arrived.

Appeals used to be forwarded to an external government cabinet
(cabinet.murajat.uz) that owned the citizen registry, which is why the old
payload carried district, quarter, birth date and gender. The institute keeps
its own appeals, and none of those fields mean anything for a student writing to
their dean — the form is now name, phone, text.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..ai.appointments import normalize_phone
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..domain.application import KIND_MURAJAAT, STATUS_NEW, Application

router = APIRouter(prefix="/api/kiosk", tags=["kiosk:appeal"])


class CreateAppealIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=4, max_length=32)
    text: str = Field(min_length=1, max_length=10_000)
    # Optional: the touch form has no AI to summarise, so the list view falls
    # back to a truncated body when this is absent.
    topic: str | None = Field(default=None, max_length=500)


class CreateAppealOut(BaseModel):
    reference: str
    status: str


@router.post("/appeal", response_model=CreateAppealOut, status_code=201)
async def create_kiosk_appeal(
    body: CreateAppealIn,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> CreateAppealOut:
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)

    text = body.text.strip()
    topic = (body.topic or "").strip() or (
        text[:60] + "…" if len(text) > 60 else text
    )

    app_id = uuid.uuid4()
    session.add(
        Application(
            id=app_id,
            org_id=device.org_id,
            applicant_name=body.full_name.strip(),
            topic=topic[:500],
            body=text,
            phone=normalize_phone(body.phone),
            status=STATUS_NEW,
            kind=KIND_MURAJAAT,
        )
    )
    await session.flush()
    # Same shape as the voice flow's reference so staff and visitors see one
    # format regardless of which surface the appeal came from.
    return CreateAppealOut(reference=f"M-{app_id.hex[:8].upper()}", status=STATUS_NEW)
