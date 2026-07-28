"""library catalogue, owned by the institute

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-28

The AI Kutubxona menu shipped with no data source: `irbis.kkmi.uz` does not
resolve outside the institute network and no catalogue export was supplied, so
the tile showed a "coming soon" screen and the menu declared no tools.

This gives the catalogue a home of our own. Unlike `hemis_*`, which is a
disposable mirror, `library_books` is a source of truth — librarians enter
books through the gov panel and the kiosk reads them back. An IRBIS export, if
one ever arrives, imports INTO this table without changing anything downstream.

No loans, borrowers or due dates: the kiosk identifies nobody, so it cannot
check a book out. The catalogue answers "do you have it, what is it, which
shelf" and stops.

Seeding is done by `core.seed.ensure_library_seed` at startup rather than here,
so the book list stays next to the rest of the seed data instead of being
frozen in a migration.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "library_books",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("authors", sa.String(400), nullable=False, server_default=""),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("publisher", sa.String(200), nullable=False, server_default=""),
        # Not unique: two accessions of the same edition on different shelves
        # are two rows with one ISBN.
        sa.Column("isbn", sa.String(32), nullable=False, server_default=""),
        sa.Column("language", sa.String(8), nullable=False, server_default="uz"),
        sa.Column("section", sa.String(32), nullable=False, server_default="other"),
        sa.Column("copies", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("shelf", sa.String(64), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "available", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_library_books_org_id", "library_books", ["org_id"])
    op.create_index(
        "ix_library_books_org_section", "library_books", ["org_id", "section"]
    )
    op.create_index(
        "ix_library_books_org_title", "library_books", ["org_id", "title"]
    )


def downgrade() -> None:
    op.drop_index("ix_library_books_org_title", table_name="library_books")
    op.drop_index("ix_library_books_org_section", table_name="library_books")
    op.drop_index("ix_library_books_org_id", table_name="library_books")
    op.drop_table("library_books")
