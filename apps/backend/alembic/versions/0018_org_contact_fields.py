"""organization: address + email + work_hours translation fields

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-15

The kiosk Contacts page was rendering hard-coded "Nukus sh., Berdaq ko'chasi 1"
and "info@nukushokimiyat.uz" out of the localization XAML — wrong placeholder
data baked at compile time. Per the multi-org requirement (other district
hokimliklar will plug in their own kiosk), contact info must live with the
Organization row so each tenant has its own address/email/hours.

Adds three new columns:
- `address_translations`  JSONB — {uz, kk, ru} per-locale street address
- `email`                 VARCHAR(255) — single org email
- `work_hours_translations` JSONB — {uz, kk, ru} per-locale "Mon-Fri 09:00-18:00"

`helpline_phone` was already added in migration 0011 (Nukus helpline) and is
reused as the kiosk contact phone — no schema change needed there.

Backfill: existing rows get the Nukus defaults so the kiosk doesn't go blank
the second this migration applies. Super-admin can then edit per-org via the
panel.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Provisional Nukus defaults — same strings the legacy localization carried
# so existing kiosks see *something* the instant migration applies. Super
# admin overwrites in the panel once the real address/email is supplied.
DEFAULT_ADDRESS = {
    "uz": "Nukus sh., Berdaq ko'chasi 1",
    "kk": "Нөкис қ., Бердақ гүзәри, 1-үй",
    "ru": "г. Нукус, ул. Бердака 1",
}
DEFAULT_HOURS = {
    "uz": "Du–Ju  09:00 – 18:00",
    "kk": "Дү–Жу 09:00 – 18:00",
    "ru": "Пн–Пт  09:00 – 18:00",
}
DEFAULT_EMAIL = "info@nukushokimiyat.uz"


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "address_translations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "email",
            sa.String(length=255),
            server_default="",
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "work_hours_translations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    # Backfill existing orgs with the legacy Nukus placeholders so kiosks
    # don't render blank cells between migration and super-admin edit.
    op.execute(
        sa.text(
            "UPDATE organizations SET "
            "address_translations = CAST(:addr AS jsonb), "
            "email = :email, "
            "work_hours_translations = CAST(:hours AS jsonb) "
            "WHERE address_translations::text = '{}' OR address_translations IS NULL"
        ).bindparams(
            sa.bindparam("addr", json.dumps(DEFAULT_ADDRESS), type_=sa.String),
            sa.bindparam("email", DEFAULT_EMAIL, type_=sa.String),
            sa.bindparam("hours", json.dumps(DEFAULT_HOURS), type_=sa.String),
        )
    )


def downgrade() -> None:
    op.drop_column("organizations", "work_hours_translations")
    op.drop_column("organizations", "email")
    op.drop_column("organizations", "address_translations")
