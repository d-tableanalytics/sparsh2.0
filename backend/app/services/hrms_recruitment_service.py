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
    COL_REQUISITIONS, COL_JDS, COL_ORG_MASTERS, COL_EMPLOYEES, SEQ_REQUISITION,
    REQ_PENDING_HR, REQ_PENDING_HOD, REQ_PENDING_MD, REQ_APPROVED, REQ_REJECTED,
    REQ_TRANSITIONS, REQ_OPEN, REQ_CLOSING_STATES, URGENCY_LEVELS,
    ORG_KIND_DESIGNATION, ORG_KIND_DEPARTMENT, EXITED_STATUSES, VACANCY_TYPES, VACANCY_NEW,
)
from app.utils.counters import next_code

logger = logging.getLogger(__name__)


async def generate_request_no() -> str:
    """HR-REQ-YYYY-NNN, allocated atomically."""
    return await next_code(SEQ_REQUISITION, "HR-REQ", width=3)


async def generate_jd_no() -> str:
    return await next_code(SEQ_REQUISITION, "JD", width=3)


async def resolve_client(company_id: Optional[str]) -> tuple:
    """(client_company_id, client_company_name) for a requisition.

    Returns ("", "") for a blank id — an unset client is legitimate and means the vacancy is
    one of Sparsh's own internal hires. A non-blank id that matches no company is an error
    rather than a silent downgrade to internal, because that would quietly misfile the
    requisition and skew the client-wise analytics it feeds.
    """
    cid = (company_id or "").strip()
    if not cid:
        return "", ""
    from bson import ObjectId
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(cid)}, {"name": 1})
    except Exception:
        raise ValueError("Invalid client company")
    if not company:
        raise ValueError("Client company not found")
    return cid, company.get("name") or ""


def can_transition(current: str, target: str) -> bool:
    return target in REQ_TRANSITIONS.get(current, [])


async def compute_sanction(department: str, designation: str, vacancy: int) -> dict:
    """Sanction vs actual for a role, as of now.

    `sanctioned` is the approved headcount recorded on the designation org master; `actual` is
    how many non-exited employees currently hold that department/designation pair. A request
    that would push actual past sanctioned is over-sanction and escalates via the HOD.

    No sanction on record (0/absent) counts as over-sanction: the review document wants an
    unsanctioned vacancy escalated, and "nobody has recorded a sanction" is the clearest case
    of unsanctioned there is.
    """
    dept = (department or "").strip()
    desig = (designation or "").strip()

    master = await get_collection(COL_ORG_MASTERS).find_one({
        "kind": ORG_KIND_DESIGNATION, "name": desig, "active": True,
    })
    sanctioned = int((master or {}).get("sanctioned_count") or 0)

    actual = await get_collection(COL_EMPLOYEES).count_documents({
        "designation": desig,
        "department": dept,
        "status": {"$nin": EXITED_STATUSES},
    })

    requested = max(int(vacancy or 1), 1)
    return {
        "sanctioned_headcount": sanctioned,
        "actual_headcount": actual,
        "over_sanction": (actual + requested) > sanctioned,
    }


def budget_mismatch(req: dict) -> Optional[str]:
    """Why the budget needs attention, or None when the two sides agree.

    Returned as human copy because it goes straight into the notification body and onto the
    requisition for the UI to show.
    """
    mgmt = (req.get("budget_sanctioned_by_management") or {}).get("amount")
    hod = (req.get("budget_approved_by_hod") or {}).get("amount")

    missing = [label for label, val in
               (("Management sanction", mgmt), ("HOD approval", hod)) if val is None]
    if missing:
        return f"{' and '.join(missing)} still pending."
    if float(mgmt) != float(hod):
        return (f"Budget mismatch: management sanctioned {mgmt:,.0f} "
                f"but HOD approved {hod:,.0f}.")
    return None


async def notify_budget_issue(req: dict, issue: str, actor: dict) -> None:
    """Tell the stakeholders a requisition's budget needs attention.

    Recipients are the raiser, the department's HOD and the MD tier — the three parties the
    review document names. Best-effort by design: a notification failure must never stop a
    requisition from moving, so everything here is caught and logged.

    In-app always fires; email only when an Active template exists for the slug, matching the
    rule task_notifications already follows so this module can't spam a workspace that has not
    configured one.
    """
    try:
        from app.services.notification_service import (
            create_in_app_notification, send_notification_from_template, active_user_template,
        )
        # calendar_utils' version, not routes/user.py's — that one returns a (user, collection)
        # tuple, and this is the same helper task_notifications uses.
        from app.utils.calendar_utils import find_user_by_id

        request_no = req.get("request_no") or ""
        targets = set()
        if req.get("created_by"):
            targets.add(str(req["created_by"]))

        # The HOD is the head recorded on the department org master.
        dept = await get_collection(COL_ORG_MASTERS).find_one({
            "kind": ORG_KIND_DEPARTMENT, "name": req.get("department"), "active": True,
        })
        if (dept or {}).get("head"):
            targets.add(str(dept["head"]))

        # MD tier — the same admin roles _can_md_approve recognises.
        async for u in get_collection("staff").find(
                {"role": {"$in": ["superadmin", "admin"]}, "is_active": {"$ne": False}},
                {"_id": 1}):
            targets.add(str(u["_id"]))

        targets.discard(str(actor.get("_id") or ""))    # no need to tell the person who acted

        context = {
            "request_no": request_no,
            "designation": req.get("designation") or "",
            "department": req.get("department") or "",
            "issue": issue,
            "actor_name": actor.get("full_name") or actor.get("email") or "",
        }
        for uid in targets:
            try:
                await create_in_app_notification(
                    user_id=uid,
                    title="Requisition budget needs attention",
                    message=f"{request_no}: {issue}",
                    type="warning",
                    meta={"request_no": request_no, "module": "hrms_recruitment"},
                )
                user_obj = await find_user_by_id(uid)
                if not user_obj:
                    continue
                if not await active_user_template("hrms_budget_issue_email", None):
                    continue
                await send_notification_from_template(
                    user_obj, "hrms_budget_issue", context, "email", "staff")
            except Exception as e:
                logger.warning("Budget notification to %s failed: %s", uid, e)
    except Exception as e:
        logger.error("Budget notification for %s failed: %s", req.get("request_no"), e)


def next_state(current: str, action: str, req: Optional[dict] = None) -> str:
    """Which state an action moves to from here. Raises if the move is illegal.

    Actions rather than raw states, so the client says what it is *doing* ("approve this") and
    the server decides what that means at this point in the chain — including whether HR review
    hands off to the HOD or straight to the MD, which depends on the sanction position stored
    on the requisition rather than on anything the client sends.
    """
    if action == "advance":
        if current == REQ_PENDING_HR:
            # Over-sanction inserts the HOD step; MD still follows either way.
            target = REQ_PENDING_HOD if (req or {}).get("over_sanction") else REQ_PENDING_MD
        elif current == REQ_PENDING_HOD:
            target = REQ_PENDING_MD
        else:
            target = REQ_APPROVED
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
    if to_state == REQ_PENDING_HOD:
        return "HR reviewed — escalated to HOD (over sanctioned headcount)"
    if to_state == REQ_PENDING_MD:
        return ("HOD approved — sent for MD approval" if from_state == REQ_PENDING_HOD
                else "HR reviewed — sent for MD approval")
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
    vtype = payload.get("vacancy_type")
    if vtype and vtype not in VACANCY_TYPES:
        raise ValueError(f"vacancy_type must be one of {VACANCY_TYPES}")


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
    target = next_state(current, action, req)     # raises on an illegal move

    now = datetime.now(timezone.utc)
    updates = {
        "approval_status": target,
        "updated_at": now,
    }
    # Pending MD Approval is reachable from two places now, so who just acted depends on where
    # the requisition came FROM, not only on where it is going.
    if current == REQ_PENDING_HOD and target == REQ_PENDING_MD:
        updates["hod_approved_by"] = str(actor.get("_id"))
        updates["hod_approved_by_name"] = actor.get("full_name") or actor.get("email")
        updates["hod_approved_at"] = now
        updates["hod_remarks"] = remarks or ""
    elif target in (REQ_PENDING_HOD, REQ_PENDING_MD):
        updates["hr_reviewed_by"] = str(actor.get("_id"))
        updates["hr_reviewed_by_name"] = actor.get("full_name") or actor.get("email")
        updates["hr_reviewed_at"] = now
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

        # Absent on every requisition raised before client linkage existed — those are
        # Sparsh's own internal hires and the UI renders them as such.
        "clientCompanyId": doc.get("client_company_id") or "",
        "clientCompanyName": doc.get("client_company_name") or "",

        # Manpower requisition: why the seat exists and where it sits against sanction.
        "vacancyType": doc.get("vacancy_type") or VACANCY_NEW,
        "replacementFor": doc.get("replacement_for") or "",
        "sanctionedHeadcount": int(doc.get("sanctioned_headcount") or 0),
        "actualHeadcount": int(doc.get("actual_headcount") or 0),
        "overSanction": bool(doc.get("over_sanction")),
        "budgetSanctionedByManagement": doc.get("budget_sanctioned_by_management") or None,
        "budgetApprovedByHod": doc.get("budget_approved_by_hod") or None,
        # Recomputed on read so an edited budget reflects immediately, rather than showing a
        # stale verdict stored at raise time.
        "budgetIssue": budget_mismatch(doc) or "",
        "hodApprovedBy": doc.get("hod_approved_by_name") or "",
        "hodRemarks": doc.get("hod_remarks") or "",

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
