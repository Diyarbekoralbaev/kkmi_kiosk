"""Gov: monthly dashboard — KPI totals, daily time-series, category mix.

Feeds the redesigned gov-panel dashboard. The old /api/gov/dashboard
endpoint is kept for back-compat and serves the legacy 4-card view, but
nothing in the new UI hits it.

Query: `?year=2026&month=5`. Defaults to the server's current UTC month.
"""
from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select

from ...core.deps import CurrentOrg, DbSession, OrgAdmin
from ...domain.application import (
    STATUS_IN_PROGRESS,
    STATUS_RESOLVED,
    STATUS_RETURNED,
    Application,
)
from ...domain.appointment import Appointment
from ...domain.category import (
    ApplicationCategory,
    category_translations_for_response,
)

router = APIRouter(prefix="/api/gov/dashboard", tags=["gov:dashboard"])


class MonthlyTotals(BaseModel):
    received: int
    in_progress: int
    resolved: int
    returned: int


class DailyPoint(BaseModel):
    date: str
    applications: int
    appointments: int


class CategoryPoint(BaseModel):
    id: str
    slug: str
    name_translations: dict[str, str]
    count: int


class MonthlyDashboardOut(BaseModel):
    year: int
    month: int
    totals: MonthlyTotals
    daily: list[DailyPoint]
    categories: list[CategoryPoint]


def _month_range(year: int, month: int) -> tuple[datetime, datetime]:
    """Inclusive start, exclusive end — half-open interval so daily count
    `WHERE created_at >= start AND created_at < end` matches the calendar
    month exactly without DST/timezone weirdness (we store in UTC)."""
    start = datetime(year, month, 1, tzinfo=UTC)
    last_day = calendar.monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59, 999999, tzinfo=UTC) + timedelta(
        microseconds=1
    )
    return start, end


@router.get("/monthly", response_model=MonthlyDashboardOut)
async def dashboard_monthly(
    session: DbSession,
    _: OrgAdmin,
    org: CurrentOrg,
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
) -> MonthlyDashboardOut:
    now = datetime.now(UTC)
    y = year or now.year
    m = month or now.month
    start, end = _month_range(y, m)

    # ── 4 KPI totals over the month ──────────────────────────────────
    # Single roll-up query — five COUNT(*) FILTERs.
    totals_row = (
        await session.execute(
            select(
                func.count().label("received"),
                func.sum(
                    case((Application.status == STATUS_IN_PROGRESS, 1), else_=0)
                ).label("in_progress"),
                func.sum(
                    case((Application.status == STATUS_RESOLVED, 1), else_=0)
                ).label("resolved"),
                func.sum(
                    case((Application.status == STATUS_RETURNED, 1), else_=0)
                ).label("returned"),
            ).where(
                Application.org_id == org.id,
                Application.created_at >= start,
                Application.created_at < end,
            )
        )
    ).one()

    totals = MonthlyTotals(
        received=int(totals_row.received or 0),
        in_progress=int(totals_row.in_progress or 0),
        resolved=int(totals_row.resolved or 0),
        returned=int(totals_row.returned or 0),
    )

    # ── Daily counts ─────────────────────────────────────────────────
    # Group by DATE(created_at) — Postgres native, no python-side bucketing.
    app_daily_rows = (
        await session.execute(
            select(
                func.date(Application.created_at).label("d"),
                func.count().label("c"),
            )
            .where(
                Application.org_id == org.id,
                Application.created_at >= start,
                Application.created_at < end,
            )
            .group_by(func.date(Application.created_at))
        )
    ).all()
    app_daily = {row[0]: int(row[1]) for row in app_daily_rows}

    appt_daily_rows = (
        await session.execute(
            select(
                func.date(Appointment.created_at).label("d"),
                func.count().label("c"),
            )
            .where(
                Appointment.org_id == org.id,
                Appointment.created_at >= start,
                Appointment.created_at < end,
            )
            .group_by(func.date(Appointment.created_at))
        )
    ).all()
    appt_daily = {row[0]: int(row[1]) for row in appt_daily_rows}

    # Fill in every day of the month so the chart line draws a continuous
    # x-axis even on quiet days (frontend doesn't have to pad on its own).
    daily: list[DailyPoint] = []
    last_day = calendar.monthrange(y, m)[1]
    for d in range(1, last_day + 1):
        cur = date(y, m, d)
        daily.append(
            DailyPoint(
                date=cur.isoformat(),
                applications=app_daily.get(cur, 0),
                appointments=appt_daily.get(cur, 0),
            )
        )

    # ── Category mix ─────────────────────────────────────────────────
    # LEFT JOIN so categories with zero hits still appear (with count=0)
    # but only for categories actually used this month — uncategorized
    # applications fall under a synthetic "Uncategorized" bucket below.
    cat_rows = (
        await session.execute(
            select(
                ApplicationCategory.id,
                ApplicationCategory.slug,
                ApplicationCategory.name_translations,
                ApplicationCategory.order,
                func.count(Application.id).label("c"),
            )
            .select_from(ApplicationCategory)
            .join(
                Application,
                (Application.category_id == ApplicationCategory.id)
                & (Application.org_id == org.id)
                & (Application.created_at >= start)
                & (Application.created_at < end),
                isouter=True,
            )
            .where(ApplicationCategory.deleted_at.is_(None))
            .group_by(
                ApplicationCategory.id,
                ApplicationCategory.slug,
                ApplicationCategory.name_translations,
                ApplicationCategory.order,
            )
            .order_by(func.count(Application.id).desc(), ApplicationCategory.order)
        )
    ).all()

    categories = [
        CategoryPoint(
            id=str(row[0]),
            slug=row[1],
            name_translations=category_translations_for_response(
                # Build a tiny stand-in so the helper can resolve fallbacks.
                # Cheap because all the fields it touches are already loaded.
                type(
                    "_CatRef",
                    (),
                    {
                        "name_translations": row[2],
                        "slug": row[1],
                    },
                )()
            ),
            count=int(row[4] or 0),
        )
        for row in cat_rows
    ]

    # Count applications submitted this month with no category — surface
    # them so admins notice the gap and can categorize via the detail page.
    uncat = (
        await session.execute(
            select(func.count())
            .select_from(Application)
            .where(
                Application.org_id == org.id,
                Application.category_id.is_(None),
                Application.created_at >= start,
                Application.created_at < end,
            )
        )
    ).scalar_one()
    if int(uncat) > 0:
        categories.append(
            CategoryPoint(
                id="",
                slug="_uncategorized",
                name_translations={
                    "uz": "Toifalanmagan",
                    "kk": "Категориясыз",
                    "ru": "Без категории",
                },
                count=int(uncat),
            )
        )

    return MonthlyDashboardOut(
        year=y,
        month=m,
        totals=totals,
        daily=daily,
        categories=categories,
    )
