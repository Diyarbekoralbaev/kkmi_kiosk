"""hemis mirror tables

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-27

Creates the local mirror of the institute's HEMIS data (student.kkmi.uz).

Why mirror instead of calling HEMIS live: the kiosk answers by voice, and a
0.5–3 s upstream round-trip lands in the middle of a spoken sentence. Mirroring
also keeps the schedule menu working while HEMIS is down or the institute's
uplink is out — a kiosk in a corridor has to degrade gracefully.

Volume for KKMI's current academic year: ~114k lessons, 998 groups, 341
subjects, 60 departments, 231 auditoriums, 260 employees. Small for Postgres —
no partitioning, plain b-tree indexes.

Deliberately NO foreign keys between these tables: upstream is paginated and
eventually consistent, so `schedule-list` regularly references a group or
employee that only a later page of `group-list` introduces, and rows vanish
upstream without notice. FKs would convert each of those into a failed sync
rather than one stale row.

Down-migration drops everything — the mirror is fully rebuildable from HEMIS,
so there is nothing to preserve.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "hemis_departments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(64), server_default="", nullable=False),
        sa.Column("structure_type_code", sa.String(16), server_default="", nullable=False),
        sa.Column("structure_type_name", sa.String(64), server_default="", nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
    )

    op.create_table(
        "hemis_specialties",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("code", sa.String(32), server_default="", nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("education_type_code", sa.String(16), server_default="", nullable=False),
        sa.Column("education_type_name", sa.String(64), server_default="", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_hemis_specialties_department_id", "hemis_specialties", ["department_id"]
    )

    op.create_table(
        "hemis_groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("specialty_id", sa.Integer(), nullable=True),
        sa.Column("specialty_name", sa.String(255), server_default="", nullable=False),
        sa.Column("education_lang_code", sa.String(16), server_default="", nullable=False),
        sa.Column("education_lang_name", sa.String(64), server_default="", nullable=False),
        sa.Column("curriculum_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_hemis_groups_specialty_id", "hemis_groups", ["specialty_id"])
    op.create_index(
        "ix_hemis_groups_department_active", "hemis_groups", ["department_id", "active"]
    )

    op.create_table(
        "hemis_subjects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(64), server_default="", nullable=False),
        *_timestamps(),
    )

    op.create_table(
        "hemis_employees",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(255), nullable=False),
        *_timestamps(),
    )

    op.create_table(
        "hemis_auditoriums",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(128), server_default="", nullable=False),
        sa.Column("building", sa.String(255), server_default="", nullable=False),
        sa.Column("kind", sa.String(64), server_default="", nullable=False),
        sa.Column("volume", sa.Integer(), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "hemis_lesson_pairs",
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("name", sa.String(64), server_default="", nullable=False),
        sa.Column("start_time", sa.String(8), server_default="", nullable=False),
        sa.Column("end_time", sa.String(8), server_default="", nullable=False),
        *_timestamps(),
    )

    op.create_table(
        "hemis_training_types",
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("name", sa.String(64), server_default="", nullable=False),
        *_timestamps(),
    )

    op.create_table(
        "hemis_semesters",
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("name", sa.String(64), server_default="", nullable=False),
        *_timestamps(),
    )

    op.create_table(
        "hemis_lessons",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("lesson_date", sa.Date(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("pair_code", sa.String(16), server_default="", nullable=False),
        sa.Column("start_time", sa.String(8), server_default="", nullable=False),
        sa.Column("end_time", sa.String(8), server_default="", nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("auditorium_code", sa.String(32), server_default="", nullable=False),
        sa.Column("faculty_id", sa.Integer(), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("training_type_code", sa.String(16), server_default="", nullable=False),
        sa.Column("semester_code", sa.String(16), server_default="", nullable=False),
        sa.Column("week_id", sa.Integer(), nullable=True),
        sa.Column("hemis_updated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index(
        "ix_hemis_lessons_group_date", "hemis_lessons", ["group_id", "lesson_date"]
    )
    op.create_index("ix_hemis_lessons_date", "hemis_lessons", ["lesson_date"])
    op.create_index(
        "ix_hemis_lessons_employee_date", "hemis_lessons", ["employee_id", "lesson_date"]
    )

    op.create_table(
        "hemis_sync_state",
        sa.Column("resource", sa.String(64), primary_key=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("item_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        *_timestamps(),
    )


def downgrade() -> None:
    for table in (
        "hemis_sync_state",
        "hemis_lessons",
        "hemis_semesters",
        "hemis_training_types",
        "hemis_lesson_pairs",
        "hemis_auditoriums",
        "hemis_employees",
        "hemis_subjects",
        "hemis_groups",
        "hemis_specialties",
        "hemis_departments",
    ):
        op.drop_table(table)
