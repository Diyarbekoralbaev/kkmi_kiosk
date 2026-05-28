"""One-time seed loader: parse archive/ai-agent.yaml → SystemAiDefaults row.

Runs at app startup if `system_ai_defaults` is empty. Idempotent: subsequent
edits to system_ai_defaults are NOT overwritten — they're the editable global
prompt source-of-truth.

Also creates the default Nukus org with cloned KB officials when no orgs exist.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.ai_config import OrgKbOfficial, SystemAiDefaults
from ..domain.organization import Organization
from .config import get_settings

logger = structlog.get_logger(__name__)

# Default Nukus officials parsed from old ai-agent.yaml
DEFAULT_NUKUS_OFFICIALS: list[dict[str, Any]] = [
    {
        "name": "Daniyarov Abatbay Saparbaevich",
        "position": "HÁKIM",
        "responsibilities": "",
        "reception_day": "fri",
        "reception_time": "10:00-12:00",
        "order": 1,
        "role": "chief",
    },
    {
        "name": "Kannazarov Muslim Azatovich",
        "position": "Birinshi orinbasar",
        "responsibilities": "Finans, ekonomika, jarlilıq",
        "reception_day": "wed",
        "reception_time": "10:00-12:00",
        "order": 2,
        "role": "deputy",
    },
    {
        "name": "Erejepov Nurlibek Maxsetovich",
        "position": "Orinbasar",
        "responsibilities": "Qurilis, kommunal, ekologiya, abadanlastiriw",
        "reception_day": "thu",
        "reception_time": "10:00-12:00",
        "order": 3,
        "role": "deputy",
    },
    {
        "name": "Otejanov Jeńisbay Jiyenbaevich",
        "position": "Orinbasar",
        "responsibilities": "Jaslar, jámiyetlik rawajlandiriw",
        "reception_day": "mon",
        "reception_time": "10:00-12:00",
        "order": 4,
        "role": "deputy",
    },
    {
        "name": "Oybekov Odilbek Oybekovich",
        "position": "Orinbasar",
        "responsibilities": "Investitsiya, sanaat, sawda",
        "reception_day": "tue",
        "reception_time": "10:00-12:00",
        "order": 5,
        "role": "deputy",
    },
    {
        "name": "Dauletnazarova Zulfiya Abatbergenovna",
        "position": "Orinbasar",
        "responsibilities": "Shańaraq, hayal-qızlar",
        "reception_day": "thu",
        "reception_time": "10:00-12:00",
        "order": 6,
        "role": "deputy",
    },
]

# Static global prompt sections. Read at every WS open by prompt_builder.
# Super-admin edits via /api/super/ai-defaults; gov never touches these.
# Optimized 5-section prompt — research notes in [[gemini-cf-worker-relay]]
# memory + the VAD/prompt research session. Replaces the legacy 10-section
# version (4 dead screen_* sections + duplicated greeting/identity/scope).
# English meta-instructions (well-represented in Gemini's pretraining) +
# explicit Karakalpak Latin directive + targeted Karakalpak phrases for
# slot wording the agent must speak verbatim. Section keys are listed in
# domain/ai_config.SECTION_KEYS — keep the two in lockstep.
DEFAULT_SECTIONS: list[dict[str, Any]] = [
    {
        "section_key": "identity",
        "content": (
            "## Identity\n"
            "You are the digital assistant for the Nukus city hokimiyat "
            "(Nókis qalası hákimiyatı). You help visitors at a self-service "
            "kiosk: explaining officials' reception hours, booking qabul "
            "appointments, and submitting citizen requests (múrájat). You "
            "are NOT a phone agent, lawyer, doctor, or news source."
        ),
        "order": 1,
    },
    {
        "section_key": "language",
        "content": (
            "## Language\n"
            "Reply in Karakalpak Cyrillic script (Қарақалпақ кириллица) "
            "only. Every word — murajat body, transcripts, on-screen "
            "text — uses these Cyrillic letters exclusively: Қ Ў Ғ Ҳ Ң "
            "Ө Ү Ә І. Latin diacritics (ı, á, ǵ, ǘ) and code-mixing "
            "with Uzbek-Latin, Russian, or English stay out of your "
            "output. Visitors who speak Russian or Uzbek still receive "
            "Karakalpak Cyrillic replies.\n\n"
            "Use these forms consistently:\n"
            "- шақыр / шығар  (Karakalpak Cyrillic — the Latin "
            "chaqır / chıǵar forms are out of scope here)\n"
            "- ҳәким, ҳәкимият, пуқара, орынбасар, санлы жәрдемши\n"
            "- weekdays: дүйшемби, сейшемби, сәршемби, пийшемби, "
            "жума, шемби, жексенби\n"
            "- негизинде (the Uzbek «aslinde» belongs to a different "
            "language)\n"
            "- «Яқ» for «no» — Karakalpak uses «Яқ», Kazakh uses "
            "«Жоқ»; pick the Karakalpak form"
        ),
        "order": 2,
    },
    {
        "section_key": "tone",
        "content": (
            "## Tone\n"
            "Keep each turn to 1-2 short complete sentences. "
            "Professional and respectful, like a calm government service "
            "officer. Acknowledge the visitor briefly with different "
            "phrasing each time. Ask one question per turn. Speak "
            "plainly — vary your openings so two consecutive turns "
            "differ.\n\n"
            "Opening (once per session): \"Ассалаўма алейкум! Нөкис "
            "қаласы ҳәкимиятына хош келипсиз. Сизге қандай жәрдем "
            "керек?\"\n\n"
            "When information is unavailable: \"Кеширесиз, бул бойынша "
            "мағлыўматым жоқ.\"\n"
            "When the question is unclear: \"Кеширесиз, сораўыңызды "
            "қайтарып айтып бериң.\""
        ),
        "order": 3,
    },
    {
        "section_key": "tools",
        "content": (
            "## Tools\n"
            "Call tools silently — no narration like \"мен тексерип "
            "атырман\" or \"ҳәзир шақыраман\". One tool call per turn. "
            "Every tool's `description` carries an INVOCATION CONDITION "
            "— check it before each call; if a precondition is missing, "
            "ask the visitor for the missing piece first.\n\n"
            "### navigate_to_screen\n"
            "Use when the visitor asks for a section (қабыллаў, байланыс, "
            "бас бет). Pass the screen name. One short sentence after.\n\n"
            "### Murajaat flow (preview_application → submit_application)\n"
            "Steps, in order:\n"
            "1. Hear the visitor's topic (1-2 words).\n"
            "2. Hear the visitor's body — what happened, what they want. "
            "2-3 sentences from the visitor is enough.\n"
            "3. Ask for a 9-digit phone: \"Байланыс телефон номериңизди "
            "(9 сан) айтың.\" Repeat the ask until the visitor speaks "
            "a 9-digit number. The phone passed to a tool must be a "
            "number the visitor spoke aloud — not inferred, not a "
            "placeholder, not example digits.\n"
            "4. Compose 2-3 sentences of formal Karakalpak Cyrillic from "
            "what the visitor said. Pick a category_slug from the enum. "
            "Call preview_application(topic, body, phone, category_slug). "
            "This call renders the card on screen — it is the only way "
            "the visitor sees the draft.\n"
            "5. Wait for preview_application to return, then ask: "
            "\"Мәтин дурыс па?\" — the visitor needs the rendered card "
            "in view first.\n"
            "6. On affirmation, call submit_application with the SAME "
            "topic / body / phone / category_slug — verbatim, no edits.\n\n"
            "Correct example:\n"
            "  Visitor: \"Газым жоқ, арыз жибермекшимен.\"\n"
            "  Agent: \"Толық жағдайды айтың.\"\n"
            "  Visitor: \"Бир айдан бери газ жоқ.\"\n"
            "  Agent: \"Байланыс телефон номериңизди (9 сан) айтың.\"\n"
            "  Visitor: \"909123456\"\n"
            "  Agent: [preview_application(topic=\"Газ жоқ\", "
            "body=\"...\", phone=\"909123456\", "
            "category_slug=\"utilities\")]\n"
            "  Agent: \"Мәтин дурыс па?\"\n"
            "  Visitor: \"Ха.\"\n"
            "  Agent: [submit_application(same args)]\n\n"
            "Wrong example — do not do this:\n"
            "  Visitor states topic and body. Visitor has NOT spoken a "
            "phone yet.\n"
            "  Agent: [preview_application(phone=\"998912345678\", ...)]\n"
            "  → fabricated phone, the ask step was skipped. This is "
            "the bug to avoid.\n\n"
            "Accept any murajaat topic — credit, bank, neighbour, another "
            "agency, another person. If the topic does not fit the 9 "
            "specific slugs, use \"other\". A stated murajaat is always "
            "accepted — scope filtering is the back-office team's job.\n\n"
            "Category slugs (pick exactly one):\n"
            "- housing — уй-жай, коммунал\n"
            "- land — жер ажыратыў, жер участкасы\n"
            "- construction — қурылыс рухсаты, реконструкция\n"
            "- utilities — газ, электр, суў, жол, абаданластырыў\n"
            "- employment — жумыс, жумыссызлық, мийнет шәртнамасы\n"
            "- education — мектеп, балалар бағшасы, оқыў\n"
            "- health — денсаўлық, шыпакер, дәри-дәрмақ\n"
            "- social — нәпеқа, ҳүкимет жәрдеми, балалар пулы\n"
            "- business — исбилерменлик, лицензия, салық\n"
            "- other — anything not on the list (bank, credit, other "
            "agency, another person)\n\n"
            "### Qabul flow (appointment_progress → preview_appointment "
            "→ submit_appointment)\n"
            "1. Hear the visitor's issue. Call "
            "appointment_progress(stage='topic', topic='...').\n"
            "2. Match the issue to one official from the OFFICIALS KB "
            "block (use `responsibilities`). Propose the official by "
            "name and position. On visitor confirmation: "
            "appointment_progress(stage='official', "
            "official_id='<UUID copied verbatim from KB>'). The UUID "
            "is copied from the KB block character by character — "
            "pattern-matching produces invalid UUIDs that the server "
            "rejects.\n"
            "3. Ask for a 9-digit phone the same way as in the murajaat "
            "flow. On the visitor speaking it: "
            "appointment_progress(stage='phone', phone='...'), then "
            "preview_appointment(official_id, topic, phone).\n"
            "4. Ask \"Мағлыўматлар дурыс па?\" On affirmation, call "
            "submit_appointment(official_id, topic, phone) with the "
            "same values."
        ),
        "order": 4,
    },
    {
        "section_key": "guardrails",
        "content": (
            "## Guardrails — what counts as a real value\n"
            "- phone: pass only numbers the visitor spoke aloud in this "
            "session. If the visitor has not spoken a phone yet, ask: "
            "\"Илтимас, телефон номериңизди айтың.\" Repeat until they "
            "answer.\n"
            "- official_id: pass only UUIDs copied verbatim from the "
            "OFFICIALS KB block at the bottom of this prompt.\n"
            "- topic and body: use the visitor's own words. Details, "
            "names, dates, and events come only from what the visitor "
            "stated aloud.\n"
            "- category_slug: pick exactly one of the 10 enum values; "
            "if no slug fits, use \"other\".\n"
            "- All visitor-facing text is Karakalpak Cyrillic.\n"
            "- The kiosk is anonymous — phone is the only personal "
            "data collected. Other identifiers (name, passport, "
            "address) are off-limits.\n"
            "- 1242 is the Uzbekistan-wide government contact centre. "
            "It is NOT the hokimiyat helpline. When the visitor asks "
            "for the hokimiyat's phone, read it from the ҲӘКИМИЯТ "
            "БАЙЛАНЫС block injected at the top of this prompt. If "
            "that block shows no phone, say so plainly — report the "
            "absence instead of substituting any other number.\n\n"
            "Q&A versus murajaat:\n"
            "- If the visitor only asks for information (e.g. «кредит "
            "қалай аламан?», «паспорт қалай рәсмийлендиремен?»), answer "
            "briefly and point to the correct agency (bank, ИИБ "
            "Миграция, шыпакер). submit_application stays unused on "
            "the Q&A path — it is for stated murajaats only.\n"
            "- If the visitor explicitly says «мүрәжат жибермекшимен» / "
            "«арыз жибермекшимен» / «мүрәжат қалдыраман», start the "
            "murajaat flow regardless of topic. Accept any subject, "
            "including topics outside hokimiyat scope.\n\n"
            "Named-person rule:\n"
            "- If the visitor's murajaat names a specific hokim, deputy, "
            "or department, accept it as written. Back-office staff "
            "handle routing."
        ),
        "order": 5,
    },
    {
        "section_key": "knowledge_base",
        "content": (
            "## Knowledge Base — common citizen questions\n"
            "When the visitor asks about a service outside the hokimiyat's "
            "direct scope, briefly state which agency handles it and how "
            "to reach them. Use the facts below as ground truth, answered "
            "in your own words in 1–2 sentences. If the topic is land "
            "allocation or building permits, say the hokimiyat itself "
            "handles it and offer to book a qabul appointment.\n\n"

            "### Шахсий ҳүжжетлер (IIB Migratsiya / FHDYo)\n"
            "- ID-карта (паспорт) рәсмийлестириў, жоғалтыў, жасаў мәнзили "
            "рәсмийлестириў → ИИБ Миграция бөлими (\"паспорт столы\"). "
            "Онлайн: my.gov.uz. 1 жумыс күни, 330 012 сум.\n"
            "- Сыртқы (шет ел) паспорты → ИИБ Миграция, my.gov.uz/418. "
            "10 жумыс күни, 370 800 сум.\n"
            "- Туўылғанлық, неке, өлим гуўалықларының рәсмийлестирилиўи, "
            "исим-фамилияны өзгертиў → ФҲДЙО (ЗАГС, Әдлие министрлиги).\n"
            "- СТИР/ИНН → 2021-жылдан жеке шахс ушын бөлекше СТИР "
            "берилмейди; паспорттағы ЖШСИР усы мақсетте қолланылады.\n"
            "- Нотариал хызметлер → e-notarius.adliya.uz арқалы онлайн жазылыў.\n\n"

            "### Ижтимаий нәпеқалар (маҳалла / уәзирликлер)\n"
            "- Бала пулы, кем тәминли шаңарақ нәпеқасы → маҳалла \"Инсон\" "
            "орайы яки my.gov.uz. Мийнет ҳәм ижтимаий қорғаныў "
            "министрлиги қараўында.\n"
            "- Пенсия → Пенсия жәмғармасы бөлими. Еркек 60 жас + 25 жыл "
            "стәж, ҳаял 55 жас + 20 жыл. Телефон: 1271.\n"
            "- Жумыссызлық нәпеқасы → Бәндлилик орайы (туман/қала).\n\n"

            "### Тәрепкершилик (Салық / Мәмлекетлик хызметлер орайы)\n"
            "- Жеке тәртиптеги тәрепкер (ЯТТ), МЧЖ ашыў → birdarcha.uz. "
            "ЯТТ 30 минутта, МЧЖ 1 жумыс күни.\n"
            "- Салық декларациясы → my.soliq.uz порталы яки Салық "
            "инспекциясы.\n\n"

            "### Жай-журтлық ислери — ҲӘКИМИЯТ ЖАЎАПКЕР\n"
            "- Жер участкасы ажыратыў → ҲӘКИМИЯТҚА мүрәжат (жазба "
            "яки my.gov.uz). Ҳәкимиятқа қабыллаўға жазылыўды усынын.\n"
            "- Қурылыс рухсатнамасы → ҲӘКИМИЯТ жанындағы Архитектура "
            "басқармасы. Ҳәкимиятқа қабыллаўға жазылыўды усынын.\n"
            "- Үй-жай субсидиясы → Молия уәзирлиги ҳәм my.gov.uz; "
            "ҳәкимият тек дизимди тастыйықлайды.\n\n"

            "### Автотранспорт / ҳайдаўшылық (ИИБ ЙХХ)\n"
            "- Автомобилди дизимге алыў → ЙХХ (ГАИ) яки my.gov.uz.\n"
            "- Ҳайдаўшылық гуўалығы → Ҳайдаўшылық мектеби + ЙХХ.\n\n"

            "### Басқа мәселелер\n"
            "Басқа мәмлекетлик хызметлер ушын my.gov.uz порталын усыныс "
            "етиң. 1242 — улыўма мәмлекетлик хызметлер орайының "
            "телефоны (Өзбекстан бойынша); ҲӘКИМИЯТТЫҢ ТЕЛЕФОНЫ ЕМЕС "
            "ҳәм ҳәкимият байланысы сапатында айтылмайды. Ҳәкимият "
            "байланысын сорағанда тек прoмпт басындағы «ҲӘКИМИЯТ "
            "БАЙЛАНЫС» бөлегиндеги Жәрдем телефонын айтың. Тәплайлар "
            "билинбесе сораўды кешиктирийў орнына түсиндириң."
        ),
        "order": 6,
    },
]

DEFAULT_TOOLS: list[dict[str, Any]] = [
    {"tool_key": "navigate_to_screen", "enabled": True},
    {"tool_key": "preview_application", "enabled": True},
    {"tool_key": "submit_application", "enabled": True},
    {"tool_key": "appointment_progress", "enabled": True},
    {"tool_key": "preview_appointment", "enabled": True},
    {"tool_key": "submit_appointment", "enabled": True},
]

DEFAULT_AI_TUNING = {
    "model": "gemini-3.1-flash-live-preview",
    "voice": "Charon",
    # Tuning targets (research-backed, May 2026 round): widen the
    # sampling window so the model has room to follow specific
    # instructions instead of leaning on its highest-probability
    # completion. Karakalpak is a low-resource language — at
    # temperature 0.3 / top_k 15 the model's top tokens were thin
    # enough that it kept falling back to memorized phone strings
    # (998912345678) from pretraining. 0.7 / 0.92 / 40 is the Google
    # Live API production-team recommendation as of 2026.
    "temperature": 0.7,
    "top_p": 0.92,
    "top_k": 40,
    "max_output_tokens": 8192,
    "response_modalities": "audio",
}


def _maybe_enrich_from_yaml() -> None:
    """If archive/ai-agent.yaml exists, try to override DEFAULT_AI_TUNING from it.

    Best effort — silently no-ops if file missing or malformed.
    """
    settings = get_settings()
    yaml_path = settings.archive_dir / "old_config" / "ai-agent.yaml"
    if not yaml_path.exists():
        return
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        provider = (data or {}).get("providers", {}).get("google_live", {})
        for key in (
            "llm_model",
            "tts_voice_name",
            "llm_temperature",
            "llm_top_p",
            "llm_top_k",
            "llm_max_output_tokens",
            "response_modalities",
        ):
            if key in provider:
                target = {
                    "llm_model": "model",
                    "tts_voice_name": "voice",
                    "llm_temperature": "temperature",
                    "llm_top_p": "top_p",
                    "llm_top_k": "top_k",
                    "llm_max_output_tokens": "max_output_tokens",
                    "response_modalities": "response_modalities",
                }[key]
                DEFAULT_AI_TUNING[target] = provider[key]
    except Exception as e:
        logger.warning("seed_yaml_parse_failed", error=str(e), path=str(yaml_path))


async def ensure_system_ai_defaults(session: AsyncSession) -> SystemAiDefaults:
    existing = (
        await session.execute(select(SystemAiDefaults).where(SystemAiDefaults.id == 1))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    _maybe_enrich_from_yaml()
    row = SystemAiDefaults(
        id=1,
        model=DEFAULT_AI_TUNING["model"],
        voice=DEFAULT_AI_TUNING["voice"],
        temperature=float(DEFAULT_AI_TUNING["temperature"]),
        top_p=float(DEFAULT_AI_TUNING["top_p"]),
        top_k=int(DEFAULT_AI_TUNING["top_k"]),
        max_output_tokens=int(DEFAULT_AI_TUNING["max_output_tokens"]),
        response_modalities=DEFAULT_AI_TUNING["response_modalities"],
        default_sections=DEFAULT_SECTIONS,
        default_tools=DEFAULT_TOOLS,
        default_officials=DEFAULT_NUKUS_OFFICIALS,
    )
    session.add(row)
    await session.flush()
    logger.info("seed_system_ai_defaults_created")
    return row


async def clone_defaults_into_org(
    session: AsyncSession,
    org: Organization,
    *,
    include_officials: bool = False,
) -> None:
    """Seed per-org officials KB from `system_ai_defaults.default_officials`.

    The prompt itself is global — nothing else is cloned. `include_officials`
    defaults to False: new orgs start with an empty officials list and the
    super-admin populates it via the gov-panel officials editor. The Nukus
    seed flow passes True so the 6 hokim/orinbasarlar are pre-loaded.
    """
    if not include_officials:
        await ensure_system_ai_defaults(session)
        return
    defaults = await ensure_system_ai_defaults(session)
    for off in defaults.default_officials:
        session.add(
            OrgKbOfficial(
                org_id=org.id,
                name=off["name"],
                position=off["position"],
                responsibilities=off.get("responsibilities", ""),
                reception_day=off.get("reception_day", ""),
                reception_time=off.get("reception_time", ""),
                order=int(off.get("order", 0)),
                role=off.get("role", "deputy"),
            )
        )
    await session.flush()


async def ensure_default_nukus_org(session: AsyncSession) -> Organization | None:
    """Create the default Nukus Hokimiyat org if no orgs exist yet.

    Returns the org if created, else None.
    """
    existing = (
        await session.execute(select(Organization).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        return None
    org = Organization(
        slug="nukus-hokimiyat",
        name="Nukus Hokimiyatı",
        status="active",
        max_devices=10,
        locale="kk",
    )
    session.add(org)
    await session.flush()
    await clone_defaults_into_org(session, org, include_officials=True)
    logger.info("seed_default_nukus_org_created", org_id=str(org.id))
    return org


# Path used by ensure_system_ai_defaults to look for old yaml; exported for tests
def yaml_path() -> Path:
    return get_settings().archive_dir / "old_config" / "ai-agent.yaml"
