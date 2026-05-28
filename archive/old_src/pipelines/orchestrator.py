"""
Pipeline orchestrator — minimal stub kept for engine.py compatibility.

The full pipeline system was removed during cleanup (Gemini-only deployment).
This stub provides a no-op orchestrator that satisfies engine.py's interface
without actually doing anything: enabled=False, started=False, get_pipeline()
returns None, etc.

If you need real pipelines back, restore from git history.
"""

from __future__ import annotations

from typing import Any, Optional


class PipelineOrchestratorError(Exception):
    """Raised when pipeline orchestration fails."""


class PipelineResolution:
    """Stub: represents a resolved pipeline (always empty after cleanup)."""
    def __init__(self) -> None:
        self.pipeline = None
        self.pipeline_name: Optional[str] = None


class PipelineOrchestrator:
    """No-op orchestrator. Always reports disabled/not-started."""

    def __init__(self, config: Any) -> None:
        self._config = config
        self.enabled: bool = False
        self.started: bool = False

    async def start(self) -> None:
        # Engine wraps this in try/except PipelineOrchestratorError, so raise to
        # signal "no pipelines configured" — engine then logs a benign info message.
        raise PipelineOrchestratorError(
            "Pipelines disabled in this build (Gemini full-agent only)."
        )

    async def stop(self) -> None:
        return None

    def get_pipeline(self, call_id: str, pipeline_name: Optional[str] = None) -> Optional[PipelineResolution]:
        return None

    async def release_pipeline(self, call_id: str) -> None:
        return None
