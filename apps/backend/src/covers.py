"""Fetch book jackets from Open Library. Entry point: `python -m src.covers`.

Deliberately a separate command rather than something the gov panel triggers on
save. Fetching is slow, rate-limited and frequently fruitless, and a librarian
typing a card should not wait on a foreign server to find out their book has no
jacket. Run it after a batch of cards go in, or nightly beside the HEMIS sync.

Open Library is the source because it is free, needs no key, and is keyed by
ISBN — which is exactly the field a librarian already copies off the back
cover. Books without an ISBN are skipped, not guessed at: the kiosk renders a
designed typographic cover for them instead, which is honest and always
available.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

import httpx
import structlog
from sqlalchemy import or_, select

from .core.db import AsyncSessionLocal
from .core.logging import setup_logging
from .domain.library import LibraryBook

logger = structlog.get_logger(__name__)

# `-L` is the large jacket, ~40-80 KB. `default=false` makes a miss a 404
# instead of a 1×1 placeholder pixel, which is the difference between knowing
# there is no cover and storing a blank one.
COVER_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"

# Open Library asks for no more than 100 requests per 5 minutes on this
# endpoint. One request per second keeps us comfortably under it and a full
# catalogue still finishes in minutes.
DELAY_SECONDS = 1.0
TIMEOUT_SECONDS = 20

# Anything smaller is not a jacket — usually an error page served as an image.
MIN_COVER_BYTES = 1024


def _clean_isbn(raw: str) -> str:
    """Strip the separators librarians actually type. Open Library accepts
    either ISBN-10 or ISBN-13 but not the hyphens."""
    return "".join(ch for ch in (raw or "") if ch.isdigit() or ch in "Xx")


def isbn_is_valid(isbn: str) -> bool:
    """Check the ISBN's own check digit before asking upstream for a jacket.

    Not pedantry. A mistyped digit usually still resolves at Open Library — to
    a DIFFERENT book — so the shelf would show a confident, wrong cover for a
    card that is merely one keystroke off. No cover at all is honest; another
    book's jacket is a lie the visitor has no way to catch. The check digit
    catches exactly the single-digit and transposition errors that typing
    produces.
    """
    s = isbn.upper()
    if len(s) == 13 and s.isdigit():
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(s[:12]))
        return (10 - total % 10) % 10 == int(s[12])
    if len(s) == 10 and s[:9].isdigit() and (s[9].isdigit() or s[9] == "X"):
        total = sum(int(d) * (10 - i) for i, d in enumerate(s[:9]))
        total += 10 if s[9] == "X" else int(s[9])
        return total % 11 == 0
    return False


async def fetch_one(client: httpx.AsyncClient, isbn: str) -> bytes | None:
    url = COVER_URL.format(isbn=isbn)
    try:
        r = await client.get(url, follow_redirects=True)
    except httpx.HTTPError as e:
        logger.warning("cover_fetch_failed", isbn=isbn, error=str(e))
        return None
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        logger.warning("cover_fetch_status", isbn=isbn, status=r.status_code)
        return None
    if len(r.content) < MIN_COVER_BYTES:
        return None
    return r.content


async def run(*, refetch: bool, limit: int | None) -> int:
    async with AsyncSessionLocal() as session:
        stmt = select(LibraryBook).where(
            LibraryBook.deleted_at.is_(None),
            LibraryBook.isbn != "",
        )
        if not refetch:
            # Never tried, or tried and the ISBN has changed since. A recorded
            # miss is left alone — see the module docstring.
            stmt = stmt.where(
                or_(
                    LibraryBook.cover_fetched_at.is_(None),
                    LibraryBook.cover.is_(None) & LibraryBook.cover_fetched_at.is_(None),
                )
            )
        if limit:
            stmt = stmt.limit(limit)
        books = list((await session.execute(stmt)).scalars().all())

    if not books:
        print("nothing to fetch — every card with an ISBN has been tried")
        return 0

    found = missing = invalid = 0
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        for i, book in enumerate(books):
            isbn = _clean_isbn(book.isbn)
            if isbn and not isbn_is_valid(isbn):
                # Do not look it up. A mistyped ISBN usually still resolves —
                # to somebody else's book.
                invalid += 1
                print(f"  ! {book.title[:56]}  (ISBN check digit fails: {book.isbn})")
                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        row = await session.get(LibraryBook, book.id)
                        if row is not None:
                            row.cover_fetched_at = datetime.now(UTC)
                continue
            data = await fetch_one(client, isbn) if isbn else None
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    row = await session.get(LibraryBook, book.id)
                    if row is None:
                        continue
                    row.cover_fetched_at = datetime.now(UTC)
                    if data:
                        row.cover = data
            if data:
                found += 1
                print(f"  ✓ {book.title[:60]}  ({len(data) // 1024} KB)")
            else:
                missing += 1
                print(f"  · {book.title[:60]}  (no cover upstream)")
            if i < len(books) - 1:
                await asyncio.sleep(DELAY_SECONDS)

    logger.info("covers_fetched", found=found, missing=missing, invalid=invalid)
    print(f"\n{found} covers stored, {missing} without one")
    if invalid:
        print(f"{invalid} card(s) have an ISBN that fails its own check digit "
              f"— correct them in the gov panel and re-run with --refetch")
    print("cards without a cover render a designed one on the kiosk")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--refetch",
        action="store_true",
        help="Try every card again, including ones already known to have no "
             "cover. Use after correcting ISBNs.",
    )
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    setup_logging()
    return asyncio.run(run(refetch=args.refetch, limit=args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
