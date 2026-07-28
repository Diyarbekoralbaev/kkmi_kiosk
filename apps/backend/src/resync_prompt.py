"""Push edited prompt sections from code into the DB. Entry point:
`python -m src.resync_prompt`.

`ensure_system_ai_defaults` writes `DEFAULT_SECTIONS` exactly once, on an empty
database, and returns the existing row ever after. That is correct — the super
admin owns the prompt once the system is live and a redeploy must not silently
undo their edits. The cost is that a correction made in `seed.py` never reaches
a running install.

This is the escape hatch for that case. It is deliberately manual and
deliberately loud: it prints what differs and changes nothing unless you pass
`--apply`, and `--only` limits it to the sections you actually corrected so an
admin's edits elsewhere are left alone.

    python -m src.resync_prompt                        # show the diff
    python -m src.resync_prompt --only identity language --apply
"""
from __future__ import annotations

import argparse
import asyncio

import structlog
from sqlalchemy.orm.attributes import flag_modified

from .core.db import AsyncSessionLocal
from .core.logging import setup_logging
from .core.seed import DEFAULT_SECTIONS, ensure_system_ai_defaults

logger = structlog.get_logger(__name__)


async def resync(only: list[str] | None, apply: bool) -> int:
    wanted = {
        str(s["section_key"]): s
        for s in DEFAULT_SECTIONS
        if only is None or str(s["section_key"]) in only
    }
    if only:
        for key in only:
            if key not in wanted:
                print(f"! no such section in seed.py: {key}")
                return 2

    async with AsyncSessionLocal() as session:
        row = await ensure_system_ai_defaults(session)
        sections = list(row.default_sections or [])

        changed: list[str] = []
        for i, live in enumerate(sections):
            key = str(live.get("section_key", ""))
            src = wanted.get(key)
            if src is None or str(live.get("content", "")) == str(src["content"]):
                continue
            changed.append(key)
            print(f"\n=== {key} ===")
            print(f"--- db   ({len(str(live.get('content', '')))} chars)")
            print(f"+++ seed ({len(str(src['content']))} chars)")
            print(str(src["content"]))
            sections[i] = {**live, "content": src["content"]}

        missing = [k for k in wanted if k not in {s.get("section_key") for s in sections}]
        for key in missing:
            changed.append(key)
            print(f"\n=== {key} (absent in db — will be added) ===")
            print(str(wanted[key]["content"]))
            sections.append(dict(wanted[key]))

        if not changed:
            print("nothing to do — db already matches seed.py")
            return 0

        if not apply:
            print(f"\n{len(changed)} section(s) differ: {', '.join(changed)}")
            print("re-run with --apply to write them")
            return 1

        row.default_sections = sections
        # JSONB columns are mutated in place; without this SQLAlchemy sees no
        # change on the attribute and issues no UPDATE.
        flag_modified(row, "default_sections")
        await session.commit()
        logger.info("prompt_sections_resynced", sections=changed)
        print(f"\nwrote {len(changed)} section(s): {', '.join(changed)}")
        print("takes effect on the NEXT kiosk session; open ones keep their prompt")
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--only",
        nargs="+",
        default=None,
        metavar="SECTION_KEY",
        help="Limit to these sections. Everything else is left untouched.",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Actually write. Without it this is a dry run.",
    )
    args = ap.parse_args()
    setup_logging()
    return asyncio.run(resync(args.only, args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
