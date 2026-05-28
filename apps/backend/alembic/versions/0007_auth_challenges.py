"""auth_challenges table — single-use ECDSA nonces

Each authenticated kiosk request follows a challenge-response: the kiosk hits
GET /api/kiosk/auth/challenge?device_id=... → server returns a random 32-byte
nonce that expires in ~10s. The kiosk signs the nonce with its TPM-bound
private key, then sends the signature on the actual request. Server verifies,
marks the nonce used. Replays fail (nonce already marked used).

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nonce_b64", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_auth_challenges_nonce_b64", "auth_challenges", ["nonce_b64"]
    )
    op.create_index(
        "ix_auth_challenges_device_id", "auth_challenges", ["device_id"]
    )
    op.create_index(
        "ix_auth_challenges_expires_at", "auth_challenges", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_auth_challenges_expires_at", "auth_challenges")
    op.drop_index("ix_auth_challenges_device_id", "auth_challenges")
    op.drop_constraint(
        "uq_auth_challenges_nonce_b64", "auth_challenges", type_="unique"
    )
    op.drop_table("auth_challenges")
