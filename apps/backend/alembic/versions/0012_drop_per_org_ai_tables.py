"""drop per-org AI tables — prompt becomes global static

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-14

The AI prompt was previously stored per-org in `org_prompt_sections` (with
a `gov_editable` flag), `org_screens`, `org_tools`, and `org_ai_settings`.
The product never needed per-org prompt customization — the whole knob was
removed, and the prompt is now read from `system_ai_defaults` (singleton,
super-admin owned) at every WS connect.

Drop the four per-org tables and the unused `default_screens` JSONB column.
`org_kb_officials` is unaffected — officials remain per-org.

Destructive: any per-org section edits are lost. The intended source of
truth is `system_ai_defaults.default_sections` (already populated from
seed). Backup the four tables before applying in production if you need
to preserve customizations.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_org_prompt_sections_org_order", table_name="org_prompt_sections")
    op.drop_index("ix_org_prompt_sections_org_id", table_name="org_prompt_sections")
    op.drop_constraint(
        "uq_org_prompt_sections_org_id_section_key",
        "org_prompt_sections",
        type_="unique",
    )
    op.drop_table("org_prompt_sections")

    op.drop_index("ix_org_screens_org_id", table_name="org_screens")
    op.drop_constraint(
        "uq_org_screens_org_id_screen_key", "org_screens", type_="unique"
    )
    op.drop_table("org_screens")

    op.drop_index("ix_org_tools_org_id", table_name="org_tools")
    op.drop_constraint("uq_org_tools_org_id_tool_key", "org_tools", type_="unique")
    op.drop_table("org_tools")

    op.drop_table("org_ai_settings")

    op.drop_column("system_ai_defaults", "default_screens")


def downgrade() -> None:
    # Recreate the four tables + the column. Empty rows — per-org data is
    # not recoverable from this migration alone; restore from backup if you
    # need it.
    op.add_column(
        "system_ai_defaults",
        sa.Column(
            "default_screens",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.create_table(
        "org_ai_settings",
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("voice", sa.String(64), nullable=False),
        sa.Column("temperature", sa.Float, nullable=False),
        sa.Column("top_p", sa.Float, nullable=False),
        sa.Column("top_k", sa.Integer, nullable=False),
        sa.Column("max_output_tokens", sa.Integer, nullable=False),
        sa.Column("response_modalities", sa.String(32), nullable=False),
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

    op.create_table(
        "org_prompt_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section_key", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("order", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "gov_editable", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
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
    op.create_unique_constraint(
        "uq_org_prompt_sections_org_id_section_key",
        "org_prompt_sections",
        ["org_id", "section_key"],
    )
    op.create_index(
        "ix_org_prompt_sections_org_id", "org_prompt_sections", ["org_id"]
    )
    op.create_index(
        "ix_org_prompt_sections_org_order",
        "org_prompt_sections",
        ["org_id", "order"],
    )

    op.create_table(
        "org_screens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("screen_key", sa.String(32), nullable=False),
        sa.Column(
            "enabled", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column("order", sa.Integer, nullable=False, server_default="0"),
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
    op.create_unique_constraint(
        "uq_org_screens_org_id_screen_key",
        "org_screens",
        ["org_id", "screen_key"],
    )
    op.create_index("ix_org_screens_org_id", "org_screens", ["org_id"])

    op.create_table(
        "org_tools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_key", sa.String(64), nullable=False),
        sa.Column(
            "enabled", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
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
    op.create_unique_constraint(
        "uq_org_tools_org_id_tool_key", "org_tools", ["org_id", "tool_key"]
    )
    op.create_index("ix_org_tools_org_id", "org_tools", ["org_id"])
