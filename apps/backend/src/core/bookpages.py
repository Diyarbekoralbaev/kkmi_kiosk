"""Scanned books on disk, and the page images the kiosk reads them through.

The kiosk never receives a PDF. It asks for page N and gets a JPEG, for two
reasons: the lobby machines are 2011 Intel boxes running a Native AOT binary,
where a PDF engine is the same class of dependency that already cost a week of
freezes; and a 16 MB scan crossing the institute's connection to show page one
is a bad trade when 200 KB will do.

Renders are cached on disk beside the scan. A textbook is read front-to-back by
one visitor after another, so the second reader of any page pays nothing, and
the cache is disposable — delete it and it rebuilds a page at a time.
"""
from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import pypdfium2
import structlog

from .config import get_settings

logger = structlog.get_logger(__name__)

# Wide enough that a scanned textbook page is readable on a 1080-wide panel
# without pinch-zoom, which these screens do not offer anyway.
TARGET_WIDTH_PX = 1400
JPEG_QUALITY = 82


def _books_dir() -> Path:
    d = get_settings().books_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def pdf_file(pdf_path: str) -> Path:
    return _books_dir() / pdf_path


def _cache_dir(book_id: uuid.UUID) -> Path:
    return _books_dir() / "pages" / str(book_id)


def _count_pages(path: Path) -> int:
    doc = pypdfium2.PdfDocument(path)
    try:
        return len(doc)
    finally:
        doc.close()


async def store(book_id: uuid.UUID, data: bytes) -> tuple[str, int]:
    """Write the scan and count its pages. Returns (filename, page_count).

    Counting here rather than lazily is deliberate: it is the one moment we can
    reject a file that is not a readable PDF, while the librarian is still
    looking at the upload form and can pick another.
    """
    name = f"{book_id}.pdf"
    target = _books_dir() / name

    def _write() -> int:
        target.write_bytes(data)
        try:
            return _count_pages(target)
        except Exception:
            target.unlink(missing_ok=True)
            raise

    pages = await asyncio.to_thread(_write)
    # A replaced scan must not serve the previous book's pages.
    await asyncio.to_thread(shutil.rmtree, _cache_dir(book_id), True)
    logger.info("book_pdf_stored", book_id=str(book_id), pages=pages, bytes=len(data))
    return name, pages


async def delete(book_id: uuid.UUID, pdf_path: str) -> None:
    def _rm() -> None:
        if pdf_path:
            (_books_dir() / pdf_path).unlink(missing_ok=True)
        shutil.rmtree(_cache_dir(book_id), ignore_errors=True)

    await asyncio.to_thread(_rm)
    logger.info("book_pdf_deleted", book_id=str(book_id))


async def page_jpeg(book_id: uuid.UUID, pdf_path: str, page: int) -> bytes:
    """Page `page` (1-based) as JPEG bytes, rendering it if not already cached."""
    cached = _cache_dir(book_id) / f"{page}.jpg"

    def _render() -> bytes:
        if cached.exists():
            return cached.read_bytes()

        doc = pypdfium2.PdfDocument(_books_dir() / pdf_path)
        try:
            pdf_page = doc[page - 1]
            # pypdfium2's scale is relative to 72 dpi, and these scans differ
            # in page size, so derive it per page rather than fixing a dpi —
            # otherwise the pages of one book come back different widths.
            width_pt = pdf_page.get_width() or 612
            bitmap = pdf_page.render(scale=TARGET_WIDTH_PX / width_pt)
            image = bitmap.to_pil().convert("RGB")
        finally:
            doc.close()

        cached.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the target and move, so a request that arrives mid-render
        # never reads a half-written file.
        tmp = cached.with_suffix(".jpg.part")
        image.save(tmp, "JPEG", quality=JPEG_QUALITY, optimize=True)
        tmp.replace(cached)
        return cached.read_bytes()

    return await asyncio.to_thread(_render)
