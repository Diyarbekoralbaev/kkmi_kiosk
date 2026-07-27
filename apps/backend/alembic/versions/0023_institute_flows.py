"""institute flows: applicant/visitor names + reset the AI prompt

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-27

Two unrelated-looking changes that both come from the same shift: the kiosk
stopped forwarding appeals to an external government cabinet and started
handling them itself, for a medical institute rather than a council.

1. Names on the records.
   Appeals used to be filed into cabinet.murajat.uz, which held the citizen
   registry, so our `applications` row needed no name. Now the appeal lives
   here and staff have to know who wrote it — `applicant_name`. Same for
   `appointments`: the council flow was "leave a phone, we call back", while
   the institute books a named visitor in to see a specific person, so
   `visitor_name` joins the existing `official_id`.

2. The AI prompt is reset rather than migrated.
   `system_ai_defaults` is deleted so app startup re-seeds it from
   `core.seed.DEFAULT_SECTIONS`. The old row described a Karakalpak-Cyrillic
   council assistant with a citizen-lookup appeal flow; not one of its sections
   survives into a four-language institute assistant with per-menu focus
   blocks. Copying ~5,000 characters of new prompt text into this migration
   just to overwrite it verbatim would leave two copies to keep in sync.

   This DISCARDS any prompt edits made through the super panel. That is the
   intent — the previous text is for a different organisation. Nothing else in
   the row is worth preserving either: model/voice/tuning are re-seeded to the
   same values.

Down-migration drops the two columns. It does not restore the council prompt;
`downgrade` then `upgrade` simply re-seeds the institute one.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column(
            "applicant_name", sa.String(255), server_default="", nullable=False
        ),
    )
    op.add_column(
        "appointments",
        sa.Column("visitor_name", sa.String(255), server_default="", nullable=False),
    )

    # Startup (core.bootstrap → ensure_system_ai_defaults) re-creates this row
    # from the institute prompt. It only seeds when the row is absent, hence
    # the delete rather than an UPDATE.
    op.execute("DELETE FROM system_ai_defaults WHERE id = 1")


def downgrade() -> None:
    op.drop_column("appointments", "visitor_name")
    op.drop_column("applications", "applicant_name")
