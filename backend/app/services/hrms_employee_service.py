"""HRMS ▸ employee master.

Closes the single biggest gap in both analysis documents: "Employee Management -- Not found
in current HRMS" (FRONTEND_ANALYSIS §2, BACKEND_ANALYSIS §2). Every later phase depends on
this -- onboarding creates employees here, leave and payroll compute over them, reporting
aggregates them.

── The central design decision ───────────────────────────────────────────────────
An employee is a **composition**, not a copy:

    EmployeeView  =  user document (staff/learners)      -- identity, owned by the ERP
                  +  hrms_employee_profiles document      -- HR data, owned by HRMS
                  +  resolved master names                -- department / designation
                  +  resolved reporting manager

HRMS never writes to `staff` or `learners`. Identity has exactly one owner, so a rename or
an email change is instantly correct everywhere with no sync step.

The source did the opposite: it kept its own `users` table and joined every HR-ops record on
`users.name`, so renaming a person silently orphaned their leave history, balance ledger and
permission grants (BACKEND_ANALYSIS §4.4, Risk #4). Keying on the immutable ObjectId removes
that failure mode entirely rather than mitigating it.

── Row scoping ───────────────────────────────────────────────────────────────────
Reads are broad but scoped, writes are narrow:
  ADMIN / INTERNAL  every company (a specific one when asked)
  MD / HR           their own company
  MANAGER (HOD)     their own department + their direct reports
  EMPLOYEE          themselves only (via the self route; not a capability, so it cannot
                    be revoked by a permission edit)
"""
import re
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AADHAAR_RE, ADDRESS_KEYS, AUDIT_EMPLOYEE_CHANGE_SCHEDULED, AUDIT_EMPLOYEE_CREATED,
    AUDIT_EMPLOYEE_UPDATED, AUDIT_SALARY_CHANGED,
    AUDIT_EMPLOYEE_LINKED, BANK_ACCOUNT_TYPES, COLL_DEPARTMENTS, COLL_DESIGNATIONS,
    COLL_EMPLOYEE_PROFILES, EMAIL_FIELDS, EMPLOYEE_DATE_FIELDS, EMPLOYEE_DUPLICATE_FIELDS,
    EMPLOYEE_TEXT_FIELDS, EMPLOYEE_TRACKED_FIELDS, ENTITY_EMPLOYEE, HISTORY_APPLIED,
    HISTORY_SCHEDULED, MARITAL_STATUSES, MASTER_LIST_FIELDS, MOBILE_FIELDS,
    IFSC_RE, PAN_RE, UAN_RE, Cap, EmploymentStatus, EmploymentType, HrmsRole, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can, hrms_role, is_internal_user

USER_COLLECTIONS = ("learners", "staff")

# Identity fields surfaced on an EmployeeView. Everything else on the user doc (password,
# permissions, session_type, ...) is deliberately NOT exposed by the HRMS directory.
_USER_PROJECTION = {
    "first_name": 1, "last_name": 1, "full_name": 1, "email": 1, "mobile": 1,
    "role": 1, "governance_role": 1, "company_id": 1, "is_active": 1,
    "reporting_manager": 1, "designation": 1, "department": 1, "joining_date": 1,
    "emergency_mobile": 1,
}


def _oid(value: str, label: str = "user") -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id.")


def _display_name(user: dict) -> str:
    return (user.get("full_name")
            or f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
            or user.get("email")
            or "Unknown")


# ─────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────
async def _validate_profile(payload: dict, company_id: str, *, partial: bool) -> dict:
    """Validate and normalise a profile payload. Raises 422 with a field-specific message.

    Every rule the source enforced only in the browser is enforced here (BACKEND_ANALYSIS
    §8 lists PAN-or-Aadhaar and duplicate detection as client-only). Identity documents are
    uppercased before validation so a lowercase PAN is accepted rather than rejected on a
    technicality.
    """
    out = {}
    # A masked value coming back from a read-only view (XXXX1234) means "unchanged".
    from app.services.hrms_employee_master_service import is_masked
    payload = {k: v for k, v in payload.items() if not is_masked(v)}

    # -- Salary --
    if "base_salary" in payload and payload["base_salary"] is not None:
        try:
            salary = float(payload["base_salary"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Base salary must be a number.")
        if salary < 0:
            raise HTTPException(status_code=422, detail="Base salary cannot be negative.")
        if salary > 100_000_000:
            raise HTTPException(status_code=422, detail="Base salary is implausibly large.")
        out["base_salary"] = salary

    # -- Dates --
    for field, label in (("date_of_birth", "Date of birth"),
                         ("joined_on", "Joining date"),
                         ("resigned_on", "Resignation date")):
        if field in payload and payload[field]:
            if not is_iso_date(payload[field]):
                raise HTTPException(
                    status_code=422,
                    detail=f"{label} must be a valid date in YYYY-MM-DD format.")
            out[field] = payload[field]
        elif field in payload:
            out[field] = None

    # -- Identity documents (uppercased, then format-checked) --
    for field, pattern, label, hint in (
        ("pan", PAN_RE, "PAN", "e.g. ABCDE1234F"),
        ("aadhaar", AADHAAR_RE, "Aadhaar", "12 digits"),
        ("uan", UAN_RE, "UAN", "12 digits"),
        ("bank_ifsc", IFSC_RE, "IFSC code", "e.g. HDFC0001234"),
    ):
        if field in payload:
            raw = (payload[field] or "").strip().upper()
            if not raw:
                out[field] = None
                continue
            if not pattern.match(raw):
                raise HTTPException(status_code=422, detail=f"{label} is not valid ({hint}).")
            out[field] = raw

    if "bank_account" in payload:
        acct = (payload["bank_account"] or "").strip()
        if acct and not acct.isdigit():
            raise HTTPException(status_code=422, detail="Bank account number must be digits only.")
        if acct and not (6 <= len(acct) <= 20):
            raise HTTPException(status_code=422, detail="Bank account number must be 6-20 digits.")
        out["bank_account"] = acct or None

    # -- Enums (Pydantic already coerced these; str() normalises Enum -> value) --
    for field in ("employment_status", "employment_type", "gender"):
        if field in payload and payload[field] is not None:
            out[field] = getattr(payload[field], "value", payload[field])

    # -- Free text --
    for field in ("pf_number", "esi_number", "bank_name", "blood_group", "address",
                  "emergency_contact_name", "emergency_contact_phone",
                  "emergency_contact_relation", "employee_code"):
        if field in payload:
            out[field] = (payload[field] or "").strip() or None

    # -- Phase 1 FRD §3: the rest of the Employee Master --
    _validate_master_fields(payload, out)

    # -- Master references must exist AND belong to this company --
    for field, coll_name, label in (("department_id", COLL_DEPARTMENTS, "Department"),
                                    ("designation_id", COLL_DESIGNATIONS, "Designation")):
        if field in payload:
            raw = payload[field]
            if not raw:
                out[field] = None
                continue
            found = await get_collection(coll_name).find_one(
                {"_id": _oid(raw, label.lower()), "company_id": str(company_id)}
            )
            if not found:
                raise HTTPException(
                    status_code=422,
                    detail=f"{label} does not exist for this company.")
            out[field] = str(raw)

    # -- Reporting / functional manager: a person in this company, never yourself --
    from app.utils.hrms_access import tenant_member
    for field, label in (("reporting_manager_id", "Reporting manager"),
                         ("functional_manager_id", "Functional manager")):
        if field in payload:
            raw = str(payload[field] or "").strip()
            if not raw:
                out[field] = None
                continue
            _oid(raw, label.lower())
            if not await tenant_member(company_id, raw, {"_id": 1}):
                raise HTTPException(status_code=422,
                                    detail=f"{label} must be a person in this company.")
            out[field] = raw

    if "custom_fields" in payload and payload["custom_fields"] is not None:
        if not isinstance(payload["custom_fields"], dict):
            raise HTTPException(status_code=422, detail="custom_fields must be an object.")
        out["custom_fields"] = payload["custom_fields"]

    return out


_EMAIL_RE = __import__("re").compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MOBILE_RE = __import__("re").compile(r"^\+?\d{10,15}$")
_PIN_RE = __import__("re").compile(r"^\d{6}$")


def _clean_address(value, label: str) -> Optional[dict]:
    if not value:
        return None
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail=f"{label} must be an object.")
    out = {k: (str(value.get(k) or "").strip()[:200] or None) for k in ADDRESS_KEYS}
    if not any(out.values()):
        return None
    country = (out.get("country") or "India").lower()
    if out.get("pin_code") and country == "india" and not _PIN_RE.match(out["pin_code"]):
        raise HTTPException(status_code=422, detail=f"{label}: PIN code must be 6 digits.")
    return out


def _validate_master_fields(payload: dict, out: dict) -> None:
    """Formats for the FRD §3 fields. Pure -- list membership and duplicates are checked
    by the caller against the database."""
    from app.services.hrms_shift_service import _validate_pattern

    for field in EMPLOYEE_TEXT_FIELDS + tuple(MASTER_LIST_FIELDS):
        if field in payload:
            out[field] = (str(payload[field] or "")).strip()[:200] or None
    for field in ("passport", "driving_license"):
        if out.get(field):
            out[field] = out[field].upper().replace(" ", "")
    if "shift_code" in payload:
        out["shift_code"] = (str(payload["shift_code"] or "")).strip().upper() or None

    for field, label in EMAIL_FIELDS:
        if field in payload:
            value = (payload[field] or "").strip().lower()
            if value and not _EMAIL_RE.match(value):
                raise HTTPException(status_code=422, detail=f"{label} is not a valid email.")
            out[field] = value or None
    for field, label in MOBILE_FIELDS:
        if field in payload:
            value = "".join(ch for ch in str(payload[field] or "") if ch.isdigit() or ch == "+")
            if value and not _MOBILE_RE.match(value):
                raise HTTPException(status_code=422,
                                    detail=f"{label} must be 10-15 digits.")
            out[field] = value or None

    for field, choices, label in (("marital_status", MARITAL_STATUSES, "Marital status"),
                                  ("bank_account_type", BANK_ACCOUNT_TYPES, "Account type")):
        if field in payload:
            value = (payload[field] or "").strip()
            if value and value not in choices:
                raise HTTPException(status_code=422,
                                    detail=f"{label} must be one of: {', '.join(choices)}.")
            out[field] = value or None

    for field, label in EMPLOYEE_DATE_FIELDS:
        if field in payload:
            value = payload[field]
            if value and not is_iso_date(value):
                raise HTTPException(status_code=422,
                                    detail=f"{label} must be a valid date in YYYY-MM-DD format.")
            out[field] = value or None

    for field, label in (("current_address", "Current address"),
                         ("permanent_address", "Permanent address")):
        if field in payload:
            out[field] = _clean_address(payload[field], label)
    if "permanent_same_as_current" in payload:
        out["permanent_same_as_current"] = bool(payload["permanent_same_as_current"])
    for field in ("attendance_active", "payroll_active"):
        if payload.get(field) is not None:
            out[field] = bool(payload[field])
    if out.get("permanent_same_as_current") and out.get("current_address"):
        out["permanent_address"] = dict(out["current_address"])

    if "weekly_off_pattern" in payload:
        out["weekly_off_pattern"] = _validate_pattern(payload["weekly_off_pattern"]) or None

    start, end = out.get("probation_start"), out.get("probation_end")
    if start and end and start > end:
        raise HTTPException(status_code=422,
                            detail="Probation end cannot be before probation start.")
    confirm = out.get("confirmation_date")
    if confirm and start and confirm < start:
        raise HTTPException(status_code=422,
                            detail="Confirmation date cannot be before probation start.")


def _check_date_order(joined_on, resigned_on) -> None:
    """Joining must not be after resignation.

    ISO date strings compare correctly lexically, which is why HRMS keeps dates as strings
    end to end -- no Date object, so no server-timezone drift.
    """
    if joined_on and resigned_on and joined_on > resigned_on:
        raise HTTPException(
            status_code=422,
            detail="Joining date cannot be after the resignation date.")


# ─────────────────────────────────────────────────────────────
# Composition
# ─────────────────────────────────────────────────────────────
async def _find_user(user_id: str) -> tuple:
    """Locate a user in either identity collection. Returns (doc, collection) or (None, None)."""
    oid = _oid(user_id)
    for coll in USER_COLLECTIONS:
        doc = await get_collection(coll).find_one({"_id": oid}, _USER_PROJECTION)
        if doc:
            return doc, coll
    return None, None


def _compose(user: Optional[dict], profile: Optional[dict], *, departments: dict,
             designations: dict, managers: dict, include_salary: bool) -> dict:
    """Merge a user document and its HR profile into one EmployeeView.

    `include_salary` is passed in rather than read from a global so the caller decides once,
    from the capability check, and the redaction cannot be forgotten at a call site.

    `user` may be None. Phase 9 creates an employee record at onboarding, BEFORE the person
    has a login — those rows carry an `identity_snapshot` taken from the candidate and are
    flagged `pending_user_link`. Identity is still single-sourced: once a real account is
    linked, the user document wins and the snapshot is ignored.
    """
    profile = profile or {}
    snapshot = profile.get("identity_snapshot") or {}
    view = {
        "user_id": str(user["_id"]) if user else None,
        "name": _display_name(user) if user else (snapshot.get("name") or "Unknown"),
        "email": user.get("email") if user else snapshot.get("email"),
        "mobile": user.get("mobile") if user else snapshot.get("mobile"),
        "role": user.get("role") if user else None,
        "governance_role": user.get("governance_role") if user else None,
        "company_id": str((user or profile).get("company_id") or ""),
        "is_active": user.get("is_active", True) if user else True,
        "has_profile": bool(profile),
        # True while the employee exists but has no login yet. The directory shows this
        # rather than pretending the record is complete.
        "pending_user_link": bool(profile) and not user,
        "source_uk": profile.get("source_uk"),

        "employee_code": profile.get("employee_code"),
        "employment_status": profile.get("employment_status"),
        "employment_type": profile.get("employment_type"),
        "gender": profile.get("gender"),
        "date_of_birth": profile.get("date_of_birth"),
        # Fall back to the legacy `users.joining_date` so an employee without an HR profile
        # still shows the date the ERP already knows.
        "joined_on": profile.get("joined_on") or (user or {}).get("joining_date"),
        "resigned_on": profile.get("resigned_on"),

        "department_id": profile.get("department_id"),
        "designation_id": profile.get("designation_id"),
        "department": departments.get(profile.get("department_id")),
        "designation": designations.get(profile.get("designation_id")),
        # The raw directory strings, kept visible so nothing is lost while HR migrates onto
        # the masters and so a mismatch is obvious rather than silent.
        "legacy_department": (user or {}).get("department"),
        "legacy_designation": (user or {}).get("designation"),

        # The user document owns the reporting line; a profile without a login (created at
        # onboarding) carries its own until it is linked.
        "reporting_manager_id": ((user or {}).get("reporting_manager")
                                 if user else profile.get("reporting_manager_id")),
        "reporting_manager": managers.get(str(((user or {}).get("reporting_manager")
                                               if user else profile.get("reporting_manager_id"))
                                              or "")),
        "functional_manager_id": profile.get("functional_manager_id"),
        "functional_manager": managers.get(str(profile.get("functional_manager_id") or "")),

        "pan": profile.get("pan"),
        "aadhaar": profile.get("aadhaar"),
        "uan": profile.get("uan"),
        "pf_number": profile.get("pf_number"),
        "esi_number": profile.get("esi_number"),
        "bank_name": profile.get("bank_name"),
        "bank_account": profile.get("bank_account"),
        "bank_ifsc": profile.get("bank_ifsc"),
        "blood_group": profile.get("blood_group"),
        "address": profile.get("address"),
        "emergency_contact_name": profile.get("emergency_contact_name"),
        "emergency_contact_phone": (profile.get("emergency_contact_phone")
                                    or (user or {}).get("emergency_mobile")),
        "emergency_contact_relation": profile.get("emergency_contact_relation"),
        "custom_fields": profile.get("custom_fields") or {},
        "created_at": profile.get("created_at"),
        "created_by": profile.get("created_by"),
        "updated_at": profile.get("updated_at"),
        "updated_by": profile.get("updated_by"),
    }
    # Phase 1 FRD §3 fields, read straight off the profile. Name parts fall back to the
    # user document so a profile created before these existed still shows them.
    for field in (EMPLOYEE_TEXT_FIELDS + tuple(MASTER_LIST_FIELDS)
                  + tuple(f for f, _ in EMPLOYEE_DATE_FIELDS)
                  + tuple(f for f, _ in EMAIL_FIELDS) + tuple(f for f, _ in MOBILE_FIELDS)
                  + ("marital_status", "bank_account_type", "current_address",
                     "permanent_address", "permanent_same_as_current", "shift_code",
                     "weekly_off_pattern", "unit", "attendance_active", "payroll_active")):
        view.setdefault(field, profile.get(field))
    for field in ("first_name", "last_name"):
        if not view.get(field):
            view[field] = (user or {}).get(field)
    if not view.get("official_email") and user:
        view["official_email"] = user.get("email")
    if not view.get("business_unit") and profile.get("unit"):
        view["business_unit"] = profile.get("unit")
    if view.get("display_name"):
        view["name"] = view["display_name"]
    # Active/Inactive (FRD §3 System): the login is active AND the person is still payable.
    from app.models.hrms import PAYABLE_STATUSES
    view["active"] = bool(view["is_active"]) and (
        view.get("employment_status") in {s.value for s in PAYABLE_STATUSES}
        or not view.get("employment_status"))
    # Salary is OMITTED entirely rather than nulled, so a client cannot confuse "you may not
    # see this" with "this employee has no salary set".
    if include_salary:
        view["base_salary"] = profile.get("base_salary")
    else:
        # Bank / identity numbers are sensitive too (FRD §18): shown masked, never in full.
        from app.services.hrms_employee_master_service import mask_view
        mask_view(view)
    return view


async def _identity_source(company_id: str) -> tuple:
    """Which identity collection holds this tenant's people. See hrms_access for the rule.

    The directory does not simply stamp `company_id` onto the staff records instead: that
    field being null is what the rest of the ERP relies on to tell an operator apart from a
    company's own user (see `list_users` in routes/user.py, and org_tools' company filter).
    Resolving it per tenant keeps that boundary where it is.
    """
    from app.utils.hrms_access import tenant_identity_source
    return await tenant_identity_source(company_id)


async def _resolve_lookups(company_id: str, users: list, profiles: list = None) -> tuple:
    """Batch-resolve department names, designation names and manager names.

    One query per lookup regardless of result size -- the alternative (resolving per row)
    is the classic N+1 that would make a 500-employee directory unusable.
    """
    departments = {
        str(d["_id"]): d.get("name")
        for d in await get_collection(COLL_DEPARTMENTS).find(
            {"company_id": str(company_id)}, {"name": 1}).to_list(1000)
    }
    designations = {
        str(d["_id"]): d.get("name")
        for d in await get_collection(COLL_DESIGNATIONS).find(
            {"company_id": str(company_id)}, {"name": 1}).to_list(1000)
    }

    manager_ids = {str(u.get("reporting_manager")) for u in users if u.get("reporting_manager")}
    for p in profiles or []:
        for key in ("functional_manager_id", "reporting_manager_id"):
            if p and p.get(key):
                manager_ids.add(str(p[key]))
    managers = {}
    if manager_ids:
        oids = []
        for m in manager_ids:
            try:
                oids.append(ObjectId(m))
            except (InvalidId, TypeError):
                continue
        if oids:
            for coll in USER_COLLECTIONS:
                for doc in await get_collection(coll).find(
                        {"_id": {"$in": oids}},
                        {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1}).to_list(1000):
                    managers[str(doc["_id"])] = _display_name(doc)
    return departments, designations, managers


# ─────────────────────────────────────────────────────────────
# Row scoping
# ─────────────────────────────────────────────────────────────
async def _manager_scope(actor: dict, company_id: str) -> dict:
    """Extra user-query clause restricting a MANAGER to their own corner of the directory.

    A hiring manager sees their direct reports plus anyone in their department. If they have
    no HR profile (so no department), it degrades to direct reports only -- never to
    "everyone", because a scoping gap must fail closed.
    """
    actor_id = str(actor.get("_id") or "")
    clauses = [{"reporting_manager": actor_id}, {"_id": _oid(actor_id)}]

    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one({"user_id": actor_id})
    dept_id = (profile or {}).get("department_id")
    if dept_id:
        peers = await get_collection(COLL_EMPLOYEE_PROFILES).find(
            {"company_id": str(company_id), "department_id": dept_id}, {"user_id": 1}
        ).to_list(2000)
        peer_oids = []
        for p in peers:
            try:
                peer_oids.append(ObjectId(p["user_id"]))
            except (InvalidId, TypeError, KeyError):
                continue
        if peer_oids:
            clauses.append({"_id": {"$in": peer_oids}})
    return {"$or": clauses}


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────
async def list_employees(actor: dict, company_id: str, *, search: str = None,
                         department_id: str = None, designation_id: str = None,
                         status: str = None, include_inactive: bool = False,
                         limit: int = 200, skip: int = 0,
                         custom_filters: Optional[dict] = None) -> dict:
    """The employee directory, scoped to what `actor` may see.

    FRD §22 Behaviour / Display: a configurable field flagged Searchable is matched by the
    search box, one flagged Filterable can be filtered on (`custom_filters`), and one
    flagged Show-in-list comes back as a directory column. Sensitive fields never do.
    """
    if not company_id:
        raise HTTPException(
            status_code=400,
            detail="A company must be selected to list employees.")

    # Effective-dated changes whose day has come are applied before anyone reads them.
    from app.services.hrms_employee_master_service import apply_due_changes
    await apply_due_changes(company_id)

    source, query = await _identity_source(company_id)
    if not include_inactive:
        query["is_active"] = {"$ne": False}

    from app.models.hrms import COLL_FIELD_DEFINITIONS
    live_defs = await get_collection(COLL_FIELD_DEFINITIONS).find(
        {"company_id": str(company_id), "module": "employee", "status": "Active"},
        {"_id": 0, "code": 1, "label": 1, "searchable": 1, "filterable": 1, "show_in_list": 1,
         "sensitive": 1, "options": 1, "display_order": 1}).to_list(500)
    live_defs.sort(key=lambda d: (d.get("display_order") or 100, d.get("code") or ""))

    if search:
        safe = _escape_regex(search.strip())
        alternatives = [
            {"full_name": {"$regex": safe, "$options": "i"}},
            {"first_name": {"$regex": safe, "$options": "i"}},
            {"last_name": {"$regex": safe, "$options": "i"}},
            {"email": {"$regex": safe, "$options": "i"}},
            {"mobile": {"$regex": safe, "$options": "i"}},
        ]
        searchable = [d["code"] for d in live_defs if d.get("searchable") and not d.get("sensitive")]
        if searchable:
            hits = await get_collection(COLL_EMPLOYEE_PROFILES).find(
                {"company_id": str(company_id), "$or": [
                    {f"custom_fields.{c}": {"$regex": safe, "$options": "i"}} for c in searchable]},
                {"user_id": 1}).to_list(5000)
            hit_ids = []
            for h in hits:
                try:
                    hit_ids.append(ObjectId(h["user_id"]))
                except (InvalidId, TypeError, KeyError):
                    continue
            if hit_ids:
                alternatives.append({"_id": {"$in": hit_ids}})
        query["$and"] = [{"$or": alternatives}]

    if hrms_role(actor) == HrmsRole.MANAGER:
        scope = await _manager_scope(actor, company_id)
        query.setdefault("$and", []).append(scope)

    # Profile-driven filters resolve to a user-id set first, because the filterable fields
    # live on the profile while the base query runs over the user collection.
    profile_filter = {"company_id": str(company_id)}
    if department_id:
        profile_filter["department_id"] = department_id
    if designation_id:
        profile_filter["designation_id"] = designation_id
    if status:
        profile_filter["employment_status"] = status
    filterable = {d["code"] for d in live_defs if d.get("filterable")}
    for code, value in (custom_filters or {}).items():
        if code not in filterable:
            raise HTTPException(status_code=422,
                                detail=f"'{code}' is not a filterable field.")
        if str(value).strip():
            profile_filter[f"custom_fields.{code}"] = str(value).strip()
    if len(profile_filter) > 1:
        matched = await get_collection(COLL_EMPLOYEE_PROFILES).find(
            profile_filter, {"user_id": 1}).to_list(5000)
        oids = []
        for m in matched:
            try:
                oids.append(ObjectId(m["user_id"]))
            except (InvalidId, TypeError, KeyError):
                continue
        if not oids:
            return {"employees": [], "total": 0, "limit": limit, "skip": skip}
        query["_id"] = {"$in": oids}

    users_coll = get_collection(source)
    total = await users_coll.count_documents(query)
    # The full matching id set (unpaginated), so the orphan check below isn't fooled by a
    # profile whose linked user simply falls on a different page.
    matched_user_ids = {
        str(d["_id"]) for d in await users_coll.find(query, {"_id": 1}).to_list(20000)
    }
    limit = max(1, min(int(limit or 200), 500))
    users = await users_coll.find(query, _USER_PROJECTION).sort(
        "full_name", 1).skip(max(0, int(skip or 0))).limit(limit).to_list(limit)

    profiles = {}
    if users:
        ids = [str(u["_id"]) for u in users]
        for p in await get_collection(COLL_EMPLOYEE_PROFILES).find(
                {"user_id": {"$in": ids}}).to_list(len(ids)):
            profiles[p["user_id"]] = p

    # Employees created by onboarding have no login yet, so they are absent from the user
    # query above. Fetch them separately rather than leaving a new hire invisible in the
    # directory the moment their Employee ID is issued.
    unlinked = await _profile_rows_visible(actor, company_id, await _unlinked_profiles(
        company_id, search=search, department_id=department_id,
        designation_id=designation_id, status=status))

    departments, designations, managers = await _resolve_lookups(
        company_id, users, list(profiles.values()) + list(unlinked))
    include_salary = can(actor, Cap.EMPLOYEE_SALARY_READ)

    rows = [
        _compose(u, profiles.get(str(u["_id"])), departments=departments,
                 designations=designations, managers=managers,
                 include_salary=include_salary)
        for u in users
    ]
    for profile in unlinked:
        rows.append(_compose(None, profile, departments=departments,
                             designations=designations, managers=managers,
                             include_salary=include_salary))

    # A profile can carry a `user_id` that no longer resolves to a learner of THIS company
    # -- the account was moved to another company, or the profile was linked against the
    # wrong one to begin with. `_unlinked_profiles` correctly skips it (its `user_id` field
    # IS set), and the query above never finds it either, so without this it vanishes from
    # the directory entirely instead of surfacing the inconsistency HR needs to fix.
    # Deliberately the COMPANY's id set, not `matched_user_ids` from the scoped query:
    # see _company_user_ids for why the difference is a scoping leak rather than a nicety.
    orphaned = await _orphaned_linked_profiles(
        company_id, await _company_user_ids(company_id), search=search,
        department_id=department_id, designation_id=designation_id, status=status)
    orphaned = await _profile_rows_visible(actor, company_id, orphaned)
    for profile in orphaned:
        row = _compose(None, profile, departments=departments, designations=designations,
                       managers=managers, include_salary=include_salary)
        row["pending_user_link"] = False
        row["link_broken"] = True
        rows.append(row)

    rows.sort(key=lambda r: (r.get("name") or "").lower())

    # §22 Display "grid / list visibility": the Show-in-list fields as directory columns.
    columns = [{"code": d["code"], "label": d["label"]} for d in live_defs
               if d.get("show_in_list") and not d.get("sensitive")]
    if columns:
        by_user = {**{str(k): v for k, v in profiles.items()}}
        extra = {p.get("employee_code"): p for p in list(unlinked) + list(orphaned)}
        for row in rows:
            source_profile = by_user.get(str(row.get("user_id") or row.get("id") or "")) \
                or extra.get(row.get("employee_code")) or {}
            values = source_profile.get("custom_fields") or {}
            row["list_fields"] = {c["code"]: values.get(c["code"]) for c in columns}

    return {
        "employees": rows,
        "list_columns": columns,
        "filterable_fields": [
            {"code": d["code"], "label": d["label"],
             "options": [o["value"] for o in d.get("options") or [] if o.get("active", True)]}
            for d in live_defs if d.get("filterable")],
        "total": total + len(unlinked) + len(orphaned),
        "limit": limit,
        "skip": skip,
        "salary_visible": include_salary,
        "pending_links": sum(1 for r in rows if r.get("pending_user_link")),
        "broken_links": sum(1 for r in rows if r.get("link_broken")),
    }


async def _unlinked_profiles(company_id: str, *, search: str = None,
                             department_id: str = None, designation_id: str = None,
                             status: str = None) -> list:
    """Employee profiles that exist without a login account.

    Matched on the ABSENCE of `user_id` (not a null value) so they line up exactly with the
    sparse unique index -- see the index comment in models/hrms.py.
    """
    query = {"company_id": str(company_id), "user_id": {"$exists": False}}
    if department_id:
        query["department_id"] = department_id
    if designation_id:
        query["designation_id"] = designation_id
    if status:
        query["employment_status"] = status

    rows = await get_collection(COLL_EMPLOYEE_PROFILES).find(query).to_list(500)
    if search:
        needle = search.strip().lower()
        rows = [
            r for r in rows
            if needle in ((r.get("identity_snapshot") or {}).get("name") or "").lower()
            or needle in ((r.get("identity_snapshot") or {}).get("email") or "").lower()
            or needle in (r.get("employee_code") or "").lower()
        ]
    return rows


async def _company_user_ids(company_id: str) -> set:
    """Every user id this company's identity collection resolves, ignoring role scope.

    The orphan test below asks "does this profile's user still belong to this company",
    which is a question about the COMPANY. Answering it from the role-scoped result set --
    as it used to -- means a manager's own narrow result makes every colleague look
    orphaned, and the directory then appends them all as broken links. That is a row-scoping
    leak dressed as a data-quality warning, and an export built on the same list would have
    carried the whole company in one file.
    """
    source, query = await _identity_source(company_id)
    rows = await get_collection(source).find(query, {"_id": 1}).to_list(20000)
    return {str(r["_id"]) for r in rows}


async def _profile_rows_visible(actor: dict, company_id: str, rows: list) -> list:
    """Narrow profile-derived rows (no login, or a broken link) to what `actor` may see.

    These rows bypass the user query, so they bypass the role scope applied to it. HR and
    above see them all -- an unlinked or orphaned profile is a data problem they are the
    ones to fix. A MANAGER sees only their own reports and their own department, and an
    EMPLOYEE sees none: fail closed, exactly as `_manager_scope` does.
    """
    role = hrms_role(actor)
    if role == HrmsRole.EMPLOYEE:
        return []
    if role != HrmsRole.MANAGER:
        return rows
    actor_id = str(actor.get("_id") or "")
    own = await get_collection(COLL_EMPLOYEE_PROFILES).find_one({"user_id": actor_id})
    dept = (own or {}).get("department_id")
    return [r for r in rows
            if r.get("reporting_manager_id") == actor_id
            or (dept and r.get("department_id") == dept)]


async def _orphaned_linked_profiles(company_id: str, matched_user_ids: set, *,
                                    search: str = None, department_id: str = None,
                                    designation_id: str = None, status: str = None) -> list:
    """Employee profiles whose `user_id` no longer resolves to a learner of THIS company.

    `_unlinked_profiles` deliberately matches on the ABSENCE of `user_id`; a profile that
    HAS one but whose target has since moved to another company (or was linked against the
    wrong one) falls through both that query and the main user-driven one, and used to
    disappear from the directory rather than surface as the data problem it is.

    Filtered exactly like `_unlinked_profiles`, so a search or filter narrows this set too
    rather than always injecting every orphan regardless of what the caller asked for.
    """
    query = {"company_id": str(company_id), "user_id": {"$exists": True, "$nin": [None, ""]}}
    if department_id:
        query["department_id"] = department_id
    if designation_id:
        query["designation_id"] = designation_id
    if status:
        query["employment_status"] = status

    rows = await get_collection(COLL_EMPLOYEE_PROFILES).find(query).to_list(2000)
    rows = [r for r in rows if r.get("user_id") not in matched_user_ids]
    if search:
        needle = search.strip().lower()
        rows = [
            r for r in rows
            if needle in ((r.get("identity_snapshot") or {}).get("name") or "").lower()
            or needle in ((r.get("identity_snapshot") or {}).get("email") or "").lower()
            or needle in (r.get("employee_code") or "").lower()
        ]
    return rows


async def get_employee(actor: dict, user_id: str, *, company_id: str = None,
                       force_salary: bool = None) -> dict:
    """One employee, composed. Raises 404 when the user does not exist or is out of scope.

    Out-of-scope reads deliberately return 404 rather than 403: a 403 would confirm that a
    given id exists in another tenant, which is an information leak in a multi-tenant system.
    """
    user, _coll = await _find_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found.")

    user_company = str(user.get("company_id") or "")
    if not is_internal_user(actor):
        if user_company != str(actor.get("company_id") or ""):
            raise HTTPException(status_code=404, detail="Employee not found.")
    elif company_id:
        # Resolved per tenant rather than by comparing `company_id` directly: Sparsh Magic's
        # own people are `staff` and carry none, so a flat comparison 404s every one of them.
        from app.utils.hrms_access import tenant_member
        if not await tenant_member(company_id, user_id, {"_id": 1}):
            raise HTTPException(status_code=404, detail="Employee not found.")

    is_self = str(actor.get("_id") or "") == str(user_id)
    if not is_self and not can(actor, Cap.EMPLOYEE_READ):
        raise HTTPException(status_code=403, detail="You may only view your own profile.")

    if not is_self and hrms_role(actor) == HrmsRole.MANAGER:
        # The collection the person was FOUND in: Sparsh Magic's own people are `staff`
        # (no company_id), a client's are `learners`. Checking learners only 404'd every
        # Sparsh manager opening their own direct report.
        scope = await _manager_scope(actor, company_id or user_company)
        visible = await get_collection(_coll).find_one(
            {"$and": [{"_id": _oid(user_id)}, scope]}, {"_id": 1})
        if not visible:
            raise HTTPException(status_code=404, detail="Employee not found.")

    if user_company or company_id:
        from app.services.hrms_employee_master_service import apply_due_changes
        await apply_due_changes(company_id or user_company)
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one({"user_id": str(user_id)})
    departments, designations, managers = await _resolve_lookups(
        (profile or {}).get("company_id") or user_company, [user], [profile])

    # You may always see your own pay; otherwise it takes the capability.
    include_salary = (force_salary if force_salary is not None
                      else (is_self or can(actor, Cap.EMPLOYEE_SALARY_READ)))
    view = _compose(user, profile, departments=departments, designations=designations,
                    managers=managers, include_salary=include_salary)
    return await _finish_view(actor, view, profile, is_self=is_self,
                              include_salary=include_salary)


async def _finish_view(actor: dict, view: dict, profile: Optional[dict], *, is_self: bool,
                       include_salary: bool) -> dict:
    """The parts of a single-employee view that need more reads: field-level visibility of
    custom fields, scheduled (future-dated) changes, the reporting manager's employee code
    and the current salary structure's CTC / gross (FRD §3 Reporting, Salary linkage)."""
    from app.services import hrms_employee_master_service as master
    company_id = (profile or {}).get("company_id") or view.get("company_id")
    if not profile or not company_id:
        view["custom_fields"] = {}
        return view
    defs = await master.list_field_definitions(company_id, "employee")
    is_hr = can(actor, Cap.EMPLOYEE_WRITE)
    view["custom_fields"] = master.visible_custom_fields(
        defs, profile.get("custom_fields"), is_hr=is_hr, is_self=is_self,
        is_manager=hrms_role(actor) == HrmsRole.MANAGER,
        is_payroll=can(actor, Cap.PAYROLL_PROCESS), context=profile)
    if is_hr and profile.get("employee_code"):
        view["scheduled_changes"] = await master.scheduled_for(company_id,
                                                                profile["employee_code"])
    for key in ("reporting_manager_id", "functional_manager_id"):
        manager_id = view.get(key)
        if manager_id:
            mp = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
                {"user_id": str(manager_id)}, {"employee_code": 1})
            view[key.replace("_id", "_code")] = (mp or {}).get("employee_code")
    if include_salary and profile.get("employee_code"):
        from app.services.hrms_payroll_service import structure_summary
        view["salary_summary"] = await structure_summary(company_id, profile["employee_code"])
    # FRD §3 Basic Identity. The metadata only — the storage key stays server-side and the
    # picture itself is fetched through its own short-lived link.
    view["photograph"] = master.photograph_view(profile.get("photograph"))
    return view


async def get_employee_by_code(actor: dict, company_id: str,
                               employee_code: str) -> Optional[dict]:
    """One employee addressed by EMPLOYEE CODE rather than by login id.

    Needed because an employee created by onboarding has no `user_id` at all until their
    account is linked -- deliberately so, see the onboarding module's own note. Every
    caller that addresses people by ObjectId therefore cannot reach a brand-new joiner,
    which is exactly the person somebody is most likely to open.

    Returns None rather than raising when there is no such code, so a caller can fall back
    to the user-id path without catching.
    """
    if not employee_code:
        return None
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        return None
    if not can(actor, Cap.EMPLOYEE_READ):
        raise HTTPException(status_code=403, detail="You may only view your own profile.")

    user = None
    if profile.get("user_id"):
        user, _coll = await _find_user(profile["user_id"])
    departments, designations, managers = await _resolve_lookups(
        company_id, [user] if user else [], [profile])
    include_salary = can(actor, Cap.EMPLOYEE_SALARY_READ)
    view = _compose(user, profile, departments=departments, designations=designations,
                    managers=managers, include_salary=include_salary)
    return await _finish_view(actor, view, profile, is_self=False,
                              include_salary=include_salary)


async def create_profile(actor: dict, company_id: str, payload: dict, *,
                         dry_run: bool = False) -> dict:
    """Create the HR profile for an existing user.

    `dry_run` runs every check below and returns what WOULD be created without writing
    anything -- not even an employee number, which is why an auto-numbered row previews
    with no code. The import preview is built on it, so a file is judged by exactly the
    rules a hand-entered employee is.
    """
    user_id = str(payload.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=422, detail="A user must be selected.")

    user, _coll = await _find_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    # Membership through tenant_identity_source, like every other "is this person in this
    # company" check: Sparsh Magic's own people are `staff` with no company_id, a client's
    # are its `learners`. This used to accept learners only, so Add Employee offered Sparsh's
    # staff (list_linkable_users resolves the same way) and then refused every one of them —
    # nobody at Sparsh could get a profile, and so nobody could be paid. The guard it was
    # there for still holds: a staff account is not a member of any CLIENT company, and a
    # learner is not a member of Sparsh Magic.
    from app.utils.hrms_access import tenant_member
    if not await tenant_member(company_id, user_id, {"_id": 1}):
        raise HTTPException(status_code=403, detail="That user belongs to another company.")

    profiles = get_collection(COLL_EMPLOYEE_PROFILES)
    if await profiles.find_one({"user_id": user_id}):
        raise HTTPException(status_code=409, detail="This user already has an employee profile.")

    if payload.get("base_salary") is not None and not can(actor, Cap.EMPLOYEE_SALARY_WRITE):
        raise HTTPException(status_code=403, detail="You may not set salary.")

    clean = await _validate_profile(payload, company_id, partial=False)
    _check_date_order(clean.get("joined_on"), clean.get("resigned_on"))

    # FRD §4: identity / duplicate validation BEFORE the record is committed, list values
    # checked against the company's masters, custom fields against their definitions.
    from app.services import hrms_employee_master_service as master
    await master.assert_no_duplicates(company_id, clean, exclude_user_id=user_id)
    await master.validate_master_values(company_id, clean)
    clean["custom_fields"] = await master.validate_custom_values(
        company_id, "employee", clean.get("custom_fields"), context=clean,
        enforce_mandatory=True)
    reporting_manager = clean.pop("reporting_manager_id", None)
    if reporting_manager == user_id:
        raise HTTPException(status_code=422, detail="Nobody reports to themselves.")

    code = clean.get("employee_code")
    if code:
        if await profiles.find_one({"company_id": str(company_id), "employee_code": code}):
            raise HTTPException(status_code=409, detail=f"Employee code '{code}' is already in use.")
    elif dry_run:
        code = None
    else:
        from app.services.hrms_employee_master_service import next_employee_code
        code = await next_employee_code(str(company_id), datetime.now(timezone.utc).year)
    if dry_run:
        return {"user_id": user_id, "name": _display_name(user), "employee_code": code}

    doc = {
        "user_id": user_id,
        "company_id": str(company_id),
        "employee_code": code,
        "employment_status": clean.get("employment_status", EmploymentStatus.ACTIVE.value),
        "employment_type": clean.get("employment_type"),
        "created_at": datetime.now(timezone.utc),
        "created_by": str(actor.get("_id")) if actor.get("_id") else None,
        "updated_at": datetime.now(timezone.utc),
        "updated_by": str(actor.get("_id")) if actor.get("_id") else None,
    }
    for field, value in clean.items():
        doc.setdefault(field, value)
        doc[field] = value

    try:
        await profiles.insert_one(doc)
    except Exception as e:
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            raise HTTPException(status_code=409, detail="This user already has an employee profile.")
        raise

    if reporting_manager:
        await master.set_user_reporting_manager(user_id, reporting_manager)
    # The starting values are the first history rows, so the timeline begins at joining.
    initial = {f: (None, doc.get(f)) for f in EMPLOYEE_TRACKED_FIELDS
               if doc.get(f) not in (None, "", [])}
    if reporting_manager:
        initial["reporting_manager_id"] = (user.get("reporting_manager"), reporting_manager)
    await master.record_changes(
        actor, company_id, doc, initial,
        effective_from=clean.get("joined_on") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        reason="Employee created", status=HISTORY_APPLIED)

    await audit(actor, AUDIT_EMPLOYEE_CREATED, ENTITY_EMPLOYEE, user_id,
                f"{_display_name(user)} ({code})", company_id)
    return await get_employee(actor, user_id, company_id=company_id)


async def update_profile(actor: dict, user_id: str, payload: dict, company_id: str) -> dict:
    """Update an employee profile, creating it on first write if absent.

    Upserting keeps the UI simple: HR edits an employee from the directory without caring
    whether a profile row already exists.
    """
    user, coll = await _find_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found.")
    # Membership through tenant_identity_source (see create_profile): Sparsh's own staff carry
    # no company_id, so the flat comparison this replaced refused EVERY edit to a staff
    # member's profile with "Employee not found".
    from app.utils.hrms_access import tenant_member
    if not await tenant_member(company_id, user_id, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Employee not found.")

    profiles = get_collection(COLL_EMPLOYEE_PROFILES)
    current = await profiles.find_one({"user_id": str(user_id)}) or {}

    # The gate is on INTENT TO WRITE, not on whether the value differs.
    #
    # A delta check looks equivalent but is not: with no salary stored yet, writing 0
    # compares `0.0 != (None or 0)` -> False, so the capability check would be skipped and a
    # caller without EMPLOYEE_SALARY_WRITE could set a salary. "Writing the same value" is
    # not a meaningful exemption from a permission check either way.
    salary_write_attempted = ("base_salary" in payload and payload["base_salary"] is not None)
    if salary_write_attempted and not can(actor, Cap.EMPLOYEE_SALARY_WRITE):
        raise HTTPException(status_code=403, detail="You may not change salary.")
    # The delta is still needed, but only to decide whether to write a dedicated audit line.
    salary_changing = (salary_write_attempted
                       and float(payload["base_salary"]) != current.get("base_salary"))

    effective_from = str(payload.get("effective_from") or "").strip() or \
        datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not is_iso_date(effective_from):
        raise HTTPException(status_code=422, detail="Effective from must be YYYY-MM-DD.")
    reason = payload.get("change_reason")

    clean = await _validate_profile(payload, company_id, partial=True)
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update.")

    _check_date_order(
        clean.get("joined_on", current.get("joined_on")),
        clean.get("resigned_on", current.get("resigned_on")),
    )

    code = clean.get("employee_code")
    if code and code != current.get("employee_code"):
        clash = await profiles.find_one({
            "company_id": str(company_id), "employee_code": code,
            "user_id": {"$ne": str(user_id)},
        })
        if clash:
            raise HTTPException(status_code=409, detail=f"Employee code '{code}' is already in use.")

    from app.services import hrms_employee_master_service as master
    await master.assert_no_duplicates(company_id, clean, exclude_user_id=str(user_id))
    await master.validate_master_values(company_id, clean)
    if "custom_fields" in clean:
        clean["custom_fields"] = await master.validate_custom_values(
            company_id, "employee", clean["custom_fields"],
            current=current.get("custom_fields"), context={**current, **clean},
            enforce_mandatory=True, record_filter={"user_id": {"$ne": str(user_id)}})
    if clean.get("reporting_manager_id") == str(user_id) or \
            clean.get("functional_manager_id") == str(user_id):
        raise HTTPException(status_code=422, detail="Nobody reports to themselves.")

    # Effective-dated fields (FRD §4, §18): what actually changes is recorded with its date;
    # a FUTURE date schedules it instead of applying it now.
    before = dict(current)
    before["reporting_manager_id"] = user.get("reporting_manager") or current.get(
        "reporting_manager_id")
    tracked = {f: (before.get(f), clean[f]) for f in EMPLOYEE_TRACKED_FIELDS
               if f in clean and clean[f] != before.get(f)
               and not (clean[f] in (None, "", []) and before.get(f) in (None, "", []))}
    # DEF-09 -- every other field (personal, contact, statutory, each custom field) is
    # recorded with its old and new value too. These are not effective-dated: they apply
    # now, so their history row is dated today whatever `effective_from` says.
    def _empty(v):
        return v in (None, "", [])
    untracked = {f: (before.get(f), clean[f]) for f in clean
                 if f not in EMPLOYEE_TRACKED_FIELDS and f != "custom_fields"
                 and clean[f] != before.get(f) and not (_empty(clean[f]) and _empty(before.get(f)))}
    if "custom_fields" in clean:
        old_custom = before.get("custom_fields") or {}
        new_custom = clean.get("custom_fields") or {}
        for key in sorted(set(old_custom) | set(new_custom)):
            old_v, new_v = old_custom.get(key), new_custom.get(key)
            if old_v != new_v and not (_empty(old_v) and _empty(new_v)):
                untracked[f"custom_fields.{key}"] = (old_v, new_v)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scheduled = effective_from > today
    if scheduled:
        for f in tracked:
            clean.pop(f, None)

    now = datetime.now(timezone.utc)
    if clean:
        clean["updated_at"] = now
        clean["updated_by"] = str(actor.get("_id") or "") or None
        await profiles.update_one(
            {"user_id": str(user_id)},
            {"$set": clean,
             "$setOnInsert": {"user_id": str(user_id), "company_id": str(company_id),
                              "created_at": now}},
            upsert=True,
        )
    if "reporting_manager_id" in clean and "reporting_manager_id" in tracked:
        await master.set_user_reporting_manager(str(user_id), clean["reporting_manager_id"])

    saved = await profiles.find_one({"user_id": str(user_id)}) or {"user_id": str(user_id)}
    await master.record_changes(actor, company_id, saved, tracked,
                                effective_from=effective_from, reason=reason,
                                status=HISTORY_SCHEDULED if scheduled else HISTORY_APPLIED)
    await master.record_changes(actor, company_id, saved, untracked,
                                effective_from=today, reason=reason, status=HISTORY_APPLIED)
    if scheduled and tracked:
        await audit(actor, AUDIT_EMPLOYEE_CHANGE_SCHEDULED, ENTITY_EMPLOYEE, str(user_id),
                    f"{', '.join(sorted(tracked))} from {effective_from}", company_id,
                    changes=master.audit_changes(tracked))

    changed = sorted(k for k in clean if k not in ("updated_at", "updated_by"))
    if changed:
        applied = {**({} if scheduled else tracked), **untracked}
        await audit(actor, AUDIT_EMPLOYEE_UPDATED, ENTITY_EMPLOYEE, str(user_id),
                    ", ".join(changed), company_id, changes=master.audit_changes(applied))
    if salary_changing and "base_salary" in clean:
        # Pay changes get their own audit line so a payroll dispute can be traced without
        # reading every field-level update row.
        await audit(actor, AUDIT_SALARY_CHANGED, ENTITY_EMPLOYEE, str(user_id),
                    f"{current.get('base_salary')} -> {clean.get('base_salary')}", company_id)

    return await get_employee(actor, user_id, company_id=company_id)


async def employee_history(actor: dict, company_id: str, user_id: str = None,
                           employee_code: str = None) -> dict:
    """The effective-dated change timeline for one employee (FRD §4, §20)."""
    from app.services import hrms_employee_master_service as master
    if not employee_code:
        profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
            {"user_id": str(user_id), "company_id": str(company_id)})
        employee_code = (profile or {}).get("employee_code")
    if not employee_code:
        return {"history": [], "employee_code": None}
    return {"employee_code": employee_code,
            "history": await master.list_history(
                company_id, employee_code,
                include_sensitive=can(actor, Cap.EMPLOYEE_SALARY_READ))}


async def get_hierarchy(actor: dict, user_id: str, company_id: str) -> dict:
    """Reporting chain upward + direct reports downward.

    The upward walk is depth-capped and cycle-guarded: `reporting_manager` has no database
    constraint preventing A->B->A, and an unguarded walk would hang the request.
    """
    employee = await get_employee(actor, user_id, company_id=company_id)

    chain, seen, cursor, depth = [], {str(user_id)}, employee.get("reporting_manager_id"), 0
    while cursor and depth < 10:
        cursor = str(cursor)
        if cursor in seen:
            chain.append({"user_id": cursor, "name": "(circular reference)", "circular": True})
            break
        seen.add(cursor)
        manager, _c = await _find_user(cursor)
        if not manager:
            break
        chain.append({
            "user_id": cursor,
            "name": _display_name(manager),
            "email": manager.get("email"),
            "governance_role": manager.get("governance_role"),
        })
        cursor = manager.get("reporting_manager")
        depth += 1

    # Resolved per tenant, like the directory: a Sparsh staff manager's reports are staff.
    source, tenant_query = await _identity_source(company_id)
    reports = await get_collection(source).find(
        {**tenant_query, "reporting_manager": str(user_id), "is_active": {"$ne": False}},
        {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1, "governance_role": 1},
    ).sort("full_name", 1).to_list(500)

    return {
        "employee": {"user_id": employee["user_id"], "name": employee["name"]},
        "manager_chain": chain,
        "direct_reports": [
            {"user_id": str(r["_id"]), "name": _display_name(r), "email": r.get("email"),
             "governance_role": r.get("governance_role")}
            for r in reports
        ],
        "report_count": len(reports),
    }


# ─────────────────────────────────────────────────────────────
# FRD §4 — "HR creates or IMPORTS the employee record"
# ─────────────────────────────────────────────────────────────
MAX_IMPORT_ROWS = 500
IMPORT_EMAIL_COLUMNS = ("email", "user_email", "login_email")
# Columns HR can fill with what they know -- a name or an email -- instead of an internal id.
IMPORT_LOOKUP_COLUMNS = ("department", "designation", "reporting_manager_email",
                         "functional_manager_email")
# Read as dd/mm/yyyy, dd-Mon-yyyy etc. as well as ISO -- a spreadsheet rarely says ISO.
IMPORT_DATE_FIELDS = {f for f, _label in EMPLOYEE_DATE_FIELDS} | {
    "date_of_birth", "joined_on", "resigned_on", "effective_from"}
IMPORT_TEMPLATE_COLUMNS = (
    "email", "employee_code", "first_name", "middle_name", "last_name", "display_name",
    "gender", "date_of_birth", "marital_status", "blood_group", "nationality",
    "personal_mobile", "official_mobile", "personal_email", "official_email",
    "current_address.line1", "current_address.line2", "current_address.city",
    "current_address.district", "current_address.state", "current_address.pin_code",
    "current_address.country", "permanent_same_as_current",
    "emergency_contact_name", "emergency_contact_relation", "emergency_contact_phone",
    "joined_on", "employee_category", "employment_status", "employment_type",
    "probation_start", "probation_end", "confirmation_date",
    "legal_entity", "business_unit", "work_location", "department", "sub_department",
    "designation", "grade", "level", "job_title", "cost_centre",
    "reporting_manager_email", "functional_manager_email",
    "shift_code", "attendance_policy_group", "weekly_off_pattern", "holiday_calendar",
    "bank_name", "bank_branch", "bank_account_holder", "bank_account", "bank_ifsc",
    "bank_account_type", "pan", "aadhaar", "uan", "pf_number", "esi_number",
    "passport", "driving_license", "payroll_group", "salary_template",
)


def _import_header(h) -> str:
    return re.sub(r"[^a-z0-9_.]+", "_", str(h or "").strip().lower()).strip("_")


def _import_text(value) -> str:
    """A cell as text: Excel hands numbers back as floats (an account number would read
    1234567890.0) and dates as datetimes."""
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


async def _import_lookups(company_id: str) -> dict:
    by_name = lambda docs: {str(d.get("name") or "").strip().lower(): str(d["_id"])
                            for d in docs if d.get("name")}
    return {
        "department": by_name(await get_collection(COLL_DEPARTMENTS).find(
            {"company_id": str(company_id)}, {"name": 1}).to_list(2000)),
        "designation": by_name(await get_collection(COLL_DESIGNATIONS).find(
            {"company_id": str(company_id)}, {"name": 1}).to_list(2000)),
    }


async def _user_by_email(company_id: str, email: str) -> Optional[dict]:
    source, query = await _identity_source(company_id)
    return await get_collection(source).find_one(
        {**query, "email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}, {"_id": 1})


async def _import_payload(company_id: str, values: dict, known: dict, lookups: dict) -> dict:
    """One row's cells as an EmployeeProfileIn payload. Dotted headers fill an address
    (`current_address.city`), `custom.<code>` fills a configurable field, and the lookup
    columns are resolved to the ids the profile stores."""
    from app.services.hrms_attendance_rules_service import _parse_date
    payload, custom = {}, {}
    for header, raw in values.items():
        text = _import_text(raw)
        if header.startswith("custom."):
            custom[header[7:]] = text
        elif header in ("department", "designation"):
            found = lookups[header].get(text.lower())
            if not found:
                raise HTTPException(status_code=422,
                                    detail=f"No {header} called '{text}' in this company.")
            payload[f"{header}_id"] = found
        elif header in ("reporting_manager_email", "functional_manager_email"):
            manager = await _user_by_email(company_id, text)
            if not manager:
                raise HTTPException(status_code=422,
                                    detail=f"No user account with email {text} for the "
                                           f"{header.split('_')[0]} manager.")
            payload[header.replace("_email", "_id")] = str(manager["_id"])
        elif "." in header and header.split(".", 1)[0] in known:
            parent, child = header.split(".", 1)
            payload.setdefault(parent, {})[child] = text
        elif header in known:
            if header in IMPORT_DATE_FIELDS:
                text = _parse_date(raw) or text
            elif "list" in str(known[header].annotation):
                text = [p.strip() for p in re.split(r"[;,]", text) if p.strip()]
            payload[header] = text
    if custom:
        payload["custom_fields"] = custom
    return payload


async def import_profiles(actor: dict, company_id: str, filename: str, raw: bytes, *,
                          commit: bool) -> dict:
    """Read an employee file and preview it (commit=False) or create its rows (commit=True).

    Each row names an EXISTING user account by email -- the same rule Add Employee follows,
    because identity lives on the user and is never duplicated onto the profile -- and goes
    through `create_profile` itself, so duplicate, master-list, custom-field and numbering
    checks are the ones a hand-entered employee meets. Rows stand alone: one bad row is
    reported, the rest still load.
    """
    from pydantic import ValidationError
    from app.models.hrms import EmployeeProfileIn
    from app.services.hrms_attendance_rules_service import read_rows
    if not str(filename or "").lower().endswith((".csv", ".xlsx", ".xlsm")):
        raise HTTPException(status_code=415, detail="Upload the employee file as CSV or Excel (.xlsx).")
    rows = [r for r in read_rows(filename, raw) if any(str(c or "").strip() for c in r)]
    if len(rows) < 2:
        raise HTTPException(status_code=422, detail="The file has no employee rows under its header.")
    if len(rows) - 1 > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=422,
                            detail=f"Import at most {MAX_IMPORT_ROWS} employees per file.")
    headers = [_import_header(h) for h in rows[0]]
    if not set(headers) & set(IMPORT_EMAIL_COLUMNS):
        raise HTTPException(status_code=422,
                            detail="Add an 'email' column: it names the user account each "
                                   "row is for.")
    known = {k: f for k, f in EmployeeProfileIn.model_fields.items() if k != "user_id"}
    usable = set(IMPORT_EMAIL_COLUMNS) | set(IMPORT_LOOKUP_COLUMNS) | set(known)
    ignored = sorted({h for h in headers if h and h.split(".", 1)[0] not in usable
                      and not h.startswith("custom.")})
    lookups = await _import_lookups(company_id)

    seen, results = {}, []
    for number, row in enumerate(rows[1:], start=2):
        values = {h: row[i] for i, h in enumerate(headers)
                  if h and h not in ignored and i < len(row) and str(row[i] or "").strip()}
        email = next((_import_text(values.pop(h)) for h in IMPORT_EMAIL_COLUMNS
                      if h in values), "")
        for h in IMPORT_EMAIL_COLUMNS:
            values.pop(h, None)
        result = {"row": number, "email": email}
        try:
            if not email:
                raise HTTPException(status_code=422, detail="No email on this row.")
            user = await _user_by_email(company_id, email)
            if not user:
                raise HTTPException(status_code=404,
                                    detail=f"No user account with email {email} in this company.")
            payload = await _import_payload(company_id, values, known, lookups)
            payload["user_id"] = str(user["_id"])
            payload = EmployeeProfileIn(**payload).model_dump(exclude_unset=True)
            # Two rows of one file never meet create_profile's database checks in a preview,
            # so the file is checked against itself too.
            for field, label in [("user_id", "user account"), ("employee_code", "employee code")] \
                    + list(EMPLOYEE_DUPLICATE_FIELDS):
                value = payload.get(field)
                if value in (None, ""):
                    continue
                key = (field, str(value).strip().lower())
                if key in seen:
                    raise HTTPException(status_code=409,
                                        detail=f"Same {label} as row {seen[key]}.")
                seen[key] = number
            made = await create_profile(actor, company_id, payload, dry_run=not commit)
            result.update(status="Created" if commit else "Ready",
                          name=made.get("name") or made.get("display_name"),
                          employee_code=made.get("employee_code"))
        except HTTPException as e:
            result.update(status="Error", error=str(e.detail))
        except ValidationError as e:
            result.update(status="Error", error="; ".join(
                f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                for err in e.errors()[:3]))
        results.append(result)

    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("Ready", "Created", "Error")}
    return {"commit": commit, "rows": results, "ignored_columns": ignored, **counts}


async def list_linkable_users(actor: dict, company_id: str) -> list:
    """Company users who do NOT yet have an employee profile -- the picker for "Add employee".

    Without this the UI would offer everyone and rely on a 409 to explain the mistake.
    """
    # `.get`, not `[...]`: a profile created by onboarding has no `user_id` key at all, and
    # subscripting one would raise KeyError for every caller of this picker.
    existing = {
        p.get("user_id") for p in await get_collection(COLL_EMPLOYEE_PROFILES).find(
            {"company_id": str(company_id)}, {"user_id": 1}).to_list(5000)
    } - {None}
    source, query = await _identity_source(company_id)
    users = await get_collection(source).find(
        {**query, "is_active": {"$ne": False}}, _USER_PROJECTION
    ).sort("full_name", 1).to_list(2000)
    return [
        {"user_id": str(u["_id"]), "name": _display_name(u), "email": u.get("email"),
         "governance_role": u.get("governance_role"), "legacy_department": u.get("department"),
         "legacy_designation": u.get("designation")}
        for u in users if str(u["_id"]) not in existing
    ]


def _escape_regex(value: str) -> str:
    import re
    return re.escape(value)


async def create_from_onboarding(actor: dict, company_id: str, *, employee_code: str,
                                 identity: dict, source_uk: str,
                                 joined_on: str = None, department_id: str = None,
                                 designation_id: str = None, assignment: dict = None,
                                 extra: dict = None) -> dict:
    """Create an employee record for someone who has no login account yet (Phase 9).

    This is the moment recruitment becomes an employee, and it is the link both analysis
    documents said was missing entirely.

    HRMS still does NOT write to `staff`/`learners`. Instead the profile carries an
    `identity_snapshot` and omits `user_id` (the index is sparse), so:
      * the new hire appears in the directory immediately, flagged `pending_user_link`;
      * nothing is duplicated into an identity collection HRMS does not own;
      * `link_user` later attaches the real account, after which the user document is the
        single source of identity and the snapshot is ignored.
    """
    profiles = get_collection(COLL_EMPLOYEE_PROFILES)
    if await profiles.find_one({"company_id": str(company_id),
                                "employee_code": employee_code}):
        raise HTTPException(
            status_code=409, detail=f"Employee code '{employee_code}' is already in use.")

    now = datetime.now(timezone.utc)
    doc = {
        # `user_id` is deliberately ABSENT, not None -- a null value would still be indexed
        # by the unique index and only one such row could exist.
        "company_id": str(company_id),
        "employee_code": employee_code,
        "identity_snapshot": {
            "name": identity.get("name"),
            "email": identity.get("email"),
            "mobile": identity.get("mobile"),
        },
        "source_uk": source_uk,
        "employment_status": EmploymentStatus.ACTIVE.value,
        "employment_type": EmploymentType.FULL_TIME.value,
        "joined_on": joined_on,
        "department_id": department_id,
        "designation_id": designation_id,
        "created_at": now,
        "created_by": str(actor.get("_id")) if actor and actor.get("_id") else None,
    }
    # §7.5 Stage 6 -- what HR assigned at joining. Applied over the defaults above, so
    # a company that records an employment category or a payroll group gets theirs rather
    # than the fallback, and one that records neither is unaffected.
    for key, value in (assignment or {}).items():
        if value not in (None, ""):
            doc[key] = getattr(value, "value", value)
    for key, value in (extra or {}).items():
        if value is not None:
            doc[key] = value

    await profiles.insert_one(dict(doc))
    await audit(actor, AUDIT_EMPLOYEE_CREATED, ENTITY_EMPLOYEE, employee_code,
                f"{identity.get('name')} created from onboarding ({source_uk})", company_id)
    doc.pop("_id", None)
    return doc


async def link_user(actor: dict, company_id: str, employee_code: str, user_id: str) -> dict:
    """Attach an onboarding-created employee record to a real login account.

    After this the user document is the single source of identity -- the snapshot stays for
    history but is no longer read (see `_compose`).
    """
    profiles = get_collection(COLL_EMPLOYEE_PROFILES)
    profile = await profiles.find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(status_code=404, detail="Employee record not found.")
    if profile.get("user_id"):
        raise HTTPException(
            status_code=409, detail="This employee is already linked to a user account.")

    user, _coll = await _find_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    # Membership through tenant_identity_source, exactly as `create_profile` resolves it.
    # This used to demand `learners` with a matching company_id, which is the rule for a
    # CLIENT company and wrong for Sparsh Magic's own tenant: its people are `staff` and
    # carry no company_id at all. So at the internal company every link was refused --
    # the same defect create_profile's comment describes having fixed, left standing here
    # because the two checks were written separately. An onboarding-created profile there
    # could never be attached to its account, which is the one step that turns a new hire
    # into somebody the directory, payroll and self-service all recognise.
    from app.utils.hrms_access import tenant_member
    if not await tenant_member(company_id, user_id, {"_id": 1}):
        raise HTTPException(
            status_code=422, detail="The account must belong to a user of this company.")
    if await profiles.find_one({"user_id": str(user_id)}):
        raise HTTPException(
            status_code=409, detail="That user already has an employee profile.")

    await profiles.update_one(
        {"company_id": str(company_id), "employee_code": employee_code},
        {"$set": {"user_id": str(user_id), "linked_at": datetime.now(timezone.utc)}})
    # From now on the user document owns the reporting line; carry over the one HR chose
    # at joining if the account has none yet.
    if profile.get("reporting_manager_id") and not user.get("reporting_manager"):
        from app.services.hrms_employee_master_service import set_user_reporting_manager
        await set_user_reporting_manager(str(user_id), profile["reporting_manager_id"])
    await audit(actor, AUDIT_EMPLOYEE_LINKED, ENTITY_EMPLOYEE, employee_code,
                f"linked to {_display_name(user)}", company_id)
    return await get_employee(actor, user_id, company_id=company_id)
