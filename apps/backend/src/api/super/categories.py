"""Super admin: application_categories CRUD.

Categories are global (no org_id) — every org sees the same list and the AI
agent's prompt references them by slug. Only super admin can manage them
because changes ripple through all kiosks at once.

Soft delete: `deleted_at` set on DELETE so historical Application.category_id
rows pointing at the slug still resolve. New submissions don't see deleted
categories in the list endpoint.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ...core import audit
from ...core.deps import DbSession, SuperAdmin
from ...core.errors import ConflictError, NotFoundError, ValidationError
from ...domain.category import (
    SUPPORTED_LOCALES,
    ApplicationCategory,
    category_translations_for_response,
)

router = APIRouter(
    prefix="/api/super/application-categories",
    tags=["super:application-categories"],
)

_SLUG_RE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")


def _validate_translations(v: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for loc in SUPPORTED_LOCALES:
        raw = v.get(loc, "")
        s = (raw or "").strip()
        if not s:
            raise ValueError(f"name_translations.{loc} is required")
        if len(s) > 64:
            raise ValueError(f"name_translations.{loc} exceeds 64 chars")
        cleaned[loc] = s
    return cleaned


class CategoryCreateIn(BaseModel):
    slug: str = Field(min_length=1, max_length=32)
    name_translations: dict[str, str]
    order: int = Field(default=0, ge=0, le=9999)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                "slug must be lowercase alphanumeric with underscores"
            )
        return v

    @field_validator("name_translations")
    @classmethod
    def validate_translations(cls, v: dict[str, str]) -> dict[str, str]:
        return _validate_translations(v)


class CategoryUpdateIn(BaseModel):
    name_translations: dict[str, str] | None = None
    order: int | None = Field(default=None, ge=0, le=9999)

    @field_validator("name_translations")
    @classmethod
    def validate_translations(
        cls, v: dict[str, str] | None
    ) -> dict[str, str] | None:
        if v is None:
            return None
        return _validate_translations(v)


class CategoryOut(BaseModel):
    id: str
    slug: str
    name_translations: dict[str, str]
    order: int
    deleted_at: str | None
    created_at: str
    updated_at: str


class CategoryListOut(BaseModel):
    items: list[CategoryOut]


def _to_out(cat: ApplicationCategory) -> CategoryOut:
    return CategoryOut(
        id=str(cat.id),
        slug=cat.slug,
        name_translations=category_translations_for_response(cat),
        order=cat.order,
        deleted_at=cat.deleted_at.isoformat() if cat.deleted_at else None,
        created_at=cat.created_at.isoformat(),
        updated_at=cat.updated_at.isoformat(),
    )


@router.get("", response_model=CategoryListOut)
async def list_categories(
    session: DbSession, _: SuperAdmin, include_deleted: bool = False
) -> CategoryListOut:
    stmt = select(ApplicationCategory)
    if not include_deleted:
        stmt = stmt.where(ApplicationCategory.deleted_at.is_(None))
    stmt = stmt.order_by(ApplicationCategory.order, ApplicationCategory.slug)
    rows = (await session.execute(stmt)).scalars().all()
    return CategoryListOut(items=[_to_out(c) for c in rows])


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreateIn,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> CategoryOut:
    existing = (
        await session.execute(
            select(ApplicationCategory).where(
                ApplicationCategory.slug == payload.slug
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("slug_taken")
    cat = ApplicationCategory(
        slug=payload.slug,
        name_translations=payload.name_translations,
        order=payload.order,
    )
    session.add(cat)
    await session.flush()
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="application_category.create",
        entity_type="application_category",
        entity_id=cat.id,
        after={"slug": cat.slug, "order": cat.order},
        request=request,
    )
    return _to_out(cat)


@router.patch("/{cat_id}", response_model=CategoryOut)
async def update_category(
    cat_id: uuid.UUID,
    payload: CategoryUpdateIn,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> CategoryOut:
    cat = (
        await session.execute(
            select(ApplicationCategory).where(ApplicationCategory.id == cat_id)
        )
    ).scalar_one_or_none()
    if cat is None:
        raise NotFoundError("category_not_found")
    if cat.deleted_at is not None:
        raise ValidationError("category_deleted")
    before = {
        "name_translations": dict(cat.name_translations or {}),
        "order": cat.order,
    }
    if payload.name_translations is not None:
        cat.name_translations = payload.name_translations
    if payload.order is not None:
        cat.order = payload.order
    after = {
        "name_translations": dict(cat.name_translations or {}),
        "order": cat.order,
    }
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="application_category.update",
        entity_type="application_category",
        entity_id=cat.id,
        before=before,
        after=after,
        request=request,
    )
    return _to_out(cat)


@router.delete("/{cat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    cat_id: uuid.UUID,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> None:
    cat = (
        await session.execute(
            select(ApplicationCategory).where(ApplicationCategory.id == cat_id)
        )
    ).scalar_one_or_none()
    if cat is None:
        raise NotFoundError("category_not_found")
    if cat.deleted_at is not None:
        return  # Idempotent: already deleted.
    cat.deleted_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="application_category.delete",
        entity_type="application_category",
        entity_id=cat.id,
        before={"slug": cat.slug},
        request=request,
    )
