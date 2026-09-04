"""The institute's book catalogue — entered by staff, not mirrored.

This is the one dataset on the kiosk that has no upstream. `irbis.kkmi.uz`,
the library's own IRBIS system, does not resolve from outside the institute
network and no export has been supplied, so the AI Kutubxona menu had nothing
to answer from and shipped as a "coming soon" screen.

So the catalogue lives here, owned by us: librarians type books into the gov
panel and the kiosk reads them straight back. That makes it the opposite of
`hemis_*` — a source of truth, written by request handlers, backed up like any
other table. If an IRBIS export ever arrives it can be imported INTO this
table; the kiosk side would not change.

Deliberately not modelled: loans, borrowers, due dates. The kiosk identifies
nobody (see the privacy stance in CLAUDE.md), so it cannot check a book out to
anyone. It answers "do you have it, what is it, where is it on the shelf" and
stops there.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin

# Shelf sections, kept as a fixed list so the kiosk can offer them as browse
# categories and the agent can filter on them without free-text matching.
# `other` is the escape hatch; everything else maps to how a medical library is
# actually arranged.
SECTIONS: tuple[str, ...] = (
    "anatomy",
    "physiology",
    "biochemistry",
    "pharmacology",
    "pathology",
    "microbiology",
    "internal_medicine",
    "surgery",
    "pediatrics",
    "obstetrics",
    "psychiatry",
    "dentistry",
    "nursing",
    "public_health",
    "reference",
    "other",
)

SECTION_LABELS: dict[str, dict[str, str]] = {
    "anatomy": {
        "kk": "Anatomiya", "uz": "Anatomiya",
        "ru": "Анатомия", "en": "Anatomy",
    },
    "physiology": {
        "kk": "Fiziologiya", "uz": "Fiziologiya",
        "ru": "Физиология", "en": "Physiology",
    },
    "biochemistry": {
        "kk": "Bioximiya", "uz": "Biokimyo",
        "ru": "Биохимия", "en": "Biochemistry",
    },
    "pharmacology": {
        "kk": "Farmakologiya", "uz": "Farmakologiya",
        "ru": "Фармакология", "en": "Pharmacology",
    },
    "pathology": {
        "kk": "Patologiya", "uz": "Patologiya",
        "ru": "Патология", "en": "Pathology",
    },
    "microbiology": {
        "kk": "Mikrobiologiya", "uz": "Mikrobiologiya",
        "ru": "Микробиология", "en": "Microbiology",
    },
    "internal_medicine": {
        "kk": "Ishki keselikler", "uz": "Ichki kasalliklar",
        "ru": "Внутренние болезни", "en": "Internal medicine",
    },
    "surgery": {
        "kk": "Xirurgiya", "uz": "Xirurgiya",
        "ru": "Хирургия", "en": "Surgery",
    },
    "pediatrics": {
        "kk": "Pediatriya", "uz": "Pediatriya",
        "ru": "Педиатрия", "en": "Pediatrics",
    },
    "obstetrics": {
        "kk": "Akusherlik hám ginekologiya", "uz": "Akusherlik va ginekologiya",
        "ru": "Акушерство и гинекология", "en": "Obstetrics and gynaecology",
    },
    "psychiatry": {
        "kk": "Psixiatriya", "uz": "Psixiatriya",
        "ru": "Психиатрия", "en": "Psychiatry",
    },
    "dentistry": {
        "kk": "Stomatologiya", "uz": "Stomatologiya",
        "ru": "Стоматология", "en": "Dentistry",
    },
    "nursing": {
        "kk": "Miyirbiykelik isi", "uz": "Hamshiralik ishi",
        "ru": "Сестринское дело", "en": "Nursing",
    },
    "public_health": {
        "kk": "Jámiyetlik densawlıq", "uz": "Jamoat salomatligi",
        "ru": "Общественное здоровье", "en": "Public health",
    },
    "reference": {
        "kk": "Anıqlamalıqlar", "uz": "Ma'lumotnomalar",
        "ru": "Справочники", "en": "Reference",
    },
    "other": {
        "kk": "Basqa", "uz": "Boshqa",
        "ru": "Прочее", "en": "Other",
    },
}

# Language of the BOOK, which is not the kiosk's language set — the library
# holds Latin-script Uzbek/Karakalpak, Cyrillic Russian and English titles.
BOOK_LANGUAGES: tuple[str, ...] = ("kk", "uz", "ru", "en")


class LibraryBook(Base, TimestampMixin):
    __tablename__ = "library_books"
    __table_args__ = (
        Index("ix_library_books_org_section", "org_id", "section"),
        # Drives both the kiosk's browse list and the agent's search: title
        # order within a section is what a person expects to scan.
        Index("ix_library_books_org_title", "org_id", "title"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(400), nullable=False)
    authors: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    """Free text, as printed on the cover — "M.R. Sapin, D.B. Nikityuk". Not a
    relation: the kiosk never needs to list an author's other works, and a
    librarian typing a book should not have to create an author record first."""

    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publisher: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    isbn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    """Not unique: the same ISBN legitimately appears twice when the library
    holds two accessions of one edition on different shelves."""

    language: Mapped[str] = mapped_column(String(8), nullable=False, default="uz")
    section: Mapped[str] = mapped_column(String(32), nullable=False, default="other")

    copies: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    shelf: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    """Where to physically walk — "A-3", "2-qavat, 14-javon". The single most
    useful field on the card and the reason the catalogue is here at all."""

    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """A sentence or two on what the book covers, for the agent to paraphrase.
    Not a blurb to read aloud verbatim."""

    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """Cleared when a title is withdrawn or lost, instead of deleting the row —
    a librarian who mistypes a search should not be able to erase a record."""

    pdf_path: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    """Filename of the scanned book under `settings.books_dir`, or "" when the
    library has not supplied one. The file itself never leaves the server: the
    kiosk asks for one rendered page at a time, because the machines in the
    lobby are from 2011 and putting a PDF engine on them is the same class of
    thing that already froze them once."""

    page_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    """Pages in that PDF, counted once at upload. Zero means there is nothing
    to read — it is the flag the kiosk uses to decide whether to offer the
    reader at all, so it must stay in step with `pdf_path`."""

    cover: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    """The jacket image, stored as bytes rather than a URL.

    A URL would make the kiosk depend on openlibrary.org being reachable at the
    moment a visitor taps a book — from a lobby in Nókis, on the institute's
    connection. Covers are 20-60 KB and a catalogue is hundreds of books, so
    the whole set is a few megabytes: cheaper to hold than to re-fetch, and it
    keeps working when the upstream does not."""
    cover_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """Set on every attempt, hit or miss. A miss is worth remembering — most
    ISBNs simply have no cover upstream, and without this the fetcher would
    retry the same hopeless lookups on every run."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


def section_label(section: str, locale: str = "kk") -> str:
    labels = SECTION_LABELS.get(section) or SECTION_LABELS["other"]
    return labels.get(locale) or labels["kk"]
