"""HRMS > Employee Movements (BA/Functional Design v2.2, §7.16).

Promotion, transfer, manager/designation/grade/location/compensation change is proposed
against the employee's CURRENT value (captured here, never client-supplied) -> approved ->
applied on its effective date, updating the live profile while the movement record itself
becomes the permanent, never-edited history entry.

-- "Never overwrite historical organisation/compensation state" (§7.16 BR) --------------------
Satisfied by construction, the same way probation/exit records already are: a NEW movement is
a NEW row, never an edit to a prior one. The live value sits on the employee profile (or the
ERP user doc, for reporting_manager) exactly as it already did before this module existed;
history is simply every past movement row, untouched.

-- Grade and Location have no canonical field yet -----------------------------------------
Neither concept exists anywhere else in this codebase (the earlier gap analysis flagged this).
Those two movement types are recorded, approved and become history like any other, but
`apply_movement` says explicitly that no live field was updated for them, rather than silently
pretending it did something it did not.
"""
from datetime import date, datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_MOVEMENT_ACTIONED, AUDIT_MOVEMENT_APPLIED, AUDIT_MOVEMENT_INITIATED,
    COLL_DESIGNATIONS, COLL_EMPLOYEE_MOVEMENTS, COLL_EMPLOYEE_PROFILES,
    ENTITY_MOVEMENT, MAX_MOVEMENT_LIST_PAGE, MOVEMENT_APPLIABLE_TYPES,
    MovementStatus, MovementType,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id

USER_COLLECTIONS = ("learners", "staff")


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _get_profile(company_id: str, employee_code: str) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(status_code=404, detail="No employee with that code in this company.")
    return profile


async def _find_user(user_id: str) -> Optional[dict]:
    try:
        oid = ObjectId(str(user_id))
    except (InvalidId, TypeError):
        return None
    for coll in USER_COLLECTIONS:
        doc = await get_collection(coll).find_one({"_id": oid})
        if doc:
            return doc
    return None


async def _current_value(company_id: str, profile: dict, movement_type: str) -> Optional[str]:
    """§7.16 step 121: "System displays current values" — looked up here, never supplied by
    the caller, so a stale or falsified "before" figure can never enter the history."""
    if movement_type in (MovementType.DESIGNATION_CHANGE.value, MovementType.PROMOTION.value):
        return profile.get("designation_id")
    if movement_type == MovementType.COMPENSATION_CHANGE.value:
        # What payroll ACTUALLY pays: the monthly earnings of the salary structure in force.
        from app.services.hrms_payroll_service import (
            get_current_structure, _load_component_types, _structure_gross)
        await _load_component_types(profile["company_id"])
        gross = _structure_gross(await get_current_structure(profile["company_id"], profile["employee_code"]))
        return str(int(gross) if gross == int(gross) else gross) if gross else None
    if movement_type == MovementType.MANAGER_CHANGE.value:
        user = await _find_user(profile.get("user_id"))
        return (user or {}).get("reporting_manager")
    # Grade / Location: no canonical field exists yet — there is genuinely nothing to read.
    return None


async def initiate_movement(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    if not employee_code:
        raise HTTPException(status_code=422, detail="Select an employee.")
    movement_type = payload.get("movement_type")
    effective_date = payload.get("effective_date")
    if not effective_date:
        raise HTTPException(status_code=422, detail="An effective date is required.")

    profile = await _get_profile(company_id, employee_code)
    from app.services import hrms_people_scope as scope
    await scope.assert_may_act_for(actor, company_id, employee_code, "propose a movement")
    current_value = await _current_value(company_id, profile, movement_type)
    to_value = str(payload.get("to_value") or "").strip()
    if not to_value and movement_type not in (MovementType.GRADE_CHANGE.value, MovementType.LOCATION_CHANGE.value):
        raise HTTPException(status_code=422, detail="Enter the proposed new value.")

    # Validate the new value NOW, not on the effective date: an approved movement that then
    # fails to apply is a decision nobody can see was never carried out.
    if movement_type in (MovementType.DESIGNATION_CHANGE.value, MovementType.PROMOTION.value):
        try:
            ok = await get_collection(COLL_DESIGNATIONS).find_one(
                {"_id": ObjectId(to_value), "company_id": str(company_id)}, {"_id": 1})
        except (InvalidId, TypeError):
            ok = None
        if not ok:
            raise HTTPException(status_code=422, detail="Choose a designation that exists in this company.")
    if movement_type == MovementType.COMPENSATION_CHANGE.value:
        try:
            amount = float(to_value)
        except ValueError:
            raise HTTPException(status_code=422, detail="Enter the new monthly salary as a number.")
        if amount <= 0:
            raise HTTPException(status_code=422, detail="The new monthly salary must be more than zero.")
        if current_value is None:
            raise HTTPException(
                status_code=422,
                detail="This employee has no salary set yet. Set it on their Salary tab first; "
                       "a compensation change then revises it.")
    if current_value is not None and str(current_value) == to_value:
        raise HTTPException(status_code=422, detail="That is what they already have — nothing would change.")
    pending = await get_collection(COLL_EMPLOYEE_MOVEMENTS).find_one({
        "company_id": str(company_id), "employee_code": employee_code,
        "movement_type": movement_type,
        "status": {"$in": [MovementStatus.PENDING.value, MovementStatus.APPROVED.value]}})
    if pending:
        raise HTTPException(
            status_code=409,
            detail=(f"{pending['move_no']} ({getattr(movement_type, 'value', movement_type)}, "
                    f"{pending['status']}) is already open "
                    f"for this employee. Approve or reject it first."))

    year = datetime.now(timezone.utc).year
    move_no = await next_business_id("movement", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "move_no": move_no,
        "company_id": str(company_id),
        "employee_code": employee_code,
        "employee_name": await scope.name_of(profile),
        "initiated_by": str(actor.get("_id") or ""),
        "movement_type": movement_type,
        "current_value": current_value,
        "proposed_value": to_value,
        "effective_date": effective_date,
        "reason": payload.get("reason"),
        "supporting_document": payload.get("supporting_document"),
        "status": MovementStatus.PENDING.value,
        "field_applied": movement_type in MOVEMENT_APPLIABLE_TYPES,
        "action_by": None, "action_at": None, "action_remarks": None,
        "applied_at": None,
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_EMPLOYEE_MOVEMENTS).insert_one(doc)
    await audit(actor, AUDIT_MOVEMENT_INITIATED, ENTITY_MOVEMENT, move_no,
               f"{employee_code}, {movement_type}: {current_value} -> {payload.get('to_value')}",
               company_id)
    return _out(doc)


async def list_movements(actor: dict, company_id: str, *, employee_code: Optional[str] = None,
                         status: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if employee_code:
        query["employee_code"] = employee_code
    if status:
        query["status"] = status
    # A manager sees their team's movements (salary changes included), not the company's.
    from app.services import hrms_people_scope as scope
    limit_to = await scope.scope_filter(actor, company_id, initiated_field="initiated_by")
    if limit_to:
        query.update(limit_to)
    rows = await get_collection(COLL_EMPLOYEE_MOVEMENTS).find(query).sort(
        "created_at", -1).to_list(min(limit, MAX_MOVEMENT_LIST_PAGE))
    return [_out(r) for r in rows]


async def _get_movement(company_id: str, move_no: str) -> dict:
    doc = await get_collection(COLL_EMPLOYEE_MOVEMENTS).find_one(
        {"company_id": str(company_id), "move_no": move_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Movement '{move_no}' not found.")
    return doc


async def act_on_movement(actor: dict, company_id: str, move_no: str, payload: dict) -> dict:
    """§7.16 steps 123-124: approve or reject. An approval scheduled for today (or a past
    date reaching this service late) is applied immediately; a future-dated one waits for
    `apply_due_movements`."""
    doc = await _get_movement(company_id, move_no)
    if doc["status"] != MovementStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"{move_no} is already \"{doc['status']}\".")
    # Two people: whoever proposed it does not also approve it, and nobody decides their own.
    if doc.get("initiated_by") and doc["initiated_by"] == str(actor.get("_id") or ""):
        raise HTTPException(status_code=403,
                            detail="You proposed this movement, so someone else must approve or reject it.")
    from app.services import hrms_people_scope as scope
    if (await scope.own_code(actor, company_id)) == doc["employee_code"]:
        raise HTTPException(status_code=403, detail="You cannot decide a movement about yourself.")

    approved = bool(payload.get("approved"))
    now = datetime.now(timezone.utc)
    new_status = MovementStatus.APPROVED.value if approved else MovementStatus.REJECTED.value
    await get_collection(COLL_EMPLOYEE_MOVEMENTS).update_one(
        {"company_id": str(company_id), "move_no": move_no},
        {"$set": {"status": new_status, "action_by": str(actor.get("_id") or ""),
                  "action_at": now, "action_remarks": payload.get("remarks"), "updated_at": now}},
    )
    await audit(actor, AUDIT_MOVEMENT_ACTIONED, ENTITY_MOVEMENT, move_no, new_status, company_id)

    if approved and doc["effective_date"] <= _today():
        return await _apply_one(company_id, await _get_movement(company_id, move_no))
    return _out(await _get_movement(company_id, move_no))


async def _apply_one(company_id: str, movement: dict) -> dict:
    """§7.16 steps 125-126: on effective date, the live record changes and the prior value
    is closed in history (this row, left exactly as it was approved)."""
    now = datetime.now(timezone.utc)
    movement_type = movement["movement_type"]
    employee_code = movement["employee_code"]
    to_value = movement["proposed_value"]

    if movement_type in (MovementType.DESIGNATION_CHANGE.value, MovementType.PROMOTION.value):
        # Validate the target designation exists in this company before pointing the
        # employee's live profile at it.
        try:
            desig = await get_collection(COLL_DESIGNATIONS).find_one(
                {"_id": ObjectId(str(to_value)), "company_id": str(company_id)})
        except (InvalidId, TypeError):
            desig = None
        if not desig:
            raise HTTPException(
                status_code=422, detail="The proposed designation does not exist in this company.")
        await get_collection(COLL_EMPLOYEE_PROFILES).update_one(
            {"company_id": str(company_id), "employee_code": employee_code},
            {"$set": {"designation_id": to_value, "updated_at": now}})
    elif movement_type == MovementType.COMPENSATION_CHANGE.value:
        try:
            new_salary = float(to_value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Proposed compensation must be numeric.")
        await get_collection(COLL_EMPLOYEE_PROFILES).update_one(
            {"company_id": str(company_id), "employee_code": employee_code},
            {"$set": {"base_salary": new_salary, "updated_at": now}})
        # Payroll pays from the SALARY STRUCTURE, never from base_salary — so an approved
        # revision used to change nothing anybody was paid. It now becomes a new structure
        # from the effective date: every earning line scaled to the new monthly total (the
        # rounding remainder on the largest), deductions left as they were.
        from app.services.hrms_payroll_service import (
            get_current_structure, _load_component_types, _component_type_cache)
        from app.models.hrms import COLL_SALARY_STRUCTURES, ComponentType
        await _load_component_types(company_id)
        base = await get_current_structure(company_id, employee_code, movement["effective_date"])
        if base and base.get("components"):
            lines = [dict(c) for c in base["components"]]
            earn = [c for c in lines if _component_type_cache.get(c.get("code")) == ComponentType.EARNING.value]
            old_total = sum(float(c.get("amount") or 0) for c in earn)
            if old_total > 0:
                for c in earn:
                    c["amount"] = round(float(c["amount"]) * new_salary / old_total, 2)
                largest = max(earn, key=lambda c: c["amount"])
                largest["amount"] = round(largest["amount"] + new_salary - sum(c["amount"] for c in earn), 2)
                await get_collection(COLL_SALARY_STRUCTURES).insert_one({
                    "company_id": str(company_id), "employee_code": employee_code,
                    "effective_from": movement["effective_date"], "components": lines,
                    "source_movement": movement["move_no"], "created_at": now, "updated_at": now})
    elif movement_type == MovementType.MANAGER_CHANGE.value:
        profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
            {"company_id": str(company_id), "employee_code": employee_code})
        user_id = (profile or {}).get("user_id")
        if user_id:
            for coll in USER_COLLECTIONS:
                result = await get_collection(coll).update_one(
                    {"_id": ObjectId(str(user_id))}, {"$set": {"reporting_manager": to_value}})
                if result.matched_count:
                    break
    # Grade / Location: nothing to write — no live field exists for either yet.

    await get_collection(COLL_EMPLOYEE_MOVEMENTS).update_one(
        {"_id": movement["_id"]},
        {"$set": {"status": MovementStatus.APPLIED.value, "applied_at": now, "updated_at": now}},
    )
    # No real actor: this fires from apply_due_movements' sweep, not a session request.
    # audit() accepts None for exactly this case and records "system" rather than a fake id.
    await audit(None, AUDIT_MOVEMENT_APPLIED, ENTITY_MOVEMENT,
               movement["move_no"], f"{movement_type} applied for {employee_code}", company_id)
    saved = await get_collection(COLL_EMPLOYEE_MOVEMENTS).find_one({"_id": movement["_id"]})
    return _out(saved)


async def apply_due_movements(company_id: str) -> list:
    """Every approved movement whose effective date has arrived, applied now. Called from the
    list route so a page load itself catches up any that became due since the last request —
    there is no scheduler in this codebase to run it on a clock."""
    today = _today()
    due = await get_collection(COLL_EMPLOYEE_MOVEMENTS).find({
        "company_id": str(company_id), "status": MovementStatus.APPROVED.value,
        "effective_date": {"$lte": today},
    }).to_list(MAX_MOVEMENT_LIST_PAGE)
    applied = []
    for movement in due:
        try:
            applied.append(await _apply_one(company_id, movement))
        except HTTPException:
            continue  # left Approved; a bad designation reference should not wedge the sweep
    return applied
