"""scanned book PDFs

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-04

The institute supplied its professors' own textbooks as scans, and asked that
a visitor be able to read them at the kiosk rather than only find them on a
shelf.

The scan itself stays on the server. The kiosk asks for one rendered page at a
time and draws it as a JPEG, because the lobby machines are 2011 Intel boxes
running a Native AOT binary — a PDF engine on them is the same class of thing
that already cost us a week of freezes. Rendering server-side also means the
whole book never travels over the institute's connection just to show page one.

`page_count` is the flag as well as the number: zero means there is nothing to
read, and the kiosk decides whether to offer the reader on that alone. It is
written in the same transaction as `pdf_path` so the two cannot disagree.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "library_books",
        sa.Column(
            "pdf_path", sa.String(length=255), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "library_books",
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("library_books", "page_count")
    op.drop_column("library_books", "pdf_path")
