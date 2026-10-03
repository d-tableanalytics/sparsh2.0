"""HRMS > Attendance > capture/import layer and timing rules (client requirement).

"Biometric login/logout/live-location practice, office timing 9:30-6:30, grace/buffer
references, outdoor duty and flexible-timing approval" -> "Attendance capture/import layer,
OD, regularisation, timing rules and audit."

This module holds the pieces the rest of attendance did not have:

  * EFFECTIVE HOURS -- the hours a day is judged against: an approved flexible timing for
    that date if there is one, otherwise the company's office timing (shift policy). Every
    writer of a day (HR's mark, self check-in, regularisation, biometric import) goes
    through `compute_day`, so a day is never judged against the wrong hours.
  * FLEXIBLE TIMING -- an employee asks for different hours over a date range (e.g. 10:30 to
    19:30); the reporting manager / HR approves (the same decision rule as OD and
    regularisation: never your own). Approving re-judges any day already recorded in range.
  * BIOMETRIC IMPORT -- the machine's export (CSV or Excel). First punch of a day = check-in,
    last = check-out. Never overwrites a locked day, an approved leave / OD / holiday /
    weekly off, or a regularised day; everything skipped is reported with its reason.
  * MONTHLY BUFFER -- each person's late minutes in a month are tolerated up to the
    buffer; the Late Coming view shows what is within it and what is beyond.
"""
import csv
import io
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    COLL_ATTENDANCE, COLL_EMPLOYEE_PROFILES, COLL_PUNCH_SEGMENTS, compute_daily_status,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id

from app.models.hrms import COLL_FLEXI_TIMING as COLL_FLEXI
ENTITY_FLEXI = "flexi_timing"
ENTITY_ATTENDANCE = "attendance"
AUDIT_FLEXI_REQUESTED = "flexible timing requested"
AUDIT_FLEXI_ACTIONED = "flexible timing decided"
AUDIT_BIOMETRIC_IMPORT = "biometric attendance imported"

FLEXI_PENDING, FLEXI_APPROVED, FLEXI_REJECTED, FLEXI_CANCELLED = (
    "Pending", "Approved", "Rejected", "Cancelled")
# Statuses a biometric file must never overwrite: somebody decided these.
PROTECTED_STATUSES = {"On Leave", "On OD", "Holiday", "Weekly Off"}
PROTECTED_SOURCES = {"regularization", "od"}
MAX_IMPORT_ROWS = 20000
MAX_FLEXI_DAYS = 92

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _hhmm(value, label: str) -> str:
    text = str(value or "").strip()
    m = _HHMM.match(text)
    if not m:
        raise HTTPException(status_code=422, detail=f"{label} must be a time like 09:30.")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _iso(value, label: str) -> str:
    try:
        return date.fromisoformat(str(value).strip()[:10]).isoformat()
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a date (YYYY-MM-DD).")


# ─────────────────────────────────────────────────────────────
# Effective hours for one person on one day
# ─────────────────────────────────────────────────────────────
async def effective_hours(company_id: str, employee_code: str, work_date: str,
                          policy: dict = None) -> dict:
    """The shift a day is judged against, and where it came from."""
    if policy is None:
        from app.services.hrms_attendance_service import get_shift_policy
        policy = await get_shift_policy(company_id)
    flexi = await get_collection(COLL_FLEXI).find_one({
        "company_id": str(company_id), "employee_code": employee_code,
        "status": FLEXI_APPROVED, "from_date": {"$lte": work_date},
        "to_date": {"$gte": work_date}})
    if flexi:
        return {"start": flexi["shift_start"], "end": flexi["shift_end"],
                "flexi_no": flexi.get("flexi_no"), "policy": policy}
    return {"start": policy["shift_start"], "end": policy["shift_end"], "flexi_no": None,
            "policy": policy}


async def compute_day(company_id: str, employee_code: str, work_date: str,
                      actual_in: Optional[str], actual_out: Optional[str],
                      policy: dict = None) -> dict:
    """compute_daily_status against the day's EFFECTIVE hours. Adds `flexi_no` when a
    flexible timing decided them."""
    hours = await effective_hours(company_id, employee_code, work_date, policy)
    p = hours["policy"]
    out = compute_daily_status(
        scheduled_in=hours["start"], scheduled_out=hours["end"],
        actual_in=actual_in, actual_out=actual_out,
        daily_grace_minutes=p["daily_grace_minutes"],
        half_day_threshold_minutes=p["half_day_threshold_minutes"])
    out["flexi_no"] = hours["flexi_no"]
    out["scheduled_in"], out["scheduled_out"] = hours["start"], hours["end"]
    return out


# ─────────────────────────────────────────────────────────────
# Flexible timing
# ─────────────────────────────────────────────────────────────
async def request_flexi(actor: dict, company_id: str, payload: dict) -> dict:
    from app.services.hrms_attendance_service import (
        _assert_self_or_privileged, _get_profile, _reporting_manager_id)
    code = str(payload.get("employee_code") or "").strip()
    if not code:
        raise HTTPException(status_code=422, detail="Choose the employee.")
    profile = await _get_profile(company_id, code)
    await _assert_self_or_privileged(actor, company_id, code)
    start_d = _iso(payload.get("from_date"), "From date")
    end_d = _iso(payload.get("to_date") or payload.get("from_date"), "To date")
    if end_d < start_d:
        raise HTTPException(status_code=422, detail="The end date is before the start date.")
    if (date.fromisoformat(end_d) - date.fromisoformat(start_d)).days + 1 > MAX_FLEXI_DAYS:
        raise HTTPException(status_code=422,
                            detail=f"Ask for at most {MAX_FLEXI_DAYS} days at a time.")
    s_in, s_out = _hhmm(payload.get("shift_start"), "Start time"), _hhmm(payload.get("shift_end"), "End time")
    if s_out <= s_in:
        raise HTTPException(status_code=422, detail="The end time must be after the start time.")
    reason = str(payload.get("reason") or "").strip()[:1000]
    if not reason:
        raise HTTPException(status_code=422, detail="Say why the different hours are needed.")
    clash = await get_collection(COLL_FLEXI).find_one({
        "company_id": str(company_id), "employee_code": code,
        "status": {"$in": [FLEXI_PENDING, FLEXI_APPROVED]},
        "from_date": {"$lte": end_d}, "to_date": {"$gte": start_d}}, {"flexi_no": 1})
    if clash:
        raise HTTPException(status_code=409,
                            detail=f"{clash['flexi_no']} already covers some of these dates.")

    now = datetime.now(timezone.utc)
    flexi_no = await next_business_id("flexi", str(company_id), now.year)
    doc = {
        "flexi_no": flexi_no, "company_id": str(company_id), "employee_code": code,
        "employee_name": profile.get("display_name") or profile.get("full_name"),
        "reporting_manager_id": await _reporting_manager_id(profile),
        "from_date": start_d, "to_date": end_d, "shift_start": s_in, "shift_end": s_out,
        "reason": reason, "status": FLEXI_PENDING,
        "requested_by": str(actor.get("_id") or ""), "action_by": None, "action_at": None,
        "remarks": None, "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_FLEXI).insert_one(dict(doc))
    await audit(actor, AUDIT_FLEXI_REQUESTED, ENTITY_FLEXI, flexi_no,
                f"{code} {start_d}..{end_d} {s_in}-{s_out}", company_id)
    doc.pop("_id", None)
    return doc


async def list_flexi(actor: dict, company_id: str, *, status: str = None, limit: int = 200) -> list:
    from app.services.hrms_attendance_service import _scope_query
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_FLEXI).find(query).sort("created_at", -1).to_list(limit)
    for r in rows:
        r.pop("_id", None)
    return rows


async def act_on_flexi(actor: dict, company_id: str, flexi_no: str, payload: dict) -> dict:
    from app.services.hrms_attendance_service import _assert_may_decide
    coll = get_collection(COLL_FLEXI)
    doc = await coll.find_one({"company_id": str(company_id), "flexi_no": flexi_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Flexible timing '{flexi_no}' not found.")
    if doc["status"] != FLEXI_PENDING:
        raise HTTPException(status_code=409, detail=f"{flexi_no} is already \"{doc['status']}\".")
    await _assert_may_decide(actor, company_id, doc["employee_code"], "flexible timing request")
    approved = bool(payload.get("approved"))
    remarks = str(payload.get("remarks") or "").strip()[:1000] or None
    if not approved and not remarks:
        raise HTTPException(status_code=422, detail="Say why it is not approved.")
    now = datetime.now(timezone.utc)
    new_status = FLEXI_APPROVED if approved else FLEXI_REJECTED
    await coll.update_one({"company_id": str(company_id), "flexi_no": flexi_no},
                          {"$set": {"status": new_status, "action_by": str(actor.get("_id") or ""),
                                    "action_at": now, "remarks": remarks, "updated_at": now}})
    rejudged = 0
    if approved:
        rejudged = await _rejudge_range(company_id, doc["employee_code"],
                                        doc["from_date"], doc["to_date"])
    await audit(actor, AUDIT_FLEXI_ACTIONED, ENTITY_FLEXI, flexi_no,
                f"{new_status}; {rejudged} recorded day(s) re-judged", company_id)
    out = await coll.find_one({"company_id": str(company_id), "flexi_no": flexi_no})
    out.pop("_id", None)
    out["rejudged_days"] = rejudged
    return out


async def _rejudge_range(company_id: str, code: str, start_d: str, end_d: str) -> int:
    """Re-judge days already recorded in a range against their (now flexible) hours."""
    rows = await get_collection(COLL_ATTENDANCE).find({
        "company_id": str(company_id), "employee_code": code,
        "work_date": {"$gte": start_d, "$lte": end_d}}).to_list(200)
    n = 0
    for r in rows:
        if r.get("locked") or r.get("status") in PROTECTED_STATUSES or not r.get("actual_in"):
            continue
        c = await compute_day(company_id, code, r["work_date"], r.get("actual_in"), r.get("actual_out"))
        await get_collection(COLL_ATTENDANCE).update_one(
            {"company_id": str(company_id), "employee_code": code, "work_date": r["work_date"]},
            {"$set": {"status": c["status"], "late_minutes": c["late_minutes"],
                      "worked_minutes": c["worked_minutes"], "flexi_no": c["flexi_no"],
                      "updated_at": datetime.now(timezone.utc)}})
        n += 1
    return n


# ─────────────────────────────────────────────────────────────
# Biometric import
# ─────────────────────────────────────────────────────────────
_CODE_COLS = ("employee code", "emp code", "employee id", "emp id", "empcode", "employee_code",
              "code", "card no", "biometric id", "enroll no", "user id")
_DATE_COLS = ("date", "work date", "attendance date", "punch date", "work_date")
_TIME_COLS = ("time", "punch time", "punch", "log time")
_DATETIME_COLS = ("datetime", "date time", "punch datetime", "timestamp", "log date")
_IN_COLS = ("in", "in time", "check in", "first in", "in_time", "actual_in")
_OUT_COLS = ("out", "out time", "check out", "last out", "out_time", "actual_out")


def _norm(h) -> str:
    return re.sub(r"\s+", " ", str(h or "").strip().lower().replace("_", " "))


def _pick(headers: list, names) -> Optional[int]:
    wanted = {_norm(n) for n in names}
    for i, h in enumerate(headers):
        if _norm(h) in wanted:
            return i
    return None


def _parse_date(v) -> Optional[str]:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    text = str(v or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text[:11].strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_time(v) -> Optional[str]:
    if isinstance(v, datetime):
        return v.strftime("%H:%M")
    if hasattr(v, "hour") and hasattr(v, "minute"):
        return f"{v.hour:02d}:{v.minute:02d}"
    text = str(v or "").strip()
    m = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm])?", text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    ap = (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def _parse_datetime(v):
    if isinstance(v, datetime):
        return v.date().isoformat(), v.strftime("%H:%M")
    text = str(v or "").strip()
    return _parse_date(text[:10]) or _parse_date(text.split(" ")[0]), _parse_time(text)


def read_rows(filename: str, raw: bytes) -> list:
    """The file as a list of rows (first row = headers). CSV or Excel."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        return [list(r) for r in wb.active.iter_rows(values_only=True)]
    if name.endswith(".csv") or name.endswith(".txt") or not name:
        text = raw.decode("utf-8-sig", errors="replace")
        return [row for row in csv.reader(io.StringIO(text))]
    raise HTTPException(status_code=415, detail="Upload the biometric export as CSV or Excel (.xlsx).")


def punches_from_rows(rows: list) -> tuple:
    """{(code, date): [times]} plus a list of unreadable rows. Pure."""
    if not rows:
        raise HTTPException(status_code=422, detail="The file is empty.")
    headers = rows[0]
    ci = _pick(headers, _CODE_COLS)
    if ci is None:
        raise HTTPException(
            status_code=422,
            detail="No employee code column found. Name it e.g. \"Employee Code\".")
    di, ti = _pick(headers, _DATE_COLS), _pick(headers, _TIME_COLS)
    dti = _pick(headers, _DATETIME_COLS)
    ii, oi = _pick(headers, _IN_COLS), _pick(headers, _OUT_COLS)
    if dti is None and di is None:
        raise HTTPException(status_code=422,
                            detail="No date column found. Name it \"Date\" (or \"Date Time\").")
    if dti is None and ti is None and ii is None and oi is None:
        raise HTTPException(status_code=422,
                            detail="No time column found. Use \"Time\", or \"In Time\" / \"Out Time\".")
    days, bad = {}, []
    for n, row in enumerate(rows[1:MAX_IMPORT_ROWS + 1], start=2):
        if not row or all(str(c or "").strip() == "" for c in row):
            continue
        cell = lambda i: row[i] if i is not None and i < len(row) else None  # noqa: E731
        code = str(cell(ci) or "").strip()
        if isinstance(cell(ci), float) and float(cell(ci)).is_integer():
            code = str(int(cell(ci)))
        if dti is not None:
            d, t = _parse_datetime(cell(dti))
            times = [t] if t else []
        else:
            d = _parse_date(cell(di))
            times = [x for x in (_parse_time(cell(ti)) if ti is not None else None,
                                 _parse_time(cell(ii)) if ii is not None else None,
                                 _parse_time(cell(oi)) if oi is not None else None) if x]
        if not code or not d or not times:
            bad.append({"row": n, "reason": "missing employee code, date or time"})
            continue
        days.setdefault((code, d), []).extend(times)
    return days, bad


async def import_biometric(actor: dict, company_id: str, filename: str, raw: bytes) -> dict:
    """Load a biometric export. First punch = in, last punch = out."""
    days, bad = punches_from_rows(read_rows(filename, raw))
    profiles = await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id)}, {"employee_code": 1, "biometric_id": 1}).to_list(5000)
    by_code = {}
    for p in profiles:
        if p.get("employee_code"):
            by_code[str(p["employee_code"]).upper()] = p["employee_code"]
        if p.get("biometric_id"):
            by_code[str(p["biometric_id"]).upper()] = p["employee_code"]

    from app.services.hrms_attendance_service import get_shift_policy
    policy = await get_shift_policy(company_id)
    now = datetime.now(timezone.utc)
    report = {"days_created": 0, "days_updated": 0, "skipped": [], "unreadable_rows": bad,
              "unknown_codes": []}
    unknown = set()
    for (raw_code, d), times in sorted(days.items()):
        code = by_code.get(raw_code.upper())
        if not code:
            unknown.add(raw_code)
            continue
        times = sorted(set(times))
        actual_in = times[0]
        actual_out = times[-1] if len(times) > 1 else None
        key = {"company_id": str(company_id), "employee_code": code, "work_date": d}
        existing = await get_collection(COLL_ATTENDANCE).find_one(key) or {}
        if existing.get("locked"):
            report["skipped"].append({"employee_code": code, "work_date": d, "reason": "locked"})
            continue
        if existing.get("status") in PROTECTED_STATUSES or existing.get("source") in PROTECTED_SOURCES:
            report["skipped"].append({"employee_code": code, "work_date": d,
                                      "reason": f"already {existing.get('status') or existing.get('source')}"})
            continue
        c = await compute_day(company_id, code, d, actual_in, actual_out, policy)
        await get_collection(COLL_ATTENDANCE).update_one(
            key,
            {"$set": {**key, "actual_in": actual_in, "actual_out": actual_out,
                      "status": c["status"], "worked_minutes": c["worked_minutes"],
                      "late_minutes": c["late_minutes"], "flexi_no": c["flexi_no"],
                      "source": "biometric", "locked": False, "updated_at": now,
                      "updated_by": str(actor.get("_id") or "")},
             "$setOnInsert": {"created_at": now}},
            upsert=True)
        await get_collection(COLL_PUNCH_SEGMENTS).insert_one({
            **key, "punch_in": actual_in, "punch_out": actual_out, "all_punches": times,
            "source": "biometric", "file": filename, "recorded_by": str(actor.get("_id") or ""),
            "recorded_at": now})
        report["days_updated" if existing else "days_created"] += 1
    report["unknown_codes"] = sorted(unknown)
    await audit(actor, AUDIT_BIOMETRIC_IMPORT, ENTITY_ATTENDANCE, filename or "biometric file",
                f"{report['days_created']} new, {report['days_updated']} updated, "
                f"{len(report['skipped'])} skipped, {len(unknown)} unknown code(s)", company_id)
    return report


# ─────────────────────────────────────────────────────────────
# Monthly buffer
# ─────────────────────────────────────────────────────────────
def monthly_buffer(rows: list, buffer_minutes: int) -> list:
    """Per person per month: late days, late minutes, and how much is within / beyond the
    monthly buffer. Pure."""
    buckets = {}
    for r in rows:
        key = (r["employee_code"], str(r["work_date"])[:7])
        b = buckets.setdefault(key, {"employee_code": key[0], "month": key[1], "late_days": 0,
                                     "late_minutes": 0, "employee_name": r.get("employee_name")})
        b["late_days"] += 1
        b["late_minutes"] += int(r.get("late_minutes") or 0)
    out = []
    for b in buckets.values():
        b["buffer_minutes"] = int(buffer_minutes or 0)
        b["within_buffer"] = min(b["late_minutes"], b["buffer_minutes"])
        b["beyond_buffer"] = max(0, b["late_minutes"] - b["buffer_minutes"])
        out.append(b)
    return sorted(out, key=lambda x: (x["month"], -x["beyond_buffer"], x["employee_code"]), reverse=False)
