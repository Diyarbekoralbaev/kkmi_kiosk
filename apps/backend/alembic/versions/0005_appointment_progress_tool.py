"""Enable appointment_progress tool for existing orgs.

Same shape as 0004 — adds the new tool row to every org that doesn't have it,
and patches the system_ai_defaults JSONB so freshly-cloned orgs pick it up.
The new tool is a stepper-only signal (no DB writes); enabling it for an org
that didn't ask for it is harmless.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-08
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TOOL_KEYS = ("appointment_progress",)


APPEND_NOTE = (
    "\n\nappointment_progress tool — hár user reply'dan keyin "
    "(stage=topic, official, phone) chaqırıw. Ekran sahnası "
    "pog'oneli jańalanadı: 1. Másele kórinedi → 2. Ofitsial kórinedi → "
    "3. Telefon kórinedi → 4. Tolıq preview_appointment."
)


def upgrade() -> None:
    bind = op.get_bind()

    # Refresh the tool_rules banner so it lists all three appointment tools.
    # WHERE clause ensures we only touch sections that still match the v1
    # default — gov-customized prompts are left alone.
    bind.execute(
        sa.text(
            "UPDATE org_prompt_sections "
            "SET content = REPLACE(content, "
            "  '===== TOOL: preview_appointment / submit_appointment =====', "
            "  '===== TOOL: appointment_progress / preview_appointment / submit_appointment ====='"
            "), updated_at = now() "
            "WHERE section_key = 'tool_rules' "
            "  AND content LIKE '%===== TOOL: preview_appointment / submit_appointment =====%' "
            "  AND content NOT LIKE '%appointment_progress%'"
        )
    )
    # Append a short note explaining when to call the new tool — only for
    # sections that still don't mention it (idempotent re-run safe).
    bind.execute(
        sa.text(
            "UPDATE org_prompt_sections "
            "SET content = content || :note, updated_at = now() "
            "WHERE section_key = 'tool_rules' "
            "  AND content NOT LIKE '%appointment_progress%'"
        ),
        {"note": APPEND_NOTE},
    )

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
        sa.text("DELETE FROM org_tools WHERE tool_key = ANY(:keys)"),
        {"keys": list(NEW_TOOL_KEYS)},
    )
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
