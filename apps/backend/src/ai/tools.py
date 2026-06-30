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
                    "enum": ["home", "qabul", "submit", "feedback", "contacts", "ai"],
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
    "appointment_progress": {
        "name": "appointment_progress",
        "description": (
            "Lightweight stage marker for the qabul (reception) registration "
            "flow. Call after EACH user reply during qabul to advance the "
            "kiosk stepper. Pass only the field captured by THIS reply.\n"
            "  - stage='topic' + topic: the reason the visitor states for the "
            "reception (always ask for it)\n"
            "  - stage='phone' + phone: visitor said their phone number\n"
            "Do NOT use this for the final confirmation — that's "
            "preview_appointment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "enum": ["topic", "phone"]},
                "topic": {"type": "string"},
                "phone": {"type": "string"},
            },
            "required": ["stage"],
        },
    },
    "preview_appointment": {
        "name": "preview_appointment",
        "description": (
            "Show the visitor a draft qabul (reception) registration on the "
            "kiosk screen for review. There is no official and no fixed date — "
            "the Council calls the citizen back to schedule.\n\n"
            "INVOCATION CONDITION — only call after the visitor has BOTH "
            "stated the reason (topic) and spoken a 9-digit phone aloud in "
            "this session. Do not ask «Мағлыўматлар дурыс па?» before this "
            "call — the visitor needs to see the rendered card first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "The reason for the reception (1-2 sentences) in the "
                        "visitor's own words."
                    ),
                },
                "phone": {"type": "string", "description": _PHONE_DESC},
            },
            "required": ["phone"],
        },
    },
    "submit_appointment": {
        "name": "submit_appointment",
        "description": (
            "Finalize the previously-previewed qabul registration. The Council "
            "will call the citizen back to schedule.\n\n"
            "INVOCATION CONDITION — only call when BOTH are true:\n"
            "  (1) preview_appointment was already called in this session with "
            "the same phone (and topic, if any).\n"
            "  (2) The visitor explicitly affirmed («Ха», «Дурыс», ...) in "
            "reply to «Мағлыўматлар дурыс па?»."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Same value as preview_appointment (may be empty)."},
                "phone": {"type": "string", "description": "Same 9-digit number as preview_appointment."},
            },
            "required": ["phone"],
        },
    },
    "preview_feedback": {
        "name": "preview_feedback",
        "description": (
            "Show the visitor a draft feedback entry (shaǵım / usınıs / "
            "minnetdarshılıq) on the kiosk screen for review.\n\n"
            "INVOCATION CONDITION — only call when ALL of these are true:\n"
            "  (1) The visitor's intent maps to one feedback_type.\n"
            "  (2) The visitor stated the feedback text in their own words.\n"
            "  (3) The visitor spoke a 9-digit phone aloud in this session.\n"
            "Do NOT ask «Дурыс па?» before this call — show the card first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "feedback_type": {
                    "type": "string",
                    "enum": ["complaint", "suggestion", "gratitude"],
                    "description": (
                        "complaint = shaǵım, suggestion = usınıs, "
                        "gratitude = minnetdarshılıq. Pick the closest match."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": (
                        "The feedback body in Karakalpak Cyrillic, composed "
                        "only from what the visitor stated."
                    ),
                },
                "phone": {"type": "string", "description": _PHONE_DESC},
            },
            "required": ["feedback_type", "text", "phone"],
        },
    },
    "submit_feedback": {
        "name": "submit_feedback",
        "description": (
            "Submit the previously-previewed feedback entry.\n\n"
            "INVOCATION CONDITION — only call when BOTH are true:\n"
            "  (1) preview_feedback was already called in this session with "
            "the same feedback_type / text / phone.\n"
            "  (2) The visitor explicitly affirmed («Ха», «Дурыс», ...).\n"
            "Pass the same values verbatim."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "feedback_type": {
                    "type": "string",
                    "enum": ["complaint", "suggestion", "gratitude"],
                    "description": "Same value as preview_feedback.",
                },
                "text": {"type": "string", "description": "Same value as preview_feedback."},
                "phone": {"type": "string", "description": "Same 9-digit number as preview_feedback."},
            },
            "required": ["feedback_type", "text", "phone"],
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
