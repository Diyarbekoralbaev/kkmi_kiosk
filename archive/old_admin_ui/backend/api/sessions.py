"""
Kiosk sessions REST API — list, detail, metrics.
Reads from admin_ui/backend/kiosk_session_store.py (SQLite).
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict

from kiosk_session_store import get_store

router = APIRouter()


@router.get("/")
async def list_sessions(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    today: bool = Query(False),
) -> Dict[str, Any]:
    """List kiosk sessions, newest first."""
    store = get_store()
    items = store.list_sessions(limit=limit, offset=offset, today_only=today)
    return {"items": items, "count": len(items)}


@router.get("/metrics")
async def metrics() -> Dict[str, Any]:
    """Dashboard metrics: today's sessions, avg duration, error count, recent 5."""
    return get_store().get_metrics()


@router.get("/{session_id}")
async def get_session(session_id: str) -> Dict[str, Any]:
    """Get a single session with full transcript."""
    session = get_store().get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
