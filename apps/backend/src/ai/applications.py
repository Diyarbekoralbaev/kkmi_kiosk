"""Shared application insert logic — murajaat (appeal) + feedback.

Both the kiosk WS voice flow and the kiosk manual-submit HTTP endpoints land
here so behavior (audit shape, default status) stays identical regardless of
source. Mirrors the pattern in `ai/appointments.py`.

For the Council there is no category picker: a murajaat is just topic + body +
phone. Feedback rides on the same `applications` table via the `kind`
discriminator + `feedback_type` (shaǵım / usınıs / minnetdarshılıq).
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.application import KIND_FEEDBACK, KIND_MURAJAAT, Application


async def create_application(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    topic: str,
    body: str,
    phone: str,
    source: str,
    kind: str = KIND_MURAJAAT,
    feedback_type: str | None = None,
    voice_session_id: uuid.UUID | None = None,
) -> Application:
    """Insert a new Application row.

    Caller owns the transaction — the function flushes but does not commit.
    `source` (e.g. "kiosk_voice" / "kiosk_manual") is informational for the
    caller's `audit.record(...)`; it is not stored on the row.
    """
    app = Application(
        id=uuid.uuid4(),
        org_id=org_id,
        session_id=voice_session_id,
        topic=topic.strip(),
        body=body.strip(),
        phone=phone,
        status="new",
        kind=kind,
        feedback_type=feedback_type,
    )
    session.add(app)
    await session.flush()
    return app


async def create_feedback(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    feedback_type: str,
    text: str,
    phone: str,
    source: str,
    voice_session_id: uuid.UUID | None = None,
) -> Application:
    """Insert a feedback row (kind=feedback). `topic` stays empty; the free
    text goes in `body`, the kind (shaǵım/usınıs/minnetdarshılıq) in
    `feedback_type`."""
    return await create_application(
        session,
        org_id=org_id,
        topic="",
        body=text,
        phone=phone,
        source=source,
        kind=KIND_FEEDBACK,
        feedback_type=feedback_type,
        voice_session_id=voice_session_id,
    )
