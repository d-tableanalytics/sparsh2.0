"""Leave — day counting, balances, approval routing.

Differences from the reference project, which its own audit rates 25% complete:

  * **Leave types are configured, each carrying its own flags.** The reference hardcodes four
    strings and then decides paid-vs-unpaid by substring match, which misses "Sick" and "Earned"
    — a paid type silently behaving as unpaid. Nothing here ever inspects a type's *name*.
  * **Day counting skips weekly offs and public holidays**, reusing the app's EXISTING `holidays`
    collection rather than a second HRMS calendar.
  * **Balance moves only on approval**, and only for paid types. Applying reserves nothing, so a
    rejected request can't leak entitlement.
  * **Approval is routed**, to the applicant's reporting manager, with HR as the fallback — and
    nobody can approve their own leave.
"""
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional

from bson import ObjectId

from app.db.mongodb import get_collection
from app.models.hrms import (
    COL_LEAVES, COL_LEAVE_BALANCES, SETTING_LEAVE,
    LeaveSettings, LEAVE_PENDING, LEAVE_APPROVED, LEAVE_CANCELLED,
)
from app.services.hrms_attendance_service import get_attendance_settings

logger = logging.getLogger(__name__)


# ─── Settings ───────────────────────────────────────────────────────────────────
async def get_leave_settings() -> dict:
    doc = await get_collection("system_settings").find_one({"setting_name": SETTING_LEAVE})
    defaults = LeaveSettings().model_dump()
    if doc:
        defaults.update({k: v for k, v in doc.items() if k in defaults and v is not None})
    return defaults


def find_leave_type(settings: dict, code: str) -> Optional[dict]:
    return next((t for t in settings.get("types", [])
                 if t.get("code") == code and t.get("active", True)), None)


def validate_leave_types(types: list) -> list:
    """Reject a type list that would break the engine downstream."""
    if not isinstance(types, list) or not types:
        raise ValueError("At least one leave type is required")
    seen = set()
    clean = []
    for t in types:
        code = str(t.get("code") or "").strip().lower()
        name = str(t.get("name") or "").strip()
        if not code or not name:
            raise ValueError("Each leave type needs a code and a name")
        if code in seen:
            raise ValueError(f"Duplicate leave type code '{code}'")
        seen.add(code)
        quota = float(t.get("annual_quota") or 0)
        if quota < 0:
            raise ValueError("annual_quota cannot be negative")
        clean.append({
            "code": code, "name": name,
            "paid": bool(t.get("paid", True)),
            "annual_quota": quota,
            "allow_half_day": bool(t.get("allow_half_day", True)),
            "active": bool(t.get("active", True)),
        })
    return clean


# ─── Day counting ───────────────────────────────────────────────────────────────
def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError(f"Invalid date '{value}', expected YYYY-MM-DD")


async def holiday_dates(start: date, end: date) -> set:
    """Public holidays in the range, from the app's existing Holiday module.

    Reused rather than duplicated — the HRMS should not maintain a second calendar that can
    disagree with the one the rest of the app already shows.
    """
    docs = await get_collection("holidays").find({
        "holiday_date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
        "status": {"$ne": "inactive"},
    }).to_list(400)
    return {d.get("holiday_date") for d in docs if d.get("holiday_date")}


async def count_leave_days(start: date, end: date, is_half_day: bool,
                           leave_settings: dict) -> float:
    """How many days a request actually consumes.

    Weekly offs and public holidays are skipped when configured, so a Friday-to-Monday request
    consumes two days, not four.
    """
    if end < start:
        raise ValueError("End date cannot be before the start date")

    if is_half_day:
        if start != end:
            # Half of a multi-day range is ambiguous — which day is the half? — so it's rejected
            # rather than guessed at.
            raise ValueError("A half day applies to a single date only")
        return 0.5

    offs = set()
    if leave_settings.get("exclude_weekly_offs"):
        attendance = await get_attendance_settings()
        offs = set(attendance.get("weekly_offs") or [])

    holidays = await holiday_dates(start, end) if leave_settings.get("exclude_holidays") else set()

    days = 0
    cursor = start
    while cursor <= end:
        if cursor.weekday() not in offs and cursor.isoformat() not in holidays:
            days += 1
        cursor += timedelta(days=1)
    return float(days)


# ─── Balances ───────────────────────────────────────────────────────────────────
async def get_balance(user_id: str, year: int, leave_type: str,
                      leave_settings: dict) -> dict:
    """Entitlement / used / remaining for one type in one year.

    Read-through: a missing row means "nothing used yet", so a balance is never created merely
    by looking at it.
    """
    doc = await get_collection(COL_LEAVE_BALANCES).find_one(
        {"user_id": user_id, "year": year, "leave_type": leave_type})
    type_def = find_leave_type(leave_settings, leave_type) or {}
    entitled = float(doc.get("entitled") if doc and doc.get("entitled") is not None
                     else type_def.get("annual_quota") or 0)
    used = float(doc.get("used") or 0) if doc else 0.0
    return {
        "leaveType": leave_type,
        "name": type_def.get("name") or leave_type,
        "paid": bool(type_def.get("paid", True)),
        "entitled": entitled,
        "used": used,
        "remaining": round(entitled - used, 2),
    }


async def all_balances(user_id: str, year: int, leave_settings: dict) -> list:
    return [await get_balance(user_id, year, t["code"], leave_settings)
            for t in leave_settings.get("types", []) if t.get("active", True)]


async def adjust_balance(user_id: str, year: int, leave_type: str, delta: float) -> None:
    """Move the used-days counter. `$inc` so two approvals landing together can't overwrite
    each other's total."""
    await get_collection(COL_LEAVE_BALANCES).update_one(
        {"user_id": user_id, "year": year, "leave_type": leave_type},
        {
            "$inc": {"used": delta},
            "$set": {"updated_at": datetime.now(timezone.utc)},
            "$setOnInsert": {
                "user_id": user_id, "year": year, "leave_type": leave_type,
                "created_at": datetime.now(timezone.utc),
            },
        },
        upsert=True,
    )


# ─── Overlap ────────────────────────────────────────────────────────────────────
async def find_overlap(user_id: str, start: date, end: date,
                       exclude_id: Optional[str] = None) -> Optional[dict]:
    """An existing pending/approved request covering any of these dates.

    Without this a person can book the same day twice and draw the balance down twice.
    """
    query = {
        "user_id": user_id,
        "status": {"$in": [LEAVE_PENDING, LEAVE_APPROVED]},
        "start_date": {"$lte": end.isoformat()},
        "end_date": {"$gte": start.isoformat()},
    }
    if exclude_id:
        query["_id"] = {"$ne": ObjectId(exclude_id)}
    return await get_collection(COL_LEAVES).find_one(query)


# ─── Approver routing ───────────────────────────────────────────────────────────
async def resolve_approver(user_id: str) -> Optional[str]:
    """The applicant's reporting manager, if they have one.

    Reuses the `reporting_manager` already on the user profile, so the leave chain and the task
    chain can never disagree. No manager means it falls to whoever holds the leave permission.
    """
    try:
        doc = await get_collection("staff").find_one(
            {"_id": ObjectId(user_id)}, {"reporting_manager": 1})
    except Exception:
        return None
    manager = str((doc or {}).get("reporting_manager") or "").strip()
    return manager or None


def serialize_leave(doc: dict, applicant: Optional[dict] = None) -> dict:
    return {
        "id": str(doc.get("_id")),
        "userId": doc.get("user_id"),
        "applicantName": (applicant or {}).get("full_name") or doc.get("applicant_name") or "",
        "leaveType": doc.get("leave_type"),
        "leaveTypeName": doc.get("leave_type_name") or doc.get("leave_type"),
        "paid": bool(doc.get("paid", True)),
        "startDate": doc.get("start_date"),
        "endDate": doc.get("end_date"),
        "isHalfDay": bool(doc.get("is_half_day")),
        "days": float(doc.get("days") or 0),
        "reason": doc.get("reason") or "",
        "status": doc.get("status") or LEAVE_PENDING,
        "approverId": doc.get("approver_id") or "",
        "approverName": doc.get("approver_name") or "",
        "decidedAt": doc.get("decided_at"),
        "remark": doc.get("remark") or "",
        "createdAt": doc.get("created_at"),
    }
