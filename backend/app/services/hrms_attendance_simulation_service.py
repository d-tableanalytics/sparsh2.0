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


# ─────────────────────────────────────────────────────────────
# FRD §26 "Draft changes should support preview" -- the two attendance policies that are
# not judged per day. Neither re-judges anything; each says what the draft would have
# decided differently about the period's real requests. Writes nothing.
# ─────────────────────────────────────────────────────────────
def _regularisation_refusals(request: dict, rules: dict, used_before: int) -> list:
    reasons = []
    created = request.get("created_at")
    window = rules.get("window_days")
    if window and isinstance(created, datetime) and request.get("work_date"):
        from datetime import date as _date
        back = (created.date() - _date.fromisoformat(request["work_date"])).days
        if back > int(window):
            reasons.append(f"asked {back} day(s) back; the window is {window}")
    if rules.get("evidence_required") and not str(request.get("evidence") or "").strip() \
            and not request.get("evidence_file"):
        reasons.append("no evidence attached")
    types = rules.get("request_types")
    if types and (request.get("request_type") or "") not in types:
        reasons.append(f"type '{request.get('request_type') or 'none'}' is not allowed")
    cap = rules.get("max_requests_per_month")
    if cap and used_before >= int(cap):
        reasons.append(f"over the monthly cap of {cap}")
    return reasons


async def preview_regularisation_policy(company_id: str, period: str, *, version_no: int,
                                        employee_codes: Optional[list] = None) -> dict:
    from app.models.hrms import (COLL_ATTENDANCE_CORRECTIONS, POLICY_ATT_REGULARISATION)
    from app.services import hrms_policy_version_service as PV
    from app.services.hrms_attendance_service import regularisation_rules
    draft = await PV._require_version(company_id, POLICY_ATT_REGULARISATION, int(version_no))
    start, end = _period_bounds(period)
    live = await regularisation_rules(company_id, on_date=end)
    proposed = {**live, **{k: v for k, v in (draft.get("rules") or {}).items() if v is not None}}
    query = {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end}}
    if employee_codes:
        query["employee_code"] = {"$in": list(employee_codes)[:MAX_SAMPLE_EMPLOYEES]}
    requests = await get_collection(COLL_ATTENDANCE_CORRECTIONS).find(query).to_list(5000)
    requests.sort(key=lambda r: (r.get("employee_code") or "", str(r.get("created_at") or "")))
    used, changes = {}, []
    for r in requests:
        code = r.get("employee_code")
        before = used.get(code, 0)
        was = _regularisation_refusals(r, live, before)
        now = _regularisation_refusals(r, proposed, before)
        used[code] = before + 1
        if bool(was) != bool(now) or was != now:
            changes.append({"employee_code": code, "work_date": r.get("work_date"),
                            "request_no": r.get("req_no"), "was_refused": was,
                            "would_be_refused": now})
    return {"policy_code": POLICY_ATT_REGULARISATION, "version_no": int(version_no),
            "period": period, "requests_examined": len(requests),
            "would_refuse": sum(1 for c in changes if c["would_be_refused"]),
            "would_allow": sum(1 for c in changes if not c["would_be_refused"]),
            "changes": changes,
            "note": "Requests already decided are not reopened; this shows what the draft "
                    "would have refused at the time they were raised.",
            "simulated_at": datetime.now(timezone.utc)}


async def preview_closure_policy(actor: dict, company_id: str, period: str, *,
                                 version_no: int) -> dict:
    from datetime import date as _date
    from app.models.hrms import POLICY_ATT_CLOSURE
    from app.services import hrms_policy_version_service as PV
    from app.services.hrms_attendance_service import closure_rules, closure_dashboard
    draft = await PV._require_version(company_id, POLICY_ATT_CLOSURE, int(version_no))
    start, end = _period_bounds(period)
    live = await closure_rules(company_id, on_date=end)
    proposed = {**live, **{k: v for k, v in (draft.get("rules") or {}).items() if v is not None}}

    def cutoff(rules):
        day = int(rules.get("closing_day") or 0)
        if not rules.get("enforce_cutoff") or not 1 <= day <= 31:
            return None
        y, m = int(period[:4]), int(period[5:7])
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        try:
            return _date(ny, nm, day).isoformat()
        except ValueError:
            return _date(ny, nm, 28).isoformat()

    snapshot = await closure_dashboard(actor, company_id, period)
    pending = sum(int(snapshot.get(k) or 0) for k in
                  ("pending_regularizations", "pending_od", "pending_leaves"))
    side = lambda rules: {"cutoff_date": cutoff(rules),  # noqa: E731
                          "locking_blocked": bool(rules.get("block_pending_requests")) and pending > 0}
    return {"policy_code": POLICY_ATT_CLOSURE, "version_no": int(version_no), "period": period,
            "pending_requests": pending, "was": side(live), "now": side(proposed),
            "simulated_at": datetime.now(timezone.utc)}
