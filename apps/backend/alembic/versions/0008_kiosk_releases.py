"""kiosk_releases — uploaded binary update bundles

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kiosk_releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False, server_default="stable"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("file_size", sa.BigInteger, nullable=False),
        sa.Column("release_notes", sa.Text, nullable=False, server_default=""),
        sa.Column("mandatory", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("github_release_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_kiosk_releases_channel_status",
        "kiosk_releases",
        ["channel", "status"],
    )
    op.create_index(
        "ix_kiosk_releases_published_at", "kiosk_releases", ["published_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_kiosk_releases_published_at", "kiosk_releases")
    op.drop_index("ix_kiosk_releases_channel_status", "kiosk_releases")
    op.drop_table("kiosk_releases")
