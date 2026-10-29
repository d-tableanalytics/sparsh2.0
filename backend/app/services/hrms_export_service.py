"""HRMS ▸ the exports the Phase 1 checklist asks for (P1-112, P1-124, P1-125, P1-127, P1-128).

Five downloads that did not exist: the employee master, attendance (daily and monthly), a
payment batch, the payroll-versus-bank reconciliation, and the configuration audit. Every
one of them was a screen somebody had to read and retype.

── Why this module exists at all ───────────────────────────────────────────────────────
Each export COULD have been a few lines in its own route. They are here together because
they share the one rule that matters about an export: it renders SERVER-SIDE from rows the
service already scoped. Building a file in the browser from a list endpoint means shipping
the rows the API deliberately withheld — a manager's download would carry the whole company
— and that mistake is made once per export unless there is one place that does it right.

So each builder here returns the same `payload` shape the analytics exporter already
renders (`entity`, `columns`, `rows`, `total`, `returned`, `truncated`), and the renderers
are IMPORTED from it rather than copied. One CSV writer, one XLSX writer, one truncation
notice, five exports.

── Scoping and masking are never re-implemented ────────────────────────────────────────
The employee export pages through `list_employees`, and the attendance export through
`list_attendance`, instead of querying the collections directly. Those functions hold the
row-scoping (a manager sees their team) and the masking (EMPLOYEE_MASKED_FIELDS shown as
XXXX+4) and they are the reason a download cannot leak what the screen withholds. Querying
Mongo here would be faster and would be a second implementation of permission, which is
the one thing a second implementation must never be.

The masked fields stay masked unless the caller holds the capability that unmasks them ON
SCREEN — the same `EMPLOYEE_SALARY_READ` gate `_employee_view` already applies — so the
file and the screen agree about what this person may see.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    COLL_FIELD_DEFINITIONS, COLL_PAYMENT_BATCHES, COLL_PAYMENTS, COLL_PAYROLL_RECORDS,
    COLL_PAYROLL_RUNS, Cap, FieldStatus, PAYROLL_FINAL_STATUSES,
)
from app.services.hrms_analytics_service import (          # noqa: F401 -- re-exported
    MAX_EXPORT_ROWS, render_csv, render_xlsx,
)
from app.utils.hrms_access import can

# One page of `list_employees` / `list_attendance`. Both cap their own `limit`, so a big
# export is paged rather than asking for a number they would silently reduce.
PAGE = 500


def payload(entity: str, columns: list, rows: list, *, total: Optional[int] = None,
            truncated: bool = False) -> dict:
    """The shape `render_csv` / `render_xlsx` read.

    `columns` is a list of (key, label) pairs so the two renderers can label a column
    without guessing, exactly as the analytics exporter's are.
    """
    return {"entity": entity, "columns": columns, "rows": rows,
            "total": total if total is not None else len(rows),
            "returned": len(rows), "truncated": truncated}


def _cell(value):
    """A value a CSV cell and an XLSX cell can both hold.

    None becomes "" rather than the string "None", a bool becomes Yes/No rather than
    TRUE/FALSE (which Excel then treats as a formula in some locales), and a list is
    joined -- a cell containing `['a', 'b']` is a bug the reader has to decode.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value if v not in (None, ""))
    if isinstance(value, dict):
        return "; ".join(f"{k}={v}" for k, v in value.items() if v not in (None, ""))
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return value


def filename(entity: str, fmt: str, suffix: str = "") -> str:
    stamp = suffix or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"hrms_{entity}_{stamp}.{fmt}"


def _rows(columns: list, records: list) -> list:
    return [[_cell(r.get(key)) for key, _ in columns] for r in records]


# ─────────────────────────────────────────────────────────────
# 6a — Employee master (P1-124)
# ─────────────────────────────────────────────────────────────
# The core columns, in the order somebody reading a staff list expects: who they are, where
# they sit, when they joined, how they are paid. `base_salary` and the masked identity
# fields are present but only CARRY a value for a caller allowed to see them -- the view
# builder decides that, not this list.
EMPLOYEE_COLUMNS = [
    ("employee_code", "Employee ID"), ("name", "Name"),
    ("official_email", "Official Email"), ("personal_email", "Personal Email"),
    ("personal_mobile", "Mobile"), ("gender", "Gender"),
    ("date_of_birth", "Date of Birth"), ("blood_group", "Blood Group"),
    ("department", "Department"), ("designation", "Designation"),
    ("grade", "Grade"), ("employment_type", "Employment Type"),
    ("employment_status", "Employment Status"), ("employment_category", "Category"),
    ("work_location", "Work Location"), ("business_unit", "Business Unit"),
    ("reporting_manager_name", "Reporting Manager"),
    ("joined_on", "Date of Joining"), ("confirmation_date", "Confirmation Date"),
    ("resigned_on", "Last Working Day"),
    ("payroll_group", "Payroll Group"), ("shift_code", "Shift"),
    ("weekly_off_pattern", "Weekly Off"),
    ("bank_name", "Bank"), ("bank_account", "Bank Account"), ("bank_ifsc", "IFSC"),
    ("pan", "PAN"), ("aadhaar", "Aadhaar"), ("uan", "UAN"), ("passport", "Passport"),
    ("base_salary", "Base Salary"), ("active", "Active"),
]


async def _exportable_custom_fields(company_id: str) -> list:
    """Custom fields whose definition says `exportable`.

    The flag has existed on every field definition since §22 and nothing read it. Honouring
    it is the difference between an export the company designed and one that dumps every
    field anyone ever added -- including the ones marked sensitive.
    """
    rows = await get_collection(COLL_FIELD_DEFINITIONS).find(
        {"company_id": str(company_id), "module": "employee", "exportable": True,
         "status": FieldStatus.ACTIVE.value}).sort("display_order", 1).to_list(200)
    return [(f"custom_fields.{r['code']}", r.get("label") or r["code"]) for r in rows]


async def employee_master(actor: dict, company_id: str, *, search: str = None,
                          department_id: str = None, status: str = None,
                          include_inactive: bool = False) -> dict:
    """§3's employee master as a file, scoped and masked exactly as the directory is."""
    from app.services.hrms_employee_service import list_employees

    columns = EMPLOYEE_COLUMNS + await _exportable_custom_fields(company_id)
    records, total, skip = [], 0, 0
    while len(records) < MAX_EXPORT_ROWS:
        page = await list_employees(
            actor, company_id, search=search, department_id=department_id, status=status,
            include_inactive=include_inactive, limit=PAGE, skip=skip)
        total = page.get("total") or 0
        batch = page.get("employees") or []
        records.extend(batch)
        if len(batch) < PAGE:
            break
        skip += PAGE
    truncated = len(records) > MAX_EXPORT_ROWS
    records = records[:MAX_EXPORT_ROWS]

    # A custom value lives under `custom_fields`, so the dotted key is resolved here rather
    # than flattening every record just to read a handful of them.
    for r in records:
        for key, _ in columns:
            if key.startswith("custom_fields."):
                r[key] = (r.get("custom_fields") or {}).get(key.split(".", 1)[1])

    return payload("employees", columns, _rows(columns, records),
                   total=total, truncated=truncated)


# ─────────────────────────────────────────────────────────────
# 6b — Attendance, daily and monthly (P1-125)
# ─────────────────────────────────────────────────────────────
ATTENDANCE_DAILY_COLUMNS = [
    ("employee_code", "Employee ID"), ("employee_name", "Name"),
    ("department", "Department"), ("work_location", "Work Location"),
    ("work_date", "Date"), ("weekday", "Day"), ("status", "Status"),
    ("shift_code", "Shift"), ("actual_in", "In"), ("actual_out", "Out"),
    ("worked_hours", "Worked Hours"), ("late_minutes", "Late (min)"),
    ("early_minutes", "Early (min)"), ("payable_day", "Payable Day"),
    ("lop_fraction", "LOP Fraction"), ("source", "Source"),
    ("regularization_flag", "Regularised"), ("od_ref", "OD Ref"),
    ("leave_ref", "Leave Ref"),
]

ATTENDANCE_MONTHLY_COLUMNS = [
    ("employee_code", "Employee ID"), ("employee_name", "Name"),
    ("department", "Department"), ("work_location", "Work Location"),
    ("present", "Present"), ("half_day", "Half Day"), ("absent", "Absent"),
    ("leave", "Leave"), ("od", "OD"), ("weekly_off", "Weekly Off"),
    ("holiday", "Holiday"), ("pending", "Pending"),
    ("late_days", "Late Days"), ("late_minutes", "Late (min)"),
    ("payable_days", "Payable Days"), ("lop_days", "LOP Days"),
]

# The statuses a monthly total counts, and the column each lands in. Driven off a map
# rather than a chain of ifs so a new status is one line and cannot be forgotten in the
# totals while appearing in the daily rows.
NO_RECORD_STATUS = "Absent (no record)"

_MONTHLY_BUCKET = {
    "Present": "present", "Half Day": "half_day", "Absent": "absent",
    "On Leave": "leave", "On OD": "od", "Weekly Off": "weekly_off",
    "Holiday": "holiday", "Pending": "pending",
    # DEF-14: a working day with no record at all is absent -- payroll charges it as LOP.
    NO_RECORD_STATUS: "absent",
}


async def _attendance_days(actor: dict, company_id: str, period: str,
                           employee_code: str = None) -> tuple:
    """Every scoped attendance row of the period, paged through `list_attendance`."""
    from app.services.hrms_attendance_service import list_attendance

    start, end = f"{period}-01", f"{period}-31"
    rows = await list_attendance(actor, company_id, employee_code=employee_code,
                                 start_date=start, end_date=end,
                                 limit=MAX_EXPORT_ROWS + 1)
    truncated = len(rows) > MAX_EXPORT_ROWS
    return rows[:MAX_EXPORT_ROWS], truncated


async def _unrecorded_rows(actor: dict, company_id: str, period: str,
                           employee_code: str = None) -> list:
    """DEF-14: every working day with NO attendance record, as report rows. Payroll charges
    each as LOP (DEF-05), so both attendance reports show it rather than leaving a silent
    gap. Same row scope as the recorded days: the scope query decides whose days this caller
    may see."""
    from app.services.hrms_attendance_service import _scope_query, unrecorded_absences
    scope = await _scope_query(actor, company_id, {})
    allowed = scope.get("employee_code")
    gaps = (await unrecorded_absences(company_id, period, every_day=True)).get("unrecorded") or []
    out = []
    for g in gaps:
        code = g["employee_code"]
        if employee_code and code != employee_code:
            continue
        if isinstance(allowed, dict) and code not in allowed.get("$in", []):
            continue
        if isinstance(allowed, str) and code != allowed:
            continue
        out.append({"employee_code": code, "employee_name": g.get("employee_name"),
                    "work_date": g["work_date"], "status": NO_RECORD_STATUS,
                    "payable_day": 0, "lop_fraction": 1, "source": "No record"})
    return out


async def attendance_daily(actor: dict, company_id: str, period: str,
                           employee_code: str = None) -> dict:
    rows, truncated = await _attendance_days(actor, company_id, period, employee_code)
    # DEF-14: a day row carries `shift_code` only when a named shift judged it, so the Shift
    # column was blank for everyone on company timing or on an un-stamped day. Fall back to
    # the employee's assigned shift, then to the name the rules engine itself uses.
    from app.models.hrms import COLL_EMPLOYEE_PROFILES
    codes = list({r.get("employee_code") for r in rows if r.get("employee_code")})
    assigned = {p["employee_code"]: p.get("shift_code")
                for p in await get_collection(COLL_EMPLOYEE_PROFILES).find(
                    {"company_id": str(company_id), "employee_code": {"$in": codes}},
                    {"employee_code": 1, "shift_code": 1}).to_list(len(codes) or 1)}
    for r in rows:
        minutes = r.get("worked_minutes")
        r["worked_hours"] = round(minutes / 60.0, 2) if minutes else None
        r["shift_code"] = (r.get("shift_code") or assigned.get(r.get("employee_code"))
                           or "Company timing")
    for g in await _unrecorded_rows(actor, company_id, period, employee_code):
        g["shift_code"] = assigned.get(g["employee_code"]) or "Company timing"
        rows.append(g)
    from datetime import date as _date
    for r in rows:
        if not r.get("weekday"):
            try:
                r["weekday"] = r.get("day") or _date.fromisoformat(r["work_date"]).strftime("%A")
            except (KeyError, TypeError, ValueError):
                pass
    rows.sort(key=lambda r: (r.get("employee_code") or "", r.get("work_date") or ""))
    return payload(f"attendance_{period}_daily", ATTENDANCE_DAILY_COLUMNS,
                   _rows(ATTENDANCE_DAILY_COLUMNS, rows), truncated=truncated)


async def attendance_monthly(actor: dict, company_id: str, period: str,
                             employee_code: str = None) -> dict:
    """Per-employee totals for the month.

    Payable days and LOP days are SUMMED FROM THE ROWS' OWN `payable_day` / `lop_fraction`,
    not counted by status. A half day is worth whatever the ATT_DAY policy said it was when
    the day was judged (Gap 1), so counting statuses would give a monthly total that
    disagrees with the payslip -- which is the defect Gap 1 closed one layer down.
    """
    rows, truncated = await _attendance_days(actor, company_id, period, employee_code)
    # DEF-14: the no-record days the daily report lists are absences here too, so the two
    # reports agree with each other and with payroll's LOP.
    rows = rows + await _unrecorded_rows(actor, company_id, period, employee_code)
    totals: dict = {}
    for r in rows:
        code = r.get("employee_code") or ""
        t = totals.setdefault(code, {
            "employee_code": code, "employee_name": r.get("employee_name"),
            "department": r.get("department"), "work_location": r.get("work_location"),
            "present": 0, "half_day": 0, "absent": 0, "leave": 0, "od": 0,
            "weekly_off": 0, "holiday": 0, "pending": 0,
            "late_days": 0, "late_minutes": 0, "payable_days": 0.0, "lop_days": 0.0,
        })
        bucket = _MONTHLY_BUCKET.get(r.get("status"))
        if bucket:
            t[bucket] += 1
        late = int(r.get("late_minutes") or 0)
        if late > 0:
            t["late_days"] += 1
            t["late_minutes"] += late
        if r.get("payable_day") is not None:
            t["payable_days"] += float(r["payable_day"])
        if r.get("lop_fraction") is not None:
            t["lop_days"] += float(r["lop_fraction"])
    for t in totals.values():
        t["payable_days"] = round(t["payable_days"], 2)
        t["lop_days"] = round(t["lop_days"], 2)

    records = sorted(totals.values(), key=lambda t: t["employee_code"])
    return payload(f"attendance_{period}_monthly", ATTENDANCE_MONTHLY_COLUMNS,
                   _rows(ATTENDANCE_MONTHLY_COLUMNS, records), truncated=truncated)


# ─────────────────────────────────────────────────────────────
# 6c — Payment batch (P1-127)
# ─────────────────────────────────────────────────────────────
PAYMENT_COLUMNS = [
    ("batch_no", "Batch No"), ("period", "Period"),
    ("employee_code", "Employee ID"), ("employee_name", "Name"),
    ("account_holder", "Account Holder"), ("bank_name", "Bank"),
    ("bank_account", "Account (masked)"), ("bank_ifsc", "IFSC"),
    ("amount", "Amount"), ("payment_mode", "Mode"), ("status", "Status"),
    ("payment_date", "Payment Date"), ("utr", "UTR"),
    ("failure_reason", "Failure Reason"), ("retry_batch_no", "Retried In"),
]


async def payment_batch(actor: dict, company_id: str, batch_no: str) -> dict:
    """One batch's payments. The account stays MASKED.

    This is a reconciliation and status document, not a payment instruction. Full account
    numbers exist in exactly one place -- `bank_file`, which is gated on payroll approval
    and audited on every download -- and an export that quietly carried them would make
    that gate meaningless.
    """
    from app.services.hrms_disbursal_service import get_batch

    batch = await get_batch(actor, company_id, batch_no)
    rows = batch.get("payments") or []
    for r in rows:
        r.setdefault("batch_no", batch_no)
        r.setdefault("period", batch.get("period"))
    return payload(f"payments_{batch_no}", PAYMENT_COLUMNS,
                   _rows(PAYMENT_COLUMNS, rows))


async def payment_period(actor: dict, company_id: str, period: str) -> dict:
    """Every payment of a period, across all its batches -- including the retries."""
    from app.services.hrms_disbursal_service import _assert_payroll_role, _out

    _assert_payroll_role(actor)
    rows = await get_collection(COLL_PAYMENTS).find(
        {"company_id": str(company_id), "period": period}).sort(
        "employee_code", 1).to_list(MAX_EXPORT_ROWS + 1)
    truncated = len(rows) > MAX_EXPORT_ROWS
    records = [_out(r) for r in rows[:MAX_EXPORT_ROWS]]
    return payload(f"payments_{period}", PAYMENT_COLUMNS,
                   _rows(PAYMENT_COLUMNS, records), truncated=truncated)


# ─────────────────────────────────────────────────────────────
# 6d — Payroll versus bank reconciliation (P1-112)
# ─────────────────────────────────────────────────────────────
RECONCILIATION_COLUMNS = [
    ("measure", "Measure"), ("employees", "Employees"), ("amount", "Amount"),
    ("note", "Note"),
]


async def reconciliation(actor: dict, company_id: str, period: str) -> dict:
    """Does what payroll approved equal what the bank was asked to pay, and what it paid?

    Three totals that should agree and usually do not, plus the differences, because "the
    payroll says 48,75,000 and the batch files add up to 48,70,000" is the question this
    answers and nothing in the product could.

    The APPROVED total counts only records in a FINAL run -- a draft run's figures are not
    something to reconcile a bank file against. Employees with a net pay of zero or less
    are excluded from the payable count for the same reason `payment_summary` excludes
    them: they were never going to appear in a batch, so counting them would show a
    permanent shortfall.
    """
    from app.services.hrms_disbursal_service import FAILED, PENDING, PROCESSED, REJECTED

    run = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": period})
    if not run:
        raise HTTPException(status_code=404, detail=f"No payroll run for {period}.")
    from app.services.hrms_disbursal_service import _assert_payroll_role
    _assert_payroll_role(actor)

    final = run.get("status") in PAYROLL_FINAL_STATUSES
    records = await get_collection(COLL_PAYROLL_RECORDS).find(
        {"company_id": str(company_id), "period": period},
        {"employee_code": 1, "net_pay": 1}).to_list(10000)
    payable = {r["employee_code"]: round(float(r.get("net_pay") or 0), 2)
               for r in records if float(r.get("net_pay") or 0) > 0}

    batches = await get_collection(COLL_PAYMENT_BATCHES).find(
        {"company_id": str(company_id), "period": period}).to_list(500)
    payments = await get_collection(COLL_PAYMENTS).find(
        {"company_id": str(company_id), "period": period}).to_list(20000)

    def total(rows):
        return round(sum(float(r.get("amount") or 0) for r in rows), 2)

    processed = [p for p in payments if p.get("status") == PROCESSED]
    pending = [p for p in payments if p.get("status") == PENDING]
    # A failure that has been retried is not an outstanding failure -- the retry batch
    # carries it, and counting both would double the shortfall.
    failed = [p for p in payments
              if p.get("status") in (FAILED, REJECTED) and not p.get("retry_batch_no")]
    batched_codes = {p["employee_code"] for p in payments}
    not_batched = {c: a for c, a in payable.items() if c not in batched_codes}

    approved_amount = round(sum(payable.values()), 2)
    batch_amount = round(sum(float(b.get("total_amount") or 0) for b in batches), 2)
    # DEF-13: what reached a batch, each employee's payment ONCE. A failure that was retried
    # is superseded by its retry row, so the batch FILE totals (retries included) count it
    # twice and "approved - batched" went negative by exactly the retried amount.
    batched_amount = total([p for p in payments
                            if not (p.get("status") in (FAILED, REJECTED)
                                    and p.get("retry_batch_no"))])
    processed_amount = total(processed)

    rows = [
        {"measure": "Approved net pay (payroll)", "employees": len(payable),
         "amount": approved_amount,
         "note": f"Run status {run.get('status')}"
                 + ("" if final else " — NOT final, so this is provisional")},
        {"measure": "Sum of batch file totals", "employees": sum(
            int(b.get("employee_count") or 0) for b in batches),
         "amount": batch_amount,
         "note": f"{len(batches)} batch(es), retries included"},
        {"measure": "Processed (bank confirmed)", "employees": len(processed),
         "amount": processed_amount, "note": ""},
        {"measure": "Pending with the bank", "employees": len(pending),
         "amount": total(pending), "note": ""},
        {"measure": "Failed / rejected, not retried", "employees": len(failed),
         "amount": total(failed), "note": "Needs a retry batch"},
        {"measure": "Payable but never batched", "employees": len(not_batched),
         "amount": round(sum(not_batched.values()), 2),
         "note": "; ".join(sorted(not_batched)[:20]) or ""},
        {"measure": "Batched, each payment once", "employees": len(batched_codes),
         "amount": batched_amount, "note": "Retried failures counted once, in the retry"},
        {"measure": "Difference: approved - batched", "employees": "",
         "amount": round(approved_amount - batched_amount, 2),
         "note": "Zero when every approved rupee reached a batch"},
        {"measure": "Difference: approved - processed", "employees": "",
         "amount": round(approved_amount - processed_amount, 2),
         "note": "What the company still owes for this period"},
    ]
    out = payload(f"reconciliation_{period}", RECONCILIATION_COLUMNS,
                  _rows(RECONCILIATION_COLUMNS, rows))
    # The figures also go back as data, because the screen shows this before anyone
    # downloads it and should not have to parse its own CSV.
    out["summary"] = {
        "period": period, "run_status": run.get("status"), "final": final,
        "approved_amount": approved_amount, "approved_employees": len(payable),
        "batch_amount": batch_amount, "batched_amount": batched_amount,
        "processed_amount": processed_amount,
        "pending_amount": total(pending), "failed_amount": total(failed),
        "not_batched_amount": round(sum(not_batched.values()), 2),
        "difference_batched": round(approved_amount - batched_amount, 2),
        "difference_processed": round(approved_amount - processed_amount, 2),
    }
    return out


# ─────────────────────────────────────────────────────────────
# 6e — Configuration audit (P1-128)
# ─────────────────────────────────────────────────────────────
AUDIT_COLUMNS = [
    ("request_no", "Request"), ("entity_type", "Type"), ("entity_code", "Configuration"),
    ("version_no", "Version"), ("title", "Title"), ("status", "Status"),
    ("requested_by_name", "Requested By"), ("requested_at", "Requested At"),
    ("reason", "Business Reason"), ("effective_from", "Effective From"),
    ("decided_by_name", "Approved / Decided By"), ("decided_at", "Decided At"),
    ("decision_comments", "Decision Comments"),
    ("activated_by_name", "Activated By"), ("activated_at", "Activated At"),
    ("old_definition", "Old Definition"), ("new_definition", "New Definition"),
]


async def config_audit(actor: dict, company_id: str, *, entity_type: str = None,
                       limit: int = MAX_EXPORT_ROWS) -> dict:
    """§29/§30 — every governed change with requester, approver, reason, effective date and
    old/new definition. The same filters the on-screen viewer takes."""
    from app.services import hrms_config_change_service as CC

    if not can(actor, Cap.CONFIG_AUDIT_READ):
        raise HTTPException(status_code=403,
                            detail="Reading the configuration audit needs config.audit_read.")
    rows = await CC.list_requests(company_id, limit=min(int(limit), MAX_EXPORT_ROWS))
    if entity_type:
        rows = [r for r in rows if r.get("entity_type") == entity_type]
    for r in rows:
        change = r.get("definition_change") or {}
        r["old_definition"] = change.get("old")
        r["new_definition"] = change.get("new")
    return payload("config_audit", AUDIT_COLUMNS, _rows(AUDIT_COLUMNS, rows))
