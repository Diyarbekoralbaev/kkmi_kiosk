"""Shared application (murajat / citizen request) insert logic.

Both the kiosk WS voice flow and the kiosk manual-submit HTTP endpoint
land here so behavior (category_slug resolution, audit shape, default
status) stays identical regardless of source. Mirrors the pattern in
`ai/appointments.py` for qabul bookings.

The voice flow previously inlined this insert in `api/kiosk_ws.py`;
extracting it here is what lets the manual REST endpoint reuse it
without duplicating SQL.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.application import Application
from ..domain.category import ApplicationCategory


async def create_application(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    topic: str,
    body: str,
    phone: str,
    category_slug: str,
    source: str,
    voice_session_id: uuid.UUID | None = None,
) -> Application:
    """Insert a new Application row with category_slug → category_id
    resolution.

    Unknown / soft-deleted slugs land as `category_id = NULL` so the
    reviewer can correct the category later from the gov-panel without
    blocking submission. Same lenient behavior the voice flow has
    always had.

    Caller owns the transaction — the function flushes but does not
    commit. `source` is one of `"kiosk_voice"` / `"kiosk_manual"` /
    similar; callers are responsible for `audit.record(...)` afterwards
    so the audit row sits in the same transaction.
    """
    category_id = None
    if category_slug:
        category_id = (
            await session.execute(
                select(ApplicationCategory.id).where(
                    ApplicationCategory.slug == category_slug,
                    ApplicationCategory.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    app = Application(
        id=uuid.uuid4(),
        org_id=org_id,
        session_id=voice_session_id,
        topic=topic.strip(),
        body=body.strip(),
        phone=phone,
        status="new",
        category_id=category_id,
    )
    session.add(app)
    await session.flush()
    return app
