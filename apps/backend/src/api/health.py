"""GET /health — liveness + DB ping."""
from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import text

from ..core.deps import DbSession

router = APIRouter(tags=["health"])


@router.get("/health", status_code=status.HTTP_200_OK)
async def health(session: DbSession) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
        db_ok = "ok"
    except Exception:
        db_ok = "down"
    return {"status": "ok", "db": db_ok}
