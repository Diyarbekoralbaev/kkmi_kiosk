"""Kiosk touch reads over the institute's book catalogue.

Touch twin of the `find_book` / `show_books` tools, same as `kiosk_schedule`
is the touch twin of the timetable tools: a visitor must be able to browse the
shelf sections and search without saying a word.

The org comes from the authenticated device, never from the request — see the
tenancy rule in CLAUDE.md.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Header, Query, Response
from sqlalchemy import select

from ..core import bookpages
from ..core import library as library_q
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import NotFoundError
from ..domain.library import SECTIONS, LibraryBook

router = APIRouter(prefix="/api/kiosk/library", tags=["kiosk:library"])


@router.get("/sections")
async def sections(
    session: DbSession,
    locale: str = Query(default="kk"),
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    """Shelf sections that actually hold books, with counts."""
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)
    return {
        "items": await library_q.sections_with_counts(
            session, device.org_id, locale=locale
        )
    }


@router.get("/books")
async def books(
    session: DbSession,
    section: str | None = Query(default=None),
    q: str | None = Query(default=None),
    locale: str = Query(default="kk"),
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    """Browse by section, or search when `q` is given."""
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)
    if q and q.strip():
        items = await library_q.search_books(
            session, device.org_id, q, locale=locale, limit=40
        )
    else:
        items = await library_q.list_books(
            session,
            device.org_id,
            section=section if section in SECTIONS else None,
            locale=locale,
        )
    return {"items": items}


@router.get("/books/{book_id}/cover.jpg")
async def book_cover(
    book_id: uuid.UUID,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> Response:
    """The stored jacket. 404 when there is none — the kiosk draws its own
    designed cover in that case rather than showing a broken frame."""
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)
    row = (
        await session.execute(
            select(LibraryBook.cover).where(
                LibraryBook.id == book_id,
                LibraryBook.org_id == device.org_id,
                LibraryBook.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundError()
    return Response(
        content=row,
        media_type="image/jpeg",
        # Jackets never change once stored, and the kiosk re-requests them on
        # every browse. A long cache keeps the shelf instant.
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/books/{book_id}/page/{page}.jpg")
async def book_page(
    book_id: uuid.UUID,
    page: int,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> Response:
    """One page of a scanned book, rendered to JPEG.

    A page at a time rather than the file: the reader on the kiosk is an image
    viewer, not a PDF viewer, which is what lets it run on hardware that cannot
    manage the second thing. The first request for a page renders it, every
    request after that is served from the cache beside the scan.
    """
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)
    row = (
        await session.execute(
            select(LibraryBook.pdf_path, LibraryBook.page_count).where(
                LibraryBook.id == book_id,
                LibraryBook.org_id == device.org_id,
                LibraryBook.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None or not row.pdf_path or row.page_count <= 0:
        raise NotFoundError()
    if page < 1 or page > row.page_count:
        raise NotFoundError()

    try:
        data = await bookpages.page_jpeg(book_id, row.pdf_path, page)
    except FileNotFoundError:
        # The row says there is a scan and the disk disagrees. Answer 404 so
        # the reader closes rather than hanging on a page that will never come.
        raise NotFoundError() from None

    return Response(
        content=data,
        media_type="image/jpeg",
        # A rendered page is immutable for the life of the scan, and a reader
        # walks back and forth over the same few pages.
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/books/{book_id}")
async def book_detail(
    book_id: uuid.UUID,
    session: DbSession,
    locale: str = Query(default="kk"),
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> dict[str, Any]:
    device = await resolve_device_from_signed_request(session, x_kiosk_auth)
    item = await library_q.book_by_id(session, device.org_id, book_id, locale=locale)
    if item is None:
        raise NotFoundError()
    return {"item": item}
