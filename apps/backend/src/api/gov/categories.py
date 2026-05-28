"""Gov admin: read-only category list.

The gov-panel needs the categories list to populate dropdowns on murajat
detail pages. Categories themselves are managed by super admin (see
api/super/categories.py).
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from ...core.deps import DbSession, OrgMember
from ...domain.category import (
    ApplicationCategory,
    category_translations_for_response,
)

router = APIRouter(
    prefix="/api/gov/application-categories",
    tags=["gov:application-categories"],
)


class CategoryOut(BaseModel):
    id: str
    slug: str
    name_translations: dict[str, str]
    order: int


class CategoryListOut(BaseModel):
    items: list[CategoryOut]


@router.get("", response_model=CategoryListOut)
async def list_categories(
    session: DbSession, _: OrgMember
) -> CategoryListOut:
    rows = (
        await session.execute(
            select(ApplicationCategory)
            .where(ApplicationCategory.deleted_at.is_(None))
            .order_by(ApplicationCategory.order, ApplicationCategory.slug)
        )
    ).scalars().all()
    return CategoryListOut(
        items=[
            CategoryOut(
                id=str(c.id),
                slug=c.slug,
                name_translations=category_translations_for_response(c),
                order=c.order,
            )
            for c in rows
        ]
    )
