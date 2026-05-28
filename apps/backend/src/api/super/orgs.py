"""Super admin: organizations CRUD + credentials regenerate."""
from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from ...core import audit
from ...core.deps import DbSession, SuperAdmin
from ...core.errors import ConflictError, NotFoundError, ValidationError
from ...core.security import hash_password, random_slug_password
from ...core.seed import clone_defaults_into_org
from ...domain.application import Application
from ...domain.device import Device
from ...domain.organization import (
    ORG_NAME_LOCALES,
    OrgCredentials,
    Organization,
    address_translations_for_response,
    name_translations_for_response,
    work_hours_translations_for_response,
)

router = APIRouter(prefix="/api/super/orgs", tags=["super:orgs"])

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:64] or "org"


# ── Schemas ───────────────────────────────────────────────


def _validate_name_translations(v: dict[str, str]) -> dict[str, str]:
    """Trim, require every known locale (uz/kk/ru) to be non-empty, and
    reject extra keys so the form doesn't accumulate stale languages."""
    cleaned: dict[str, str] = {}
    for loc in ORG_NAME_LOCALES:
        raw = v.get(loc, "")
        s = (raw or "").strip()
        if not s:
            raise ValueError(f"name_translations.{loc} is required")
        if len(s) > 255:
            raise ValueError(f"name_translations.{loc} exceeds 255 chars")
        cleaned[loc] = s
    return cleaned


def _validate_optional_translations(
    v: dict[str, str] | None, field_name: str, max_len: int
) -> dict[str, str] | None:
    """Lenient counterpart to _validate_name_translations for the optional
    address/work_hours dicts: empty strings allowed, missing locales
    coerced to '', extra keys ignored. Returns a fully-shaped dict (every
    ORG_NAME_LOCALE key present) so the JSONB column always has a stable
    schema regardless of which locales the form filled in."""
    if v is None:
        return None
    cleaned: dict[str, str] = {}
    for loc in ORG_NAME_LOCALES:
        raw = v.get(loc, "")
        s = (raw or "").strip()
        if len(s) > max_len:
            raise ValueError(f"{field_name}.{loc} exceeds {max_len} chars")
        cleaned[loc] = s
    return cleaned


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip()
    if s == "":
        return ""
    if not _EMAIL_RE.match(s):
        raise ValueError("email is not a valid address")
    if len(s) > 255:
        raise ValueError("email exceeds 255 chars")
    return s


def _validate_helpline_phone(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip()
    if len(s) > 32:
        raise ValueError("helpline_phone exceeds 32 chars")
    return s


class OrgCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    """Legacy/canonical name. Optional now — if omitted the create handler
    derives it from `name_translations[locale]`. Kept on the wire so older
    clients can still POST a single name."""
    name_translations: dict[str, str] = Field(default_factory=dict)
    """Required for new orgs. Keys: uz, kk, ru. Each value 1-255 chars."""
    slug: str | None = Field(default=None, max_length=64)
    max_devices: int = Field(default=10, ge=1, le=10_000)
    locale: str = Field(default="kk", max_length=8)
    include_default_officials: bool = Field(default=False)
    # Optional contact fields. If omitted at create, the org row is created
    # with empty dicts/strings and super-admin fills them via PATCH later.
    address_translations: dict[str, str] | None = Field(default=None)
    email: str | None = Field(default=None, max_length=255)
    work_hours_translations: dict[str, str] | None = Field(default=None)
    helpline_phone: str | None = Field(default=None, max_length=32)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not _SLUG_RE.match(v):
            raise ValueError("slug must be lowercase alphanumeric with dashes")
        return v

    @field_validator("name_translations")
    @classmethod
    def validate_translations(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            return {}
        return _validate_name_translations(v)

    @field_validator("address_translations")
    @classmethod
    def validate_address(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return _validate_optional_translations(v, "address_translations", 500)

    @field_validator("work_hours_translations")
    @classmethod
    def validate_hours(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return _validate_optional_translations(v, "work_hours_translations", 120)

    @field_validator("email")
    @classmethod
    def validate_email_create(cls, v: str | None) -> str | None:
        return _validate_email(v)

    @field_validator("helpline_phone")
    @classmethod
    def validate_phone_create(cls, v: str | None) -> str | None:
        return _validate_helpline_phone(v)


class OrgUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    name_translations: dict[str, str] | None = Field(default=None)
    """Partial update — when present, must include every supported locale
    (uz/kk/ru). Use the GET payload as the baseline and edit fields you
    want changed; passing only one locale would otherwise drop the others."""
    status: str | None = Field(default=None)
    max_devices: int | None = Field(default=None, ge=1, le=10_000)
    address_translations: dict[str, str] | None = Field(default=None)
    email: str | None = Field(default=None, max_length=255)
    work_hours_translations: dict[str, str] | None = Field(default=None)
    helpline_phone: str | None = Field(default=None, max_length=32)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ("active", "suspended"):
            raise ValueError("status must be active or suspended")
        return v

    @field_validator("name_translations")
    @classmethod
    def validate_translations(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return None
        return _validate_name_translations(v)

    @field_validator("address_translations")
    @classmethod
    def validate_address_update(
        cls, v: dict[str, str] | None
    ) -> dict[str, str] | None:
        return _validate_optional_translations(v, "address_translations", 500)

    @field_validator("work_hours_translations")
    @classmethod
    def validate_hours_update(
        cls, v: dict[str, str] | None
    ) -> dict[str, str] | None:
        return _validate_optional_translations(v, "work_hours_translations", 120)

    @field_validator("email")
    @classmethod
    def validate_email_update(cls, v: str | None) -> str | None:
        return _validate_email(v)

    @field_validator("helpline_phone")
    @classmethod
    def validate_phone_update(cls, v: str | None) -> str | None:
        return _validate_helpline_phone(v)


class OrgOut(BaseModel):
    id: str
    slug: str
    name: str
    name_translations: dict[str, str]
    """Always populated for every supported locale — see
    `name_translations_for_response` for the fallback chain."""
    status: str
    max_devices: int
    locale: str
    devices_count: int = 0
    applications_count: int = 0
    # Contact info shown on the kiosk Contacts page + footer band. Always
    # populated for every supported locale (empty string where a locale
    # has no value yet) so the panel form has a stable shape.
    address_translations: dict[str, str] = Field(default_factory=dict)
    email: str = ""
    work_hours_translations: dict[str, str] = Field(default_factory=dict)
    helpline_phone: str = ""
    created_at: str
    updated_at: str


class OrgCreatedOut(OrgOut):
    credentials_username: str
    credentials_password: str
    """Plain-text password — shown ONCE; never returned again."""


class OrgListOut(BaseModel):
    items: list[OrgOut]
    total: int


class OrgCredentialsRegeneratedOut(BaseModel):
    username: str
    password: str


def _to_out(org: Organization, *, devices: int = 0, apps: int = 0) -> OrgOut:
    return OrgOut(
        id=str(org.id),
        slug=org.slug,
        name=org.name,
        name_translations=name_translations_for_response(org),
        status=org.status,
        max_devices=org.max_devices,
        locale=org.locale,
        devices_count=devices,
        applications_count=apps,
        address_translations=address_translations_for_response(org),
        email=org.email or "",
        work_hours_translations=work_hours_translations_for_response(org),
        helpline_phone=org.helpline_phone or "",
        created_at=org.created_at.isoformat(),
        updated_at=org.updated_at.isoformat(),
    )


async def _get_or_404(session: DbSession, org_id: uuid.UUID) -> Organization:
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFoundError("organization_not_found")
    return org


# ── Endpoints ─────────────────────────────────────────────


@router.get("", response_model=OrgListOut)
async def list_orgs(
    session: DbSession,
    _: SuperAdmin,
    search: str | None = Query(default=None, max_length=255),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> OrgListOut:
    stmt = select(Organization)
    count_stmt = select(func.count()).select_from(Organization)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            (func.lower(Organization.name).like(like))
            | (func.lower(Organization.slug).like(like))
        )
        count_stmt = count_stmt.where(
            (func.lower(Organization.name).like(like))
            | (func.lower(Organization.slug).like(like))
        )
    if status_filter:
        stmt = stmt.where(Organization.status == status_filter)
        count_stmt = count_stmt.where(Organization.status == status_filter)
    stmt = stmt.order_by(Organization.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(count_stmt)).scalar_one()

    items: list[OrgOut] = []
    for org in rows:
        devices_count = (
            await session.execute(
                select(func.count()).select_from(Device).where(Device.org_id == org.id)
            )
        ).scalar_one()
        apps_count = (
            await session.execute(
                select(func.count())
                .select_from(Application)
                .where(Application.org_id == org.id)
            )
        ).scalar_one()
        items.append(_to_out(org, devices=devices_count, apps=apps_count))
    return OrgListOut(items=items, total=int(total))


@router.post("", response_model=OrgCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_org(
    payload: OrgCreateIn,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> OrgCreatedOut:
    slug = payload.slug or _slugify(payload.name)
    if not _SLUG_RE.match(slug):
        raise ValidationError("invalid_slug")

    existing = (
        await session.execute(select(Organization).where(Organization.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("slug_taken")

    # If translations omitted, populate all three slots from the legacy
    # `name` so the row is never half-localized. The super-panel form
    # always sends translations; this branch is for API clients / scripts.
    translations = payload.name_translations or {
        loc: payload.name for loc in ORG_NAME_LOCALES
    }
    # Canonical name follows the create-time locale so the legacy column
    # has a sensible value (audit logs etc.).
    canonical = translations.get(payload.locale) or payload.name
    org = Organization(
        slug=slug,
        name=canonical,
        name_translations=translations,
        status="active",
        max_devices=payload.max_devices,
        locale=payload.locale,
        address_translations=payload.address_translations
        or {loc: "" for loc in ORG_NAME_LOCALES},
        email=payload.email or "",
        work_hours_translations=payload.work_hours_translations
        or {loc: "" for loc in ORG_NAME_LOCALES},
        helpline_phone=payload.helpline_phone or None,
        created_by_user_id=actor.id,
    )
    session.add(org)
    await session.flush()

    # Clone system defaults
    await clone_defaults_into_org(
        session, org, include_officials=payload.include_default_officials
    )

    # Generate org credentials (1-time plain shown, hash stored)
    password_plain = random_slug_password(length=20)
    creds = OrgCredentials(
        org_id=org.id,
        username=slug,
        password_hash=hash_password(password_plain),
    )
    session.add(creds)

    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="org.create",
        entity_type="organization",
        entity_id=org.id,
        after={"slug": org.slug, "name": org.name},
        request=request,
    )
    await session.flush()

    out = _to_out(org)
    return OrgCreatedOut(
        **out.model_dump(),
        credentials_username=slug,
        credentials_password=password_plain,
    )


@router.get("/{org_id}", response_model=OrgOut)
async def get_org(org_id: uuid.UUID, session: DbSession, _: SuperAdmin) -> OrgOut:
    org = await _get_or_404(session, org_id)
    devices_count = (
        await session.execute(
            select(func.count()).select_from(Device).where(Device.org_id == org_id)
        )
    ).scalar_one()
    apps_count = (
        await session.execute(
            select(func.count())
            .select_from(Application)
            .where(Application.org_id == org_id)
        )
    ).scalar_one()
    return _to_out(org, devices=devices_count, apps=apps_count)


@router.patch("/{org_id}", response_model=OrgOut)
async def update_org(
    org_id: uuid.UUID,
    payload: OrgUpdateIn,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> OrgOut:
    org = await _get_or_404(session, org_id)
    before: dict[str, Any] = {
        "name": org.name,
        "name_translations": dict(org.name_translations or {}),
        "status": org.status,
        "max_devices": org.max_devices,
        "address_translations": dict(org.address_translations or {}),
        "email": org.email,
        "work_hours_translations": dict(org.work_hours_translations or {}),
        "helpline_phone": org.helpline_phone,
    }
    if payload.name_translations is not None:
        org.name_translations = payload.name_translations
        # Keep the canonical `name` in lockstep with the org's primary locale
        # so audit logs and back-compat code paths see fresh data.
        canonical = payload.name_translations.get(org.locale)
        if canonical:
            org.name = canonical
    if payload.name is not None:
        org.name = payload.name
    if payload.status is not None:
        org.status = payload.status
    if payload.max_devices is not None:
        org.max_devices = payload.max_devices
    if payload.address_translations is not None:
        org.address_translations = payload.address_translations
    if payload.email is not None:
        org.email = payload.email
    if payload.work_hours_translations is not None:
        org.work_hours_translations = payload.work_hours_translations
    if payload.helpline_phone is not None:
        # Empty string saved as NULL so weather/heartbeat treat "no helpline"
        # uniformly; non-empty trims+stores verbatim.
        org.helpline_phone = payload.helpline_phone or None
    after = {
        "name": org.name,
        "name_translations": dict(org.name_translations or {}),
        "status": org.status,
        "max_devices": org.max_devices,
        "address_translations": dict(org.address_translations or {}),
        "email": org.email,
        "work_hours_translations": dict(org.work_hours_translations or {}),
        "helpline_phone": org.helpline_phone,
    }
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="org.update",
        entity_type="organization",
        entity_id=org.id,
        before=before,
        after=after,
        request=request,
    )
    return _to_out(org)


@router.post(
    "/{org_id}/credentials/regenerate",
    response_model=OrgCredentialsRegeneratedOut,
)
async def regenerate_credentials(
    org_id: uuid.UUID,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> OrgCredentialsRegeneratedOut:
    org = await _get_or_404(session, org_id)
    creds = (
        await session.execute(
            select(OrgCredentials).where(OrgCredentials.org_id == org.id)
        )
    ).scalar_one_or_none()
    new_password = random_slug_password(length=20)
    if creds is None:
        creds = OrgCredentials(
            org_id=org.id,
            username=org.slug,
            password_hash=hash_password(new_password),
        )
        session.add(creds)
    else:
        creds.password_hash = hash_password(new_password)
        creds.last_rotated_at = func.now()
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="org.credentials_regenerate",
        entity_type="organization",
        entity_id=org.id,
        request=request,
    )
    return OrgCredentialsRegeneratedOut(username=creds.username, password=new_password)
