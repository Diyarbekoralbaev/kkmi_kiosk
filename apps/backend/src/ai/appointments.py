"""Shared qabul (reception) registration logic — kiosk WS + manual endpoint.

For the Council there is no official, no fixed date, and no queue number: the
citizen registers (phone + optional short reason) and staff call them back.
A verification token + receipt PDF/QR are still produced so the kiosk can print
and display a confirmation talon.
"""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..domain.appointment import Appointment
from ..domain.organization import Organization


def mint_verification_token() -> str:
    """32-byte URL-safe random token. Embedded in the QR code on the receipt."""
    return secrets.token_urlsafe(32)


def build_verify_url(token: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/p/qabul/verify/{token}"


def reference_no(appt: Appointment) -> str:
    """Short human-facing reference shown on the talon/receipt in place of the
    old date-based queue number, e.g. `Q-1A2B3C4D`."""
    return f"Q-{appt.id.hex[:8].upper()}"


def mask_phone(phone: str) -> str:
    """No-op pass-through (kiosk is anonymous; staff need the real number to
    call back). Kept so call sites don't change."""
    return phone


def normalize_phone(phone: str) -> str:
    """Strip non-digits, keep the leading + if present. Doesn't validate."""
    raw = phone.strip()
    if raw.startswith("+"):
        digits = "".join(c for c in raw[1:] if c.isdigit())
        return f"+{digits}"
    digits = "".join(c for c in raw if c.isdigit())
    # Heuristic: 9-digit Uzbekistan local format → prepend +998
    if len(digits) == 9:
        return f"+998{digits}"
    return digits or raw


@dataclass
class CreatedAppointment:
    """Result of a registration insert. PDF/QR are populated lazily by
    `render_appointment_artifacts` after the transaction commits."""
    appointment: Appointment
    org: Organization
    verify_url: str
    receipt_pdf: bytes = b""
    qr_png: bytes = b""


async def create_appointment(
    session: AsyncSession,
    *,
    org: Organization,
    visitor_phone: str,
    topic_summary: str = "",
    source: str,
    voice_session_id: uuid.UUID | None = None,
) -> CreatedAppointment:
    """Insert a qabul registration. No official / date / queue — the citizen
    is called back. Caller owns the transaction (flush, no commit)."""
    token = mint_verification_token()
    appt = Appointment(
        id=uuid.uuid4(),
        org_id=org.id,
        official_id=None,
        session_id=voice_session_id,
        visitor_phone=normalize_phone(visitor_phone),
        topic_summary=(topic_summary or "").strip(),
        scheduled_date=None,
        queue_number=None,
        status="pending",
        source=source,
        verification_token=token,
    )
    session.add(appt)
    await session.flush()
    return CreatedAppointment(
        appointment=appt,
        org=org,
        verify_url=build_verify_url(appt.verification_token),
    )


def render_appointment_artifacts(
    appt: Appointment,
    org: Organization,
    verify_url: str,
    *,
    locale: str = "kk",
) -> tuple[bytes, bytes]:
    """CPU-bound: render the printable receipt PDF + QR PNG. No DB calls.
    Returns empty bytes on failure so the caller can still respond."""
    from .receipt import render_qr_png, render_receipt_pdf  # local to avoid cycle
    try:
        pdf = render_receipt_pdf(appt, org, verify_url, locale=locale)
    except Exception:
        pdf = b""
    try:
        qr = render_qr_png(verify_url)
    except Exception:
        qr = b""
    return pdf, qr
