"""org name_translations JSONB column

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-14

Adds `organizations.name_translations` so each tenant can carry its display
name in {uz, kk, ru} simultaneously. The legacy `name` column stays — it's
the canonical/fallback string referenced from audit logs and any code path
that doesn't yet know about locales. Backfill copies `name` into all three
keys so existing kiosks/receipts continue to render *something* in every
language until the super admin edits the translations.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add the column with a sane default first, then backfill from `name`.
    # Doing the backfill in one UPDATE keeps existing orgs visually
    # unchanged in every language until the operator localizes them.
    op.add_column(
        "organizations",
        sa.Column(
            "name_translations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE organizations "
        "SET name_translations = jsonb_build_object('uz', name, 'kk', name, 'ru', name) "
        "WHERE (name_translations::text = '{}' OR name_translations IS NULL)"
    )


def downgrade() -> None:
    op.drop_column("organizations", "name_translations")
