"""Application status machine — pure logic, no DB."""
from __future__ import annotations

from src.domain.application import (
    ALLOWED_TRANSITIONS,
    STATUS_ARCHIVED,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    STATUS_RESOLVED,
)


def test_new_can_progress_or_archive() -> None:
    allowed = ALLOWED_TRANSITIONS[STATUS_NEW]
    assert STATUS_IN_PROGRESS in allowed
    assert STATUS_ARCHIVED in allowed
    assert STATUS_RESOLVED not in allowed  # must go through in_progress


def test_in_progress_can_resolve_archive_or_revert() -> None:
    allowed = ALLOWED_TRANSITIONS[STATUS_IN_PROGRESS]
    assert STATUS_RESOLVED in allowed
    assert STATUS_ARCHIVED in allowed
    assert STATUS_NEW in allowed


def test_resolved_can_re_open_or_archive() -> None:
    allowed = ALLOWED_TRANSITIONS[STATUS_RESOLVED]
    assert STATUS_ARCHIVED in allowed
    assert STATUS_IN_PROGRESS in allowed
    assert STATUS_NEW not in allowed


def test_archived_is_terminal() -> None:
    assert ALLOWED_TRANSITIONS[STATUS_ARCHIVED] == set()
