"""device_keys: drop key_hash → public_key_pem (ECDSA P-256)

Old auth: server stored SHA-256 of a shared secret bearer token. Stolen secret =
total compromise; server DB leak = also bad.

New auth: kiosk generates ECDSA P-256 keypair INSIDE TPM; server only stores
the PUBLIC key. Server compromise leaks no creds; admin-level extraction on
the kiosk is blocked by TPM (private key never leaves the chip).

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All existing key_hash rows become unusable after the kiosk re-enrolls
    # (they need to upload a fresh public_key_pem), so we drop them and the
    # column wholesale rather than trying to migrate values.
    op.execute("DELETE FROM device_keys")
    op.drop_constraint("uq_device_keys_key_hash", "device_keys", type_="unique")
    op.drop_column("device_keys", "key_hash")
    op.add_column(
        "device_keys",
        sa.Column("public_key_pem", sa.Text(), nullable=False, server_default=""),
    )
    # Server default was only needed to satisfy NOT NULL on the (empty) table;
    # drop it so future inserts must provide a real PEM.
    op.alter_column("device_keys", "public_key_pem", server_default=None)
    op.create_index(
        "ix_device_keys_device_revoked",
        "device_keys",
        ["device_id", "revoked_at"],
    )


def downgrade() -> None:
    op.execute("DELETE FROM device_keys")
    op.drop_index("ix_device_keys_device_revoked", "device_keys")
    op.drop_column("device_keys", "public_key_pem")
    op.add_column(
        "device_keys",
        sa.Column("key_hash", sa.String(64), nullable=False, server_default=""),
    )
    op.alter_column("device_keys", "key_hash", server_default=None)
    op.create_unique_constraint(
        "uq_device_keys_key_hash", "device_keys", ["key_hash"]
    )
