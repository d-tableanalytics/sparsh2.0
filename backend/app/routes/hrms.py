"""HRMS — module root.

Routes stay thin: validation and business logic live in app/services/hrms_*, so this file reads
as the API surface rather than the implementation. Built in phases — see
docs/HRMS_REPLICATION_ROADMAP.md.

  Phase 0  access gate + permission probe
  Phase 1  org masters, employee master, employee timeline
  Phase 2  attendance (punch, team, manual entry, policy)
  Phase 3  leave (apply, decide, balances, policy)
  Phase 4  payroll (config, run, lock, payslips)
  Phase 5  recruitment (requisitions, JD, approval chain)

Every route sits behind `require_hrms_access` (internal Sparsh staff only), and anything
touching another person's record additionally checks a per-module permission via
`has_hrms_permission`. Two layers, matching how Task & Delegation gates itself.
"""
import re
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.controllers.auth_controller import (
    require_hrms_access,
    has_hrms_access,
    has_hrms_permission,
    get_current_user,
)
from app.db.mongodb import get_collection
from app.models.hrms import (
    HRMS_PERMISSION_MODULES, HrmsAccessResponse,
    COL_EMPLOYEES, COL_EMPLOYEE_EVENTS, COL_ORG_MASTERS,
    ORG_KINDS, ORG_KIND_DEPARTMENT, ORG_KIND_DESIGNATION, ORG_KIND_LOCATION,
    EMPLOYEE_STATUSES, EMPLOYMENT_TYPES, WORK_MODES, EXITED_STATUSES,
    OrgMasterCreate, OrgMasterUpdate,
    EmployeeCreate, EmployeeUpdate, EmployeeEventCreate,
    EVENT_CREATED, EVENT_UPDATED, EVENT_STATUS_CHANGE, EVENT_EXIT, EVENT_NOTE,
    COL_ATTENDANCE, SETTING_ATTENDANCE,
    AttendanceSettingsUpdate, PunchRequest, ManualAttendanceRequest,
    COL_LEAVES, SETTING_LEAVE, LEAVE_PENDING, LEAVE_APPROVED, LEAVE_REJECTED, LEAVE_CANCELLED,
    LeaveSettingsUpdate, LeaveApply, LeaveDecision,
    COL_PAYROLL_RUNS, COL_PAYSLIPS, SETTING_PAYROLL,
    PayrollRunRequest, PayrollConfigUpdate,
    COL_REQUISITIONS, COL_JDS,
    REQ_PENDING_HR, REQ_PENDING_MD, REQ_APPROVED, REQ_REJECTED,
    REQ_OPEN, REQ_CLOSING_STATES, URGENCY_LEVELS,
    RequisitionCreate, RequisitionUpdate, RequisitionDecision, RequisitionClose,
    COL_POSTINGS, COL_CANDIDATES, POSTING_STATES,
    STAGE_APPLIED, STAGE_ASSESSMENT, STAGE_INTERVIEW, STAGE_REJECTED, CANDIDATE_STAGES,
    ASSESSMENT_SENT, ASSESSMENT_OPENED, ASSESSMENT_SUBMITTED, ASSESSMENT_REVIEWED,
    INTERVIEW_SCHEDULED, INTERVIEW_DONE, INTERVIEW_CANCELLED,
    PostingCreate, PostingUpdate, PublicApplication, CandidateCreate, ScreenDecision,
    AssessmentSend, AssessmentSubmission, AssessmentReview,
    InterviewSchedule, InterviewEvaluation,
    STAGE_OFFER, STAGE_HIRED,
    OFFER_SENT, OFFER_ACCEPTED, OFFER_DECLINED, OFFER_WITHDRAWN, OFFER_FINAL,
    ONB_INVITED, ONB_SUBMITTED, ONB_VERIFIED, ONB_CONVERTED,
    OfferCreate, OfferDecision, OnboardingInvite, OnboardingSubmission,
    OnboardingVerify, ConvertToEmployee,
)
from app.services.hrms_attendance_service import (
    get_attendance_settings, validate_settings, serialize_day,
    punch, add_manual_segment, get_day, ist_date_str,
)
from app.services.hrms_leave_service import (
    get_leave_settings, validate_leave_types, find_leave_type, parse_date,
    count_leave_days, get_balance, all_balances, adjust_balance, set_balance,
    find_overlap, resolve_approver, serialize_leave,
)
from app.services.hrms_payroll_service import (
    get_payroll_config, validate_payroll_config, run_payroll,
    serialize_run, serialize_payslip, RUN_LOCKED,
)
from app.services.hrms_recruitment_service import (
    generate_request_no, validate_requisition, apply_decision, build_step,
    upsert_jd, get_jd, serialize_requisition, serialize_jd,
)
from app.services.hrms_candidate_service import (
    generate_candidate_uk, validate_applicant, store_resume,
    create_posting, posting_is_live, serialize_posting, serialize_public_posting,
    can_advance, journey_entry, serialize_candidate,
    find_candidate_by_assessment_code, find_assessment,
    find_candidate_by_offer_code, find_offer, active_offer, offer_link_state,
    find_candidate_by_onboarding_code,
)
from app.utils.public_guard import (
    rate_limit, decode_upload, public_token, safe_public_error,
)
from app.services.activity_log_service import log_activity
from app.services.hrms_employee_service import (
    can_read_personal_data, serialize_employee, serialize_event, serialize_org_master,
    add_employee_event, upsert_org_master, generate_employee_code,
    build_employee_query, get_employee_stats, find_employee, link_user_exists,
)

router = APIRouter(prefix="/hrms", tags=["HRMS"])


def _require(current_user: dict, module: str, action: str):
    """403 unless the caller holds `module.action`. The module gate (internal staff) is already
    applied by the route dependency; this is the second layer."""
    if not has_hrms_permission(current_user, module, action):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission for this HRMS action.",
        )


@router.get("/meta", response_model=HrmsAccessResponse)
async def hrms_meta(current_user: dict = Depends(require_hrms_access)):
    """What this user may do in the HRMS.

    The UI renders its HRMS nav from this rather than from role names, so the backend stays the
    single source of truth for access and a role rename can't silently open or hide a screen.
    """
    is_super = current_user.get("role") == "superadmin"
    perms = current_user.get("permissions", {}) or {}
    resolved = {
        module: {
            action: has_hrms_permission(current_user, module, action)
            for action in ("create", "read", "update", "delete")
        }
        for module in HRMS_PERMISSION_MODULES
    }
    # The caller's own employee record, matched by their staff login id, so self-service screens
    # (my attendance / my payslip / my profile) can resolve "me" without a second call.
    me_emp = await get_collection(COL_EMPLOYEES).find_one(
        {"user_id": str(current_user["_id"])}, {"employee_code": 1})
    return HrmsAccessResponse(
        has_access=True,
        permissions=resolved,
        is_superadmin=is_super,
        modules=HRMS_PERMISSION_MODULES,
        employee_code=(me_emp or {}).get("employee_code"),
    )


@router.get("/access")
async def hrms_access(current_user: dict = Depends(get_current_user)):
    """Non-403 access probe.

    `/meta` 403s a user without the module, which is right for the app shell but wrong for a
    nav that simply wants to know whether to show the HRMS group. This answers that question
    for ANY authenticated user without raising.
    """
    return {"has_access": has_hrms_access(current_user)}


@router.get("/staff-options")
async def hrms_staff_options(current_user: dict = Depends(require_hrms_access)):
    """Internal Sparsh staff logins — the source for the employee 'linked account' and
    'reporting manager' pickers (both reference a staff id)."""
    _require(current_user, "hrms", "read")
    out = []
    async for u in get_collection("staff").find(
            {"is_active": {"$ne": False}},
            {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1,
             "designation": 1, "role": 1}):
        out.append({
            "_id": str(u["_id"]),
            "full_name": (u.get("full_name")
                          or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
                          or u.get("email")),
            "email": u.get("email"),
            "designation": u.get("designation"),
            "role": u.get("role"),
        })
    out.sort(key=lambda x: (x["full_name"] or "").lower())
    return out


@router.get("/options")
async def hrms_options(current_user: dict = Depends(require_hrms_access)):
    """Enum values + master lists the employee form needs, in one call.

    Served from the backend so the dropdowns can never drift from what the API will accept —
    the reference project hardcodes these in several components and they diverge.
    """
    masters = await get_collection(COL_ORG_MASTERS).find({"active": True}).to_list(2000)
    grouped = {kind: [] for kind in ORG_KINDS}
    for m in masters:
        if m.get("kind") in grouped:
            grouped[m["kind"]].append(m.get("name"))
    for kind in grouped:
        grouped[kind].sort(key=lambda s: (s or "").lower())
    return {
        "statuses": EMPLOYEE_STATUSES,
        "employmentTypes": EMPLOYMENT_TYPES,
        "workModes": WORK_MODES,
        "exitedStatuses": EXITED_STATUSES,
        "departments": grouped[ORG_KIND_DEPARTMENT],
        "designations": grouped[ORG_KIND_DESIGNATION],
        "locations": grouped[ORG_KIND_LOCATION],
    }


# ─── Org structure ──────────────────────────────────────────────────────────────
@router.get("/org")
async def list_org_masters(
    kind: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    current_user: dict = Depends(require_hrms_access),
):
    _require(current_user, "hrms", "read")
    query = {}
    if kind:
        if kind not in ORG_KINDS:
            raise HTTPException(status_code=400, detail=f"kind must be one of {ORG_KINDS}")
        query["kind"] = kind
    if not include_inactive:
        query["active"] = True
    docs = await get_collection(COL_ORG_MASTERS).find(query).to_list(2000)
    docs.sort(key=lambda d: ((d.get("kind") or ""), (d.get("name") or "").lower()))
    return [serialize_org_master(d) for d in docs]


@router.post("/org")
async def create_org_master(body: OrgMasterCreate, current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "hrms", "create")
    if body.kind not in ORG_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {ORG_KINDS}")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    payload = body.model_dump()
    payload.pop("kind", None)
    payload.pop("name", None)
    await upsert_org_master(body.kind, name, current_user, extra=payload)

    doc = await get_collection(COL_ORG_MASTERS).find_one({"kind": body.kind, "name": name})
    await log_activity(current_user, "Create HRMS Org Master", COL_ORG_MASTERS,
                       f"{body.kind} created: {name}")
    return serialize_org_master(doc)


@router.patch("/org/{master_id}")
async def update_org_master(master_id: str, body: OrgMasterUpdate,
                            current_user: dict = Depends(require_hrms_access)):
    """Edit or retire a master value.

    Retiring (`active=false`) is the only removal path — history that references the value by
    name keeps rendering, which a hard delete would break.
    """
    _require(current_user, "hrms", "update")
    try:
        oid = ObjectId(master_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    existing = await get_collection(COL_ORG_MASTERS).find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Not found")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = datetime.now(timezone.utc)

    await get_collection(COL_ORG_MASTERS).update_one({"_id": oid}, {"$set": updates})
    await log_activity(current_user, "Update HRMS Org Master", COL_ORG_MASTERS,
                       f"{existing.get('kind')} updated: {existing.get('name')}")
    doc = await get_collection(COL_ORG_MASTERS).find_one({"_id": oid})
    return serialize_org_master(doc)


# ─── Employees ──────────────────────────────────────────────────────────────────
@router.get("/employees")
async def list_employees(
    search: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    include_exited: bool = Query(False),
    sort: str = Query("created_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=200),
    current_user: dict = Depends(require_hrms_access),
):
    """The directory. Filtering, sorting and paging are all server-side — the reference project
    renders every row client-side, which stops scaling at a few hundred people."""
    _require(current_user, "hrms", "read")

    query = build_employee_query(search, department, status, include_exited)
    col = get_collection(COL_EMPLOYEES)

    sort_map = {
        "created_desc": [("created_at", -1)],
        "created_asc": [("created_at", 1)],
        "name_asc": [("full_name", 1)],
        "name_desc": [("full_name", -1)],
        "joining_desc": [("date_of_joining", -1)],
        "joining_asc": [("date_of_joining", 1)],
    }
    order = sort_map.get(sort, sort_map["created_desc"])

    total = await col.count_documents(query)
    docs = await col.find(query).sort(order).skip((page - 1) * limit).limit(limit).to_list(limit)

    include_sensitive = can_read_personal_data(current_user)
    stats = await get_employee_stats()
    departments = sorted({d for d in await col.distinct("department") if d})

    return {
        "employees": [serialize_employee(d, include_sensitive) for d in docs],
        "total": total,
        "page": page,
        "limit": limit,
        "stats": stats,
        "departments": departments,
        "sensitiveVisible": include_sensitive,
    }


@router.post("/employees")
async def create_employee(body: EmployeeCreate, current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "hrms", "create")

    full_name = (body.full_name or "").strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="Full name is required")
    if body.status and body.status not in EMPLOYEE_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {EMPLOYEE_STATUSES}")

    # An employee may be linked to a Sparsh login, but only an internal staff account — the
    # HRMS manages Sparsh's own workforce, so a learner id is never valid.
    if body.user_id:
        if not await link_user_exists(body.user_id):
            raise HTTPException(status_code=400, detail="Linked user must be an internal staff account")
        clash = await get_collection(COL_EMPLOYEES).find_one({"user_id": body.user_id})
        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"That account is already linked to employee {clash.get('employee_code')}")

    doc = body.model_dump()
    doc["full_name"] = full_name
    doc["employee_code"] = await generate_employee_code()
    doc["created_by"] = str(current_user["_id"])
    doc["created_at"] = datetime.now(timezone.utc)
    doc["updated_at"] = doc["created_at"]

    await get_collection(COL_EMPLOYEES).insert_one(doc)

    # A typed-in department/designation/location joins the master list, so the pickers populate
    # from real use instead of needing to be curated up front.
    await upsert_org_master(ORG_KIND_DEPARTMENT, doc.get("department"), current_user)
    await upsert_org_master(ORG_KIND_DESIGNATION, doc.get("designation"), current_user)
    await upsert_org_master(ORG_KIND_LOCATION, doc.get("location"), current_user)

    await add_employee_event(doc["employee_code"], EVENT_CREATED,
                             f"Employee record created for {full_name}", current_user,
                             effective_date=doc.get("date_of_joining"))
    await log_activity(current_user, "Create Employee", COL_EMPLOYEES,
                       f"Employee created: {doc['employee_code']} — {full_name}")

    created = await find_employee(doc["employee_code"])
    return serialize_employee(created, can_read_personal_data(current_user))


@router.get("/employees/{employee_code}")
async def get_employee(employee_code: str, current_user: dict = Depends(require_hrms_access)):
    """A single profile.

    Anyone with `hrms.read` may open a profile; the sensitive block is still gated separately,
    so "can see the directory" never implies "can see bank details".
    """
    _require(current_user, "hrms", "read")
    doc = await find_employee(employee_code)
    if not doc:
        raise HTTPException(status_code=404, detail="Employee not found")
    return serialize_employee(doc, can_read_personal_data(current_user))


@router.patch("/employees/{employee_code}")
async def update_employee(employee_code: str, body: EmployeeUpdate,
                          current_user: dict = Depends(require_hrms_access)):
    """Edit a profile. Records what changed on the timeline, and treats a status change (and an
    exit in particular) as its own event rather than a generic edit."""
    _require(current_user, "hrms", "update")

    existing = await find_employee(employee_code)
    if not existing:
        raise HTTPException(status_code=404, detail="Employee not found")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "status" in updates and updates["status"] not in EMPLOYEE_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {EMPLOYEE_STATUSES}")

    if "user_id" in updates and updates["user_id"]:
        if not await link_user_exists(updates["user_id"]):
            raise HTTPException(status_code=400, detail="Linked user must be an internal staff account")
        clash = await get_collection(COL_EMPLOYEES).find_one({
            "user_id": updates["user_id"], "employee_code": {"$ne": employee_code}})
        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"That account is already linked to employee {clash.get('employee_code')}")

    updates["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COL_EMPLOYEES).update_one(
        {"employee_code": employee_code}, {"$set": updates})

    for kind, field in ((ORG_KIND_DEPARTMENT, "department"),
                        (ORG_KIND_DESIGNATION, "designation"),
                        (ORG_KIND_LOCATION, "location")):
        if updates.get(field):
            await upsert_org_master(kind, updates[field], current_user)

    # A status move is the event people actually look for on a timeline, so it gets its own
    # entry instead of being buried in a field-list.
    old_status = existing.get("status")
    new_status = updates.get("status")
    if new_status and new_status != old_status:
        is_exit = new_status in EXITED_STATUSES
        await add_employee_event(
            employee_code, EVENT_EXIT if is_exit else EVENT_STATUS_CHANGE,
            f"Status changed from {old_status} to {new_status}", current_user,
            effective_date=updates.get("exit_date") if is_exit else None,
            meta={"from": old_status, "to": new_status})

    changed = [k for k in updates if k not in ("updated_at", "status")]
    if changed:
        await add_employee_event(employee_code, EVENT_UPDATED,
                                 f"Updated: {', '.join(sorted(changed))}", current_user)

    await log_activity(current_user, "Update Employee", COL_EMPLOYEES,
                       f"Employee updated: {employee_code}")

    doc = await find_employee(employee_code)
    return serialize_employee(doc, can_read_personal_data(current_user))


@router.get("/employees/{employee_code}/events")
async def list_employee_events(employee_code: str, current_user: dict = Depends(require_hrms_access)):
    """The profile timeline, newest first."""
    _require(current_user, "hrms", "read")
    if not await find_employee(employee_code):
        raise HTTPException(status_code=404, detail="Employee not found")
    docs = await get_collection(COL_EMPLOYEE_EVENTS).find(
        {"employee_code": employee_code}).sort([("created_at", -1)]).to_list(500)
    return [serialize_event(d) for d in docs]


@router.post("/employees/{employee_code}/events")
async def create_employee_event(employee_code: str, body: EmployeeEventCreate,
                                current_user: dict = Depends(require_hrms_access)):
    """Add a manual note to the timeline (promotion, transfer, confirmation, free-text note)."""
    _require(current_user, "hrms", "update")
    if not await find_employee(employee_code):
        raise HTTPException(status_code=404, detail="Employee not found")
    detail = (body.detail or "").strip()
    if not detail:
        raise HTTPException(status_code=400, detail="Detail is required")
    await add_employee_event(employee_code, body.event_type or EVENT_NOTE, detail,
                             current_user, effective_date=body.effective_date)
    return {"message": "Event added"}


# ─── Attendance ─────────────────────────────────────────────────────────────────
# Punching your own attendance needs no grant — it is the one HRMS action every internal user
# performs. `attendance.read` governs seeing OTHER people, `attendance.update` governs entering
# attendance on their behalf.
@router.get("/attendance/settings")
async def read_attendance_settings(current_user: dict = Depends(require_hrms_access)):
    """Policy the punch UI needs: is geofencing on, where is the office, is a selfie required."""
    return await get_attendance_settings()


@router.put("/attendance/settings")
async def write_attendance_settings(body: AttendanceSettingsUpdate,
                                    current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "attendance", "update")
    try:
        clean = validate_settings(body.model_dump())
    except (ValueError, TypeError) as e:
        # Validated at the boundary because payroll reads these in Phase 4 — a bad radius or an
        # unparseable shift time must never reach the salary maths.
        raise HTTPException(status_code=400, detail=str(e))
    if not clean:
        raise HTTPException(status_code=400, detail="No valid settings to update")

    clean["updated_by"] = str(current_user["_id"])
    clean["updated_at"] = datetime.now(timezone.utc)
    await get_collection("system_settings").update_one(
        {"setting_name": SETTING_ATTENDANCE}, {"$set": clean}, upsert=True)
    await log_activity(current_user, "Update HRMS Settings", "system_settings",
                       "Attendance policy updated")
    return await get_attendance_settings()


@router.get("/attendance")
async def read_attendance(
    user_id: Optional[str] = Query(None),
    month: Optional[str] = Query(None, description="YYYY-MM; defaults to the current IST month"),
    current_user: dict = Depends(require_hrms_access),
):
    """A month of attendance for one person — your own by default.

    Reading someone else's needs `attendance.read`, so an ordinary staff member can see their
    own record and nobody else's.
    """
    me = str(current_user["_id"])
    target = user_id or me
    if target != me:
        _require(current_user, "attendance", "read")

    period = month or ist_date_str()[:7]
    docs = await get_collection(COL_ATTENDANCE).find({
        "user_id": target,
        "punch_date": {"$regex": f"^{period}"},
    }).sort([("punch_date", -1)]).to_list(62)

    today = ist_date_str()
    today_doc = next((d for d in docs if d.get("punch_date") == today), None)
    if today_doc is None and period == today[:7]:
        today_doc = await get_day(target, today)

    return {
        "userId": target,
        "month": period,
        "days": [serialize_day(d) for d in docs],
        "today": serialize_day(today_doc) if today_doc else None,
        "settings": await get_attendance_settings(),
        "serverDate": today,
    }


@router.post("/attendance/punch")
async def punch_attendance(body: PunchRequest, current_user: dict = Depends(require_hrms_access)):
    """Punch in or out — one toggle, so the client can't disagree with the server about state."""
    settings = await get_attendance_settings()
    try:
        result = await punch(
            str(current_user["_id"]), settings,
            body.latitude, body.longitude, body.selfie,
        )
    except ValueError as e:
        # Policy rejections (outside the geofence, selfie required) are the user's to fix, so
        # they come back as 400 with the reason rather than a generic failure.
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.post("/attendance/manual")
async def manual_attendance(body: ManualAttendanceRequest,
                            current_user: dict = Depends(require_hrms_access)):
    """HR recording a missed punch. Stored as an ordinary segment flagged `manual`, so payroll
    and every other consumer count it exactly like a self-punch."""
    _require(current_user, "attendance", "update")
    try:
        day = await add_manual_segment(
            body.user_id, body.punch_date, body.punch_in, body.punch_out,
            body.note or "", str(current_user["_id"]))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await log_activity(current_user, "Manual Attendance", COL_ATTENDANCE,
                       f"Manual attendance for {body.user_id} on {body.punch_date}")
    return day


@router.get("/attendance/team")
async def team_attendance(
    date: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today (IST)"),
    current_user: dict = Depends(require_hrms_access),
):
    """Who is in today. Rows are joined to the employee directory so the view shows people,
    not user ids."""
    _require(current_user, "attendance", "read")
    day = date or ist_date_str()

    employees = await get_collection(COL_EMPLOYEES).find(
        {"status": {"$nin": EXITED_STATUSES}}).to_list(2000)
    linked = [e for e in employees if e.get("user_id")]
    by_user = {e["user_id"]: e for e in linked}

    docs = await get_collection(COL_ATTENDANCE).find({
        "punch_date": day,
        "user_id": {"$in": list(by_user.keys())},
    }).to_list(2000)
    attendance_by_user = {d["user_id"]: serialize_day(d) for d in docs}

    rows = []
    for user_id, emp in by_user.items():
        record = attendance_by_user.get(user_id)
        rows.append({
            "userId": user_id,
            "employeeCode": emp.get("employee_code"),
            "fullName": emp.get("full_name"),
            "displayName": emp.get("display_name") or emp.get("full_name"),
            "designation": emp.get("designation") or "",
            "department": emp.get("department") or "",
            "photoUrl": emp.get("photo_url") or "",
            "attendance": record,
            # Present = has at least one punch. Absent here means "no record", which is NOT the
            # same as unauthorized absence — leave and holidays are resolved in Phases 3 and 4.
            "present": bool(record and record.get("segments")),
        })
    rows.sort(key=lambda r: (not r["present"], (r["displayName"] or "").lower()))

    present = sum(1 for r in rows if r["present"])
    return {
        "date": day,
        "rows": rows,
        "stats": {
            "total": len(rows),
            "present": present,
            "notPunched": len(rows) - present,
            # Employees with no linked login can't punch at all — surfaced so the gap is
            # visible rather than looking like absenteeism.
            "unlinked": len(employees) - len(linked),
        },
    }


@router.get("/attendance/selfie")
async def attendance_selfie(key: str = Query(...),
                            current_user: dict = Depends(require_hrms_access)):
    """A short-lived signed URL for a punch selfie (S3 key stored on the segment). The raw
    image is never public — HR fetches a fresh signed URL to view it. Key is validated to the
    attendance prefix so this can't be used to sign arbitrary objects."""
    _require(current_user, "attendance", "read")
    if not str(key).startswith("hrms/attendance/"):
        raise HTTPException(status_code=400, detail="Not an attendance selfie key")
    from app.services.s3_service import get_signed_url
    return {"url": get_signed_url(key)}


# ─── Leave ──────────────────────────────────────────────────────────────────────
# Applying for your own leave needs no grant. `attendance.read` sees others' requests,
# `attendance.update` decides them — the same pair that governs attendance, since in practice
# the same people do both.
@router.get("/leaves/settings")
async def read_leave_settings(current_user: dict = Depends(require_hrms_access)):
    """Leave types and counting policy. The apply form reads its dropdown from here, so a type
    the server would reject is never offered."""
    return await get_leave_settings()


@router.put("/leaves/settings")
async def write_leave_settings(body: LeaveSettingsUpdate,
                               current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "attendance", "update")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No settings to update")
    if "types" in updates:
        try:
            updates["types"] = validate_leave_types(updates["types"])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    updates["updated_by"] = str(current_user["_id"])
    updates["updated_at"] = datetime.now(timezone.utc)
    await get_collection("system_settings").update_one(
        {"setting_name": SETTING_LEAVE}, {"$set": updates}, upsert=True)
    await log_activity(current_user, "Update HRMS Settings", "system_settings",
                       "Leave policy updated")
    return await get_leave_settings()


@router.get("/leaves/balance")
async def read_leave_balance(
    user_id: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    current_user: dict = Depends(require_hrms_access),
):
    """Entitlement / used / remaining per type. Your own unless attendance.read is held."""
    me = str(current_user["_id"])
    target = user_id or me
    if target != me:
        _require(current_user, "attendance", "read")
    settings = await get_leave_settings()
    yr = year or int(ist_date_str()[:4])
    return {"userId": target, "year": yr,
            "balances": await all_balances(target, yr, settings)}


@router.patch("/leaves/balance")
async def adjust_leave_balance(body: dict, current_user: dict = Depends(require_hrms_access)):
    """HR override of a person's entitlement / used-days for a leave type (carry-in, correction).
    Absolute set, not a delta. Needs the same grant that decides leave."""
    _require(current_user, "attendance", "update")
    user_id = str(body.get("user_id") or "").strip()
    leave_type = str(body.get("leave_type") or "").strip().lower()
    if not user_id or not leave_type:
        raise HTTPException(status_code=400, detail="user_id and leave_type are required")
    yr = int(body.get("year") or int(ist_date_str()[:4]))
    entitled = body.get("entitled")
    used = body.get("used")
    if entitled is None and used is None:
        raise HTTPException(status_code=400, detail="Provide entitled and/or used")
    await set_balance(user_id, yr, leave_type,
                      entitled=None if entitled is None else float(entitled),
                      used=None if used is None else float(used))
    await log_activity(current_user, "Adjust Leave Balance", COL_LEAVES,
                       f"Balance set for {user_id}/{leave_type} {yr}")
    settings = await get_leave_settings()
    return {"userId": user_id, "year": yr,
            "balances": await all_balances(user_id, yr, settings)}


@router.get("/leaves")
async def list_leaves(
    scope: str = Query("mine", description="mine | pending | all"),
    status: Optional[str] = Query(None),
    current_user: dict = Depends(require_hrms_access),
):
    """Leave requests.

    `mine` is always allowed. `pending` is the approvals inbox — requests routed to the caller
    as reporting manager, plus everything unrouted when they hold the decide permission.
    """
    me = str(current_user["_id"])
    col = get_collection(COL_LEAVES)

    if scope == "mine":
        query = {"user_id": me}
    elif scope == "pending":
        _require(current_user, "attendance", "read")
        # Routed to me, or unrouted (no manager on the applicant) and I can decide.
        arms = [{"approver_id": me}]
        if has_hrms_permission(current_user, "attendance", "update"):
            arms.append({"approver_id": {"$in": [None, ""]}})
        query = {"status": LEAVE_PENDING, "$or": arms}
    else:
        _require(current_user, "attendance", "read")
        query = {}

    if status:
        query = {**query, "status": status}

    docs = await col.find(query).sort([("created_at", -1)]).to_list(500)

    # Resolve applicant names in ONE query rather than per row.
    ids = {d.get("user_id") for d in docs if d.get("user_id") and d.get("user_id") != me}
    people = {}
    if ids:
        oids = [ObjectId(i) for i in ids if ObjectId.is_valid(i)]
        async for u in get_collection("staff").find({"_id": {"$in": oids}},
                                                    {"full_name": 1, "email": 1}):
            people[str(u["_id"])] = u

    return [serialize_leave(d, people.get(d.get("user_id"))) for d in docs]


@router.post("/leaves")
async def apply_leave(body: LeaveApply, current_user: dict = Depends(require_hrms_access)):
    """Apply for leave. Applying reserves nothing — the balance moves only on approval."""
    me = str(current_user["_id"])
    settings = await get_leave_settings()

    type_def = find_leave_type(settings, body.leave_type)
    if not type_def:
        raise HTTPException(status_code=400, detail="Unknown or inactive leave type")
    if body.is_half_day and not type_def.get("allow_half_day", True):
        raise HTTPException(status_code=400,
                            detail=f"{type_def['name']} cannot be taken as a half day")
    if not (body.reason or "").strip():
        raise HTTPException(status_code=400, detail="A reason is required")

    try:
        start = parse_date(body.start_date)
        end = parse_date(body.end_date)
        days = await count_leave_days(start, end, body.is_half_day, settings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if days <= 0:
        raise HTTPException(
            status_code=400,
            detail="That range contains no working days — it is all weekly offs or holidays.")

    clash = await find_overlap(me, start, end)
    if clash:
        raise HTTPException(
            status_code=409,
            detail=f"You already have leave from {clash.get('start_date')} to {clash.get('end_date')}.")

    # Paid types can be balance-enforced; unpaid ones never block.
    if settings.get("enforce_balance") and type_def.get("paid", True):
        balance = await get_balance(me, start.year, body.leave_type, settings)
        if days > balance["remaining"]:
            raise HTTPException(
                status_code=400,
                detail=f"Only {balance['remaining']} day(s) of {type_def['name']} remaining.")

    approver_id = await resolve_approver(me)
    doc = {
        "user_id": me,
        "applicant_name": current_user.get("full_name") or current_user.get("email"),
        "leave_type": body.leave_type,
        "leave_type_name": type_def["name"],
        "paid": bool(type_def.get("paid", True)),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "is_half_day": body.is_half_day,
        "days": days,
        "reason": body.reason.strip(),
        "status": LEAVE_PENDING,
        "approver_id": approver_id or "",
        "created_at": datetime.now(timezone.utc),
    }
    result = await get_collection(COL_LEAVES).insert_one(doc)
    doc["_id"] = result.inserted_id

    await log_activity(current_user, "Apply Leave", COL_LEAVES,
                       f"{type_def['name']} {start} to {end} ({days} day(s))")
    return serialize_leave(doc)


@router.patch("/leaves/{leave_id}/decide")
async def decide_leave(leave_id: str, body: LeaveDecision,
                       current_user: dict = Depends(require_hrms_access)):
    """Approve or reject. The balance moves here and only here."""
    me = str(current_user["_id"])
    try:
        oid = ObjectId(leave_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    doc = await get_collection(COL_LEAVES).find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Leave request not found")
    if doc.get("status") != LEAVE_PENDING:
        raise HTTPException(status_code=409,
                            detail=f"This request is already {doc.get('status')}.")
    if doc.get("user_id") == me:
        raise HTTPException(status_code=403, detail="You cannot decide your own leave request.")

    # The routed manager may decide; anyone else needs the explicit grant.
    if doc.get("approver_id") != me:
        _require(current_user, "attendance", "update")

    if body.status not in (LEAVE_APPROVED, LEAVE_REJECTED):
        raise HTTPException(status_code=400,
                            detail=f"status must be {LEAVE_APPROVED} or {LEAVE_REJECTED}")

    await get_collection(COL_LEAVES).update_one({"_id": oid}, {"$set": {
        "status": body.status,
        "approver_id": me,
        "approver_name": current_user.get("full_name") or current_user.get("email"),
        "remark": (body.remark or "").strip(),
        "decided_at": datetime.now(timezone.utc),
    }})

    # Only an approved PAID request consumes entitlement.
    if body.status == LEAVE_APPROVED and doc.get("paid", True):
        year = int(str(doc.get("start_date"))[:4])
        await adjust_balance(doc["user_id"], year, doc["leave_type"], float(doc.get("days") or 0))

    await log_activity(current_user, "Decide Leave", COL_LEAVES,
                       f"Leave {leave_id} {body.status.lower()}")
    updated = await get_collection(COL_LEAVES).find_one({"_id": oid})
    return serialize_leave(updated)


@router.patch("/leaves/{leave_id}/cancel")
async def cancel_leave(leave_id: str, current_user: dict = Depends(require_hrms_access)):
    """Withdraw your own request. An approved one returns its days to the balance."""
    me = str(current_user["_id"])
    try:
        oid = ObjectId(leave_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    doc = await get_collection(COL_LEAVES).find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Leave request not found")
    if doc.get("user_id") != me and not has_hrms_permission(current_user, "attendance", "update"):
        raise HTTPException(status_code=403, detail="You can only cancel your own leave.")
    if doc.get("status") in (LEAVE_REJECTED, LEAVE_CANCELLED):
        raise HTTPException(status_code=409, detail=f"Already {doc.get('status')}.")

    was_approved = doc.get("status") == LEAVE_APPROVED
    await get_collection(COL_LEAVES).update_one({"_id": oid}, {"$set": {
        "status": LEAVE_CANCELLED,
        "decided_at": datetime.now(timezone.utc),
    }})
    # Give the days back, or an approved-then-cancelled leave would consume entitlement forever.
    if was_approved and doc.get("paid", True):
        year = int(str(doc.get("start_date"))[:4])
        await adjust_balance(doc["user_id"], year, doc["leave_type"], -float(doc.get("days") or 0))

    await log_activity(current_user, "Cancel Leave", COL_LEAVES, f"Leave {leave_id} cancelled")
    updated = await get_collection(COL_LEAVES).find_one({"_id": oid})
    return serialize_leave(updated)


# ─── Payroll ────────────────────────────────────────────────────────────────────
# `payroll.read` sees everyone's figures; `payroll.update` runs and locks a period. An employee
# always sees their OWN payslip — but only once the run is locked, so nobody plans around a
# draft that may still change.
@router.get("/payroll/config")
async def read_payroll_config(current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "payroll", "read")
    return (await get_payroll_config()).to_dict()


@router.put("/payroll/config")
async def write_payroll_config(body: PayrollConfigUpdate,
                               current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "payroll", "update")
    try:
        clean = validate_payroll_config(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    clean["updated_by"] = str(current_user["_id"])
    clean["updated_at"] = datetime.now(timezone.utc)
    await get_collection("system_settings").update_one(
        {"setting_name": SETTING_PAYROLL}, {"$set": clean}, upsert=True)
    await log_activity(current_user, "Update HRMS Settings", "system_settings",
                       "Payroll policy updated")
    return (await get_payroll_config()).to_dict()


@router.get("/payroll/runs")
async def list_payroll_runs(current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "payroll", "read")
    docs = await get_collection(COL_PAYROLL_RUNS).find({}).sort(
        [("year", -1), ("month", -1)]).to_list(60)
    return [serialize_run(d) for d in docs]


@router.get("/payroll")
async def read_payroll(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    current_user: dict = Depends(require_hrms_access),
):
    """Read a stored run. Never computes and never writes — the reference project's payroll GET
    mutates the leave ledger, which is why a page refresh could change someone's balance."""
    _require(current_user, "payroll", "read")
    run = await get_collection(COL_PAYROLL_RUNS).find_one({"year": year, "month": month})
    if not run:
        return {"run": None, "payslips": []}
    slips = await get_collection(COL_PAYSLIPS).find(
        {"run_id": str(run["_id"])}).sort([("fullName", 1)]).to_list(5000)
    return {"run": serialize_run(run), "payslips": [serialize_payslip(s) for s in slips]}


@router.post("/payroll/run")
async def create_payroll_run(body: PayrollRunRequest,
                             current_user: dict = Depends(require_hrms_access)):
    """Compute and store a draft run. Re-running replaces the draft; a locked period is refused."""
    _require(current_user, "payroll", "update")
    if not 1 <= body.month <= 12:
        raise HTTPException(status_code=400, detail="month must be 1-12")
    if not 2000 <= body.year <= 2999:
        raise HTTPException(status_code=400, detail="year is out of range")
    try:
        result = await run_payroll(body.year, body.month, current_user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    await log_activity(current_user, "Run Payroll", COL_PAYROLL_RUNS,
                       f"Payroll computed for {body.year}-{body.month:02d}")
    return result


@router.post("/payroll/lock")
async def lock_payroll_run(body: PayrollRunRequest,
                           current_user: dict = Depends(require_hrms_access)):
    """Freeze a period. After this the figures are what people were paid against, so nothing
    may recompute them."""
    _require(current_user, "payroll", "update")
    runs = get_collection(COL_PAYROLL_RUNS)
    run = await runs.find_one({"year": body.year, "month": body.month})
    if not run:
        raise HTTPException(status_code=404, detail="No payroll run for that period")
    if run.get("status") == RUN_LOCKED:
        raise HTTPException(status_code=409, detail="That period is already locked")

    await runs.update_one({"_id": run["_id"]}, {"$set": {
        "status": RUN_LOCKED,
        "locked_by": str(current_user["_id"]),
        "locked_by_name": current_user.get("full_name") or current_user.get("email"),
        "locked_at": datetime.now(timezone.utc),
    }})
    await log_activity(current_user, "Lock Payroll", COL_PAYROLL_RUNS,
                       f"Payroll locked for {body.year}-{body.month:02d}")
    return serialize_run(await runs.find_one({"_id": run["_id"]}))


@router.get("/payroll/payslip")
async def read_my_payslip(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    current_user: dict = Depends(require_hrms_access),
):
    """Your own payslip. Visible only once the period is locked — a draft can still change, and
    handing someone a number that later moves is worse than making them wait."""
    run = await get_collection(COL_PAYROLL_RUNS).find_one({"year": year, "month": month})
    if not run or run.get("status") != RUN_LOCKED:
        return {"payslip": None, "status": (run or {}).get("status") or "not_run"}

    slip = await get_collection(COL_PAYSLIPS).find_one({
        "run_id": str(run["_id"]), "userId": str(current_user["_id"])})
    if not slip:
        return {"payslip": None, "status": "no_record"}
    return {"payslip": serialize_payslip(slip), "status": RUN_LOCKED,
            "run": serialize_run(run)}


# ─── Recruitment: requisitions + JD ─────────────────────────────────────────────
# `recruitment.create` raises a requisition, `recruitment.update` reviews it as HR, and
# `recruitment.approve`-equivalent (delete, reserved for the admin tier) approves it as MD.
# Using the existing CRUD verbs rather than inventing a fifth keeps the permission dict uniform.
def _can_md_approve(user: dict) -> bool:
    """MD approval is the admin tier's call, matching how the reference reserves it for Admin."""
    return user.get("role") in ("superadmin", "admin") or has_hrms_permission(
        user, "recruitment", "delete")


@router.get("/requisitions")
async def list_requisitions(
    approval_status: Optional[str] = Query(None),
    closing_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: dict = Depends(require_hrms_access),
):
    _require(current_user, "recruitment", "read")
    query = {}
    if approval_status:
        query["approval_status"] = approval_status
    if closing_status:
        query["closing_status"] = closing_status
    if search:
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        query["$or"] = [{"designation": rx}, {"department": rx}, {"request_no": rx}]

    docs = await get_collection(COL_REQUISITIONS).find(query).sort(
        [("created_at", -1)]).to_list(1000)

    counts = {}
    async for row in get_collection(COL_REQUISITIONS).aggregate(
            [{"$group": {"_id": "$approval_status", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]

    return {
        "requisitions": [serialize_requisition(d) for d in docs],
        "stats": {
            "total": sum(counts.values()),
            "pendingHr": counts.get(REQ_PENDING_HR, 0),
            "pendingMd": counts.get(REQ_PENDING_MD, 0),
            "approved": counts.get(REQ_APPROVED, 0),
            "rejected": counts.get(REQ_REJECTED, 0),
        },
        "canApproveMd": _can_md_approve(current_user),
    }


@router.post("/requisitions")
async def create_requisition(body: RequisitionCreate,
                             current_user: dict = Depends(require_hrms_access)):
    """Raise a requisition. It enters the chain at Pending HR Review."""
    _require(current_user, "recruitment", "create")
    payload = body.model_dump()
    jd = payload.pop("jd", None)
    try:
        validate_requisition(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    now = datetime.now(timezone.utc)
    request_no = await generate_request_no()
    doc = {
        **payload,
        "request_no": request_no,
        "approval_status": REQ_PENDING_HR,
        "closing_status": REQ_OPEN,
        "steps": [],
        "created_by": str(current_user["_id"]),
        "created_by_name": current_user.get("full_name") or current_user.get("email"),
        "created_at": now,
        "updated_at": now,
    }
    jd_no = await upsert_jd(request_no, jd, current_user) if jd else None
    if jd_no:
        doc["jd_no"] = jd_no

    await get_collection(COL_REQUISITIONS).insert_one(doc)
    # A typed department/designation joins the org masters, same as on the employee form.
    await upsert_org_master(ORG_KIND_DEPARTMENT, payload.get("department"), current_user)
    await upsert_org_master(ORG_KIND_DESIGNATION, payload.get("designation"), current_user)

    await log_activity(current_user, "Create Requisition", COL_REQUISITIONS,
                       f"Requisition {request_no}: {payload.get('designation')}")
    saved = await get_collection(COL_REQUISITIONS).find_one({"request_no": request_no})
    return serialize_requisition(saved, await get_jd(request_no))


@router.get("/requisitions/{request_no}")
async def read_requisition(request_no: str, current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "recruitment", "read")
    doc = await get_collection(COL_REQUISITIONS).find_one({"request_no": request_no})
    if not doc:
        raise HTTPException(status_code=404, detail="Requisition not found")
    return serialize_requisition(doc, await get_jd(request_no))


@router.patch("/requisitions/{request_no}")
async def update_requisition(request_no: str, body: RequisitionUpdate,
                             current_user: dict = Depends(require_hrms_access)):
    """Edit a requisition. Refused once approved — the approved terms are what was signed off."""
    _require(current_user, "recruitment", "update")
    doc = await get_collection(COL_REQUISITIONS).find_one({"request_no": request_no})
    if not doc:
        raise HTTPException(status_code=404, detail="Requisition not found")
    if doc.get("approval_status") == REQ_APPROVED:
        raise HTTPException(
            status_code=409,
            detail="An approved requisition cannot be edited. Close it and raise a new one.")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    jd = updates.pop("jd", None)
    if updates:
        try:
            validate_requisition({**doc, **updates})
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        updates["updated_at"] = datetime.now(timezone.utc)
        await get_collection(COL_REQUISITIONS).update_one(
            {"request_no": request_no}, {"$set": updates})

    if jd:
        jd_no = await upsert_jd(request_no, jd, current_user)
        if jd_no and not doc.get("jd_no"):
            await get_collection(COL_REQUISITIONS).update_one(
                {"request_no": request_no}, {"$set": {"jd_no": jd_no}})

    await log_activity(current_user, "Update Requisition", COL_REQUISITIONS,
                       f"Requisition {request_no} updated")
    saved = await get_collection(COL_REQUISITIONS).find_one({"request_no": request_no})
    return serialize_requisition(saved, await get_jd(request_no))


@router.post("/requisitions/{request_no}/decide")
async def decide_requisition(request_no: str, body: RequisitionDecision,
                             current_user: dict = Depends(require_hrms_access)):
    """Move the requisition one step along the chain.

    One endpoint for the whole chain: the server derives which step is being taken from the
    current state, so the client can't skip HR review or approve twice.
    """
    doc = await get_collection(COL_REQUISITIONS).find_one({"request_no": request_no})
    if not doc:
        raise HTTPException(status_code=404, detail="Requisition not found")

    current = doc.get("approval_status") or REQ_PENDING_HR
    # MD approval is the admin tier's; HR review and resubmission need the update grant.
    if current == REQ_PENDING_MD and body.action == "advance":
        if not _can_md_approve(current_user):
            raise HTTPException(status_code=403,
                                detail="Only an admin can give MD approval.")
    else:
        _require(current_user, "recruitment", "update")

    # The person who raised it shouldn't also wave it through.
    if body.action == "advance" and doc.get("created_by") == str(current_user["_id"]) \
            and not _can_md_approve(current_user):
        raise HTTPException(status_code=403,
                            detail="You cannot review a requisition you raised.")

    try:
        outcome = await apply_decision(doc, body.action, current_user,
                                       body.remarks or "", body.salary_change or "")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    await get_collection(COL_REQUISITIONS).update_one(
        {"request_no": request_no},
        {"$set": outcome["updates"], "$push": {"steps": outcome["step"]}})

    await log_activity(current_user, "Decide Requisition", COL_REQUISITIONS,
                       f"Requisition {request_no}: {outcome['step']['label']}")
    saved = await get_collection(COL_REQUISITIONS).find_one({"request_no": request_no})
    return serialize_requisition(saved, await get_jd(request_no))


@router.post("/requisitions/{request_no}/close")
async def close_requisition(request_no: str, body: RequisitionClose,
                            current_user: dict = Depends(require_hrms_access)):
    """Set where the vacancy stands — hired, closed, on hold, cancelled.

    Separate from the approval chain: an approved requisition stays approved even once it is
    filled. (The reference ships this API with no UI at all; here it is wired to a control.)
    """
    _require(current_user, "recruitment", "update")
    if body.closing_status not in REQ_CLOSING_STATES:
        raise HTTPException(status_code=400,
                            detail=f"closing_status must be one of {REQ_CLOSING_STATES}")
    doc = await get_collection(COL_REQUISITIONS).find_one({"request_no": request_no})
    if not doc:
        raise HTTPException(status_code=404, detail="Requisition not found")

    step = build_step(doc.get("closing_status") or REQ_OPEN, body.closing_status,
                      current_user, body.remarks or "")
    step["label"] = f"Vacancy marked {body.closing_status}"
    await get_collection(COL_REQUISITIONS).update_one({"request_no": request_no}, {
        "$set": {"closing_status": body.closing_status,
                 "updated_at": datetime.now(timezone.utc)},
        "$push": {"steps": step},
    })
    await log_activity(current_user, "Close Requisition", COL_REQUISITIONS,
                       f"Requisition {request_no} marked {body.closing_status}")
    saved = await get_collection(COL_REQUISITIONS).find_one({"request_no": request_no})
    return serialize_requisition(saved, await get_jd(request_no))


# ─── Job postings ───────────────────────────────────────────────────────────────
@router.get("/postings")
async def list_postings(current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "recruitment", "read")
    docs = await get_collection(COL_POSTINGS).find({}).sort([("created_at", -1)]).to_list(500)
    return [serialize_posting(d) for d in docs]


@router.post("/postings")
async def add_posting(body: PostingCreate, current_user: dict = Depends(require_hrms_access)):
    """Publish an approved requisition to one platform, each with its own public link."""
    _require(current_user, "recruitment", "create")
    try:
        doc = await create_posting(body.request_no, body.platform, body.notes or "",
                                   body.expires_on, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await log_activity(current_user, "Create Job Posting", COL_POSTINGS,
                       f"{doc['designation']} posted to {doc['platform']}")
    return serialize_posting(doc)


@router.patch("/postings/{posting_id}")
async def edit_posting(posting_id: str, body: PostingUpdate,
                       current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "recruitment", "update")
    try:
        oid = ObjectId(posting_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates.get("status") and updates["status"] not in POSTING_STATES:
        raise HTTPException(status_code=400, detail=f"status must be one of {POSTING_STATES}")
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = datetime.now(timezone.utc)
    result = await get_collection(COL_POSTINGS).update_one({"_id": oid}, {"$set": updates})
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Posting not found")
    return serialize_posting(await get_collection(COL_POSTINGS).find_one({"_id": oid}))


# ─── PUBLIC: apply ──────────────────────────────────────────────────────────────
# The app's first unauthenticated surface. Everything here is rate-limited, size-capped and
# state-gated, and no internal identifier is ever returned.
@router.get("/public/postings/{code}")
async def public_posting(code: str, request: Request):
    """What an applicant sees before applying. No auth, so it returns the role only."""
    rate_limit(request, "lookup")
    posting = await get_collection(COL_POSTINGS).find_one({"public_code": code})
    live, reason = posting_is_live(posting)
    if not live:
        # A closed and a non-existent code give the same shape, so the endpoint can't be used to
        # confirm which codes exist.
        raise HTTPException(status_code=404, detail=reason or "This link is not valid.")
    jd = await get_jd(posting.get("request_no"))
    return serialize_public_posting({**posting, "_jd": serialize_jd(jd)})


@router.post("/public/postings/{code}/apply")
async def public_apply(code: str, body: PublicApplication, request: Request):
    """Accept an application from an anonymous visitor."""
    rate_limit(request, "apply")

    posting = await get_collection(COL_POSTINGS).find_one({"public_code": code})
    live, reason = posting_is_live(posting)
    if not live:
        raise HTTPException(status_code=404, detail=reason or "This link is not valid.")

    payload = body.model_dump()
    resume = payload.pop("resume", None)
    try:
        validate_applicant(payload)
    except ValueError as e:
        raise safe_public_error(str(e))

    email = payload["email"].strip().lower()
    # One application per person per role. The reference has no dedupe at all, so a refresh
    # creates another candidate.
    existing = await get_collection(COL_CANDIDATES).find_one({
        "email": email, "request_no": posting.get("request_no")})
    if existing:
        raise HTTPException(
            status_code=409,
            detail="You have already applied for this role. We will be in touch.")

    upload = decode_upload(resume)      # raises 400 with applicant-facing copy
    uk = await generate_candidate_uk()
    resume_key = store_resume(upload["blob"], upload["extension"],
                              upload["content_type"], uk) if upload else ""

    now = datetime.now(timezone.utc)
    doc = {
        **payload,
        "uk": uk,
        "email": email,
        "request_no": posting.get("request_no"),
        "designation": posting.get("designation"),
        "department": posting.get("department"),
        "platform": posting.get("platform"),
        "source": "Public link",
        "resume_key": resume_key,
        "stage": STAGE_APPLIED,
        "assessments": [],
        "interviews": [],
        "journey": [],
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COL_CANDIDATES).insert_one(doc)
    await get_collection(COL_POSTINGS).update_one(
        {"_id": posting["_id"]}, {"$inc": {"applications": 1}})

    # Nothing internal comes back — no candidate id, no requisition number.
    return {"message": "Thank you. Your application has been received."}


# ─── Candidates & screening ─────────────────────────────────────────────────────
@router.get("/candidates")
async def list_candidates(
    stage: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: dict = Depends(require_hrms_access),
):
    _require(current_user, "recruitment", "read")
    query = {}
    if stage:
        query["stage"] = stage
    if request_no:
        query["request_no"] = request_no
    if search:
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        query["$or"] = [{"full_name": rx}, {"email": rx}, {"uk": rx}, {"current_company": rx}]

    docs = await get_collection(COL_CANDIDATES).find(query).sort(
        [("created_at", -1)]).to_list(2000)

    counts = {}
    async for row in get_collection(COL_CANDIDATES).aggregate(
            [{"$group": {"_id": "$stage", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]

    return {
        # Access codes are never included here — see serialize_candidate.
        "candidates": [serialize_candidate(d) for d in docs],
        "stages": CANDIDATE_STAGES,
        "counts": counts,
        "total": sum(counts.values()),
    }


@router.post("/candidates")
async def add_candidate(body: CandidateCreate, current_user: dict = Depends(require_hrms_access)):
    """HR entering a candidate directly (referral, agency, walk-in)."""
    _require(current_user, "recruitment", "create")
    payload = body.model_dump()
    try:
        validate_applicant(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    email = payload["email"].strip().lower()
    if await get_collection(COL_CANDIDATES).find_one({
            "email": email, "request_no": payload.get("request_no") or ""}):
        raise HTTPException(status_code=409,
                            detail="That candidate has already been added for this role.")

    designation = department = ""
    if payload.get("request_no"):
        req = await get_collection(COL_REQUISITIONS).find_one(
            {"request_no": payload["request_no"]})
        if req:
            designation = req.get("designation") or ""
            department = req.get("department") or ""

    now = datetime.now(timezone.utc)
    uk = await generate_candidate_uk()
    doc = {
        **payload, "uk": uk, "email": email,
        "designation": designation, "department": department,
        "stage": STAGE_APPLIED, "assessments": [], "interviews": [], "journey": [],
        "created_by": str(current_user["_id"]),
        "created_at": now, "updated_at": now,
    }
    await get_collection(COL_CANDIDATES).insert_one(doc)
    await log_activity(current_user, "Add Candidate", COL_CANDIDATES, f"Candidate {uk} added")
    return serialize_candidate(doc)


@router.post("/candidates/screen")
async def screen_candidates(body: ScreenDecision,
                            current_user: dict = Depends(require_hrms_access)):
    """Move one or many candidates along the pipeline.

    Bulk by design — screening is done in batches. Each move is validated individually, so one
    illegal transition doesn't abort the rest and isn't silently applied either.
    """
    _require(current_user, "recruitment", "update")
    if body.stage not in CANDIDATE_STAGES:
        raise HTTPException(status_code=400, detail=f"stage must be one of {CANDIDATE_STAGES}")
    if not body.candidate_ids:
        raise HTTPException(status_code=400, detail="No candidates selected")

    col = get_collection(COL_CANDIDATES)
    moved, skipped = [], []
    for cid in body.candidate_ids:
        try:
            oid = ObjectId(cid)
        except Exception:
            skipped.append({"id": cid, "reason": "invalid id"})
            continue
        doc = await col.find_one({"_id": oid})
        if not doc:
            skipped.append({"id": cid, "reason": "not found"})
            continue
        current = doc.get("stage") or STAGE_APPLIED
        if not can_advance(current, body.stage):
            skipped.append({"id": cid, "reason": f"cannot move from {current} to {body.stage}"})
            continue

        updates = {"stage": body.stage, "updated_at": datetime.now(timezone.utc)}
        if body.stage == STAGE_REJECTED:
            updates["rejection_reason"] = body.remarks or ""
        await col.update_one({"_id": oid}, {
            "$set": updates,
            "$push": {"journey": journey_entry(current, body.stage, current_user, body.remarks or "")},
        })
        moved.append(cid)

    await log_activity(current_user, "Screen Candidates", COL_CANDIDATES,
                       f"{len(moved)} candidate(s) moved to {body.stage}")
    # Skipped rows are reported rather than swallowed, so a bulk action can't quietly do less
    # than the user thinks it did.
    return {"moved": len(moved), "skipped": skipped, "stage": body.stage}


@router.get("/candidates/{uk}")
async def read_candidate(uk: str, current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "recruitment", "read")
    doc = await get_collection(COL_CANDIDATES).find_one({"uk": uk})
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return serialize_candidate(doc)


# ─── Assessments ────────────────────────────────────────────────────────────────
@router.post("/candidates/{uk}/assessments")
async def send_assessment(uk: str, body: AssessmentSend,
                          current_user: dict = Depends(require_hrms_access)):
    """Create an assessment and return its link ONCE, to the HR user who made it.

    This is the only endpoint that reveals an access code. Every list/read response omits it —
    the reference returns every candidate's code to any logged-in user.
    """
    _require(current_user, "recruitment", "update")
    col = get_collection(COL_CANDIDATES)
    doc = await col.find_one({"uk": uk})
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if doc.get("stage") == STAGE_REJECTED:
        raise HTTPException(status_code=409,
                            detail="This candidate has been rejected.")

    assessment = {
        "id": str(ObjectId()),
        "access_code": public_token(),
        "title": body.title or "Written assessment",
        "instructions": body.instructions or "",
        "questions": body.questions or [],
        "answers": [],
        "due_on": body.due_on,
        "status": ASSESSMENT_SENT,
        "sent_by": str(current_user["_id"]),
        "sent_at": datetime.now(timezone.utc),
    }
    push = {"$push": {"assessments": assessment}, "$set": {"updated_at": datetime.now(timezone.utc)}}
    current = doc.get("stage") or STAGE_APPLIED
    if can_advance(current, STAGE_ASSESSMENT):
        push["$set"]["stage"] = STAGE_ASSESSMENT
        push["$push"]["journey"] = journey_entry(current, STAGE_ASSESSMENT, current_user,
                                                 "Assessment sent")
    await col.update_one({"_id": doc["_id"]}, push)

    await log_activity(current_user, "Send Assessment", COL_CANDIDATES,
                       f"Assessment sent to candidate {uk}")
    return {"assessmentId": assessment["id"], "accessCode": assessment["access_code"]}


@router.post("/candidates/{uk}/assessments/{assessment_id}/review")
async def review_assessment(uk: str, assessment_id: str, body: AssessmentReview,
                            current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "recruitment", "update")
    col = get_collection(COL_CANDIDATES)
    doc = await col.find_one({"uk": uk})
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found")
    target = next((a for a in doc.get("assessments", []) if a.get("id") == assessment_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if target.get("status") != ASSESSMENT_SUBMITTED:
        raise HTTPException(status_code=409,
                            detail="That assessment has not been submitted yet.")

    await col.update_one(
        {"_id": doc["_id"], "assessments.id": assessment_id},
        {"$set": {
            "assessments.$.status": ASSESSMENT_REVIEWED,
            "assessments.$.score": body.score,
            "assessments.$.passed": body.passed,
            "assessments.$.remarks": body.remarks or "",
            "assessments.$.reviewed_by": str(current_user["_id"]),
            "assessments.$.reviewed_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }})
    return serialize_candidate(await col.find_one({"_id": doc["_id"]}))


# ─── PUBLIC: assessment ─────────────────────────────────────────────────────────
@router.get("/public/assessments/{code}")
async def public_assessment(code: str, request: Request):
    """The questions, for the candidate holding the link. Marks it Opened once."""
    rate_limit(request, "assess")
    doc = await find_candidate_by_assessment_code(code)
    assessment = find_assessment(doc, code) if doc else None
    if not assessment:
        raise HTTPException(status_code=404, detail="This link is not valid.")
    if assessment.get("status") in (ASSESSMENT_SUBMITTED, ASSESSMENT_REVIEWED):
        raise HTTPException(status_code=409,
                            detail="This assessment has already been submitted.")

    if assessment.get("status") == ASSESSMENT_SENT:
        await get_collection(COL_CANDIDATES).update_one(
            {"_id": doc["_id"], "assessments.access_code": code},
            {"$set": {"assessments.$.status": ASSESSMENT_OPENED,
                      "assessments.$.opened_at": datetime.now(timezone.utc)}})

    return {
        "candidateName": doc.get("full_name") or "",
        "title": assessment.get("title") or "",
        "instructions": assessment.get("instructions") or "",
        "questions": assessment.get("questions") or [],
        "dueOn": assessment.get("due_on"),
    }


@router.post("/public/assessments/{code}/submit")
async def public_submit_assessment(code: str, body: AssessmentSubmission, request: Request):
    """Accept the candidate's answers. State-gated, so the link can't be replayed."""
    rate_limit(request, "assess")
    doc = await find_candidate_by_assessment_code(code)
    assessment = find_assessment(doc, code) if doc else None
    if not assessment:
        raise HTTPException(status_code=404, detail="This link is not valid.")
    if assessment.get("status") in (ASSESSMENT_SUBMITTED, ASSESSMENT_REVIEWED):
        # 409 rather than silently overwriting — the reference's onboarding equivalent lets a
        # public link rewrite verified data forever.
        raise HTTPException(status_code=409,
                            detail="This assessment has already been submitted.")

    await get_collection(COL_CANDIDATES).update_one(
        {"_id": doc["_id"], "assessments.access_code": code},
        {"$set": {
            "assessments.$.answers": body.answers or [],
            "assessments.$.note": body.note or "",
            "assessments.$.status": ASSESSMENT_SUBMITTED,
            "assessments.$.submitted_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }})
    return {"message": "Thank you. Your assessment has been submitted."}


# ─── Interviews ─────────────────────────────────────────────────────────────────
@router.post("/candidates/{uk}/interviews")
async def schedule_interview(uk: str, body: InterviewSchedule,
                             current_user: dict = Depends(require_hrms_access)):
    _require(current_user, "recruitment", "update")
    col = get_collection(COL_CANDIDATES)
    doc = await col.find_one({"uk": uk})
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if doc.get("stage") == STAGE_REJECTED:
        raise HTTPException(status_code=409, detail="This candidate has been rejected.")

    names = []
    if body.interviewer_ids:
        oids = [ObjectId(i) for i in body.interviewer_ids if ObjectId.is_valid(i)]
        async for u in get_collection("staff").find({"_id": {"$in": oids}},
                                                    {"full_name": 1, "email": 1}):
            names.append(u.get("full_name") or u.get("email"))

    interview = {
        "id": str(ObjectId()),
        "round_name": body.round_name or "Round 1",
        "scheduled_at": body.scheduled_at,
        "duration_minutes": int(body.duration_minutes or 45),
        "mode": body.mode or "In person",
        "location": body.location or "",
        "interviewer_ids": body.interviewer_ids or [],
        "interviewer_names": names,
        "status": INTERVIEW_SCHEDULED,
        "scheduled_by": str(current_user["_id"]),
        "created_at": datetime.now(timezone.utc),
    }
    push = {"$push": {"interviews": interview},
            "$set": {"updated_at": datetime.now(timezone.utc)}}
    current = doc.get("stage") or STAGE_APPLIED
    if can_advance(current, STAGE_INTERVIEW):
        push["$set"]["stage"] = STAGE_INTERVIEW
        push["$push"]["journey"] = journey_entry(current, STAGE_INTERVIEW, current_user,
                                                 f"{interview['round_name']} scheduled")
    await col.update_one({"_id": doc["_id"]}, push)

    await log_activity(current_user, "Schedule Interview", COL_CANDIDATES,
                       f"{interview['round_name']} scheduled for candidate {uk}")
    return serialize_candidate(await col.find_one({"_id": doc["_id"]}))


@router.post("/candidates/{uk}/interviews/{interview_id}/evaluate")
async def evaluate_interview(uk: str, interview_id: str, body: InterviewEvaluation,
                             current_user: dict = Depends(require_hrms_access)):
    """Record a scorecard. The assigned interviewer may do this without the update grant —
    they are the person who conducted it."""
    col = get_collection(COL_CANDIDATES)
    doc = await col.find_one({"uk": uk})
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found")
    target = next((i for i in doc.get("interviews", []) if i.get("id") == interview_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Interview not found")

    me = str(current_user["_id"])
    if me not in (target.get("interviewer_ids") or []):
        _require(current_user, "recruitment", "update")
    if target.get("status") == INTERVIEW_CANCELLED:
        raise HTTPException(status_code=409, detail="That interview was cancelled.")
    if body.recommendation not in ("Proceed", "Hold", "Reject"):
        raise HTTPException(status_code=400,
                            detail="recommendation must be Proceed, Hold or Reject")

    await col.update_one(
        {"_id": doc["_id"], "interviews.id": interview_id},
        {"$set": {
            "interviews.$.status": INTERVIEW_DONE,
            "interviews.$.recommendation": body.recommendation,
            "interviews.$.score": body.score,
            "interviews.$.strengths": body.strengths or "",
            "interviews.$.concerns": body.concerns or "",
            "interviews.$.remarks": body.remarks or "",
            "interviews.$.evaluated_by": me,
            "interviews.$.evaluated_by_name": current_user.get("full_name") or current_user.get("email"),
            "interviews.$.evaluated_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }})
    await log_activity(current_user, "Evaluate Interview", COL_CANDIDATES,
                       f"Interview evaluated for candidate {uk}: {body.recommendation}")
    return serialize_candidate(await col.find_one({"_id": doc["_id"]}))


# ─── Offers ─────────────────────────────────────────────────────────────────────
def _can_read_kyc(user: dict) -> bool:
    """Who may see a candidate's statutory and bank details.

    Deliberately narrower than `recruitment.read`: a recruiter can run the pipeline without
    ever seeing someone's bank account. The reference guards the same data with "any
    authenticated user" and returns the whole workforce's KYC — its own audit's C-3.
    """
    return user.get("role") == "superadmin" or has_hrms_permission(user, "hrms", "update")


@router.post("/candidates/{uk}/offers")
async def create_offer(uk: str, body: OfferCreate,
                       current_user: dict = Depends(require_hrms_access)):
    """Draft and send an offer. Returns the candidate link ONCE, like assessments."""
    _require(current_user, "recruitment", "update")
    col = get_collection(COL_CANDIDATES)
    doc = await col.find_one({"uk": uk})
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if doc.get("stage") == STAGE_REJECTED:
        raise HTTPException(status_code=409, detail="This candidate has been rejected.")

    live = active_offer(doc)
    if live and live.get("status") not in OFFER_FINAL:
        raise HTTPException(
            status_code=409,
            detail="An offer is already open with this candidate. Withdraw it first.")
    if float(body.annual_ctc or 0) <= 0:
        raise HTTPException(status_code=400, detail="Annual CTC must be greater than zero")

    offer = {
        "id": str(ObjectId()),
        "access_code": public_token(),
        "designation": body.designation,
        "department": body.department or "",
        "annual_ctc": float(body.annual_ctc),
        "joining_date": body.joining_date,
        "location": body.location or "",
        "employment_type": body.employment_type or "Full-time",
        "probation_months": body.probation_months,
        "notes": body.notes or "",
        "valid_till": body.valid_till,
        "status": OFFER_SENT,
        "sent_by": str(current_user["_id"]),
        "sent_at": datetime.now(timezone.utc),
    }
    push = {"$push": {"offers": offer}, "$set": {"updated_at": datetime.now(timezone.utc)}}
    current = doc.get("stage") or STAGE_APPLIED
    if can_advance(current, STAGE_OFFER):
        push["$set"]["stage"] = STAGE_OFFER
        push["$push"]["journey"] = journey_entry(current, STAGE_OFFER, current_user, "Offer sent")
    await col.update_one({"_id": doc["_id"]}, push)

    await log_activity(current_user, "Send Offer", COL_CANDIDATES, f"Offer sent to candidate {uk}")
    return {"offerId": offer["id"], "accessCode": offer["access_code"]}


@router.post("/candidates/{uk}/offers/{offer_id}/withdraw")
async def withdraw_offer(uk: str, offer_id: str,
                         current_user: dict = Depends(require_hrms_access)):
    """Pull an offer back. Refused once the candidate has answered — you cannot un-accept."""
    _require(current_user, "recruitment", "update")
    col = get_collection(COL_CANDIDATES)
    doc = await col.find_one({"uk": uk})
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found")
    target = next((o for o in doc.get("offers", []) if o.get("id") == offer_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Offer not found")
    if target.get("status") in OFFER_FINAL:
        raise HTTPException(status_code=409,
                            detail=f"That offer is already {target.get('status').lower()}.")

    await col.update_one({"_id": doc["_id"], "offers.id": offer_id}, {"$set": {
        "offers.$.status": OFFER_WITHDRAWN,
        "offers.$.decided_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }})
    await log_activity(current_user, "Withdraw Offer", COL_CANDIDATES, f"Offer withdrawn for {uk}")
    return serialize_candidate(await col.find_one({"_id": doc["_id"]}),
                               include_kyc=_can_read_kyc(current_user))


# ─── PUBLIC: offer ──────────────────────────────────────────────────────────────
@router.get("/public/offers/{code}")
async def public_offer(code: str, request: Request):
    """The offer, for the candidate holding the link."""
    rate_limit(request, "assess")
    doc = await find_candidate_by_offer_code(code)
    offer = find_offer(doc, code) if doc else None
    usable, reason = offer_link_state(offer)
    if not usable:
        # 409 when it was already answered, 404 otherwise — the candidate gets a true
        # explanation without the endpoint confirming which codes exist.
        status = 409 if offer and offer.get("status") in OFFER_FINAL else 404
        raise HTTPException(status_code=status, detail=reason)

    return {
        "candidateName": doc.get("full_name") or "",
        "designation": offer.get("designation") or "",
        "department": offer.get("department") or "",
        "annualCtc": float(offer.get("annual_ctc") or 0),
        "joiningDate": offer.get("joining_date"),
        "location": offer.get("location") or "",
        "employmentType": offer.get("employment_type") or "",
        "probationMonths": offer.get("probation_months"),
        "notes": offer.get("notes") or "",
        "validTill": offer.get("valid_till"),
    }


@router.post("/public/offers/{code}/respond")
async def public_offer_respond(code: str, body: OfferDecision, request: Request):
    """Accept or decline. State-gated, so the link cannot be replayed to change the answer."""
    rate_limit(request, "assess")
    doc = await find_candidate_by_offer_code(code)
    offer = find_offer(doc, code) if doc else None
    usable, reason = offer_link_state(offer)
    if not usable:
        status = 409 if offer and offer.get("status") in OFFER_FINAL else 404
        raise HTTPException(status_code=status, detail=reason)

    new_status = OFFER_ACCEPTED if body.accept else OFFER_DECLINED
    updates = {
        "offers.$.status": new_status,
        "offers.$.candidate_note": (body.note or "").strip(),
        "offers.$.decided_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    # Declining ends the pipeline for this candidate; accepting leaves them at Offer until HR
    # completes onboarding, so the funnel never shows someone as Hired before they have joined.
    if not body.accept:
        updates["stage"] = STAGE_REJECTED
        updates["rejection_reason"] = "Offer declined by candidate"

    await get_collection(COL_CANDIDATES).update_one(
        {"_id": doc["_id"], "offers.access_code": code}, {"$set": updates})

    return {"message": "Thank you. Your response has been recorded."
            if body.accept else "Thank you for letting us know."}


# ─── Onboarding ─────────────────────────────────────────────────────────────────
@router.post("/candidates/{uk}/onboarding")
async def invite_onboarding(uk: str, body: OnboardingInvite,
                            current_user: dict = Depends(require_hrms_access)):
    """Open the KYC form for a candidate who accepted. Returns the link once."""
    _require(current_user, "recruitment", "update")
    col = get_collection(COL_CANDIDATES)
    doc = await col.find_one({"uk": uk})
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found")

    accepted = next((o for o in (doc.get("offers") or [])
                     if o.get("status") == OFFER_ACCEPTED), None)
    if not accepted:
        raise HTTPException(status_code=409,
                            detail="Onboarding starts once the candidate has accepted an offer.")
    existing = doc.get("onboarding") or {}
    if existing.get("status") == ONB_CONVERTED:
        raise HTTPException(status_code=409,
                            detail="This candidate has already been converted to an employee.")

    onboarding = {
        "access_code": public_token(),
        "status": ONB_INVITED,
        "message": body.message or "",
        "due_on": body.due_on,
        "invited_by": str(current_user["_id"]),
        "invited_at": datetime.now(timezone.utc),
    }
    await col.update_one({"_id": doc["_id"]},
                         {"$set": {"onboarding": onboarding,
                                   "updated_at": datetime.now(timezone.utc)}})
    await log_activity(current_user, "Invite Onboarding", COL_CANDIDATES,
                       f"Onboarding invited for candidate {uk}")
    return {"accessCode": onboarding["access_code"]}


@router.post("/candidates/{uk}/onboarding/verify")
async def verify_onboarding(uk: str, body: OnboardingVerify,
                            current_user: dict = Depends(require_hrms_access)):
    """HR confirming the submitted KYC. After this the public link is closed for good."""
    _require(current_user, "hrms", "update")
    col = get_collection(COL_CANDIDATES)
    doc = await col.find_one({"uk": uk})
    if not doc or not doc.get("onboarding"):
        raise HTTPException(status_code=404, detail="Onboarding not found")
    if doc["onboarding"].get("status") != ONB_SUBMITTED:
        raise HTTPException(status_code=409,
                            detail="Only a submitted onboarding can be verified.")

    await col.update_one({"_id": doc["_id"]}, {"$set": {
        "onboarding.status": ONB_VERIFIED,
        "onboarding.remarks": body.remarks or "",
        "onboarding.verified_by": str(current_user["_id"]),
        "onboarding.verified_by_name": current_user.get("full_name") or current_user.get("email"),
        "onboarding.verified_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }})
    await log_activity(current_user, "Verify Onboarding", COL_CANDIDATES,
                       f"Onboarding verified for candidate {uk}")
    return serialize_candidate(await col.find_one({"_id": doc["_id"]}), include_kyc=True)


@router.post("/candidates/{uk}/onboarding/convert")
async def convert_to_employee(uk: str, body: ConvertToEmployee,
                              current_user: dict = Depends(require_hrms_access)):
    """Create the employee record from a verified onboarding.

    Idempotent: converting twice returns the SAME employee rather than creating a second one.
    The reference's onboarding never creates an employee at all — the handoff is missing, so
    HR retypes everything.
    """
    _require(current_user, "hrms", "create")
    col = get_collection(COL_CANDIDATES)
    doc = await col.find_one({"uk": uk})
    onb = (doc or {}).get("onboarding") or {}
    if not doc or not onb:
        raise HTTPException(status_code=404, detail="Onboarding not found")

    if onb.get("status") == ONB_CONVERTED and onb.get("employee_code"):
        existing = await find_employee(onb["employee_code"])
        if existing:
            return serialize_employee(existing, can_read_personal_data(current_user))

    if onb.get("status") != ONB_VERIFIED:
        raise HTTPException(status_code=409,
                            detail="Verify the submitted details before creating the employee.")

    offer = next((o for o in (doc.get("offers") or [])
                  if o.get("status") == OFFER_ACCEPTED), None)
    if not offer:
        raise HTTPException(status_code=409, detail="No accepted offer found for this candidate.")

    if body.user_id:
        if not await link_user_exists(body.user_id):
            raise HTTPException(status_code=400,
                                detail="Linked user must be an internal staff account")
        clash = await get_collection(COL_EMPLOYEES).find_one({"user_id": body.user_id})
        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"That account is already linked to employee {clash.get('employee_code')}")

    now = datetime.now(timezone.utc)
    joining = body.date_of_joining or offer.get("joining_date")
    employee_code = await generate_employee_code()
    employee = {
        "employee_code": employee_code,
        "user_id": body.user_id or "",
        # Provenance, so an employee can always be traced back to the hire that produced them.
        "candidate_uk": uk,
        "full_name": doc.get("full_name") or "",
        "display_name": "",
        "work_email": doc.get("email") or "",
        "personal_email": onb.get("personal_email") or "",
        "phone": onb.get("phone") or doc.get("phone") or "",
        "gender": onb.get("gender") or "",
        "date_of_birth": onb.get("date_of_birth"),
        "address": onb.get("address") or "",
        "emergency_name": onb.get("emergency_name") or "",
        "emergency_relation": onb.get("emergency_relation") or "",
        "emergency_phone": onb.get("emergency_phone") or "",
        "designation": offer.get("designation") or "",
        "department": offer.get("department") or "",
        "location": offer.get("location") or "",
        "employment_type": offer.get("employment_type") or "Full-time",
        "work_mode": "Office",
        "status": "Probation" if offer.get("probation_months") else "Active",
        "date_of_joining": joining,
        "ctc_annual": float(offer.get("annual_ctc") or 0),
        "pan": onb.get("pan") or "",
        "aadhaar": onb.get("aadhaar") or "",
        "passport": onb.get("passport") or "",
        "driving_license": onb.get("driving_license") or "",
        "uan": onb.get("uan") or "",
        "esic_no": onb.get("esic_no") or "",
        "bank_name": onb.get("bank_name") or "",
        "bank_account": onb.get("bank_account") or "",
        "bank_ifsc": onb.get("bank_ifsc") or "",
        "created_by": str(current_user["_id"]),
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COL_EMPLOYEES).insert_one(employee)

    await col.update_one({"_id": doc["_id"]}, {"$set": {
        "onboarding.status": ONB_CONVERTED,
        "onboarding.employee_code": employee_code,
        "onboarding.converted_at": now,
        "stage": STAGE_HIRED,
        "updated_at": now,
    }, "$push": {"journey": journey_entry(doc.get("stage") or STAGE_OFFER, STAGE_HIRED,
                                          current_user, f"Converted to employee {employee_code}")}})

    await add_employee_event(employee_code, EVENT_CREATED,
                             f"Hired from candidate {uk}", current_user, effective_date=joining)
    await log_activity(current_user, "Convert Candidate", COL_EMPLOYEES,
                       f"Candidate {uk} converted to employee {employee_code}")

    created = await find_employee(employee_code)
    return serialize_employee(created, can_read_personal_data(current_user))


# ─── PUBLIC: onboarding ─────────────────────────────────────────────────────────
@router.get("/public/onboarding/{code}")
async def public_onboarding(code: str, request: Request):
    """The KYC form for the new joiner.

    Returns only what the form needs to render. It never echoes back previously submitted
    identifiers, so the link cannot be used to READ someone's bank details.
    """
    rate_limit(request, "assess")
    doc = await find_candidate_by_onboarding_code(code)
    onb = (doc or {}).get("onboarding") if doc else None
    if not onb:
        raise HTTPException(status_code=404, detail="This link is not valid.")
    if onb.get("status") in (ONB_VERIFIED, ONB_CONVERTED):
        raise HTTPException(status_code=409,
                            detail="Your details have been received and confirmed.")

    return {
        "candidateName": doc.get("full_name") or "",
        "message": onb.get("message") or "",
        "dueOn": onb.get("due_on"),
        "alreadySubmitted": onb.get("status") == ONB_SUBMITTED,
    }


@router.post("/public/onboarding/{code}/submit")
async def public_onboarding_submit(code: str, body: OnboardingSubmission, request: Request):
    """Accept the joiner's KYC.

    Refused once HR has verified. The reference overwrites bank details on EVERY post — even
    after verification, which silently reverts the record to Submitted. That is a direct
    salary-redirection vector (its audit's C-4); here verification closes the link for good.
    """
    rate_limit(request, "assess")
    doc = await find_candidate_by_onboarding_code(code)
    onb = (doc or {}).get("onboarding") if doc else None
    if not onb:
        raise HTTPException(status_code=404, detail="This link is not valid.")
    if onb.get("status") in (ONB_VERIFIED, ONB_CONVERTED):
        raise HTTPException(status_code=409,
                            detail="Your details have already been confirmed and can no longer be changed.")

    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    updates = {f"onboarding.{k}": v for k, v in payload.items()}
    updates["onboarding.status"] = ONB_SUBMITTED
    updates["onboarding.submitted_at"] = datetime.now(timezone.utc)
    updates["updated_at"] = datetime.now(timezone.utc)

    await get_collection(COL_CANDIDATES).update_one(
        {"_id": doc["_id"], "onboarding.access_code": code}, {"$set": updates})
    return {"message": "Thank you. Your details have been submitted."}
