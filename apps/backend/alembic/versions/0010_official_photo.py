"""official photo_path column

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-13

Adds OrgKbOfficial.photo_path — the on-disk filename (just the basename,
no directory) of an uploaded photo. Empty string means no photo. The
actual files live under settings.photos_dir (default
/var/lib/kiosk/photos in prod, mounted as a docker volume).

Rationale: deputies on the kiosk Qabul page need faces, not just names.
Stored on disk instead of as a BLOB because (a) the DB stays small, (b)
serving binary by file is cheaper than going through the ORM, and (c)
backups can dedupe / rsync the photos directory independently.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "org_kb_officials",
        sa.Column(
            "photo_path",
            sa.String(255),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("org_kb_officials", "photo_path")
