"""Shared SQLAlchemy column helpers."""
from __future__ import annotations

import uuid
from typing import Annotated

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column

UuidPk = Annotated[
    uuid.UUID,
    mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
]


def short_str(length: int = 255):
    return mapped_column(String(length))
