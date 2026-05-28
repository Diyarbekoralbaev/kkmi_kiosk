"""Shared appointment booking logic — kiosk WS dispatch and public booking
endpoint both go through here so the queue-numbering, receipt rendering, and
audit semantics stay identical regardless of source.
"""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.timezone import now_local
from ..domain.ai_config import OrgKbOfficial
from ..domain.appointment import STATUS_CANCELLED, Appointment
from ..domain.organization import Organization

# Per-official, per-day visitor cap. Reasoning: one official can physically
# receive ~25 visitors in a working day. The 26th is automatically rolled to
# the next reception day. Set as a module constant rather than a column so
# operations can adjust it in one place without a schema migration.
PER_DAY_CAP: int = 25

# Safety bound on the forward-search horizon when every near-term reception
# day is full. ~10 years out — if we ever hit this in practice something is
# very wrong (an official with 25 booked every week for a decade).
MAX_LOOKAHEAD_WEEKS: int = 520

# `mon`..`sun` → Python weekday (Mon=0, Sun=6)
DAY_TO_WEEKDAY: dict[str, int] = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


def _reception_ended(reception_time: str, now: datetime) -> bool:
    """True if `reception_time` ("HH:MM-HH:MM") names a window whose END is
    already past `now`'s local time. Lets same-day booking skip to next week
    once the official's reception window has closed — a visitor arriving after
    it can't be received today, so booking them for today's finished session
    would be wrong.

    Defensive: empty or unparseable reception_time → False (never skip), so a
    misconfigured time string can't strand every booking a week out.
    """
    try:
        end = reception_time.split("-", 1)[1].strip()  # "10:00-12:00" → "12:00"
        hh, mm = (int(x) for x in end.split(":", 1))
        return (now.hour, now.minute) > (hh, mm)
    except Exception:
        return False


def compute_next_reception_date(
    reception_day: str,
    reception_time: str = "",
    *,
    now: datetime | None = None,
    today: date | None = None,
) -> date:
    """Next occurrence of `reception_day` on or after today, in Asia/Tashkent.

    If today matches `reception_day` AND the reception window has NOT ended
    yet, today is returned (same-day booking while the official is still
    receiving). Once today's window has closed, the visitor rolls to next
    week's occurrence — they can't be received today. Empty/unknown
    reception_day → today + 1 as a safe fallback.

    Day boundaries use local (Tashkent) time, not UTC, so the "business day"
    matches the wall clock the kiosks and staff actually see.
    """
    now = now or now_local()
    today = today or now.date()
    target = DAY_TO_WEEKDAY.get((reception_day or "").lower())
    if target is None:
        return today + timedelta(days=1)
    delta = (target - today.weekday()) % 7
    candidate = today + timedelta(days=delta)
    # Same-day, but the reception window already closed → next week's session.
    if delta == 0 and _reception_ended(reception_time, now):
        candidate += timedelta(days=7)
    return candidate


async def compute_next_available_reception_date(
    session: AsyncSession,
    official: OrgKbOfficial,
    *,
    today: date | None = None,
    cap: int = PER_DAY_CAP,
    max_weeks: int = MAX_LOOKAHEAD_WEEKS,
) -> date:
    """Pick the earliest reception day for `official` whose live appointment
    count is below `cap`. Cancelled bookings free their slot — they're
    excluded from the count — so a cancellation today opens a slot for the
    next new visitor without disturbing anyone already booked for later
    dates.

    Existing bookings are immutable: once a visitor has a queue number and
    a receipt, this function never moves them to a different day. Only
    fresh bookings see the most up-to-date count.

    Algorithm: start at `compute_next_reception_date()` and step forward by
    7 days while the count is at or above `cap`. Returns the first
    available date.

    `max_weeks` is a safety bound, not a business rule — if we hit it the
    system has a much bigger problem than the cap. Realistic ceiling is
    ~10 years out."""
    candidate = compute_next_reception_date(
        official.reception_day, official.reception_time, today=today
    )
    for _ in range(max_weeks):
        count = (
            await session.execute(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.official_id == official.id)
                .where(Appointment.scheduled_date == candidate)
                .where(Appointment.status != STATUS_CANCELLED)
            )
        ).scalar_one()
        if int(count) < cap:
            return candidate
        candidate = candidate + timedelta(days=7)
    raise RuntimeError(
        f"no_reception_slot_within_{max_weeks}_weeks "
        f"(official={official.id} reception_day={official.reception_day})"
    )


def mint_verification_token() -> str:
    """32-byte URL-safe random token. Embedded in the QR code on the receipt."""
    return secrets.token_urlsafe(32)


def build_verify_url(token: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/p/qabul/verify/{token}"


def mask_phone(phone: str) -> str:
    """No-op pass-through. See receipt.mask_phone — operator decided
    masking adds no value here. Kept as a function so call sites don't
    have to change; the `phone_masked` wire field now carries the raw
    number."""
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
    """Result of an appointment insert. The PDF/QR fields are populated
    lazily by `render_appointment_artifacts` — `create_appointment` itself
    no longer renders them so the DB transaction can commit before the
    CPU-bound ReportLab/QR work starts (previously the transaction stayed
    open through PDF rendering, holding a row lock on the
    (official_id, scheduled_date) pair for ~100 ms per booking)."""
    appointment: Appointment
    official: OrgKbOfficial
    org: Organization
    verify_url: str
    receipt_pdf: bytes = b""
    qr_png: bytes = b""


async def create_appointment(
    session: AsyncSession,
    *,
    org: Organization,
    official: OrgKbOfficial,
    visitor_phone: str,
    topic_summary: str,
    source: str,
    voice_session_id: uuid.UUID | None = None,
    today: date | None = None,
) -> CreatedAppointment:
    """Insert a new Appointment row + compute queue_number.

    Idempotent only by verification_token uniqueness — caller should not retry
    blindly. The function retries on `(official_id, scheduled_date,
    queue_number)` collisions which can happen under concurrent inserts; up to
    3 attempts.

    Returns a CreatedAppointment with EMPTY `receipt_pdf` and `qr_png` —
    the caller must call `render_appointment_artifacts(...)` after the
    surrounding transaction commits to populate those bytes.
    """
    last_err: Exception | None = None
    for _attempt in range(3):
        # Re-pick the scheduled day on EVERY attempt: a concurrent writer
        # may have filled our target day between attempts, in which case
        # we want the next free day rather than re-trying the same full
        # one and failing forever on the queue_number unique constraint.
        scheduled = await compute_next_available_reception_date(
            session, official, today=today
        )
        # Re-read max queue number on each attempt — another writer may have
        # claimed our slot between attempts.
        max_q = (
            await session.execute(
                select(func.coalesce(func.max(Appointment.queue_number), 0))
                .where(Appointment.official_id == official.id)
                .where(Appointment.scheduled_date == scheduled)
            )
        ).scalar_one()
        queue_number = int(max_q) + 1
        token = mint_verification_token()
        appt = Appointment(
            id=uuid.uuid4(),
            org_id=org.id,
            official_id=official.id,
            session_id=voice_session_id,
            visitor_phone=normalize_phone(visitor_phone),
            topic_summary=topic_summary.strip(),
            scheduled_date=scheduled,
            queue_number=queue_number,
            status="pending",
            source=source,
            verification_token=token,
        )
        session.add(appt)
        try:
            await session.flush()
            break
        except IntegrityError as e:
            last_err = e
            await session.rollback()
            # The session is now expired; caller is expected to start a fresh
            # transaction by re-entering this function. We re-raise after retries.
            continue
    else:
        # All attempts exhausted.
        raise last_err or RuntimeError("appointment_insert_failed")

    return CreatedAppointment(
        appointment=appt,
        official=official,
        org=org,
        verify_url=build_verify_url(appt.verification_token),
    )


def render_appointment_artifacts(
    appt: Appointment,
    official: OrgKbOfficial,
    org: Organization,
    verify_url: str,
    *,
    locale: str = "kk",
) -> tuple[bytes, bytes]:
    """CPU-bound: render the printable receipt PDF + QR PNG. No DB calls.

    Callers should invoke this AFTER the appointment transaction has
    committed, so the row lock is released before ReportLab generates the
    PDF (~100 ms) and qrcode generates the PNG (~20 ms). On failure (e.g.
    font missing) returns empty bytes so the caller can still respond to
    the kiosk with the appointment metadata — the visitor sees the queue
    number on screen, just no QR/print until the bug is fixed.

    `locale` selects which language the printed receipt uses (see
    `render_receipt_pdf` for supported values).
    """
    from .receipt import render_qr_png, render_receipt_pdf  # local to avoid cycle
    try:
        pdf = render_receipt_pdf(appt, official, org, verify_url, locale=locale)
    except Exception:
        pdf = b""
    try:
        qr = render_qr_png(verify_url)
    except Exception:
        qr = b""
    return pdf, qr
