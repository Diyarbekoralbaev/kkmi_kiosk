"""Kiosk manual murajat (appeal) submission — proxied to cabinet.murajat.uz.

The visitor fills the touch form (phone → lookup → confirm name, or full citizen
details → appeal text) and the kiosk POSTs it here. We forward to the external
Council cabinet; nothing is stored locally. Citizen lookup by phone and the
districts/quarters reference lists live in `kiosk_locations.py`.

No categories, no officials, no qabul, no feedback — the Council kiosk does one
thing: file an appeal to the external cabinet.
"""
from __future__ import annotations

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..core import murajat
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request

router = APIRouter(prefix="/api/kiosk", tags=["kiosk:appeal"])


class CreateAppealIn(BaseModel):
    phone: str = Field(min_length=4, max_length=32)
    text: str = Field(min_length=1, max_length=10_000)
    # true = an existing citizen confirmed their identity → only phone + text are
    # forwarded and the registry record is left unchanged. false = a new citizen
    # or «men emas» → all personal fields below are required upstream.
    confirmed: bool = False
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    birth_date: str | None = None  # YYYY-MM-DD
    gender: int | None = None  # 1 = erkak, 0 = ayol
    district_id: int | None = None
    quarter_id: int | None = None
    address: str | None = Field(default=None, max_length=500)
    high_organization: str | None = Field(default=None, max_length=255)


class CreateAppealOut(BaseModel):
    appeal_number: str
    status: str


@router.post("/appeal", response_model=CreateAppealOut, status_code=201)
async def create_kiosk_appeal(
    body: CreateAppealIn,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> CreateAppealOut:
    # Device auth only — the appeal is stored upstream, not in our DB.
    await resolve_device_from_signed_request(session, x_kiosk_auth)
    fields = body.model_dump(exclude_none=True)
    data = await murajat.submit_appeal(fields)
    appeal = data.get("appeal") or {}
    return CreateAppealOut(
        appeal_number=str(appeal.get("appeal_number") or ""),
        status=str(appeal.get("status") or "pending"),
    )
