"""Kiosk tool declarations + dispatcher that maps tool calls to events."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# JSON Schema declarations for the three kiosk tools we expose to Gemini Live.
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
                    "enum": ["home", "reception", "submit", "contacts", "ai"],
                    "description": "Screen to navigate to.",
                }
            },
            "required": ["screen"],
        },
    },
    "preview_application": {
        "name": "preview_application",
        "description": (
            "Show the visitor a draft formal application (murajaat) on the "
            "kiosk screen for review. This call renders the card visitors "
            "see — it is the ONLY way to put the draft on screen.\n\n"
            "INVOCATION CONDITION — only call when ALL of these are true:\n"
            "  (1) The visitor stated a topic in their own words.\n"
            "  (2) The visitor stated the full body of their request in "
            "their own words (what happened, what they want).\n"
            "  (3) The visitor spoke a 9-digit phone number aloud in this "
            "session. Heard, not inferred, not assumed, not a placeholder.\n"
            "If any of the three is missing, ask for it first. "
            "Do NOT ask the visitor «Мәтин дурыс па?» before this call — "
            "the visitor needs to see the rendered card first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "1-2 word subject of the visitor's request, in "
                        "their own words. Do not invent a topic the "
                        "visitor did not state."
                    ),
                },
                "body": {
                    "type": "string",
                    "description": (
                        "2-3 sentence formal body in Karakalpak Cyrillic, "
                        "composed only from facts the visitor stated. "
                        "Do not infer details, names, dates, or events "
                        "the visitor did not say."
                    ),
                },
                "phone": {
                    "type": "string",
                    "description": (
                        "Exactly 9 digits, no spaces or separators. The "
                        "visitor MUST have spoken this number aloud in "
                        "the current session. Do not pass a placeholder, "
                        "do not pass example digits like 998912345678 or "
                        "901234567, do not copy a number from any other "
                        "source. If the visitor has not yet spoken a "
                        "phone, do not call this tool — ask for the "
                        "phone first."
                    ),
                },
                "category_slug": {
                    "type": "string",
                    "enum": [
                        "housing",
                        "land",
                        "construction",
                        "utilities",
                        "employment",
                        "education",
                        "health",
                        "social",
                        "business",
                        "other",
                    ],
                    "description": (
                        "Exactly one of the 10 enum values. Pick the "
                        "closest match to the visitor's stated issue. "
                        "If unsure or the topic is not on the list "
                        "(bank, credit, other agency, private person), "
                        "use 'other'. Do not invent a slug outside the "
                        "enum."
                    ),
                },
            },
            "required": ["topic", "body", "phone", "category_slug"],
        },
    },
    "submit_application": {
        "name": "submit_application",
        "description": (
            "Submit the previously-previewed application to the back "
            "office.\n\n"
            "INVOCATION CONDITION — only call when BOTH are true:\n"
            "  (1) preview_application was already called in this "
            "session with the same topic / body / phone / category_slug.\n"
            "  (2) The visitor explicitly affirmed with «Ха», «Дурыс», or "
            "an equivalent in reply to «Мәтин дурыс па?».\n"
            "Pass the same topic, body, phone, and category_slug verbatim "
            "as you sent to preview_application. Do not re-compose the "
            "body, do not re-categorize, do not 'tidy up' the text "
            "between preview and submit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "Same value passed to preview_application — "
                        "verbatim, no edits."
                    ),
                },
                "body": {
                    "type": "string",
                    "description": (
                        "Same value passed to preview_application — "
                        "verbatim, no edits."
                    ),
                },
                "phone": {
                    "type": "string",
                    "description": (
                        "Same 9-digit number passed to "
                        "preview_application — the one the visitor "
                        "actually spoke aloud."
                    ),
                },
                "category_slug": {
                    "type": "string",
                    "enum": [
                        "housing",
                        "land",
                        "construction",
                        "utilities",
                        "employment",
                        "education",
                        "health",
                        "social",
                        "business",
                        "other",
                    ],
                    "description": (
                        "Same slug passed to preview_application. "
                        "Do not re-categorize."
                    ),
                },
            },
            "required": ["topic", "body", "phone", "category_slug"],
        },
    },
    "appointment_progress": {
        "name": "appointment_progress",
        "description": (
            "Lightweight stage marker for the qabul booking flow. Call after "
            "EACH user reply during qabul to advance the kiosk stepper. Pass "
            "only the field captured by THIS user reply.\n"
            "  - stage='topic' + topic: visitor stated their issue\n"
            "  - stage='official' + official_id: visitor confirmed the official you proposed\n"
            "  - stage='phone' + phone: visitor said their phone number\n"
            "Do NOT use this for the final confirmation step — that's preview_appointment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "enum": ["topic", "official", "phone"],
                },
                "topic": {"type": "string"},
                "official_id": {"type": "string"},
                "phone": {"type": "string"},
            },
            "required": ["stage"],
        },
    },
    "preview_appointment": {
        "name": "preview_appointment",
        "description": (
            "Show the visitor a draft qabul (reception appointment) on the "
            "kiosk screen for review. This call renders the card the "
            "visitor sees.\n\n"
            "INVOCATION CONDITION — only call when ALL of these are true:\n"
            "  (1) The visitor stated an issue that you mapped to one "
            "specific official from the OFFICIALS KB (by responsibilities), "
            "and you sent appointment_progress(stage='topic', topic=...).\n"
            "  (2) You proposed that official by name and position, and "
            "the visitor confirmed; you sent "
            "appointment_progress(stage='official', official_id=...).\n"
            "  (3) The visitor spoke a 9-digit phone number aloud in this "
            "session, and you sent appointment_progress(stage='phone', "
            "phone=...).\n"
            "If any is missing, collect it first. Do not ask "
            "«Мағлыўматлар дурыс па?» before this call — the visitor "
            "needs to see the rendered card first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "official_id": {
                    "type": "string",
                    "description": (
                        "MUST be a UUID copied verbatim from the OFFICIALS "
                        "KB block at the bottom of this prompt. Do not "
                        "fabricate a UUID, do not pattern-match a "
                        "plausible-looking one, do not pass any UUID that "
                        "is not present in the KB block."
                    ),
                },
                "topic": {
                    "type": "string",
                    "description": (
                        "1-2 sentence summary of the visitor's issue, "
                        "in their own words. Do not invent or paraphrase "
                        "details the visitor did not state."
                    ),
                },
                "phone": {
                    "type": "string",
                    "description": (
                        "Exactly 9 digits, no spaces or separators. The "
                        "visitor MUST have spoken this number aloud in "
                        "the current session. Do not pass a placeholder, "
                        "do not pass example digits like 998912345678 or "
                        "901234567. If the visitor has not yet spoken a "
                        "phone, do not call this tool — ask for the "
                        "phone first."
                    ),
                },
            },
            "required": ["official_id", "topic", "phone"],
        },
    },
    "submit_appointment": {
        "name": "submit_appointment",
        "description": (
            "Finalize the previously-previewed qabul (reception "
            "appointment). Backend assigns a queue number and triggers "
            "receipt printing.\n\n"
            "INVOCATION CONDITION — only call when BOTH are true:\n"
            "  (1) preview_appointment was already called in this session "
            "with the same official_id / topic / phone.\n"
            "  (2) The visitor explicitly affirmed with «Ха», «Дурыс», or "
            "an equivalent in reply to «Мағлыўматлар дурыс па?»."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "official_id": {
                    "type": "string",
                    "description": (
                        "Same UUID passed to preview_appointment — "
                        "verbatim, copied from the OFFICIALS KB block."
                    ),
                },
                "topic": {
                    "type": "string",
                    "description": (
                        "Same value passed to preview_appointment — "
                        "verbatim, no edits."
                    ),
                },
                "phone": {
                    "type": "string",
                    "description": (
                        "Same 9-digit number passed to "
                        "preview_appointment — the one the visitor "
                        "actually spoke aloud."
                    ),
                },
            },
            "required": ["official_id", "topic", "phone"],
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
