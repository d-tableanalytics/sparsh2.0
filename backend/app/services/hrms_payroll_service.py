"""Payroll adapter and run persistence.

Splits cleanly in two:
  * `hrms_payroll_rules` is the pure engine — no I/O, fully unit-testable.
  * this module reads Mongo, shapes the engine's inputs, and stores the result.

Three rules the reference project breaks, held to here:
  1. **A run is persisted.** The reference computes on the fly and stores nothing, so last
     month's payslip can silently change if the underlying data or policy does.
  2. **Nothing is written on a read.** Its payroll `GET` mutates the leave ledger; here only
     `run_payroll` writes, and only to the run and payslip collections.
  3. **A locked run is immutable.** Re-running a locked period is refused rather than quietly
     overwriting what people were already paid against.
"""
import calendar
import logging
from datetime import datetime, date, timezone
from typing import Optional

from bson import ObjectId

from app.db.mongodb import get_collection
from app.models.hrms import (
    COL_ATTENDANCE, COL_LEAVES, COL_LEAVE_BALANCES, COL_EMPLOYEES,
    COL_PAYROLL_RUNS, COL_PAYSLIPS, SETTING_PAYROLL,
    EXITED_STATUSES, LEAVE_APPROVED, LEAVE_REJECTED,
)
from app.services.hrms_payroll_rules import (
    PayrollConfig, PunchSegment, DayRecord, LeaveDay, EmployeeMonth, compute_payroll,
    LEAVE_PAID, LEAVE_UNPAID, LEAVE_REJECTED as KIND_REJECTED,
)
from app.services.hrms_leave_service import get_leave_settings, find_leave_type

logger = logging.getLogger(__name__)

RUN_DRAFT = "draft"
RUN_LOCKED = "locked"


# ─── Config ─────────────────────────────────────────────────────────────────────
async def get_payroll_config() -> PayrollConfig:
    """Policy, seeded from the dataclass defaults and overridable in settings."""
    doc = await get_collection("system_settings").find_one({"setting_name": SETTING_PAYROLL})
    cfg = PayrollConfig()
    if doc:
        for key in cfg.to_dict():
            if doc.get(key) is not None:
                setattr(cfg, key, doc[key])
    return cfg


def validate_payroll_config(updates: dict) -> dict:
    """Every value that reaches the salary maths is bounded here.

    The reference stores these unvalidated and a bad value NaN-poisons the whole run.
    """
    numeric_bounds = {
        "salary_base_days": (0, 31),
        "shift_start": (0, 1439),
        "shift_end": (0, 1439),
        "working_hours_per_day": (1, 24),
        "late_flat_fine_after": (0, 1439),
        "late_flat_fine_amount": (0, 100000),
        "late_hour_penalty_after": (0, 1439),
        "late_hour_penalty_hours": (0, 24),
        "ot_eligible_from": (0, 1439),
        "ot_min_minutes": (1, 1440),
        "ot_multiplier": (0, 10),
        "unauthorized_leave_penalty_days": (0, 31),
        "paid_leaves_per_year": (0, 365),
        "max_monthly_leaves_before_sunday_loss": (0, 31),
        "professional_tax": (0, 100000),
    }
    clean = {}
    for key, value in updates.items():
        if value is None or key not in numeric_bounds:
            continue
        low, high = numeric_bounds[key]
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
        if num != num or num in (float("inf"), float("-inf")):
            raise ValueError(f"{key} must be a finite number")
        if not low <= num <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
        clean[key] = int(num) if float(num).is_integer() and key not in (
            "ot_multiplier", "late_hour_penalty_hours",
            "unauthorized_leave_penalty_days", "paid_leaves_per_year",
            "max_monthly_leaves_before_sunday_loss",
        ) else num
    if not clean:
        raise ValueError("No valid payroll settings to update")
    return clean


# ─── Input shaping ──────────────────────────────────────────────────────────────
def _minutes_from_iso(value: str) -> Optional[int]:
    """Minutes since local midnight from a stored ISO timestamp."""
    try:
        dt = datetime.fromisoformat(value)
        return dt.hour * 60 + dt.minute
    except Exception:
        return None


def _day_records(attendance_docs: list, year: int, month: int) -> list:
    days = []
    for doc in attendance_docs:
        iso = doc.get("punch_date")
        if not iso:
            continue
        try:
            y, m, d = (int(p) for p in iso.split("-"))
            weekday = date(y, m, d).weekday()
        except Exception:
            continue
        segments = []
        for s in doc.get("segments", []):
            start = _minutes_from_iso(s.get("in")) if s.get("in") else None
            if start is None:
                continue
            end = _minutes_from_iso(s.get("out")) if s.get("out") else None
            segments.append(PunchSegment(start=start, end=end))
        days.append(DayRecord(date=iso, weekday=weekday, segments=segments))
    return days


def _leave_days(leave_docs: list, leave_settings: dict, year: int, month: int) -> list:
    """Expand leave requests into per-date rows the engine can classify.

    The KIND comes from the leave type's `paid` FLAG, never from its name — the reference
    classifies by substring and so mis-prices "Sick" and "Earned".
    """
    prefix = f"{year:04d}-{month:02d}"
    out = []
    for doc in leave_docs:
        status = doc.get("status")
        if status == LEAVE_APPROVED:
            type_def = find_leave_type(leave_settings, doc.get("leave_type")) or {}
            kind = LEAVE_PAID if type_def.get("paid", doc.get("paid", True)) else LEAVE_UNPAID
        elif status == LEAVE_REJECTED:
            # A rejected request that the person then didn't work is an unauthorized absence.
            # The engine waives the penalty if they actually turned up.
            kind = KIND_REJECTED
        else:
            continue    # pending / cancelled affect nothing

        try:
            start = date.fromisoformat(doc["start_date"])
            end = date.fromisoformat(doc["end_date"])
        except Exception:
            continue

        half = bool(doc.get("is_half_day"))
        cursor = start
        while cursor <= end:
            iso = cursor.isoformat()
            if iso.startswith(prefix):
                out.append(LeaveDay(date=iso, kind=kind, half=half))
            cursor = date.fromordinal(cursor.toordinal() + 1)
    return out


async def _holidays_in_month(year: int, month: int) -> list:
    """From the app's EXISTING Holiday module — not a second HRMS calendar."""
    prefix = f"{year:04d}-{month:02d}"
    docs = await get_collection("holidays").find({
        "holiday_date": {"$regex": f"^{prefix}"},
        "status": {"$ne": "inactive"},
    }).to_list(60)
    return [d["holiday_date"] for d in docs if d.get("holiday_date")]


def _day_in_month(iso: Optional[str], year: int, month: int) -> Optional[int]:
    """Day-of-month if the date falls inside this run's month, else None.

    Used for join/exit proration: a join last year doesn't prorate this month.
    """
    if not iso:
        return None
    try:
        d = date.fromisoformat(str(iso)[:10])
    except Exception:
        return None
    return d.day if (d.year == year and d.month == month) else None


# ─── Run ────────────────────────────────────────────────────────────────────────
async def compute_for_employee(emp: dict, year: int, month: int, cfg: PayrollConfig,
                               leave_settings: dict, holidays: list) -> dict:
    """One employee's payslip figures. Reads only; the engine does the arithmetic."""
    user_id = emp.get("user_id") or ""
    days_in_month = calendar.monthrange(year, month)[1]
    prefix = f"{year:04d}-{month:02d}"

    attendance_docs, leave_docs = [], []
    if user_id:
        attendance_docs = await get_collection(COL_ATTENDANCE).find({
            "user_id": user_id, "punch_date": {"$regex": f"^{prefix}"}}).to_list(62)
        leave_docs = await get_collection(COL_LEAVES).find({
            "user_id": user_id,
            "status": {"$in": [LEAVE_APPROVED, LEAVE_REJECTED]},
            "start_date": {"$lte": f"{prefix}-31"},
            "end_date": {"$gte": f"{prefix}-01"},
        }).to_list(200)

    # Remaining paid-leave allowance for the year, so the engine can overflow past it.
    balance_left = float(cfg.paid_leaves_per_year)
    if user_id:
        used = 0.0
        async for b in get_collection(COL_LEAVE_BALANCES).find({"user_id": user_id, "year": year}):
            used += float(b.get("used") or 0)
        balance_left = max(0.0, float(cfg.paid_leaves_per_year) - used)

    monthly = float(emp.get("ctc_annual") or 0) / 12.0

    month_input = EmployeeMonth(
        year=year, month=month, days_in_month=days_in_month,
        monthly_salary=monthly,
        days=_day_records(attendance_docs, year, month),
        leaves=_leave_days(leave_docs, leave_settings, year, month),
        holidays=holidays,
        paid_leave_balance=balance_left,
        joined_on_day=_day_in_month(emp.get("date_of_joining"), year, month),
        left_on_day=_day_in_month(emp.get("exit_date"), year, month),
    )

    result = compute_payroll(month_input, cfg)
    result.update({
        "employeeCode": emp.get("employee_code"),
        "userId": user_id,
        "fullName": emp.get("full_name"),
        "department": emp.get("department") or "",
        "designation": emp.get("designation") or "",
        # Surfaced rather than hidden: an employee with no CTC produces a zero payslip, and HR
        # should see that as a data gap, not as a salary.
        "missingSalary": monthly <= 0,
        "missingLogin": not user_id,
    })
    return result


async def run_payroll(year: int, month: int, actor: dict) -> dict:
    """Compute and STORE a draft run for the period. Idempotent: re-running replaces the draft.

    Refuses to touch a locked period — those figures are what people were paid against.
    """
    runs = get_collection(COL_PAYROLL_RUNS)
    existing = await runs.find_one({"year": year, "month": month})
    if existing and existing.get("status") == RUN_LOCKED:
        raise ValueError(f"Payroll for {year}-{month:02d} is locked and cannot be re-run.")

    cfg = await get_payroll_config()
    leave_settings = await get_leave_settings()
    holidays = await _holidays_in_month(year, month)

    employees = await get_collection(COL_EMPLOYEES).find({
        "status": {"$nin": EXITED_STATUSES}}).to_list(5000)
    # An employee who left mid-month is still owed the part they worked, so include exits
    # dated inside this month.
    exited = await get_collection(COL_EMPLOYEES).find({
        "status": {"$in": EXITED_STATUSES},
        "exit_date": {"$regex": f"^{year:04d}-{month:02d}"},
    }).to_list(1000)
    employees.extend(exited)

    payslips = []
    for emp in employees:
        try:
            payslips.append(await compute_for_employee(emp, year, month, cfg, leave_settings, holidays))
        except Exception as e:
            logger.error("Payroll failed for %s: %s", emp.get("employee_code"), e)

    totals = {
        "headcount": len(payslips),
        "gross": round(sum(p["totalEarnings"] for p in payslips), 2),
        "deductions": round(sum(p["totalDeductions"] for p in payslips), 2),
        "net": round(sum(p["netSalary"] for p in payslips), 2),
        "missingSalary": sum(1 for p in payslips if p["missingSalary"]),
        "missingLogin": sum(1 for p in payslips if p["missingLogin"]),
    }

    now = datetime.now(timezone.utc)
    run_doc = {
        "year": year, "month": month,
        "status": RUN_DRAFT,
        "totals": totals,
        # The exact policy used, stored WITH the run — so a payslip can always be explained
        # even after someone edits the live settings.
        "config": cfg.to_dict(),
        "computed_by": str(actor.get("_id")),
        "computed_by_name": actor.get("full_name") or actor.get("email"),
        "computed_at": now,
        "updated_at": now,
    }
    await runs.update_one({"year": year, "month": month},
                          {"$set": run_doc, "$setOnInsert": {"created_at": now}}, upsert=True)
    run = await runs.find_one({"year": year, "month": month})
    run_id = str(run["_id"])

    # Replace this run's payslips wholesale — a recompute must not leave stale rows for an
    # employee who has since been removed from the period.
    slips = get_collection(COL_PAYSLIPS)
    await slips.delete_many({"run_id": run_id})
    if payslips:
        await slips.insert_many([{**p, "run_id": run_id, "year": year, "month": month,
                                  "created_at": now} for p in payslips])

    return {"run": serialize_run(run), "payslips": payslips}


def serialize_run(doc: dict) -> dict:
    if not doc:
        return {}
    return {
        "id": str(doc.get("_id")),
        "year": doc.get("year"),
        "month": doc.get("month"),
        "status": doc.get("status") or RUN_DRAFT,
        "totals": doc.get("totals") or {},
        "config": doc.get("config") or {},
        "computedBy": doc.get("computed_by_name") or "",
        "computedAt": doc.get("computed_at"),
        "lockedBy": doc.get("locked_by_name") or "",
        "lockedAt": doc.get("locked_at"),
    }


def serialize_payslip(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k not in ("_id", "run_id", "created_at")}
    out["id"] = str(doc.get("_id"))
    out["runId"] = doc.get("run_id")
    return out
