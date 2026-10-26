"""HRMS > Employee Master support (Phase 1 FRD §3, §4, §18, §21-22).

The pieces the employee profile needed around it, kept out of hrms_employee_service so that
module stays about composing a person:

  * MASTER LISTS -- the company-maintained dropdowns behind Legal entity, Business unit,
    Location, Grade, Level, Cost centre, Employee category, Payroll group, ... An empty list
    means "not configured", and then free text is accepted, so a company that has not set up
    its locations can still save an employee.
  * DUPLICATE CHECK -- PAN, Aadhaar, UAN, passport, personal/official email, personal mobile
    and bank account must not already belong to another employee (FRD §4, §18).
  * EFFECTIVE-DATED HISTORY -- every change to an organisation / reporting / pay-linkage
    field is written to hrms_employee_history with its effective date. A future date
    SCHEDULES the change instead of applying it; `apply_due_changes` applies it on the day.
    Prior values are never lost (FRD §4 last bullet, §20 "preserve history").
  * CONFIGURABLE FIELDS -- HR defines extra Employee / Attendance fields (type, options,
    validation, visibility, applicability, lifecycle) without a code change (FRD §21-22).
    A field that has values is retired, never deleted, and its data type is then frozen.
  * PHOTOGRAPH -- FRD §3 Basic Identity. Its own small upload rather than a value on the
    profile update, for the same reason the candidate photo is: a picture is not
    effective-dated, so routing it through `record_changes` would put a binary blob in the
    change timeline that nobody can read and that nothing can schedule.
"""
import base64
import binascii
import io as _io
import re
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_EMPLOYEE_CHANGE_CANCELLED, AUDIT_FIELD_DEFINITION_SAVED, AUDIT_FIELD_DEFINITION_STATUS,
    AUDIT_MASTER_LISTS_SAVED, COLL_EMPLOYEE_HISTORY, COLL_EMPLOYEE_PROFILES,
    COLL_FIELD_DEFINITIONS, COLL_SETTINGS, ENTITY_EMPLOYEE, ENTITY_FIELD_DEFINITION,
    EMPLOYEE_DUPLICATE_FIELDS, EMPLOYEE_MASKED_FIELDS, FIELD_MODULES, HISTORY_APPLIED,
    HISTORY_CANCELLED, HISTORY_SCHEDULED, MASTER_LIST_FIELDS, MASTER_LIST_KEYS,
    FieldDataType, FieldStatus, is_iso_date,
)
from app.services.hrms_audit_service import audit

USER_COLLECTIONS = ("learners", "staff")
MASK_PREFIX = "XXXX"
MAX_LIST_VALUES = 300

# FRD §3 Basic Identity -- the photograph. Deliberately narrow: an employee photo is a
# head-and-shoulders picture, so the formats are the three every camera and phone produces
# and the ceiling is small enough that a directory of them stays cheap to serve.
PHOTO_MIME_TYPES = ("image/jpeg", "image/png", "image/webp")
PHOTO_MAX_BYTES = 5 * 1024 * 1024
AUDIT_PHOTOGRAPH_SAVED = "employee photograph saved"
AUDIT_PHOTOGRAPH_REMOVED = "employee photograph removed"

# Human labels for history rows, so the timeline reads "Location" rather than work_location.
FIELD_LABELS = {
    "department_id": "Department", "designation_id": "Designation",
    "sub_department": "Sub-department", "grade": "Grade", "level": "Level",
    "job_title": "Job title", "legal_entity": "Company / legal entity",
    "business_unit": "Business unit / branch", "work_location": "Location",
    "cost_centre": "Cost centre", "employee_category": "Employee category",
    "employment_type": "Employment type", "employment_status": "Employment status",
    "reporting_manager_id": "Reporting manager", "functional_manager_id": "Functional manager",
    "payroll_group": "Payroll group", "salary_template": "Salary structure template",
    "shift_code": "Shift", "attendance_policy_group": "Attendance policy group",
    "weekly_off_pattern": "Weekly off", "holiday_calendar": "Holiday calendar",
    "base_salary": "Base salary", "bank_name": "Bank name", "bank_account": "Bank account",
    "bank_ifsc": "IFSC", "bank_branch": "Bank branch", "bank_account_holder": "Account holder",
    "bank_account_type": "Account type",
}
SENSITIVE_HISTORY_FIELDS = {"base_salary", "bank_account"}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _actor_id(actor: Optional[dict]) -> str:
    return str((actor or {}).get("_id") or "")


def _actor_name(actor: Optional[dict]) -> Optional[str]:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email"))


def mask(value) -> Optional[str]:
    """XXXX + the last four characters. Enough to recognise an account, not to use it."""
    if value in (None, ""):
        return value
    text = str(value)
    return MASK_PREFIX + text[-4:] if len(text) > 4 else MASK_PREFIX


def is_masked(value) -> bool:
    return isinstance(value, str) and value.startswith(MASK_PREFIX)


def mask_view(view: dict) -> dict:
    for field in EMPLOYEE_MASKED_FIELDS:
        if view.get(field):
            view[field] = mask(view[field])
    return view


# ─────────────────────────────────────────────────────────────
# Master lists
# ─────────────────────────────────────────────────────────────
async def get_master_lists(company_id: str) -> dict:
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    stored = (doc or {}).get("employee_master_lists") or {}
    lists = {key: list(stored.get(key) or []) for key in MASTER_LIST_KEYS}
    # Shift codes come from the shift master rather than a free list.
    from app.services.hrms_shift_service import list_shifts
    lists["shifts"] = [s["code"] for s in await list_shifts(company_id) if s.get("active", True)]
    return lists


async def save_master_lists(actor: dict, company_id: str, payload: dict) -> dict:
    raw = payload.get("lists") or {}
    clean = {}
    for key, values in raw.items():
        if key not in MASTER_LIST_KEYS:
            raise HTTPException(status_code=422, detail=f"Unknown list '{key}'.")
        seen, out = set(), []
        for v in values or []:
            text = str(v or "").strip()[:120]
            if text and text.lower() not in seen:
                seen.add(text.lower())
                out.append(text)
        if len(out) > MAX_LIST_VALUES:
            raise HTTPException(status_code=422,
                                detail=f"At most {MAX_LIST_VALUES} values per list.")
        clean[key] = out
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    merged = {**((doc or {}).get("employee_master_lists") or {}), **clean}
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {"employee_master_lists": merged, "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"company_id": str(company_id)}},
        upsert=True)
    await audit(actor, AUDIT_MASTER_LISTS_SAVED, ENTITY_EMPLOYEE, "master-lists",
                ", ".join(sorted(clean)), company_id)
    return await get_master_lists(company_id)


# ─────────────────────────────────────────────────────────────
# FRD §4 "Employee ID is created according to CONFIGURED numbering"
# ─────────────────────────────────────────────────────────────
DEFAULT_EMPLOYEE_ID_FORMAT = {"prefix": "EMP", "include_year": True, "digits": 3}
_ID_PREFIX_RE = re.compile(r"^[A-Z0-9]{1,10}$")


async def get_employee_id_format(company_id: str) -> dict:
    doc = await get_collection(COLL_SETTINGS).find_one(
        {"company_id": str(company_id)}, {"employee_id_format": 1}) or {}
    return {**DEFAULT_EMPLOYEE_ID_FORMAT, **(doc.get("employee_id_format") or {})}


def render_employee_code(fmt: dict, seq: int, year: int) -> str:
    parts = [fmt["prefix"]] + ([str(year)] if fmt.get("include_year") else [])
    return "-".join(parts + [str(seq).zfill(int(fmt.get("digits") or 3))])


async def save_employee_id_format(actor: dict, company_id: str, payload: dict) -> dict:
    prefix = str(payload.get("prefix") or "").strip().upper()
    if not _ID_PREFIX_RE.match(prefix):
        raise HTTPException(status_code=422,
                            detail="The prefix is 1-10 capital letters or digits, e.g. EMP or SM.")
    try:
        digits = int(payload.get("digits") or 3)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Digits must be a whole number.")
    if not 1 <= digits <= 8:
        raise HTTPException(status_code=422, detail="Digits must be between 1 and 8.")
    fmt = {"prefix": prefix, "include_year": bool(payload.get("include_year", True)),
           "digits": digits}
    before = await get_employee_id_format(company_id)
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {"employee_id_format": fmt, "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"company_id": str(company_id)}}, upsert=True)
    await audit(actor, AUDIT_MASTER_LISTS_SAVED, ENTITY_EMPLOYEE, "employee_id_format",
                f"{render_employee_code(before, 1, 2026)} -> {render_employee_code(fmt, 1, 2026)}",
                company_id)
    return {**fmt, "example": render_employee_code(fmt, 1, datetime.now(timezone.utc).year)}


async def next_employee_code(company_id: str, year: int) -> str:
    """The next employee number in the company's format. The default format takes exactly
    the path it always took, so a company that configures nothing numbers as before; a
    configured one shares the same atomic counter and skips any code already in use (a
    hand-entered one, or one minted under the old format)."""
    from app.services.hrms_id_service import next_business_id, next_sequence
    fmt = await get_employee_id_format(company_id)
    if fmt == DEFAULT_EMPLOYEE_ID_FORMAT:
        return await next_business_id("employee", str(company_id), year)
    profiles = get_collection(COLL_EMPLOYEE_PROFILES)
    for _ in range(50):
        seq = await next_sequence("employee", str(company_id), year if fmt["include_year"] else 0)
        code = render_employee_code(fmt, seq, year)
        if not await profiles.find_one({"company_id": str(company_id), "employee_code": code},
                                       {"_id": 1}):
            return code
    raise HTTPException(status_code=409, detail="Could not find a free employee number — "
                                                "check the employee ID format.")


async def validate_master_values(company_id: str, clean: dict) -> None:
    """A value from a configured list must be on that list (case-insensitive; the stored
    spelling is the list's). Unconfigured lists accept any text."""
    lists = None
    for field, (key, label) in MASTER_LIST_FIELDS.items():
        value = clean.get(field)
        if not value:
            continue
        if lists is None:
            lists = await get_master_lists(company_id)
        allowed = lists.get(key) or []
        if not allowed:
            continue
        match = next((a for a in allowed if a.lower() == str(value).lower()), None)
        if not match:
            raise HTTPException(
                status_code=422,
                detail=f"{label} '{value}' is not in the company's list. "
                       f"Add it under Employee Master settings first.")
        clean[field] = match
    if clean.get("shift_code"):
        from app.services.hrms_shift_service import get_shift
        if not await get_shift(company_id, clean["shift_code"]):
            raise HTTPException(status_code=422,
                                detail=f"Shift '{clean['shift_code']}' does not exist.")


# ─────────────────────────────────────────────────────────────
# Duplicate / identity check
# ─────────────────────────────────────────────────────────────
def _normalise_for_duplicate(field: str, value) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if field.endswith("email"):
        return text.lower()
    if field.endswith("mobile"):
        digits = re.sub(r"\D", "", text)
        return digits[-10:] if len(digits) >= 10 else digits
    return text.upper()


async def find_duplicates(company_id: str, values: dict, *, exclude_user_id: str = None,
                          exclude_code: str = None) -> list:
    """Other employees in this company already holding one of these identifying values."""
    hits = []
    profiles = get_collection(COLL_EMPLOYEE_PROFILES)
    for field, label in EMPLOYEE_DUPLICATE_FIELDS:
        wanted = _normalise_for_duplicate(field, values.get(field))
        if not wanted:
            continue
        if field.endswith("email"):
            cond = {"$regex": f"^{re.escape(wanted)}$", "$options": "i"}
        elif field.endswith("mobile"):
            cond = {"$regex": f"{re.escape(wanted)}$"}
        else:
            cond = wanted
        query = {"company_id": str(company_id), field: cond}
        for other in await profiles.find(query, {"employee_code": 1, "user_id": 1,
                                                 "identity_snapshot": 1, "first_name": 1,
                                                 "last_name": 1}).to_list(5):
            if exclude_user_id and str(other.get("user_id") or "") == str(exclude_user_id):
                continue
            if exclude_code and other.get("employee_code") == exclude_code:
                continue
            hits.append({"field": field, "label": label,
                         "employee_code": other.get("employee_code"),
                         "name": (f"{other.get('first_name') or ''} "
                                  f"{other.get('last_name') or ''}").strip()
                         or (other.get("identity_snapshot") or {}).get("name")})
    return hits


async def assert_no_duplicates(company_id: str, values: dict, **exclude) -> None:
    hits = await find_duplicates(company_id, values, **exclude)
    if hits:
        first = hits[0]
        who = first["employee_code"] + (f" ({first['name']})" if first.get("name") else "")
        raise HTTPException(
            status_code=409,
            detail=f"{first['label']} is already recorded for {who}. "
                   f"Check this is not the same person before continuing.")


# ─────────────────────────────────────────────────────────────
# Effective-dated history
# ─────────────────────────────────────────────────────────────
def _plain(value):
    return getattr(value, "value", value)


async def record_changes(actor: dict, company_id: str, profile: dict, changes: dict, *,
                         effective_from: str, reason: Optional[str], status: str) -> list:
    """One history row per changed field. `changes` is {field: (old, new)}."""
    if not changes:
        return []
    now = datetime.now(timezone.utc)
    rows = []
    for field, (old, new) in changes.items():
        rows.append({
            "company_id": str(company_id),
            "employee_code": profile.get("employee_code"),
            "user_id": profile.get("user_id"),
            "field": field,
            "label": FIELD_LABELS.get(field, field),
            "old_value": _plain(old),
            "new_value": _plain(new),
            "effective_from": effective_from,
            "status": status,
            "reason": (reason or "").strip()[:500] or None,
            "changed_by": _actor_id(actor),
            "changed_by_name": _actor_name(actor),
            "changed_at": now,
            "applied_at": now if status == HISTORY_APPLIED else None,
        })
    await get_collection(COLL_EMPLOYEE_HISTORY).insert_many([dict(r) for r in rows])
    return rows


async def list_history(company_id: str, employee_code: str, *,
                       include_sensitive: bool) -> list:
    rows = await get_collection(COLL_EMPLOYEE_HISTORY).find(
        {"company_id": str(company_id), "employee_code": employee_code}
    ).sort("changed_at", -1).to_list(500)
    # FRD §3 System / Audit "Effective From / To": a value is in force until the day before
    # the same field's next applied or scheduled change. Derived, never stored, so it can
    # not drift from the rows it is computed from; the latest value has no Effective To.
    from datetime import date as _date, timedelta as _td
    starts: dict = {}
    for r in rows:
        if r.get("status") != HISTORY_CANCELLED and r.get("effective_from"):
            starts.setdefault(r["field"], []).append(str(r["effective_from"])[:10])
    out = []
    for r in rows:
        r = dict(r)
        r["id"] = str(r.pop("_id"))
        start = str(r.get("effective_from") or "")[:10]
        later = sorted(s for s in starts.get(r["field"], []) if s > start)
        r["effective_to"] = None
        if r.get("status") != HISTORY_CANCELLED and start and later:
            try:
                r["effective_to"] = (_date.fromisoformat(later[0]) - _td(days=1)).isoformat()
            except ValueError:
                pass
        if r["field"] in SENSITIVE_HISTORY_FIELDS and not include_sensitive:
            r["old_value"] = mask(r["old_value"]) if r["field"] == "bank_account" else "hidden"
            r["new_value"] = mask(r["new_value"]) if r["field"] == "bank_account" else "hidden"
        out.append(r)
    return out


async def _apply_field(company_id: str, profile: dict, field: str, value) -> None:
    await get_collection(COLL_EMPLOYEE_PROFILES).update_one(
        {"_id": profile["_id"]},
        {"$set": {field: value, "updated_at": datetime.now(timezone.utc)}})
    if field == "reporting_manager_id" and profile.get("user_id"):
        await set_user_reporting_manager(profile["user_id"], value)


async def set_user_reporting_manager(user_id: str, manager_id: Optional[str]) -> None:
    """The reporting line lives on the user document (the ERP reads it there too), so a
    manager change is written through -- the same write a Manager Change movement makes."""
    try:
        oid = ObjectId(str(user_id))
    except Exception:
        return
    for coll in USER_COLLECTIONS:
        result = await get_collection(coll).update_one(
            {"_id": oid}, {"$set": {"reporting_manager": manager_id or None}})
        if getattr(result, "matched_count", 0):
            return


async def apply_due_changes(company_id: str) -> int:
    """Apply every scheduled change whose effective date has arrived. Cheap when there is
    nothing due (one indexed query), so it runs on directory reads."""
    today = _today()
    due = await get_collection(COLL_EMPLOYEE_HISTORY).find(
        {"company_id": str(company_id), "status": HISTORY_SCHEDULED,
         "effective_from": {"$lte": today}}).sort("effective_from", 1).to_list(500)
    applied = 0
    for row in due:
        profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
            {"company_id": str(company_id), "employee_code": row["employee_code"]})
        if not profile:
            continue
        await _apply_field(company_id, profile, row["field"], row["new_value"])
        await get_collection(COLL_EMPLOYEE_HISTORY).update_one(
            {"_id": row["_id"]},
            {"$set": {"status": HISTORY_APPLIED, "applied_at": datetime.now(timezone.utc),
                      "old_value": _plain(profile.get(row["field"]))}})
        applied += 1
    return applied


async def cancel_scheduled(actor: dict, company_id: str, history_id: str) -> dict:
    try:
        oid = ObjectId(history_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid history id.")
    row = await get_collection(COLL_EMPLOYEE_HISTORY).find_one(
        {"_id": oid, "company_id": str(company_id)})
    if not row:
        raise HTTPException(status_code=404, detail="Change not found.")
    if row["status"] != HISTORY_SCHEDULED:
        raise HTTPException(status_code=409,
                            detail="Only a scheduled change can be cancelled; an applied one "
                                   "is history and is corrected by a new change.")
    await get_collection(COLL_EMPLOYEE_HISTORY).update_one(
        {"_id": oid}, {"$set": {"status": HISTORY_CANCELLED, "cancelled_by": _actor_id(actor),
                                "cancelled_at": datetime.now(timezone.utc)}})
    await audit(actor, AUDIT_EMPLOYEE_CHANGE_CANCELLED, ENTITY_EMPLOYEE, row["employee_code"],
                f"{row['label']} -> {row['new_value']} from {row['effective_from']}", company_id)
    return {"cancelled": True, "id": history_id}


async def scheduled_for(company_id: str, employee_code: str) -> list:
    rows = await get_collection(COLL_EMPLOYEE_HISTORY).find(
        {"company_id": str(company_id), "employee_code": employee_code,
         "status": HISTORY_SCHEDULED}).sort("effective_from", 1).to_list(100)
    return [{"id": str(r["_id"]), "field": r["field"], "label": r["label"],
             "new_value": r["new_value"], "effective_from": r["effective_from"]} for r in rows]


# ─────────────────────────────────────────────────────────────
# Configurable fields (FRD §21-22)
# ─────────────────────────────────────────────────────────────
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_CHOICE_TYPES = {FieldDataType.SINGLE_SELECT.value, FieldDataType.MULTI_SELECT.value}


def _def_out(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


async def list_field_definitions(company_id: str, module: Optional[str] = None, *,
                                 include_retired: bool = True) -> list:
    query = {"company_id": str(company_id)}
    if module:
        query["module"] = module
    if not include_retired:
        query["status"] = FieldStatus.ACTIVE.value
    rows = await get_collection(COLL_FIELD_DEFINITIONS).find(query).sort(
        "display_order", 1).to_list(500)
    return [_def_out(r) for r in rows]


async def _usage_count(company_id: str, module: str, code: str) -> int:
    from app.models.hrms import COLL_ATTENDANCE
    coll = COLL_EMPLOYEE_PROFILES if module == "employee" else COLL_ATTENDANCE
    return await get_collection(coll).count_documents(
        {"company_id": str(company_id), f"custom_fields.{code}": {"$exists": True}})


async def _field_change_governed(company_id: str) -> bool:
    from app.models.hrms import CONFIG_ENTITY_FIELD_DEFINITION
    from app.services import hrms_config_change_service as CC
    return await CC.is_governed(company_id, CONFIG_ENTITY_FIELD_DEFINITION)


async def _stage_field_change(actor: dict, company_id: str, current: dict, changed: dict,
                              payload: dict, now) -> dict:
    """Hold a governed field change on the document and raise a §27 request for it.

    The staged keys live under `pending_definition`, which nothing in `_applies`,
    `_in_force`, `_check_value` or `visible_custom_fields` reads -- that is what makes the
    live field's behaviour unchanged while the change is pending, rather than merely
    intended to be.
    """
    from app.models.hrms import CONFIG_ENTITY_FIELD_DEFINITION
    from app.services import hrms_config_change_service as CC

    reason = str(payload.get("change_reason") or "").strip()
    if not reason:
        raise HTTPException(
            status_code=422,
            detail="Say why this field is changing — your company sends field changes for "
                   "approval, and the approver needs the business reason (FRD §27).")
    module, code = current["module"], current["code"]
    await get_collection(COLL_FIELD_DEFINITIONS).update_one(
        {"_id": current["_id"]},
        {"$set": {"pending_definition": changed, "pending_reason": reason,
                  "pending_by": _actor_id(actor), "pending_at": now, "updated_at": now}})
    request = await CC.create_request(actor, company_id, {
        "entity_type": CONFIG_ENTITY_FIELD_DEFINITION,
        "entity_code": f"{module}.{code}", "reason": reason,
        "effective_from": payload.get("effective_from"),
        "title": f"{module}.{code} — {', '.join(sorted(changed))}"[:160]})
    await get_collection(COLL_FIELD_DEFINITIONS).update_one(
        {"_id": current["_id"]}, {"$set": {"pending_request_no": request["request_no"]}})
    await audit(actor, AUDIT_FIELD_DEFINITION_SAVED, ENTITY_FIELD_DEFINITION,
                f"{module}.{code}", f"staged as {request['request_no']}", company_id,
                changes=[{"field": k, "old": current.get(k), "new": v}
                         for k, v in sorted(changed.items())])
    saved = await get_collection(COLL_FIELD_DEFINITIONS).find_one({"_id": current["_id"]})
    return _def_out(saved)


async def save_field_definition(actor: dict, company_id: str, payload: dict) -> dict:
    module = str(payload.get("module") or "employee")
    if module not in FIELD_MODULES:
        raise HTTPException(status_code=422, detail="Module must be employee or attendance.")
    code = str(payload.get("code") or "").strip().lower()
    if not _CODE_RE.match(code):
        raise HTTPException(status_code=422,
                            detail="Field code: lowercase letters, digits and _, 2-40 chars, "
                                   "starting with a letter.")
    label = str(payload.get("label") or "").strip()
    if not label:
        raise HTTPException(status_code=422, detail="A field label is required.")
    data_type = _plain(payload.get("data_type") or FieldDataType.TEXT.value)
    options = [
        {"value": str(_o(o, "value")).strip(), "label": (_o(o, "label") or _o(o, "value")),
         "active": bool(_o(o, "active", True))}
        for o in (payload.get("options") or []) if str(_o(o, "value") or "").strip()]
    if data_type in _CHOICE_TYPES and not options:
        raise HTTPException(status_code=422, detail="A dropdown field needs at least one option.")
    if data_type == FieldDataType.MASTER_LOOKUP.value and \
            payload.get("master_list") not in MASTER_LIST_KEYS:
        raise HTTPException(status_code=422, detail="Choose which master list to look up.")
    if payload.get("pattern"):
        try:
            re.compile(payload["pattern"])
        except re.error:
            raise HTTPException(status_code=422, detail="The validation pattern is not valid.")
    for key in ("effective_from", "effective_to", "min_date", "max_date"):
        if payload.get(key) and not is_iso_date(payload[key]):
            raise HTTPException(status_code=422, detail=f"{key} must be YYYY-MM-DD.")
    if "depends_on" in payload:
        payload = {**payload, "depends_on": _clean_dependency(payload.get("depends_on"), code)}

    coll = get_collection(COLL_FIELD_DEFINITIONS)
    current = await coll.find_one({"company_id": str(company_id), "module": module,
                                   "code": code})
    now = datetime.now(timezone.utc)
    definition = {
        k: _plain(payload.get(k)) for k in (
            "label", "section", "help_text", "master_list", "mandatory", "read_only",
            "default_value", "unique", "searchable", "filterable", "exportable",
            "show_in_list", "sensitive", "visible_to_self", "visible_to_manager",
            "visible_to_payroll", "min_length", "max_length", "min_value", "max_value",
            "pattern", "pattern_message", "min_date", "max_date", "depends_on",
            "source_column", "display_order", "applicability", "effective_from",
            "effective_to")
        if k in payload}
    definition.update({"label": label, "data_type": data_type, "options": options})

    if current:
        if current.get("data_type") != data_type and \
                await _usage_count(company_id, module, code):
            raise HTTPException(
                status_code=409,
                detail="This field already holds values, so its data type cannot change. "
                       "Retire it and create a new field instead.")
        old = {k: current.get(k) for k in definition}
        changed = {k: v for k, v in definition.items() if old.get(k) != v}
        if not changed:
            return _def_out(current)
        # §27 — when the company governs field definitions, a change to a LIVE field is
        # STAGED rather than written over it. The field goes on validating, masking and
        # exporting exactly as it did while the change waits for its approver; applying it
        # is `_field_activate`'s and nothing else's.
        #
        # A DRAFT field is edited freely, on the same reasoning the component lifecycle
        # uses: a Draft has never been live, so there is nothing to protect and no
        # approver who would learn anything from reviewing it.
        if current.get("status") == FieldStatus.ACTIVE.value and \
                await _field_change_governed(company_id):
            return await _stage_field_change(actor, company_id, current, changed, payload,
                                             now)
        entry = {"at": now, "by": _actor_id(actor), "by_name": _actor_name(actor),
                 "reason": payload.get("change_reason"),
                 "old": {k: old.get(k) for k in changed}, "new": changed}
        await coll.update_one({"_id": current["_id"]},
                              {"$set": {**changed, "updated_at": now,
                                        "version": int(current.get("version") or 1) + 1},
                               "$push": {"history": entry}})
    else:
        doc = {"company_id": str(company_id), "module": module, "code": code,
               **definition, "status": FieldStatus.DRAFT.value, "version": 1,
               "created_by": _actor_id(actor), "created_by_name": _actor_name(actor),
               "created_at": now, "updated_at": now,
               "history": [{"at": now, "by": _actor_id(actor), "by_name": _actor_name(actor),
                            "reason": payload.get("change_reason"), "old": None,
                            "new": definition}]}
        await coll.insert_one(doc)
    await audit(actor, AUDIT_FIELD_DEFINITION_SAVED, ENTITY_FIELD_DEFINITION,
                f"{module}.{code}", label, company_id)
    saved = await coll.find_one({"company_id": str(company_id), "module": module, "code": code})
    return _def_out(saved)


DEPENDENCY_RULES = ("required", "only")


def _clean_dependency(dep, code: str) -> Optional[dict]:
    """§22 dependent validation, as saved: one controlling field, the values that trigger the
    rule, and whether the rule makes this field required or allows it only then. A blank
    controlling field clears the dependency."""
    if not dep:
        return None
    dep = dep if isinstance(dep, dict) else dict(dep)
    field = str(dep.get("field") or "").strip().lower()
    if not field:
        return None
    if field == code:
        raise HTTPException(status_code=422, detail="A field cannot depend on itself.")
    rule = str(dep.get("rule") or "required")
    if rule not in DEPENDENCY_RULES:
        raise HTTPException(status_code=422, detail="Dependent rule must be required or only.")
    raw = dep.get("equals")
    equals = [str(v).strip() for v in (raw if isinstance(raw, (list, tuple)) else [raw])
              if str(v if v is not None else "").strip()]
    if not equals:
        raise HTTPException(status_code=422,
                            detail="Say which value(s) of the other field trigger the rule.")
    return {"field": field, "equals": equals, "rule": rule}


def _dependency_holds(actual, equals: list) -> bool:
    """Does the controlling field's value match one of `equals`? Text compares without case;
    a Yes/No field matches yes/true/1 or no/false/0; a multi-select matches on any item."""
    if actual in (None, "", []):
        return False
    wanted = {str(e).strip().lower() for e in equals}
    if isinstance(actual, bool):
        return bool(wanted & ({"yes", "true", "1"} if actual else {"no", "false", "0"}))
    values = actual if isinstance(actual, (list, tuple)) else [actual]
    return any(str(int(v) if isinstance(v, float) and v.is_integer() else v).strip().lower()
               in wanted for v in values)


def _o(option, key, default=None):
    if isinstance(option, dict):
        return option.get(key, default)
    return getattr(option, key, default)


async def set_field_status(actor: dict, company_id: str, module: str, code: str,
                           payload: dict) -> dict:
    """Draft -> Active (approval recorded), Active -> Retired, Retired -> Active.
    A Draft field nobody has used can be discarded; a used field is only ever retired."""
    coll = get_collection(COLL_FIELD_DEFINITIONS)
    current = await coll.find_one({"company_id": str(company_id), "module": module,
                                   "code": code})
    if not current:
        raise HTTPException(status_code=404, detail="Field not found.")
    new_status = _plain(payload.get("status"))
    now = datetime.now(timezone.utc)
    if new_status == "Deleted":
        if current["status"] != FieldStatus.DRAFT.value or \
                await _usage_count(company_id, module, code):
            raise HTTPException(status_code=409,
                                detail="Only an unused Draft field can be deleted; retire it.")
        await coll.delete_one({"_id": current["_id"]})
        return {"deleted": True, "code": code}
    if new_status not in {s.value for s in FieldStatus}:
        raise HTTPException(status_code=422, detail="Unknown status.")
    if new_status == current["status"]:
        return _def_out(current)
    # §27 — making a field LIVE is the governed move. Retiring one is not: it stops the
    # field being collected and breaks nothing that already holds a value, and refusing it
    # would leave a field that should not be in use waiting on an approver.
    if new_status in (FieldStatus.ACTIVE.value, FieldStatus.APPROVED.value) and \
            await _field_change_governed(company_id):
        raise HTTPException(
            status_code=409,
            detail=f"{module}.{code} cannot be {new_status.lower()} directly. Raise a "
                   f"configuration change request for it and have somebody else approve it, "
                   f"then activate it from the Configuration Approvals screen (FRD §27).")
    updates = {"status": new_status, "updated_at": now}
    # §22 Approved: a sign-off by someone other than the author. Optional -- Draft -> Active
    # stays open, recording the activator as the approver, exactly as before.
    if new_status == FieldStatus.APPROVED.value:
        if current["status"] != FieldStatus.DRAFT.value:
            raise HTTPException(status_code=409, detail="Only a Draft field can be approved.")
        if current.get("created_by") and current["created_by"] == _actor_id(actor):
            raise HTTPException(status_code=403,
                                detail="You created this field, so the approval is someone "
                                       "else's to give.")
        updates.update({"approved_by": _actor_id(actor), "approved_by_name": _actor_name(actor),
                        "approved_at": now})
    if new_status == FieldStatus.ACTIVE.value and current["status"] == FieldStatus.APPROVED.value:
        # Already approved: activation keeps that approver and records who switched it on.
        updates.update({"activated_by": _actor_id(actor), "activated_at": now})
        if not current.get("effective_from"):
            updates["effective_from"] = _today()
    elif new_status == FieldStatus.ACTIVE.value:
        updates.update({"approved_by": _actor_id(actor), "approved_by_name": _actor_name(actor),
                        "approved_at": now})
        if not current.get("effective_from"):
            updates["effective_from"] = _today()
    if new_status == FieldStatus.RETIRED.value:
        # §22 Control 3: a field configuration still reads (a bank file column, a policy
        # scope) is not retired until that is resolved -- the same refusal, naming the
        # dependants, that a salary component gets.
        from app.services.hrms_config_dependency_service import ENTITY_FIELD, assert_retirable
        await assert_retirable(company_id, ENTITY_FIELD, code, module)
        updates.update({"retired_by": _actor_id(actor), "retired_at": now,
                        "effective_to": current.get("effective_to") or _today()})
    entry = {"at": now, "by": _actor_id(actor), "by_name": _actor_name(actor),
             "reason": payload.get("reason"), "old": {"status": current["status"]},
             "new": {"status": new_status}}
    await coll.update_one({"_id": current["_id"]}, {"$set": updates, "$push": {"history": entry}})
    await audit(actor, AUDIT_FIELD_DEFINITION_STATUS, ENTITY_FIELD_DEFINITION,
                f"{module}.{code}", f"{current['status']} -> {new_status}", company_id)
    return _def_out(await coll.find_one({"_id": current["_id"]}))


def _applies(definition: dict, context: dict) -> bool:
    """Applicability: every non-empty list on the definition must contain the record's value."""
    rules = definition.get("applicability") or {}
    for field, allowed in rules.items():
        if allowed and context.get(field) not in allowed:
            return False
    return True


def _in_force(definition: dict, today: str) -> bool:
    start, end = definition.get("effective_from"), definition.get("effective_to")
    return (not start or start <= today) and (not end or end >= today)


def _check_value(d: dict, value):
    """Validate and coerce one custom value against its definition. Raises 422."""
    label, dtype = d["label"], d["data_type"]
    if value in (None, "", []):
        return None
    if dtype in (FieldDataType.NUMBER.value,):
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{label} must be a whole number.")
    elif dtype in (FieldDataType.DECIMAL.value, FieldDataType.CURRENCY.value):
        try:
            value = round(float(value), 2)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    elif dtype == FieldDataType.BOOLEAN.value:
        value = value in (True, "true", "yes", "Yes", 1, "1")
    elif dtype == FieldDataType.DATE.value:
        if not is_iso_date(str(value)):
            raise HTTPException(status_code=422, detail=f"{label} must be a date (YYYY-MM-DD).")
        if d.get("min_date") and value < d["min_date"]:
            raise HTTPException(status_code=422, detail=f"{label} cannot be before {d['min_date']}.")
        if d.get("max_date") and value > d["max_date"]:
            raise HTTPException(status_code=422, detail=f"{label} cannot be after {d['max_date']}.")
    elif dtype == FieldDataType.SINGLE_SELECT.value:
        allowed = {o["value"] for o in d.get("options") or [] if o.get("active", True)}
        if value not in allowed:
            raise HTTPException(status_code=422, detail=f"{label}: choose one of the options.")
    elif dtype == FieldDataType.MULTI_SELECT.value:
        allowed = {o["value"] for o in d.get("options") or [] if o.get("active", True)}
        value = list(value) if isinstance(value, (list, tuple)) else [value]
        if any(v not in allowed for v in value):
            raise HTTPException(status_code=422, detail=f"{label}: choose from the options.")
    else:
        value = str(value).strip()

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if d.get("min_value") is not None and value < d["min_value"]:
            raise HTTPException(status_code=422, detail=f"{label} must be at least {d['min_value']}.")
        if d.get("max_value") is not None and value > d["max_value"]:
            raise HTTPException(status_code=422, detail=f"{label} must be at most {d['max_value']}.")
    if isinstance(value, str):
        if d.get("min_length") and len(value) < d["min_length"]:
            raise HTTPException(status_code=422,
                                detail=f"{label} must be at least {d['min_length']} characters.")
        if d.get("max_length") and len(value) > d["max_length"]:
            raise HTTPException(status_code=422,
                                detail=f"{label} must be at most {d['max_length']} characters.")
        if d.get("pattern") and not re.fullmatch(d["pattern"], value):
            raise HTTPException(status_code=422,
                                detail=d.get("pattern_message") or f"{label} is not in the expected format.")
    return value


async def validate_custom_values(company_id: str, module: str, values: Optional[dict], *,
                                 current: Optional[dict] = None, context: dict = None,
                                 enforce_mandatory: bool = True,
                                 record_filter: dict = None) -> dict:
    """Validate a record's custom values against the ACTIVE definitions in force today.

    Unknown codes are refused (a typo would otherwise be stored silently). Retired fields
    keep their stored values but accept no new ones. Mandatory is enforced only when the
    caller is writing the custom section, so an unrelated edit to an older record is never
    blocked by a field added after it was created (FRD §22 controls).
    """
    values = dict(values or {})
    current = dict(current or {})
    defs = {d["code"]: d for d in await list_field_definitions(company_id, module)}
    today = _today()
    out = dict(current)
    for code, value in values.items():
        d = defs.get(code)
        if not d:
            raise HTTPException(status_code=422, detail=f"Unknown field '{code}'.")
        if d["status"] != FieldStatus.ACTIVE.value:
            if value != current.get(code):
                raise HTTPException(status_code=422,
                                    detail=f"{d['label']} is {d['status'].lower()} and cannot be changed.")
            continue
        if d.get("read_only") and code in current and value != current.get(code):
            raise HTTPException(status_code=422, detail=f"{d['label']} is read-only.")
        clean = _check_value(d, value)
        if clean is None:
            out.pop(code, None)
            continue
        if d.get("unique"):
            query = {"company_id": str(company_id), f"custom_fields.{code}": clean}
            if record_filter:
                query.update(record_filter)
            from app.models.hrms import COLL_ATTENDANCE
            coll = COLL_EMPLOYEE_PROFILES if module == "employee" else COLL_ATTENDANCE
            if await get_collection(coll).find_one(query):
                raise HTTPException(status_code=409,
                                    detail=f"{d['label']} '{clean}' is already in use.")
        out[code] = clean
    if enforce_mandatory:
        for d in defs.values():
            if (d["status"] == FieldStatus.ACTIVE.value and d.get("mandatory")
                    and _in_force(d, today) and _applies(d, context or {})
                    and out.get(d["code"]) in (None, "", [])):
                if d.get("default_value") not in (None, ""):
                    out[d["code"]] = _check_value(d, d["default_value"])
                else:
                    raise HTTPException(status_code=422, detail=f"{d['label']} is required.")
        # §22 dependent validation. The controlling value is the record's custom value when
        # the field is a custom one, else the profile key of that name from `context`.
        for d in defs.values():
            dep = d.get("depends_on")
            if not dep or d["status"] != FieldStatus.ACTIVE.value or \
                    not _in_force(d, today) or not _applies(d, context or {}):
                continue
            ctrl = dep.get("field")
            actual = out.get(ctrl) if ctrl in defs else (context or {}).get(ctrl)
            holds = _dependency_holds(actual, dep.get("equals") or [])
            empty = out.get(d["code"]) in (None, "", [])
            ctrl_label = (defs.get(ctrl) or {}).get("label") or str(ctrl).replace("_", " ")
            when = f"{ctrl_label} is {' / '.join(dep.get('equals') or [])}"
            if dep.get("rule") == "only":
                if not holds and not empty and d["code"] in values:
                    raise HTTPException(status_code=422,
                                        detail=f"{d['label']} only applies when {when}.")
            elif holds and empty:
                raise HTTPException(status_code=422,
                                    detail=f"{d['label']} is required when {when}.")
    return out


def visible_custom_fields(defs: list, values: Optional[dict], *, is_hr: bool, is_self: bool,
                          is_manager: bool, is_payroll: bool) -> dict:
    """Field-level visibility (FRD §22 Visibility): HR sees everything; others see what the
    definition grants their relationship to the record. Sensitive fields: HR and self only."""
    values = values or {}
    if is_hr:
        return dict(values)
    by_code = {d["code"]: d for d in defs}
    out = {}
    for code, value in values.items():
        d = by_code.get(code)
        if not d:
            continue
        if d.get("sensitive") and not is_self:
            continue
        if ((is_self and d.get("visible_to_self", True))
                or (is_manager and d.get("visible_to_manager", True))
                or (is_payroll and d.get("visible_to_payroll"))):
            out[code] = value
    return out


async def field_usage(company_id: str, module: str, code: str) -> dict:
    """Impact check before retiring: how many records hold a value (FRD §22, §30)."""
    return {"module": module, "code": code,
            "records_with_value": await _usage_count(company_id, module, code)}


# ─────────────────────────────────────────────────────────────
# Photograph (FRD §3 Basic Identity)
# ─────────────────────────────────────────────────────────────
async def _photo_profile(company_id: str, user_id: str) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"user_id": str(user_id), "company_id": str(company_id)})
    if not profile:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return profile


def _decode_photo(payload: dict) -> tuple:
    """base64 (optionally a data: URL) -> bytes, filename, mime.

    Checked in this order on purpose: the declared type first, then the ENCODED length,
    then the decoded length. Measuring the encoded string before decoding is what stops a
    50 MB body being expanded into memory just to be rejected afterwards.
    """
    data = str(payload.get("data") or "")
    if not data:
        raise HTTPException(status_code=422, detail="Attach a photograph.")
    mime = str(payload.get("mime_type") or "").strip().lower()
    if mime not in PHOTO_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"A photograph must be one of: {', '.join(PHOTO_MIME_TYPES)}.")
    if "," in data[:120] and data[:5].lower() == "data:":
        data = data.split(",", 1)[1]
    limit_mb = PHOTO_MAX_BYTES // 1024 // 1024
    if len(data) > (PHOTO_MAX_BYTES * 4 // 3) + 1024:
        raise HTTPException(status_code=413,
                            detail=f"The photograph is too large. The limit is {limit_mb} MB.")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="The photograph could not be read.")
    if not raw:
        raise HTTPException(status_code=400, detail="The photograph is empty.")
    if len(raw) > PHOTO_MAX_BYTES:
        raise HTTPException(status_code=413,
                            detail=f"The photograph is too large. The limit is {limit_mb} MB.")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", str(payload.get("name") or "photo"))[:120]
    return raw, name or "photo", mime


async def save_photograph(actor: dict, company_id: str, user_id: str, payload: dict) -> dict:
    """Store (or replace) one employee's photograph.

    The previous file's key is NOT deleted from object storage here. A payslip or a letter
    generated earlier may still reference it, and a dangling reference in an issued document
    is worse than an orphaned object -- the same reasoning Phase LETTER-1 applies to a
    rendered letter. Removal is an explicit act (`remove_photograph`).
    """
    profile = await _photo_profile(company_id, user_id)
    raw, name, mime = _decode_photo(payload)

    from app.services.s3_service import upload_file_to_s3_with_key
    code = profile.get("employee_code") or user_id
    try:
        stored = upload_file_to_s3_with_key(_io.BytesIO(raw), f"employee_photo_{code}_{name}", mime)
    except Exception as e:
        print(f"[WARN] HRMS photograph upload failed for {code}: {e}")
        raise HTTPException(
            status_code=503,
            detail="The photograph could not be uploaded right now. Please try again.")

    now = datetime.now(timezone.utc)
    entry = {"name": name, "key": stored.get("key"), "mime_type": mime,
             "size_bytes": len(raw), "uploaded_by": _actor_id(actor),
             "uploaded_by_name": _actor_name(actor), "uploaded_at": now}
    await get_collection(COLL_EMPLOYEE_PROFILES).update_one(
        {"_id": profile["_id"]}, {"$set": {"photograph": entry, "updated_at": now}})
    await audit(actor, AUDIT_PHOTOGRAPH_SAVED, ENTITY_EMPLOYEE, code, name, company_id)
    return photograph_view(entry)


async def remove_photograph(actor: dict, company_id: str, user_id: str) -> dict:
    """Clear the photograph from the profile. The stored object is left alone, for the
    reason save_photograph gives."""
    profile = await _photo_profile(company_id, user_id)
    code = profile.get("employee_code") or user_id
    await get_collection(COLL_EMPLOYEE_PROFILES).update_one(
        {"_id": profile["_id"]},
        {"$unset": {"photograph": ""},
         "$set": {"updated_at": datetime.now(timezone.utc)}})
    await audit(actor, AUDIT_PHOTOGRAPH_REMOVED, ENTITY_EMPLOYEE, code, None, company_id)
    return {"photograph": None}


async def photograph_url(company_id: str, user_id: str) -> dict:
    """A short-lived link to the photograph, the same shape every other HRMS attachment
    read returns."""
    profile = await _photo_profile(company_id, user_id)
    photo = profile.get("photograph") or {}
    if not photo.get("key"):
        raise HTTPException(status_code=404,
                            detail="No photograph is on file for this employee.")
    from app.services.s3_service import get_signed_url
    url = get_signed_url(photo["key"], expires_in=300)
    if not url:
        raise HTTPException(
            status_code=503,
            detail="The photograph could not be opened right now. Please try again.")
    return {"url": url, "expires_in": 300, "name": photo.get("name") or "photo"}


def photograph_view(photo: Optional[dict]) -> Optional[dict]:
    """What a profile read exposes about the photograph: that one exists and what it is,
    never the storage key. The key is an address in the bucket, and handing it out would
    let anybody who has ever seen one profile construct links to others."""
    if not photo or not photo.get("key"):
        return None
    return {k: photo.get(k) for k in ("name", "mime_type", "size_bytes", "uploaded_at",
                                      "uploaded_by_name")}
