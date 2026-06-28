"""Thin proxy to the external Joqari Kenes murajat cabinet (cabinet.murajat.uz).

The kiosk's appeals (murajaatlar) are stored in THEIR Laravel system, not in our
DB. The backend only forwards: look up a citizen by phone, submit an appeal, and
serve the districts/quarters reference lists. Those lists rarely change, so they
are cached in-memory (TTL) — we don't hit upstream on every kiosk session and the
AI prompt embeds the districts without a network round-trip.

Auth: a static Bearer token minted on their server (`php artisan kiosk:token`),
read from KIOSK_MURAJAT_TOKEN. It lives only on the backend — never on a kiosk.
districts/quarters are *open* upstream endpoints (no token needed).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import structlog

from .config import get_settings
from .errors import ServiceUnavailableError, UpstreamError

logger = structlog.get_logger(__name__)

# districts/quarters change rarely; cache for hours so the AI prompt + the kiosk
# dropdowns don't hammer upstream. Served stale on upstream failure.
_LOCATIONS_TTL_SEC = 6 * 3600
_locations: dict[str, Any] | None = None
_locations_at: float = 0.0
_locations_lock = asyncio.Lock()


def _phone9(phone: str) -> str:
    """Upstream keys citizens by the bare 9-digit phone (e.g. 901234567)."""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    return digits[-9:] if len(digits) >= 9 else digits


def _form_value(v: Any) -> str:
    """Laravel boolean validation accepts 'true'/'false'/1/0 — not Python's
    capitalised 'True'/'False'. Serialise bools as lowercase; everything else
    via str()."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _require_token() -> tuple[str, str]:
    s = get_settings()
    base = (s.murajat_api_base or "").rstrip("/")
    token = s.kiosk_murajat_token.get_secret_value()
    if not base or not token:
        raise ServiceUnavailableError("murajat_not_configured")
    return base, token


def _authed_client(base: str, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base,
        timeout=get_settings().murajat_timeout,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )


async def lookup_personal(phone: str) -> dict[str, Any]:
    """GET /kiosk/personal?phone= → {"exists": bool, "personal"?: {...}}."""
    base, token = _require_token()
    try:
        async with _authed_client(base, token) as c:
            r = await c.get("/kiosk/personal", params={"phone": _phone9(phone)})
        r.raise_for_status()
        data = r.json()
    except ServiceUnavailableError:
        raise
    except Exception as e:
        logger.warning("murajat_lookup_failed", error=str(e), error_type=type(e).__name__)
        raise UpstreamError(cause=e) from e
    return data if isinstance(data, dict) else {"exists": False}


async def submit_appeal(fields: dict[str, Any]) -> dict[str, Any]:
    """POST /kiosk/appeal (multipart) → {"status", "message", "appeal": {...}}.

    `fields` is the upstream field set: phone + text, optional confirmed, and (for
    new / «men emas» citizens) first_name … address. Sent as multipart/form-data
    so a future jk_file attachment slots in without reshaping.
    """
    base, token = _require_token()
    form = {k: _form_value(v) for k, v in fields.items() if v is not None}
    form["phone"] = _phone9(form.get("phone", ""))
    try:
        async with _authed_client(base, token) as c:
            r = await c.post("/kiosk/appeal", data=form)
        if r.status_code == 422:
            logger.warning("murajat_appeal_422", upstream=_safe_json(r))
            raise UpstreamError("appeal_rejected")
        r.raise_for_status()
        data = r.json()
    except (UpstreamError, ServiceUnavailableError):
        raise
    except Exception as e:
        logger.warning("murajat_submit_failed", error=str(e), error_type=type(e).__name__)
        raise UpstreamError(cause=e) from e
    return data


async def get_locations(force: bool = False) -> dict[str, Any]:
    """{"districts": [...], "quarters": [...]} — cached in-memory (TTL).

    Each row slimmed to id (+district_id for quarters) and the four name variants
    (uz/oz/ru/qq). Served stale on upstream failure rather than breaking the kiosk.
    """
    global _locations, _locations_at
    if not force and _fresh():
        return _locations  # type: ignore[return-value]
    async with _locations_lock:
        if not force and _fresh():
            return _locations  # type: ignore[return-value]
        base = (get_settings().murajat_api_base or "").rstrip("/")
        if not base:
            raise ServiceUnavailableError("murajat_not_configured")
        try:
            async with httpx.AsyncClient(
                base_url=base,
                timeout=get_settings().murajat_timeout,
                headers={"Accept": "application/json"},
            ) as c:
                dr = await c.get("/api/districts")
                qr = await c.get("/api/quarters")
            dr.raise_for_status()
            qr.raise_for_status()
            districts = [_slim(d, with_district=False) for d in _as_list(dr.json())]
            quarters = [_slim(q, with_district=True) for q in _as_list(qr.json())]
        except Exception as e:
            logger.warning(
                "murajat_locations_failed", error=str(e), error_type=type(e).__name__
            )
            if _locations is not None:
                return _locations
            raise UpstreamError(cause=e) from e
        _locations = {"districts": districts, "quarters": quarters}
        _locations_at = time.monotonic()
        logger.info(
            "murajat_locations_cached", districts=len(districts), quarters=len(quarters)
        )
        return _locations


async def quarters_for_district(district_id: int) -> list[dict[str, Any]]:
    """The cached quarters filtered to one district — small enough for the AI to
    match a spoken mahalla against."""
    locs = await get_locations()
    return [q for q in locs["quarters"] if q.get("district_id") == district_id]


def _fresh() -> bool:
    return (
        _locations is not None
        and (time.monotonic() - _locations_at) < _LOCATIONS_TTL_SEC
    )


def _as_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", []) or []
    return []


def _slim(row: dict[str, Any], *, with_district: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.get("id"),
        "name_uz": row.get("name_uz"),
        "name_oz": row.get("name_oz"),
        "name_ru": row.get("name_ru"),
        "name_qq": row.get("name_qq"),
    }
    if with_district:
        out["district_id"] = row.get("district_id")
    return out


def _safe_json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except Exception:
        return r.text[:500]
