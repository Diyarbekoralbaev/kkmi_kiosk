"""Enable qabul (appointment) tools and refresh seed sections for existing orgs.

system_ai_defaults stores templates used when cloning into a NEW org. Existing
orgs (e.g. the bootstrap Nukus seed) are untouched by code changes to those
templates, so this data migration:
  1. Inserts the two new tool rows (preview_appointment, submit_appointment)
     enabled-by-default for every existing org that does not already have them.
  2. Updates the in-DB system_ai_defaults JSONB to include the two new tools so
     orgs created after this migration also pick them up.

We deliberately do NOT touch existing org_prompt_sections rows — section text
may have been customized by a gov admin. New seed text only applies to fresh
orgs (via clone_defaults_into_org).

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-08
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_TOOL_KEYS = ("preview_appointment", "submit_appointment")


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add the two new tool rows to every existing org that lacks them.
    org_ids = [
        row[0]
        for row in bind.execute(sa.text("SELECT id FROM organizations")).all()
    ]
    for org_id in org_ids:
        existing_keys = {
            row[0]
            for row in bind.execute(
                sa.text("SELECT tool_key FROM org_tools WHERE org_id = :oid"),
                {"oid": org_id},
            ).all()
        }
        for key in NEW_TOOL_KEYS:
            if key in existing_keys:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO org_tools (id, org_id, tool_key, enabled, "
                    "created_at, updated_at) "
                    "VALUES (:id, :oid, :key, TRUE, now(), now())"
                ),
                {"id": uuid.uuid4(), "oid": org_id, "key": key},
            )

    # 2. Patch system_ai_defaults.default_tools JSONB so future orgs get the
    #    tools too. Defensive: keep existing entries untouched, only append.
    rows = bind.execute(
        sa.text("SELECT id, default_tools FROM system_ai_defaults")
    ).all()
    for row_id, default_tools in rows:
        tools = default_tools if isinstance(default_tools, list) else (default_tools or [])
        existing_keys = {t.get("tool_key") for t in tools if isinstance(t, dict)}
        changed = False
        for key in NEW_TOOL_KEYS:
            if key not in existing_keys:
                tools.append({"tool_key": key, "enabled": True})
                changed = True
        if changed:
            bind.execute(
                sa.text(
                    "UPDATE system_ai_defaults SET default_tools = :tools, "
                    "updated_at = now() WHERE id = :id"
                ),
                {"tools": json.dumps(tools), "id": row_id},
            )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM org_tools WHERE tool_key = ANY(:keys)"
        ),
        {"keys": list(NEW_TOOL_KEYS)},
    )
    # Best-effort revert of system_ai_defaults JSONB.
    rows = bind.execute(
        sa.text("SELECT id, default_tools FROM system_ai_defaults")
    ).all()
    for row_id, default_tools in rows:
        tools = default_tools if isinstance(default_tools, list) else (default_tools or [])
        filtered = [t for t in tools if t.get("tool_key") not in NEW_TOOL_KEYS]
        if len(filtered) != len(tools):
            bind.execute(
                sa.text(
                    "UPDATE system_ai_defaults SET default_tools = :tools, "
                    "updated_at = now() WHERE id = :id"
                ),
                {"tools": json.dumps(filtered), "id": row_id},
            )
