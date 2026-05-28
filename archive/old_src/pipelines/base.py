"""
Pipeline base — minimal stub kept for engine.py imports.

The full pipeline system was removed during cleanup (Gemini-only deployment).
Only LLMResponse is kept because engine.py imports it for tool-call response shaping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class LLMResponse:
    """Standard response from an LLM, containing text and/or tool calls."""
    text: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
