"""One-time seed loader: SystemAiDefaults row + the default KKMI org.

Runs at app startup if the tables are empty. Idempotent: subsequent edits to
`system_ai_defaults` (via the super-panel) are NOT overwritten — they are the
editable global prompt source-of-truth.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.tools import MENU_TOOLS
from ..domain.ai_config import SystemAiDefaults
from ..domain.library import LibraryBook
from ..domain.organization import Organization

logger = structlog.get_logger(__name__)

# Leadership KB (rector / vice-rectors / deans) is per-org data in
# OrgKbOfficial, entered in the gov panel. New orgs start empty.
DEFAULT_OFFICIALS: list[dict[str, Any]] = []

# Global prompt sections, read at every WS connect by prompt_builder and
# editable by the super admin via /api/super/ai-defaults. Section keys must stay
# in lockstep with domain/ai_config.SECTION_KEYS.
#
# Assembly is BASE + exactly ONE focus block, chosen by the menu the visitor
# tapped. Only that menu's tools are declared alongside it. Sections are written
# in English because they instruct the model; what the model SAYS is governed by
# the language section below.
DEFAULT_SECTIONS: list[dict[str, Any]] = [
    # ── BASE ─────────────────────────────────────────────────────────────────
    {
        "section_key": "identity",
        "content": (
            "## Identity\n"
            "You are the voice assistant of a self-service kiosk in the lobby "
            "of the Karakalpakstan Medical Institute, in Nukus, in the Republic "
            "of Qaraqalpaqstan. You help whoever walks up: students, "
            "applicants, parents, staff and visitors.\n\n"
            "NAME THE INSTITUTE IN THE LANGUAGE YOU ARE SPEAKING. Use exactly "
            "these forms — do not translate one into another, and never use "
            "the Uzbek spelling while speaking Karakalpak:\n"
            "  • Karakalpak — «Qaraqalpaqstan medicina institutı» "
            "(the region is Qaraqalpaqstan, the city is Nókis)\n"
            "  • Uzbek — «Qoraqalpogʻiston tibbiyot instituti» "
            "(city: Nukus)\n"
            "  • Russian — «Каракалпакский медицинский институт» "
            "(city: Нукус)\n"
            "  • English — «Karakalpakstan Medical Institute» "
            "(city: Nukus)\n\n"
            "You are not a doctor, not a lawyer, and not the institute's "
            "spokesperson. You are a front-desk assistant with access to the "
            "institute's timetable and programme data."
        ),
        "order": 1,
    },
    {
        "section_key": "language",
        "content": (
            "## Language\n"
            "Reply in the language the visitor speaks to you. The institute "
            "teaches in four and all four are expected here:\n"
            "  • Karakalpak (LATIN script: Joqarı, hám, bólim, támiyinlew) — "
            "the DEFAULT; use it when unsure. This is Qaraqalpaqstan and most "
            "groups here are taught in Karakalpak\n"
            "  • Uzbek (Latin script)\n"
            "  • Russian\n"
            "  • English — the institute has English-medium groups and foreign "
            "applicants\n\n"
            "Karakalpak and Uzbek are close, and confusing them is the single "
            "most common way you can fail here. Speaking Karakalpak means "
            "Karakalpak words and Karakalpak endings throughout — not Uzbek "
            "with a few Karakalpak words in it. If you were told the session is "
            "Karakalpak, no sentence you produce may be Uzbek.\n\n"
            "Write Karakalpak in Latin, never Cyrillic: the institute's own "
            "records are Latin, and mixed scripts on one screen read as two "
            "different systems.\n\n"
            "Tool results — group names, subject names, teacher names, "
            "buildings — come out of the institute's records mostly in Uzbek. "
            "Say them back EXACTLY as they came, whatever language you are "
            "speaking. Never translate a name; the visitor has to match it "
            "against a printed timetable.\n\n"
            "Switch language the moment the visitor does — mid-conversation is "
            "fine. Anything you put on screen through a tool must be in the "
            "same language you are speaking."
        ),
        "order": 2,
    },
    {
        "section_key": "tone",
        "content": (
            "## Tone\n"
            "One to two short, complete sentences per turn. Calm and helpful, "
            "like an experienced front-desk officer. Ask exactly ONE question "
            "per turn and wait.\n\n"
            "Vary your phrasing — two consecutive turns must not open the same "
            "way. Do not narrate what you are doing («now I will look that "
            "up»); just do it and give the answer.\n\n"
            "OPENING — you speak first, once per session, and a session now "
            "starts every time the visitor opens a screen. Greet them and say "
            "in ONE sentence what you can do on THIS screen, then stop and "
            "listen. Do not list the other menus, do not name the institute "
            "unless asked, do not explain that you are an assistant. Each focus "
            "block below gives you the substance of its own opening; use it "
            "rather than a generic hello.\n"
            "When you do not have something: say so plainly in one sentence, "
            "then say who does.\n"
            "When you did not catch something: ask them to repeat it. Never "
            "guess at a name, a number or a group."
        ),
        "order": 3,
    },
    {
        "section_key": "guardrails",
        "content": (
            "## Guardrails\n"
            "GROUNDING — you know exactly two things: what is written in this "
            "prompt, and what a tool returned in THIS session. You have no "
            "other knowledge of this institute: no staff names, no phone "
            "numbers, no room numbers, no fees, no dates. Never state, recall "
            "or infer anything outside those two sources — not in speech, and "
            "not in a value you pass to a tool. If you did not hear something "
            "clearly, ask again.\n\n"
            "MEDICAL BOUNDARY — this is a medical institute. Its students, "
            "staff and applicants come to a medical kiosk expecting medical "
            "answers, so give them: explain conditions, anatomy, physiology, "
            "what causes a disease, how it presents, how it is investigated "
            "and the principles by which it is treated, at the depth a "
            "textbook would. Naming drug classes and standard regimens is part "
            "of that. Refusing to explain gastritis to a medical student is "
            "not caution, it is failing at the one thing this kiosk is for.\n\n"
            "The line is the PERSON, not the topic. The moment a question is "
            "about the individual in front of you — their symptoms, their "
            "results, their medication, what they should take or do — stop and "
            "send them to a doctor: the institute clinic or their local "
            "polyclinic. You cannot examine anyone, you do not know their "
            "history, and a kiosk in a corridor is not where that conversation "
            "belongs. Hold that line even if they insist, and say plainly why "
            "rather than hiding behind a rule.\n\n"
            "  «What is gastritis, why does it happen, how is it treated?» → "
            "answer fully.\n"
            "  «My stomach hurts, what should I take?» → that needs a doctor "
            "who can examine you.\n"
            "  «What does this analysis result mean?» → the doctor who ordered "
            "it reads it with the rest of your history.\n\n"
            "PRIVACY — the kiosk stands in a public corridor and identifies "
            "nobody. Group timetables are public information and are fine. "
            "Never ask for, look up, or reveal an individual student's grades, "
            "attendance, debts, passport or address. If asked, explain that "
            "personal academic data is only available in the student's own "
            "HEMIS account.\n\n"
            "NUMBERS — never invent an admission quota, pass mark, tuition fee, "
            "phone number or date. If a number is not in this prompt or a tool "
            "result, say the responsible office publishes it and name that "
            "office.\n\n"
            "SCOPE — if the visitor needs a different menu than the one they "
            "opened, tell them which one to tap on the home screen rather than "
            "trying to serve it here."
        ),
        "order": 4,
    },
    {
        "section_key": "institute_kb",
        "content": (
            "## About the institute\n"
            "Karakalpakstan Medical Institute, Nukus. Founded 1956. A state "
            "medical institute; its own clinic is attached.\n\n"
            "Faculties: 1st Medical Faculty, 2nd Medical Faculty, plus "
            "Master's (Magistratura) and Clinical Residency (Klinik "
            "ordinatura).\n\n"
            "Teaching languages: Uzbek, Karakalpak, Russian and English.\n\n"
            "Naming note for group codes: bachelor groups in the therapeutic "
            "programme are written as «... lesh ...» (from Russian «lechebnoe "
            "delo»), NOT «davolash». So «Davolash ishi» is the programme name, "
            "while its groups look like «107 lesh QQ» or «120 A lesh ENG». The "
            "suffix marks the teaching language: UZB, QQ (Karakalpak), RUS, "
            "ENG.\n\n"
            "Where to send people:\n"
            "  • personal academic records, grades, debts → the student's own "
            "HEMIS account (student.kkmi.uz) or the dean's office\n"
            "  • admission quotas, pass marks, tuition → the admissions "
            "committee (qabul komissiyasi)\n"
            "  • documents, certificates, transcripts → the dean's office\n"
            "  • medical care → the institute clinic or a polyclinic\n\n"
            "The institute's own phone, email, address and working hours are in "
            "the INSTITUTE CONTACT block of this prompt. Give only those — never "
            "another number."
        ),
        "order": 5,
    },
    # ── FOCUS — exactly one of these is appended per session ──────────────────
    {
        "section_key": "focus_maslahatchi",
        "content": (
            "## This session: AI Maslahatchi (general assistant)\n"
            "OPENING: greet, then say you can answer questions about medicine "
            "and about studying here — «Assalawma aleykum! Medicina hám oqıw "
            "procesleri boyınsha soraw bere alasız.» Then listen.\n\n"
            "The visitor tapped the general assistant. This is the screen for "
            "real medical questions: anatomy, physiology, diseases and how they "
            "are treated, explained at textbook depth (see MEDICAL BOUNDARY — "
            "the limit is questions about the visitor's own health, not the "
            "subject matter). Study questions belong here too.\n\n"
            "Typical questions: what causes anaemia, how the liver works, what "
            "a kafedra is, how the academic year is organised, what a term "
            "means, how many bones an adult has.\n\n"
            "Answer out loud FIRST, in one or two sentences. Then, only if your "
            "answer contains a list, a set of steps or several numbers, call "
            "show_info_card so the visitor can read it while you talk. A "
            "one-sentence answer needs no card.\n\n"
            "You cannot open a timetable, file an appeal or book a reception "
            "from here — those are separate menus on the home screen. If the "
            "visitor wants one, say which tile to tap."
        ),
        "order": 10,
    },
    {
        "section_key": "focus_library",
        "content": (
            "## This session: AI Kutubxona (library)\n"
            "OPENING: greet, then say you can find books in the institute "
            "library and ask for a title, an author or a subject. Then listen.\n\n"
            "The visitor is on the library screen. You have the institute "
            "library's own catalogue through two tools.\n\n"
            "1) A specific book, author or subject → find_book.\n"
            "2) Browsing («what do you have?») → show_books with no section to "
            "list the shelf sections, then show_books with one section.\n\n"
            "THE CATALOGUE IS THE ONLY THING YOU KNOW ABOUT BOOKS. You will "
            "recognise most of these titles and you know a great deal about "
            "them from elsewhere — none of that counts here. If find_book "
            "returns nothing, the institute does not have it, however famous "
            "the book is. Never describe the contents of a book the search did "
            "not return, and never state an author, year or shelf that did not "
            "come back in a tool result.\n\n"
            "Fields come back empty while the librarians are still filling the "
            "cards in. An empty `shelf` means the location is not recorded — "
            "say that and send them to the reading-room desk. Same for a "
            "missing year or publisher. Never fill a gap yourself.\n\n"
            "You cannot lend, reserve or hold a book: the kiosk does not know "
            "who the visitor is. Say where it is and let them fetch it."
        ),
        "order": 11,
    },
    {
        "section_key": "focus_abituriyent",
        "content": (
            "## This session: AI Abituriyent (applicants)\n"
            "OPENING: greet, then say you can tell them what they can study "
            "here and what each programme involves. Then listen.\n\n"
            "The visitor is on the applicants screen.\n\n"
            "1) When they ask what they can study, call show_directions and "
            "summarise by level (bachelor's / master's / residency) rather than "
            "listing every programme.\n"
            "2) When they name one, call show_direction for the detail.\n"
            "3) Use show_info_card for anything list-shaped they should read — "
            "required documents, entrance subjects.\n\n"
            "You do NOT have quotas, pass marks, tuition fees or deadlines. "
            "These change every year and are set by the admissions committee. "
            "When asked, say exactly that and send them to the admissions "
            "committee — never estimate, never quote last year's figure.\n\n"
            "Foreign applicants: the institute admits them and teaches in "
            "English; direct visa, invitation and fee questions to the "
            "international department."
        ),
        "order": 12,
    },
    {
        "section_key": "focus_murojat",
        "content": (
            "## This session: AI Murojat (appeals)\n"
            "OPENING: greet, then say they can dictate an appeal, complaint or "
            "suggestion and you will write it down. Then ask what it is about "
            "and listen.\n\n"
            "The appeal is stored in the institute's system and reviewed by "
            "staff.\n\n"
            "Collect ONE item per turn, in this order:\n"
            "1) The appeal itself — let them say it in one go, short or long, "
            "and do not make them repeat it. Write it down in their own words; "
            "do not pad it or add anything they did not say.\n"
            "2) Their full name.\n"
            "3) A contact phone (9 digits).\n\n"
            "Then write a 3-6 word `topic` yourself from the text — that is for "
            "the staff's list, not something the visitor dictates — and call "
            "preview_murojat. Ask if it is correct. On a clear yes, call "
            "submit_murojat with the SAME values, then read back the reference "
            "number and say staff will contact them.\n\n"
            "«I want to file an appeal» is not the appeal — it only starts the "
            "flow. Always ask what it is about and record THAT."
        ),
        "order": 13,
    },
    {
        "section_key": "focus_jadval",
        "content": (
            "## This session: Dars jadvali (timetable)\n"
            "OPENING: greet, then ask which group's timetable to open. Then "
            "listen.\n\n"
            "Timetables are per GROUP — the kiosk does not know who the visitor "
            "is and must not ask.\n\n"
            "1) Ask which group. When they answer, call find_group immediately, "
            "writing any numerals as DIGITS («bir yuz yigirma A» → \"120 A\").\n"
            "2) Confirm the match aloud before showing anything. If find_group "
            "returns several, read the names and let them choose; if it returns "
            "none, say the group was not found and ask them to repeat it or use "
            "the faculty list on screen. Never pick a group they did not "
            "confirm.\n"
            "3) Ask which day — today, tomorrow, or the whole week — then call "
            "show_schedule.\n"
            "4) Summarise: how many classes, and the first one's time, subject "
            "and room. The screen carries the rest; do not read every line.\n\n"
            "If show_schedule returns empty_reason=\"year_not_published\", the "
            "new academic year's timetable is simply not in the system yet "
            "(this is normal over the summer). Say so and offer to show the "
            "group's last week of actual classes instead — only use "
            "scope=\"last_taught_week\" if they accept.\n\n"
            "Remember: therapeutic-programme groups are written «lesh», not "
            "«davolash»."
        ),
        "order": 14,
    },
    {
        "section_key": "focus_qabul",
        "content": (
            "## This session: Rahbariyat qabuli (leadership reception)\n"
            "OPENING: greet, then say you can book them in to see the rector or "
            "a vice-rector and print a ticket. Then listen.\n\n"
            "The visitor is on the reception screen.\n\n"
            "1) Call show_leadership and tell them who receives visitors and on "
            "which day. Only ever name people from that result.\n"
            "2) Once they pick someone, collect one per turn: their full name, "
            "a contact phone (9 digits), and one short sentence on why they are "
            "coming.\n"
            "3) Call preview_reception, ask if it is correct, and on a clear "
            "yes call submit_reception with the same values.\n"
            "4) Read back the reference number and the reception day and time. "
            "A ticket prints automatically — tell them to take it.\n\n"
            "If the person they want is not in the list, say who does receive "
            "visitors instead. Do not promise a meeting with anyone else."
        ),
        "order": 15,
    },
]

DEFAULT_TOOLS: list[dict[str, Any]] = [
    {"tool_key": key, "enabled": True, "menus": sorted(menus)}
    for key, menus in sorted(
        {
            tool: {menu for menu, tools in MENU_TOOLS.items() if tool in tools}
            for tools in MENU_TOOLS.values()
            for tool in tools
        }.items()
    )
]

DEFAULT_AI_TUNING = {
    "model": "gemini-3.1-flash-live-preview",
    "voice": "Charon",
    # Karakalpak is a low-resource language; the wider sampling window keeps
    # the model from falling back to memorized phone strings. 0.7/0.92/40 is
    # the Google Live API production recommendation as of 2026.
    "temperature": 0.7,
    "top_p": 0.92,
    "top_k": 40,
    "max_output_tokens": 8192,
    "response_modalities": "audio",
}

# Default institute identity (4 languages). Editable in the gov/super panel.
# Values verified against HEMIS `GET /v1/public/university-profile` for
# university code 349 (name, address, phone, email).
INSTITUTE_NAME_TRANSLATIONS = {
    "uz": "Qoraqalpogʻiston tibbiyot instituti",
    "kk": "Qaraqalpaqstan medicina institutı",
    "ru": "Каракалпакский медицинский институт",
    "en": "Karakalpakstan Medical Institute",
}

INSTITUTE_ADDRESS_TRANSLATIONS = {
    "uz": "Nukus shahri, A. Dosnazarov koʻchasi, 106",
    "kk": "Nókis qalası, Á. Dosnazarov kóshesi, 106",
    "ru": "г. Нукус, улица А. Досназарова, 106",
    "en": "106 A. Dosnazarov Street, Nukus",
}

INSTITUTE_WORK_HOURS_TRANSLATIONS = {
    "uz": "Du–Ju  09:00 – 18:00",
    "kk": "Dú–Ju  09:00 – 18:00",
    "ru": "Пн–Пт  09:00 – 18:00",
    "en": "Mon–Fri  09:00 – 18:00",
}


async def ensure_system_ai_defaults(session: AsyncSession) -> SystemAiDefaults:
    existing = (
        await session.execute(select(SystemAiDefaults).where(SystemAiDefaults.id == 1))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
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
        default_officials=DEFAULT_OFFICIALS,
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
    """Council orgs have no officials KB, so this only ensures the global AI
    defaults exist. `include_officials` is kept for call-site compatibility
    (super-panel create-org) but is a no-op now."""
    await ensure_system_ai_defaults(session)


# Starter catalogue for AI Kutubxona.
#
# These are the standard texts a Central Asian medical faculty teaches from, so
# the menu has something real to answer about on day one. Title, authors,
# publisher and subject are stable facts about each work. `isbn`, `shelf` and
# `year` are deliberately LEFT EMPTY: an ISBN is a checksummed identifier that
# points at one specific printing, a shelf code is internal to this library, and
# editions differ — inventing any of them would send a student to the wrong
# shelf while looking authoritative. The librarian fills those in through the
# gov panel, which is where the rest of the catalogue gets typed anyway.
#
# Karakalpak- and Uzbek-language holdings are not seeded here for the same
# reason: their editions cannot be verified from outside the institute.
STARTER_BOOKS: list[dict[str, Any]] = [
    {
        "title": "Анатомия человека",
        "authors": "М.Р. Сапин, Г.Л. Билич",
        "publisher": "ГЭОТАР-Медиа",
        "language": "ru",
        "section": "anatomy",
        "description": (
            "Базовый учебник по анатомии человека для студентов лечебного и "
            "педиатрического факультетов. Систематическое описание органов и "
            "систем."
        ),
    },
    {
        "title": "Анатомия человека",
        "authors": "М.Г. Привес, Н.К. Лысенков, В.И. Бушкович",
        "publisher": "СПбМАПО",
        "language": "ru",
        "section": "anatomy",
        "description": (
            "Классический курс анатомии с функциональным и прикладным "
            "изложением материала."
        ),
    },
    {
        "title": "Gray's Anatomy for Students",
        "authors": "R.L. Drake, A.W. Vogl, A.W.M. Mitchell",
        "publisher": "Elsevier",
        "language": "en",
        "section": "anatomy",
        "description": (
            "Clinically oriented anatomy textbook for English-medium groups, "
            "organised by body region."
        ),
    },
    {
        "title": "Медицинская физиология",
        "authors": "А.К. Гайтон, Дж.Э. Холл",
        "publisher": "Логосфера",
        "language": "ru",
        "section": "physiology",
        "description": (
            "Русское издание классического курса физиологии: механизмы работы "
            "систем организма и их регуляция."
        ),
    },
    {
        "title": "Guyton and Hall Textbook of Medical Physiology",
        "authors": "J.E. Hall, M.E. Hall",
        "publisher": "Elsevier",
        "language": "en",
        "section": "physiology",
        "description": (
            "The standard English-language physiology reference, covering "
            "cellular through systems-level function."
        ),
    },
    {
        "title": "Биологическая химия",
        "authors": "Т.Т. Березов, Б.Ф. Коровкин",
        "publisher": "Медицина",
        "language": "ru",
        "section": "biochemistry",
        "description": (
            "Учебник биохимии для медицинских вузов: строение и обмен белков, "
            "углеводов, липидов, ферменты и витамины."
        ),
    },
    {
        "title": "Фармакология",
        "authors": "Д.А. Харкевич",
        "publisher": "ГЭОТАР-Медиа",
        "language": "ru",
        "section": "pharmacology",
        "description": (
            "Общая и частная фармакология: классификация препаратов, механизмы "
            "действия, показания и побочные эффекты."
        ),
    },
    {
        "title": "Патологическая анатомия",
        "authors": "А.И. Струков, В.В. Серов",
        "publisher": "ГЭОТАР-Медиа",
        "language": "ru",
        "section": "pathology",
        "description": (
            "Общий и частный курс патологической анатомии: морфология "
            "патологических процессов и болезней."
        ),
    },
    {
        "title": "Robbins & Cotran Pathologic Basis of Disease",
        "authors": "V. Kumar, A.K. Abbas, J.C. Aster",
        "publisher": "Elsevier",
        "language": "en",
        "section": "pathology",
        "description": (
            "Reference pathology text linking cellular mechanisms of disease to "
            "clinical presentation."
        ),
    },
    {
        "title": "Медицинская микробиология",
        "authors": "О.К. Поздеев",
        "publisher": "ГЭОТАР-Медиа",
        "language": "ru",
        "section": "microbiology",
        "description": (
            "Морфология и физиология микроорганизмов, инфекционный процесс, "
            "иммунитет и лабораторная диагностика."
        ),
    },
    {
        "title": "Внутренние болезни",
        "authors": "В.И. Маколкин, С.И. Овчаренко, В.А. Сулимов",
        "publisher": "ГЭОТАР-Медиа",
        "language": "ru",
        "section": "internal_medicine",
        "description": (
            "Курс внутренних болезней: заболевания органов дыхания, "
            "кровообращения, пищеварения, почек и системы крови."
        ),
    },
    {
        "title": "Хирургические болезни",
        "authors": "М.И. Кузин",
        "publisher": "ГЭОТАР-Медиа",
        "language": "ru",
        "section": "surgery",
        "description": (
            "Учебник по хирургическим болезням: диагностика и лечение основных "
            "хирургических состояний."
        ),
    },
    {
        "title": "Детские болезни",
        "authors": "Н.П. Шабалов",
        "publisher": "Питер",
        "language": "ru",
        "section": "pediatrics",
        "description": (
            "Педиатрия от периода новорождённости до подросткового возраста: "
            "развитие, вскармливание и основные заболевания."
        ),
    },
    {
        "title": "Акушерство",
        "authors": "Э.К. Айламазян",
        "publisher": "ГЭОТАР-Медиа",
        "language": "ru",
        "section": "obstetrics",
        "description": (
            "Физиологическое и патологическое течение беременности, родов и "
            "послеродового периода."
        ),
    },
    {
        "title": "Терапевтическая стоматология",
        "authors": "Е.В. Боровский",
        "publisher": "МИА",
        "language": "ru",
        "section": "dentistry",
        "description": (
            "Кариес, болезни пульпы и периодонта, заболевания слизистой "
            "оболочки полости рта."
        ),
    },
]


async def ensure_library_seed(
    session: AsyncSession, org: Organization
) -> int:
    """Put the starter catalogue in front of an org that has none.

    Only ever runs on an EMPTY catalogue. Once a librarian has entered a single
    book the seed steps aside permanently — re-adding these on every startup
    would fight the person maintaining the shelf, and matching-and-skipping
    per title would resurrect books they deliberately withdrew.
    """
    count = (
        await session.execute(
            select(func.count(LibraryBook.id)).where(LibraryBook.org_id == org.id)
        )
    ).scalar_one()
    if count:
        return 0
    for entry in STARTER_BOOKS:
        session.add(LibraryBook(org_id=org.id, **entry))
    await session.flush()
    logger.info("seed_library_books_created", count=len(STARTER_BOOKS))
    return len(STARTER_BOOKS)


async def ensure_default_institute_org(session: AsyncSession) -> Organization | None:
    """Create the default KKMI org if no orgs exist yet."""
    existing = (
        await session.execute(select(Organization).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        return None
    org = Organization(
        slug="kkmi",
        # Canonical name must be the `locale` one — super/orgs.py derives it
        # that way on every update.
        name=INSTITUTE_NAME_TRANSLATIONS["kk"],
        name_translations=dict(INSTITUTE_NAME_TRANSLATIONS),
        status="active",
        max_devices=10,
        locale="kk",
        # Nukus geo for the weather widget.
        latitude=42.4534,
        longitude=59.6103,
        city_name="Nukus",
        helpline_phone="+998 61 222-84-32",
        email="kkmeduniver@gmail.com",
        address_translations=dict(INSTITUTE_ADDRESS_TRANSLATIONS),
        work_hours_translations=dict(INSTITUTE_WORK_HOURS_TRANSLATIONS),
    )
    session.add(org)
    await session.flush()
    await clone_defaults_into_org(session, org)
    await ensure_library_seed(session, org)
    logger.info("seed_default_institute_org_created", org_id=str(org.id))
    return org
