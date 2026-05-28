"""Public (auth-less) qabul booking + verification.

Surfaces:
  - List an org's officials by URL slug                 GET /api/public/orgs/{slug}/officials
  - Serve an official's uploaded photo                  GET /api/public/officials/{id}/photo.jpg
  - Create a booking by URL slug + official_id          POST /api/public/orgs/{slug}/appointments
  - Verify a booking by token (returned in the QR)      GET /api/public/appointments/verify/{token}
  - Stream the receipt PDF                              GET /api/public/appointments/receipt/{token}.pdf

Rate limits are enforced per IP and per phone (booking only) — see rate_limit.py.
No auth, no sessions, no cookies. Tenant context is resolved by `slug`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ...ai.appointments import (
    build_verify_url,
    create_appointment,
    mask_phone,
    normalize_phone,
)
from ...ai.receipt import format_date_kk, render_qr_png, render_receipt_pdf
from ...core.config import get_settings
from ...core.deps import DbSession
from ...core.errors import AppError, NotFoundError, ValidationError
from ...core.rate_limit import client_ip, limiter
from ...domain.ai_config import OrgKbOfficial
from ...domain.appointment import Appointment
from ...domain.organization import Organization, name_translations_for_response

router = APIRouter(prefix="/api/public", tags=["public:qabul"])


class TooManyRequestsError(AppError):
    code = "rate_limited"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS
    public_message = "Too many requests, slow down."


class PublicOfficialOut(BaseModel):
    id: str
    name: str
    position: str
    responsibilities: str
    reception_day: str
    reception_time: str
    order: int
    role: str = "deputy"
    # True iff a photo has been uploaded. Public surface uses this to
    # decide whether to render the photo (fetched from the photo serve
    # endpoint below) or an initials-circle fallback.
    has_photo: bool = False


class PublicOrgOfficialsOut(BaseModel):
    org_name: str
    org_slug: str
    # Localized variants for the public booking page header (gov-panel /p/...).
    org_name_translations: dict[str, str] = {}
    officials: list[PublicOfficialOut]


class CreateBookingIn(BaseModel):
    official_id: uuid.UUID
    topic: str = Field(min_length=2, max_length=500)
    phone: str = Field(min_length=4, max_length=32)

    @field_validator("topic")
    @classmethod
    def topic_clean(cls, v: str) -> str:
        return v.strip()

    @field_validator("phone")
    @classmethod
    def phone_clean(cls, v: str) -> str:
        return v.strip()


class CreatedBookingOut(BaseModel):
    appointment_id: str
    official_name: str
    official_position: str
    queue_number: int
    scheduled_date: str
    scheduled_date_human: str
    reception_time: str
    phone_masked: str
    topic: str
    verification_token: str
    verification_url: str
    receipt_pdf_url: str


class VerifyOut(BaseModel):
    org_name: str
    org_name_translations: dict[str, str] = {}
    official_name: str
    official_position: str
    scheduled_date: str
    scheduled_date_human: str
    reception_time: str
    queue_number: int
    status: str
    topic: str
    phone_masked: str
    source: str
    created_at: str


async def _resolve_org_by_slug(session: DbSession, slug: str) -> Organization:
    org = (
        await session.execute(select(Organization).where(Organization.slug == slug))
    ).scalar_one_or_none()
    if org is None or org.status != "active":
        raise NotFoundError("org_not_found")
    return org


@router.get(
    "/orgs/{slug}/officials",
    response_model=PublicOrgOfficialsOut,
)
async def list_org_officials(
    slug: str, session: DbSession, request: Request
) -> PublicOrgOfficialsOut:
    """Online booking is disabled — operator's decision May 2026. Bookings
    must go through the physical kiosk now. The endpoint stays in code
    (revertible) but returns 410 Gone. Kiosk does not call this path —
    only the QabulBook web frontend did, and that route is removed from
    the gov-panel SPA in the same commit. Photo / receipt / verify
    endpoints below are still live because the kiosk uses them."""
    raise HTTPException(
        status_code=410,
        detail="online_booking_disabled — use the in-person kiosk",
    )


@router.get("/officials/{official_id}/photo.jpg")
async def get_official_photo(
    official_id: uuid.UUID, session: DbSession, request: Request
) -> Response:
    """Serve the official's uploaded photo, public.

    Same trust model as `list_org_officials`: an official's name, position,
    and face are public reference data for a government office. No org/slug
    in the URL because the kiosk has the bare ID from the officials list
    response and constructing a slug-aware URL on the client would just
    duplicate state. 404 when no photo on file."""
    if not limiter.allow(
        "public_official_photo", client_ip(request),
        max_per_window=300, window_seconds=60,
    ):
        raise TooManyRequestsError()

    o = (
        await session.execute(
            select(OrgKbOfficial).where(OrgKbOfficial.id == official_id)
        )
    ).scalar_one_or_none()
    if o is None or not o.photo_path:
        raise NotFoundError("photo_not_found")

    settings = get_settings()
    path = settings.photos_dir / o.photo_path
    if not path.exists() or not path.is_file():
        # Row points to a missing file — treat as no photo.
        raise NotFoundError("photo_not_found")

    media_type = "image/png" if o.photo_path.lower().endswith(".png") else "image/jpeg"
    return Response(
        content=path.read_bytes(),
        media_type=media_type,
        headers={
            # 1 day cache — photos rarely change; if they do, the kiosk
            # will pick it up on its next cold start. A future tweak
            # could embed an `updated_at` query token for cache busting.
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.post(
    "/orgs/{slug}/appointments",
    response_model=CreatedBookingOut,
    status_code=status.HTTP_201_CREATED,
)
async def book_appointment_public(
    slug: str,
    payload: CreateBookingIn,
    session: DbSession,
    request: Request,
) -> CreatedBookingOut:
    """Online appointment booking is disabled — operator's decision May
    2026. The physical kiosk is the only booking surface so the per-day
    25-visitor cap can be enforced with a single funnel. The endpoint
    stays here (returns 410) so we can revert quickly if needed; the
    QabulBook web frontend that called this is removed from gov-panel
    routes in the same commit."""
    raise HTTPException(
        status_code=410,
        detail="online_booking_disabled — use the in-person kiosk",
    )


@router.get("/appointments/verify/{token}", response_model=VerifyOut)
async def verify_appointment(
    token: str, session: DbSession, request: Request
) -> VerifyOut:
    if not limiter.allow(
        "public_verify", client_ip(request),
        max_per_window=60, window_seconds=60,
    ):
        raise TooManyRequestsError()
    a = (
        await session.execute(
            select(Appointment).where(Appointment.verification_token == token)
        )
    ).scalar_one_or_none()
    if a is None:
        raise NotFoundError()
    ofc = (
        await session.execute(
            select(OrgKbOfficial).where(OrgKbOfficial.id == a.official_id)
        )
    ).scalar_one()
    org = (
        await session.execute(select(Organization).where(Organization.id == a.org_id))
    ).scalar_one()
    return VerifyOut(
        org_name=org.name,
        org_name_translations=name_translations_for_response(org),
        official_name=ofc.name,
        official_position=ofc.position,
        scheduled_date=a.scheduled_date.isoformat(),
        scheduled_date_human=format_date_kk(a.scheduled_date),
        reception_time=ofc.reception_time,
        queue_number=a.queue_number,
        status=a.status,
        topic=a.topic_summary,
        phone_masked=mask_phone(a.visitor_phone),
        source=a.source,
        created_at=a.created_at.isoformat(),
    )


@router.get("/appointments/qr/{token}.png")
async def qr_png(
    token: str, session: DbSession, request: Request
) -> Response:
    """Stream the QR-coded verify URL as a 240x240 PNG. Used by the public
    booking page so we don't depend on a 3rd-party QR service."""
    if not limiter.allow(
        "public_qr", client_ip(request),
        max_per_window=60, window_seconds=60,
    ):
        raise TooManyRequestsError()
    a = (
        await session.execute(
            select(Appointment).where(Appointment.verification_token == token)
        )
    ).scalar_one_or_none()
    if a is None:
        raise NotFoundError()
    png = render_qr_png(build_verify_url(a.verification_token), size_px=240)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/appointments/receipt/{token}.pdf")
async def receipt_pdf(
    token: str, session: DbSession, request: Request, lang: str = "kk",
) -> Response:
    if not limiter.allow(
        "public_receipt", client_ip(request),
        max_per_window=10, window_seconds=60,
    ):
        raise TooManyRequestsError()
    # Allow-list the locale — anything else falls back to kk. Prevents
    # arbitrary strings sneaking into render_receipt_pdf's RECEIPT_STRINGS
    # lookup (which already falls back, but cheap to validate at the edge).
    locale = lang.lower() if lang and lang.lower() in {"kk", "uz", "ru"} else "kk"
    a = (
        await session.execute(
            select(Appointment).where(Appointment.verification_token == token)
        )
    ).scalar_one_or_none()
    if a is None:
        raise NotFoundError()
    ofc = (
        await session.execute(
            select(OrgKbOfficial).where(OrgKbOfficial.id == a.official_id)
        )
    ).scalar_one()
    org = (
        await session.execute(select(Organization).where(Organization.id == a.org_id))
    ).scalar_one()
    pdf = render_receipt_pdf(
        a, ofc, org, build_verify_url(a.verification_token), locale=locale,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="qabul-{a.queue_number:03d}.pdf"',
            "Cache-Control": "private, max-age=60",
        },
    )
