"""Recruitment — the requisition approval chain.

The chain is a guarded state machine:

    Pending HR Review --(HR reviews)--> Pending MD Approval --(MD approves)--> Approved
           |                                    |
           +--------- Rejected <----------------+
                          |
                          +--(revise)--> Pending HR Review

Every transition goes through `apply_decision`, so an illegal jump is impossible and each step
records who took it and when. The reference project tracks the same chain across 27 numbered
`planned_N` / `actual_N` columns — a spreadsheet port it calls technical debt itself — which is
collapsed here into one `steps` list that reads as a history.

The job description is authored WITH the requisition and co-approved. There is no independent
JD approval to chase; the reference has one, and its own UI never calls it.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from app.db.mongodb import get_collection
from app.models.hrms import (
    COL_REQUISITIONS, COL_JDS, SEQ_REQUISITION,
    REQ_PENDING_HR, REQ_PENDING_MD, REQ_APPROVED, REQ_REJECTED, REQ_TRANSITIONS,
    REQ_OPEN, REQ_CLOSING_STATES, URGENCY_LEVELS,
)
from app.utils.counters import next_code

logger = logging.getLogger(__name__)


async def generate_request_no() -> str:
    """HR-REQ-YYYY-NNN, allocated atomically."""
    return await next_code(SEQ_REQUISITION, "HR-REQ", width=3)


async def generate_jd_no() -> str:
    return await next_code(SEQ_REQUISITION, "JD", width=3)


def can_transition(current: str, target: str) -> bool:
    return target in REQ_TRANSITIONS.get(current, [])


def next_state(current: str, action: str) -> str:
    """Which state an action moves to from here. Raises if the move is illegal.

    Actions rather than raw states, so the client says what it is *doing* ("approve this") and
    the server decides what that means at this point in the chain.
    """
    if action == "advance":
        # HR review moves it to MD; MD approval finalises it.
        target = REQ_PENDING_MD if current == REQ_PENDING_HR else REQ_APPROVED
    elif action == "reject":
        target = REQ_REJECTED
    elif action == "resubmit":
        target = REQ_PENDING_HR
    else:
        raise ValueError(f"Unknown action '{action}'")

    if not can_transition(current, target):
        raise ValueError(f"Cannot move a requisition from '{current}' to '{target}'.")
    return target


def step_label(from_state: str, to_state: str) -> str:
    if to_state == REQ_PENDING_MD:
        return "HR reviewed — sent for MD approval"
    if to_state == REQ_APPROVED:
        return "Approved by MD"
    if to_state == REQ_REJECTED:
        return f"Rejected at {from_state}"
    if to_state == REQ_PENDING_HR:
        return "Revised and resubmitted"
    return f"{from_state} → {to_state}"


def validate_requisition(payload: dict) -> None:
    """Reject a requisition that cannot be acted on."""
    if not (payload.get("department") or "").strip():
        raise ValueError("Department is required")
    if not (payload.get("designation") or "").strip():
        raise ValueError("Designation is required")
    vacancy = payload.get("vacancy")
    if vacancy is not None:
        try:
            v = int(vacancy)
        except (TypeError, ValueError):
            raise ValueError("Vacancy must be a whole number")
        if v < 1:
            raise ValueError("Vacancy must be at least 1")
    urgency = payload.get("urgency_level")
    if urgency and urgency not in URGENCY_LEVELS:
        raise ValueError(f"urgency_level must be one of {URGENCY_LEVELS}")


def build_step(from_state: str, to_state: str, actor: dict, remarks: str = "") -> dict:
    return {
        "from": from_state,
        "to": to_state,
        "label": step_label(from_state, to_state),
        "actor": str(actor.get("_id")) if actor else "",
        "actor_name": (actor or {}).get("full_name") or (actor or {}).get("email") or "",
        "remarks": remarks or "",
        "at": datetime.now(timezone.utc),
    }


async def apply_decision(req: dict, action: str, actor: dict, remarks: str = "",
                         salary_change: str = "") -> dict:
    """Move a requisition one step and record it. Returns the fields to $set."""
    current = req.get("approval_status") or REQ_PENDING_HR
    target = next_state(current, action)     # raises on an illegal move

    updates = {
        "approval_status": target,
        "updated_at": datetime.now(timezone.utc),
    }
    if target == REQ_PENDING_MD:
        updates["hr_reviewed_by"] = str(actor.get("_id"))
        updates["hr_reviewed_by_name"] = actor.get("full_name") or actor.get("email")
        updates["hr_reviewed_at"] = datetime.now(timezone.utc)
        updates["hr_remarks"] = remarks or ""
    elif target == REQ_APPROVED:
        updates["approved_by"] = str(actor.get("_id"))
        updates["approved_by_name"] = actor.get("full_name") or actor.get("email")
        updates["approved_at"] = datetime.now(timezone.utc)
        updates["md_remarks"] = remarks or ""
        # The MD may revise the offered CTC as a condition of approving.
        if salary_change:
            updates["salary_change"] = salary_change
            updates["offering_ctc"] = salary_change
        # Approval opens the vacancy for sourcing.
        updates["closing_status"] = req.get("closing_status") or REQ_OPEN
    elif target == REQ_REJECTED:
        updates["rejected_by"] = str(actor.get("_id"))
        updates["rejected_by_name"] = actor.get("full_name") or actor.get("email")
        updates["rejected_at"] = datetime.now(timezone.utc)
        updates["md_remarks"] = remarks or ""

    return {"updates": updates, "step": build_step(current, target, actor, remarks)}


async def upsert_jd(request_no: str, jd: dict, actor: dict) -> Optional[str]:
    """Create or update the JD attached to a requisition.

    Versioned: each rewrite bumps `version`, so a JD edited after a rejection is traceable
    rather than silently replaced.
    """
    if not jd:
        return None
    col = get_collection(COL_JDS)
    existing = await col.find_one({"request_no": request_no})
    now = datetime.now(timezone.utc)

    if existing:
        await col.update_one({"_id": existing["_id"]}, {
            "$set": {**jd, "updated_at": now,
                     "updated_by": str(actor.get("_id")) if actor else ""},
            "$inc": {"version": 1},
        })
        return existing.get("jd_no")

    jd_no = await generate_jd_no()
    await col.insert_one({
        **jd,
        "jd_no": jd_no,
        "request_no": request_no,
        "version": 1,
        "created_by": str(actor.get("_id")) if actor else "",
        "created_at": now,
        "updated_at": now,
    })
    return jd_no


async def get_jd(request_no: str) -> Optional[dict]:
    return await get_collection(COL_JDS).find_one({"request_no": request_no})


def serialize_jd(doc: dict) -> Optional[dict]:
    if not doc:
        return None
    return {
        "jdNo": doc.get("jd_no"),
        "requestNo": doc.get("request_no"),
        "title": doc.get("title") or "",
        "responsibilities": doc.get("responsibilities") or "",
        "skills": doc.get("skills") or "",
        "qualifications": doc.get("qualifications") or "",
        "experience": doc.get("experience") or "",
        "ctc": doc.get("ctc") or "",
        "location": doc.get("location") or "",
        "benefits": doc.get("benefits") or "",
        "employmentType": doc.get("employment_type") or "Full-time",
        "version": doc.get("version") or 1,
        "updatedAt": doc.get("updated_at"),
    }


def serialize_requisition(doc: dict, jd: Optional[dict] = None) -> dict:
    return {
        "id": str(doc.get("_id")),
        "requestNo": doc.get("request_no"),
        "department": doc.get("department") or "",
        "designation": doc.get("designation") or "",
        "vacancy": int(doc.get("vacancy") or 1),
        "experienceRequired": doc.get("experience_required") or "",
        "offeringCtc": doc.get("offering_ctc") or "",
        "qualification": doc.get("qualification") or "",
        "essentialSkills": doc.get("essential_skills") or "",
        "genderPreferred": doc.get("gender_preferred") or "Any",
        "workLocation": doc.get("work_location") or "",
        "urgencyLevel": doc.get("urgency_level") or "Medium",
        "requiredDate": doc.get("required_date"),
        "assignee": doc.get("assignee") or "",

        "approvalStatus": doc.get("approval_status") or REQ_PENDING_HR,
        "closingStatus": doc.get("closing_status") or REQ_OPEN,
        "salaryChange": doc.get("salary_change") or "",

        "createdBy": doc.get("created_by_name") or "",
        "createdAt": doc.get("created_at"),
        "hrReviewedBy": doc.get("hr_reviewed_by_name") or "",
        "hrRemarks": doc.get("hr_remarks") or "",
        "approvedBy": doc.get("approved_by_name") or "",
        "rejectedBy": doc.get("rejected_by_name") or "",
        "mdRemarks": doc.get("md_remarks") or "",

        # The whole chain as a readable history, replacing the reference's numbered columns.
        "steps": [
            {
                "from": s.get("from"), "to": s.get("to"), "label": s.get("label"),
                "actorName": s.get("actor_name") or "", "remarks": s.get("remarks") or "",
                "at": s.get("at"),
            }
            for s in (doc.get("steps") or [])
        ],
        "jd": serialize_jd(jd) if jd else None,
        "jdNo": doc.get("jd_no") or "",
    }
