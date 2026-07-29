"""book jacket images

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-29

A catalogue of titles and authors reads as a spreadsheet. A shelf reads as a
shelf because you see the books, so the kiosk stores each jacket alongside the
card.

Bytes, not a URL: the kiosk sits on the institute's connection in Nókis, and a
URL would make every tap depend on openlibrary.org answering right then.
Covers are 20-60 KB, a catalogue is hundreds of books, so the whole set is a
few megabytes — cheaper to hold than to re-fetch, and it still works when the
upstream does not.

`cover_fetched_at` is stamped on misses too. Most ISBNs have no cover upstream,
and without remembering that, the fetcher would retry the same hopeless lookups
on every run.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "library_books", sa.Column("cover", sa.LargeBinary(), nullable=True)
    )
    op.add_column(
        "library_books",
        sa.Column("cover_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("library_books", "cover_fetched_at")
    op.drop_column("library_books", "cover")
