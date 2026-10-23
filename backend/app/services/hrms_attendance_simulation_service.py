"""HRMS ▸ Attendance ▸ rule simulation (Phase 1 FRD §23, §25, §29, §30).

§23: "HR should be able to create a new policy version, **test it** and activate it from a
future effective date without changing prior-period attendance."
§25: "Simulation — test formula against sample employees/periods before activation" and
"Comparison — show old result versus proposed new rule during simulation."

Payroll already had this for a salary component (`simulate_component`). Attendance had
nothing, so the only way to find out what a new grace or half-day rule did was to activate
it and look — on live data, for everybody, with a closed month one mistake away.

── How it works ────────────────────────────────────────────────────────────────────────
Re-judge days that have ALREADY BEEN RECORDED, from their stored punches, under the draft
rules. Two passes over the same days: one with the rules in force, one with the draft, then
the differences.

Using recorded days rather than synthetic ones is the point. "What would this rule have
done to last month" is a question about real arrivals and real departures; invented punches
would answer a question nobody asked.

── What it does not do ─────────────────────────────────────────────────────────────────
It writes NOTHING. Not the simulated days, not a flag on the real ones. A simulation that
touched the data it simulates would be an activation with extra steps.

It also does not re-judge leave, holidays, weekly offs or OD. Those days are decided by
somebody's approval, not by the timing rules, and showing them as "unchanged" in a
comparison of timing rules would pad the result with rows that could never move.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    COLL_ATTENDANCE, COLL_EMPLOYEE_PROFILES, POLICY_ATT_DAY, compute_daily_status,
)

# Days whose status somebody DECIDED. Timing rules cannot move them, so they are excluded
# rather than reported as unchanged.
DECIDED_STATUSES = {"On Leave", "On OD", "Holiday", "Weekly Off"}
MAX_SAMPLE_EMPLOYEES = 50
MAX_SAMPLE_DAYS = 2000


def _period_bounds(period: str) -> tuple:
    if len(str(period or "")) != 7 or str(period)[4] != "-":
        raise HTTPException(status_code=422, detail="Period must be YYYY-MM.")
    return f"{period}-01", f"{period}-31"


def _judge(day: dict, rules: dict) -> dict:
    """One recorded day under one rule set. Pure: the punches and the schedule come off the
    stored row, so both passes are judged against exactly the same inputs."""
    return compute_daily_status(
        scheduled_in=day.get("scheduled_in") or rules.get("shift_start") or "09:30",
        scheduled_out=day.get("scheduled_out") or rules.get("shift_end") or "18:30",
        actual_in=day.get("actual_in"), actual_out=day.get("actual_out"),
        daily_grace_minutes=int(rules.get("daily_grace_minutes") or 0),
        half_day_threshold_minutes=int(rules.get("half_day_threshold_minutes") or 240),
        early_going_grace_minutes=int(rules.get("early_going_grace_minutes") or 0),
        break_minutes=int(rules.get("break_minutes") or 0),
        min_hours=rules.get("min_hours"),
        absent_threshold_minutes=rules.get("absent_threshold_minutes"),
        half_day_fraction=rules.get("half_day_fraction", 0.5),
        half_day_late_minutes=rules.get("half_day_late_minutes"),
        half_day_early_minutes=rules.get("half_day_early_minutes"),
        absent_on_no_out_punch=bool(rules.get("absent_on_no_out_punch")),
    )


async def simulate_day_policy(company_id: str, period: str, *, version_no: int,
                              employee_codes: Optional[list] = None,
                              policy_code: str = POLICY_ATT_DAY) -> dict:
    """What a DRAFT ATT_DAY version would have done to a month already recorded.

    Returns per-employee totals and the days that actually move, plus a headline count. The
    changed days are capped in the caller's UI, not here: an administrator who has just
    written a rule that moves 900 days needs to see that it moves 900 days.
    """
    from app.services import hrms_policy_version_service as PV
    from app.services.hrms_attendance_service import get_shift_policy
    from app.services.hrms_shift_service import resolve_rules as shift_rules

    draft = await PV._require_version(company_id, policy_code, int(version_no))
    draft_rules = draft.get("rules") or {}

    start, end = _period_bounds(period)
    query = {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end}}
    if employee_codes:
        query["employee_code"] = {"$in": list(employee_codes)[:MAX_SAMPLE_EMPLOYEES]}
    days = await get_collection(COLL_ATTENDANCE).find(query).to_list(MAX_SAMPLE_DAYS)
    days = [d for d in days if d.get("status") not in DECIDED_STATUSES and d.get("actual_in")]
    if not days:
        return {"policy_code": policy_code, "version_no": int(version_no), "period": period,
                "days_examined": 0, "days_changed": 0, "employees": [], "changes": [],
                "note": "No recorded working days with punches in this period to test against."}

    company_policy = await get_shift_policy(company_id)
    profiles = {p["employee_code"]: p for p in await get_collection(
        COLL_EMPLOYEE_PROFILES).find({"company_id": str(company_id)}).to_list(5000)}

    # The rules each employee is on TODAY, cached per employee: within one simulation every
    # day of the month resolves the same shift, and re-reading it per day turns a 30-day
    # month for 50 people into 1,500 lookups to answer 50 questions.
    current_cache: dict = {}
    changes, by_employee = [], {}

    for day in sorted(days, key=lambda d: (d.get("employee_code") or "", d.get("work_date") or "")):
        code = day.get("employee_code")
        profile = profiles.get(code) or {}
        if code not in current_cache:
            current_cache[code] = await shift_rules(
                company_id, profile, day.get("work_date") or start, policy=company_policy)
        base = {**company_policy,
                **{k: v for k, v in current_cache[code].items() if v is not None}}
        # The version in force today for this employee, so the comparison is against what
        # is actually happening rather than against the company default.
        live = await PV.resolve_rules(company_id, policy_code, profile,
                                      day.get("work_date"), default=base)
        proposed = {**base, **{k: v for k, v in draft_rules.items() if v is not None}}

        was, now = _judge(day, live), _judge(day, proposed)
        totals = by_employee.setdefault(code, {
            "employee_code": code, "days": 0, "days_changed": 0,
            "payable_was": 0.0, "payable_now": 0.0,
            "late_minutes_was": 0, "late_minutes_now": 0})
        totals["days"] += 1
        totals["payable_was"] += was["payable_day"]
        totals["payable_now"] += now["payable_day"]
        totals["late_minutes_was"] += was["late_minutes"]
        totals["late_minutes_now"] += now["late_minutes"]

        if (was["status"], was["payable_day"], was["late_minutes"]) == \
           (now["status"], now["payable_day"], now["late_minutes"]):
            continue
        totals["days_changed"] += 1
        changes.append({
            "employee_code": code, "work_date": day.get("work_date"),
            "actual_in": day.get("actual_in"), "actual_out": day.get("actual_out"),
            "was": {"status": was["status"], "payable_day": was["payable_day"],
                    "late_minutes": was["late_minutes"]},
            "now": {"status": now["status"], "payable_day": now["payable_day"],
                    "late_minutes": now["late_minutes"],
                    "reason": now.get("half_day_reason")},
        })

    for row in by_employee.values():
        row["payable_was"] = round(row["payable_was"], 2)
        row["payable_now"] = round(row["payable_now"], 2)
        row["payable_delta"] = round(row["payable_now"] - row["payable_was"], 2)

    employees = sorted(by_employee.values(), key=lambda r: (-abs(r["payable_delta"]),
                                                            r["employee_code"]))
    return {
        "policy_code": policy_code, "version_no": int(version_no), "period": period,
        "status": draft.get("status"),
        "days_examined": len(days), "days_changed": len(changes),
        "employees_affected": sum(1 for r in employees if r["days_changed"]),
        "payable_days_delta": round(sum(r["payable_delta"] for r in employees), 2),
        "employees": employees, "changes": changes,
        "simulated_at": datetime.now(timezone.utc),
    }
