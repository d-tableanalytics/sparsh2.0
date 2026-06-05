"""Assessment results service (V1 decision #3 — defensive legacy handling).

Reads results from BOTH the primary `LearnerAssessments` collection and the
legacy typo'd `LearnerAsessments` (single 's'), merging by `submitted_at`. All
assessment access goes through this service; the dual-read can be removed once
TD-1 (collection consolidation) is complete.

Phase 0: signatures + collection constants only.
"""
from __future__ import annotations

from typing import Dict, List

from app.assistant.schemas.context import UserContext

PRIMARY_COLLECTION = "LearnerAssessments"
LEGACY_COLLECTION = "LearnerAsessments"  # TD-1: legacy typo — read defensively


async def get_results_for_user(ctx: UserContext, user_id: str, limit: int = 100) -> List[Dict]:
    """Merged assessment results for a user (primary + legacy). Phase 1.

    Callers pass a `user_id` already validated against `ctx` scope (a learner may
    only request their own; staff/admin within their permitted scope).
    """
    raise NotImplementedError("assessment_service.get_results_for_user — Phase 1")


async def get_latest_result(ctx: UserContext, user_id: str) -> Dict:
    """Most recent assessment result for a user (primary + legacy). Phase 1."""
    raise NotImplementedError("assessment_service.get_latest_result — Phase 1")
