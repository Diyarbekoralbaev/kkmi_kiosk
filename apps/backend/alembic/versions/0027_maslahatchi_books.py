"""the general assistant may look books up

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-04

Asked "do you have a book about anatomy" on the AI Maslahatchi screen, the
agent told visitors to go and ask a librarian. It was not being obstinate: that
menu declared only `navigate_to_screen` and `show_info_card`, so it had no way
to see the catalogue and improvised the only answer available to it.

`find_book` and `show_books` now travel with that menu (ai/tools.py), and this
adds the paragraph that tells the agent they are there — without it the model
keeps the habit, since nothing in the prompt says the catalogue is reachable
from this screen.

The wording borrows the discipline already in `focus_library`: the catalogue is
the only thing that counts, and a book the search did not return is a book the
institute does not hold, however well the model knows it. Repeating that here
matters more than it would elsewhere — this is the screen where the model is
otherwise encouraged to answer from its own knowledge.

Forward-only, and idempotent: the paragraph is appended once, keyed on a
sentence that only it contains.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MARKER = "Books are the one thing on this screen you look up"

PARAGRAPH = (
    "\n\n"
    "Books are the one thing on this screen you look up rather than answer "
    "from what you know. If the visitor asks whether the library holds "
    "something, or wants a book on a subject, call find_book; for «what books "
    "do you have» call show_books. The institute's own catalogue is the only "
    "source that counts here. Report what came back — title, author, and the "
    "shelf if the card carries one. If the search returned nothing, the "
    "institute does not hold that book, however famous it is: say so and send "
    "them to the reading-room desk. State no title, author, year or shelf that "
    "a tool result did not contain.\n\n"
    "Some books are scanned and can be read on the kiosk itself. When a result "
    "comes back with pages, say the visitor can read it here and call "
    "navigate_to_screen with «library» so they can open it."
)


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT default_sections FROM system_ai_defaults WHERE id = 1")
    ).first()
    if row is None or row[0] is None:
        return

    sections = list(row[0])
    changed = False
    for sec in sections:
        if sec.get("section_key") != "focus_maslahatchi":
            continue
        content = str(sec.get("content", ""))
        if MARKER in content:
            break
        sec["content"] = content.rstrip() + PARAGRAPH
        changed = True
        break

    if changed:
        op.execute(
            sa.text(
                "UPDATE system_ai_defaults "
                "SET default_sections = CAST(:s AS jsonb) WHERE id = 1"
            ).bindparams(sa.bindparam("s", json.dumps(sections), type_=sa.String))
        )


def downgrade() -> None:
    """Forward-only: the paragraph describes tools the menu now carries, and
    removing it would leave the agent with the tools and no instruction."""
