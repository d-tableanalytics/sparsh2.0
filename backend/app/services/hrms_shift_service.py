"""HRMS > Attendance > shift master and the per-employee calendar (Phase 1 FRD §5, §23, §26).

Until this module attendance had ONE company-wide shift policy. The FRD asks for:

  * a SHIFT MASTER -- code, name, start/end, break, minimum hours, grace, late / early /
    half-day / absent thresholds, monthly buffer, weekly-off pattern;
  * VERSIONED rules -- "grace changed from 5 to 10 minutes from a future date". Every edit
    appends a version with its own effective date; a day is always judged by the version
    in force ON that day, so a change never rewrites a closed period (FRD §23, §26, §30);
  * APPLICABILITY with a documented priority -- which shift a person works is resolved:
        1. the shift set on the employee (Employee Master > Work setup)
        2. the most specific active shift whose applicability matches the employee
           (attendance policy group / location / category / grade / department);
           more matching rules = more specific; ties go to the lower code
        3. the company shift policy (the pre-existing single policy), unchanged
  * the employee's WEEKLY OFF (employee pattern > shift pattern > company default) and
    HOLIDAY calendar (company holidays, optionally scoped by calendar / location).

Weekly-off patterns are a list of weekday names, optionally with a week-of-month suffix:
"Sunday" = every Sunday, "Saturday#2" = the 2nd Saturday of the month.
"""
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    COLL_EMPLOYEE_PROFILES, COLL_HOLIDAYS, COLL_SETTINGS, COLL_SHIFTS, DEFAULT_SHIFT_POLICY,
    WEEKDAYS,
)
from app.services.hrms_audit_service import audit

ENTITY_SHIFT = "shift"
AUDIT_SHIFT_SAVED = "shift saved"
DEFAULT_WEEKLY_OFF = ["Sunday"]

# The rule parameters a version carries, with the company-policy key they fall back to.
SHIFT_PARAMS = {
    "start": "shift_start",
    "end": "shift_end",
    "break_minutes": None,
    "min_hours": None,
    "daily_grace_minutes": "daily_grace_minutes",
    "early_going_grace_minutes": None,
    "half_day_threshold_minutes": "half_day_threshold_minutes",
    "absent_threshold_minutes": None,
    "monthly_buffer_minutes": "monthly_buffer_minutes",
    "flexible": None,
    "weekly_off_pattern": None,
}
APPLICABILITY_KEYS = ("attendance_policy_groups", "locations", "employee_categories",
                      "grades", "department_ids")
_PROFILE_KEY = {"attendance_policy_groups": "attendance_policy_group",
                "locations": "work_location", "employee_categories": "employee_category",
                "grades": "grade", "department_ids": "department_id"}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _hhmm(value, label: str) -> str:
    from app.services.hrms_attendance_rules_service import _hhmm as parse
    return parse(value, label)


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _validate_pattern(pattern) -> list:
    out = []
    for item in pattern or []:
        text = str(item or "").strip()
        if not text:
            continue
        day, _, nth = text.partition("#")
        day = day.strip().capitalize()
        if day not in WEEKDAYS:
            raise HTTPException(status_code=422, detail=f"'{text}' is not a weekday.")
        if nth:
            if nth not in {"1", "2", "3", "4", "5"}:
                raise HTTPException(status_code=422,
                                    detail=f"'{text}': the week of the month must be 1-5.")
            out.append(f"{day}#{nth}")
        else:
            out.append(day)
    return sorted(set(out), key=lambda s: (WEEKDAYS.index(s.split("#")[0]), s))


def _clean_version(payload: dict) -> dict:
    v = {}
    if payload.get("start") is not None:
        v["start"] = _hhmm(payload["start"], "Start time")
    if payload.get("end") is not None:
        v["end"] = _hhmm(payload["end"], "End time")
    for key in ("break_minutes", "daily_grace_minutes", "early_going_grace_minutes",
                "half_day_threshold_minutes", "absent_threshold_minutes",
                "monthly_buffer_minutes"):
        if payload.get(key) is not None:
            try:
                n = int(payload[key])
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"{key} must be whole minutes.")
            if n < 0 or n > 24 * 60:
                raise HTTPException(status_code=422, detail=f"{key} is out of range.")
            v[key] = n
    if payload.get("min_hours") is not None:
        try:
            v["min_hours"] = round(float(payload["min_hours"]), 2)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Minimum hours must be a number.")
        if not 0 <= v["min_hours"] <= 24:
            raise HTTPException(status_code=422, detail="Minimum hours must be 0-24.")
    if payload.get("flexible") is not None:
        v["flexible"] = bool(payload["flexible"])
    if payload.get("weekly_off_pattern") is not None:
        v["weekly_off_pattern"] = _validate_pattern(payload["weekly_off_pattern"])
    return v


# ─────────────────────────────────────────────────────────────
# Shift master
# ─────────────────────────────────────────────────────────────
async def list_shifts(company_id: str) -> list:
    rows = await get_collection(COLL_SHIFTS).find(
        {"company_id": str(company_id)}).sort("code", 1).to_list(200)
    today = _today()
    out = []
    for r in rows:
        r = _out(r)
        r["current"] = version_on(r, today)
        upcoming = [v for v in r.get("versions") or [] if v["effective_from"] > today]
        r["upcoming"] = upcoming
        out.append(r)
    return out


async def get_shift(company_id: str, code: str) -> Optional[dict]:
    if not code:
        return None
    doc = await get_collection(COLL_SHIFTS).find_one(
        {"company_id": str(company_id), "code": str(code).strip().upper()})
    return _out(doc) if doc else None


def version_on(shift: dict, work_date: str) -> Optional[dict]:
    """The version in force on `work_date`: the latest one effective on or before it."""
    versions = sorted(shift.get("versions") or [], key=lambda v: v["effective_from"])
    current = None
    for v in versions:
        if v["effective_from"] <= work_date:
            current = v
    return current


async def save_shift(actor: dict, company_id: str, payload: dict) -> dict:
    code = str(payload.get("code") or "").strip().upper()
    if not code or len(code) > 20:
        raise HTTPException(status_code=422, detail="A shift code (up to 20 characters) is required.")
    name = str(payload.get("name") or "").strip()[:80]
    effective_from = str(payload.get("effective_from") or _today())[:10]
    from app.models.hrms import is_iso_date
    if not is_iso_date(effective_from):
        raise HTTPException(status_code=422, detail="Effective from must be YYYY-MM-DD.")
    # FRD §26: a retroactive change is an explicit, reasoned act, and never reaches into a
    # CLOSED period. A back-dated version is allowed only when its month is not locked and a
    # reason is given; locked months stay as judged (their rows cannot be re-marked anyway),
    # and days already recorded keep their values until somebody re-marks them.
    if effective_from < _today():
        from app.models.hrms import COLL_ATTENDANCE_LOCKS
        lock = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
            {"company_id": str(company_id), "period": effective_from[:7], "status": "Locked"})
        if lock:
            raise HTTPException(
                status_code=422,
                detail=f"Attendance for {effective_from[:7]} is locked, so a shift change cannot "
                       f"start inside it. Choose a date in an open month.")
        if not (payload.get("reason") or "").strip():
            raise HTTPException(
                status_code=422,
                detail="A back-dated shift change needs a reason. Days already recorded keep "
                       "their values until they are re-marked or regularised.")

    coll = get_collection(COLL_SHIFTS)
    current = await coll.find_one({"company_id": str(company_id), "code": code})
    params = _clean_version(payload)
    base = version_on(current, effective_from) if current else None
    merged = {**(base or {}), **params}
    merged.pop("effective_from", None)
    for required, label in (("start", "Start time"), ("end", "End time")):
        if not merged.get(required):
            raise HTTPException(status_code=422, detail=f"{label} is required.")
    if merged["end"] <= merged["start"]:
        raise HTTPException(status_code=422, detail="The end time must be after the start time.")
    merged.setdefault("break_minutes", 0)
    merged.setdefault("daily_grace_minutes", DEFAULT_SHIFT_POLICY["daily_grace_minutes"])
    merged.setdefault("half_day_threshold_minutes",
                      DEFAULT_SHIFT_POLICY["half_day_threshold_minutes"])
    merged.setdefault("monthly_buffer_minutes", DEFAULT_SHIFT_POLICY["monthly_buffer_minutes"])
    version = {**merged, "effective_from": effective_from,
               "created_by": str((actor or {}).get("_id") or ""),
               "created_at": datetime.now(timezone.utc),
               "reason": (payload.get("reason") or "").strip()[:300] or None}

    applicability = {}
    for key in APPLICABILITY_KEYS:
        values = (payload.get("applicability") or {}).get(key)
        if values:
            applicability[key] = [str(v).strip() for v in values if str(v).strip()]

    now = datetime.now(timezone.utc)
    if current:
        versions = [v for v in current.get("versions") or []
                    if v["effective_from"] != effective_from]
        versions.append(version)
        versions.sort(key=lambda v: v["effective_from"])
        updates = {"versions": versions, "updated_at": now}
        if name:
            updates["name"] = name
        if "applicability" in payload:
            updates["applicability"] = applicability
        if payload.get("active") is not None:
            updates["active"] = bool(payload["active"])
        await coll.update_one({"_id": current["_id"]}, {"$set": updates})
    else:
        await coll.insert_one({
            "company_id": str(company_id), "code": code, "name": name or code,
            "active": payload.get("active", True) is not False,
            "applicability": applicability, "versions": [version],
            "created_at": now, "updated_at": now,
        })
    await audit(actor, AUDIT_SHIFT_SAVED, ENTITY_SHIFT, code,
                f"version from {effective_from}", company_id)
    return await get_shift(company_id, code)


# ─────────────────────────────────────────────────────────────
# Resolution: which rules judge this person on this day
# ─────────────────────────────────────────────────────────────
async def _company_policy(company_id: str) -> dict:
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    return {**DEFAULT_SHIFT_POLICY, **((doc or {}).get("shift_policy") or {})}


def _specificity(shift: dict, profile: dict) -> int:
    """-1 when the shift does not apply to this person; otherwise how many rules matched.

    The scoring is the same "more matched dimensions wins" rule the policy spine uses
    (hrms_policy_version_service.specificity), with ONE deliberate difference kept here: a
    shift carrying no applicability rules scores -1 rather than 0. A shift is something a
    person is PUT ON, so an unscoped one is only ever assigned explicitly -- whereas an
    unscoped POLICY is the company-wide default that applies to everybody. Sharing the
    scoring but not that rule is why this stays its own three lines rather than a call.
    """
    rules = shift.get("applicability") or {}
    if not any(rules.get(k) for k in APPLICABILITY_KEYS):
        return -1          # a shift with no rules is only ever assigned explicitly
    matched = 0
    for key in APPLICABILITY_KEYS:
        allowed = rules.get(key)
        if not allowed:
            continue
        if str(profile.get(_PROFILE_KEY[key]) or "") not in allowed:
            return -1
        matched += 1
    return matched


async def resolve_rules(company_id: str, profile: Optional[dict], work_date: str, *,
                        policy: dict = None, shifts: list = None) -> dict:
    """The full rule set for one person on one day, flattened onto the company-policy keys
    every existing reader already uses, plus where it came from."""
    policy = policy or await _company_policy(company_id)
    rules = {
        "shift_start": policy["shift_start"], "shift_end": policy["shift_end"],
        "daily_grace_minutes": policy["daily_grace_minutes"],
        "half_day_threshold_minutes": policy["half_day_threshold_minutes"],
        "monthly_buffer_minutes": policy.get("monthly_buffer_minutes") or 0,
        "break_minutes": policy.get("break_minutes") or 0,
        "min_hours": policy.get("min_hours"),
        "early_going_grace_minutes": policy.get("early_going_grace_minutes") or 0,
        "absent_threshold_minutes": policy.get("absent_threshold_minutes"),
        "weekly_off_pattern": policy.get("weekly_off_pattern") or DEFAULT_WEEKLY_OFF,
        "flexible": False,
        "shift_code": None, "shift_name": "Company timing", "rule_source": "company policy",
        "shift_version": None,
    }
    profile = profile or {}
    if shifts is None:
        shifts = await list_shifts(company_id)
    chosen = None
    if profile.get("shift_code"):
        chosen = next((s for s in shifts if s["code"] == profile["shift_code"]), None)
        source = "employee shift"
    if not chosen:
        ranked = sorted(((_specificity(s, profile), s) for s in shifts
                         if s.get("active", True)), key=lambda p: (-p[0], p[1]["code"]))
        if ranked and ranked[0][0] >= 0:
            chosen, source = ranked[0][1], "policy applicability"
    if chosen:
        v = version_on(chosen, work_date)
        if v:
            for key, policy_key in SHIFT_PARAMS.items():
                if v.get(key) is None:
                    continue
                rules[policy_key or key] = v[key]
            rules.update({"shift_code": chosen["code"], "shift_name": chosen.get("name"),
                          "rule_source": source, "shift_version": v["effective_from"]})
    if profile.get("weekly_off_pattern"):
        rules["weekly_off_pattern"] = profile["weekly_off_pattern"]
    return rules


def is_weekly_off(pattern: list, work_date: str) -> bool:
    d = date.fromisoformat(work_date)
    name = WEEKDAYS[d.weekday()]
    nth = (d.day - 1) // 7 + 1
    for item in pattern or []:
        day, _, which = item.partition("#")
        if day == name and (not which or int(which) == nth):
            return True
    return False


def _holiday_applies(holiday: dict, profile: dict) -> bool:
    cal = holiday.get("calendar")
    if cal and cal != profile.get("holiday_calendar"):
        return False
    locations = holiday.get("locations") or []
    if locations and profile.get("work_location") not in locations:
        return False
    return True


async def holidays_for(company_id: str, profile: Optional[dict], start: str, end: str) -> dict:
    """{date: holiday name} for the dates in [start, end] that are holidays for this person."""
    rows = await get_collection(COLL_HOLIDAYS).find(
        {"company_id": str(company_id), "holiday_date": {"$gte": start, "$lte": end}}
    ).to_list(400)
    return {str(r["holiday_date"])[:10]: r.get("holiday_name")
            for r in rows if _holiday_applies(r, profile or {})}


async def day_type(company_id: str, profile: Optional[dict], work_date: str,
                   rules: dict = None) -> Optional[str]:
    """'Holiday', 'Weekly Off' or None (a working day) for this person on this date."""
    if work_date in await holidays_for(company_id, profile, work_date, work_date):
        return "Holiday"
    rules = rules or await resolve_rules(company_id, profile, work_date)
    if is_weekly_off(rules.get("weekly_off_pattern") or [], work_date):
        return "Weekly Off"
    return None


async def month_calendar(company_id: str, profile: Optional[dict], period: str) -> dict:
    """Per-day schedule for a month: which days are weekly off / holiday, and the counts
    payroll needs (calendar, weekly-off, holiday, working days)."""
    year, month = (int(x) for x in period.split("-"))
    days = monthrange(year, month)[1]
    start, end = f"{period}-01", f"{period}-{days:02d}"
    hols = await holidays_for(company_id, profile, start, end)
    policy = await _company_policy(company_id)
    shifts = await list_shifts(company_id)
    out = {}
    weekly_offs = holidays = 0
    for d in range(1, days + 1):
        ds = f"{period}-{d:02d}"
        if ds in hols:
            out[ds] = "Holiday"
            holidays += 1
            continue
        rules = await resolve_rules(company_id, profile, ds, policy=policy, shifts=shifts)
        if is_weekly_off(rules.get("weekly_off_pattern") or [], ds):
            out[ds] = "Weekly Off"
            weekly_offs += 1
    return {"days": out, "calendar_days": days, "weekly_off_days": weekly_offs,
            "holiday_days": holidays, "working_days": days - weekly_offs - holidays}


async def profile_for(company_id: str, employee_code: str) -> Optional[dict]:
    return await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
