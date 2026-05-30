"""Kiosk tool declarations + dispatcher that maps tool calls to events.

Council flows (no categories, no officials, no fixed dates):
  - murajaat: preview_application → submit_application  (topic + body + phone)
  - qabul:    appointment_progress → preview_appointment → submit_appointment
              (optional reason + phone; staff call the citizen back)
  - feedback: preview_feedback → submit_feedback  (type + text + phone)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_PHONE_DESC = (
    "Exactly 9 digits, no spaces or separators. The visitor MUST have spoken "
    "this number aloud in the current session. Do not pass a placeholder, do "
    "not pass example digits like 998912345678 or 901234567, do not copy a "
    "number from any other source. If the visitor has not yet spoken a phone, "
    "do not call this tool — ask for the phone first."
)

# JSON Schema declarations for the kiosk tools we expose to Gemini Live.
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
    "preview_application": {
        "name": "preview_application",
        "description": (
            "Show the visitor a draft formal appeal (murajaat) to the Council "
            "on the kiosk screen for review. This call renders the card the "
            "visitor sees — it is the ONLY way to put the draft on screen.\n\n"
            "INVOCATION CONDITION — only call when ALL of these are true:\n"
            "  (1) The visitor stated a topic in their own words.\n"
            "  (2) The visitor stated the full body of their appeal (what "
            "happened, what they want).\n"
            "  (3) The visitor spoke a 9-digit phone aloud in this session.\n"
            "If any is missing, ask for it first. Do NOT ask «Мәтин дурыс па?» "
            "before this call — the visitor needs to see the rendered card."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "1-2 word subject of the appeal, in the visitor's own "
                        "words. Do not invent a topic the visitor did not state."
                    ),
                },
                "body": {
                    "type": "string",
                    "description": (
                        "2-3 sentence formal body in Karakalpak Cyrillic, "
                        "composed only from facts the visitor stated. Do not "
                        "infer details, names, dates, or events not said."
                    ),
                },
                "phone": {"type": "string", "description": _PHONE_DESC},
            },
            "required": ["topic", "body", "phone"],
        },
    },
    "submit_application": {
        "name": "submit_application",
        "description": (
            "Submit the previously-previewed appeal (murajaat) to the "
            "Council back office.\n\n"
            "INVOCATION CONDITION — only call when BOTH are true:\n"
            "  (1) preview_application was already called in this session with "
            "the same topic / body / phone.\n"
            "  (2) The visitor explicitly affirmed («Ха», «Дурыс», ...) in "
            "reply to «Мәтин дурыс па?».\n"
            "Pass the same topic, body, and phone verbatim — do not re-compose "
            "or 'tidy up' the text between preview and submit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Same value as preview_application."},
                "body": {"type": "string", "description": "Same value as preview_application."},
                "phone": {"type": "string", "description": "Same 9-digit number as preview_application."},
            },
            "required": ["topic", "body", "phone"],
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
