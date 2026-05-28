"""SQLAlchemy ORM models. Importing this module registers all tables on `Base.metadata`."""
from __future__ import annotations

from .ai_config import (  # noqa: F401
    OrgKbOfficial,
    SystemAiDefaults,
)
from .application import Application  # noqa: F401
from .appointment import Appointment  # noqa: F401
from .category import ApplicationCategory  # noqa: F401
from .audit import AuditLog  # noqa: F401
from .device import AuthChallenge, Device, DeviceEnrollmentCode, DeviceKey  # noqa: F401
from .organization import Organization, OrgCredentials  # noqa: F401
from .release import KioskRelease  # noqa: F401
from .session import VoiceSession  # noqa: F401
from .user import RefreshToken, User  # noqa: F401
