"""appointments table

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "official_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org_kb_officials.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("voice_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("visitor_phone", sa.String(32), nullable=False),
        sa.Column("topic_summary", sa.Text, nullable=False),
        sa.Column("scheduled_date", sa.Date, nullable=False),
        sa.Column("queue_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(16), nullable=False, server_default="kiosk"),
        sa.Column("verification_token", sa.String(64), nullable=False),
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
    op.create_index("ix_appointments_org_id", "appointments", ["org_id"])
    op.create_index("ix_appointments_official_id", "appointments", ["official_id"])
    op.create_index(
        "ix_appointments_verification_token", "appointments", ["verification_token"]
    )
    op.create_index(
        "ix_appointments_org_date", "appointments", ["org_id", "scheduled_date"]
    )
    op.create_index(
        "ix_appointments_org_status_created",
        "appointments",
        ["org_id", "status", "created_at"],
    )
    op.create_unique_constraint(
        "uq_appointments_official_date_queue",
        "appointments",
        ["official_id", "scheduled_date", "queue_number"],
    )
    op.create_unique_constraint(
        "uq_appointments_verification_token",
        "appointments",
        ["verification_token"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_appointments_verification_token", "appointments", type_="unique"
    )
    op.drop_constraint(
        "uq_appointments_official_date_queue", "appointments", type_="unique"
    )
    op.drop_index("ix_appointments_org_status_created", "appointments")
    op.drop_index("ix_appointments_org_date", "appointments")
    op.drop_index("ix_appointments_verification_token", "appointments")
    op.drop_index("ix_appointments_official_id", "appointments")
    op.drop_index("ix_appointments_org_id", "appointments")
    op.drop_table("appointments")
