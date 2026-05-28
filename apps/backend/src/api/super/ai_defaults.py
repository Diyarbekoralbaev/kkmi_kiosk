"""Super admin: edit the GLOBAL AI prompt + tuning.

`system_ai_defaults` is the single source of truth read by prompt_builder at
every WS connect. Super edits here propagate to every kiosk's NEXT session.
There are no per-org AI endpoints — orgs share the same prompt.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ...core import audit
from ...core.deps import DbSession, SuperAdmin
from ...core.errors import NotFoundError, ValidationError
from ...core.seed import ensure_system_ai_defaults
from ...domain.ai_config import SECTION_KEYS

router = APIRouter(prefix="/api/super", tags=["super:ai"])


class AiSettingsBase(BaseModel):
    model: str
    voice: str
    temperature: float = Field(ge=0.0, le=2.0)
    top_p: float = Field(ge=0.0, le=1.0)
    top_k: int = Field(ge=1, le=200)
    max_output_tokens: int = Field(ge=64, le=131072)
    response_modalities: str = Field(min_length=1, max_length=32)


class SystemDefaultsOut(AiSettingsBase):
    default_sections: list[dict[str, Any]]
    default_tools: list[dict[str, Any]]
    default_officials: list[dict[str, Any]]


class SystemDefaultsUpdate(BaseModel):
    model: str | None = None
    voice: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_output_tokens: int | None = None
    response_modalities: str | None = None
    default_sections: list[dict[str, Any]] | None = None
    default_tools: list[dict[str, Any]] | None = None
    default_officials: list[dict[str, Any]] | None = None


def _to_out(row: Any) -> SystemDefaultsOut:
    return SystemDefaultsOut(
        model=row.model,
        voice=row.voice,
        temperature=row.temperature,
        top_p=row.top_p,
        top_k=row.top_k,
        max_output_tokens=row.max_output_tokens,
        response_modalities=row.response_modalities,
        default_sections=row.default_sections,
        default_tools=row.default_tools,
        default_officials=row.default_officials,
    )


@router.get("/ai-defaults", response_model=SystemDefaultsOut)
async def get_defaults(session: DbSession, _: SuperAdmin) -> SystemDefaultsOut:
    row = await ensure_system_ai_defaults(session)
    return _to_out(row)


@router.patch("/ai-defaults", response_model=SystemDefaultsOut)
async def update_defaults(
    payload: SystemDefaultsUpdate,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> SystemDefaultsOut:
    row = await ensure_system_ai_defaults(session)
    before = {
        "model": row.model,
        "voice": row.voice,
        "temperature": row.temperature,
    }
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="ai_defaults.update",
        entity_type="system_ai_defaults",
        entity_id=str(row.id),
        before=before,
        request=request,
    )
    return _to_out(row)


class SectionContentIn(BaseModel):
    content: str = Field(max_length=20_000)


@router.patch("/ai-defaults/sections/{section_key}", response_model=SystemDefaultsOut)
async def update_section(
    section_key: str,
    payload: SectionContentIn,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> SystemDefaultsOut:
    """Update a single section's content in `default_sections` JSONB.

    Avoids round-tripping the full array from the super panel. Validates
    the section_key against the canonical set; missing keys are rejected
    (no auto-insert) so we don't accumulate stale entries.
    """
    if section_key not in SECTION_KEYS:
        raise ValidationError("unknown_section_key")
    row = await ensure_system_ai_defaults(session)
    sections: list[dict[str, Any]] = list(row.default_sections or [])
    found = False
    for sec in sections:
        if sec.get("section_key") == section_key:
            sec["content"] = payload.content
            found = True
            break
    if not found:
        raise NotFoundError("section_not_found")
    # JSONB column needs a fresh list to trigger SQLAlchemy's change tracking.
    row.default_sections = sections
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="ai_defaults.section_update",
        entity_type="system_ai_defaults",
        entity_id=str(row.id),
        after={"section_key": section_key, "content_len": len(payload.content)},
        request=request,
    )
    return _to_out(row)
