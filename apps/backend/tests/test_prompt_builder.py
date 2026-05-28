"""Smoke test for prompt formatting — no DB needed.

Officials were removed for the Council, so the old `_format_officials` block is
gone. These cover the surviving runtime blocks: the today/date header and the
КЕҢЕС contact block (which must NOT leak the old hokimiyat branding).
"""
from __future__ import annotations

from src.ai.prompt_builder import _format_org_contact_block, _format_today_block
from src.domain.organization import Organization


def test_today_block_has_header_and_karakalpak_weekday() -> None:
    out = _format_today_block()
    assert "ҲӘЗИРГИ ЎАҚЫТ" in out
    days = ["дүйшемби", "сейшемби", "сәршемби", "пийшемби", "жума", "шемби", "жексенби"]
    assert any(d in out for d in days)


def _org(**kw: object) -> Organization:
    o = Organization()
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def test_contact_block_council_header_and_fields() -> None:
    org = _org(
        helpline_phone="+998 61 222-00-00",
        email="info@kenes.uz",
        address_translations={"kk": "Нөкис қ."},
        work_hours_translations={"kk": "Дү–Жу 09:00–18:00"},
    )
    out = _format_org_contact_block(org)
    assert "КЕҢЕС БАЙЛАНЫС" in out
    assert "+998 61 222-00-00" in out
    assert "info@kenes.uz" in out
    # The old executive branding must not leak into the Council contact block.
    assert "ҲӘКИМИЯТ" not in out


def test_contact_block_empty_fields_render_dash() -> None:
    org = _org(
        helpline_phone=None,
        email="",
        address_translations={},
        work_hours_translations={},
    )
    out = _format_org_contact_block(org)
    assert "КЕҢЕС БАЙЛАНЫС" in out
    assert "—" in out
