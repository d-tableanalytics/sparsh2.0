"""HRMS > Leave & Compensatory Off (BA/Functional Design v2.2, §7.10, §7.11, §22.8).

Leave: apply -> balance/eligibility validated -> reporting manager -> HR -> ledger updated;
cancellation restores the balance. C-Off is a two-sided ledger of individually-expiring
batches (§7.11): APPROVED WORK on a weekly-off/holiday earns a credit with its own expiry;
a later leave application of type "C-Off" (§22.8: "must be available in leave dropdown and
use C-Off earned balance") debits the oldest unexpired batches first.

-- Leave-type policy is NOT frozen -----------------------------------------------------------
See the Phase ATT-1 docstring in models/hrms.py. `hrms_leave_types` is seeded per company from
DEFAULT_LEAVE_TYPES the first time it is read, exactly as an adjustable starting point; nothing
here computes CL/SL/EL entitlement, accrual or lapse from a hardcoded number — every figure this
module uses comes from that row, so a client-confirmed policy takes effect by editing data, not
by a code change.

-- Ownership scoping mirrors hrms_attendance_service --------------------------------------------
An EMPLOYEE sees and applies for their own leave/C-Off only; a MANAGER additionally sees and
acts on their team's. See `_scope_query` / `_assert_self_or_privileged`.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_COFF_EARN_ACTIONED, AUDIT_COFF_EARN_REQUESTED,
    AUDIT_LEAVE_ACTIONED, AUDIT_LEAVE_APPLIED, AUDIT_LEAVE_BALANCE_ADJUSTED,
    AUDIT_LEAVE_CANCELLED, AUDIT_LEAVE_TYPE_SAVED,
    COLL_COFF_LEDGER, COLL_EMPLOYEE_PROFILES, COLL_LEAVE_BALANCES, COLL_LEAVE_TYPES,
    COLL_LEAVES,
    DEFAULT_LEAVE_TYPES,
    ENTITY_COFF, ENTITY_LEAVE_REQUEST, ENTITY_LEAVE_TYPE,
    MAX_ATTENDANCE_LIST_PAGE,
    CoffLedgerStatus, HrmsRole, LeaveStatus, OPEN_LEAVE_STATUSES,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import hrms_role
from app.utils.hrms_access import sees_all_people

USER_COLLECTIONS = ("learners", "staff")


# ─────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────
def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _out_with_id(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_between(start: str, end: str) -> int:
    y1, m1, d1 = (int(x) for x in start.split("-"))
    y2, m2, d2 = (int(x) for x in end.split("-"))
    return (date(y2, m2, d2) - date(y1, m1, d1)).days + 1


def _n(x) -> str:
    """2.0 -> "2", 0.5 -> "0.5": day counts read as people say them."""
    x = float(x or 0)
    return str(int(x)) if x == int(x) else f"{x:g}"


def _iso(d: str) -> date:
    y, m, dd = (int(x) for x in d.split("-"))
    return date(y, m, dd)


async def _company_holidays(company_id: str) -> set:
    """This company's holiday dates. Leave ALWAYS skips them when recorded — unlike the SLA
    maths, whose opt-in (`honour_holidays`) is about deadlines, not about charging someone a
    day of leave for a day the office was shut."""
    from app.models.hrms import COLL_HOLIDAYS
    rows = await get_collection(COLL_HOLIDAYS).find(
        {"company_id": str(company_id)}, {"holiday_date": 1}).to_list(1000)
    return {str(r["holiday_date"])[:10] for r in rows if r.get("holiday_date")}


def _is_working_day(d: date, holidays: set) -> bool:
    """Saturday and Sunday are off — the same WEEKEND the rest of HRMS uses
    (hrms_sla_service) — as is any date on the company's holiday calendar."""
    from app.services.hrms_sla_service import WEEKEND
    return d.weekday() not in WEEKEND and d.isoformat() not in holidays


async def _working_days(company_id: str, start: str, end: str) -> list:
    """The working dates in [start, end]. Leave is charged for these only: a Friday-to-
    Monday leave is 2 days, not 4 — the weekend was never a day anybody had to take off."""
    holidays = await _company_holidays(company_id)
    out, cursor, last = [], _iso(start), _iso(end)
    while cursor <= last:
        if _is_working_day(cursor, holidays):
            out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


async def _person(profile: dict) -> str:
    from app.services.hrms_payroll_service import _employee_names, _name_of
    return _name_of(profile, await _employee_names([profile])) or profile.get("employee_code")


async def _overlapping_leave(company_id: str, employee_code: str, start: str, end: str,
                             exclude_leave_no: Optional[str] = None) -> Optional[dict]:
    """An open or approved leave of this employee that shares any date with [start, end]."""
    query = {"company_id": str(company_id), "employee_code": employee_code,
             "status": {"$in": list(OPEN_LEAVE_STATUSES | {LeaveStatus.APPROVED.value})},
             "start_date": {"$lte": end}, "end_date": {"$gte": start}}
    if exclude_leave_no:
        query["leave_no"] = {"$ne": exclude_leave_no}
    return await get_collection(COLL_LEAVES).find_one(query)


async def _pending_days(company_id: str, employee_code: str, leave_type: str,
                        year: Optional[int] = None) -> float:
    """Days already asked for and not yet decided. The balance is only debited at final
    approval, so without counting these, two pending 7-day requests against 8 days each
    passed the check — and approving both took the balance to -6."""
    rows = await get_collection(COLL_LEAVES).find({
        "company_id": str(company_id), "employee_code": employee_code,
        "leave_type": leave_type, "status": {"$in": list(OPEN_LEAVE_STATUSES)},
    }).to_list(500)
    return sum(float(r.get("days_count") or 0) for r in rows
               if year is None or str(r.get("start_date", ""))[:4] == str(year))


async def _get_profile(company_id: str, employee_code: str) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(status_code=404, detail="No employee with that code in this company.")
    return profile


async def _reporting_manager_id(profile: dict) -> Optional[str]:
    user_id = profile.get("user_id")
    if not user_id:
        return None
    from bson import ObjectId
    from bson.errors import InvalidId
    try:
        oid = ObjectId(str(user_id))
    except (InvalidId, TypeError):
        return None
    for coll in USER_COLLECTIONS:
        user = await get_collection(coll).find_one({"_id": oid})
        if user:
            return user.get("reporting_manager")
    return None


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    actor_id = str(actor.get("_id") or "")
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": actor_id})
    return (profile or {}).get("employee_code")


async def _team_employee_codes(actor: dict, company_id: str) -> list:
    actor_id = str(actor.get("_id") or "")
    reports = []
    for coll in USER_COLLECTIONS:
        rows = await get_collection(coll).find(
            {"reporting_manager": actor_id}, {"_id": 1}).to_list(2000)
        reports.extend(str(r["_id"]) for r in rows)
    if not reports:
        return []
    profiles = await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id), "user_id": {"$in": reports}},
        {"employee_code": 1}).to_list(2000)
    return [p["employee_code"] for p in profiles if p.get("employee_code")]


async def _scope_query(actor: dict, company_id: str, query: dict) -> dict:
    # Scoped by what the role is FOR, not by `role == EMPLOYEE`: every staff member now
    # holds the read capability for their OWN records, so an EMPLOYEE-only check would hand
    # Finance, support staff and everyone else the whole company's.
    if sees_all_people(actor):
        return query
    own = await _own_employee_code(actor, company_id)
    if hrms_role(actor) == HrmsRole.MANAGER:
        team = await _team_employee_codes(actor, company_id)
        codes = list({c for c in ([own] if own else []) + team})
        query["employee_code"] = {"$in": codes or ["__none__"]}
    else:
        query["employee_code"] = own or "__none__"
    return query


async def _assert_self_or_privileged(actor: dict, company_id: str, employee_code: str) -> None:
    role = hrms_role(actor)
    if role in (HrmsRole.HR, HrmsRole.MD, HrmsRole.ADMIN, None):
        return
    own = await _own_employee_code(actor, company_id)
    if own and own == employee_code:
        return
    if role == HrmsRole.MANAGER and employee_code in await _team_employee_codes(actor, company_id):
        return
    raise HTTPException(status_code=403, detail="You may only act on your own record.")


async def _assert_may_decide(actor: dict, company_id: str, employee_code: str, what: str) -> None:
    """Nobody decides their own request; a manager decides only for their own team."""
    own = await _own_employee_code(actor, company_id)
    if own and own == employee_code:
        raise HTTPException(status_code=403, detail=f"You cannot approve your own {what}.")
    if hrms_role(actor) == HrmsRole.MANAGER and \
            employee_code not in await _team_employee_codes(actor, company_id):
        raise HTTPException(status_code=403,
                            detail=f"A manager can decide {what} only for their own team.")


# ─────────────────────────────────────────────────────────────
# §22.8 — leave-type policy register
# ─────────────────────────────────────────────────────────────
async def _ensure_seeded(company_id: str) -> None:
    coll = get_collection(COLL_LEAVE_TYPES)
    if await coll.count_documents({"company_id": str(company_id)}) > 0:
        return
    now = datetime.now(timezone.utc)
    rows = [{**t, "company_id": str(company_id), "policy_confirmed": False, "active": True,
            "created_at": now, "updated_at": now} for t in DEFAULT_LEAVE_TYPES]
    if rows:
        await coll.insert_many(rows)


async def list_leave_types(actor: dict, company_id: str) -> list:
    await _ensure_seeded(company_id)
    rows = await get_collection(COLL_LEAVE_TYPES).find(
        {"company_id": str(company_id)}).sort("code", 1).to_list(100)
    return [_out(r) for r in rows]


async def _get_leave_type(company_id: str, code: str) -> dict:
    await _ensure_seeded(company_id)
    doc = await get_collection(COLL_LEAVE_TYPES).find_one(
        {"company_id": str(company_id), "code": code})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Leave type '{code}' is not configured.")
    return doc


async def save_leave_type(actor: dict, company_id: str, payload: dict) -> dict:
    code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=422, detail="A leave type code is required.")
    now = datetime.now(timezone.utc)
    clean = {k: v for k, v in payload.items() if k != "code"}
    clean["updated_at"] = now
    await get_collection(COLL_LEAVE_TYPES).update_one(
        {"company_id": str(company_id), "code": code},
        {"$set": clean, "$setOnInsert": {"company_id": str(company_id), "code": code,
                                         "created_at": now}},
        upsert=True,
    )
    await audit(actor, AUDIT_LEAVE_TYPE_SAVED, ENTITY_LEAVE_TYPE, code,
               f"entitlement={payload.get('annual_entitlement')}, "
               f"confirmed={payload.get('policy_confirmed')}", company_id)
    return _out(await _get_leave_type(company_id, code))


# ─────────────────────────────────────────────────────────────
# Balances
# ─────────────────────────────────────────────────────────────
async def _get_balance(company_id: str, employee_code: str, leave_type: str, year: int) -> dict:
    coll = get_collection(COLL_LEAVE_BALANCES)
    doc = await coll.find_one({"company_id": str(company_id), "employee_code": employee_code,
                               "leave_type": leave_type, "year": year})
    if doc:
        return doc
    leave_cfg = await _get_leave_type(company_id, leave_type)
    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "employee_code": employee_code, "leave_type": leave_type,
        "year": year, "opening": 0, "accrued": leave_cfg.get("annual_entitlement", 0),
        "used": 0, "adjusted": 0, "encashed": 0, "carried_forward_in": 0,
        "created_at": now, "updated_at": now,
    }
    await coll.insert_one(doc)
    return doc


def _closing(bal: dict) -> float:
    return (bal.get("opening", 0) + bal.get("carried_forward_in", 0) + bal.get("accrued", 0)
            + bal.get("adjusted", 0) - bal.get("used", 0) - bal.get("encashed", 0))


async def get_leave_balances(actor: dict, company_id: str, employee_code: str,
                             year: Optional[int] = None) -> list:
    await _get_profile(company_id, employee_code)
    # Your own balance, your team's if you manage one, anyone's for HR/MD. Found by the live
    # self-service test: any caller holding LEAVE_READ could read any colleague's balance.
    await _assert_self_or_privileged(actor, company_id, employee_code)
    year = year or datetime.now(timezone.utc).year
    types = await list_leave_types(actor, company_id)
    out = []
    for t in types:
        if t["code"] == "C-Off":
            out.append({"leave_type": "C-Off", "year": year,
                       "closing": await _coff_available_balance(company_id, employee_code)})
            continue
        bal = await _get_balance(company_id, employee_code, t["code"], year)
        out.append({**_out(bal), "closing": _closing(bal)})
    return out


async def adjust_leave_balance(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    leave_type = payload.get("leave_type")
    year = int(payload.get("year") or datetime.now(timezone.utc).year)
    await _get_profile(company_id, employee_code)
    bal = await _get_balance(company_id, employee_code, leave_type, year)
    now = datetime.now(timezone.utc)
    await get_collection(COLL_LEAVE_BALANCES).update_one(
        {"_id": bal["_id"]},
        {"$inc": {"adjusted": float(payload.get("adjustment_days") or 0)},
         "$set": {"updated_at": now}},
    )
    await audit(actor, AUDIT_LEAVE_BALANCE_ADJUSTED, ENTITY_LEAVE_REQUEST,
               f"{employee_code}:{leave_type}:{year}",
               f"{payload.get('adjustment_days')}d — {payload.get('reason')}", company_id)
    return _out(await _get_balance(company_id, employee_code, leave_type, year))


# ─────────────────────────────────────────────────────────────
# §7.10 — Leave application & approval
# ─────────────────────────────────────────────────────────────
async def apply_leave(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    leave_type = payload.get("leave_type")
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")
    if not (employee_code and leave_type and start_date and end_date):
        raise HTTPException(
            status_code=422,
            detail="employee_code, leave_type, start_date and end_date are required.")
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date cannot be before start_date.")

    profile = await _get_profile(company_id, employee_code)
    await _assert_self_or_privileged(actor, company_id, employee_code)
    leave_cfg = await _get_leave_type(company_id, leave_type)
    if not leave_cfg.get("active", True):
        raise HTTPException(status_code=422, detail=f"'{leave_type}' is not an active leave type.")

    half_day = bool(payload.get("half_day"))
    if half_day and end_date != start_date:
        raise HTTPException(status_code=422, detail="A half day is a single date — set the end date to the start date.")
    working = await _working_days(company_id, start_date, end_date)
    if not working:
        raise HTTPException(
            status_code=422,
            detail="Every date chosen is a weekend or a company holiday — no leave is needed.")
    days_count = 0.5 if half_day else float(len(working))

    clash = await _overlapping_leave(company_id, employee_code, start_date, end_date)
    if clash:
        raise HTTPException(
            status_code=409,
            detail=(f"{await _person(profile)} already has {clash['leave_no']} "
                    f"({clash['leave_type']}, {clash['start_date']} to {clash['end_date']}, "
                    f"{clash['status']}) on some of these dates."))

    # §7.10 step 71: eligibility/balance validation before the request is even raised —
    # against what is left once the requests still awaiting a decision are counted.
    if leave_type == "C-Off":
        available = (await _coff_available_balance(company_id, employee_code)
                     - await _pending_days(company_id, employee_code, "C-Off"))
        if days_count > available:
            raise HTTPException(
                status_code=422,
                detail=f"Only {_n(max(available, 0))} C-Off day(s) available; {_n(days_count)} requested.")
    else:
        year = int(start_date[:4])
        bal = await _get_balance(company_id, employee_code, leave_type, year)
        pending = await _pending_days(company_id, employee_code, leave_type, year)
        available = _closing(bal) - pending
        if days_count > available:
            raise HTTPException(
                status_code=422,
                detail=(f"Insufficient {leave_type} balance: {_n(max(available, 0))} available"
                        f"{f' ({_n(pending)} more already requested and awaiting approval)' if pending else ''}, "
                        f"{_n(days_count)} requested."))

    year = datetime.now(timezone.utc).year
    leave_no = await next_business_id("leave", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "leave_no": leave_no,
        "company_id": str(company_id),
        "employee_code": employee_code,
        "employee_name": await _person(profile),
        "reporting_manager_id": await _reporting_manager_id(profile),
        "leave_type": leave_type,
        "start_date": start_date,
        "end_date": end_date,
        "half_day": half_day,
        "half_session": payload.get("half_session"),
        "days_count": days_count,
        "leave_dates": working[:1] if half_day else working,
        "reason": payload.get("reason"),
        "attachment": payload.get("attachment"),
        "status": LeaveStatus.PENDING.value,
        "manager_action_by": None, "manager_action_at": None, "manager_remarks": None,
        "hr_action_by": None, "hr_action_at": None, "hr_remarks": None,
        "cancelled_reason": None, "cancelled_at": None,
        "coff_batches_used": [],
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_LEAVES).insert_one(doc)
    await audit(actor, AUDIT_LEAVE_APPLIED, ENTITY_LEAVE_REQUEST, leave_no,
               f"{employee_code}, {leave_type}, {start_date}..{end_date} ({days_count}d)",
               company_id)
    return _out(doc)


async def list_leaves(actor: dict, company_id: str, *, status: Optional[str] = None,
                      employee_code: Optional[str] = None, leave_type: Optional[str] = None,
                      limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if employee_code:
        query["employee_code"] = employee_code
    if leave_type:
        query["leave_type"] = leave_type
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_LEAVES).find(query).sort(
        "created_at", -1).to_list(min(limit, MAX_ATTENDANCE_LIST_PAGE))
    return [_out(r) for r in rows]


async def _get_leave(company_id: str, leave_no: str) -> dict:
    doc = await get_collection(COLL_LEAVES).find_one(
        {"company_id": str(company_id), "leave_no": leave_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Leave request '{leave_no}' not found.")
    return doc


async def act_on_leave(actor: dict, company_id: str, leave_no: str, payload: dict) -> dict:
    """§7.10 steps 73-75: manager, then HR; approval updates the ledger and the attendance
    calendar. Mirrors act_on_regularization's two-stage shape exactly."""
    doc = await _get_leave(company_id, leave_no)
    if doc["status"] not in (LeaveStatus.PENDING.value, LeaveStatus.MANAGER_APPROVED.value):
        raise HTTPException(status_code=409, detail=f"{leave_no} is already \"{doc['status']}\".")
    await _assert_may_decide(actor, company_id, doc["employee_code"], "leave")

    decision = payload.get("decision")
    now = datetime.now(timezone.utc)
    updates = {"updated_at": now}

    if decision == LeaveStatus.REJECTED.value:
        updates["status"] = LeaveStatus.REJECTED.value
    elif decision == LeaveStatus.RETURNED.value:
        updates["status"] = LeaveStatus.RETURNED.value
    elif decision == LeaveStatus.MANAGER_APPROVED.value:
        if doc["status"] != LeaveStatus.PENDING.value:
            raise HTTPException(status_code=409, detail=f"{leave_no} already passed the manager step.")
        updates.update({"status": LeaveStatus.MANAGER_APPROVED.value,
                        "manager_action_by": str(actor.get("_id") or ""),
                        "manager_action_at": now, "manager_remarks": payload.get("remarks")})
    elif decision == LeaveStatus.APPROVED.value:
        if doc["status"] != LeaveStatus.MANAGER_APPROVED.value:
            raise HTTPException(
                status_code=409,
                detail=f"{leave_no} needs the manager's approval before HR's final sign-off.")
        # Two steps are only two checks if two people take them.
        if doc.get("manager_action_by") and doc["manager_action_by"] == str(actor.get("_id") or ""):
            raise HTTPException(
                status_code=409,
                detail=(f"You gave the manager approval for {leave_no}, so the final approval "
                        f"must come from someone else in HR."))
        await _debit_on_approval(company_id, doc, now)
        updates.update({"status": LeaveStatus.APPROVED.value,
                        "hr_action_by": str(actor.get("_id") or ""),
                        "hr_action_at": now, "hr_remarks": payload.get("remarks")})
    else:
        raise HTTPException(status_code=422, detail=f"Unrecognised decision '{decision}'.")

    await get_collection(COLL_LEAVES).update_one(
        {"company_id": str(company_id), "leave_no": leave_no}, {"$set": updates})
    await audit(actor, AUDIT_LEAVE_ACTIONED, ENTITY_LEAVE_REQUEST, leave_no, decision, company_id)
    return _out(await _get_leave(company_id, leave_no))


async def _debit_on_approval(company_id: str, leave: dict, now: datetime) -> None:
    """§7.10 step 75: ledger + attendance calendar update on final approval."""
    if leave["leave_type"] == "C-Off":
        usage = await _debit_coff(
            company_id, leave["employee_code"], leave["days_count"], leave["leave_no"])
        await get_collection(COLL_LEAVES).update_one(
            {"_id": leave["_id"]},
            {"$set": {"coff_batches_used": [u["batch_id"] for u in usage], "coff_usage": usage}})
    else:
        year = int(leave["start_date"][:4])
        bal = await _get_balance(company_id, leave["employee_code"], leave["leave_type"], year)
        # Re-checked here, not just at apply: the balance may have moved since.
        if leave["days_count"] > _closing(bal):
            raise HTTPException(
                status_code=409,
                detail=(f"Only {_n(_closing(bal))} {leave['leave_type']} day(s) left now, and "
                        f"{leave['leave_no']} needs {_n(leave['days_count'])}. Reject or return it."))
        await get_collection(COLL_LEAVE_BALANCES).update_one(
            {"_id": bal["_id"]},
            {"$inc": {"used": leave["days_count"]}, "$set": {"updated_at": now}})

    # Attendance calendar: mark the leave's WORKING days On Leave (a weekend inside the range
    # stays a Weekly Off), unless already locked. The day's previous status is kept so a
    # cancellation can put it back rather than leave "On Leave" behind.
    dates = leave.get("leave_dates") or await _working_days(
        company_id, leave["start_date"], leave["end_date"])
    from app.models.hrms import AttendanceStatus
    from app.db.mongodb import get_collection as _gc
    for wd in dates:
        existing = await _gc("hrms_attendance").find_one(
            {"company_id": str(company_id), "employee_code": leave["employee_code"], "work_date": wd})
        if existing and existing.get("locked"):
            continue
        keep = {}
        if existing and existing.get("leave_ref") != leave["leave_no"]:
            keep = {"pre_leave_status": existing.get("status")}
        await _gc("hrms_attendance").update_one(
            {"company_id": str(company_id), "employee_code": leave["employee_code"],
             "work_date": wd},
            {"$set": {"status": AttendanceStatus.ON_LEAVE.value, "source": "leave",
                      "leave_ref": leave["leave_no"], "updated_at": now, **keep},
             "$setOnInsert": {"company_id": str(company_id),
                              "employee_code": leave["employee_code"], "work_date": wd,
                              "created_at": now, "locked": False, "worked_minutes": None,
                              "late_minutes": 0, "created_by_leave": True}},
            upsert=True,
        )


async def _undo_leave_attendance(company_id: str, leave_no: str) -> None:
    """Put attendance back the way it was before `leave_no` was approved. A day the leave
    itself created is removed; a day that already had a status gets that status back. Locked
    days are left alone — a closed month is changed only by an authorised reopen."""
    coll = get_collection("hrms_attendance")
    rows = await coll.find({"company_id": str(company_id), "leave_ref": leave_no}).to_list(400)
    for r in rows:
        if r.get("locked"):
            continue
        if r.get("pre_leave_status"):
            await coll.update_one({"_id": r["_id"]}, {
                "$set": {"status": r["pre_leave_status"], "updated_at": datetime.now(timezone.utc)},
                "$unset": {"leave_ref": "", "source": "", "pre_leave_status": ""}})
        else:
            await coll.delete_one({"_id": r["_id"]})


async def cancel_leave(actor: dict, company_id: str, leave_no: str, reason: str) -> dict:
    """§7.10 step 76: controlled withdrawal, restoring whatever it consumed."""
    doc = await _get_leave(company_id, leave_no)
    if doc["status"] not in OPEN_LEAVE_STATUSES | {LeaveStatus.APPROVED.value}:
        raise HTTPException(status_code=409, detail=f"{leave_no} cannot be cancelled from "
                                                     f"\"{doc['status']}\".")
    was_approved = doc["status"] == LeaveStatus.APPROVED.value
    now = datetime.now(timezone.utc)
    await get_collection(COLL_LEAVES).update_one(
        {"_id": doc["_id"]},
        {"$set": {"status": LeaveStatus.CANCELLED.value, "cancelled_reason": reason,
                  "cancelled_at": now, "updated_at": now}},
    )
    if was_approved:
        await _undo_leave_attendance(company_id, leave_no)
        if doc["leave_type"] == "C-Off" and doc.get("coff_usage"):
            # Give back exactly what this leave took from each batch — a half-day leave
            # took half a day, and must not hand back a whole one.
            from bson import ObjectId
            for u in doc["coff_usage"]:
                await get_collection(COLL_COFF_LEDGER).update_one(
                    {"_id": ObjectId(u["batch_id"]), "company_id": str(company_id)},
                    {"$inc": {"remaining_days": float(u["days"])},
                     "$set": {"status": CoffLedgerStatus.AVAILABLE.value},
                     "$pull": {"usage": {"leave_no": leave_no}}})
        elif doc["leave_type"] == "C-Off":
            # Scoped by company: `leave_no` is issued per company, so unscoped this frees the
            # comp-off credits consumed by the same-numbered leave in EVERY other tenant.
            await get_collection(COLL_COFF_LEDGER).update_many(
                {"used_in_leave_no": leave_no, "company_id": str(company_id)},
                {"$set": {"status": CoffLedgerStatus.AVAILABLE.value, "used_in_leave_no": None,
                          "used_at": None}})
        else:
            year = int(doc["start_date"][:4])
            bal = await _get_balance(company_id, doc["employee_code"], doc["leave_type"], year)
            await get_collection(COLL_LEAVE_BALANCES).update_one(
                {"_id": bal["_id"]},
                {"$inc": {"used": -doc["days_count"]}, "$set": {"updated_at": now}})
    await audit(actor, AUDIT_LEAVE_CANCELLED, ENTITY_LEAVE_REQUEST, leave_no, reason, company_id)
    return _out(await _get_leave(company_id, leave_no))


# ─────────────────────────────────────────────────────────────
# §7.11 — Compensatory Off (earn -> ledger -> use)
# ─────────────────────────────────────────────────────────────
async def request_coff_earn(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    earned_for_date = str(payload.get("earned_for_date") or "").strip()
    if not (employee_code and earned_for_date):
        raise HTTPException(
            status_code=422, detail="employee_code and earned_for_date are required.")
    await _get_profile(company_id, employee_code)
    await _assert_self_or_privileged(actor, company_id, employee_code)
    try:
        worked_on = _iso(earned_for_date)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="The worked date must be YYYY-MM-DD.")
    if earned_for_date > _today():
        raise HTTPException(status_code=422, detail="C-Off is claimed after the day was worked, not before.")
    if _is_working_day(worked_on, await _company_holidays(company_id)):
        raise HTTPException(
            status_code=422,
            detail=(f"{worked_on.strftime('%a %d %b %Y')} is a normal working day. C-Off is earned "
                    f"only for work on a weekend or a company holiday."))
    already = await get_collection(COLL_COFF_LEDGER).find_one({
        "company_id": str(company_id), "employee_code": employee_code,
        "earned_for_date": earned_for_date,
        "status": {"$ne": CoffLedgerStatus.REJECTED.value}})
    if already:
        raise HTTPException(
            status_code=409,
            detail=f"{earned_for_date} has already been claimed ({already['status']}).")

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "employee_code": employee_code,
        "earned_for_date": earned_for_date, "note": payload.get("note"),
        "status": CoffLedgerStatus.PENDING_APPROVAL.value,
        "credited_days": 1,
        "approved_by": None, "approved_at": None,
        "expiry_date": None,               # set on approval, from the C-Off policy's expiry days
        "used_in_leave_no": None, "used_at": None,
        "created_at": now, "updated_at": now,
    }
    result = await get_collection(COLL_COFF_LEDGER).insert_one(doc)
    doc["_id"] = result.inserted_id
    await audit(actor, AUDIT_COFF_EARN_REQUESTED, ENTITY_COFF, str(doc["_id"]),
               f"{employee_code}, worked {earned_for_date}", company_id)
    return _out_with_id(doc)


async def list_coff_ledger(actor: dict, company_id: str, *, employee_code: Optional[str] = None,
                           status: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if employee_code:
        query["employee_code"] = employee_code
    if status:
        query["status"] = status
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_COFF_LEDGER).find(query).sort(
        "created_at", -1).to_list(min(limit, MAX_ATTENDANCE_LIST_PAGE))
    return [_out_with_id(r) for r in rows]


async def act_on_coff_earn(actor: dict, company_id: str, batch_id: str, payload: dict) -> dict:
    from bson import ObjectId
    from bson.errors import InvalidId
    try:
        oid = ObjectId(str(batch_id))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid C-Off batch id.")
    doc = await get_collection(COLL_COFF_LEDGER).find_one(
        {"_id": oid, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="C-Off earn request not found.")
    if doc["status"] != CoffLedgerStatus.PENDING_APPROVAL.value:
        raise HTTPException(status_code=409, detail=f"Already \"{doc['status']}\".")
    await _assert_may_decide(actor, company_id, doc["employee_code"], "C-Off claim")

    approved = bool(payload.get("approved"))
    now = datetime.now(timezone.utc)
    updates = {"approved_by": str(actor.get("_id") or ""), "approved_at": now,
              "remarks": payload.get("remarks"), "updated_at": now}
    if approved:
        coff_cfg = await _get_leave_type(company_id, "C-Off")
        expiry_days = int(coff_cfg.get("coff_expiry_days") or 60)
        earned = doc["earned_for_date"]
        y, m, d = (int(x) for x in earned.split("-"))
        updates["status"] = CoffLedgerStatus.AVAILABLE.value
        updates["expiry_date"] = (date(y, m, d) + timedelta(days=expiry_days)).isoformat()
        updates["remaining_days"] = float(doc.get("credited_days", 1))
    else:
        updates["status"] = CoffLedgerStatus.REJECTED.value
    await get_collection(COLL_COFF_LEDGER).update_one({"_id": oid}, {"$set": updates})
    await audit(actor, AUDIT_COFF_EARN_ACTIONED, ENTITY_COFF, str(oid),
               updates["status"], company_id)
    saved = await get_collection(COLL_COFF_LEDGER).find_one({"_id": oid})
    return _out_with_id(saved)


async def _coff_available_balance(company_id: str, employee_code: str) -> float:
    today = _today()
    rows = await get_collection(COLL_COFF_LEDGER).find({
        "company_id": str(company_id), "employee_code": employee_code,
        "status": CoffLedgerStatus.AVAILABLE.value, "expiry_date": {"$gte": today},
    }).to_list(1000)
    return sum(_left_on(r) for r in rows)


def _left_on(batch: dict) -> float:
    """What is still usable on one C-Off batch. Batches credited before partial use
    existed carry no `remaining_days`, and are whole."""
    left = batch.get("remaining_days")
    return float(batch.get("credited_days", 0) if left is None else left)


async def _debit_coff(company_id: str, employee_code: str, days_needed: float,
                      leave_no: str) -> list:
    """FIFO by nearest expiry (§7.11 step 81) — the batches actually consumed, for the
    leave record's own audit trail (`coff_batches_used`) and so cancel_leave can find and
    restore exactly these batches later."""
    today = _today()
    batches = await get_collection(COLL_COFF_LEDGER).find({
        "company_id": str(company_id), "employee_code": employee_code,
        "status": CoffLedgerStatus.AVAILABLE.value, "expiry_date": {"$gte": today},
    }).sort("expiry_date", 1).to_list(1000)

    # Take only what is needed from each batch, oldest-expiring first. A half-day leave
    # used to mark a whole one-day batch Used, silently losing the other half.
    remaining = float(days_needed)
    plan = []
    for batch in batches:
        if remaining <= 0:
            break
        take = min(_left_on(batch), remaining)
        if take <= 0:
            continue
        plan.append((batch, take))
        remaining -= take
    if remaining > 1e-9:
        raise HTTPException(status_code=409, detail="C-Off balance changed; insufficient at approval time.")

    now = datetime.now(timezone.utc)
    usage = []
    for batch, take in plan:
        left = round(_left_on(batch) - take, 2)
        await get_collection(COLL_COFF_LEDGER).update_one(
            {"_id": batch["_id"]},
            {"$set": {"remaining_days": left,
                      "status": CoffLedgerStatus.USED.value if left <= 0 else CoffLedgerStatus.AVAILABLE.value,
                      "used_at": now, "used_in_leave_no": leave_no},
             "$push": {"usage": {"leave_no": leave_no, "days": take, "at": now}}})
        usage.append({"batch_id": str(batch["_id"]), "days": take})
    return usage
