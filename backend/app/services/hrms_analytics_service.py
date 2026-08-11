"""HRMS > recruitment analytics and reports. READ-ONLY.

Closes the gap both analysis documents flag: the source computed every figure in the
browser (FRONTEND_ANALYSIS 6.1, BACKEND_ANALYSIS "no reporting backend"). That approach has
three problems this module does not:

  1. It cannot be role-scoped. Whatever the browser is sent, it can total -- so a hiring
     manager who should see their own requisitions is one devtools panel away from the
     company's whole pipeline. Here every aggregation runs behind `_scope`.
  2. It does not scale. Totalling 10k candidates client-side means shipping 10k candidates.
  3. It drifts. Each screen re-derives "how many were interviewed" slightly differently.
     Here the funnel is declared once, in FUNNEL_STAGES, and computed once.

-- Effective rank ------------------------------------------------------------------
A funnel that counts `application_status` can show more offers than interviews, because a
candidate at `Offer Accepted` no longer has an interview status. Every candidate is
therefore ranked by the furthest point they can be SHOWN to have reached -- their status,
OR the existence of an assessment, interview or offer record, whichever is furthest. The
funnel then counts "reached at least this stage", which is monotonically non-increasing by
construction. See models/hrms.py STAGE_RANK.

-- Nothing here writes ---------------------------------------------------------------
No insert, no update, no delete. Analytics that mutate are a debugging nightmare, and a
read-only surface can be reasoned about from its inputs alone.

-- Exports are generated server-side ---------------------------------------------------
Deliberately not built in the browser from a fetched page. The rows are already
role-scoped and paginated here; rebuilding a file client-side would mean shipping rows the
UI had correctly withheld. This mirrors routes/reports.py, but does NOT import from it --
that module is outside HRMS's scope and coupling to its private helpers would make this
module break when it changes.
"""
import csv
import io
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    BREAKDOWN_FIELDS, COLL_ASSESSMENTS, COLL_CANDIDATES, COLL_INTERVIEWS,
    COLL_JOB_POSTINGS, COLL_OFFERS, COLL_ONBOARDING, COLL_REQUISITIONS,
    FUNNEL_STAGES, MAX_BREAKDOWN_ROWS, MAX_EXPORT_ROWS, MAX_RANGE_DAYS,
    MAX_REPORT_PAGE_SIZE, RANK_IF_ACCEPTED, RANK_IF_ASSESSED, RANK_IF_INTERVIEWED,
    RANK_IF_OFFERED, REPORT_ENTITIES, SALARY_REPORT_COLUMNS, AppStatus, Cap, HrmsRole,
    InterviewStatus, OfferStatus, OnboardStatus, ReqApproval, ReqClosing, conversion,
    is_iso_date, stage_rank,
)
# ── Phase 11-R (Items 4, 6) ──
from app.models.hrms import ClientShareStatus, budget_status
from app.utils.hrms_access import can, hrms_role

# Every read in this module is capped. An unbounded to_list on an analytics endpoint is a
# denial-of-service waiting for the first client with real volume.
SCAN_CAP = 20000


# ─────────────────────────────────────────────────────────────
# Scoping — the security boundary of this whole module
# ─────────────────────────────────────────────────────────────
async def _manager_requisitions(actor: dict, company_id: str) -> list:
    """The requisition numbers a hiring manager owns.

    Mirrors hrms_candidate_service._scope_filter exactly. Duplicating the rule would let
    the two drift, and the one that drifts is the one that leaks -- so this reads the same
    source of truth (requisitions raised by this actor) and fails CLOSED: an empty list
    means an `$in: []`, which matches nothing.
    """
    rows = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id), "created_by": str(actor.get("_id"))},
        {"request_no": 1}).to_list(2000)
    return [r["request_no"] for r in rows if r.get("request_no")]


async def _client_requisitions(company_id: str, client_id: str) -> list:
    """The requisition numbers belonging to one client (Phase 11-R, Item 4).

    Fails CLOSED in the same way `_manager_requisitions` does: a client with no
    requisitions yields `$in: []`, which matches nothing rather than everything. A filter
    that silently widens when it finds nothing is how a scoping bug becomes a data leak.
    """
    rows = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id), "client_id": str(client_id)},
        {"request_no": 1}).to_list(5000)
    return [r["request_no"] for r in rows if r.get("request_no")]


async def _scope(actor: dict, company_id: str, client_id: str = None) -> dict:
    """The base `$match` for every aggregation in this module.

    A MANAGER is narrowed to their own requisitions. Everyone else with `analytics.read`
    sees the company. This is applied to EVERY query below without exception -- there is no
    "just this one summary" path that skips it.

    Phase 11-R adds an optional CLIENT narrowing. It composes with the manager narrowing by
    INTERSECTION, never replacing it: a hiring manager filtering by client sees the
    requisitions that are both theirs and that client's, so the filter can only ever narrow
    what they may see, never widen it. `company_id` remains the only tenant boundary --
    `client_id` is a reporting dimension inside one tenant, not a second security rule.
    """
    base = {"company_id": str(company_id)}
    is_manager = hrms_role(actor) == HrmsRole.MANAGER

    if not client_id:
        if not is_manager:
            return base
        return {**base,
                "request_no": {"$in": await _manager_requisitions(actor, company_id)}}

    client_reqs = await _client_requisitions(company_id, client_id)
    if not is_manager:
        return {**base, "request_no": {"$in": client_reqs}}

    own = set(await _manager_requisitions(actor, company_id))
    return {**base, "request_no": {"$in": [r for r in client_reqs if r in own]}}


def _scoped_by_request(scope: dict, field: str = "request_no") -> dict:
    """Re-express a scope for a collection whose link to a requisition uses another name.

    Every HRMS collection carries `request_no`, so in practice this is the identity -- it
    exists so a future collection that does not can be handled in one place rather than by
    quietly dropping the manager narrowing.
    """
    out = dict(scope)
    if field != "request_no" and "request_no" in out:
        out[field] = out.pop("request_no")
    return out


# ─────────────────────────────────────────────────────────────
# Date range
# ─────────────────────────────────────────────────────────────
def parse_range(date_from: Optional[str], date_to: Optional[str]) -> tuple:
    """Validate and normalise a date window. Returns (start, end) as aware datetimes.

    Defaults to the last 90 days -- a dashboard with no window is a dashboard that gets
    slower every month it is in production.
    """
    now = datetime.now(timezone.utc)
    for value, label in ((date_from, "Start date"), (date_to, "End date")):
        if value and not is_iso_date(value):
            raise HTTPException(
                status_code=422,
                detail=f"{label} must be a valid date in YYYY-MM-DD format.")

    end = (datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
           if date_to else now)
    start = (datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
             if date_from else end - timedelta(days=90))

    # End of the chosen day, so "to = today" includes everything that happened today.
    end = end.replace(hour=23, minute=59, second=59, microsecond=999999)

    if start > end:
        raise HTTPException(
            status_code=422, detail="The start date must be on or before the end date.")
    if (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Choose a range of {MAX_RANGE_DAYS} days or fewer.")
    return start, end


def _window(field: str, start: datetime, end: datetime) -> dict:
    return {field: {"$gte": start, "$lte": end}}


# ─────────────────────────────────────────────────────────────
# Effective rank
# ─────────────────────────────────────────────────────────────
async def _evidence_ranks(scope: dict) -> dict:
    """`uk` -> the rank implied by records elsewhere in the pipeline.

    Four cheap grouped reads rather than a `$lookup` chain: each is index-backed on its own
    collection, the result sets are small (one row per candidate touched), and the merge is
    plain arithmetic that a person can check by hand.
    """
    ranks = {}

    def bump(uk, rank):
        if uk and ranks.get(uk, 0) < rank:
            ranks[uk] = rank

    for coll, floor in ((COLL_ASSESSMENTS, RANK_IF_ASSESSED),
                        (COLL_INTERVIEWS, RANK_IF_INTERVIEWED)):
        rows = await get_collection(coll).find(scope, {"uk": 1}).to_list(SCAN_CAP)
        for row in rows:
            bump(row.get("uk"), floor)

    # An offer proves stage 6; an ACCEPTED offer proves stage 7. A draft proves neither --
    # it has not been issued, so nothing has happened to the candidate yet.
    offers = await get_collection(COLL_OFFERS).find(
        scope, {"uk": 1, "status": 1}).to_list(SCAN_CAP)
    for row in offers:
        status = row.get("status")
        if status == OfferStatus.DRAFT.value:
            continue
        bump(row.get("uk"),
             RANK_IF_ACCEPTED if status == OfferStatus.ACCEPTED.value else RANK_IF_OFFERED)

    return ranks


def _effective(candidate: dict, evidence: dict) -> int:
    return max(stage_rank(candidate.get("application_status")),
               evidence.get(candidate.get("uk"), 0))


# ─────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────
async def dashboard(actor: dict, company_id: str, *, date_from: str = None,
                    date_to: str = None, client_id: str = None) -> dict:
    """Headline KPIs plus the positions/vacancy summary.

    Every tile carries the `link` and `filter` the UI needs to deep-link into the screen
    that produced the number. A KPI you cannot click through to is a number the reader has
    to take on trust.
    """
    start, end = parse_range(date_from, date_to)
    scope = await _scope(actor, company_id, client_id)

    candidates = await get_collection(COLL_CANDIDATES).find(
        {**scope, **_window("applied_at", start, end)},
        # Phase 11-R: client_share and the referral fields ride along, so the new tiles are
        # computed from the SAME single read rather than adding a second pass.
        {"uk": 1, "application_status": 1, "source": 1, "applied_at": 1,
         "client_share": 1, "client_share_status": 1, "is_referral": 1,
         "referral_source": 1}).to_list(SCAN_CAP)
    evidence = await _evidence_ranks(scope)

    reqs = await get_collection(COLL_REQUISITIONS).find(
        {**scope, **_window("created_at", start, end)},
        {"request_no": 1, "vacancy": 1, "closing_status": 1,
         "approval_status": 1}).to_list(SCAN_CAP)

    interviews = await get_collection(COLL_INTERVIEWS).find(
        {**scope, **_window("scheduled_at", start, end)},
        {"status": 1, "outcome": 1, "scheduled_at": 1}).to_list(SCAN_CAP)

    offers = await get_collection(COLL_OFFERS).find(
        {**scope, **_window("created_at", start, end)},
        {"status": 1, "uk": 1, "responded_at": 1}).to_list(SCAN_CAP)

    onboardings = await get_collection(COLL_ONBOARDING).find(
        {**scope, **_window("created_at", start, end)},
        {"status": 1, "employee_id": 1}).to_list(SCAN_CAP)

    ranks = [_effective(c, evidence) for c in candidates]
    hired = sum(1 for r in ranks if r >= 7)
    in_pipeline = sum(1 for c, r in zip(candidates, ranks)
                      if c.get("application_status") not in
                      (AppStatus.REJECTED.value, AppStatus.DUPLICATE.value,
                       AppStatus.OFFER_DECLINED.value, AppStatus.EMPLOYEE_CREATED.value))

    open_reqs = [r for r in reqs if r.get("closing_status") == ReqClosing.OPEN.value]
    total_vacancy = sum(int(r.get("vacancy") or 1) for r in open_reqs)
    awaiting = sum(1 for r in reqs if r.get("approval_status") in
                   (ReqApproval.PENDING_HR.value, ReqApproval.PENDING_MD.value))

    offers_sent = sum(1 for o in offers if o.get("status") != OfferStatus.DRAFT.value)
    offers_accepted = sum(1 for o in offers if o.get("status") == OfferStatus.ACCEPTED.value)

    ttf = await _time_to_hire(scope, start, end)
    cv = _cv_metrics(candidates, ranks)

    return {
        "range": {"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d")},
        "scoped_to_own_requisitions": hrms_role(actor) == HrmsRole.MANAGER,
        # ── Phase 11-R, Item 4 ──
        "client_id": client_id,
        "cv_metrics": cv,
        "client_metrics": {
            "shared": cv["shared_with_client"],
            "shortlisted": cv["client_shortlisted"],
            "rejected": cv["client_rejected"],
            "awaiting_verdict": cv["client_awaiting"],
            # Of the CVs the client has actually ANSWERED on. Measuring against everything
            # shared would report a low rate for a client who is simply slow, which is a
            # different problem and would read as a quality one.
            "shortlist_rate": conversion(
                cv["client_shortlisted"],
                cv["client_shortlisted"] + cv["client_rejected"]),
        },
        # Populated only when no single client is selected — the comparison IS the
        # "all clients" view.
        "client_comparison": (None if client_id else
                              await _client_comparison(actor, company_id, start, end)),
        "kpis": [
            {"key": "candidates", "label": "Candidates", "value": len(candidates),
             "hint": "Applications received in this period",
             "link": "/hrms/candidates"},
            {"key": "in_pipeline", "label": "In pipeline", "value": in_pipeline,
             "hint": "Still live -- not rejected, declined or already hired",
             "link": "/hrms/candidates"},
            {"key": "open_requisitions", "label": "Open requisitions",
             "value": len(open_reqs),
             "hint": f"{total_vacancy} vacancies to fill",
             "link": "/hrms/requisitions"},
            {"key": "awaiting_approval", "label": "Awaiting approval", "value": awaiting,
             "hint": "Requisitions with HR or MD",
             "link": "/hrms/requisitions"},
            {"key": "interviews", "label": "Interviews", "value": len(interviews),
             "hint": f"{sum(1 for i in interviews if i.get('status') == InterviewStatus.COMPLETED.value)} completed",
             "link": "/hrms/interviews"},
            {"key": "offers_sent", "label": "Offers sent", "value": offers_sent,
             "hint": f"{offers_accepted} accepted",
             "link": "/hrms/offers"},
            {"key": "onboarding", "label": "Onboarding", "value": len(onboardings),
             "hint": f"{sum(1 for o in onboardings if o.get('employee_id'))} employee IDs issued",
             "link": "/hrms/onboarding"},
            {"key": "hired", "label": "Hired", "value": hired,
             "hint": "Reached an accepted offer or beyond",
             "link": "/hrms/onboarding"},
            # ── Phase 11-R, Item 4 ── every new tile carries the same link + filter the
            # existing ones do, so a reader can click through to the rows behind the number.
            {"key": "cvs_reviewed", "label": "CVs reviewed",
             "value": cv["reviewed"],
             "hint": "Reached Under Review or further",
             "link": "/hrms/candidates"},
            {"key": "cvs_selected", "label": "CVs selected", "value": cv["selected"],
             "hint": "Reached Selected or further",
             "link": "/hrms/candidates", "filter": {"status": AppStatus.SELECTED.value}},
            {"key": "cvs_rejected", "label": "CVs rejected", "value": cv["rejected"],
             "hint": "Rejected, declined, duplicated or failed",
             "link": "/hrms/candidates", "filter": {"status": AppStatus.REJECTED.value}},
            {"key": "shared_with_client", "label": "Shared with client",
             "value": cv["shared_with_client"],
             "hint": f"{cv['client_awaiting']} awaiting a verdict",
             "link": "/hrms/candidates",
             "filter": {"status": AppStatus.SHARED_WITH_CLIENT.value}},
            {"key": "client_shortlisted", "label": "Client shortlisted",
             "value": cv["client_shortlisted"],
             "hint": "The client's own shortlist",
             "link": "/hrms/candidates",
             "filter": {"status": AppStatus.CLIENT_SHORTLISTED.value}},
            {"key": "client_rejected", "label": "Client rejections",
             "value": cv["client_rejected"],
             "hint": "Rejected by the client after review",
             "link": "/hrms/candidates",
             "filter": {"status": AppStatus.CLIENT_REJECTED.value}},
            {"key": "joinings", "label": "Total joinings", "value": cv["joinings"],
             "hint": "Joined or converted to an employee record",
             "link": "/hrms/onboarding"},
        ],
        "positions": {
            "open": len(open_reqs),
            "vacancies": total_vacancy,
            "filled": sum(1 for r in reqs if r.get("closing_status") == ReqClosing.HIRED.value),
            "on_hold": sum(1 for r in reqs if r.get("closing_status") == ReqClosing.HOLD.value),
            "cancelled": sum(1 for r in reqs if r.get("closing_status") == ReqClosing.CANCEL.value),
        },
        "offer_outcomes": {
            "draft": sum(1 for o in offers if o.get("status") == OfferStatus.DRAFT.value),
            "sent": sum(1 for o in offers if o.get("status") == OfferStatus.SENT.value),
            "accepted": offers_accepted,
            "declined": sum(1 for o in offers if o.get("status") == OfferStatus.DECLINED.value),
            "revoked": sum(1 for o in offers if o.get("status") == OfferStatus.REVOKED.value),
            "acceptance_rate": conversion(
                offers_accepted,
                sum(1 for o in offers if o.get("status") in
                    (OfferStatus.ACCEPTED.value, OfferStatus.DECLINED.value))),
        },
        "onboarding_states": {
            "pre_onboarding": sum(1 for o in onboardings
                                  if o.get("status") == OnboardStatus.PRE_ONBOARDING.value),
            "onboarding": sum(1 for o in onboardings
                              if o.get("status") == OnboardStatus.ONBOARDING.value),
            "completed": sum(1 for o in onboardings
                             if o.get("status") == OnboardStatus.COMPLETED.value),
        },
        "time_to_hire": ttf,
    }


# ─────────────────────────────────────────────────────────────
# Phase 11-R, Item 4 — CV and client metrics
# ─────────────────────────────────────────────────────────────
# Every figure below is DERIVED from data that already exists after the client-share write
# path lands, and every one is computed from the ALREADY-SCOPED candidate list rather than
# by issuing its own query — so none of them can accidentally escape `_scope`.
#
# The formulas, stated once here and repeated in PHASE_11R_REPORT:
#
#   reviewed  = effective_rank >= rank(Under Review)   -- "we looked at it", by evidence,
#               not by whether somebody remembered to set a status
#   selected  = effective_rank >= rank(Selected)
#   rejected  = status in the rejection set (a STATUS, not a rank: a rejection is a
#               destination, and ranking it where they entered is what keeps the funnel
#               monotonic — see STAGE_RANK)
#   joinings  = status in {Joined, Employee Created}
#
# `reviewed` uses effective rank so a candidate who is now at Offer Accepted still counts as
# reviewed — exactly the bug the Phase 10 rank system was built to prevent.
REJECTION_STATUSES = {
    AppStatus.REJECTED.value, AppStatus.CLIENT_REJECTED.value, AppStatus.DUPLICATE.value,
    AppStatus.ASSESSMENT_FAILED.value, AppStatus.OFFER_DECLINED.value,
}
JOINED_STATUSES = {AppStatus.JOINED.value, AppStatus.EMPLOYEE_CREATED.value}


def _cv_metrics(candidates: list, ranks: list) -> dict:
    """The Item 4 headline figures, from one already-scoped pass over the candidates."""
    rank_reviewed = stage_rank(AppStatus.UNDER_REVIEW.value)
    rank_selected = stage_rank(AppStatus.SELECTED.value)

    shared = shortlisted = rejected_by_client = awaiting = 0
    for c in candidates:
        share = c.get("client_share") or {}
        # `shared_at` is the fact of the share; `client_share_status` is the denormalised
        # verdict. Reading the sub-document first means a row written before the flat field
        # existed still counts.
        if not share.get("shared_at"):
            continue
        shared += 1
        verdict = share.get("status") or c.get("client_share_status")
        if verdict == ClientShareStatus.SHORTLISTED.value:
            shortlisted += 1
        elif verdict == ClientShareStatus.REJECTED.value:
            rejected_by_client += 1
        elif verdict in (None, ClientShareStatus.PENDING.value):
            awaiting += 1

    return {
        "reviewed": sum(1 for r in ranks if r >= rank_reviewed),
        "selected": sum(1 for r in ranks if r >= rank_selected),
        "rejected": sum(1 for c in candidates
                        if c.get("application_status") in REJECTION_STATUSES),
        "shared_with_client": shared,
        "client_shortlisted": shortlisted,
        "client_rejected": rejected_by_client,
        "client_awaiting": awaiting,
        "joinings": sum(1 for c in candidates
                        if c.get("application_status") in JOINED_STATUSES),
        "referrals": sum(1 for c in candidates if c.get("is_referral")),
        "total": len(candidates),
    }


async def _client_comparison(actor: dict, company_id: str, start: datetime,
                             end: datetime) -> list:
    """One row per client, for the "all clients" view.

    Bounded work: one requisition read, one candidate read, then arithmetic. The naive
    shape — re-running `dashboard` per client — would issue six reads per client and get
    slower with every client won.
    """
    scope = await _scope(actor, company_id)
    reqs = await get_collection(COLL_REQUISITIONS).find(
        {**scope}, {"request_no": 1, "client_id": 1, "client_name": 1, "vacancy": 1,
                    "closing_status": 1}).to_list(SCAN_CAP)
    if not reqs:
        return []

    by_request = {r["request_no"]: r for r in reqs if r.get("request_no")}
    candidates = await get_collection(COLL_CANDIDATES).find(
        {**scope, **_window("applied_at", start, end)},
        {"uk": 1, "application_status": 1, "request_no": 1, "client_share": 1,
         "client_share_status": 1}).to_list(SCAN_CAP)
    evidence = await _evidence_ranks(scope)

    buckets = {}
    for r in reqs:
        # Requisitions with no client are grouped under a single explicit bucket rather
        # than dropped: "in-house" is an answer, and silently omitting those rows would make
        # the comparison's total disagree with the dashboard's.
        key = r.get("client_id") or "__none__"
        bucket = buckets.setdefault(key, {
            "client_id": r.get("client_id"),
            "client_name": r.get("client_name") or "In-house / no client",
            "requisitions": 0, "vacancies": 0, "candidates": [], "ranks": [],
        })
        bucket["requisitions"] += 1
        if r.get("closing_status") == ReqClosing.OPEN.value:
            bucket["vacancies"] += int(r.get("vacancy") or 1)

    for c in candidates:
        req = by_request.get(c.get("request_no"))
        key = (req or {}).get("client_id") or "__none__"
        bucket = buckets.get(key)
        if not bucket:
            continue
        bucket["candidates"].append(c)
        bucket["ranks"].append(_effective(c, evidence))

    rows = []
    for bucket in buckets.values():
        metrics = _cv_metrics(bucket["candidates"], bucket["ranks"])
        rows.append({
            "client_id": bucket["client_id"],
            "client_name": bucket["client_name"],
            "requisitions": bucket["requisitions"],
            "vacancies": bucket["vacancies"],
            **metrics,
        })
    rows.sort(key=lambda r: (-r["total"], r["client_name"]))
    return rows


# ─────────────────────────────────────────────────────────────
# Phase 11-R, Item 4 — position-wise CV status matrix
# ─────────────────────────────────────────────────────────────
async def positions(actor: dict, company_id: str, *, date_from: str = None,
                    date_to: str = None, client_id: str = None) -> dict:
    """Rows = requisition, columns = a count for every application status.

    Same `_scope`, same SCAN_CAP, same window validation as everything else here. Read-only.

    The status columns come from AppStatus itself rather than a hand-kept list, so a stage
    added in a later phase appears in this matrix automatically instead of silently
    vanishing from a report somebody trusts.
    """
    start, end = parse_range(date_from, date_to)
    scope = await _scope(actor, company_id, client_id)

    reqs = await get_collection(COLL_REQUISITIONS).find(
        {**scope, **_window("created_at", start, end)},
        {"request_no": 1, "designation_name": 1, "department_name": 1, "vacancy": 1,
         "urgency_level": 1, "closing_status": 1, "approval_status": 1,
         "client_id": 1, "client_name": 1, "requisition_type": 1}).to_list(SCAN_CAP)
    if not reqs:
        return {"range": {"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d")},
                "statuses": [s.value for s in AppStatus], "rows": [], "total": 0,
                "scoped_to_own_requisitions": hrms_role(actor) == HrmsRole.MANAGER}

    request_nos = [r["request_no"] for r in reqs if r.get("request_no")]
    candidates = await get_collection(COLL_CANDIDATES).find(
        {**scope, "request_no": {"$in": request_nos}},
        {"uk": 1, "application_status": 1, "request_no": 1, "client_share": 1,
         "client_share_status": 1}).to_list(SCAN_CAP)
    evidence = await _evidence_ranks(scope)

    grouped = {}
    for c in candidates:
        grouped.setdefault(c.get("request_no"), []).append(c)

    statuses = [s.value for s in AppStatus]
    rows = []
    for r in reqs:
        mine = grouped.get(r.get("request_no"), [])
        ranks = [_effective(c, evidence) for c in mine]
        counts = {s: 0 for s in statuses}
        for c in mine:
            status = c.get("application_status")
            if status in counts:
                counts[status] += 1
        rows.append({
            "request_no": r.get("request_no"),
            "designation": r.get("designation_name"),
            "department": r.get("department_name"),
            "client_name": r.get("client_name"),
            "requisition_type": r.get("requisition_type"),
            "vacancy": int(r.get("vacancy") or 1),
            "urgency": r.get("urgency_level"),
            "closing_status": r.get("closing_status"),
            "approval_status": r.get("approval_status"),
            "counts": counts,
            "totals": {"candidates": len(mine), **_cv_metrics(mine, ranks)},
        })

    rows.sort(key=lambda x: -x["totals"]["candidates"])
    return {
        "range": {"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d")},
        "statuses": statuses,
        "rows": rows,
        "total": len(rows),
        "scoped_to_own_requisitions": hrms_role(actor) == HrmsRole.MANAGER,
    }


async def _time_to_hire(scope: dict, start: datetime, end: datetime) -> dict:
    """Median and mean days from application to offer acceptance.

    Measured between two first-class timestamps -- `candidates.applied_at` and
    `offers.responded_at` -- rather than by parsing stage-change strings out of the audit
    log. The audit trail records the transitions, but its `detail` is prose written for a
    human; deriving a metric from it would make the number hostage to a wording change.

    Median AND mean, because one slow senior hire skews a mean badly and a reader deserves
    to see both rather than one number chosen for them.
    """
    accepted = await get_collection(COLL_OFFERS).find(
        {**scope, "status": OfferStatus.ACCEPTED.value,
         **_window("responded_at", start, end)},
        {"uk": 1, "responded_at": 1}).to_list(SCAN_CAP)
    if not accepted:
        return {"median_days": None, "mean_days": None, "sample": 0}

    by_uk = {row["uk"]: row["responded_at"] for row in accepted if row.get("uk")}
    applicants = await get_collection(COLL_CANDIDATES).find(
        {"uk": {"$in": list(by_uk)}}, {"uk": 1, "applied_at": 1}).to_list(SCAN_CAP)

    spans = []
    for row in applicants:
        applied, responded = row.get("applied_at"), by_uk.get(row.get("uk"))
        if not applied or not responded:
            continue
        days = (responded - applied).total_seconds() / 86400.0
        if days >= 0:                      # clock skew or a back-dated import
            spans.append(days)

    if not spans:
        return {"median_days": None, "mean_days": None, "sample": 0}
    spans.sort()
    mid = len(spans) // 2
    median = spans[mid] if len(spans) % 2 else (spans[mid - 1] + spans[mid]) / 2
    return {"median_days": round(median, 1),
            "mean_days": round(sum(spans) / len(spans), 1),
            "sample": len(spans)}


# ─────────────────────────────────────────────────────────────
# Funnel
# ─────────────────────────────────────────────────────────────
async def funnel(actor: dict, company_id: str, *, date_from: str = None,
                 date_to: str = None, client_id: str = None) -> dict:
    """The hiring funnel, by effective rank.

    Each stage counts candidates who reached AT LEAST that stage, so the series can never
    increase -- which is what makes stage-to-stage conversion meaningful.
    """
    start, end = parse_range(date_from, date_to)
    scope = await _scope(actor, company_id, client_id)

    candidates = await get_collection(COLL_CANDIDATES).find(
        {**scope, **_window("applied_at", start, end)},
        {"uk": 1, "application_status": 1}).to_list(SCAN_CAP)
    evidence = await _evidence_ranks(scope)
    ranks = [_effective(c, evidence) for c in candidates]

    stages, previous, top = [], None, None
    for key, label, min_rank in FUNNEL_STAGES:
        count = sum(1 for r in ranks if r >= min_rank)
        if top is None:
            top = count
        stages.append({
            "key": key, "label": label, "count": count,
            # Conversion from the PREVIOUS stage, and share of the top of the funnel. Both,
            # because "60% of the previous stage" and "3% of all applicants" answer
            # different questions and showing only one invites the wrong conclusion.
            "from_previous": conversion(count, previous) if previous is not None else 100.0,
            "of_total": conversion(count, top),
        })
        previous = count

    lost = {
        "rejected": sum(1 for c in candidates
                        if c.get("application_status") == AppStatus.REJECTED.value),
        "on_hold": sum(1 for c in candidates
                       if c.get("application_status") == AppStatus.ON_HOLD.value),
        "declined": sum(1 for c in candidates
                        if c.get("application_status") == AppStatus.OFFER_DECLINED.value),
        "duplicate": sum(1 for c in candidates
                         if c.get("application_status") == AppStatus.DUPLICATE.value),
    }

    return {
        "range": {"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d")},
        "total": len(candidates),
        "stages": stages,
        "lost": lost,
        # Surfaced so a reader can tell "nobody has been interviewed" from "we could not
        # interpret these rows". A silent zero would look identical.
        "unranked": sum(1 for r in ranks if r == 0),
    }


# ─────────────────────────────────────────────────────────────
# Breakdowns
# ─────────────────────────────────────────────────────────────
async def breakdown(actor: dict, company_id: str, by: str, *, date_from: str = None,
                    date_to: str = None, client_id: str = None) -> dict:
    """Group counts along one allow-listed dimension."""
    spec = BREAKDOWN_FIELDS.get(by)
    if not spec:
        raise HTTPException(status_code=422, detail="Unknown breakdown.")
    collection, field, label = spec

    start, end = parse_range(date_from, date_to)
    scope = await _scope(actor, company_id, client_id)
    date_field = "applied_at" if collection == COLL_CANDIDATES else "created_at"

    rows = await get_collection(collection).aggregate([
        {"$match": {**scope, **_window(date_field, start, end),
                    field: {"$nin": [None, ""]}}},
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": MAX_BREAKDOWN_ROWS},
    ]).to_list(MAX_BREAKDOWN_ROWS)

    total = sum(r["count"] for r in rows)
    return {
        "by": by, "label": label,
        "range": {"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d")},
        "total": total,
        "rows": [{"name": r["_id"], "count": r["count"],
                  "share": conversion(r["count"], total)} for r in rows],
        "truncated": len(rows) >= MAX_BREAKDOWN_ROWS,
    }


# ─────────────────────────────────────────────────────────────
# Detailed reports
# ─────────────────────────────────────────────────────────────
def _spec(entity: str) -> dict:
    spec = REPORT_ENTITIES.get(entity)
    if not spec:
        raise HTTPException(status_code=404, detail="Unknown report.")
    return spec


def _project(spec: dict, include_salary: bool) -> list:
    """The columns this caller may see. Compensation columns are DROPPED, not blanked, so a
    reader cannot mistake "you may not see this" for "there is no figure"."""
    return [(key, label) for key, label in spec["columns"]
            if include_salary or key not in SALARY_REPORT_COLUMNS]


def _derive(entity: str, row: dict) -> dict:
    """Fill the DERIVED report columns for one row (Phase 11-R).

    Some columns are computed rather than stored — `budget_status` most notably, which is a
    function of two figures precisely so a correction can never leave a stale flag behind
    (models.budget_status). The report projects a fixed column list off the raw document, so
    without this the column would render empty and read as "no budget recorded".

    Read-only: the row is a copy, and nothing is written back.
    """
    if entity == "requisitions":
        row = dict(row)
        row["budget_status"] = budget_status(row)
        return row
    if entity == "candidates":
        row = dict(row)
        # Prefer the sub-document, fall back to the denormalised field, so rows written at
        # any point since this phase read correctly.
        share = row.get("client_share") or {}
        row["client_share_status"] = share.get("status") or row.get("client_share_status")
        return row
    return row


def _cell(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return ""                       # never flatten a structure into a report cell
    return value


async def _query(actor: dict, company_id: str, entity: str, *, search: str = None,
                 date_from: str = None, date_to: str = None,
                 client_id: str = None) -> tuple:
    spec = _spec(entity)
    start, end = parse_range(date_from, date_to)
    scope = await _scope(actor, company_id, client_id)

    query = {**scope, **_window(spec["date_field"], start, end)}
    if search:
        term = (search or "").strip()[:80]
        if term:
            escaped = re.escape(term)
            query["$or"] = [{f: {"$regex": escaped, "$options": "i"}}
                            for f in spec["search"]]
    return spec, query, (start, end)


async def report(actor: dict, company_id: str, entity: str, *, page: int = 1,
                 page_size: int = None, search: str = None, date_from: str = None,
                 date_to: str = None, client_id: str = None) -> dict:
    """One page of a detailed report."""
    spec, query, (start, end) = await _query(
        actor, company_id, entity, search=search, date_from=date_from, date_to=date_to,
        client_id=client_id)

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 25), MAX_REPORT_PAGE_SIZE))
    columns = _project(spec, can(actor, Cap.EMPLOYEE_SALARY_READ))

    coll = get_collection(spec["collection"])
    total = await coll.count_documents(query)
    rows = await coll.find(query).sort(spec["date_field"], -1).skip(
        (page - 1) * page_size).limit(page_size).to_list(page_size)

    return {
        "entity": entity,
        "range": {"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d")},
        "columns": [{"key": k, "label": lbl} for k, lbl in columns],
        "rows": [{k: _cell(_derive(entity, r).get(k)) for k, _ in columns} for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
        "salary_visible": can(actor, Cap.EMPLOYEE_SALARY_READ),
        # Told to the UI so a hiring manager's table is labelled honestly rather than
        # reading as company-wide.
        "scoped_to_own_requisitions": hrms_role(actor) == HrmsRole.MANAGER,
    }


async def export_rows(actor: dict, company_id: str, entity: str, *, search: str = None,
                      date_from: str = None, date_to: str = None,
                      client_id: str = None) -> dict:
    """Every row for an export, up to the cap, plus an honest truncation flag."""
    spec, query, (start, end) = await _query(
        actor, company_id, entity, search=search, date_from=date_from, date_to=date_to,
        client_id=client_id)

    columns = _project(spec, can(actor, Cap.EMPLOYEE_SALARY_READ))
    coll = get_collection(spec["collection"])
    total = await coll.count_documents(query)
    # One more than the cap, so truncation is detected from the data rather than inferred
    # from a count that could have changed between the two queries.
    rows = await coll.find(query).sort(spec["date_field"], -1).to_list(MAX_EXPORT_ROWS + 1)
    truncated = len(rows) > MAX_EXPORT_ROWS
    rows = rows[:MAX_EXPORT_ROWS]

    return {
        "entity": entity,
        "columns": columns,
        "rows": [[_cell(_derive(entity, r).get(k)) for k, _ in columns] for r in rows],
        "total": total,
        "returned": len(rows),
        "truncated": truncated,
        "range": (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
    }


# ─────────────────────────────────────────────────────────────
# File rendering
# ─────────────────────────────────────────────────────────────
def render_csv(payload: dict) -> bytes:
    """UTF-8 with a BOM, so Excel opens accented names correctly instead of as mojibake."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([label for _, label in payload["columns"]])
    for row in payload["rows"]:
        writer.writerow(row)
    if payload.get("truncated"):
        writer.writerow([])
        writer.writerow([f"NOTE: truncated to the first {MAX_EXPORT_ROWS} rows of "
                         f"{payload['total']}. Narrow the date range to export the rest."])
    return buf.getvalue().encode("utf-8-sig")


def render_xlsx(payload: dict) -> bytes:
    """openpyxl is imported lazily -- an optional dependency must not cost import time on
    every request, and CSV remains available if it is absent."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Excel export is unavailable on this server. Please export CSV.")

    wb = Workbook()
    ws = wb.active
    ws.title = payload["entity"][:31].title()

    headers = [label for _, label in payload["columns"]]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"

    for row in payload["rows"]:
        ws.append(list(row))

    for i, header in enumerate(headers, start=1):
        widest = max([len(str(header))]
                     + [len(str(r[i - 1])) for r in payload["rows"][:200]] or [0])
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(
            max(widest + 2, 10), 48)

    if payload.get("truncated"):
        ws.append([])
        ws.append([f"NOTE: truncated to the first {MAX_EXPORT_ROWS} rows of "
                   f"{payload['total']}. Narrow the date range to export the rest."])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_filename(entity: str, fmt: str, date_range: tuple) -> str:
    return f"hrms_{entity}_{date_range[0]}_to_{date_range[1]}.{fmt}"
