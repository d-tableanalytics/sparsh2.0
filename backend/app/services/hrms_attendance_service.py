"""HRMS > Attendance (BA/Functional Design v2.2, §7.8, §7.9, §7.12, §22.9).

Daily capture -> the engine derives status/late-minutes/worked-minutes against the company's
configured shift and grace -> exceptions are regularised (employee proposes -> manager ->
HR) -> HR locks the month, freezing an immutable snapshot for payroll to consume later
(§7.13 itself is unbuilt — see hrms_exit_service's FnfInput for the same constraint). Outdoor
Duty (§7.8 step 59) is its own small request/approval workflow, routed the same way.

-- No punch source exists yet -----------------------------------------------------------------
§7.8 names the intended source as "Biometric login/logout/live-location", with API/mobile/
import as a future option. Nothing in this codebase talks to hardware, so ATTENDANCE_MARK is
the only write path today: HR (or a manager, for their own team) records a day's punches by
hand, and the daily engine still runs the same arithmetic it would run on real punch data —
the workflow is real even though the capture is manual for now.

-- Ownership scoping is enforced here, not left as a follow-up -------------------------------
Unlike Phase EXIT-1's employee self-service caps (documented there as not yet scoped), an
EMPLOYEE-role caller's list/get/request calls in this module ARE filtered to their own
employee_code — see `_scope_query` and `_assert_self_or_privileged`.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_ATTENDANCE_LOCKED, AUDIT_ATTENDANCE_MARKED, AUDIT_ATTENDANCE_UNLOCKED, Cap,
    AUDIT_CORRECTION_ACTIONED, AUDIT_CORRECTION_REQUESTED,
    AUDIT_OD_ACTIONED, AUDIT_OD_REQUESTED,
    COLL_ATTENDANCE, COLL_ATTENDANCE_CORRECTIONS, COLL_ATTENDANCE_LOCKS,
    COLL_EMPLOYEE_PROFILES, COLL_OD_REQUESTS, COLL_PUNCH_SEGMENTS, COLL_SETTINGS,
    DEFAULT_SHIFT_POLICY,
    ENTITY_ATT_LOCK, ENTITY_ATTENDANCE, ENTITY_CORRECTION, ENTITY_OD,
    MAX_ATTENDANCE_LIST_PAGE,
    AttendanceStatus, CorrectionStatus, HrmsRole, LockStatus, OdStatus,
    compute_daily_status,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can, hrms_role
from app.utils.hrms_access import sees_all_people

USER_COLLECTIONS = ("learners", "staff")


# ─────────────────────────────────────────────────────────────
# Small helpers — same shape as hrms_exit_service's
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


def _oid(value: str, label: str = "record") -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id.")


async def _find_user(user_id: str) -> tuple:
    try:
        oid = _oid(user_id)
    except HTTPException:
        return None, None
    for coll in USER_COLLECTIONS:
        doc = await get_collection(coll).find_one({"_id": oid})
        if doc:
            return doc, coll
    return None, None


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
    user, _coll = await _find_user(user_id)
    return (user or {}).get("reporting_manager")


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    """The acting user's OWN employee_code, if they have an HR profile in this company."""
    actor_id = str(actor.get("_id") or "")
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": actor_id})
    return (profile or {}).get("employee_code")


async def _team_employee_codes(actor: dict, company_id: str) -> list:
    """A manager's own reports, by employee_code — the same directory relationship
    hrms_employee_service._manager_scope reads (`reporting_manager` on the user doc),
    resolved here to employee_code because this module addresses people that way."""
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
    """Row-scopes a list query to what `actor` may see: EMPLOYEE sees only their own
    records, MANAGER sees their own plus their team's, everyone else (HR/MD/ADMIN) sees the
    whole company — the query already carries that. Fails CLOSED: an employee with no linked
    profile sees nothing rather than everything."""
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
    """A MANAGER may act for their own team, HR/MD/ADMIN for anyone; an EMPLOYEE only for
    themselves. Raises 403 rather than silently scoping, because this guards a WRITE."""
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
# §7.8 — shift policy (company-configurable; see the Phase ATT-1 module docstring in
# models/hrms.py for why these numbers are adjustable defaults, not frozen constants)
# ─────────────────────────────────────────────────────────────
async def get_shift_policy(company_id: str) -> dict:
    from app.models.hrms import DEFAULT_ATTENDANCE_RULES
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    stored = (doc or {}).get("shift_policy") or {}
    return {**DEFAULT_SHIFT_POLICY, **DEFAULT_ATTENDANCE_RULES, **stored}


def _validate_policy(payload: dict) -> dict:
    from app.services.hrms_attendance_rules_service import _hhmm
    from app.services.hrms_shift_service import _validate_pattern
    clean = {}
    for key, value in payload.items():
        if value is None:
            continue
        if key in ("shift_start", "shift_end"):
            clean[key] = _hhmm(value, key.replace("_", " ").title())
        elif key == "weekly_off_pattern":
            clean[key] = _validate_pattern(value)
        elif key == "regularisation_evidence_required":
            clean[key] = bool(value)
        elif key == "min_hours":
            clean[key] = float(value) if value != "" else None
        elif key in ("daily_grace_minutes", "monthly_buffer_minutes",
                     "half_day_threshold_minutes", "regularisation_window_days",
                     "attendance_closing_day", "early_going_grace_minutes", "break_minutes",
                     "absent_threshold_minutes"):
            try:
                clean[key] = int(value) if value != "" else None
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"{key} must be a whole number.")
            if clean[key] is not None and clean[key] < 0:
                raise HTTPException(status_code=422, detail=f"{key} cannot be negative.")
        else:
            clean[key] = value
    if clean.get("attendance_closing_day") and not 1 <= clean["attendance_closing_day"] <= 31:
        raise HTTPException(status_code=422, detail="Closing day must be 1-31.")
    return clean


async def save_shift_policy(actor: dict, company_id: str, payload: dict) -> dict:
    merged = {**await get_shift_policy(company_id), **_validate_policy(payload)}
    if merged["shift_end"] <= merged["shift_start"]:
        raise HTTPException(status_code=422, detail="The end time must be after the start time.")
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {"shift_policy": merged, "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"company_id": str(company_id)}},
        upsert=True,
    )
    await audit(actor, "shift policy updated", ENTITY_ATTENDANCE, "policy",
               ", ".join(sorted(payload.keys())), company_id)
    return merged


async def _month_locked(company_id: str, work_date: str) -> bool:
    """A new row in a locked month would slip past the lock (only existing rows carry
    `locked`), so writers check the period itself too."""
    lock = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
        {"company_id": str(company_id), "period": str(work_date)[:7]})
    return (lock or {}).get("status") == LockStatus.LOCKED.value


async def closure_rules(company_id: str, profile: Optional[dict] = None,
                        on_date: Optional[str] = None) -> dict:
    """The ATT_CLOSURE policy in force, over the company's stored attendance rules.

    Falls back to the settings dict every company already has, so this answers identically
    for a company that has configured no closure policy.
    """
    from app.models.hrms import DEFAULT_ATTENDANCE_RULES, POLICY_ATT_CLOSURE
    from app.services import hrms_policy_version_service as PV
    settings = await get_shift_policy(company_id)
    default = {"closing_day": settings.get("attendance_closing_day")
               or DEFAULT_ATTENDANCE_RULES["attendance_closing_day"],
               "enforce_cutoff": bool(settings.get("enforce_attendance_cutoff")),
               "block_pending_requests": bool(settings.get("block_pending_at_lock"))}
    return await PV.resolve_rules(company_id, POLICY_ATT_CLOSURE, profile or {}, on_date,
                                  default=default)


async def regularisation_rules(company_id: str, profile: Optional[dict] = None,
                               on_date: Optional[str] = None) -> dict:
    """The ATT_REGULARISATION policy in force, over the company's stored settings.

    The window and the evidence flag were already enforced -- from the flat settings dict.
    This routes them through the policy spine so they can be versioned, effective-dated and
    scoped like every other §23 rule, WITHOUT changing the answer for a company that has
    configured no policy: the settings remain the fallback.
    """
    from app.models.hrms import DEFAULT_ATTENDANCE_RULES, POLICY_ATT_REGULARISATION
    from app.services import hrms_policy_version_service as PV
    settings = await get_shift_policy(company_id)
    default = {
        "window_days": settings.get("regularisation_window_days",
                                    DEFAULT_ATTENDANCE_RULES["regularisation_window_days"]),
        "evidence_required": bool(settings.get("regularisation_evidence_required")),
        "max_requests_per_month": settings.get("regularisation_max_per_month"),
        "approval_levels": settings.get("regularisation_approval_levels") or 1,
        "request_types": settings.get("regularisation_request_types") or None,
    }
    return await PV.resolve_rules(company_id, POLICY_ATT_REGULARISATION, profile or {},
                                  on_date, default=default)


async def _assert_within_cutoff(actor: dict, company_id: str, work_date: str) -> None:
    """FRD §23 Monthly Closure -- the cut-off, enforced.

    `attendance_closing_day` has been stored since the FRD's first pass and commented
    "(informational)": nothing read it, so a company could set a cut-off of the 26th and
    still have days added to the previous month in the middle of March. §5 calls it the
    "attendance closing date" and §23 makes it a configurable rule, which means it has to
    actually stop something.

    What it stops: writing to a month whose cut-off has passed. What it does NOT stop:
    anyone holding the unlock capability (ATTENDANCE_LOCK) -- the cut-off is a routine
    control, not a wall, and the authority that can reopen a LOCKED month can certainly
    correct one that is merely past its cut-off. Default is OFF: §19 lists the cut-off as
    unconfirmed, so no company gets a new refusal it did not ask for.
    """
    from datetime import date as _date
    rules = await closure_rules(company_id)
    if not rules.get("enforce_cutoff"):
        return
    closing_day = int(rules.get("closing_day") or 0)
    if not 1 <= closing_day <= 31:
        return
    period = str(work_date)[:7]
    today = datetime.now(timezone.utc).date()
    if today.strftime("%Y-%m") <= period:
        return                      # the current month or a future one: nothing to enforce
    # The cut-off falls in the month AFTER the one being written to.
    year, month = int(period[:4]), int(period[5:7])
    nxt_y, nxt_m = (year + 1, 1) if month == 12 else (year, month + 1)
    try:
        cutoff = _date(nxt_y, nxt_m, closing_day)
    except ValueError:              # e.g. the 31st of a 30-day month
        cutoff = _date(nxt_y, nxt_m, 28)
    if today <= cutoff:
        return
    if can(actor, Cap.ATTENDANCE_LOCK):
        return
    raise HTTPException(
        status_code=409,
        detail=f"Attendance for {period} closed on {cutoff.isoformat()}. Ask HR to reopen "
               f"the month if this day still needs correcting.")


_PAYABLE_BY_STATUS = {
    AttendanceStatus.PRESENT.value: 1.0, AttendanceStatus.HALF_DAY.value: 0.5,
    AttendanceStatus.ON_LEAVE.value: 1.0, AttendanceStatus.ON_OD.value: 1.0,
    AttendanceStatus.WEEKLY_OFF.value: 1.0, AttendanceStatus.HOLIDAY.value: 1.0,
    AttendanceStatus.ABSENT.value: 0.0, AttendanceStatus.PENDING.value: 0.0,
}


def _status_only(status: str) -> dict:
    """A day decided by its status alone (an override, a weekly off, a holiday)."""
    payable = _PAYABLE_BY_STATUS.get(status, 0.0)
    return {"status": status, "worked_minutes": None, "late_minutes": 0, "early_minutes": 0,
            "payable_day": payable, "lop_fraction": round(1 - payable, 2),
            "missing_out_punch": False}


# ─────────────────────────────────────────────────────────────
# §7.8 — daily capture
# ─────────────────────────────────────────────────────────────
async def mark_attendance(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    work_date = str(payload.get("work_date") or "").strip()
    if not employee_code or not work_date:
        raise HTTPException(status_code=422, detail="employee_code and work_date are required.")
    await _get_profile(company_id, employee_code)
    await _assert_self_or_privileged(actor, company_id, employee_code)

    existing = await get_collection(COLL_ATTENDANCE).find_one(
        {"company_id": str(company_id), "employee_code": employee_code, "work_date": work_date})
    if (existing and existing.get("locked")) or await _month_locked(company_id, work_date):
        raise HTTPException(
            status_code=409,
            detail=f"{work_date} is inside a locked attendance period; use an authorised "
                   f"unlock before changing it.")
    await _assert_within_cutoff(actor, company_id, work_date)

    override = getattr(payload.get("override_status"), "value", payload.get("override_status"))
    actual_in = payload.get("actual_in")
    actual_out = payload.get("actual_out")
    from app.services.hrms_attendance_rules_service import compute_day, derived_fields

    if override:
        computed = _status_only(override)
    elif not actual_in and not actual_out:
        # FRD §5: weekly off and holidays come from the employee's own calendar, so a blank
        # Sunday is a Weekly Off, not an Absence.
        from app.services.hrms_shift_service import day_type, profile_for
        kind = await day_type(company_id, await profile_for(company_id, employee_code), work_date)
        computed = _status_only(kind) if kind else await compute_day(
            company_id, employee_code, work_date, actual_in, actual_out)
    else:
        # Against the day's EFFECTIVE hours (an approved flexible timing, else the shift).
        computed = await compute_day(company_id, employee_code, work_date, actual_in, actual_out)

    source = payload.get("source") or "Manual"
    from app.models.hrms import ATTENDANCE_SOURCES
    if source not in ATTENDANCE_SOURCES:
        raise HTTPException(status_code=422,
                            detail=f"Source must be one of: {', '.join(ATTENDANCE_SOURCES)}.")
    custom = None
    if payload.get("custom_fields") is not None:
        from app.services.hrms_employee_master_service import validate_custom_values
        custom = await validate_custom_values(
            company_id, "attendance", payload["custom_fields"],
            current=(existing or {}).get("custom_fields"), enforce_mandatory=True)

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id),
        "employee_code": employee_code,
        "work_date": work_date,
        "actual_in": actual_in,
        "actual_out": actual_out,
        "status": computed["status"],
        "worked_minutes": computed["worked_minutes"],
        "late_minutes": computed["late_minutes"],
        "flexi_no": computed.get("flexi_no"),
        **derived_fields(computed),
        "source": source.lower() if source == "Manual" else source,
        "source_reference": payload.get("source_reference"),
        "notes": payload.get("notes"),
        "locked": False,
        "updated_at": now,
        "updated_by": str(actor.get("_id") or ""),
    }
    if custom is not None:
        doc["custom_fields"] = custom
    update = {"$set": doc,
              "$setOnInsert": {"created_at": now, "original_in": actual_in,
                               "original_out": actual_out, "original_status": computed["status"],
                               "original_source": doc["source"]}}
    if existing:
        # FRD §6 Audit: original/raw values stay; every later change is appended.
        update["$push"] = {"modification_history": {
            "at": now, "by": str(actor.get("_id") or ""), "via": "mark",
            "old": {k: existing.get(k) for k in ("actual_in", "actual_out", "status", "source")},
            "new": {"actual_in": actual_in, "actual_out": actual_out,
                    "status": computed["status"], "source": doc["source"]}}}
    await get_collection(COLL_ATTENDANCE).update_one(
        {"company_id": str(company_id), "employee_code": employee_code, "work_date": work_date},
        update, upsert=True,
    )
    # Raw punches are preserved as their own append-only record, never overwritten by a later
    # correction — §7.8's own BR ("Raw attendance data should not be overwritten...").
    if actual_in or actual_out:
        await get_collection(COLL_PUNCH_SEGMENTS).insert_one({
            "company_id": str(company_id), "employee_code": employee_code,
            "work_date": work_date, "punch_in": actual_in, "punch_out": actual_out,
            "source": "manual", "recorded_by": str(actor.get("_id") or ""), "recorded_at": now,
        })

    await audit(actor, AUDIT_ATTENDANCE_MARKED, ENTITY_ATTENDANCE, f"{employee_code}:{work_date}",
               computed["status"], company_id)
    saved = await get_collection(COLL_ATTENDANCE).find_one(
        {"company_id": str(company_id), "employee_code": employee_code, "work_date": work_date})
    return _out(saved)


async def list_attendance(actor: dict, company_id: str, *, employee_code: Optional[str] = None,
                          start_date: Optional[str] = None, end_date: Optional[str] = None,
                          status: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if employee_code:
        query["employee_code"] = employee_code
    if start_date or end_date:
        rng = {}
        if start_date:
            rng["$gte"] = start_date
        if end_date:
            rng["$lte"] = end_date
        query["work_date"] = rng
    if status:
        query["status"] = status
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_ATTENDANCE).find(query).sort(
        "work_date", -1).to_list(min(limit, MAX_ATTENDANCE_LIST_PAGE))
    return await _with_identity(company_id, [_out(r) for r in rows])


async def _with_identity(company_id: str, rows: list) -> list:
    """FRD §6 Identity / Date: employee name, department, location and weekday on each
    day, joined once for the whole page rather than once per row."""
    codes = {r["employee_code"] for r in rows if r.get("employee_code")}
    if not codes:
        return rows
    from datetime import date as _date
    from app.models.hrms import COLL_DEPARTMENTS, WEEKDAYS
    profiles = await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id), "employee_code": {"$in": list(codes)}}).to_list(len(codes))
    depts = {str(d["_id"]): d.get("name") for d in await get_collection(COLL_DEPARTMENTS).find(
        {"company_id": str(company_id)}, {"name": 1}).to_list(1000)}
    from app.services.hrms_payroll_service import _employee_names, _name_of
    names = await _employee_names(profiles)
    by_code = {p["employee_code"]: p for p in profiles}
    for r in rows:
        p = by_code.get(r.get("employee_code")) or {}
        r.setdefault("employee_name", _name_of(p, names))
        r["department"] = depts.get(p.get("department_id"))
        r["work_location"] = p.get("work_location")
        try:
            r["day"] = WEEKDAYS[_date.fromisoformat(r["work_date"]).weekday()]
        except (KeyError, ValueError, TypeError):
            r["day"] = None
    return rows


# ─────────────────────────────────────────────────────────────
# §7.9 — regularisation (employee -> manager -> HR)
# ─────────────────────────────────────────────────────────────
async def request_regularization(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    work_date = str(payload.get("work_date") or "").strip()
    if not employee_code or not work_date:
        raise HTTPException(status_code=422, detail="employee_code and work_date are required.")
    profile = await _get_profile(company_id, employee_code)
    await _assert_self_or_privileged(actor, company_id, employee_code)

    attendance = await get_collection(COLL_ATTENDANCE).find_one(
        {"company_id": str(company_id), "employee_code": employee_code, "work_date": work_date})
    if (attendance and attendance.get("locked")) or await _month_locked(company_id, work_date):
        raise HTTPException(
            status_code=409,
            detail=f"{work_date} is inside a locked attendance period — no regularisation "
                   f"without an authorised unlock (§7.9 BR).")
    await _assert_within_cutoff(actor, company_id, work_date)
    # FRD §5/§23 Regularisation: window, evidence, request type and monthly cap, from the
    # ATT_REGULARISATION policy in force for THIS employee on THIS date.
    rules = await regularisation_rules(company_id, profile, work_date)
    window = rules.get("window_days")
    today = _today()
    if work_date > today:
        raise HTTPException(status_code=422, detail="You cannot regularise a future date.")
    if window:
        from datetime import date as _date, timedelta as _td
        earliest = (_date.fromisoformat(today) - _td(days=int(window))).isoformat()
        if work_date < earliest:
            raise HTTPException(
                status_code=422,
                detail=f"Regularisation can be requested up to {window} day(s) back "
                       f"(from {earliest}).")
    if rules.get("evidence_required") and not (payload.get("evidence") or "").strip():
        raise HTTPException(status_code=422,
                            detail="Attach supporting evidence (a link or reference) — company "
                                   "policy requires it for regularisation.")

    # §23 "Request types". Configured as a list; unconfigured means anything is accepted,
    # which is how every company behaved before this existed.
    allowed_types = rules.get("request_types")
    request_type = (payload.get("request_type") or "").strip()
    if allowed_types and request_type not in allowed_types:
        raise HTTPException(
            status_code=422,
            detail=f"Choose a regularisation type: {', '.join(allowed_types)}.")

    # §23 "Request window ... monthly count". A cap on how often one person may ask, which
    # is what stops regularisation quietly becoming the way attendance is recorded.
    cap = rules.get("max_requests_per_month")
    if cap:
        period = str(work_date)[:7]
        used = await get_collection(COLL_ATTENDANCE_CORRECTIONS).count_documents({
            "company_id": str(company_id), "employee_code": employee_code,
            "work_date": {"$gte": f"{period}-01", "$lte": f"{period}-31"},
            "status": {"$ne": CorrectionStatus.REJECTED.value},
        })
        if used >= int(cap):
            raise HTTPException(
                status_code=409,
                detail=f"{employee_code} has already used {used} of {cap} regularisation(s) "
                       f"allowed for {period}.")

    year = datetime.now(timezone.utc).year
    req_no = await next_business_id("regularization", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "req_no": req_no,
        "request_type": request_type or None,
        "company_id": str(company_id),
        "employee_code": employee_code,
        "employee_name": profile.get("display_name") or profile.get("full_name"),
        "reporting_manager_id": await _reporting_manager_id(profile),
        "work_date": work_date,
        "exception_type": payload.get("exception_type"),
        "proposed_in": payload.get("proposed_in"),
        "proposed_out": payload.get("proposed_out"),
        "reason": payload.get("reason"),
        "evidence": payload.get("evidence"),
        "status": CorrectionStatus.PENDING.value,
        "manager_action_by": None, "manager_action_at": None, "manager_remarks": None,
        "hr_action_by": None, "hr_action_at": None, "hr_remarks": None,
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_ATTENDANCE_CORRECTIONS).insert_one(doc)
    await audit(actor, AUDIT_CORRECTION_REQUESTED, ENTITY_CORRECTION, req_no,
               f"{employee_code}, {work_date}, {payload.get('exception_type')}", company_id)
    return _out(doc)


async def list_regularizations(actor: dict, company_id: str, *, status: Optional[str] = None,
                               employee_code: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if employee_code:
        query["employee_code"] = employee_code
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_ATTENDANCE_CORRECTIONS).find(query).sort(
        "created_at", -1).to_list(min(limit, MAX_ATTENDANCE_LIST_PAGE))
    return [_out(r) for r in rows]


async def act_on_regularization(actor: dict, company_id: str, req_no: str, payload: dict) -> dict:
    """§7.9 steps 66-69: manager decides first; HR gives the final sign-off. A caller who
    holds both levels (HR/MD/ADMIN) may also record the manager step directly — the same
    "no separate manager, no dead end" reasoning Phase EXIT-1's MD fallback already uses —
    but the ORDER itself (manager step before HR-final) is never skipped."""
    doc = await get_collection(COLL_ATTENDANCE_CORRECTIONS).find_one(
        {"company_id": str(company_id), "req_no": req_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Regularisation '{req_no}' not found.")
    if doc["status"] not in (CorrectionStatus.PENDING.value, CorrectionStatus.MANAGER_APPROVED.value):
        raise HTTPException(status_code=409, detail=f"{req_no} is already \"{doc['status']}\".")
    await _assert_may_decide(actor, company_id, doc["employee_code"], "regularisation")

    decision = payload.get("decision")
    now = datetime.now(timezone.utc)
    updates = {"updated_at": now}

    if decision == CorrectionStatus.REJECTED.value:
        updates.update({"status": CorrectionStatus.REJECTED.value})
    elif decision == CorrectionStatus.RETURNED.value:
        updates.update({"status": CorrectionStatus.RETURNED.value})
    elif decision == CorrectionStatus.MANAGER_APPROVED.value:
        if doc["status"] != CorrectionStatus.PENDING.value:
            raise HTTPException(status_code=409, detail=f"{req_no} already passed the manager step.")
        updates.update({"status": CorrectionStatus.MANAGER_APPROVED.value,
                        "manager_action_by": str(actor.get("_id") or ""),
                        "manager_action_at": now, "manager_remarks": payload.get("remarks")})
    elif decision == CorrectionStatus.APPROVED.value:
        if doc["status"] != CorrectionStatus.MANAGER_APPROVED.value:
            raise HTTPException(
                status_code=409,
                detail=f"{req_no} needs the manager's approval before HR's final sign-off.")
        # The final sign-off is HR's (FRD §17): a reporting manager records the manager step
        # only, never both.
        if hrms_role(actor) not in (HrmsRole.HR, HrmsRole.MD, HrmsRole.ADMIN, None):
            raise HTTPException(status_code=403,
                                detail="HR gives the final sign-off on a regularisation.")
        if await _month_locked(company_id, doc["work_date"]):
            raise HTTPException(status_code=409,
                                detail=f"{doc['work_date']} is in a locked month — unlock it first.")
        # HR-final: recalculate attendance, preserving the original record (the update, not a
        # second row) — §7.9 step 69. The raw punches stay as original_in/out (FRD §18).
        from app.services.hrms_attendance_rules_service import compute_day, derived_fields
        computed = await compute_day(company_id, doc["employee_code"], doc["work_date"],
                                     doc.get("proposed_in"), doc.get("proposed_out"))
        key = {"company_id": str(company_id), "employee_code": doc["employee_code"],
               "work_date": doc["work_date"]}
        before = await get_collection(COLL_ATTENDANCE).find_one(key) or {}
        await get_collection(COLL_ATTENDANCE).update_one(
            key,
            {"$set": {"actual_in": doc.get("proposed_in"), "actual_out": doc.get("proposed_out"),
                      "status": computed["status"], "worked_minutes": computed["worked_minutes"],
                      "late_minutes": computed["late_minutes"], "source": "regularization",
                      **derived_fields(computed), "flexi_no": computed.get("flexi_no"),
                      "regularized_from": req_no, "regularization_flag": True,
                      "corrected_in": doc.get("proposed_in"),
                      "corrected_out": doc.get("proposed_out"),
                      "manager_status": CorrectionStatus.MANAGER_APPROVED.value,
                      "hr_status": CorrectionStatus.APPROVED.value,
                      "approver_comments": payload.get("remarks"), "updated_at": now},
             "$setOnInsert": {"created_at": now, "locked": False, "original_in": None,
                              "original_out": None, "original_status": None,
                              "original_source": None},
             "$push": {"modification_history": {
                 "at": now, "by": str(actor.get("_id") or ""), "via": req_no,
                 "old": {k: before.get(k) for k in ("actual_in", "actual_out", "status",
                                                    "source")},
                 "new": {"actual_in": doc.get("proposed_in"),
                         "actual_out": doc.get("proposed_out"),
                         "status": computed["status"], "source": "regularization"}}}},
            upsert=True,
        )
        updates.update({"status": CorrectionStatus.APPROVED.value,
                        "hr_action_by": str(actor.get("_id") or ""),
                        "hr_action_at": now, "hr_remarks": payload.get("remarks")})
    else:
        raise HTTPException(status_code=422, detail=f"Unrecognised decision '{decision}'.")

    await get_collection(COLL_ATTENDANCE_CORRECTIONS).update_one(
        {"company_id": str(company_id), "req_no": req_no}, {"$set": updates})
    await audit(actor, AUDIT_CORRECTION_ACTIONED, ENTITY_CORRECTION, req_no,
               decision, company_id)
    saved = await get_collection(COLL_ATTENDANCE_CORRECTIONS).find_one(
        {"company_id": str(company_id), "req_no": req_no})
    return _out(saved)


# ─────────────────────────────────────────────────────────────
# §7.8 step 59 — Outdoor Duty
# ─────────────────────────────────────────────────────────────
async def request_od(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    od_date = str(payload.get("od_date") or "").strip()
    if not employee_code or not od_date:
        raise HTTPException(status_code=422, detail="employee_code and od_date are required.")
    profile = await _get_profile(company_id, employee_code)
    await _assert_self_or_privileged(actor, company_id, employee_code)

    year = datetime.now(timezone.utc).year
    od_no = await next_business_id("od", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "od_no": od_no,
        "company_id": str(company_id),
        "employee_code": employee_code,
        "employee_name": profile.get("display_name") or profile.get("full_name"),
        "reporting_manager_id": await _reporting_manager_id(profile),
        "od_date": od_date,
        "purpose": payload.get("purpose"),
        "location": payload.get("location"),
        "status": OdStatus.PENDING.value,
        "action_by": None, "action_at": None, "remarks": None,
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_OD_REQUESTS).insert_one(doc)
    await audit(actor, AUDIT_OD_REQUESTED, ENTITY_OD, od_no,
               f"{employee_code}, {od_date}", company_id)
    return _out(doc)


async def list_od_requests(actor: dict, company_id: str, *, status: Optional[str] = None,
                           employee_code: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if employee_code:
        query["employee_code"] = employee_code
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_OD_REQUESTS).find(query).sort(
        "created_at", -1).to_list(min(limit, MAX_ATTENDANCE_LIST_PAGE))
    return [_out(r) for r in rows]


async def act_on_od(actor: dict, company_id: str, od_no: str, payload: dict) -> dict:
    doc = await get_collection(COLL_OD_REQUESTS).find_one(
        {"company_id": str(company_id), "od_no": od_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"OD request '{od_no}' not found.")
    if doc["status"] != OdStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"{od_no} is already \"{doc['status']}\".")
    await _assert_may_decide(actor, company_id, doc["employee_code"], "Outdoor Duty request")

    approved = bool(payload.get("approved"))
    if approved and await _month_locked(company_id, doc["od_date"]):
        raise HTTPException(status_code=409,
                            detail=f"{doc['od_date']} is in a locked month — an OD cannot change "
                                   f"it without an authorised unlock.")
    now = datetime.now(timezone.utc)
    new_status = OdStatus.APPROVED.value if approved else OdStatus.REJECTED.value
    await get_collection(COLL_OD_REQUESTS).update_one(
        {"company_id": str(company_id), "od_no": od_no},
        {"$set": {"status": new_status, "action_by": str(actor.get("_id") or ""),
                  "action_at": now, "remarks": payload.get("remarks"), "updated_at": now}},
    )
    if approved:
        # §7.8: an approved OD becomes the day's attendance status directly.
        await get_collection(COLL_ATTENDANCE).update_one(
            {"company_id": str(company_id), "employee_code": doc["employee_code"],
             "work_date": doc["od_date"]},
            {"$set": {"status": AttendanceStatus.ON_OD.value, "source": "od",
                      "od_ref": od_no, "payable_day": 1.0, "lop_fraction": 0.0,
                      "updated_at": now},
             "$setOnInsert": {"company_id": str(company_id), "employee_code": doc["employee_code"],
                              "work_date": doc["od_date"], "created_at": now, "locked": False,
                              "worked_minutes": None, "late_minutes": 0}},
            upsert=True,
        )
    await audit(actor, AUDIT_OD_ACTIONED, ENTITY_OD, od_no, new_status, company_id)
    saved = await get_collection(COLL_OD_REQUESTS).find_one(
        {"company_id": str(company_id), "od_no": od_no})
    return _out(saved)


# ─────────────────────────────────────────────────────────────
# §7.12 — monthly closure
# ─────────────────────────────────────────────────────────────
async def closure_dashboard(actor: dict, company_id: str, period: str) -> dict:
    """§7.12 steps 84-85: what is still open for this period, before HR can lock it."""
    start, end = f"{period}-01", f"{period}-31"
    missing_punches = await get_collection(COLL_ATTENDANCE).count_documents(
        {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end},
         "status": AttendanceStatus.PENDING.value})
    pending_regularizations = await get_collection(COLL_ATTENDANCE_CORRECTIONS).count_documents(
        {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end},
         "status": {"$in": [CorrectionStatus.PENDING.value, CorrectionStatus.MANAGER_APPROVED.value]}})
    pending_od = await get_collection(COLL_OD_REQUESTS).count_documents(
        {"company_id": str(company_id), "od_date": {"$gte": start, "$lte": end},
         "status": OdStatus.PENDING.value})
    unexplained_absence = await get_collection(COLL_ATTENDANCE).count_documents(
        {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end},
         "status": AttendanceStatus.ABSENT.value})
    # A day with a check-in and no check-out (before today) is an open exception too.
    missing_out_punches = await get_collection(COLL_ATTENDANCE).count_documents(
        {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end, "$lt": _today()},
         "missing_out_punch": True})
    from app.models.hrms import COLL_LEAVES, OPEN_LEAVE_STATUSES
    pending_leaves = await get_collection(COLL_LEAVES).count_documents(
        {"company_id": str(company_id), "status": {"$in": list(OPEN_LEAVE_STATUSES)},
         "start_date": {"$lte": end}, "end_date": {"$gte": start}})
    lock = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
        {"company_id": str(company_id), "period": period})
    policy = await get_shift_policy(company_id)
    return {
        "period": period,
        "status": (lock or {}).get("status", LockStatus.OPEN.value),
        "missing_punches": missing_punches,
        "missing_out_punches": missing_out_punches,
        "pending_regularizations": pending_regularizations,
        "pending_od": pending_od,
        "pending_leaves": pending_leaves,
        "unexplained_absence": unexplained_absence,
        "ready_to_lock": not (missing_punches or missing_out_punches or pending_regularizations
                              or pending_od or pending_leaves),
        "closing_day": policy.get("attendance_closing_day"),
        "locked_by": (lock or {}).get("locked_by"),
        "locked_by_name": (lock or {}).get("locked_by_name"),
        "locked_at": (lock or {}).get("locked_at"),
        "override_reason": (lock or {}).get("override_reason"),
    }


async def lock_period(actor: dict, company_id: str, period: str,
                      override_reason: Optional[str] = None) -> dict:
    existing = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
        {"company_id": str(company_id), "period": period})
    if existing and existing.get("status") == LockStatus.LOCKED.value:
        raise HTTPException(status_code=409, detail=f"{period} is already locked.")

    snapshot = await closure_dashboard(actor, company_id, period)
    # FRD §8: HR resolves pending exceptions BEFORE locking. Locking with some still open is
    # the lock authority's explicit, reasoned decision -- enforced here, not just shown.
    reason = (override_reason or "").strip()
    if not snapshot["ready_to_lock"] and not reason:
        open_items = ", ".join(f"{snapshot[k]} {label}" for k, label in (
            ("missing_punches", "pending day(s)"), ("missing_out_punches", "missing out-punch(es)"),
            ("pending_regularizations", "open regularisation(s)"), ("pending_od", "open OD(s)"),
            ("pending_leaves", "open leave request(s)")) if snapshot.get(k))
        raise HTTPException(
            status_code=409,
            detail=f"{period} still has {open_items}. Resolve them, or lock with a reason.")
    now = datetime.now(timezone.utc)
    actor_name = (actor.get("full_name") or f"{actor.get('first_name') or ''} "
                  f"{actor.get('last_name') or ''}".strip() or actor.get("email"))
    doc = {
        "company_id": str(company_id), "period": period, "status": LockStatus.LOCKED.value,
        "locked_by": str(actor.get("_id") or ""), "locked_at": now,
        "locked_by_name": actor_name, "override_reason": reason or None,
        "exceptions_at_lock": {k: snapshot[k] for k in (
            "missing_punches", "missing_out_punches", "pending_regularizations", "pending_od",
            "pending_leaves", "unexplained_absence")},
        "unlock_history": (existing or {}).get("unlock_history", []),
        "updated_at": now,
    }
    await get_collection(COLL_ATTENDANCE_LOCKS).update_one(
        {"company_id": str(company_id), "period": period},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    # Freeze the period's own attendance rows — payroll consumes this flag, not the lock
    # document, so "is THIS row immutable" never needs a second lookup.
    start, end = f"{period}-01", f"{period}-31"
    await get_collection(COLL_ATTENDANCE).update_many(
        {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end}},
        {"$set": {"locked": True, "locked_by": doc["locked_by"], "locked_at": now}})
    await audit(actor, AUDIT_ATTENDANCE_LOCKED, ENTITY_ATT_LOCK, period,
               f"exceptions at lock: {doc['exceptions_at_lock']}", company_id)
    return _out(doc)


async def unlock_period(actor: dict, company_id: str, period: str, reason: str) -> dict:
    existing = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
        {"company_id": str(company_id), "period": period})
    if not existing or existing.get("status") != LockStatus.LOCKED.value:
        raise HTTPException(status_code=409, detail=f"{period} is not locked.")
    # Once payroll has locked on this snapshot, attendance stays closed: a correction is a
    # payroll adjustment in a later month (FRD §8, §18), not a reopened month.
    from app.models.hrms import COLL_PAYROLL_RUNS, PAYROLL_FINAL_STATUSES
    run = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": period}, {"status": 1})
    if (run or {}).get("status") in PAYROLL_FINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Payroll for {period} is already {run['status']} on this attendance. Record "
                   f"the correction as a post-lock payroll adjustment instead.")

    now = datetime.now(timezone.utc)
    entry = {"by": str(actor.get("_id") or ""), "at": now, "reason": reason}
    await get_collection(COLL_ATTENDANCE_LOCKS).update_one(
        {"company_id": str(company_id), "period": period},
        {"$set": {"status": LockStatus.OPEN.value, "updated_at": now},
         "$push": {"unlock_history": entry}},
    )
    start, end = f"{period}-01", f"{period}-31"
    await get_collection(COLL_ATTENDANCE).update_many(
        {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end}},
        {"$set": {"locked": False, "locked_by": None, "locked_at": None}})
    await audit(actor, AUDIT_ATTENDANCE_UNLOCKED, ENTITY_ATT_LOCK, period, reason, company_id)
    saved = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
        {"company_id": str(company_id), "period": period})
    return _out(saved)


# ─────────────────────────────────────────────────────────────
# §22.9 — late-coming analytics
# ─────────────────────────────────────────────────────────────
async def late_coming_summary(actor: dict, company_id: str, *, employee_code: Optional[str] = None,
                              start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
    """Total late-coming days and the dates themselves, for the calendar marker and the
    monthly card's click-to-filter (§22.9)."""
    query = {"company_id": str(company_id), "late_minutes": {"$gt": 0}}
    if employee_code:
        query["employee_code"] = employee_code
    if start_date or end_date:
        rng = {}
        if start_date:
            rng["$gte"] = start_date
        if end_date:
            rng["$lte"] = end_date
        query["work_date"] = rng
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_ATTENDANCE).find(
        query, {"work_date": 1, "employee_code": 1, "late_minutes": 1}
    ).sort("work_date", -1).to_list(MAX_ATTENDANCE_LIST_PAGE)

    # Department label per employee_code, joined once for the whole result rather than once
    # per row — the same batched-lookup reasoning hrms_scheduler_service._managerial_
    # request_nos already applies for the same shape of problem. A profile stores
    # department_id, not a resolved name (see hrms_employee_service._compose), so this is
    # two batched lookups, not one.
    codes = {r["employee_code"] for r in rows}
    departments = {}
    names = {}
    if codes:
        from app.models.hrms import COLL_DEPARTMENTS
        profiles = await get_collection(COLL_EMPLOYEE_PROFILES).find(
            {"company_id": str(company_id), "employee_code": {"$in": list(codes)}},
            {"employee_code": 1, "department_id": 1, "user_id": 1, "display_name": 1,
             "full_name": 1, "identity_snapshot": 1}).to_list(len(codes))
        dept_names = {
            str(d["_id"]): d.get("name")
            for d in await get_collection(COLL_DEPARTMENTS).find(
                {"company_id": str(company_id)}, {"name": 1}).to_list(1000)
        }
        departments = {p["employee_code"]: dept_names.get(p.get("department_id"))
                       for p in profiles}
        # Names, so the tab reads "Dummy HOD" rather than a bare EMP code — identity lives on
        # the user document, never on the profile (same resolution payroll uses).
        from app.services.hrms_payroll_service import _employee_names, _name_of
        user_names = await _employee_names(profiles)
        names = {p["employee_code"]: _name_of(p, user_names) for p in profiles}

    dates = [{"work_date": r["work_date"], "employee_code": r["employee_code"],
              "employee_name": names.get(r["employee_code"]),
              "late_minutes": r["late_minutes"],
              "department": departments.get(r["employee_code"])} for r in rows]
    # The monthly buffer: late minutes tolerated per person per month (shift policy).
    from app.services.hrms_attendance_rules_service import monthly_buffer
    policy = await get_shift_policy(company_id)
    return {
        "total_late_days": len(rows),
        "dates": dates,
        "buffer_minutes": policy.get("monthly_buffer_minutes") or 0,
        "grace_minutes": policy.get("daily_grace_minutes") or 0,
        "monthly": monthly_buffer(dates, policy.get("monthly_buffer_minutes") or 0),
    }
