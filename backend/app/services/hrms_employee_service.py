"""Employee master — the only place employee queries are written.

Routes stay thin (mirroring how the reference project keeps its SQL in one repo module, and how
this app keeps report logic in report_service). Two rules are enforced here rather than in the
routes, so no future endpoint can forget them:

  1. **Sensitive fields are masked at serialization.** PAN, Aadhaar, UAN, ESIC, bank details and
     CTC never leave this module for a caller without personal-data permission. The guard is not
     "hope the UI hides it" — the data is not in the response at all.
  2. **Every mutation appends a timeline event.** A profile shows a chronology, not one mutable
     row.

Nothing here deletes an employee. Leaving the company is a STATUS change (Resigned/Retired/…),
which keeps attendance, leave and payroll history intact and referable.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

from app.db.mongodb import get_collection
from app.models.hrms import (
    COL_EMPLOYEES, COL_EMPLOYEE_EVENTS, COL_ORG_MASTERS,
    SENSITIVE_FIELDS, EXITED_STATUSES, ORG_KINDS,
    SEQ_EMPLOYEE, EVENT_CREATED, EVENT_UPDATED, EVENT_STATUS_CHANGE, EVENT_EXIT,
)
from app.utils.counters import next_code

logger = logging.getLogger(__name__)


# ─── Permission helpers ─────────────────────────────────────────────────────────
def can_read_personal_data(user: dict) -> bool:
    """Who may see statutory / bank / salary data.

    Deliberately stricter than `hrms.read` (which grants the directory): a reader needs
    `hrms.update` — i.e. someone who administers employee records, not merely looks people up.
    Super Admin bypasses, as everywhere else in the app.
    """
    if not user:
        return False
    if user.get("role") == "superadmin":
        return True
    return bool(user.get("permissions", {}).get("hrms", {}).get("update"))


def _mask(value: str) -> str:
    """Show only the last 4 characters of an identifier: 'XXXXXX1234'. Empty stays empty."""
    s = str(value or "").strip()
    if not s:
        return ""
    if len(s) <= 4:
        return "•" * len(s)
    return "•" * (len(s) - 4) + s[-4:]


def serialize_employee(doc: dict, include_sensitive: bool) -> dict:
    """DB document -> API shape.

    When `include_sensitive` is False the identifiers are masked and bank/CTC are dropped
    entirely — a non-HR reader gets a directory, not a data dump.
    """
    if not doc:
        return {}
    out = {
        "id": str(doc.get("_id")),
        "employeeCode": doc.get("employee_code"),
        "userId": doc.get("user_id") or "",
        "fullName": doc.get("full_name") or "",
        "displayName": doc.get("display_name") or "",
        "gender": doc.get("gender") or "",
        "dateOfBirth": doc.get("date_of_birth"),
        "personalEmail": doc.get("personal_email") or "",
        "workEmail": doc.get("work_email") or "",
        "phone": doc.get("phone") or "",
        "address": doc.get("address") or "",
        "emergencyName": doc.get("emergency_name") or "",
        "emergencyRelation": doc.get("emergency_relation") or "",
        "emergencyPhone": doc.get("emergency_phone") or "",
        "designation": doc.get("designation") or "",
        "department": doc.get("department") or "",
        "location": doc.get("location") or "",
        "employmentType": doc.get("employment_type") or "Full-time",
        "grade": doc.get("grade") or "",
        "workMode": doc.get("work_mode") or "Office",
        "reportingManager": doc.get("reporting_manager") or "",
        "status": doc.get("status") or "Active",
        "dateOfJoining": doc.get("date_of_joining"),
        "probationEndDate": doc.get("probation_end_date"),
        "confirmationDate": doc.get("confirmation_date"),
        "exitDate": doc.get("exit_date"),
        "exitReason": doc.get("exit_reason") or "",
        "photoUrl": doc.get("photo_url") or "",
        "createdBy": doc.get("created_by") or "",
        "createdAt": doc.get("created_at"),
        "updatedAt": doc.get("updated_at"),
        # Lets the UI render a "hidden" state honestly instead of showing blanks that look like
        # missing data.
        "sensitiveVisible": include_sensitive,
    }
    if include_sensitive:
        out.update({
            "pan": doc.get("pan") or "",
            "aadhaar": doc.get("aadhaar") or "",
            "passport": doc.get("passport") or "",
            "drivingLicense": doc.get("driving_license") or "",
            "uan": doc.get("uan") or "",
            "esicNo": doc.get("esic_no") or "",
            "bankName": doc.get("bank_name") or "",
            "bankAccount": doc.get("bank_account") or "",
            "bankIfsc": doc.get("bank_ifsc") or "",
            "ctcAnnual": float(doc.get("ctc_annual") or 0),
        })
    else:
        # Identifiers masked (so HR can confirm "is this the right PAN?" over a shoulder);
        # bank and salary omitted outright.
        out.update({
            "pan": _mask(doc.get("pan")),
            "aadhaar": _mask(doc.get("aadhaar")),
            "passport": _mask(doc.get("passport")),
            "drivingLicense": _mask(doc.get("driving_license")),
            "uan": _mask(doc.get("uan")),
            "esicNo": _mask(doc.get("esic_no")),
        })
    return out


def serialize_event(doc: dict) -> dict:
    return {
        "id": str(doc.get("_id")),
        "employeeCode": doc.get("employee_code"),
        "eventType": doc.get("event_type"),
        "detail": doc.get("detail") or "",
        "effectiveDate": doc.get("effective_date"),
        "actor": doc.get("actor") or "",
        "actorName": doc.get("actor_name") or "",
        "meta": doc.get("meta") or {},
        "createdAt": doc.get("created_at"),
    }


def serialize_org_master(doc: dict) -> dict:
    return {
        "id": str(doc.get("_id")),
        "kind": doc.get("kind"),
        "name": doc.get("name") or "",
        "code": doc.get("code") or "",
        "head": doc.get("head") or "",
        "department": doc.get("department") or "",
        "grade": doc.get("grade") or "",
        "type": doc.get("type") or "",
        "city": doc.get("city") or "",
        "state": doc.get("state") or "",
        "description": doc.get("description") or "",
        "active": doc.get("active", True),
        "createdAt": doc.get("created_at"),
    }


# ─── Timeline ───────────────────────────────────────────────────────────────────
async def add_employee_event(employee_code: str, event_type: str, detail: str,
                             actor: dict, effective_date: Optional[str] = None,
                             meta: Optional[dict] = None) -> None:
    """Append a timeline entry. Never raises into the caller — a missing history line must not
    roll back the employee change that produced it."""
    try:
        await get_collection(COL_EMPLOYEE_EVENTS).insert_one({
            "employee_code": employee_code,
            "event_type": event_type,
            "detail": detail,
            "effective_date": effective_date,
            "actor": str(actor.get("_id")) if actor else "",
            "actor_name": (actor or {}).get("full_name") or (actor or {}).get("email") or "",
            "meta": meta or {},
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.error("Failed to write employee event for %s: %s", employee_code, e)


# ─── Org masters ────────────────────────────────────────────────────────────────
async def upsert_org_master(kind: str, name: str, actor: dict, extra: Optional[dict] = None) -> None:
    """Add a master value if it isn't already there.

    Called both from the Org Structure page and implicitly whenever an employee form submits a
    typed-in department/designation/location — so the lists populate organically from real use
    and can still be curated. Case-insensitive on name, so 'Sales' and 'sales' don't both land.
    """
    clean = (name or "").strip()
    if not clean or kind not in ORG_KINDS:
        return
    existing = await get_collection(COL_ORG_MASTERS).find_one(
        {"kind": kind, "name": {"$regex": f"^{_escape_regex(clean)}$", "$options": "i"}})
    if existing:
        return
    await get_collection(COL_ORG_MASTERS).insert_one({
        "kind": kind,
        "name": clean,
        "active": True,
        "created_by": str(actor.get("_id")) if actor else "",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        **(extra or {}),
    })


def _escape_regex(value: str) -> str:
    """Escape a user-supplied string used inside a Mongo $regex, so a name containing regex
    metacharacters matches literally instead of being interpreted."""
    import re
    return re.escape(value)


# ─── Employees ──────────────────────────────────────────────────────────────────
async def generate_employee_code() -> str:
    """EMP-YYYY-NNNN, allocated atomically so concurrent creates can't collide."""
    return await next_code(SEQ_EMPLOYEE, "EMP")


def build_employee_query(search: Optional[str], department: Optional[str],
                         status: Optional[str], include_exited: bool) -> dict:
    """The directory filter. Kept here so the list and the stats always agree — the reference
    project's dashboard and reports disagree precisely because each built its own copy."""
    clauses = []
    if department:
        clauses.append({"department": department})
    if status:
        clauses.append({"status": status})
    elif not include_exited:
        # Default view is the current workforce; leavers are opt-in.
        clauses.append({"status": {"$nin": EXITED_STATUSES}})
    if search:
        rx = {"$regex": _escape_regex(search.strip()), "$options": "i"}
        clauses.append({"$or": [
            {"full_name": rx}, {"display_name": rx}, {"employee_code": rx},
            {"designation": rx}, {"department": rx}, {"work_email": rx}, {"phone": rx},
        ]})
    return {"$and": clauses} if clauses else {}


async def get_employee_stats() -> dict:
    """Headcount tiles. One aggregation rather than several counts, so the numbers are a
    consistent snapshot of the same moment."""
    col = get_collection(COL_EMPLOYEES)
    pipeline = [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    by_status = {row["_id"]: row["n"] async for row in col.aggregate(pipeline)}
    exited = sum(n for s, n in by_status.items() if s in EXITED_STATUSES)
    return {
        "total": sum(by_status.values()),
        "active": by_status.get("Active", 0),
        "probation": by_status.get("Probation", 0) + by_status.get("On Notice", 0),
        "exited": exited,
        "byStatus": by_status,
    }


async def find_employee(employee_code: str) -> Optional[dict]:
    return await get_collection(COL_EMPLOYEES).find_one({"employee_code": employee_code})


async def link_user_exists(user_id: str) -> bool:
    """Whether `user_id` is a real internal staff account. Employees link to `staff` only —
    the HRMS manages Sparsh's own workforce, so a learner id is never valid here."""
    if not user_id:
        return False
    try:
        doc = await get_collection("staff").find_one({"_id": ObjectId(user_id)}, {"_id": 1})
        return doc is not None
    except Exception:
        return False
