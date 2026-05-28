"""nukus helpline phone — real number

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-13

Migration 0009 seeded the Nukus tenant's helpline_phone with the
placeholder "+998 (61) 222-12-34". The real Murojat bo'limi number is
"+998 (61) 222-89-77" per the operator. Update the row in place.

Conditional on the value still being the placeholder so a manual edit
through the gov-panel (if any) isn't clobbered.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE organizations
        SET helpline_phone = '+998 (61) 222-89-77'
        WHERE helpline_phone = '+998 (61) 222-12-34'
          AND (slug = 'nokis' OR slug = 'nukus'
               OR name ILIKE '%nukus%' OR name ILIKE '%nókis%' OR name ILIKE '%нөкис%')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE organizations
        SET helpline_phone = '+998 (61) 222-12-34'
        WHERE helpline_phone = '+998 (61) 222-89-77'
          AND (slug = 'nokis' OR slug = 'nukus'
               OR name ILIKE '%nukus%' OR name ILIKE '%nókis%' OR name ILIKE '%нөкис%')
        """
    )
