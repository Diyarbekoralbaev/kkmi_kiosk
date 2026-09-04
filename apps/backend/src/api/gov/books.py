"""Gov admin: the library catalogue — CRUD.

This is the table the institute owns and maintains by hand, unlike the `hemis_*`
mirror the gov panel can only look at. Everything the kiosk and the AI say about
a book comes from a row somebody typed here.

Deletes are soft. A librarian searching for a typo'd title and hitting the wrong
row should not be able to erase a catalogue record; `deleted_at` hides it from
the kiosk and leaves it recoverable in the database.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, File, Query, Request, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from ...core import audit, bookpages
from ...core.deps import CurrentOrg, DbSession, OrgAdmin
from ...core.errors import NotFoundError, ValidationError
from ...domain.library import BOOK_LANGUAGES, SECTIONS, LibraryBook

router = APIRouter(prefix="/api/gov/books", tags=["gov:books"])


class BookOut(BaseModel):
    id: str
    title: str
    authors: str
    year: int | None
    publisher: str
    isbn: str
    language: str
    section: str
    copies: int
    shelf: str
    description: str
    available: bool
    pages: int


class BookListOut(BaseModel):
    items: list[BookOut]
    total: int


class BookIn(BaseModel):
    title: str = Field(min_length=1, max_length=400)
    authors: str = Field(default="", max_length=400)
    # Gutenberg to a decade out; anything outside is a typo, most often a
    # 2-digit year or a transposed digit.
    year: int | None = Field(default=None, ge=1450, le=2100)
    publisher: str = Field(default="", max_length=200)
    isbn: str = Field(default="", max_length=32)
    language: str = Field(default="uz", max_length=8)
    section: str = Field(default="other", max_length=32)
    copies: int = Field(default=1, ge=0, le=9999)
    shelf: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=4000)
    available: bool = True

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        if v not in BOOK_LANGUAGES:
            raise ValueError(f"language must be one of {BOOK_LANGUAGES}")
        return v

    @field_validator("section")
    @classmethod
    def _section(cls, v: str) -> str:
        if v not in SECTIONS:
            raise ValueError(f"section must be one of {SECTIONS}")
        return v


class BookPatchIn(BookIn):
    title: str | None = Field(default=None, min_length=1, max_length=400)


def _out(b: LibraryBook) -> BookOut:
    return BookOut(
        id=str(b.id),
        title=b.title,
        authors=b.authors,
        year=b.year,
        publisher=b.publisher,
        isbn=b.isbn,
        language=b.language,
        section=b.section,
        copies=b.copies,
        shelf=b.shelf,
        description=b.description,
        available=b.available,
        pages=b.page_count,
    )


async def _get(
    session: DbSession, org_id: uuid.UUID, book_id: uuid.UUID
) -> LibraryBook:
    b = (
        await session.execute(
            select(LibraryBook).where(
                LibraryBook.id == book_id,
                LibraryBook.org_id == org_id,
                LibraryBook.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if b is None:
        raise NotFoundError()
    return b


@router.get("", response_model=BookListOut)
async def list_books(
    session: DbSession,
    _: OrgAdmin,
    org: CurrentOrg,
    q: str | None = Query(default=None),
    section: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> BookListOut:
    where = [LibraryBook.org_id == org.id, LibraryBook.deleted_at.is_(None)]
    if section in SECTIONS:
        where.append(LibraryBook.section == section)
    if q and q.strip():
        # Plain ILIKE here, not the kiosk's fold-and-token search: an admin is
        # typing into a box and watching the list narrow, so predictable
        # substring behaviour beats clever matching.
        like = f"%{q.strip()}%"
        where.append(
            or_(
                LibraryBook.title.ilike(like),
                LibraryBook.authors.ilike(like),
                LibraryBook.isbn.ilike(like),
            )
        )

    total = (
        await session.execute(select(func.count(LibraryBook.id)).where(*where))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(LibraryBook)
                .where(*where)
                .order_by(LibraryBook.title)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return BookListOut(items=[_out(b) for b in rows], total=int(total))


@router.get("/sections")
async def list_sections(_: OrgAdmin) -> dict[str, list[str]]:
    """The fixed section vocabulary, so the panel's dropdown cannot drift out
    of sync with what the kiosk knows how to browse."""
    return {"sections": list(SECTIONS), "languages": list(BOOK_LANGUAGES)}


@router.get("/{book_id}", response_model=BookOut)
async def get_book(
    book_id: uuid.UUID, session: DbSession, _: OrgAdmin, org: CurrentOrg
) -> BookOut:
    return _out(await _get(session, org.id, book_id))


@router.post("", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def create_book(
    payload: BookIn,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
) -> BookOut:
    b = LibraryBook(org_id=org.id, **payload.model_dump())
    session.add(b)
    await session.flush()
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="book.create",
        entity_type="library_book",
        entity_id=b.id,
        after={"title": b.title, "authors": b.authors, "section": b.section},
        request=request,
    )
    return _out(b)


@router.patch("/{book_id}", response_model=BookOut)
async def update_book(
    book_id: uuid.UUID,
    payload: BookPatchIn,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
) -> BookOut:
    b = await _get(session, org.id, book_id)
    before = {"title": b.title, "authors": b.authors, "shelf": b.shelf}
    fields = payload.model_dump(exclude_unset=True)
    if "title" in fields and not (fields["title"] or "").strip():
        raise ValidationError("title_required")
    for key, value in fields.items():
        setattr(b, key, value)
    await session.flush()
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="book.update",
        entity_type="library_book",
        entity_id=b.id,
        before=before,
        after={"title": b.title, "authors": b.authors, "shelf": b.shelf},
        request=request,
    )
    return _out(b)


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(
    book_id: uuid.UUID,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
) -> None:
    b = await _get(session, org.id, book_id)
    b.deleted_at = datetime.now(UTC)
    await session.flush()
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="book.delete",
        entity_type="library_book",
        entity_id=b.id,
        before={"title": b.title},
        request=request,
    )


# A scanned textbook of 100-250 pages runs 10-35 MB. 60 gives room for a
# heavier scan without letting a mis-picked file (a video, a disk image) reach
# the disk.
PDF_MAX_BYTES = 60 * 1024 * 1024


@router.post("/{book_id}/pdf", response_model=BookOut)
async def upload_pdf(
    book_id: uuid.UUID,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
    file: UploadFile = File(...),
) -> BookOut:
    """Attach (or replace) the scanned book a visitor reads at the kiosk.

    The upload is validated by its bytes, not by the Content-Type the browser
    claims, and then by actually opening it — a file that pdfium cannot page
    through is rejected here, while the librarian is still looking at the form,
    rather than becoming a reader that fails at the kiosk.
    """
    b = await _get(session, org.id, book_id)

    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(256 * 1024):
        chunks.append(chunk)
        total += len(chunk)
        if total > PDF_MAX_BYTES:
            raise ValidationError("pdf_too_large")
    data = b"".join(chunks)
    if not data:
        raise ValidationError("pdf_empty")
    if not data.startswith(b"%PDF-"):
        raise ValidationError("pdf_invalid_format")

    try:
        name, pages = await bookpages.store(b.id, data)
    except Exception as e:
        raise ValidationError("pdf_unreadable") from e

    b.pdf_path = name
    b.page_count = pages
    await session.flush()
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="book.pdf.upload",
        entity_type="library_book",
        entity_id=b.id,
        after={"pages": pages, "size": total},
        request=request,
    )
    return _out(b)


@router.delete("/{book_id}/pdf", response_model=BookOut)
async def delete_pdf(
    book_id: uuid.UUID,
    session: DbSession,
    actor: OrgAdmin,
    org: CurrentOrg,
    request: Request,
) -> BookOut:
    """Detach the scan. The catalogue card stays; only the reader goes away."""
    b = await _get(session, org.id, book_id)
    await bookpages.delete(b.id, b.pdf_path)
    b.pdf_path = ""
    b.page_count = 0
    await session.flush()
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=org.id,
        action="book.pdf.delete",
        entity_type="library_book",
        entity_id=b.id,
        request=request,
    )
    return _out(b)
