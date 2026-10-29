"""Post-review Gap 6 -- the five exports the Phase 1 checklist asks for.

Checklist rows P1-124, P1-125, P1-127, P1-128 and P1-112.

None of them existed: the employee master, attendance (daily and monthly), a payment
batch, the payroll-versus-bank reconciliation and the configuration audit were all screens
somebody had to read and retype.

The checks that matter most here are the NEGATIVE ones, because an export is the one
feature where a permission mistake ships the whole company's data in a single file:

  * a masked field stays masked for a caller who cannot unmask it on screen (section 1),
  * a manager's download carries their team and nobody else's (section 2),
  * a caller without the capability gets 403 rather than a file (sections 1 and 5),
  * the batch export does NOT carry full account numbers, which live only in the gated and
    audited bank file (section 3).

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_gap6_exports   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []


def check(label: str, condition: bool, extra=None) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}"
          + ("" if condition or extra is None else f"  -- {str(extra)[:300]}"))
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


async def expect(label, coro, status, needle=""):
    from fastapi import HTTPException
    try:
        await coro
    except HTTPException as e:
        return check(f"{label} -> {status}", e.status_code == status
                     and needle.lower() in str(e.detail).lower(), e.detail)
    return check(f"{label} -> {status} (no error raised)", False)


from app.services.hrms.tests.test_payroll_live_findings import FakeCollection  # noqa: E402

CO = "C1"
PERIOD = "2026-03"


def headers(payload):
    return [label for _, label in payload["columns"]]


def by_header(payload, header):
    """One column out of the rendered rows, addressed by its human label."""
    idx = headers(payload).index(header)
    return [row[idx] for row in payload["rows"]]


async def main() -> int:
    from bson import ObjectId

    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_audit_service as AU
    import app.services.hrms_config_change_service as CC
    import app.services.hrms_disbursal_service as DB
    import app.services.hrms_employee_master_service as EM
    import app.services.hrms_employee_service as ES
    import app.services.hrms_export_service as EX
    import app.services.hrms_payroll_service as PR
    import app.utils.hrms_access as HA

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AT, AU, CC, DB, EM, ES, EX, PR):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    for mod in (AT, DB, EM, PR):
        mod.audit = no_audit

    U1, U2, U3, U4 = ObjectId(), ObjectId(), ObjectId(), ObjectId()
    HR = {"_id": "hr-1", "role": "superadmin", "governance_role": "HR",
          "full_name": "Dummy HR", "company_id": CO}
    MGR = {"_id": str(U2), "role": "staff", "governance_role": "HOD",
           "full_name": "Dummy Manager", "company_id": CO}
    PLAIN = {"_id": "emp-9", "role": "staff", "full_name": "Dummy Employee",
             "company_id": CO}

    # A tenant company's people live in `learners`, keyed by company_id -- see
    # tenant_identity_source. Putting them in `staff` would make them Sparsh's own
    # operators and the directory would resolve none of them.
    store["learners"] = FakeCollection([
        {"_id": U1, "full_name": "Asha Rao", "email": "asha@x.com", "is_active": True,
         "company_id": CO, "reporting_manager": str(U2)},
        {"_id": U2, "full_name": "Dummy Manager", "email": "mgr@x.com", "is_active": True,
         "company_id": CO},
        # Reports to nobody in this test, and is in no department -- so the manager must
        # not see them. Without a third person the scope check would pass on a manager who
        # sees the whole company, because their own row plus their report IS the company.
        {"_id": U3, "full_name": "Ravi Kumar", "email": "ravi@x.com", "is_active": True,
         "company_id": CO},
    ])
    store[M.COLL_EMPLOYEE_PROFILES] = FakeCollection([
        {"company_id": CO, "employee_code": "E-001", "user_id": str(U1),
         "employment_status": "Active", "grade": "M2", "work_location": "Pune",
         "joined_on": "2025-04-01", "bank_name": "HDFC",
         "bank_account": "501000123456789", "bank_ifsc": "HDFC0001234",
         "bank_account_holder": "Asha Rao",
         "pan": "ABCDE1234F", "aadhaar": "111122223333", "base_salary": 50000,
         "custom_fields": {"tshirt": "L", "secret_note": "private"}},
        {"company_id": CO, "employee_code": "E-002", "user_id": str(U2),
         "employment_status": "Active", "grade": "M3", "work_location": "Mumbai",
         "joined_on": "2024-01-01", "bank_name": "ICICI",
         "bank_account": "602000987654321", "bank_ifsc": "ICIC0005678",
         "pan": "ZZZZZ9999Z", "base_salary": 90000},
        {"company_id": CO, "employee_code": "E-003", "user_id": str(U3),
         "employment_status": "Active", "grade": "M1", "work_location": "Pune",
         "joined_on": "2026-01-15"},
    ])
    # Only `tshirt` is marked exportable; `secret_note` is not, and must not appear.
    store[M.COLL_FIELD_DEFINITIONS] = FakeCollection([
        {"company_id": CO, "module": "employee", "code": "tshirt", "label": "T-Shirt Size",
         "exportable": True, "status": "Active", "display_order": 1},
        {"company_id": CO, "module": "employee", "code": "secret_note",
         "label": "Secret Note", "exportable": False, "status": "Active",
         "display_order": 2},
    ])

    # ── 1. Employee master (P1-124) ─────────────────────────────────────────────────
    section("1. Employee master: columns, masking, exportable custom fields")

    full = await EX.employee_master(HR, CO)
    head = headers(full)
    check("the core columns are there, in a readable order",
          head[:4] == ["Employee ID", "Name", "Official Email", "Personal Email"], head[:4])
    check("every employee HR can see is exported", full["returned"] == 3, full["returned"])
    check("an exportable custom field gets a column under its own label",
          "T-Shirt Size" in head, head[-4:])
    check("...and one marked NOT exportable does not",
          "Secret Note" not in head, head)
    check("the custom value is actually carried, not just the column",
          "L" in by_header(full, "T-Shirt Size"), by_header(full, "T-Shirt Size"))

    accounts = by_header(full, "Bank Account")
    check("HR holds salary access, so the account is in full",
          "501000123456789" in accounts, accounts)
    check("...and so is the base salary",
          50000 in by_header(full, "Base Salary"), by_header(full, "Base Salary"))

    # A caller without EMPLOYEE_SALARY_READ gets the same file with the masked fields
    # masked -- the file and the screen must agree about what this person may see.
    real_can = HA.can
    ES.can = lambda actor, cap: (real_can(actor, cap)
                                 and cap != M.Cap.EMPLOYEE_SALARY_READ)
    unmasked_blocked = await EX.employee_master(HR, CO)
    ES.can = real_can
    masked = by_header(unmasked_blocked, "Bank Account")
    check("without salary access the account is MASKED, not omitted or full",
          all(str(v).startswith("XXXX") for v in masked if v), masked)
    check("...and the PAN too",
          all(str(v).startswith("XXXX")
              for v in by_header(unmasked_blocked, "PAN") if v),
          by_header(unmasked_blocked, "PAN"))
    check("...while the salary column is empty rather than guessable",
          all(v == "" for v in by_header(unmasked_blocked, "Base Salary")),
          by_header(unmasked_blocked, "Base Salary"))

    # ── 2. The export cannot out-reach the screen ───────────────────────────────────
    section("2. A manager's download carries their team and nobody else's")

    scoped = await EX.employee_master(MGR, CO)
    codes = sorted(by_header(scoped, "Employee ID"))
    check("the manager's file holds their report and themselves, as the screen does",
          codes == ["E-001", "E-002"], codes)
    check("...and NOT the third employee, who reports elsewhere",
          "E-003" not in codes, codes)
    check("...so it is fewer rows than HR's, out of the same function",
          scoped["returned"] < full["returned"], (scoped["returned"], full["returned"]))

    # Wiring the export exposed a row-scoping leak in `list_employees` itself, which the
    # two checks below pin SEPARATELY because either half of the fix alone hides the other.
    #
    # A profile whose `user_id` no longer resolves in this company is reported as a broken
    # link, so HR can fix the data. The test for "no longer resolves" compared against the
    # ROLE-SCOPED result set, so for a manager every colleague failed it and the directory
    # appended the whole company as broken links -- and this export would have written
    # them to a file.
    rows_hr = (await ES.list_employees(HR, CO))["employees"]
    broken_for_hr = sorted(r["employee_code"] for r in rows_hr if r.get("link_broken"))
    check("a colleague who resolves normally is NOT reported as a broken link to HR",
          broken_for_hr == [], broken_for_hr)

    # The sharpest case for the company-wide id set, and the one that shows the two sets
    # are not interchangeable even for HR: a LEAVER. They are filtered out of the user
    # query by `is_active`, so the scoped result set does not contain them -- and testing
    # "does this user still resolve" against that set made every leaver reappear in the
    # live directory flagged as a broken link.
    store["learners"].docs.append(
        {"_id": U4, "full_name": "Old Leaver", "email": "old@x.com", "is_active": False,
         "company_id": CO})
    store[M.COLL_EMPLOYEE_PROFILES].docs.append(
        {"company_id": CO, "employee_code": "E-LEFT", "user_id": str(U4),
         "employment_status": "Exited"})
    active_only = await ES.list_employees(HR, CO)
    codes_active = sorted(r["employee_code"] for r in active_only["employees"])
    check("a leaver stays out of the default directory instead of returning as a broken link",
          "E-LEFT" not in codes_active
          and not any(r.get("link_broken") for r in active_only["employees"]),
          codes_active)
    with_inactive = await ES.list_employees(HR, CO, include_inactive=True)
    check("...and is there, unflagged, when inactive employees are asked for",
          "E-LEFT" in [r["employee_code"] for r in with_inactive["employees"]]
          and not any(r.get("link_broken") for r in with_inactive["employees"]),
          [r["employee_code"] for r in with_inactive["employees"]])
    store["learners"].docs.pop()
    store[M.COLL_EMPLOYEE_PROFILES].docs.pop()

    # A genuinely orphaned profile: HR must still see it, because it is theirs to fix.
    store[M.COLL_EMPLOYEE_PROFILES].docs.append(
        {"company_id": CO, "employee_code": "E-ORPHAN", "user_id": str(ObjectId()),
         "employment_status": "Active", "reporting_manager_id": "somebody-else"})
    rows_hr = (await ES.list_employees(HR, CO))["employees"]
    check("a genuinely orphaned profile still surfaces to HR as a broken link",
          [r["employee_code"] for r in rows_hr if r.get("link_broken")] == ["E-ORPHAN"],
          [r["employee_code"] for r in rows_hr if r.get("link_broken")])
    rows_mgr = (await ES.list_employees(MGR, CO))["employees"]
    check("...and not to a manager it does not report to -- profile rows fail closed",
          not any(r.get("link_broken") for r in rows_mgr),
          [r["employee_code"] for r in rows_mgr])
    store[M.COLL_EMPLOYEE_PROFILES].docs.pop()

    # A new hire onboarded with no login yet has no `user_id` at all, so they reach the
    # directory through the same profile-side path and need the same scoping. HR sees them
    # (their Employee ID has been issued); a manager they do not report to does not.
    store[M.COLL_EMPLOYEE_PROFILES].docs.append(
        {"company_id": CO, "employee_code": "E-NEW", "employment_status": "Active",
         "reporting_manager_id": "somebody-else"})
    hr_new = [r["employee_code"] for r in (await ES.list_employees(HR, CO))["employees"]]
    mgr_new = [r["employee_code"] for r in (await ES.list_employees(MGR, CO))["employees"]]
    check("a login-less new hire is in HR's directory",
          "E-NEW" in hr_new, hr_new)
    check("...and not in an unrelated manager's",
          "E-NEW" not in mgr_new, mgr_new)
    store[M.COLL_EMPLOYEE_PROFILES].docs.pop()

    # ── 3. Attendance, daily and monthly (P1-125) ──────────────────────────────────
    section("3. Attendance: a row per day, and totals that match the payslip")

    # 20 present, 1 half day worth 0.75 under the policy, 1 absent, 1 late.
    att = store.setdefault(M.COLL_ATTENDANCE, FakeCollection())
    att.docs.extend([
        {"company_id": CO, "employee_code": "E-001", "work_date": f"{PERIOD}-{d:02d}",
         "status": "Present", "actual_in": "09:30", "actual_out": "18:30",
         "worked_minutes": 540, "late_minutes": 0, "early_minutes": 0,
         "payable_day": 1.0, "lop_fraction": 0.0, "source": "Manual"}
        for d in range(1, 21)]
        + [{"company_id": CO, "employee_code": "E-001", "work_date": f"{PERIOD}-21",
            "status": "Half Day", "actual_in": "09:30", "actual_out": "13:00",
            "worked_minutes": 210, "late_minutes": 0, "early_minutes": 330,
            "payable_day": 0.75, "lop_fraction": 0.25, "source": "Manual"},
           {"company_id": CO, "employee_code": "E-001", "work_date": f"{PERIOD}-22",
            "status": "Absent", "payable_day": 0.0, "lop_fraction": 1.0},
           {"company_id": CO, "employee_code": "E-001", "work_date": f"{PERIOD}-23",
            "status": "Present", "actual_in": "10:45", "actual_out": "19:30",
            "worked_minutes": 525, "late_minutes": 75, "early_minutes": 0,
            "payable_day": 1.0, "lop_fraction": 0.0, "source": "Manual"}])

    daily = await EX.attendance_daily(HR, CO, PERIOD)
    dhead = headers(daily)
    # DEF-14: recorded days, plus every working day with NO record (absent -> LOP).
    statuses = by_header(daily, "Status")
    check("the daily view has a row per recorded employee-day",
          sum(1 for s in statuses if s != "Absent (no record)") == 23, daily["returned"])
    check("...and lists working days with no record as absent (DEF-14)",
          daily["returned"] > 23
          and "Absent (no record)" in statuses, daily["returned"])
    check("...with the columns the checklist names",
          all(h in dhead for h in ["Status", "In", "Out", "Worked Hours", "Late (min)",
                                   "Early (min)", "Payable Day", "LOP Fraction"]), dhead)
    check("worked minutes are reported as HOURS, which is what a reader wants",
          9.0 in by_header(daily, "Worked Hours"), by_header(daily, "Worked Hours")[:3])

    monthly = await EX.attendance_monthly(HR, CO, PERIOD)
    mhead = headers(monthly)
    # DEF-14: the no-record days the daily view lists are absences in the monthly totals
    # too (full LOP each), so both reports agree with payroll.
    gaps = [r for r in daily["rows"] if r[dhead.index("Status")] == "Absent (no record)"]
    e001_gaps = sum(1 for r in gaps if r[dhead.index("Employee ID")] == "E-001")
    employees = {r[dhead.index("Employee ID")] for r in daily["rows"]}
    mcodes = by_header(monthly, "Employee ID")
    e001 = mcodes.index("E-001")
    check("the monthly view is one row per employee in the daily view",
          monthly["returned"] == len(employees), (monthly["returned"], sorted(employees)))
    check("...with the totals the checklist names",
          all(h in mhead for h in ["Present", "Absent", "Half Day", "Leave", "OD",
                                   "Late Days", "Late (min)", "Payable Days",
                                   "LOP Days"]), mhead)
    check("present, half day and absent are counted by status",
          (by_header(monthly, "Present")[e001], by_header(monthly, "Half Day")[e001],
           by_header(monthly, "Absent")[e001]) == (21, 1, 1 + e001_gaps),
          [by_header(monthly, h)[e001] for h in ("Present", "Half Day", "Absent")])
    check("late days count the days, and late minutes the minutes",
          (by_header(monthly, "Late Days")[e001],
           by_header(monthly, "Late (min)")[e001]) == (1, 75),
          (by_header(monthly, "Late Days")[e001], by_header(monthly, "Late (min)")[e001]))
    # 21 whole days + 0.75 = 21.75, NOT 21.5 -- summing the rows' own fractions is what
    # keeps the monthly total agreeing with what payroll paid (Gap 1).
    check("payable days SUM the rows' own fractions rather than counting statuses",
          by_header(monthly, "Payable Days")[e001] == 21.75,
          by_header(monthly, "Payable Days")[e001])
    check("...and LOP days likewise",
          by_header(monthly, "LOP Days")[e001] == 1.25 + e001_gaps,
          by_header(monthly, "LOP Days")[e001])

    # ── 4. Payment batch and the reconciliation (P1-127, P1-112) ───────────────────
    section("4. Payment batch and payroll-versus-bank reconciliation")

    store[M.COLL_PAYROLL_RUNS] = FakeCollection([
        {"_id": ObjectId(), "company_id": CO, "period": PERIOD, "status": "Closed"}])
    store[M.COLL_PAYROLL_RECORDS] = FakeCollection([
        {"company_id": CO, "period": PERIOD, "employee_code": "E-001",
         "employee_name": "Asha Rao", "net_pay": 48000.0},
        {"company_id": CO, "period": PERIOD, "employee_code": "E-002",
         "employee_name": "Dummy Manager", "net_pay": 86000.0},
        # Nobody pays a zero net, so it must not show up as a permanent shortfall.
        {"company_id": CO, "period": PERIOD, "employee_code": "E-003",
         "employee_name": "Ravi Kumar", "net_pay": 0.0},
    ])
    store[M.COLL_PAYMENT_BATCHES] = FakeCollection([
        {"company_id": CO, "batch_no": "PB-0001", "period": PERIOD, "status": "Generated",
         "employee_count": 2, "total_amount": 134000.0, "payment_mode": "NEFT"}])
    store[M.COLL_PAYMENTS] = FakeCollection([
        {"company_id": CO, "batch_no": "PB-0001", "period": PERIOD,
         "employee_code": "E-001", "employee_name": "Asha Rao",
         "account_holder": "Asha Rao", "bank_name": "HDFC",
         "bank_account": "501000123456789", "bank_ifsc": "HDFC0001234",
         "amount": 48000.0, "payment_mode": "NEFT", "status": "Processed",
         "utr": "UTR12345", "payment_date": "2026-04-02", "failure_reason": None,
         "retry_batch_no": None},
        {"company_id": CO, "batch_no": "PB-0001", "period": PERIOD,
         "employee_code": "E-002", "employee_name": "Dummy Manager",
         "account_holder": "Dummy Manager", "bank_name": "ICICI",
         "bank_account": "602000987654321", "bank_ifsc": "ICIC0005678",
         "amount": 86000.0, "payment_mode": "NEFT", "status": "Failed",
         "utr": None, "payment_date": None, "failure_reason": "Account frozen",
         "retry_batch_no": None},
    ])

    batch = await EX.payment_batch(HR, CO, "PB-0001")
    bhead = headers(batch)
    check("the batch export carries the columns the checklist names",
          all(h in bhead for h in ["Batch No", "Period", "Employee ID", "IFSC", "Amount",
                                   "Status", "Payment Date", "UTR", "Failure Reason",
                                   "Retried In"]), bhead)
    check("the batch number and period are on every row, not only in the filename",
          by_header(batch, "Batch No") == ["PB-0001", "PB-0001"]
          and by_header(batch, "Period") == [PERIOD, PERIOD])
    accts = by_header(batch, "Account (masked)")
    check("the account is MASKED -- this is a reconciliation, not a payment instruction",
          all(str(a).startswith("XXXX") for a in accts), accts)
    check("...and no column anywhere in the file holds the full number",
          not any("501000123456789" in str(c) for row in batch["rows"] for c in row))
    check("the failure reason is carried, which is the point of the export",
          "Account frozen" in by_header(batch, "Failure Reason"))

    period_pay = await EX.payment_period(HR, CO, PERIOD)
    check("the period export spans the batches", period_pay["returned"] == 2,
          period_pay["returned"])

    rec = await EX.reconciliation(HR, CO, PERIOD)
    summary = rec["summary"]
    check("approved net pay excludes the zero-net employee",
          summary["approved_employees"] == 2
          and summary["approved_amount"] == 134000.0, summary)
    check("the batch file totals are summed from the batches themselves",
          summary["batch_amount"] == 134000.0, summary["batch_amount"])
    check("approved minus batched is zero -- every rupee reached a batch",
          summary["difference_batched"] == 0.0, summary["difference_batched"])
    check("processed is only what the bank confirmed",
          summary["processed_amount"] == 48000.0, summary["processed_amount"])
    check("the failure is reported as still owed",
          summary["failed_amount"] == 86000.0
          and summary["difference_processed"] == 86000.0, summary)
    check("the figures add up: processed + failed + pending = approved",
          round(summary["processed_amount"] + summary["failed_amount"]
                + summary["pending_amount"], 2) == summary["approved_amount"], summary)
    check("...and the run's finality is stated, so a draft run cannot be mistaken for one",
          summary["final"] is True and summary["run_status"] == "Closed", summary)

    # A retried failure is carried by its retry batch, so counting both would double it.
    store[M.COLL_PAYMENTS].docs[1]["retry_batch_no"] = "PB-0002"
    retried = (await EX.reconciliation(HR, CO, PERIOD))["summary"]
    check("a failure that has been retried is no longer an outstanding failure",
          retried["failed_amount"] == 0.0, retried["failed_amount"])

    await expect("an employee asking for the reconciliation",
                 EX.reconciliation(PLAIN, CO, PERIOD), 403, "payroll")
    await expect("an employee asking for a payment batch",
                 EX.payment_batch(PLAIN, CO, "PB-0001"), 403, "payroll")

    # ── 5. Configuration audit (P1-128) ────────────────────────────────────────────
    section("5. Configuration audit, gated on its own capability")

    store[M.COLL_CONFIG_CHANGE_REQUESTS] = FakeCollection([
        {"company_id": CO, "request_no": "CFG-0001", "entity_type": "policy_version",
         "entity_code": "ATT_DAY", "version_no": 2, "title": "ATT_DAY v2",
         "status": "Active", "reason": "Client asked for a quarter-day half day",
         "requested_by_name": "Dummy HR", "requested_at": "2026-02-01",
         "effective_from": "2026-03-01", "decided_by_name": "Dummy Finance",
         "decided_at": "2026-02-03", "decision_comments": "Agreed",
         "activated_by_name": "Dummy Finance", "activated_at": "2026-02-04",
         "definition_change": {"old": {"half_day_fraction": 0.5},
                               "new": {"half_day_fraction": 0.25}}},
        {"company_id": CO, "request_no": "CFG-0002", "entity_type": "salary_component",
         "entity_code": "HRA", "title": "HRA 40% -> 50%", "status": "Pending Approval",
         "reason": "Market correction", "requested_by_name": "Dummy HR",
         "requested_at": "2026-02-10"},
    ])

    audit = await EX.config_audit(HR, CO)
    ahead = headers(audit)
    check("the audit export carries everything FRD 30 asks for",
          all(h in ahead for h in ["Request", "Requested By", "Business Reason",
                                   "Effective From", "Approved / Decided By",
                                   "Old Definition", "New Definition"]), ahead)
    check("both requests are exported", audit["returned"] == 2, audit["returned"])
    check("the old and new definitions are rendered readably, not as raw dicts",
          "half_day_fraction=0.5" in by_header(audit, "Old Definition")[0]
          and "half_day_fraction=0.25" in by_header(audit, "New Definition")[0],
          (by_header(audit, "Old Definition")[0], by_header(audit, "New Definition")[0]))
    check("the business reason is there -- an audit without it answers nothing",
          "Client asked for a quarter-day half day" in by_header(audit, "Business Reason"))

    filtered = await EX.config_audit(HR, CO, entity_type="salary_component")
    check("the same entity_type filter the on-screen viewer takes",
          by_header(filtered, "Request") == ["CFG-0002"], by_header(filtered, "Request"))

    await expect("a caller without config.audit_read",
                 EX.config_audit(PLAIN, CO), 403, "config.audit_read")

    # ── 6. Both renderers produce a file from every payload ────────────────────────
    section("6. One CSV writer and one XLSX writer, for all five")

    for name, data in (("employees", full), ("attendance daily", daily),
                       ("attendance monthly", monthly), ("payment batch", batch),
                       ("reconciliation", rec), ("config audit", audit)):
        csv_bytes = EX.render_csv(data)
        first_line = csv_bytes.decode("utf-8-sig").splitlines()[0]
        check(f"{name}: CSV renders with its header row",
              first_line.startswith(headers(data)[0]) and len(csv_bytes) > 50,
              first_line[:80])

    check("the CSV is UTF-8 with a BOM, so Excel opens accented names correctly",
          EX.render_csv(full).startswith(b"\xef\xbb\xbf"))
    check("the filename names the entity and the format",
          EX.filename("employees", "csv").startswith("hrms_employees_")
          and EX.filename("attendance_daily", "xlsx", PERIOD)
          == "hrms_attendance_daily_2026-03.xlsx")

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
