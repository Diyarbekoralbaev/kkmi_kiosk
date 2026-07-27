"""Prompt assembly — the runtime blocks and the menu→tools scoping.

No DB needed: these cover the pure functions. DB-backed `load_agent_config` is
exercised by the WS smoke run in DEPLOY.md.

The menu-scoping tests are the load-bearing ones. Declaring every tool at once
made the model blend flows — offering to file an appeal when asked for a
timetable — so "this menu sees only these tools" is a behavioural contract, not
an implementation detail.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.ai.prompt_builder import (
    _format_org_contact_block,
    _format_today_block,
    normalize_menu,
)
from src.ai.tools import MENU_TOOLS, TOOL_DECLS, declarations_for, tools_for_menu
from src.domain.ai_config import BASE_SECTION_KEYS, SECTION_KEYS, focus_key
from src.domain.organization import Organization

TASHKENT = ZoneInfo("Asia/Tashkent")


# ── Runtime blocks ────────────────────────────────────────────────────────────


def test_today_block_states_date_and_weekday() -> None:
    out = _format_today_block(datetime(2026, 9, 7, 9, 30, tzinfo=TASHKENT))
    assert "2026-09-07" in out
    assert "Monday" in out
    assert "09:30" in out


def test_today_block_uses_local_not_utc_date() -> None:
    """At 02:00 in Nukus the UTC date is still the previous day; resolving
    "today" in UTC would show the wrong day's classes."""
    local = datetime(2026, 9, 8, 2, 0, tzinfo=TASHKENT)
    assert local.astimezone(ZoneInfo("UTC")).date().isoformat() == "2026-09-07"
    assert "2026-09-08" in _format_today_block(local)


def _org(**kw: object) -> Organization:
    o = Organization()
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def test_contact_block_carries_the_real_details() -> None:
    out = _format_org_contact_block(
        _org(
            helpline_phone="+998 61 222-84-32",
            email="kkmeduniver@gmail.com",
            address_translations={"uz": "Nukus, A. Dosnazarov 106"},
            work_hours_translations={"uz": "Du–Ju 09:00–18:00"},
        )
    )
    assert "+998 61 222-84-32" in out
    assert "kkmeduniver@gmail.com" in out
    assert "Nukus, A. Dosnazarov 106" in out


def test_contact_block_renders_dash_for_missing_fields() -> None:
    """A half-empty section invites the model to fill the gap itself, so a
    missing value must be explicitly marked absent."""
    out = _format_org_contact_block(
        _org(
            helpline_phone=None,
            email="",
            address_translations={},
            work_hours_translations={},
        )
    )
    assert "—" in out


# ── Menu scoping ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("menu", list(MENU_TOOLS))
def test_every_menu_has_a_focus_section_key(menu: str) -> None:
    assert focus_key(menu) in SECTION_KEYS


@pytest.mark.parametrize("menu", list(MENU_TOOLS))
def test_every_declared_tool_exists(menu: str) -> None:
    for name in tools_for_menu(menu):
        assert name in TOOL_DECLS, f"{menu} declares unknown tool {name}"


def test_declarations_are_built_for_the_menu_only() -> None:
    names = {d["name"] for d in declarations_for(tools_for_menu("jadval"))}
    assert names == {"navigate_to_screen", "find_group", "show_schedule"}


def test_appeal_tools_are_not_reachable_from_the_timetable_menu() -> None:
    """The specific cross-flow leak this design exists to prevent."""
    assert "submit_murojat" not in tools_for_menu("jadval")
    assert "show_schedule" not in tools_for_menu("murojat")


def test_library_menu_declares_no_tools() -> None:
    """The catalogue is not connected yet. With no tools the agent can only say
    so, rather than answering about books from memory."""
    assert tools_for_menu("library") == []


@pytest.mark.parametrize("raw", ["jadval", "JADVAL", " jadval ", "murojat", "qabul"])
def test_normalize_menu_accepts_known_menus(raw: str) -> None:
    assert normalize_menu(raw) == raw.strip().lower()


@pytest.mark.parametrize("raw", [None, "", "nonsense", "../../etc/passwd"])
def test_normalize_menu_falls_back_for_anything_else(raw: str | None) -> None:
    """The menu arrives on a URL the kiosk builds, so it is untrusted input."""
    assert normalize_menu(raw) == "maslahatchi"


def test_base_sections_are_disjoint_from_focus_sections() -> None:
    assert set(BASE_SECTION_KEYS).isdisjoint({focus_key(m) for m in MENU_TOOLS})
