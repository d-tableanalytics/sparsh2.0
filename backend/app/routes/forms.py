"""
TPMS ▸ Forms sub-module — API routes.

Endpoints (all mounted under /api):
  GET  /forms/definitions                         list all form definitions
  GET  /forms/{form_type}/definition              one form's criteria/scale
  GET  /forms/members                             candidate team members to rate
  POST /forms/{form_type}/submissions             save a submission
  GET  /forms/{form_type}/submissions             list submissions (filterable)
  GET  /forms/submissions/{submission_id}         fetch one submission

Data is stored atomically per (company, period, hod, member, criterion) so that
future Success Measure calculations can aggregate freely. No Success Measure
computation is performed here — this module only captures and serves the data.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId

from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.models.forms import (
    FORM_DEFINITIONS,
    FORM_COLLECTIONS,
    ACTIVITY_CATALOGUE,
    ACTIVITY_FORM_MAP,
    submission_collection,
    get_definition,
    criteria_codes,
    form_kind,
    form_audience,
    question_map,
    RatingSubmissionCreate,
    FeedbackSubmissionCreate,
    SCALE_MIN,
    SCALE_MAX,
    KIND_RATING_MATRIX,
    KIND_YESNO_CHECKLIST,
)

router = APIRouter(prefix="/forms", tags=["TPMS Forms"])

# Each form is stored in its own collection ("table") — see FORM_COLLECTIONS in
# app.models.forms. Resolve the collection for a form_type via submission_collection().

# Internal staff (the /tpms/admin panel) may submit on behalf of anyone.
STAFF_ROLES = {"superadmin", "admin"}
# Client-side users fill TPMS forms for themselves (HODs rate their team; everyone
# submits Culture + Implementation Feedback). Their writes are self-scoped below.
CLIENT_ROLES = {"clientadmin", "clientuser"}


def _is_staff(user: dict) -> bool:
    return user.get("role") in STAFF_ROLES


def _is_client(user: dict) -> bool:
    return user.get("role") in CLIENT_ROLES


def _self_id(user: dict) -> str:
    """The identity a client-side user submits under. Standardised to the Mongo _id
    (also used to exclude self from the team roster and to scope reads/writes)."""
    return str(user.get("_id"))


def _can_write(user: dict) -> bool:
    if _is_staff(user):
        return True
    if _is_client(user):
        return True
    # Also honour the granular permission flag if present.
    return bool(user.get("permissions", {}).get("forms", {}).get("create"))


def _can_read(user: dict) -> bool:
    if _is_staff(user) or _is_client(user):
        return True
    return bool(user.get("permissions", {}).get("forms", {}).get("read", True))


def _is_hod(user: dict) -> bool:
    return (user.get("department") or "").strip().lower() == "hod"


def _enforce_client_scope(user: dict, company_id: str, respondent_id: str, form_type: str) -> None:
    """Defence-in-depth for client-side submissions. Staff bypass all of this.
    A client user may only write:
      • within their own company, and
      • under their own identity (as the HOD/respondent),
      • and 'hod'-audience forms only if their department is HOD.
    """
    if _is_staff(user):
        return
    if not _is_client(user):
        return  # other roles fall through to the permission-flag path
    if company_id != (user.get("company_id") or ""):
        raise HTTPException(status_code=403, detail="You can only submit forms for your own company.")
    if respondent_id != _self_id(user):
        raise HTTPException(status_code=403, detail="You can only submit your own form.")
    if form_audience(form_type) == "hod" and not _is_hod(user):
        raise HTTPException(status_code=403, detail="Only an HOD can submit this form.")


def _require_form_type(form_type: str) -> dict:
    definition = get_definition(form_type)
    if not definition:
        raise HTTPException(status_code=404, detail=f"Unknown form type '{form_type}'")
    return definition


def _serialize(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc


def _user_display_name(user: dict) -> str:
    return (
        user.get("full_name")
        or " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip()
        or user.get("name")
        or user.get("email")
        or "Unknown"
    )


# ─────────────────────────────────────────────────────────────
# Form definitions (criteria registry)
# ─────────────────────────────────────────────────────────────
@router.get("/definitions")
async def list_definitions(current_user: dict = Depends(get_current_user)):
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    return {"definitions": list(FORM_DEFINITIONS.values())}


# ─────────────────────────────────────────────────────────────
# Candidate members to rate (sourced from existing users)
# ─────────────────────────────────────────────────────────────
@router.get("/members")
async def list_members(
    company_id: str = Query(..., description="Company to load team members for"),
    hod_id: Optional[str] = Query(None, description="Exclude this HOD from the member list"),
    current_user: dict = Depends(get_current_user),
):
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    # Client-side users may only load their own company's roster.
    if _is_client(current_user):
        company_id = current_user.get("company_id") or ""
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")

    query = {"company_id": company_id, "is_active": {"$ne": False}}
    staff = await get_collection("staff").find(query).to_list(1000)
    learners = await get_collection("learners").find(query).to_list(1000)

    members = []
    for u in staff + learners:
        uid = str(u["_id"])
        emp = u.get("employee_id") or u.get("emp_id") or u.get("emp_code")
        if hod_id and hod_id in (uid, emp):
            continue
        members.append({
            "member_id": uid,
            "employee_id": emp,
            "member_name": _user_display_name(u),
            "designation": u.get("designation"),
            "department": u.get("department"),
            "role": u.get("role"),
        })
    members.sort(key=lambda m: (m.get("member_name") or "").lower())
    return {"members": members}


# ─────────────────────────────────────────────────────────────
# Submissions
# ─────────────────────────────────────────────────────────────
def _matrix_key(form_type: str, company_id: str, period: str, hod_id: str) -> dict:
    return {"form_type": form_type, "company_id": company_id, "period": period, "hod_id": hod_id}


@router.get("/{form_type}/ratings")
async def get_ratings(
    form_type: str,
    company_id: str = Query(...),
    period: str = Query(...),
    hod_id: str = Query(...),
    current_user: dict = Depends(get_current_user),
):
    """Existing ratings for (company, period, HOD) so the UI can lock saved cells."""
    definition = _require_form_type(form_type)
    if definition.get("kind") != KIND_RATING_MATRIX:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not a rating form")
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Client-side users are scoped to their own company + identity.
    if _is_client(current_user):
        company_id = current_user.get("company_id") or ""
        hod_id = _self_id(current_user)

    doc = await get_collection(submission_collection(form_type)).find_one(
        _matrix_key(form_type, company_id.strip(), period.strip(), hod_id.strip())
    )
    ratings = (doc or {}).get("ratings", {})           # { code: { member_id: {rating, ...} } }
    count = sum(len(v) for v in ratings.values())
    return {
        "submitted": count > 0,
        "submitted_on": (doc or {}).get("created_at"),
        "ratings": ratings,
        "count": count,
    }


@router.post("/{form_type}/ratings")
async def submit_ratings(
    form_type: str,
    payload: RatingSubmissionCreate,
    current_user: dict = Depends(get_current_user),
):
    """Cell-level partial submit: append only (criterion × member) cells not already saved."""
    definition = _require_form_type(form_type)
    if definition.get("kind") != KIND_RATING_MATRIX:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not a rating form; use the feedback endpoint")
    if not _can_write(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to submit forms")
    if not definition.get("available"):
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not yet available for submission")

    valid_codes = set(criteria_codes(form_type))
    if not valid_codes:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' has no criteria configured")

    # Client-side users submit for themselves in their own company — the payload's
    # company_id/hod_id are ignored in favour of the authenticated identity.
    company_id = payload.company_id
    hod_id = payload.hod_id
    hod_name = payload.hod_name
    if _is_client(current_user):
        company_id = current_user.get("company_id") or ""
        hod_id = _self_id(current_user)
        hod_name = _user_display_name(current_user)
    _enforce_client_scope(current_user, company_id, hod_id, form_type)

    key = _matrix_key(form_type, company_id, payload.period, hod_id)
    existing = await get_collection(submission_collection(form_type)).find_one(key)
    saved = (existing or {}).get("ratings", {})

    now = datetime.utcnow()
    who = str(current_user.get("_id"))
    who_name = _user_display_name(current_user)

    set_fields: Dict[str, dict] = {}
    added = 0
    for cell in payload.ratings:
        if cell.criterion_code not in valid_codes:
            raise HTTPException(status_code=400, detail=f"Unknown criterion '{cell.criterion_code}'")
        # Skip a cell that's already on file (append-only, no duplicates).
        if saved.get(cell.criterion_code, {}).get(cell.member_id) is not None:
            continue
        set_fields[f"ratings.{cell.criterion_code}.{cell.member_id}"] = {
            "rating": cell.rating,
            "member_name": cell.member_name,
            "designation": cell.designation,
            "employee_id": cell.employee_id,
            "criterion": cell.criterion_code,
            "rated_at": now,
            "rated_by": who,
            "rated_by_name": who_name,
        }
        added += 1

    if not added:
        raise HTTPException(
            status_code=400,
            detail="Nothing new to save — the selected cells were already submitted.",
        )

    set_fields["updated_at"] = now
    set_fields["hod_name"] = hod_name
    await get_collection(submission_collection(form_type)).update_one(
        key,
        {
            "$set": set_fields,
            "$setOnInsert": {
                **key,
                "kind": KIND_RATING_MATRIX,
                "criteria_codes": criteria_codes(form_type),
                "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
                "created_at": now,
                "created_by": who,
                "created_by_name": who_name,
            },
        },
        upsert=True,
    )

    total_saved = sum(len(v) for v in saved.values()) + added
    return {
        "message": f"{definition['title']}: {added} rating(s) saved",
        "count": added,
        "total_saved": total_saved,
    }


# ─────────────────────────────────────────────────────────────
# yesno_checklist (Implementation Feedback) — partial submission
# ─────────────────────────────────────────────────────────────
def _feedback_key(form_type: str, company_id: str, period: str, md_id: str) -> dict:
    return {"form_type": form_type, "company_id": company_id, "period": period, "md_id": md_id}


@router.get("/{form_type}/feedback")
async def get_feedback(
    form_type: str,
    company_id: str = Query(...),
    period: str = Query(...),
    md_id: str = Query(...),
    current_user: dict = Depends(get_current_user),
):
    """Existing answers for (company, period, MD) so the UI can lock what's already saved."""
    definition = _require_form_type(form_type)
    if definition.get("kind") != KIND_YESNO_CHECKLIST:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not a feedback form")
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Client-side users are scoped to their own company + identity.
    if _is_client(current_user):
        company_id = current_user.get("company_id") or ""
        md_id = _self_id(current_user)

    doc = await get_collection(submission_collection(form_type)).find_one(
        _feedback_key(form_type, company_id.strip(), period.strip(), md_id.strip())
    )
    answers = (doc or {}).get("answers", {})
    return {
        "submitted": bool(answers),
        "submitted_on": (doc or {}).get("created_at"),
        "answers": answers,          # { question_id: {question, checked, remark, ...} }
        "count": len(answers),
    }


@router.post("/{form_type}/feedback")
async def submit_feedback(
    form_type: str,
    payload: FeedbackSubmissionCreate,
    current_user: dict = Depends(get_current_user),
):
    """Slot-by-slot submit: append only questions not already saved for this (company, period, MD)."""
    definition = _require_form_type(form_type)
    if definition.get("kind") != KIND_YESNO_CHECKLIST:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not a feedback form")
    if not _can_write(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to submit forms")
    if not definition.get("available"):
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not yet available for submission")

    qmap = question_map(form_type)
    if not qmap:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' has no questions configured")

    # Client-side users submit their own response in their own company.
    company_id = payload.company_id
    md_id = payload.md_id
    md_name = payload.md_name
    if _is_client(current_user):
        company_id = current_user.get("company_id") or ""
        md_id = _self_id(current_user)
        md_name = _user_display_name(current_user)
    _enforce_client_scope(current_user, company_id, md_id, form_type)

    key = _feedback_key(form_type, company_id, payload.period, md_id)
    existing = await get_collection(submission_collection(form_type)).find_one(key)
    already = set((existing or {}).get("answers", {}).keys())

    now = datetime.utcnow()
    who = str(current_user.get("_id"))
    who_name = _user_display_name(current_user)

    new_answers: Dict[str, dict] = {}
    skipped_unknown, skipped_existing = [], []
    for a in payload.answers:
        qid = a.question_id
        if qid not in qmap:
            skipped_unknown.append(qid)
            continue
        if qid in already:
            skipped_existing.append(qid)
            continue
        # Only persist a slot that was actually answered (ticked) or has a remark.
        if not a.checked and not (a.remark or "").strip():
            continue
        new_answers[qid] = {
            "question": a.question or qmap[qid].get("title", ""),
            "checked": bool(a.checked),
            "answer": "Yes" if a.checked else "No",
            "remark": (a.remark or "").strip(),
            "answered_at": now,
            "answered_by": who,
            "answered_by_name": who_name,
        }

    if not new_answers:
        raise HTTPException(
            status_code=400,
            detail="Nothing new to save — tick a box or add a remark on an unanswered question.",
        )

    set_fields = {f"answers.{qid}": val for qid, val in new_answers.items()}
    set_fields["updated_at"] = now
    set_fields["md_name"] = md_name

    await get_collection(submission_collection(form_type)).update_one(
        key,
        {
            "$set": set_fields,
            "$setOnInsert": {
                **key,
                "kind": KIND_YESNO_CHECKLIST,
                "created_at": now,
                "created_by": who,
                "created_by_name": who_name,
            },
        },
        upsert=True,
    )

    return {
        "message": f"{definition['title']}: {len(new_answers)} answer(s) saved",
        "count": len(new_answers),
        "skipped_already_saved": skipped_existing,
        "total_saved": len(already) + len(new_answers),
        "total_questions": len(qmap),
    }


@router.get("/{form_type}/submissions")
async def list_submissions(
    form_type: str,
    company_id: Optional[str] = None,
    period: Optional[str] = None,
    hod_id: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    _require_form_type(form_type)
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    query: dict = {"form_type": form_type}
    if _is_client(current_user):
        # A client may only list their own submissions in their own company.
        query["company_id"] = current_user.get("company_id") or ""
        if form_kind(form_type) == KIND_YESNO_CHECKLIST:
            query["md_id"] = _self_id(current_user)
        else:
            query["hod_id"] = _self_id(current_user)
        if period:
            query["period"] = period
    else:
        if company_id:
            query["company_id"] = company_id
        if period:
            query["period"] = period
        if hod_id:
            query["hod_id"] = hod_id

    cursor = get_collection(submission_collection(form_type)).find(query).sort("created_at", -1)
    docs = await cursor.to_list(length=limit)
    return {"submissions": [_serialize(d) for d in docs]}


@router.get("/submissions/{submission_id}")
async def get_submission(submission_id: str, current_user: dict = Depends(get_current_user)):
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        oid = ObjectId(submission_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid submission id")

    # Submissions live in one collection per form — search each until found.
    doc = None
    for coll_name in FORM_COLLECTIONS.values():
        doc = await get_collection(coll_name).find_one({"_id": oid})
        if doc:
            break
    if not doc:
        raise HTTPException(status_code=404, detail="Submission not found")

    # A client may only fetch their own submission.
    if _is_client(current_user):
        if doc.get("company_id") != (current_user.get("company_id") or ""):
            raise HTTPException(status_code=403, detail="Not authorized")
        respondent = doc.get("md_id") if doc.get("kind") == KIND_YESNO_CHECKLIST else doc.get("hod_id")
        if respondent != _self_id(current_user):
            raise HTTPException(status_code=403, detail="Not authorized")

    return {"submission": _serialize(doc)}


# ─────────────────────────────────────────────────────────────
# Client dashboard — Success-Measure scorecard for one company + month.
#
# Data sources (all scoped to the client's own company):
#   • Scheduled activities → calendar events carrying an `activity` label (created by
#     the Schedule Calendar modal). These drive Planned / Completed / Actual Impl %.
#   • TPMS form submissions → the Accountability/Ownership/Culture/Implementation tables
#     drive Actual Score % for the three form-backed activities.
# Success Measure math is deliberately simple and transparent (documented inline) — it
# aggregates only the data that exists; everything else renders as "no data" (— / 0%).
# ─────────────────────────────────────────────────────────────
_CAL_COLLECTIONS = ["STAFF_CALENDER", "LEARNER_CALENDER", "calendar_events"]


def _month_parts(month: str):
    """Accept 'YYYY-MM' and return (year, month_num, [period tokens forms may use])."""
    try:
        year, month_num = int(month[:4]), int(month[5:7])
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="month must be 'YYYY-MM'")
    first = datetime(year, month_num, 1)
    mon_short = first.strftime("%b").lower()   # jul
    mon_full = first.strftime("%B").lower()    # july
    yy = str(year)[-2:]
    tokens = list({f"{mon_short}{yy}", f"{mon_full}{yy}", month, f"{mon_short}-{yy}"})
    return year, month_num, tokens


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _rating_score_pct(docs):
    total = count = 0
    for d in docs:
        for _code, members in (d.get("ratings") or {}).items():
            for _mid, cell in (members or {}).items():
                r = cell.get("rating")
                if isinstance(r, (int, float)):
                    total += r
                    count += 1
    if not count:
        return None
    return round(total / count / SCALE_MAX * 100)


def _feedback_score_pct(docs):
    yes = count = 0
    for d in docs:
        for _qid, a in (d.get("answers") or {}).items():
            count += 1
            if a.get("checked"):
                yes += 1
    if not count:
        return None
    return round(yes / count * 100)


async def _activity_score_pct(activity: str, company_id: str, period_tokens: list):
    form_types = ACTIVITY_FORM_MAP.get(activity)
    if not form_types:
        return None
    pcts = []
    for ft in form_types:
        docs = await get_collection(submission_collection(ft)).find(
            {"company_id": company_id, "period": {"$in": period_tokens}}
        ).to_list(1000)
        pct = _feedback_score_pct(docs) if form_kind(ft) == KIND_YESNO_CHECKLIST else _rating_score_pct(docs)
        if pct is not None:
            pcts.append(pct)
    if not pcts:
        return None
    return round(sum(pcts) / len(pcts))


def _status_for(achievement, has_data):
    if not has_data:
        return "Not Met"
    if achievement >= 100:
        return "Met"
    if achievement > 0:
        return "Partial"
    return "Not Met"


@router.get("/dashboard")
async def client_dashboard(
    month: str = Query(..., description="Month to report on, 'YYYY-MM'"),
    company_id: Optional[str] = Query(None, description="Staff only — target company"),
    current_user: dict = Depends(get_current_user),
):
    if not _can_read(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Client-side users are locked to their own company; staff may pass company_id.
    if _is_client(current_user):
        company_id = current_user.get("company_id") or ""
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")

    year, month_num, period_tokens = _month_parts(month)

    # Company name.
    company = None
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
    except Exception:
        company = None
    company_name = (company or {}).get("name") or company_id
    om_name = (company or {}).get("owner")

    # Scheduled activities for this company + month (events carrying an `activity`).
    scheduled = []
    for coll in _CAL_COLLECTIONS:
        docs = await get_collection(coll).find(
            {"company_id": company_id, "activity": {"$nin": [None, ""]}}
        ).to_list(3000)
        scheduled.extend(docs)
    month_events = []
    for e in scheduled:
        dt = _parse_dt(e.get("start"))
        if dt and dt.year == year and dt.month == month_num:
            month_events.append(e)

    by_activity: dict = {}
    for e in month_events:
        by_activity.setdefault(e.get("activity"), []).append(e)

    # Build the scorecard over the full activity catalogue.
    scorecard = []
    met = partial = not_met = 0
    score_values = []
    for activity in ACTIVITY_CATALOGUE:
        evs = by_activity.get(activity, [])
        planned = len(evs)
        completed = len([e for e in evs if e.get("status") == "completed"])
        actual_impl = round(completed / planned * 100) if planned else None
        actual_score = await _activity_score_pct(activity, company_id, period_tokens)

        vals = [v for v in (actual_impl, actual_score) if v is not None]
        has_data = bool(vals)
        achievement = round(sum(vals) / len(vals)) if vals else 0
        status = _status_for(achievement, has_data)

        if status == "Met":
            met += 1
        elif status == "Partial":
            partial += 1
        else:
            not_met += 1
        if actual_score is not None:
            score_values.append(actual_score)

        scorecard.append({
            "activity": activity,
            "impl_target_pct": 100,
            "actual_impl_pct": actual_impl,
            "score_target_pct": 100,
            "actual_score_pct": actual_score,
            "achievement_pct": achievement,
            "progress_pct": achievement,
            "status": status,
            "planned": planned,
            "completed": completed,
        })

    # Month-level summary cards (across all scheduled activities).
    total_planned = len(month_events)
    total_completed = len([e for e in month_events if e.get("status") == "completed"])
    completion_pct = round(total_completed / total_planned * 100) if total_planned else 0

    delays = []
    for e in month_events:
        if e.get("status") != "completed":
            continue
        start_dt = _parse_dt(e.get("start"))
        done_dt = _parse_dt(e.get("completed_at") or e.get("updated_at"))
        if start_dt and done_dt:
            delays.append(max(0, (done_dt.date() - start_dt.date()).days))
    avg_delay = round(sum(delays) / len(delays), 1) if delays else 0

    overall_status = "On Track" if completion_pct >= 80 else ("At Risk" if completion_pct >= 50 else "Critical")
    avg_score = round(sum(score_values) / len(score_values)) if score_values else 0

    return {
        "company": {
            "id": company_id,
            "name": company_name,
            "om_name": om_name,
            "completion_pct": completion_pct,
            "status": overall_status,
        },
        "month": month,
        "cards": {
            "planned": total_planned,
            "completed": total_completed,
            "completion_pct": completion_pct,
            "avg_delay_days": avg_delay,
        },
        "scorecard": scorecard,
        "stats": {
            "met": met,
            "partial": partial,
            "not_met": not_met,
            "total_activities": len(ACTIVITY_CATALOGUE),
            "avg_score_pct": avg_score,
            "target_score_pct": 100,
        },
    }
