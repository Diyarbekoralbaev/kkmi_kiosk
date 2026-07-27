"""Local mirror of the institute's HEMIS data.

HEMIS (hemis.uz) is the national higher-education management system; KKMI's
instance lives at student.kkmi.uz. The kiosk needs class schedules, groups and
specialties, but a kiosk cannot afford a 0.5–3 s upstream round-trip in the
middle of a spoken answer, and it must keep working when HEMIS is down. So a
nightly job mirrors the data here and every read path hits Postgres.

Scope: these tables are GLOBAL, not per-org — same precedent as
`system_ai_defaults`. HEMIS credentials are a single pair of env vars
(`HEMIS_API_BASE` / `HEMIS_TOKEN`), so one deployment mirrors exactly one
institute. If a second institute is ever onboarded, per-org HEMIS config gets
added at that point, the same way the AI config went global in 0012.

No foreign keys between the mirrored tables. Upstream is paginated and
eventually-consistent: `schedule-list` routinely references a group or employee
that a later page of `group-list` would introduce, and rows disappear upstream
without warning. Real FKs would turn each of those into a failed sync instead
of a slightly stale row, so the id columns are plain indexed integers and the
read paths LEFT JOIN.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin


class HemisDepartment(Base, TimestampMixin):
    """Any HEMIS org unit: faculty, kafedra, or rectorate office.

    HEMIS models all of them in one `department-list` (60 rows for KKMI);
    faculties are the ones with `structure_type_code == "11"` — that is the
    filter the kiosk's faculty→course→group drill-down uses.
    """

    __tablename__ = "hemis_departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    structure_type_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    structure_type_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class HemisSpecialty(Base, TimestampMixin):
    """Degree programme ("Davolash ishi", "Pediatriya ishi", ...). Drives the
    AI Abituriyent menu — it is the one part of that menu HEMIS can answer on
    its own (quotas and pass marks are not in HEMIS)."""

    __tablename__ = "hemis_specialties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    education_type_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    education_type_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class HemisGroup(Base, TimestampMixin):
    """Student group. `name` is free-text and messy upstream ("120 A lesh ENG",
    "Joqarı miyirbiykelik isi-233", "PEDIATRIYA-209 RUS QOSPA"), which is why
    the voice path fuzzy-matches against it instead of expecting an exact
    utterance."""

    __tablename__ = "hemis_groups"
    __table_args__ = (
        Index("ix_hemis_groups_department_active", "department_id", "active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    specialty_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    specialty_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    education_lang_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    education_lang_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    """"O'zbek" | "Qoraqalpoq" | "Rus" | "Ingliz" — the institute teaches in all four."""
    curriculum_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class HemisSubject(Base, TimestampMixin):
    __tablename__ = "hemis_subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class HemisEmployee(Base, TimestampMixin):
    """Teacher. Upstream only gives an initialled surname here
    ("MELDEBEKOVA S. U."), which is what the kiosk shows."""

    __tablename__ = "hemis_employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class HemisAuditorium(Base, TimestampMixin):
    """Room. Keyed by HEMIS's `code`, not `id` — `schedule-list` references
    rooms by code."""

    __tablename__ = "hemis_auditoriums"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    building: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    kind: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    """auditoriumType.name upstream — "Seminar", "Amaliy", ..."""
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)


class HemisLessonPair(Base, TimestampMixin):
    """Bell-schedule slot ("(08:30-09:50)"). 17 of them at KKMI."""

    __tablename__ = "hemis_lesson_pairs"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    start_time: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    end_time: Mapped[str] = mapped_column(String(8), default="", nullable=False)


class HemisTrainingType(Base, TimestampMixin):
    """Ma'ruza / Amaliy / Laboratoriya / Seminar."""

    __tablename__ = "hemis_training_types"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class HemisSemester(Base, TimestampMixin):
    __tablename__ = "hemis_semesters"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class HemisLesson(Base, TimestampMixin):
    """One scheduled class. ~114k rows for the current academic year.

    `lesson_date` is a DATE in Tashkent time, converted from the upstream Unix
    timestamp at sync. Storing the local date (not the timestamp) is what makes
    "what do I have today" a plain equality lookup — the kiosk's single hottest
    query.
    """

    __tablename__ = "hemis_lessons"
    __table_args__ = (
        # The kiosk's main query: one group, one day (or a date range for the
        # week view). Composite so both the equality and the range are served.
        Index("ix_hemis_lessons_group_date", "group_id", "lesson_date"),
        # "what is running in the institute right now" + the sync's date sweep.
        Index("ix_hemis_lessons_date", "lesson_date"),
        Index("ix_hemis_lessons_employee_date", "employee_id", "lesson_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    lesson_date: Mapped[date] = mapped_column(Date, nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    """ISO weekday, 1 = Monday .. 7 = Sunday."""
    pair_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    start_time: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    end_time: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auditorium_code: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    faculty_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    training_type_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    semester_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    week_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hemis_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """Upstream's own updated_at. Named apart from TimestampMixin.updated_at,
    which tracks when WE last wrote the row."""


class HemisSyncState(Base, TimestampMixin):
    """One row per mirrored resource — the incremental-sync watermark plus the
    last run's outcome, which is what the gov-panel's HEMIS page renders."""

    __tablename__ = "hemis_sync_state"

    resource: Mapped[str] = mapped_column(String(64), primary_key=True)
    """"schedule", "groups", "departments", ..."""
    last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """Highest upstream updated_at seen. Sent as `updated_at_from` next run."""
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    """pending | running | ok | error"""
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
