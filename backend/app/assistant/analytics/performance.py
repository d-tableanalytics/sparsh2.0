"""Performance analytics: averages, trend, strengths/weaknesses, subject scores.

Subject is DERIVED (V1 decision #1) from quiz_title / session topic / quarter name.
Phase 3.
"""
from __future__ import annotations

from typing import List

from app.assistant.schemas.analytics import PerformanceSummary, SubjectScore


def derive_subject(assessment: dict) -> str:
    """Derive a subject label from an assessment record. Phase 3.

    Order of preference (per architecture doc): quiz_title → session topic/title
    → quarter name.
    """
    raise NotImplementedError("performance.derive_subject — Phase 3")


def analyze(assessments: List[dict]) -> PerformanceSummary:
    """Compute a PerformanceSummary from raw assessment records. Phase 3."""
    raise NotImplementedError("performance.analyze — Phase 3")


def subject_scores(assessments: List[dict]) -> List[SubjectScore]:
    """Group results by derived subject into SubjectScore items. Phase 3."""
    raise NotImplementedError("performance.subject_scores — Phase 3")
