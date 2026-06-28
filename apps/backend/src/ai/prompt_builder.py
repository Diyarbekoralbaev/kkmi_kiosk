"""Build the final system prompt string for a kiosk's WS session, from DB.

Source of truth is the singleton `system_ai_defaults` row (super-admin owned).
The prompt sections are read straight out of `default_sections` JSONB and
concatenated in `order`. A per-org `OrgKbOfficial` block (hokim/orinbasarlar
list) is appended at the end so the agent has the up-to-date officials KB
for the current org.

Two dynamic blocks are prepended/appended at runtime (NOT stored in
default_sections, since they change per session/org):

  - "ҲӘЗИРГИ ЎАҚЫТ" at the top: today's date + Karakalpak Cyrillic
    weekday, so the agent computes "ертең / индин" against real time
    instead of guessing. ("сана" is a Kazakh/Latin borrowing and not
    used in Karakalpak — "ўақыт" is the operator-approved term.)
  - "КЕҢЕС БАЙЛАНЫС" before the officials block: the current org's
    helpline phone, email, address (per-locale → kk picked) so the
    agent stops hallucinating phone numbers like the cross-government
    1242 hotline.

No per-org overrides. No filtering by `gov_editable`. No screen-by-screen
section masking. The static prompt the agent sees is identical for every
org — only the dynamic blocks + trailing officials block vary.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import murajat
from ..core.seed import ensure_system_ai_defaults
from ..domain.organization import (
    Organization,
    address_translations_for_response,
    work_hours_translations_for_response,
)

logger = structlog.get_logger(__name__)


@dataclass
class AgentConfig:
    system_prompt: str
    model: str
    voice: str
    temperature: float
    top_p: float
    top_k: int
    max_output_tokens: int
    response_modalities: str
    enabled_tools: list[str]


# weekday() returns 0=Mon..6=Sun, matched to the Karakalpak Cyrillic names
# so the runtime date block reads identical to anything the static prompt
# already mentions.
_WEEKDAY_INDEX_TO_KK = [
    "дүйшемби",
    "сейшемби",
    "сәршемби",
    "пийшемби",
    "жума",
    "шемби",
    "жексенби",
]


def _format_today_block(now: datetime | None = None) -> str:
    """Today's date + weekday in Karakalpak Cyrillic. Computed once per
    WS session — the agent uses it to resolve "ертең", "индин", "келеси
    жума" against real time instead of guessing. Without this, Gemini
    has no calendar; it would routinely place qabul on "пийшемби" when
    the kiosk operator's clock says жума.

    Header is "ҲӘЗИРГИ ЎАҚЫТ" (current time) — the operator-approved
    Karakalpak term. "сана" is a Kazakh/Latin borrowing not used in
    natural Karakalpak speech, per native-speaker correction."""
    now = now or datetime.now(UTC)
    iso = now.date().isoformat()
    weekday = _WEEKDAY_INDEX_TO_KK[now.weekday()]
    return (
        "===== ҲӘЗИРГИ ЎАҚЫТ =====\n"
        f"Бүгинги күн: {iso} ({weekday})."
    )


def _pick_kk(d: dict[str, str]) -> str:
    """Karakalpak Cyrillic is the agent's working script; pick the kk
    translation if present, else any non-empty locale, else empty."""
    v = d.get("kk")
    if isinstance(v, str) and v.strip():
        return v
    for k in ("ru", "uz"):
        alt = d.get(k)
        if isinstance(alt, str) and alt.strip():
            return alt
    return ""


def _format_org_contact_block(org: Organization) -> str:
    """Inject the current org's helpline + email + address into the
    prompt so the agent stops hallucinating phone numbers (the most
    egregious one being 1242, which is the cross-government Uzbekistan
    contact-centre and NOT a hokimiyat line). Empty fields render as
    "—" rather than being omitted, so the agent never sees a half-empty
    section and tries to fill it in itself."""
    address = _pick_kk(address_translations_for_response(org)) or "—"
    hours = _pick_kk(work_hours_translations_for_response(org)) or "—"
    phone = (org.helpline_phone or "").strip() or "—"
    email = (org.email or "").strip() or "—"
    return (
        "===== КЕҢЕС БАЙЛАНЫС =====\n"
        f"Жәрдем телефоны: {phone}\n"
        f"Email: {email}\n"
        f"Мәнзил: {address}\n"
        f"Жумыс ўақты: {hours}\n"
        "Тек усы реквизитлерди айтың. 1242 (улыўма мәмлекетлик "
        "хызметлер орайы) Кеңес номери ЕМЕС — Кеңес байланысы "
        "сапатында айтпаң. Кеңес телефонын сорағанда жоқарыдағы "
        "«Жәрдем телефоны»ды ғана айтың; ол бос болса «бизде жария "
        "етилген жәрдем телефоны жоқ, орынлы келиң» деп жуўап бер."
    )


def _format_districts_block(districts: list[dict]) -> str:
    """The 17 districts (id + name) so the agent maps a spoken tuman to its
    district_id during a new-citizen murajat. Quarters are fetched per-district
    at runtime via the get_quarters tool — 454 of them won't fit the prompt."""
    lines = [
        "===== ТУМАНЛАР (district_id) =====",
        "Жаңа пуқараның мүрәжатын толтырғанда, оның жасайтуғын туманын усы "
        "дизимнен таңла ҳәм id'син district_id ретинде қолла (қарақалпақша, "
        "өзбекше яки русша айтса да ең жақынын таңла):",
    ]
    for d in districts:
        did = d.get("id")
        name = (d.get("name_qq") or d.get("name_uz") or "").strip()
        uz = (d.get("name_uz") or "").strip()
        suffix = f" / {uz}" if uz and uz != name else ""
        lines.append(f"  {did} — {name}{suffix}")
    lines.append(
        "Туман белгили болғаннан кейин get_quarters(district_id) шақыр — ол сол "
        "туманның мәкан (МПЖ/АПЖ) дизимин қайтарады; пуқара айтқан мәканды таңлап "
        "quarter_id ди ал."
    )
    return "\n".join(lines)


async def load_agent_config(session: AsyncSession, org_id: uuid.UUID) -> AgentConfig:
    defaults = await ensure_system_ai_defaults(session)

    sections = list(defaults.default_sections or [])
    sections.sort(key=lambda s: int(s.get("order", 0)))

    # Today block at the very top — so the agent reads "real time" before
    # any guidance section. Without this it's the FIRST thing Gemini
    # forgets when picking қабыл dates.
    pieces: list[str] = [_format_today_block()]

    for sec in sections:
        content = str(sec.get("content", "")).strip()
        if content:
            pieces.append(content)

    # Org contact block — placed after the static sections but BEFORE the
    # officials block so the agent reads "use these contacts" right
    # before seeing the names it might want to forward visitors to.
    org = (
        await session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is not None:
        pieces.append(_format_org_contact_block(org))

    # Districts reference — only the murajat new-citizen flow needs it. Fetched
    # (and cached) from the external cabinet; if it's unreachable or unconfigured
    # we build the prompt without it rather than failing the whole session.
    try:
        districts = (await murajat.get_locations()).get("districts") or []
        if districts:
            pieces.append(_format_districts_block(districts))
    except Exception as e:
        logger.warning("districts_block_skipped", error=str(e), error_type=type(e).__name__)

    system_prompt = "\n\n".join(pieces)
    enabled_tools = [
        str(t.get("tool_key", ""))
        for t in (defaults.default_tools or [])
        if t.get("enabled") and t.get("tool_key")
    ]

    return AgentConfig(
        system_prompt=system_prompt,
        model=defaults.model,
        voice=defaults.voice,
        temperature=defaults.temperature,
        top_p=defaults.top_p,
        top_k=defaults.top_k,
        max_output_tokens=defaults.max_output_tokens,
        response_modalities=defaults.response_modalities,
        enabled_tools=enabled_tools,
    )
