"""Read layer over the institute's own book catalogue.

Search runs in Python rather than SQL. The catalogue is one institute's kiosk
holdings — hundreds of rows, not millions — so the whole active set fits in
memory, and doing it here buys two things SQL would fight us for: the
Cyrillic→Latin fold from `schedule.normalize_text`, so «Сапин» finds "Sapin",
and token containment, so "sapin anatomiya" matches "Anatomiya cheloveka /
M.R. Sapin" in either order.

An ILIKE query would miss both, and `unaccent`/`pg_trgm` would need extensions
installed on every environment for a table this small.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.library import LibraryBook, section_label
from .schedule import normalize_text


def _book_dict(b: LibraryBook, locale: str = "kk") -> dict[str, Any]:
    return {
        "id": str(b.id),
        "title": b.title,
        "authors": b.authors,
        "year": b.year,
        "publisher": b.publisher,
        "isbn": b.isbn,
        "language": b.language,
        "section": b.section,
        "section_label": section_label(b.section, locale),
        "copies": b.copies,
        "shelf": b.shelf,
        "description": b.description,
        "available": b.available,
        # Whether a jacket exists, not the bytes. The kiosk uses this to decide
        # between fetching the image and drawing its own designed cover, and it
        # keeps a browse listing small.
        "has_cover": b.cover is not None,
        # Page count doubles as "is there anything to read": the kiosk shows
        # the reader button only when this is non-zero, and needs the number
        # anyway to render "12 / 142" and to stop at the last page.
        "pages": b.page_count,
    }


def _haystack(b: LibraryBook) -> str:
    return normalize_text(f"{b.title} {b.authors} {b.publisher}")


async def _active(session: AsyncSession, org_id: uuid.UUID) -> list[LibraryBook]:
    return list(
        (
            await session.execute(
                select(LibraryBook)
                .where(
                    LibraryBook.org_id == org_id,
                    LibraryBook.deleted_at.is_(None),
                )
                .order_by(LibraryBook.title)
            )
        )
        .scalars()
        .all()
    )


async def list_books(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    section: str | None = None,
    locale: str = "kk",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """The browse list, optionally narrowed to one shelf section."""
    books = await _active(session, org_id)
    if section:
        books = [b for b in books if b.section == section]
    return [_book_dict(b, locale) for b in books[:limit]]


async def book_by_id(
    session: AsyncSession, org_id: uuid.UUID, book_id: uuid.UUID, locale: str = "kk"
) -> dict[str, Any] | None:
    b = (
        await session.execute(
            select(LibraryBook).where(
                LibraryBook.id == book_id,
                LibraryBook.org_id == org_id,
                LibraryBook.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    return _book_dict(b, locale) if b else None


async def search_books(
    session: AsyncSession,
    org_id: uuid.UUID,
    query: str,
    *,
    locale: str = "kk",
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Books matching a spoken or typed query, best first.

    Every token of the query must appear somewhere in title/authors/publisher.
    Requiring ALL of them — rather than ranking by how many hit — is what keeps
    "anatomiya sapin" from returning every anatomy book on the shelf with the
    right one buried in the middle. A visitor who over-specifies gets nothing
    back and rephrases; one who gets nine near-misses read aloud gives up.
    """
    tokens = [t for t in normalize_text(query).split() if t]
    if not tokens:
        return []

    scored: list[tuple[float, LibraryBook]] = []
    for b in await _active(session, org_id):
        hay = _haystack(b)
        if not all(t in hay for t in tokens):
            continue
        # Prefer a title hit over an author-only hit, and a short title over a
        # long one — "Anatomiya" should outrank "…atlas of anatomy, vol 3".
        title = normalize_text(b.title)
        in_title = sum(1 for t in tokens if t in title)
        scored.append((in_title * 10 - len(title) / 100, b))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [_book_dict(b, locale) for _, b in scored[:limit]]


async def sections_with_counts(
    session: AsyncSession, org_id: uuid.UUID, locale: str = "kk"
) -> list[dict[str, Any]]:
    """Shelf sections that actually hold something, for the browse screen.

    Empty sections are omitted: the kiosk should not offer a category that
    leads to a blank list.
    """
    rows = (
        await session.execute(
            select(LibraryBook.section, func.count(LibraryBook.id))
            .where(
                LibraryBook.org_id == org_id,
                LibraryBook.deleted_at.is_(None),
            )
            .group_by(LibraryBook.section)
        )
    ).all()
    out = [
        {
            "section": section,
            "label": section_label(section, locale),
            "count": int(count),
        }
        for section, count in rows
    ]
    out.sort(key=lambda s: s["label"])
    return out
