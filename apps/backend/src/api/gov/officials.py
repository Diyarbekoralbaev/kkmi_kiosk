"""Gov admin: hokim/orinbosarlar (officials) — knowledge-base CRUD.

Lives at /api/gov/officials (not under /settings/ai/) — it's reference data
that AI uses, but conceptually it's a directory the gov manages directly.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ...core import audit
from ...core.config import get_settings
from ...core.deps import CurrentOrg, DbSession, OrgAdmin
from ...core.errors import NotFoundError, ValidationError
from ...domain.ai_config import DAY_KEYS, OrgKbOfficial

router = APIRouter(prefix="/api/gov/officials", tags=["gov:officials"])


ROLE_KEYS = ("chief", "deputy")

# Photo upload constraints. 2 MB is comfortably more than enough for a
# 1024×1024 JPEG of a face — anything larger is either an attack or a
# user uploading a 4K phone snap they didn't crop.
PHOTO_MAX_BYTES = 2 * 1024 * 1024
PHOTO_ALLOWED_EXT = ("jpg", "jpeg", "png")
# Magic-byte signatures. The Content-Type header from the client is
# advisory; we trust the first few bytes instead so a malicious upload
# can't pretend to be an image.
PHOTO_MAGIC = {
    "jpg": b"\xff\xd8\xff",
    "jpeg": b"\xff\xd8\xff",
    "png": b"\x89PNG\r\n\x1a\n",
}


class OfficialOut(BaseModel):
    id: str
    name: str
    position: str
    responsibilities: str
    reception_day: str
    reception_time: str
    order: int
    # 'chief' = hokim (single per org), 'deputy' = orinbasar (many).
    role: str = "deputy"
    # True iff a photo has been uploaded. UI uses this to render either
    # the photo (fetched from /api/public/officials/{id}/photo.jpg) or
    # an initials-circle fallback. We never return the bare filename
    # because clients shouldn't need to know the on-disk path.
    has_photo: bool = False


class OfficialListOut(BaseModel):
    items: list[OfficialOut]
    total: int


class OfficialIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    position: str = Field(min_length=1, max_length=255)
    responsibilities: str = Field(default="", max_length=2000)
    reception_day: str = Field(default="", max_length=8)
    reception_time: str = Field(default="", max_length=64)
    order: int = Field(default=0, ge=0, le=999)
    role: str = Field(default="deputy", max_length=16)

    @field_validator("reception_day")
    @classmethod
    def day_valid(cls, v: str) -> str:
        if v == "":
            return v
        if v not in DAY_KEYS:
            raise ValueError(f"reception_day must be one of {DAY_KEYS} or empty")
        return v

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        if v not in ROLE_KEYS:
            raise ValueError(f"role must be one of {ROLE_KEYS}")
        return v


class OfficialPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    position: str | None = Field(default=None, max_length=255)
    responsibilities: str | None = Field(default=None, max_length=2000)
    reception_day: str | None = Field(default=None, max_length=8)
    reception_time: str | None = Field(default=None, max_length=64)
    order: int | None = Field(default=None, ge=0, le=999)
    role: str | None = Field(default=None, max_length=16)

    @field_validator("reception_day")
    @classmethod
    def day_valid(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if v not in DAY_KEYS:
            raise ValueError(f"reception_day must be one of {DAY_KEYS} or empty")
        return v

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in ROLE_KEYS:
            raise ValueError(f"role must be one of {ROLE_KEYS}")
        return v


def _to_out(o: OrgKbOfficial) -> OfficialOut:
    return OfficialOut(
        id=str(o.id),
        name=o.name,
        position=o.position,
        responsibilities=o.responsibilities,
        reception_day=o.reception_day,
        reception_time=o.reception_time,
        order=o.order,
        role=o.role,
        has_photo=bool(o.photo_path),
    )


def _delete_photo_file(o: OrgKbOfficial) -> None:
    """Best-effort delete of an official's photo file. Errors are
    swallowed — a missing/unwritable file shouldn't block the API call
    (DB row state is what the rest of the system cares about)."""
    if not o.photo_path:
        return
    try:
        p = get_settings().photos_dir / o.photo_path
        if p.exists():
            p.unlink()
    except Exception:
        pass


@router.get("", response_model=OfficialListOut)
async def list_officials(
    session: DbSession, _: OrgAdmin, org: CurrentOrg
) -> OfficialListOut:
    rows = (
        await session.execute(
            select(OrgKbOfficial)
            .where(OrgKbOfficial.org_id == org.id)
            .order_by(OrgKbOfficial.order, OrgKbOfficial.created_at)
        )
    ).scalars().all()
    return OfficialListOut(items=[_to_out(r) for r in rows], total=len(rows))


@router.get("/{official_id}", response_model=OfficialOut)
async def get_official(
    official_id: uuid.UUID, session: DbSession, _: OrgAdmin, org: CurrentOrg
) -> OfficialOut:
    o = (
        await session.execute(
            select(OrgKbOfficial).where(
                OrgKbOfficial.id == official_id, OrgKbOfficial.org_id == org.id
            )
        )
    ).scalar_one_or_none()
    if o is None:
        raise NotFoundError()
    return _to_out(o)


@router.post("", response_model=OfficialOut, status_code=status.HTTP_201_CREATED)
async def create_official(
    payload: OfficialIn,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
) -> OfficialOut:
    o = OrgKbOfficial(
        org_id=org.id,
        name=payload.name,
        position=payload.position,
        responsibilities=payload.responsibilities,
        reception_day=payload.reception_day,
        reception_time=payload.reception_time,
        order=payload.order,
        role=payload.role,
    )
    session.add(o)
    await session.flush()
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="official.create",
        entity_type="org_kb_official",
        entity_id=o.id,
        after={"name": o.name, "position": o.position},
        request=request,
    )
    return _to_out(o)


@router.patch("/{official_id}", response_model=OfficialOut)
async def update_official(
    official_id: uuid.UUID,
    payload: OfficialPatchIn,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
) -> OfficialOut:
    o = (
        await session.execute(
            select(OrgKbOfficial).where(
                OrgKbOfficial.id == official_id, OrgKbOfficial.org_id == org.id
            )
        )
    ).scalar_one_or_none()
    if o is None:
        raise NotFoundError()
    before = {"name": o.name, "position": o.position}
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(o, k, v)
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="official.update",
        entity_type="org_kb_official",
        entity_id=o.id,
        before=before,
        after={"name": o.name, "position": o.position},
        request=request,
    )
    return _to_out(o)


@router.delete("/{official_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_official(
    official_id: uuid.UUID,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
) -> None:
    o = (
        await session.execute(
            select(OrgKbOfficial).where(
                OrgKbOfficial.id == official_id, OrgKbOfficial.org_id == org.id
            )
        )
    ).scalar_one_or_none()
    if o is None:
        raise NotFoundError()
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="official.delete",
        entity_type="org_kb_official",
        entity_id=o.id,
        before={"name": o.name, "position": o.position},
        request=request,
    )
    # Photo on disk is orphaned the moment the row is gone — clean it up
    # synchronously so the photos directory doesn't grow unboundedly with
    # ex-employees of a tenant.
    _delete_photo_file(o)
    await session.delete(o)


# ── Photo upload / delete ─────────────────────────────────────────────────


@router.post("/{official_id}/photo", response_model=OfficialOut)
async def upload_official_photo(
    official_id: uuid.UUID,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
    file: UploadFile = File(...),
) -> OfficialOut:
    """Upload (or replace) an official's face photo. Validates magic
    bytes — Content-Type header from the client is untrusted. Stores
    on disk under settings.photos_dir as `{id}.{ext}`."""
    o = (
        await session.execute(
            select(OrgKbOfficial).where(
                OrgKbOfficial.id == official_id, OrgKbOfficial.org_id == org.id
            )
        )
    ).scalar_one_or_none()
    if o is None:
        raise NotFoundError()

    # Guess extension from filename — only used to pick the magic-byte
    # signature to validate against; the real check is the bytes.
    name = (file.filename or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in PHOTO_ALLOWED_EXT:
        raise ValidationError("photo_invalid_extension")
    if ext == "jpeg":
        ext = "jpg"

    # Read fully into memory — cap at 2 MB. Reading 2 MB + 1 byte then
    # checking length catches "tried to upload a giant file" without
    # buffering an unbounded amount.
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(64 * 1024):
        chunks.append(chunk)
        total += len(chunk)
        if total > PHOTO_MAX_BYTES:
            raise ValidationError("photo_too_large")
    data = b"".join(chunks)
    if len(data) == 0:
        raise ValidationError("photo_empty")
    if not data.startswith(PHOTO_MAGIC[ext]):
        raise ValidationError("photo_invalid_format")

    settings = get_settings()
    photos_dir: Path = settings.photos_dir
    photos_dir.mkdir(parents=True, exist_ok=True)

    # If the previous photo had a different extension (e.g. .png → .jpg),
    # delete the old file BEFORE writing the new one — otherwise the old
    # file would be orphaned on disk while photo_path now points at the
    # new file.
    if o.photo_path and o.photo_path != f"{o.id}.{ext}":
        _delete_photo_file(o)

    target = photos_dir / f"{o.id}.{ext}"
    target.write_bytes(data)
    o.photo_path = target.name

    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="official.photo.upload",
        entity_type="org_kb_official",
        entity_id=o.id,
        after={"photo_path": o.photo_path, "size": total},
        request=request,
    )
    return _to_out(o)


@router.delete("/{official_id}/photo", response_model=OfficialOut)
async def delete_official_photo(
    official_id: uuid.UUID,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
) -> OfficialOut:
    o = (
        await session.execute(
            select(OrgKbOfficial).where(
                OrgKbOfficial.id == official_id, OrgKbOfficial.org_id == org.id
            )
        )
    ).scalar_one_or_none()
    if o is None:
        raise NotFoundError()
    if not o.photo_path:
        # Idempotent — already no photo. Return the row state so the UI
        # can refresh its has_photo without a separate GET.
        return _to_out(o)

    _delete_photo_file(o)
    before = {"photo_path": o.photo_path}
    o.photo_path = ""

    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="official.photo.delete",
        entity_type="org_kb_official",
        entity_id=o.id,
        before=before,
        request=request,
    )
    return _to_out(o)
