"""Learning-progress analytics: completion %, sessions, courses in progress. Phase 3."""
from __future__ import annotations

from typing import List

from app.assistant.schemas.analytics import ProgressSummary


def analyze(learnings: List[dict], sessions: List[dict], quarters: List[dict]) -> ProgressSummary:
    """Compute a ProgressSummary from learnings/sessions/quarters. Phase 3."""
    raise NotImplementedError("progress.analyze — Phase 3")
