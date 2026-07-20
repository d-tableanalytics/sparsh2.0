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
    get_definition,
    criteria_codes,
    form_kind,
    question_map,
    RatingSubmissionCreate,
    FeedbackSubmissionCreate,
    SCALE_MIN,
    SCALE_MAX,
    KIND_RATING_MATRIX,
    KIND_YESNO_CHECKLIST,
)

router = APIRouter(prefix="/forms", tags=["TPMS Forms"])

COLLECTION = "TPMS_Form_Submissions"          # rating_matrix submissions
FEEDBACK_COLLECTION = "TPMS_Feedback_Responses"  # yesno_checklist answers (one doc per company+period+md)

# TPMS Forms are an internal-staff admin tool (mirrors the /tpms/admin panel guard).
STAFF_ROLES = {"superadmin", "admin"}


def _can_write(user: dict) -> bool:
    if user.get("role") in STAFF_ROLES:
        return True
    # Also honour the granular permission flag if present.
    return bool(user.get("permissions", {}).get("forms", {}).get("create"))


def _can_read(user: dict) -> bool:
    if user.get("role") in STAFF_ROLES:
        return True
    return bool(user.get("permissions", {}).get("forms", {}).get("read", True))


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

    doc = await get_collection(COLLECTION).find_one(
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

    key = _matrix_key(form_type, payload.company_id, payload.period, payload.hod_id)
    existing = await get_collection(COLLECTION).find_one(key)
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
    set_fields["hod_name"] = payload.hod_name
    await get_collection(COLLECTION).update_one(
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

    doc = await get_collection(FEEDBACK_COLLECTION).find_one(
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

    key = _feedback_key(form_type, payload.company_id, payload.period, payload.md_id)
    existing = await get_collection(FEEDBACK_COLLECTION).find_one(key)
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
    set_fields["md_name"] = payload.md_name

    await get_collection(FEEDBACK_COLLECTION).update_one(
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
    if company_id:
        query["company_id"] = company_id
    if period:
        query["period"] = period
    if hod_id:
        query["hod_id"] = hod_id

    cursor = get_collection(COLLECTION).find(query).sort("created_at", -1)
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

    doc = await get_collection(COLLECTION).find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Submission not found")
    return {"submission": _serialize(doc)}
