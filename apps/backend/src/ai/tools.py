"""Kiosk tool declarations, scoped per menu.

The visitor picks a menu on the home screen before the voice session opens, and
the kiosk passes that menu on the WS URL. Only that menu's tools are declared to
Gemini. This is deliberate: with all of them live at once the model reliably
mixed flows — offering to file an appeal when asked about a timetable, or
calling `show_schedule` mid-appeal. Declaring three tools instead of ten also
keeps the prompt short enough that the guardrails stay in attention.

Menus and their tools:

  maslahatchi   navigate_to_screen, show_info_card
                General study/medical Q&A. Answers out loud; the info card is
                the visual aid.
  library       navigate_to_screen, find_book, show_books
                Reads OUR catalogue (`library_books`), typed in by the
                librarians — IRBIS was never reachable from outside the
                institute network.
  abituriyent   navigate_to_screen, show_directions, show_direction,
                show_info_card
  murojat       navigate_to_screen, preview_murojat, submit_murojat
                Appeals are stored in OUR database and worked in the gov panel.
  jadval        navigate_to_screen, find_group, show_schedule
  qabul         navigate_to_screen, show_leadership, preview_reception,
                submit_reception

`preview_*` before `submit_*` is not ceremony: it is the only way the visitor
sees what is about to be filed under their name. The submit tool refuses to run
until the matching preview has.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.library import SECTIONS

_PHONE_DESC = (
    "Exactly 9 digits, no spaces or separators (e.g. 901234567). The visitor "
    "MUST have spoken this number aloud in the current session. Do not pass a "
    "placeholder or example digits, and do not copy a number from any other "
    "source. If the visitor has not yet spoken a phone, do not call this tool — "
    "ask for the phone first."
)

_SCREENS = [
    "home",
    "maslahatchi",
    "library",
    "abituriyent",
    "murojat",
    "jadval",
    "qabul",
    "contacts",
]

TOOL_DECLS: dict[str, dict[str, Any]] = {
    "navigate_to_screen": {
        "name": "navigate_to_screen",
        "description": (
            "Navigate the kiosk UI to one of the available screens. Call this "
            "BEFORE speaking when the visitor asks for a section that lives on "
            "a different screen."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "screen": {
                    "type": "string",
                    "enum": _SCREENS,
                    "description": "Screen to navigate to.",
                }
            },
            "required": ["screen"],
        },
    },
    # ── Shared visual aid ────────────────────────────────────────────────────
    "show_info_card": {
        "name": "show_info_card",
        "description": (
            "Put a short titled card with bullet points on the kiosk screen "
            "while you speak. Use it when your spoken answer contains a list, "
            "numbers, or steps the visitor would otherwise have to memorise — "
            "e.g. the parts of a body system, exam subjects, required "
            "documents.\n\n"
            "Do NOT use it to repeat a one-sentence answer; the card is a "
            "visual aid, not a transcript. Keep bullets to 6 or fewer and each "
            "under ~60 characters so they stay readable across the hall. Write "
            "the card in the SAME language you are speaking."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short heading, 2-5 words."},
                "bullets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Up to 6 short lines. No numbering — the UI adds it.",
                },
            },
            "required": ["title", "bullets"],
        },
    },
    # ── Dars jadvali ─────────────────────────────────────────────────────────
    "find_group": {
        "name": "find_group",
        "description": (
            "Find a study group by the name the visitor spoke. Call this as "
            "soon as they name a group, BEFORE asking for a day.\n\n"
            "Write digits as DIGITS: say the visitor said «bir yuz yigirma A», "
            "pass \"120 A\". Spelled-out numerals will not match.\n\n"
            "Returns {candidates: [{id, name, faculty, specialty, language}]} "
            "ordered best-first.\n"
            "  • Exactly one candidate → confirm it aloud («120 A lesh ENG "
            "guruhimi?») before calling show_schedule.\n"
            "  • Several → read the names out and ask which one.\n"
            "  • Empty → the group does not exist under that name. Say so and "
            "ask them to repeat it or to use the on-screen faculty list. NEVER "
            "guess a group: showing a stranger's timetable sends the visitor to "
            "the wrong room."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The group name as spoken, with numerals written as "
                        "digits. E.g. \"120 A\", \"pediatriya 209\"."
                    ),
                }
            },
            "required": ["query"],
        },
    },
    "show_schedule": {
        "name": "show_schedule",
        "description": (
            "Render a group's timetable on the kiosk screen and return the same "
            "lessons so you can read them aloud.\n\n"
            "INVOCATION CONDITION: `group_id` must come from a find_group "
            "result that the visitor CONFIRMED. Never invent an id.\n\n"
            "Returns {group, scope, lessons: [{date, weekday, start, end, "
            "subject, teacher, room, kind}], empty_reason}.\n"
            "  • lessons non-empty → summarise briefly (how many classes, the "
            "first one's time and subject). Do not read every field aloud; the "
            "card on screen has them.\n"
            "  • lessons empty with empty_reason=\"no_lessons_that_day\" → tell "
            "them there are no classes then.\n"
            "  • lessons empty with empty_reason=\"year_not_published\" → the "
            "new academic year's timetable is not in the system yet. Say that "
            "plainly and offer to show the last week that did have classes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "group_id": {
                    "type": "integer",
                    "description": "Confirmed id from find_group.",
                },
                "scope": {
                    "type": "string",
                    "enum": [
                        "today",
                        "tomorrow",
                        "week",
                        "last_taught_week",
                        "date",
                        "week_of",
                    ],
                    "description": (
                        "Which range to show. Use \"last_taught_week\" — the group's "
                        "most recent week with classes — only after the "
                        "visitor accepts the offer to see it. Use \"date\" for one "
                        "named day and \"week_of\" for the week containing it; "
                        "both need `date`."
                    ),
                },
                "date": {
                    "type": "string",
                    "description": (
                        "ISO date YYYY-MM-DD. Required for scope \"date\" and "
                        "\"week_of\", ignored otherwise. Resolve relative phrases "
                        "(«next Monday», «the 5th») against the CURRENT TIME "
                        "block at the top of this prompt — never guess the year."
                    ),
                },
            },
            "required": ["group_id", "scope"],
        },
    },
    # ── Abituriyent ──────────────────────────────────────────────────────────
    "show_directions": {
        "name": "show_directions",
        "description": (
            "List the institute's degree programmes on screen (bachelor's, "
            "master's, clinical residency) and return them so you can answer. "
            "Call this when an applicant asks what they can study here.\n\n"
            "Returns {items: [{id, code, name, faculty, education_type, "
            "group_count, languages}]}. Summarise by education type rather "
            "than reading all of them."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    "show_direction": {
        "name": "show_direction",
        "description": (
            "Show one programme in detail. `specialty_id` must come from a "
            "show_directions result.\n\n"
            "Returns {item: {name, code, education_type, faculty, languages, "
            "group_count, subjects}}. `subjects` is what the degree is actually "
            "taught through, ranked by how much of the timetable each takes — "
            "it is the most useful thing you can tell an applicant, so name a "
            "few rather than listing the label fields. `languages` are the "
            "languages this programme really has groups in.\n\n"
            "Admission quotas, pass marks and tuition fees are NOT in this "
            "system. If asked, say the institute's admissions office publishes "
            "them each year and point the visitor there — never estimate a "
            "number."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "specialty_id": {
                    "type": "integer",
                    "description": "Id from show_directions.",
                }
            },
            "required": ["specialty_id"],
        },
    },
    # ── Kutubxona (our own catalogue, typed in by the librarians) ────────────
    "find_book": {
        "name": "find_book",
        "description": (
            "Search the institute library's catalogue by title, author or "
            "subject, show the matches on screen, and return them.\n\n"
            "Returns {items: [{id, title, authors, year, publisher, language, "
            "section_label, copies, shelf, description, available}]}.\n"
            "  • One match → say the title and author, and where it is "
            "(`shelf`). The card on screen carries the rest.\n"
            "  • Several → read out two or three titles and ask which one.\n"
            "  • Empty → the library has not catalogued it. Say so plainly and "
            "suggest the reading room. Do NOT fall back on what you know about "
            "the book from anywhere else — only this catalogue counts.\n\n"
            "`shelf` or `year` may be empty: the librarians are still filling "
            "the cards in. An empty field means «not recorded», so say that "
            "rather than guessing a shelf."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Title, author surname, or both, as the visitor said "
                        "them. E.g. \"anatomiya sapin\", \"farmakologiya\"."
                    ),
                }
            },
            "required": ["query"],
        },
    },
    "show_books": {
        "name": "show_books",
        "description": (
            "List the catalogue's shelf sections, or every book in ONE section, "
            "on screen. Use this when the visitor is browsing rather than "
            "looking for a specific title — «what medical books do you have?», "
            "«anything on pharmacology?».\n\n"
            "Called with no `section` it returns the sections and their counts; "
            "with a `section` it returns that section's books. Summarise; do "
            "not read a whole shelf aloud."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": list(SECTIONS),
                    "description": "Shelf section. Omit to list the sections.",
                }
            },
        },
    },
    # ── Murojat (stored in our DB) ───────────────────────────────────────────
    "preview_murojat": {
        "name": "preview_murojat",
        "description": (
            "Show the drafted appeal on the kiosk screen for the visitor to "
            "check. This is the ONLY way to render it — do not ask «is this "
            "correct?» before calling, because there is nothing on screen yet.\n\n"
            "Collect first, one question per turn: what the appeal is about "
            "(the whole text, in the visitor's own words — do not pad or "
            "invent), their full name, and a contact phone.\n\n"
            "`topic` is a 3-6 word summary YOU write from the text, for the "
            "staff's list view. It is not a field the visitor dictates."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "full_name": {
                    "type": "string",
                    "description": "As the visitor stated it. Required.",
                },
                "phone": {"type": "string", "description": _PHONE_DESC},
                "topic": {
                    "type": "string",
                    "description": "Your 3-6 word summary of the appeal.",
                },
                "text": {
                    "type": "string",
                    "description": (
                        "The appeal body, composed only from what the visitor "
                        "said, in the language they used."
                    ),
                },
            },
            "required": ["full_name", "phone", "topic", "text"],
        },
    },
    "submit_murojat": {
        "name": "submit_murojat",
        "description": (
            "File the previewed appeal with the institute.\n\n"
            "INVOCATION CONDITION — both must hold:\n"
            "  (1) preview_murojat already ran this session with these values.\n"
            "  (2) The visitor explicitly agreed («ha», «to‘g‘ri», «yes»).\n"
            "Pass the SAME values verbatim; do not re-compose the text between "
            "preview and submit.\n\n"
            "Returns {reference}. Read that reference number back to the "
            "visitor and tell them the institute will contact them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "full_name": {"type": "string", "description": "Same as preview_murojat."},
                "phone": {"type": "string", "description": "Same as preview_murojat."},
                "topic": {"type": "string", "description": "Same as preview_murojat."},
                "text": {"type": "string", "description": "Same as preview_murojat."},
            },
            "required": ["full_name", "phone", "topic", "text"],
        },
    },
    # ── Rahbariyat qabuli ────────────────────────────────────────────────────
    "show_leadership": {
        "name": "show_leadership",
        "description": (
            "Show the institute's leadership (rector, vice-rectors, deans) with "
            "their reception days on screen, and return the list.\n\n"
            "Returns {items: [{id, name, position, reception_day, "
            "reception_time}]}. Call this when the visitor asks who they can "
            "see or wants to book a reception. Only offer people from this "
            "list — never name an official from memory."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    "preview_reception": {
        "name": "preview_reception",
        "description": (
            "Show the drafted reception booking on screen for review.\n\n"
            "`official_id` must come from show_leadership. Collect the "
            "visitor's full name, a contact phone, and the reason for the "
            "visit (one short sentence) before calling."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "official_id": {
                    "type": "string",
                    "description": "Id from show_leadership.",
                },
                "full_name": {"type": "string", "description": "As stated by the visitor."},
                "phone": {"type": "string", "description": _PHONE_DESC},
                "reason": {
                    "type": "string",
                    "description": "One short sentence, in the visitor's words.",
                },
            },
            "required": ["official_id", "full_name", "phone", "reason"],
        },
    },
    "submit_reception": {
        "name": "submit_reception",
        "description": (
            "Register the previewed reception booking and print the visitor's "
            "ticket.\n\n"
            "INVOCATION CONDITION — preview_reception already ran this session "
            "with these values AND the visitor explicitly agreed. Pass the same "
            "values verbatim.\n\n"
            "Returns {reference, reception_day, reception_time}. Tell the "
            "visitor their number and when to come; the ticket prints itself."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "official_id": {"type": "string", "description": "Same as preview_reception."},
                "full_name": {"type": "string", "description": "Same as preview_reception."},
                "phone": {"type": "string", "description": "Same as preview_reception."},
                "reason": {"type": "string", "description": "Same as preview_reception."},
            },
            "required": ["official_id", "full_name", "phone", "reason"],
        },
    },
}

# Which tools each menu declares. The kiosk sends the menu on the WS URL; an
# unknown value falls back to "maslahatchi" (see api/kiosk_ws.py).
MENU_TOOLS: dict[str, tuple[str, ...]] = {
    "maslahatchi": ("navigate_to_screen", "show_info_card"),
    "library": ("navigate_to_screen", "find_book", "show_books"),
    "abituriyent": (
        "navigate_to_screen",
        "show_directions",
        "show_direction",
        "show_info_card",
    ),
    "murojat": ("navigate_to_screen", "preview_murojat", "submit_murojat"),
    "jadval": ("navigate_to_screen", "find_group", "show_schedule"),
    "qabul": (
        "navigate_to_screen",
        "show_leadership",
        "preview_reception",
        "submit_reception",
    ),
}

MENUS = tuple(MENU_TOOLS)
DEFAULT_MENU = "maslahatchi"


def tools_for_menu(menu: str) -> list[str]:
    return list(MENU_TOOLS.get(menu, MENU_TOOLS[DEFAULT_MENU]))


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    call_id: str


def declarations_for(enabled_tools: list[str]) -> list[dict[str, Any]]:
    return [TOOL_DECLS[name] for name in enabled_tools if name in TOOL_DECLS]
