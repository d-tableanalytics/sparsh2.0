"""Structured shapes returned by the analytics & recommendation engine.

These are the contracts the LLM narrates from — analytics tools return structured
insight (not raw rows) so answers are accurate and consistent.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SubjectScore(BaseModel):
    subject: str                             # derived from quiz_title/topic/quarter (V1)
    average_percentage: float
    attempts: int


class PerformanceSummary(BaseModel):
    average_percentage: float = 0.0
    trend: str = "flat"                      # improving | declining | flat
    quizzes_taken: int = 0
    quizzes_passed: int = 0
    strong_subjects: List[SubjectScore] = Field(default_factory=list)
    weak_subjects: List[SubjectScore] = Field(default_factory=list)


class ProgressSummary(BaseModel):
    completion_percentage: float = 0.0
    completed_sessions: int = 0
    total_sessions: int = 0
    courses_in_progress: int = 0


class StudyRecommendation(BaseModel):
    title: str
    reason: str
    priority: int = 0                        # higher = more urgent
    related_subject: Optional[str] = None


class StudyPlan(BaseModel):
    generated_for: str                       # user_id
    recommendations: List[StudyRecommendation] = Field(default_factory=list)
