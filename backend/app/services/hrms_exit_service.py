"""HRMS > Exit Management (BA/Functional Design v2.2, §7.18, §22.2, §7.21).

Resignation submitted -> notice calculated from status + designation level -> HR/manager
records acceptance, with an approval gate on any waiver (BR-016) -> a Handover Plan and
departmental Clearance/Asset-Return/Access-Clearance tasks run in parallel (§22.2) -> an Exit
Interview is captured -> Finance approves the F&F (BR-021) -> the case closes and the employee
is marked separated.

-- Identity: keyed by employee_code, like probation -----------------------------------------
The same convention hrms_probation_service already uses: a separation is a post-hire
EMPLOYEE fact, addressed by the company's own employee_code rather than the ERP's internal
user id, so a case reads the same way a probation record or a payslip eventually will.

-- One open case at a time, enforced in code rather than a unique index --------------------
A rehired-and-separated-again employee legitimately gets a SECOND separation row, so the
uniqueness a database index would give is the wrong tool; `_assert_no_open_case` checks it
instead, against CLOSED_SEPARATION_STAGES.

-- F&F has no payroll engine behind it -------------------------------------------------------
§7.13 (Payroll Processing) is unbuilt. FnfInput captures the figures a real payroll run would
otherwise supply, entered by hand, so a settlement can still be prepared, reviewed with a real
maker/checker gate, and paid -- it cannot compute LOP, PF or TDS from first principles, because
nothing in this codebase does that yet. Asset/clearance recoveries ARE rolled up automatically
(§22.2 step 196), because those numbers already live in this module's own collections.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_ACCESS_CLEARANCE_CREATED, AUDIT_ACCESS_CLEARANCE_UPDATED,
    AUDIT_ASSET_RETURN_CREATED, AUDIT_ASSET_RETURN_UPDATED,
    AUDIT_CLEARANCE_ACTIONED, AUDIT_CLEARANCE_CREATED,
    AUDIT_EXIT_INTERVIEW_SAVED, AUDIT_NOMINEE_DETAILS_SAVED,
    AUDIT_FNF_APPROVED, AUDIT_FNF_PAID, AUDIT_FNF_REJECTED, AUDIT_FNF_SAVED,
    AUDIT_HANDOVER_ACCEPTED, AUDIT_HANDOVER_CREATED, AUDIT_HANDOVER_UPDATED,
    AUDIT_SEPARATION_CLOSED, AUDIT_SEPARATION_DECIDED, AUDIT_SEPARATION_INITIATED,
    AUDIT_SEPARATION_WAIVED, AUDIT_SEPARATION_WITHDRAWN,
    CLOSED_SEPARATION_STAGES,
    COLL_ACCESS_CLEARANCES, COLL_ASSET_RETURNS, COLL_CLEARANCE_TASKS,
    COLL_DESIGNATIONS, COLL_EMPLOYEE_PROFILES, COLL_EXIT_INTERVIEWS,
    COLL_FNF_SETTLEMENTS, COLL_HANDOVER_TASKS, COLL_PROBATION_REVIEWS,
    COLL_SEPARATIONS,
    ENTITY_ACCESS_CLEARANCE, ENTITY_ASSET_RETURN, ENTITY_CLEARANCE,
    ENTITY_EXIT_INTERVIEW, ENTITY_FNF, ENTITY_HANDOVER, ENTITY_SEPARATION,
    MAX_TASKS_PER_SEPARATION,
    AccessClearanceStatus, AssetReturnStatus, ClearanceOwnerType, ClearanceStatus,
    EmploymentStatus, ExitType, FnfStatus, HandoverStatus, HrmsRole, ProbationOutcome,
    SeparationStage,
    notice_days_for,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import hrms_role

USER_COLLECTIONS = ("learners", "staff")


# ─────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────
def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _out_with_id(doc: dict) -> dict:
    """Like `_out`, but for the three child collections that carry no business id of their
    own (handover/clearance/access-clearance items) — the Mongo `_id` IS their identity, so
    it is kept, as a string, the same convention hrms_document_service uses for the same
    reason."""
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _oid(value: str, label: str = "record") -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id.")


def _add_days(iso_date: str, days: int) -> str:
    from datetime import date, timedelta
    y, m, d = (int(x) for x in iso_date.split("-"))
    return (date(y, m, d) + timedelta(days=days)).isoformat()


def _require_iso_date(value: Optional[str], field: str) -> Optional[str]:
    if value is None:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} must be a valid YYYY-MM-DD date.")
    return value


async def _find_user(user_id: str) -> tuple:
    oid = _oid(user_id)
    for coll in USER_COLLECTIONS:
        doc = await get_collection(coll).find_one({"_id": oid})
        if doc:
            return doc, coll
    return None, None


def _display_name(user: Optional[dict]) -> Optional[str]:
    if not user:
        return None
    return (user.get("full_name")
            or f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
            or user.get("email"))


async def _get_profile(company_id: str, employee_code: str) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(status_code=404, detail="No employee with that code in this company.")
    return profile


async def _designation_level(company_id: str, designation_id: Optional[str]) -> Optional[int]:
    if not designation_id:
        return None
    try:
        doc = await get_collection(COLL_DESIGNATIONS).find_one(
            {"_id": ObjectId(str(designation_id)), "company_id": str(company_id)})
    except (InvalidId, TypeError):
        return None
    return (doc or {}).get("level")


async def _is_on_probation(company_id: str, employee_code: str) -> bool:
    """The latest probation review's outcome decides this. No record at all reads as
    Confirmed — the same "assume the safer-for-the-company reading only where the doc is
    silent" principle notice_days_for's own default level follows, and consistent with an
    employee whose probation was simply never tracked in this system."""
    row = await get_collection(COLL_PROBATION_REVIEWS).find_one(
        {"company_id": str(company_id), "employee_code": employee_code},
        sort=[("started_on", -1)])
    if not row:
        return False
    return row.get("outcome") in (ProbationOutcome.PENDING.value, ProbationOutcome.EXTENDED.value)


async def _reporting_manager_id(profile: dict) -> Optional[str]:
    user_id = profile.get("user_id")
    if not user_id:
        return None
    user, _coll = await _find_user(user_id)
    return (user or {}).get("reporting_manager")


async def _get_separation(company_id: str, sep_no: str) -> dict:
    doc = await get_collection(COLL_SEPARATIONS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Separation '{sep_no}' not found.")
    return doc


def _require_open(sep: dict) -> None:
    if sep.get("stage") in CLOSED_SEPARATION_STAGES:
        raise HTTPException(
            status_code=409,
            detail=f"{sep['sep_no']} is already \"{sep.get('stage')}\" — no further action is possible.")


async def _task_count(coll_name: str, company_id: str, sep_no: str) -> int:
    return await get_collection(coll_name).count_documents(
        {"company_id": str(company_id), "sep_no": sep_no})


# ─────────────────────────────────────────────────────────────
# §7.18 — Resignation & Notice Period
# ─────────────────────────────────────────────────────────────
async def initiate_separation(actor: dict, company_id: str, payload: dict) -> dict:
    """§7.18 steps 137-139: raise a case and calculate the notice obligation.

    The calculation is a STARTING POINT, not a verdict — `notice_basis` tells the caller
    whether it rests on a real designation level or the safe default, and `decide_separation`
    / `approve_separation` are how a waiver or early release then gets recorded (BR-016).
    """
    employee_code = str(payload.get("employee_code") or "").strip()
    if not employee_code:
        raise HTTPException(status_code=422, detail="Select an employee.")

    existing_open = await get_collection(COLL_SEPARATIONS).find_one({
        "company_id": str(company_id), "employee_code": employee_code,
        "stage": {"$nin": list(CLOSED_SEPARATION_STAGES)},
    })
    if existing_open:
        raise HTTPException(
            status_code=409,
            detail=f"{employee_code} already has an open separation ({existing_open['sep_no']}).")

    profile = await _get_profile(company_id, employee_code)
    exit_type = payload.get("exit_type") or ExitType.RESIGNATION.value
    resignation_date = _require_iso_date(
        payload.get("resignation_date"), "Resignation date") or _today()

    level = await _designation_level(company_id, profile.get("designation_id"))
    on_probation = await _is_on_probation(company_id, employee_code)
    calculated_days = notice_days_for(on_probation, level)
    calculated_lwd = _add_days(resignation_date, calculated_days)
    proposed_lwd = _require_iso_date(payload.get("proposed_lwd"), "Proposed LWD") or calculated_lwd

    manager_id = await _reporting_manager_id(profile)
    year = datetime.now(timezone.utc).year
    sep_no = await next_business_id("separation", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "sep_no": sep_no,
        "company_id": str(company_id),
        "employee_code": employee_code,
        "employee_name": profile.get("display_name") or profile.get("full_name"),
        "user_id": profile.get("user_id"),
        "reporting_manager_id": manager_id,
        "exit_type": exit_type,
        "reason": payload.get("reason"),
        "resignation_date": resignation_date,
        "employment_status_at_exit": profile.get("employment_status"),
        "designation_level": level,
        "notice_basis": "designation level" if level else "no designation level on file — assumed L1",
        "on_probation_at_exit": on_probation,
        "calculated_notice_days": calculated_days,
        "calculated_lwd": calculated_lwd,
        "proposed_lwd": proposed_lwd,
        "recommended_lwd": None,
        "waiver_days": None,
        "shortfall_days": None,
        "waiver_approved": None,
        "waiver_remarks": None,
        "final_lwd": None,           # set once accepted (decide_separation), or on approval
        "stage": SeparationStage.INITIATED.value,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_SEPARATIONS).insert_one(doc)

    # §7.18 step 142: status moves to Notice Period the moment the case is opened — the
    # obligation exists from here, whatever HR later decides about a waiver.
    #
    # A profile never linked to a portal login (Phase 9's employee.link_user is a separate,
    # optional step — see hrms_employee_service.link_user) has no `user_id`, and
    # update_profile looks a profile up BY user_id, so there is nothing for it to find. The
    # separation record above already carries employment_status_at_exit correctly either
    # way; this is only the sync onto the login-linked profile row, which simply does not
    # exist yet for an unlinked employee. Skipping it (rather than `profile["user_id"]`,
    # which raised an unhandled KeyError -> 500 here) is the same "no linked account yet"
    # case this codebase already treats as normal elsewhere.
    if profile.get("user_id"):
        from app.services.hrms_employee_service import update_profile
        await update_profile(actor, profile["user_id"],
                             {"employment_status": EmploymentStatus.ON_NOTICE.value}, company_id)

    await audit(actor, AUDIT_SEPARATION_INITIATED, ENTITY_SEPARATION, sep_no,
               f"{employee_code}, {exit_type}, calculated notice {calculated_days}d "
               f"(LWD {calculated_lwd})", company_id)
    return _out(doc)


async def list_separations(actor: dict, company_id: str, *, stage: Optional[str] = None,
                           employee_code: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if stage:
        query["stage"] = stage
    if employee_code:
        query["employee_code"] = employee_code
    rows = await get_collection(COLL_SEPARATIONS).find(query).sort(
        "created_at", -1).to_list(limit)
    return [_out(r) for r in rows]


async def get_separation(actor: dict, company_id: str, sep_no: str) -> dict:
    """One case, composed with the child-collection counts the Exit tab (§22.1) needs to
    show progress without five separate round trips."""
    sep = await _get_separation(company_id, sep_no)
    out = _out(sep)

    handover_total = await _task_count(COLL_HANDOVER_TASKS, company_id, sep_no)
    handover_done = await get_collection(COLL_HANDOVER_TASKS).count_documents(
        {"company_id": str(company_id), "sep_no": sep_no, "status": HandoverStatus.ACCEPTED.value})
    clearance_total = await _task_count(COLL_CLEARANCE_TASKS, company_id, sep_no)
    clearance_done = await get_collection(COLL_CLEARANCE_TASKS).count_documents(
        {"company_id": str(company_id), "sep_no": sep_no,
         "status": {"$in": [ClearanceStatus.CLEARED.value, ClearanceStatus.WAIVED.value]}})
    asset_total = await _task_count(COLL_ASSET_RETURNS, company_id, sep_no)
    asset_pending = await get_collection(COLL_ASSET_RETURNS).count_documents(
        {"company_id": str(company_id), "sep_no": sep_no, "status": AssetReturnStatus.PENDING.value})
    access_total = await _task_count(COLL_ACCESS_CLEARANCES, company_id, sep_no)
    access_pending = await get_collection(COLL_ACCESS_CLEARANCES).count_documents(
        {"company_id": str(company_id), "sep_no": sep_no, "status": AccessClearanceStatus.PENDING.value})
    interview = await get_collection(COLL_EXIT_INTERVIEWS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no})
    fnf = await get_collection(COLL_FNF_SETTLEMENTS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no})

    out["progress"] = {
        "handover": {"done": handover_done, "total": handover_total},
        "clearance": {"done": clearance_done, "total": clearance_total},
        "asset_returns": {"pending": asset_pending, "total": asset_total},
        "access_clearances": {"pending": access_pending, "total": access_total},
        "exit_interview_done": bool(interview),
        "fnf_status": (fnf or {}).get("status"),
    }
    return out


async def decide_separation(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """§7.18 steps 140-142: HR/manager records acceptance. Any revision away from the
    CALCULATED notice needs SeparationApprovalIn before it takes effect (BR-016) — recording
    it here only proposes it; `final_lwd` stays the calculated date until approved.

    Also opens the standard departmental clearance tasks (§22.2 step 192: "System creates
    Departmental Clearance tasks") — this is the point the doc's own step sequence puts that
    system action, right after notice is accepted and before handover/clearance work starts.
    """
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)

    revised_lwd = _require_iso_date(payload.get("revised_lwd"), "Revised LWD")
    waiver_days = payload.get("waiver_days")
    shortfall_days = payload.get("shortfall_days")
    needs_approval = bool(
        waiver_days or shortfall_days
        or (revised_lwd and revised_lwd != sep.get("calculated_lwd")))

    updates = {
        "recommended_lwd": revised_lwd or sep.get("calculated_lwd"),
        "waiver_days": waiver_days,
        "shortfall_days": shortfall_days,
        "decision_remarks": payload.get("remarks"),
        "updated_at": datetime.now(timezone.utc),
    }
    if not needs_approval:
        # Nothing to approve — the calculated notice stands, so it is final immediately.
        updates["final_lwd"] = updates["recommended_lwd"]
        updates["waiver_approved"] = None
    if sep.get("stage") == SeparationStage.INITIATED.value:
        updates["stage"] = SeparationStage.HANDOVER_CLEARANCE.value

    await get_collection(COLL_SEPARATIONS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no}, {"$set": updates})

    if not await get_collection(COLL_CLEARANCE_TASKS).count_documents(
            {"company_id": str(company_id), "sep_no": sep_no}):
        await _seed_clearance_tasks(actor, company_id, sep)

    await audit(actor, AUDIT_SEPARATION_DECIDED, ENTITY_SEPARATION, sep_no,
               f"recommended LWD {updates['recommended_lwd']}"
               + (" — awaiting approval" if needs_approval else " — final"), company_id)
    return await get_separation(actor, company_id, sep_no)


async def approve_separation(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """The written approval BR-016 requires before a waiver or early release takes effect."""
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)
    if not sep.get("recommended_lwd") or sep.get("final_lwd"):
        raise HTTPException(
            status_code=409,
            detail="Nothing is pending approval on this case.")

    approved = bool(payload.get("approved"))
    updates = {
        "waiver_approved": approved,
        "waiver_remarks": payload.get("remarks"),
        "updated_at": datetime.now(timezone.utc),
    }
    if approved:
        updates["final_lwd"] = sep["recommended_lwd"]
    await get_collection(COLL_SEPARATIONS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no}, {"$set": updates})

    await audit(actor, AUDIT_SEPARATION_WAIVED, ENTITY_SEPARATION, sep_no,
               f"{'approved' if approved else 'rejected'}: LWD {sep['recommended_lwd']}", company_id)
    return await get_separation(actor, company_id, sep_no)


async def withdraw_separation(actor: dict, company_id: str, sep_no: str, remarks: Optional[str]) -> dict:
    """An employee changing their mind, or HR raising a case in error. Reverts the employee
    to Active — the only stage transition in this module that undoes an employment_status
    change rather than advancing it."""
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)
    await get_collection(COLL_SEPARATIONS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no},
        {"$set": {"stage": SeparationStage.WITHDRAWN.value, "withdrawal_remarks": remarks,
                  "updated_at": datetime.now(timezone.utc)}})
    if sep.get("user_id"):
        from app.services.hrms_employee_service import update_profile
        await update_profile(actor, sep["user_id"],
                             {"employment_status": EmploymentStatus.ACTIVE.value}, company_id)
    await audit(actor, AUDIT_SEPARATION_WITHDRAWN, ENTITY_SEPARATION, sep_no, remarks, company_id)
    return await get_separation(actor, company_id, sep_no)


# ─────────────────────────────────────────────────────────────
# §22.2 — Handover Plan
# ─────────────────────────────────────────────────────────────
async def create_handover_task(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)
    if await _task_count(COLL_HANDOVER_TASKS, company_id, sep_no) >= MAX_TASKS_PER_SEPARATION:
        raise HTTPException(status_code=400, detail="This case already carries the maximum number of handover tasks.")

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id),
        "sep_no": sep_no,
        "task": payload.get("task"),
        "description": payload.get("description"),
        "assigned_to": payload.get("assigned_to"),
        "owner_id": payload.get("owner_id") or sep.get("reporting_manager_id"),
        "due_date": _require_iso_date(payload.get("due_date"), "Due date"),
        "attachment": payload.get("attachment"),
        "status": HandoverStatus.PENDING.value,
        "completion_evidence": None,
        "manager_acceptance": None,
        "remarks": None,
        "created_at": now,
        "updated_at": now,
    }
    if not doc["task"]:
        raise HTTPException(status_code=422, detail="Describe the task or knowledge item.")
    result = await get_collection(COLL_HANDOVER_TASKS).insert_one(doc)
    doc["_id"] = result.inserted_id
    await audit(actor, AUDIT_HANDOVER_CREATED, ENTITY_HANDOVER, str(result.inserted_id),
               f"{sep_no}: {doc['task']}", company_id)
    return _out_with_id(doc)


async def list_handover_tasks(actor: dict, company_id: str, sep_no: str) -> list:
    rows = await get_collection(COLL_HANDOVER_TASKS).find(
        {"company_id": str(company_id), "sep_no": sep_no}).sort("created_at", 1).to_list(
            MAX_TASKS_PER_SEPARATION)
    return [_out_with_id(r) for r in rows]


async def _get_handover_task(company_id: str, sep_no: str, task_id: str) -> dict:
    doc = await get_collection(COLL_HANDOVER_TASKS).find_one(
        {"_id": _oid(task_id, "handover task"), "company_id": str(company_id), "sep_no": sep_no})
    if not doc:
        raise HTTPException(status_code=404, detail="Handover task not found.")
    return doc


async def update_handover_task(actor: dict, company_id: str, sep_no: str, task_id: str,
                               payload: dict) -> dict:
    """The doer (or HR, editing the plan) updates a task — including marking it Submitted,
    which is what puts it in front of the manager for acceptance."""
    await _get_handover_task(company_id, sep_no, task_id)
    clean = {k: v for k, v in payload.items() if v is not None}
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update.")
    clean["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_HANDOVER_TASKS).update_one(
        {"_id": _oid(task_id)}, {"$set": clean})
    await audit(actor, AUDIT_HANDOVER_UPDATED, ENTITY_HANDOVER, task_id,
               ", ".join(sorted(clean.keys())), company_id)
    return _out_with_id(await _get_handover_task(company_id, sep_no, task_id))


async def accept_handover_task(actor: dict, company_id: str, sep_no: str, task_id: str,
                               payload: dict) -> dict:
    """§22.2 step 191: the reporting manager's sign-off. The one place in this module a
    capability check alone is not enough — a manager may only accept work on THEIR OWN
    report's case, enforced by the caller matching `sep.reporting_manager_id` against actor.

    Enforced here, not just documented: `Cap.HANDOVER_APPROVE` is a role-wide grant (every
    HOD/Manager in the company holds it, the same as every other capability in this module),
    so without this check any manager could accept or reject a handover on any OTHER
    manager's report — exactly the cross-department mistake the docstring above already
    claimed was impossible. MD (and internal staff via the ADMIN implicit-grant) are exempt,
    the same override authority they hold everywhere else in this module (the named manager
    may be unavailable, on leave, or the one leaving)."""
    task = await _get_handover_task(company_id, sep_no, task_id)
    if hrms_role(actor) is HrmsRole.MANAGER:
        sep = await _get_separation(company_id, sep_no)
        manager_id = str(sep.get("reporting_manager_id") or "")
        if not manager_id or manager_id != str(actor.get("_id") or ""):
            raise HTTPException(
                status_code=403,
                detail="Only this employee's reporting manager may accept or reject their handover.")
    accepted = bool(payload.get("accepted"))
    updates = {
        "status": HandoverStatus.ACCEPTED.value if accepted else HandoverStatus.REJECTED.value,
        "manager_acceptance": accepted,
        "remarks": payload.get("remarks"),
        "updated_at": datetime.now(timezone.utc),
    }
    await get_collection(COLL_HANDOVER_TASKS).update_one({"_id": task["_id"]}, {"$set": updates})
    await audit(actor, AUDIT_HANDOVER_ACCEPTED, ENTITY_HANDOVER, task_id,
               "accepted" if accepted else "rejected", company_id)
    return _out_with_id(await _get_handover_task(company_id, sep_no, task_id))


# ─────────────────────────────────────────────────────────────
# §22.2 — Departmental Clearance
# ─────────────────────────────────────────────────────────────
# The five standing functions the BA doc names by name (step 192). A company that needs a
# sixth adds it with create_clearance_task — this list is the FLOOR every case gets for free,
# not the ceiling.
_STANDARD_CLEARANCE_OWNERS = [
    (ClearanceOwnerType.MANAGER, "Manager clearance", "reporting_manager_id"),
    (ClearanceOwnerType.HR, "HR clearance", None),
    (ClearanceOwnerType.IT, "IT clearance", None),
    (ClearanceOwnerType.ADMIN, "Admin clearance", None),
    (ClearanceOwnerType.FINANCE, "Finance clearance", None),
]


async def _seed_clearance_tasks(actor: dict, company_id: str, sep: dict) -> None:
    now = datetime.now(timezone.utc)
    docs = []
    for owner_type, label, owner_field in _STANDARD_CLEARANCE_OWNERS:
        docs.append({
            "company_id": str(company_id),
            "sep_no": sep["sep_no"],
            "owner_type": owner_type.value,
            "owner_id": sep.get(owner_field) if owner_field else None,
            "task": label,
            "due_date": sep.get("final_lwd") or sep.get("recommended_lwd") or sep.get("calculated_lwd"),
            "status": ClearanceStatus.PENDING.value,
            "recovery_amount": None,
            "evidence": None,
            "remarks": None,
            "created_at": now,
            "updated_at": now,
        })
    if docs:
        await get_collection(COLL_CLEARANCE_TASKS).insert_many(docs)
        await audit(actor, AUDIT_CLEARANCE_CREATED, ENTITY_CLEARANCE, sep["sep_no"],
                   f"{len(docs)} standard departmental clearance tasks opened", company_id)


async def create_clearance_task(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """§22.2: '... and any other configured function' — a clearance owner beyond the five
    standard ones."""
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)
    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "sep_no": sep_no,
        "owner_type": payload.get("owner_type"),
        "owner_id": payload.get("owner_id"),
        "task": payload.get("task"),
        "due_date": _require_iso_date(payload.get("due_date"), "Due date"),
        "status": ClearanceStatus.PENDING.value,
        "recovery_amount": None, "evidence": None, "remarks": None,
        "created_at": now, "updated_at": now,
    }
    if not doc["task"]:
        raise HTTPException(status_code=422, detail="Describe the clearance task.")
    result = await get_collection(COLL_CLEARANCE_TASKS).insert_one(doc)
    doc["_id"] = result.inserted_id
    await audit(actor, AUDIT_CLEARANCE_CREATED, ENTITY_CLEARANCE, str(result.inserted_id),
               f"{sep_no}: {doc['task']}", company_id)
    return _out_with_id(doc)


async def list_clearance_tasks(actor: dict, company_id: str, sep_no: str) -> list:
    rows = await get_collection(COLL_CLEARANCE_TASKS).find(
        {"company_id": str(company_id), "sep_no": sep_no}).sort("created_at", 1).to_list(
            MAX_TASKS_PER_SEPARATION)
    return [_out_with_id(r) for r in rows]


async def act_on_clearance_task(actor: dict, company_id: str, sep_no: str, task_id: str,
                                payload: dict) -> dict:
    doc = await get_collection(COLL_CLEARANCE_TASKS).find_one(
        {"_id": _oid(task_id, "clearance task"), "company_id": str(company_id), "sep_no": sep_no})
    if not doc:
        raise HTTPException(status_code=404, detail="Clearance task not found.")
    updates = {
        "status": payload.get("status"),
        "recovery_amount": payload.get("recovery_amount"),
        "evidence": payload.get("evidence"),
        "remarks": payload.get("remarks"),
        "updated_at": datetime.now(timezone.utc),
    }
    await get_collection(COLL_CLEARANCE_TASKS).update_one({"_id": doc["_id"]}, {"$set": updates})
    await audit(actor, AUDIT_CLEARANCE_ACTIONED, ENTITY_CLEARANCE, task_id,
               f"{doc.get('task')}: {updates['status']}", company_id)
    return _out_with_id({**doc, **updates})


# ─────────────────────────────────────────────────────────────
# §22.2 — Asset Return Requests
# ─────────────────────────────────────────────────────────────
async def create_asset_return(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """The employee or HR may initiate this (§22.2) — the route allows either without an
    extra capability check when the actor IS the separating employee."""
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)
    if not payload.get("description"):
        raise HTTPException(status_code=422, detail="Describe the asset.")
    year = datetime.now(timezone.utc).year
    ast_no = await next_business_id("asset_return", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "ast_no": ast_no,
        "company_id": str(company_id), "sep_no": sep_no,
        "asset_id": payload.get("asset_id"),
        "category": payload.get("category"),
        "description": payload.get("description"),
        "issued_date": _require_iso_date(payload.get("issued_date"), "Issued date"),
        "return_request_date": _today(),
        "expected_return_date": _require_iso_date(
            payload.get("expected_return_date"), "Expected return date"),
        "returned_date": None,
        "condition": None,
        "missing_or_damaged": False,
        "recovery_amount": None,
        "received_by": None,
        "attachment": None,
        "status": AssetReturnStatus.PENDING.value,
        "remarks": None,
        "created_at": now, "updated_at": now,
    }
    result = await get_collection(COLL_ASSET_RETURNS).insert_one(doc)
    doc["_id"] = result.inserted_id
    await audit(actor, AUDIT_ASSET_RETURN_CREATED, ENTITY_ASSET_RETURN, ast_no,
               f"{sep_no}: {doc['description']}", company_id)
    return _out(doc)


async def list_asset_returns(actor: dict, company_id: str, sep_no: str) -> list:
    rows = await get_collection(COLL_ASSET_RETURNS).find(
        {"company_id": str(company_id), "sep_no": sep_no}).sort("created_at", 1).to_list(
            MAX_TASKS_PER_SEPARATION)
    return [_out(r) for r in rows]


async def update_asset_return(actor: dict, company_id: str, sep_no: str, ast_no: str,
                              payload: dict) -> dict:
    """HR/Admin confirms receipt and condition (§22.2)."""
    doc = await get_collection(COLL_ASSET_RETURNS).find_one(
        {"ast_no": ast_no, "company_id": str(company_id), "sep_no": sep_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Asset return '{ast_no}' not found.")
    clean = {k: v for k, v in payload.items() if v is not None}
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update.")
    for field in ("returned_date",):
        if field in clean:
            clean[field] = _require_iso_date(clean[field], "Returned date")
    clean["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_ASSET_RETURNS).update_one({"_id": doc["_id"]}, {"$set": clean})
    await audit(actor, AUDIT_ASSET_RETURN_UPDATED, ENTITY_ASSET_RETURN, ast_no,
               ", ".join(sorted(clean.keys())), company_id)
    return _out({**doc, **clean})


# ─────────────────────────────────────────────────────────────
# §22.2 — Access Clearance
# ─────────────────────────────────────────────────────────────
async def create_access_clearance(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)
    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "sep_no": sep_no,
        "system_type": payload.get("system_type"),
        "description": payload.get("description"),
        "owner_id": payload.get("owner_id"),
        "status": AccessClearanceStatus.PENDING.value,
        "remarks": None,
        "created_at": now, "updated_at": now,
    }
    if not doc["system_type"]:
        raise HTTPException(status_code=422, detail="Select the system/access type.")
    result = await get_collection(COLL_ACCESS_CLEARANCES).insert_one(doc)
    doc["_id"] = result.inserted_id
    await audit(actor, AUDIT_ACCESS_CLEARANCE_CREATED, ENTITY_ACCESS_CLEARANCE,
               str(result.inserted_id), f"{sep_no}: {doc['system_type']}", company_id)
    return _out_with_id(doc)


async def list_access_clearances(actor: dict, company_id: str, sep_no: str) -> list:
    rows = await get_collection(COLL_ACCESS_CLEARANCES).find(
        {"company_id": str(company_id), "sep_no": sep_no}).sort("created_at", 1).to_list(
            MAX_TASKS_PER_SEPARATION)
    return [_out_with_id(r) for r in rows]


async def update_access_clearance(actor: dict, company_id: str, sep_no: str, item_id: str,
                                  payload: dict) -> dict:
    doc = await get_collection(COLL_ACCESS_CLEARANCES).find_one(
        {"_id": _oid(item_id, "access clearance"), "company_id": str(company_id), "sep_no": sep_no})
    if not doc:
        raise HTTPException(status_code=404, detail="Access clearance item not found.")
    updates = {
        "status": payload.get("status"),
        "remarks": payload.get("remarks"),
        "updated_at": datetime.now(timezone.utc),
    }
    await get_collection(COLL_ACCESS_CLEARANCES).update_one({"_id": doc["_id"]}, {"$set": updates})
    await audit(actor, AUDIT_ACCESS_CLEARANCE_UPDATED, ENTITY_ACCESS_CLEARANCE, item_id,
               f"{doc.get('system_type')}: {updates['status']}", company_id)
    return _out_with_id({**doc, **updates})


# ─────────────────────────────────────────────────────────────
# §22.2 step 195 — Exit Interview Form
# ─────────────────────────────────────────────────────────────
async def save_exit_interview(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """Upsert — one interview per case (COLL_EXIT_INTERVIEWS carries a unique index on
    (company_id, sep_no)), so a re-submission corrects the same record rather than
    accumulating duplicates."""
    await _get_separation(company_id, sep_no)   # 404s if the case does not exist
    now = datetime.now(timezone.utc)
    clean = {k: v for k, v in payload.items() if v is not None}
    clean["updated_at"] = now
    await get_collection(COLL_EXIT_INTERVIEWS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no},
        {"$set": clean,
         "$setOnInsert": {"company_id": str(company_id), "sep_no": sep_no, "created_at": now}},
        upsert=True)
    await audit(actor, AUDIT_EXIT_INTERVIEW_SAVED, ENTITY_EXIT_INTERVIEW, sep_no, None, company_id)
    return _out(await get_collection(COLL_EXIT_INTERVIEWS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no}))


async def get_exit_interview(actor: dict, company_id: str, sep_no: str) -> Optional[dict]:
    doc = await get_collection(COLL_EXIT_INTERVIEWS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no})
    return _out(doc) if doc else None


# ─────────────────────────────────────────────────────────────
# §7.20 step 157 — Demise/Missing nominee & legal documentation
# ─────────────────────────────────────────────────────────────
async def save_nominee_details(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """Kept ON the separation record itself, not a parallel collection — this is
    exit-type-specific data about ONE case (Demise/Missing), the same reason handover/
    clearance/asset-return already live alongside it rather than in COLL_EMPLOYEE_PROFILES.
    Nothing in the BA doc says this is restricted to those two exit types, so it is not
    enforced here either — a company that wants to record it for other types may."""
    sep = await _get_separation(company_id, sep_no)
    clean = {k: v for k, v in payload.items() if v is not None}
    now = datetime.now(timezone.utc)
    await get_collection(COLL_SEPARATIONS).update_one(
        {"_id": sep["_id"]}, {"$set": {"nominee_details": clean, "updated_at": now}})
    await audit(actor, AUDIT_NOMINEE_DETAILS_SAVED, ENTITY_SEPARATION, sep_no,
               "nominee/legal documentation saved", company_id)
    return _out(await _get_separation(company_id, sep_no))


# ─────────────────────────────────────────────────────────────
# §7.21 — Full & Final Settlement
# ─────────────────────────────────────────────────────────────
async def _rolled_up_recoveries(company_id: str, sep_no: str) -> float:
    """§22.2 step 196: unreturned assets and clearance recoveries feed F&F automatically."""
    total = 0.0
    for coll_name in (COLL_ASSET_RETURNS, COLL_CLEARANCE_TASKS):
        async for row in get_collection(coll_name).find(
                {"company_id": str(company_id), "sep_no": sep_no,
                 "recovery_amount": {"$ne": None}}):
            total += float(row.get("recovery_amount") or 0)
    return round(total, 2)


def _fnf_total(inputs: dict, rolled_up_recovery: float) -> float:
    earnings = (
        float(inputs.get("payable_days") or 0)
        + float(inputs.get("leave_encashment") or 0)
        + float(inputs.get("variable_pay_hold_release") or 0)
        + float(inputs.get("other_earnings") or 0)
    )
    # notice_pay_or_shortfall may itself be negative (a recovery) — added as-is.
    earnings += float(inputs.get("notice_pay_or_shortfall") or 0)
    deductions = (
        float(inputs.get("advance_recovery") or 0)
        + float(inputs.get("other_deductions") or 0)
        + rolled_up_recovery
    )
    return round(earnings - deductions, 2)


async def save_fnf(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """HR/Payroll prepares the settlement (the maker half of BR-021's maker/checker gate).
    Upsert while still Draft/Prepared; once Approved or Paid it is closed to further edits —
    a correction after approval is a new decision, not a silent rewrite of an approved figure,
    the same discipline BR-020 asks of real payroll."""
    sep = await _get_separation(company_id, sep_no)
    existing = await get_collection(COLL_FNF_SETTLEMENTS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no})
    if existing and existing.get("status") in (FnfStatus.APPROVED.value, FnfStatus.PAID.value):
        raise HTTPException(
            status_code=409,
            detail=f"F&F for {sep_no} is already \"{existing['status']}\" and cannot be edited.")

    inputs = {k: v for k, v in payload.items() if k != "remarks"}
    rolled_up = await _rolled_up_recoveries(company_id, sep_no)
    total = _fnf_total(inputs, rolled_up)
    now = datetime.now(timezone.utc)
    doc = {
        **inputs,
        "rolled_up_recovery": rolled_up,
        "total_settlement": total,
        "remarks": payload.get("remarks"),
        "status": FnfStatus.PREPARED.value,
        "prepared_by": str(actor.get("_id")) if actor.get("_id") else None,
        "approved_by": None, "approved_at": None,
        "paid_on": None, "payment_reference": None,
        "updated_at": now,
    }
    await get_collection(COLL_FNF_SETTLEMENTS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no},
        {"$set": doc,
         "$setOnInsert": {"company_id": str(company_id), "sep_no": sep_no, "created_at": now}},
        upsert=True)
    if sep.get("stage") not in (SeparationStage.FNF_PENDING.value,):
        await get_collection(COLL_SEPARATIONS).update_one(
            {"company_id": str(company_id), "sep_no": sep_no},
            {"$set": {"stage": SeparationStage.FNF_PENDING.value, "updated_at": now}})
    await audit(actor, AUDIT_FNF_SAVED, ENTITY_FNF, sep_no,
               f"total {total} (recoveries rolled up: {rolled_up})", company_id)
    return await get_fnf(actor, company_id, sep_no)


async def get_fnf(actor: dict, company_id: str, sep_no: str) -> dict:
    doc = await get_collection(COLL_FNF_SETTLEMENTS).find_one(
        {"company_id": str(company_id), "sep_no": sep_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"No F&F prepared yet for {sep_no}.")
    return _out(doc)


async def approve_fnf(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    """Finance's checker gate (BR-021)."""
    doc = await get_fnf(actor, company_id, sep_no)
    if doc.get("status") != FnfStatus.PREPARED.value:
        raise HTTPException(
            status_code=409,
            detail=f"F&F for {sep_no} is \"{doc.get('status')}\", not awaiting approval.")

    approved = bool(payload.get("approved"))
    now = datetime.now(timezone.utc)
    updates = {
        "status": FnfStatus.APPROVED.value if approved else FnfStatus.REJECTED.value,
        "approved_by": str(actor.get("_id")) if actor.get("_id") else None,
        "approved_at": now,
        "approval_remarks": payload.get("remarks"),
        "updated_at": now,
    }
    await get_collection(COLL_FNF_SETTLEMENTS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no}, {"$set": updates})
    if approved:
        await get_collection(COLL_SEPARATIONS).update_one(
            {"company_id": str(company_id), "sep_no": sep_no},
            {"$set": {"stage": SeparationStage.FNF_APPROVED.value, "updated_at": now}})
    await audit(actor, AUDIT_FNF_APPROVED if approved else AUDIT_FNF_REJECTED,
               ENTITY_FNF, sep_no, payload.get("remarks"), company_id)
    return await get_fnf(actor, company_id, sep_no)


async def mark_fnf_paid(actor: dict, company_id: str, sep_no: str, payload: dict) -> dict:
    doc = await get_fnf(actor, company_id, sep_no)
    if doc.get("status") != FnfStatus.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=f"F&F for {sep_no} must be Approved before it can be marked paid.")
    now = datetime.now(timezone.utc)
    updates = {
        "status": FnfStatus.PAID.value,
        "paid_on": _require_iso_date(payload.get("paid_on"), "Paid on") or _today(),
        "payment_reference": payload.get("reference"),
        "updated_at": now,
    }
    await get_collection(COLL_FNF_SETTLEMENTS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no}, {"$set": updates})
    await get_collection(COLL_SEPARATIONS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no},
        {"$set": {"stage": SeparationStage.SETTLED.value, "updated_at": now}})
    await audit(actor, AUDIT_FNF_PAID, ENTITY_FNF, sep_no,
               updates["payment_reference"], company_id)
    return await get_fnf(actor, company_id, sep_no)


# ─────────────────────────────────────────────────────────────
# §22.2 step 199 — Closure
# ─────────────────────────────────────────────────────────────
async def close_separation(actor: dict, company_id: str, sep_no: str, *, force: bool = False) -> dict:
    """BR-025: exit cannot be treated as complete until mandatory handover and clearance
    tasks are completed or formally waived. `force` is HR's explicit override for a task that
    will never close (e.g. an absconding case with no handover possible) — recorded as such
    in the audit line rather than silently skipped.
    """
    sep = await _get_separation(company_id, sep_no)
    _require_open(sep)

    if not force:
        open_handover = await get_collection(COLL_HANDOVER_TASKS).count_documents(
            {"company_id": str(company_id), "sep_no": sep_no,
             "status": {"$nin": [HandoverStatus.ACCEPTED.value, HandoverStatus.REJECTED.value]}})
        open_clearance = await get_collection(COLL_CLEARANCE_TASKS).count_documents(
            {"company_id": str(company_id), "sep_no": sep_no,
             "status": ClearanceStatus.PENDING.value})
        fnf = await get_collection(COLL_FNF_SETTLEMENTS).find_one(
            {"company_id": str(company_id), "sep_no": sep_no})
        problems = []
        if open_handover:
            problems.append(f"{open_handover} handover task(s) not yet accepted/rejected")
        if open_clearance:
            problems.append(f"{open_clearance} clearance task(s) still pending")
        if not fnf or fnf.get("status") != FnfStatus.PAID.value:
            problems.append("F&F is not marked Paid")
        if problems:
            raise HTTPException(
                status_code=409,
                detail="Cannot close: " + "; ".join(problems) + ". Pass force to override with a recorded reason.")

    now = datetime.now(timezone.utc)
    final_lwd = sep.get("final_lwd") or sep.get("calculated_lwd")
    await get_collection(COLL_SEPARATIONS).update_one(
        {"company_id": str(company_id), "sep_no": sep_no},
        {"$set": {"stage": SeparationStage.CLOSED.value, "closed_at": now, "updated_at": now}})

    if sep.get("user_id"):
        from app.services.hrms_employee_service import update_profile
        status = (EmploymentStatus.TERMINATED.value
                 if sep.get("exit_type") in (ExitType.TERMINATION.value, ExitType.ABSCONDING.value)
                 else EmploymentStatus.RESIGNED.value)
        await update_profile(actor, sep["user_id"],
                             {"employment_status": status, "resigned_on": final_lwd}, company_id)
        for coll in USER_COLLECTIONS:
            await get_collection(coll).update_one(
                {"_id": ObjectId(sep["user_id"])}, {"$set": {"is_active": False}})

    # §7.15 BR: "If employee leaves before 12 months, held 25% is not payable." Any
    # variable-pay hold still sitting as Held at closure has, by definition, not already
    # gone through a manual Release (the escape hatch when the 12-month condition was
    # genuinely met) — so it is forfeited here rather than left for someone to remember.
    from app.services.hrms_variable_pay_service import forfeit_holds_for_separation
    await forfeit_holds_for_separation(company_id, sep["employee_code"], sep_no)

    await audit(actor, AUDIT_SEPARATION_CLOSED, ENTITY_SEPARATION, sep_no,
               f"LWD {final_lwd}" + (" (forced)" if force else ""), company_id)
    return await get_separation(actor, company_id, sep_no)
