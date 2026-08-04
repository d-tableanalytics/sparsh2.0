"""Recruitment analytics — the client-wise hiring funnel.

Answers the metrics the review document lists, for one client or across all of them:
CVs reviewed / selected / rejected, CVs shared with the client, client-side rejections and
shortlists, total joinings, plus the position-wise breakdown and the source/referral mix.

Two things worth knowing about how the numbers are derived:

  * A candidate has ONE `stage`, so a naive group-by would count someone now at Offer as
    neither "shortlisted" nor "shared with client", even though they passed through both. The
    funnel counts are therefore computed from stage ORDERING — reached(stage) means "is at or
    past it" — which is what makes the funnel monotonic and the conversion rates meaningful.
  * Rejections are terminal, so a candidate rejected at Shortlisted never reached Assessment.
    Their furthest point is recorded on the journey, so `reached` reads the journey when the
    current stage is terminal and falls back to the stage itself otherwise.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from app.db.mongodb import get_collection
from app.models.hrms import (
    COL_CANDIDATES, COL_REQUISITIONS,
    CANDIDATE_STAGES, CANDIDATE_FORWARD, REJECTION_STAGES,
    STAGE_APPLIED, STAGE_SHORTLISTED, STAGE_SHARED_CLIENT, STAGE_CLIENT_SHORTLISTED,
    STAGE_CLIENT_REJECTED, STAGE_ASSESSMENT, STAGE_INTERVIEW, STAGE_OFFER,
    STAGE_APPOINTMENT, STAGE_HIRED, STAGE_REJECTED,
)

logger = logging.getLogger(__name__)


def _furthest_stage(doc: dict) -> str:
    """How far this candidate actually got.

    For a live candidate that is simply their current stage. For a rejected one the current
    stage says only "Rejected", so the journey is walked to find the furthest forward stage
    they reached before it — otherwise every rejection would collapse to the top of the funnel
    and the drop-off point would be invisible.
    """
    stage = doc.get("stage") or STAGE_APPLIED
    if stage not in REJECTION_STAGES:
        return stage

    furthest = STAGE_APPLIED
    for entry in (doc.get("journey") or []):
        for candidate_stage in (entry.get("from"), entry.get("to")):
            if candidate_stage in CANDIDATE_FORWARD:
                if CANDIDATE_FORWARD.index(candidate_stage) > CANDIDATE_FORWARD.index(furthest):
                    furthest = candidate_stage
    return furthest


def _reached(furthest: str, target: str) -> bool:
    """Did the candidate get at least as far as `target`?"""
    if furthest not in CANDIDATE_FORWARD or target not in CANDIDATE_FORWARD:
        return False
    return CANDIDATE_FORWARD.index(furthest) >= CANDIDATE_FORWARD.index(target)


def build_query(client_company_id: Optional[str] = None,
                request_no: Optional[str] = None,
                date_from: Optional[str] = None,
                date_to: Optional[str] = None) -> dict:
    """Mongo query for the analytics filters. Backed by ix_candidate_client_date."""
    query: dict = {}
    if client_company_id:
        query["client_company_id"] = client_company_id
    if request_no:
        query["request_no"] = request_no

    window = {}
    if date_from:
        try:
            window["$gte"] = datetime.fromisoformat(f"{date_from[:10]}T00:00:00+00:00")
        except ValueError:
            pass
    if date_to:
        try:
            window["$lte"] = datetime.fromisoformat(f"{date_to[:10]}T23:59:59+00:00")
        except ValueError:
            pass
    if window:
        query["created_at"] = window
    return query


async def recruitment_analytics(client_company_id: Optional[str] = None,
                                request_no: Optional[str] = None,
                                date_from: Optional[str] = None,
                                date_to: Optional[str] = None) -> dict:
    """The whole dashboard payload in one call.

    Read in a single pass and folded in Python rather than as several aggregations: the funnel
    needs `_furthest_stage`, which walks the journey array, and expressing that as a pipeline
    would be far harder to read for no gain at this data size.
    """
    query = build_query(client_company_id, request_no, date_from, date_to)

    docs = await get_collection(COL_CANDIDATES).find(
        query,
        {"stage": 1, "journey": 1, "designation": 1, "request_no": 1, "source": 1,
         "platform": 1, "referral_source": 1, "referred_by": 1,
         "client_company_id": 1, "client_company_name": 1},
    ).to_list(20000)

    # Stage census — where everyone stands right now.
    by_stage = {s: 0 for s in CANDIDATE_STAGES}
    # Funnel — how many ever reached each step.
    funnel = {s: 0 for s in CANDIDATE_FORWARD}
    positions: dict = {}
    sources: dict = {}
    referrals: dict = {}

    internal_rejected = 0
    client_rejected = 0

    for doc in docs:
        stage = doc.get("stage") or STAGE_APPLIED
        by_stage[stage] = by_stage.get(stage, 0) + 1
        if stage == STAGE_REJECTED:
            internal_rejected += 1
        elif stage == STAGE_CLIENT_REJECTED:
            client_rejected += 1

        furthest = _furthest_stage(doc)
        for step in CANDIDATE_FORWARD:
            if _reached(furthest, step):
                funnel[step] += 1

        # Position-wise: every stage count, keyed by the role.
        key = doc.get("designation") or "Unspecified"
        slot = positions.setdefault(key, {
            "designation": key,
            "requestNo": doc.get("request_no") or "",
            "total": 0,
            **{s: 0 for s in CANDIDATE_STAGES},
        })
        slot["total"] += 1
        slot[stage] = slot.get(stage, 0) + 1

        src = doc.get("source") or doc.get("platform") or "Unknown"
        sources[src] = sources.get(src, 0) + 1
        ref = doc.get("referral_source")
        if ref:
            referrals[ref] = referrals.get(ref, 0) + 1

    total = len(docs)
    # "Reviewed" = screened at all, i.e. moved off Applied in any direction. A CV still sitting
    # at Applied has not been looked at yet, which is precisely the number HR wants to see.
    pending_review = by_stage.get(STAGE_APPLIED, 0)
    reviewed = total - pending_review

    return {
        "totals": {
            "cvsReceived": total,
            "cvsReviewed": reviewed,
            "cvsPendingReview": pending_review,
            "cvsSelected": funnel.get(STAGE_SHORTLISTED, 0),
            "cvsRejected": internal_rejected,
            "cvsSharedWithClient": funnel.get(STAGE_SHARED_CLIENT, 0),
            "clientShortlisted": funnel.get(STAGE_CLIENT_SHORTLISTED, 0),
            "clientRejected": client_rejected,
            "interviewed": funnel.get(STAGE_INTERVIEW, 0),
            "offered": funnel.get(STAGE_OFFER, 0),
            "appointmentLettersSent": funnel.get(STAGE_APPOINTMENT, 0),
            "joinings": funnel.get(STAGE_HIRED, 0),
        },
        # Ordered so the client can render it as a funnel without re-sorting.
        "funnel": [{"stage": s, "count": funnel[s]} for s in CANDIDATE_FORWARD],
        "byStage": [{"stage": s, "count": by_stage.get(s, 0)} for s in CANDIDATE_STAGES],
        "positions": sorted(positions.values(), key=lambda p: -p["total"]),
        "sources": sorted(
            [{"source": k, "count": v} for k, v in sources.items()], key=lambda r: -r["count"]),
        "referrals": sorted(
            [{"source": k, "count": v} for k, v in referrals.items()], key=lambda r: -r["count"]),
        "stages": CANDIDATE_STAGES,
    }


async def requisition_options(client_company_id: Optional[str] = None) -> list:
    """Requisitions for the dashboard's position filter, newest first."""
    query = {"client_company_id": client_company_id} if client_company_id else {}
    rows = await get_collection(COL_REQUISITIONS).find(
        query, {"request_no": 1, "designation": 1}).sort([("created_at", -1)]).to_list(500)
    return [{"requestNo": r.get("request_no"), "designation": r.get("designation") or ""}
            for r in rows]
