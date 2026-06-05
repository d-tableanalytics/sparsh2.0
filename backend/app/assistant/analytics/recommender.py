"""Recommendation engine: deterministic study-plan generation.

Signals (per architecture doc §9 / Mapping 3): weak subjects (low/failed quizzes),
pending assignments, attendance gaps, upcoming sessions/exams, incomplete courses.
Candidate generation + ranking happen here; the LLM only phrases the result.
Phase 3.
"""
from __future__ import annotations

from typing import List

from app.assistant.schemas.analytics import StudyPlan


def build_study_plan(
    user_id: str,
    performance: dict,
    pending_assignments: List[dict],
    attendance: List[dict],
    upcoming_sessions: List[dict],
) -> StudyPlan:
    """Rank and assemble a personalized StudyPlan. Phase 3."""
    raise NotImplementedError("recommender.build_study_plan — Phase 3")
