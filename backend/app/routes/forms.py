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
    FormSubmissionCreate,
    SCALE_MIN,
    SCALE_MAX,
)

router = APIRouter(prefix="/forms", tags=["TPMS Forms"])

COLLECTION = "TPMS_Form_Submissions"

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
@router.post("/{form_type}/submissions")
async def create_submission(
    form_type: str,
    payload: FormSubmissionCreate,
    current_user: dict = Depends(get_current_user),
):
    definition = _require_form_type(form_type)
    if not _can_write(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to submit forms")
    if not definition.get("available"):
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' is not yet available for submission")

    valid_codes = set(criteria_codes(form_type))
    if not valid_codes:
        raise HTTPException(status_code=400, detail=f"Form '{form_type}' has no criteria configured")

    members_out: List[dict] = []
    for member in payload.members:
        # Every required criterion must be present, and no stray codes allowed.
        missing = valid_codes - set(member.scores.keys())
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Missing scores for {sorted(missing)} for member '{member.member_name}'",
            )
        unknown = set(member.scores.keys()) - valid_codes
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown criteria {sorted(unknown)} for member '{member.member_name}'",
            )

        ordered_scores = {code: int(member.scores[code]) for code in criteria_codes(form_type)}
        total = sum(ordered_scores.values())
        max_total = len(valid_codes) * SCALE_MAX
        members_out.append({
            "member_id": member.member_id,
            "employee_id": member.employee_id,
            "member_name": member.member_name,
            "designation": member.designation,
            "department": member.department,
            "scores": ordered_scores,
            # Convenience aggregates (plain arithmetic of the stored answers — NOT a
            # Success Measure). Raw `scores` remain the authoritative source.
            "total": total,
            "max_total": max_total,
            "average": round(total / len(valid_codes), 2) if valid_codes else 0,
        })

    now = datetime.utcnow()
    doc = {
        "form_type": form_type,
        "company_id": payload.company_id,
        "period": payload.period,
        "hod_id": payload.hod_id,
        "hod_name": payload.hod_name,
        "members": members_out,
        "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
        "criteria_codes": criteria_codes(form_type),
        "submitted_by": str(current_user.get("_id")),
        "submitted_by_name": _user_display_name(current_user),
        "source": "web",
        "created_at": now,
        "updated_at": now,
    }
    result = await get_collection(COLLECTION).insert_one(doc)
    return {
        "message": f"{definition['title']} submitted successfully",
        "submission": _serialize({**doc, "_id": result.inserted_id}),
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
