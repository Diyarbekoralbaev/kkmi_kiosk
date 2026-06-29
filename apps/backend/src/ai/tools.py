"""Kiosk tool declarations + dispatcher that maps tool calls to events.

Single citizen flow — murajat (appeal) to the Council, forwarded to the external
cabinet (cabinet.murajat.uz). The appeal is keyed by the citizen's phone:

  - lookup_citizen(phone)     → is this phone a known citizen? returns their name
    so the agent can ask «Siz {name} misiz?» before collecting anything.
  - get_quarters(district_id) → the mahallalar of one district, so the agent maps
    a spoken mahalla to its quarter_id (the districts themselves are listed in
    the system prompt).
  - preview_murajat           → show the draft appeal on screen for review.
  - submit_murajat            → forward it to the cabinet.

No qabul, no feedback, no categories, no officials.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_PHONE_DESC = (
    "Exactly 9 digits, no spaces or separators (e.g. 901234567). The visitor "
    "MUST have spoken this number aloud in the current session. Do not pass a "
    "placeholder or example digits, do not copy a number from any other source. "
    "If the visitor has not yet spoken a phone, do not call this tool — ask for "
    "the phone first."
)

# JSON Schema declarations for the kiosk tools we expose to the voice agent.
# Only the tools listed in `enabled_tools` (from prompt_builder) are sent.
TOOL_DECLS: dict[str, dict[str, Any]] = {
    "navigate_to_screen": {
        "name": "navigate_to_screen",
        "description": (
            "Navigate the kiosk UI to one of the available screens. "
            "Call this BEFORE speaking when the visitor requests info that "
            "lives on a specific screen."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "screen": {
                    "type": "string",
                    "enum": ["home", "submit", "contacts", "ai"],
                    "description": "Screen to navigate to.",
                }
            },
            "required": ["screen"],
        },
    },
    "lookup_citizen": {
        "name": "lookup_citizen",
        "description": (
            "Look up a citizen by phone in the Council registry. Call this as "
            "soon as the visitor has spoken a 9-digit phone aloud, BEFORE "
            "collecting any personal details.\n\n"
            "Returns {exists, full_name}.\n"
            "  • exists=true → greet by name and ask «Siz {full_name} misiz?». "
            "If the visitor confirms, you need ONLY the appeal text — call "
            "preview_murajat with confirmed=true (no personal fields).\n"
            "  • exists=false, OR the visitor says it is not them → collect the "
            "full personal details and call preview_murajat with confirmed=false."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": _PHONE_DESC},
            },
            "required": ["phone"],
        },
    },
    "get_quarters": {
        "name": "get_quarters",
        "description": (
            "List the mahallalar (quarters / MFY) of ONE district so you can "
            "map the mahalla the visitor names to its quarter_id. Call this "
            "AFTER you have resolved the district_id — the districts (with ids) "
            "are listed in your system prompt under «ТУМАНЛАР».\n"
            "Returns [{id, name_uz, name_oz, name_ru, name_qq}]. Match the "
            "visitor's spoken mahalla to the closest entry and use its id as "
            "quarter_id. Only needed for a NEW citizen (confirmed=false)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "district_id": {
                    "type": "integer",
                    "description": "The id of the district the visitor named.",
                },
            },
            "required": ["district_id"],
        },
    },
    "preview_murajat": {
        "name": "preview_murajat",
        "description": (
            "Show the visitor the draft appeal (murajaat) on the kiosk screen "
            "for review. This renders the card the visitor sees — it is the ONLY "
            "way to put the draft on screen. Do NOT ask «Дурыс па?» before this "
            "call — the visitor needs to see the rendered card first.\n\n"
            "TWO cases:\n"
            "  • CONFIRMED existing citizen (lookup_citizen returned exists=true "
            "AND the visitor confirmed «Siz X misiz?» → ha): pass confirmed=true "
            "with ONLY phone + text. Personal fields are NOT needed.\n"
            "  • NEW citizen, or the visitor said it is not them: pass "
            "confirmed=false with phone + text AND every personal field "
            "(first_name, last_name, birth_date, gender, district_id, "
            "quarter_id, address).\n"
            "Compose `text` in Karakalpak Cyrillic only from facts the visitor "
            "stated — do not infer. Do not call until the appeal text and (for a "
            "new citizen) all personal fields are collected."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": _PHONE_DESC},
                "text": {
                    "type": "string",
                    "description": (
                        "The appeal body in Karakalpak Cyrillic — what happened "
                        "and what the visitor wants, composed only from what they "
                        "said. This is the whole appeal (there is no separate "
                        "topic field)."
                    ),
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "true ONLY when lookup_citizen found this phone and the "
                        "visitor confirmed it is them — then personal fields are "
                        "omitted and the registry record is left unchanged. "
                        "false for a new citizen or «it is not me» — then ALL "
                        "personal fields below are required."
                    ),
                },
                "first_name": {"type": "string", "description": "Required when confirmed=false."},
                "last_name": {"type": "string", "description": "Required when confirmed=false."},
                "birth_date": {
                    "type": "string",
                    "description": "Birth date YYYY-MM-DD. Required when confirmed=false.",
                },
                "gender": {
                    "type": "string",
                    "enum": ["1", "0"],
                    "description": "1 = erkak (male), 0 = ayol (female). Required when confirmed=false.",
                },
                "district_id": {
                    "type": "integer",
                    "description": (
                        "The district id, matched from the «ТУМАНЛАР» list in "
                        "your prompt. Required when confirmed=false."
                    ),
                },
                "quarter_id": {
                    "type": "integer",
                    "description": (
                        "The mahalla id from get_quarters(district_id). "
                        "Required when confirmed=false."
                    ),
                },
                "address": {
                    "type": "string",
                    "description": "Street / house address. Required when confirmed=false.",
                },
            },
            "required": ["phone", "text", "confirmed"],
        },
    },
    "submit_murajat": {
        "name": "submit_murajat",
        "description": (
            "Forward the previously-previewed appeal to the Council cabinet.\n\n"
            "INVOCATION CONDITION — only call when BOTH are true:\n"
            "  (1) preview_murajat was already called in this session with the "
            "same values.\n"
            "  (2) The visitor explicitly affirmed («Ха», «Дурыс», ...).\n"
            "Pass the SAME values verbatim — same confirmed flag, same text, "
            "same personal fields. Do not re-compose the text between preview "
            "and submit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Same 9-digit number as preview_murajat."},
                "text": {"type": "string", "description": "Same value as preview_murajat."},
                "confirmed": {"type": "boolean", "description": "Same value as preview_murajat."},
                "first_name": {"type": "string", "description": "Same as preview_murajat (when confirmed=false)."},
                "last_name": {"type": "string", "description": "Same as preview_murajat (when confirmed=false)."},
                "birth_date": {"type": "string", "description": "Same as preview_murajat (when confirmed=false)."},
                "gender": {"type": "string", "enum": ["1", "0"], "description": "Same as preview_murajat (when confirmed=false)."},
                "district_id": {"type": "integer", "description": "Same as preview_murajat (when confirmed=false)."},
                "quarter_id": {"type": "integer", "description": "Same as preview_murajat (when confirmed=false)."},
                "address": {"type": "string", "description": "Same as preview_murajat (when confirmed=false)."},
            },
            "required": ["phone", "text", "confirmed"],
        },
    },
}


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    call_id: str


def declarations_for(enabled_tools: list[str]) -> list[dict[str, Any]]:
    return [TOOL_DECLS[name] for name in enabled_tools if name in TOOL_DECLS]
