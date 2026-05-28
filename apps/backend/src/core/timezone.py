"""Single source of truth for the app's display/business timezone.

Storage and all internal logic stay UTC (the DB is timestamptz, datetimes are
UTC-aware). This module is the ONE place that knows the local timezone, used
only at the edges: user-facing timestamps (Telegram posts) and business-day
boundaries (reception-day rollover). Keeping it isolated keeps the
"UTC inside, local at the edge" rule in a single, obvious home.

Asia/Tashkent — UTC+5, no DST. The kiosks and the hokimiyat are all here.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Tashkent")


def now_local() -> datetime:
    """Current time as a timezone-aware datetime in Asia/Tashkent."""
    return datetime.now(LOCAL_TZ)


def today_local() -> date:
    """Today's calendar date in Asia/Tashkent (the business day, not UTC)."""
    return now_local().date()
