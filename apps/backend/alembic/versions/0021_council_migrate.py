"""council migrate: appeals without categories, qabul without official/date, feedback

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-28

Turns the cloned Hokimiyat schema into the Joqarı Keńes (Supreme Council) one:

1. **applications** — add `kind` (murajaat | feedback) discriminator + nullable
   `feedback_type` (complaint/suggestion/gratitude). Categories are no longer
   used (the existing nullable `category_id` is left in place, simply unset).
2. **appointments** — qabul has no official, no fixed date, no queue number for
   the Council (staff call the citizen back). Make `official_id`,
   `scheduled_date`, `queue_number` nullable and drop the
   `uq_appointments_official_date_queue` unique constraint + the
   `ix_appointments_org_date` index. Historical rows keep their old values.
3. **officials cleanup** — NULL out `appointments.official_id` (so the RESTRICT
   FK doesn't block) and delete all `org_kb_officials` rows. The official
   concept is gone.
4. **organizations** — rename the seeded `nukus-hokimiyat` org to the Council.
5. **system_ai_defaults** — clear `default_officials` (no officials to seed).

The Council prompt sections + tools come from `core/seed.py` on a fresh DB
(ensure_system_ai_defaults populates the empty singleton). This migration does
not rewrite the section JSON — on a brand-new joqari_kenes deployment the seed
is the source of truth; on an already-populated DB, re-seed via the super-panel
/ai-defaults editor. Forward-only.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


COUNCIL_NAME_TRANSLATIONS = {
    "uz": "Qoraqalpog'iston Respublikasi Joqarg'i Kengashi",
    "kk": "Қарақалпақстан Республикасы Жоқарғы Кеңеси",
    "ru": "Жокаргы Кенес Республики Каракалпакстан",
}


def upgrade() -> None:
    # 1. applications: kind + feedback_type
    op.add_column(
        "applications",
        sa.Column(
            "kind",
            sa.String(length=16),
            server_default="murajaat",
            nullable=False,
        ),
    )
    op.add_column(
        "applications",
        sa.Column("feedback_type", sa.String(length=16), nullable=True),
    )

    # 2. appointments: drop the official/date/queue uniqueness + make nullable
    op.drop_constraint(
        "uq_appointments_official_date_queue", "appointments", type_="unique"
    )
    op.drop_index("ix_appointments_org_date", table_name="appointments")
    op.alter_column(
        "appointments", "official_id",
        existing_type=postgresql.UUID(as_uuid=True), nullable=True,
    )
    op.alter_column(
        "appointments", "scheduled_date", existing_type=sa.Date(), nullable=True
    )
    op.alter_column(
        "appointments", "queue_number", existing_type=sa.Integer(), nullable=True
    )

    # 3. officials cleanup — NULL the FK first so the RESTRICT delete succeeds.
    op.execute(sa.text("UPDATE appointments SET official_id = NULL"))
    op.execute(sa.text("DELETE FROM org_kb_officials"))

    # 4. rename the seeded Nukus org to the Council (only if it's still there).
    op.execute(
        sa.text(
            "UPDATE organizations SET "
            "slug = 'joqari-kenes', "
            "name = :name, "
            "name_translations = CAST(:trans AS jsonb) "
            "WHERE slug = 'nukus-hokimiyat'"
        ).bindparams(
            sa.bindparam("name", COUNCIL_NAME_TRANSLATIONS["uz"], type_=sa.String),
            sa.bindparam(
                "trans", json.dumps(COUNCIL_NAME_TRANSLATIONS), type_=sa.String
            ),
        )
    )

    # 5. clear seed officials on the singleton AI defaults.
    op.execute(
        sa.text(
            "UPDATE system_ai_defaults SET default_officials = CAST('[]' AS jsonb) "
            "WHERE id = 1"
        )
    )


def downgrade() -> None:
    # Forward-only in spirit (data was deleted). Reverse only the safe schema
    # bits: drop the new columns and re-create the dropped index. The unique
    # constraint + NOT NULLs are not restored (rows now hold NULLs).
    op.drop_column("applications", "feedback_type")
    op.drop_column("applications", "kind")
    op.create_index(
        "ix_appointments_org_date", "appointments", ["org_id", "scheduled_date"]
    )
