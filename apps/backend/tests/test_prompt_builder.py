"""Smoke test for prompt formatting — no DB needed."""
from __future__ import annotations

from src.ai.prompt_builder import _format_officials
from src.domain.ai_config import OrgKbOfficial


def _o(**kw: object) -> OrgKbOfficial:
    o = OrgKbOfficial()
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def test_format_officials_empty_returns_empty_string() -> None:
    assert _format_officials([]) == ""


def test_format_officials_renders_full_block() -> None:
    officials = [
        _o(
            order=1,
            position="HÁKIM",
            name="Daniyarov A. S.",
            responsibilities="",
            reception_day="fri",
            reception_time="10:00-12:00",
        ),
        _o(
            order=2,
            position="Birinshi orinbasar",
            name="Kannazarov M. A.",
            responsibilities="Finans, ekonomika",
            reception_day="wed",
            reception_time="10:00-12:00",
        ),
    ]
    out = _format_officials(officials)
    assert "HOKIM HÁM ORINBASARLAR" in out
    assert "Daniyarov A. S." in out
    assert "Kannazarov M. A." in out
    assert "juma 10:00-12:00" in out  # Karakalpak day translation
    assert "sárshembi 10:00-12:00" in out
