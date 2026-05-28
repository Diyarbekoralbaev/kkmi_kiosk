"""official role + organization weather/helpline

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-12

Two unrelated columns ride in the same migration because both unblock the
kiosk redesign and neither is large enough to warrant its own file:

  - org_kb_officials.role : 'chief' | 'deputy' — drives the new Home-screen
    split where "Hokim jeke" and "Hokim orinbasari" tiles each show only
    their subset of officials.
  - organizations.latitude / .longitude / .city_name : per-org geo for the
    kiosk header's weather widget (fetched from Open-Meteo by the backend
    and bundled into the heartbeat response).
  - organizations.helpline_phone : per-org footer phone shown in the
    kiosk's deep-blue footer band.

Backfill rule for `role`: every org's first-by-`order` official is marked
'chief'; the rest are 'deputy'. Matches the seed convention where the
HÁKIM is the first row in the KB. Operators can flip this in gov-panel.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # OrgKbOfficial.role
    op.add_column(
        "org_kb_officials",
        sa.Column(
            "role",
            sa.String(16),
            nullable=False,
            server_default="deputy",
        ),
    )
    # Backfill: the first official per org (lowest `order`) is the chief.
    op.execute(
        """
        UPDATE org_kb_officials AS o
        SET role = 'chief'
        WHERE o.id = (
            SELECT inner_o.id
            FROM org_kb_officials AS inner_o
            WHERE inner_o.org_id = o.org_id
            ORDER BY inner_o."order" ASC, inner_o.created_at ASC
            LIMIT 1
        )
        """
    )

    # Organization geo + helpline
    op.add_column("organizations", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("organizations", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("organizations", sa.Column("city_name", sa.String(64), nullable=True))
    op.add_column("organizations", sa.Column("helpline_phone", sa.String(32), nullable=True))

    # Seed Nukus tenant's geo (best-effort — only updates if the slug exists).
    # Kk-Cyrl city name so the kiosk renders it verbatim in the weather row.
    op.execute(
        """
        UPDATE organizations
        SET latitude = 42.4534,
            longitude = 59.6103,
            city_name = 'Нөкис',
            helpline_phone = COALESCE(helpline_phone, '+998 (61) 222-12-34')
        WHERE slug = 'nokis' OR slug = 'nukus' OR name ILIKE '%nukus%' OR name ILIKE '%nókis%' OR name ILIKE '%нөкис%'
        """
    )


def downgrade() -> None:
    op.drop_column("organizations", "helpline_phone")
    op.drop_column("organizations", "city_name")
    op.drop_column("organizations", "longitude")
    op.drop_column("organizations", "latitude")
    op.drop_column("org_kb_officials", "role")
