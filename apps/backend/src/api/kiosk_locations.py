"""Kiosk reference data + citizen lookup, proxied from cabinet.murajat.uz.

GET /api/kiosk/locations → districts + quarters. The kiosk fetches this once on
                           open and caches it in-memory for the manual murajat
                           form's tuman/mahalla dropdowns.
GET /api/kiosk/personal  → look up a citizen by phone so the kiosk (or the AI)
                           can ask «Siz {name} misiz?» before collecting details.

Both require device auth; the upstream bearer token never leaves the backend.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, Query

from ..core import murajat
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request

router = APIRouter(prefix="/api/kiosk", tags=["kiosk:locations"])


@router.get("/locations")
async def get_locations(
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict:
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    return await murajat.get_locations()


@router.get("/personal")
async def lookup_personal(
    session: DbSession,
    phone: str = Query(min_length=4, max_length=32),
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict:
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    return await murajat.lookup_personal(phone)
