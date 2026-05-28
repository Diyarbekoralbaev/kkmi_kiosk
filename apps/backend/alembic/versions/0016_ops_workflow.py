"""ops workflow: categories table + reviewer role + returned status + appointment outcome

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-15

Ships the gov-ops workflow upgrade in one migration so the gov-panel can
roll out assignment + categorization + the new dashboard without
half-deployed states. Specifically:

1. New `application_categories` table — global list (no org_id), seeded
   with 10 default domains (housing, land, construction, utilities,
   employment, education, health, social, business, other). Each row
   carries a uz/kk/ru `name_translations` dict.

2. `applications.category_id` UUID FK → application_categories, nullable,
   ON DELETE SET NULL. Existing rows stay NULL; reviewers/agent populate
   over time. No backfill: AI couldn't have guessed at the time, manual
   re-categorization is reviewer work.

3. `applications.status` — new value `returned` is just an extra string
   the existing String(32) column accepts. No DB-level enum to alter.

4. `appointments.assigned_user_id` UUID FK → users, nullable, SET NULL.
   `appointments.result_note` TEXT NOT NULL DEFAULT ''.
   `appointments.assigned_at` TIMESTAMP nullable.

5. `users.role` — new value `reviewer` is just an extra string the
   existing String(32) column accepts. Existing rows untouched.

Forward-only. Categories live in the DB after this; super-admin can
edit them through `/api/super/application-categories`. The seed list
matches the agent's prompt — keep them in sync going forward.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Mirror of domain/category.py DEFAULT_CATEGORIES. Duplicated rather than
# imported because migrations are supposed to be self-contained and not
# break if the domain module is later refactored.
SEED_CATEGORIES: list[dict[str, object]] = [
    {"slug": "housing",      "order": 10,  "uz": "Uy-jay",        "kk": "Үй-жай",          "ru": "Жилищный"},
    {"slug": "land",         "order": 20,  "uz": "Yer ajratish",  "kk": "Жер ажыратыў",    "ru": "Земельный"},
    {"slug": "construction", "order": 30,  "uz": "Qurilish",      "kk": "Қурылыс",         "ru": "Строительство"},
    {"slug": "utilities",    "order": 40,  "uz": "Kommunal",      "kk": "Коммунал",        "ru": "Коммунальный"},
    {"slug": "employment",   "order": 50,  "uz": "Ish bandlik",   "kk": "Жумыс бентлик",   "ru": "Трудоустройство"},
    {"slug": "education",    "order": 60,  "uz": "Ta'lim",        "kk": "Билимлендириў",   "ru": "Образование"},
    {"slug": "health",       "order": 70,  "uz": "Sog'liq",       "kk": "Денсаўлық",       "ru": "Здравоохранение"},
    {"slug": "social",       "order": 80,  "uz": "Ijtimoiy",      "kk": "Социаллық",       "ru": "Социальный"},
    {"slug": "business",     "order": 90,  "uz": "Tadbirkorlik",  "kk": "Исбилерменлик",   "ru": "Предпринимательство"},
    {"slug": "other",        "order": 999, "uz": "Boshqa",        "kk": "Басқа",           "ru": "Прочее"},
]


def upgrade() -> None:
    # ── 1. application_categories ────────────────────────────────────
    op.create_table(
        "application_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(length=32), nullable=False, unique=True),
        sa.Column(
            "name_translations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index(
        "ix_application_categories_slug", "application_categories", ["slug"]
    )

    # Seed defaults via parametrized INSERT — keeps JSONB casting clean.
    # asyncpg is strict about UUID vs varchar so both id and the JSONB
    # blob need explicit CASTs from string bind values.
    insert_sql = sa.text(
        "INSERT INTO application_categories (id, slug, name_translations, \"order\") "
        "VALUES (CAST(:id AS uuid), :slug, CAST(:translations AS jsonb), :order)"
    ).bindparams(
        sa.bindparam("id", type_=sa.String),
        sa.bindparam("translations", type_=sa.String),
    )
    for cat in SEED_CATEGORIES:
        op.execute(
            insert_sql.bindparams(
                id=str(uuid.uuid4()),
                slug=cat["slug"],
                translations=json.dumps(
                    {"uz": cat["uz"], "kk": cat["kk"], "ru": cat["ru"]}
                ),
                order=cat["order"],
            )
        )

    # ── 2. applications.category_id ───────────────────────────────────
    op.add_column(
        "applications",
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("application_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_applications_category_id", "applications", ["category_id"]
    )

    # ── 3. appointments outcome columns ───────────────────────────────
    op.add_column(
        "appointments",
        sa.Column(
            "assigned_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "appointments",
        sa.Column(
            "result_note", sa.Text(), nullable=False, server_default=""
        ),
    )
    op.create_index(
        "ix_appointments_assigned_user_id",
        "appointments",
        ["assigned_user_id"],
    )

    # Status `returned` for applications + role `reviewer` for users need no
    # schema change — both columns are String(32) and accept new values
    # naturally. Backend validation enforces the new state in code.


def downgrade() -> None:
    # Forward-only in spirit, but provide a clean reversal for local dev.
    op.drop_index("ix_appointments_assigned_user_id", table_name="appointments")
    op.drop_column("appointments", "result_note")
    op.drop_column("appointments", "assigned_at")
    op.drop_column("appointments", "assigned_user_id")

    op.drop_index("ix_applications_category_id", table_name="applications")
    op.drop_column("applications", "category_id")

    op.drop_index(
        "ix_application_categories_slug", table_name="application_categories"
    )
    op.drop_table("application_categories")
