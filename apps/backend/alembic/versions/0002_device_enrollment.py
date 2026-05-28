"""device enrollment codes + device keys

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_enrollment_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_unique_constraint(
        "uq_device_enrollment_codes_code_hash",
        "device_enrollment_codes",
        ["code_hash"],
    )
    op.create_index(
        "ix_device_enrollment_codes_device_id",
        "device_enrollment_codes",
        ["device_id"],
    )

    op.create_table(
        "device_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_unique_constraint("uq_device_keys_key_hash", "device_keys", ["key_hash"])
    op.create_index("ix_device_keys_device_id", "device_keys", ["device_id"])


def downgrade() -> None:
    op.drop_index("ix_device_keys_device_id", "device_keys")
    op.drop_constraint("uq_device_keys_key_hash", "device_keys", type_="unique")
    op.drop_table("device_keys")
    op.drop_index("ix_device_enrollment_codes_device_id", "device_enrollment_codes")
    op.drop_constraint(
        "uq_device_enrollment_codes_code_hash",
        "device_enrollment_codes",
        type_="unique",
    )
    op.drop_table("device_enrollment_codes")
