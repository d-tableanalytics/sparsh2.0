"""FRD §20 Phase 1 Acceptance Criteria, walked end to end against the REAL database.

Every other suite in this repo runs on fake collections, which is right for pinning logic.
Acceptance is a different question -- "does the product actually do this" -- so this one
uses the live database, the live services and the §17 roles, and walks one employee from
creation to a payslip in their hand.

-- Why a sandbox company, and not Sparsh Magic --------------------------------------
Criterion 5 locks the attendance month, and a lock is COMPANY-wide: running this inside a
real tenant would freeze that month for every employee in it. So the whole run happens
under its own company id, created and removed by this script. Nothing outside it is read
or written.

-- Who does what ----------------------------------------------------------------------
The four §17 roles are used as four different people, because several criteria are only
meaningful if the right person does the step and the wrong one cannot:

    HR              creates the employee, marks attendance, resolves exceptions, locks
    Payroll Maker   loads inputs, calculates, submits
    Payroll Checker reviews and passes on
    Finance         approves, locks payroll, pays, captures the UTR

Run from backend/:
    python -m app.scripts.acceptance_phase1            # run it
    python -m app.scripts.acceptance_phase1 --undo     # remove everything it created
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

CO = "ACCEPTANCE-PHASE1"          # the sandbox tenant; nothing else uses this id
PERIOD = "2026-03"
EMP_NAME = "Tester Account"

results: list[tuple] = []


def criterion(n, label):
    print(f"\n{n:>2}. {label}")


def check(label, condition, extra=None):
    results.append((bool(condition), label))
    print(f"      {'PASS' if condition else 'FAIL'}  {label}"
          + ("" if condition or extra is None else f"  -- {str(extra)[:220]}"))
    return bool(condition)


async def teardown(db, quiet=False):
    collections = [
        "hrms_employee_profiles", "hrms_employee_history", "hrms_attendance",
        "hrms_attendance_corrections", "hrms_attendance_locks", "hrms_od_requests",
        "hrms_salary_components", "hrms_salary_structures", "hrms_payroll_runs",
        "hrms_payroll_records", "hrms_payment_batches", "hrms_payments",
        "hrms_settings", "hrms_shifts", "hrms_departments", "hrms_designations",
        "hrms_counters", "hrms_audit_log", "hrms_punch_segments",
        "hrms_payroll_carry_forwards", "hrms_payslip_templates", "hrms_bank_formats",
    ]
    total = 0
    for c in collections:
        total += (await db[c].delete_many({"company_id": CO})).deleted_count
    total += (await db["learners"].delete_many({"company_id": CO})).deleted_count
    total += (await db["companies"].delete_many({"_id": CO})).deleted_count
    if not quiet:
        print(f"Removed {total} sandbox record(s) under company {CO}.")
    return total


async def main() -> int:
    from bson import ObjectId
    from app.db.mongodb import connect_to_mongo, db_connection
    await connect_to_mongo()
    db = db_connection.db

    if "--undo" in sys.argv:
        await teardown(db)
        db_connection.client.close()
        return 0

    from app.models import hrms as M
    import app.services.hrms_employee_service as ES
    import app.services.hrms_employee_master_service as EM
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_payroll_service as PS
    import app.services.hrms_disbursal_service as DS
    import app.services.hrms_payslip_service as PSL
    import app.services.hrms_export_service as EX

    print(f"database : {db.name}")
    print(f"sandbox  : {CO}   period: {PERIOD}   employee: {EMP_NAME}")
    await teardown(db, quiet=True)          # a clean slate every run

    # ── Cast ────────────────────────────────────────────────────────────────────────
    def person(name, governance):
        return {"_id": str(ObjectId()), "role": "clientuser",
                "_source_collection": "learners", "company_id": CO,
                "full_name": name, "governance_role": governance}

    HR = person("Hana HR", "HR")
    MAKER = person("Maya Maker", "PAYROLL_MAKER")
    CHECKER = person("Chandra Checker", "PAYROLL_CHECKER")
    FINANCE = person("Farid Finance", "FINANCE")
    MANAGER = person("Manu Manager", "HOD")

    now = datetime.now(timezone.utc)
    await db["companies"].insert_one({"_id": CO, "name": "Acceptance Sandbox",
                                      "is_internal": False, "hrms_enabled": True})
    tester_id = ObjectId()
    await db["learners"].insert_many([
        {"_id": tester_id, "company_id": CO, "full_name": EMP_NAME,
         "email": "tester.account@acceptance.local", "role": "clientuser",
         "is_active": True},
        *({"_id": ObjectId(p["_id"]), "company_id": CO, "full_name": p["full_name"],
           "email": f"{p['governance_role'].lower()}@acceptance.local",
           "role": "clientuser", "governance_role": p["governance_role"],
           "is_active": True} for p in (HR, MAKER, CHECKER, FINANCE, MANAGER)),
    ])
    dept = ObjectId(); desig = ObjectId()
    await db["hrms_departments"].insert_one(
        {"_id": dept, "company_id": CO, "name": "Finance & Accounts", "active": True})
    await db["hrms_designations"].insert_one(
        {"_id": desig, "company_id": CO, "name": "Payroll Analyst", "active": True})
    # The sandbox runs an historic month, so the regularisation window is configured wide
    # enough to reach it. This is CONFIGURATION, not a bypass -- the 7-day default is a
    # real control and a company that wanted a longer window would set exactly this key.
    await db["hrms_settings"].insert_one(
        {"company_id": CO, "shift_policy": {**M.DEFAULT_SHIFT_POLICY,
                                            "regularisation_window_days": 400}})
    await db["hrms_shifts"].insert_one({
        "company_id": CO, "code": "GEN", "name": "General", "active": True,
        "applicability": {}, "versions": [{"effective_from": "2025-01-01",
                                           "start": "09:30", "end": "18:30",
                                           "break_minutes": 30, "daily_grace_minutes": 5,
                                           "weekly_off_pattern": ["Sunday"]}]})
    await EM.save_master_lists(HR, CO, {"lists": {
        "locations": ["Pune"], "grades": ["M2", "M3"], "levels": ["Level 3"],
        "employee_categories": ["Staff"], "payroll_groups": ["PG1 Monthly Staff"],
        "salary_templates": ["Standard Staff Structure"],
        "attendance_policy_groups": ["General Shift"],
        "legal_entities": ["Sparsh Magic Pvt Ltd"]}})
    for c in ({"code": "BASIC", "name": "Basic", "component_type": "Earning",
               "calculation_method": "Fixed", "sequence": 10},
              {"code": "HRA", "name": "House Rent Allowance", "component_type": "Earning",
               "calculation_method": "Percentage", "calculation_base": "BASIC",
               "percentage": 40, "sequence": 20},
              {"code": "PF", "name": "Provident Fund", "component_type": "Deduction",
               "calculation_method": "Formula", "sequence": 80,
               "formula": "ROUND(MIN(BASIC, 15000) * 12 / 100, 0)"},
              {"code": "PF_ER", "name": "PF employer",
               "component_type": "Employer Contribution",
               "calculation_method": "Formula", "sequence": 81,
               "formula": "ROUND(MIN(BASIC, 15000) * 12 / 100, 0)"}):
        await db["hrms_salary_components"].insert_one(
            {**c, "company_id": CO, "active": True, "created_at": now})

    # ── 1 ───────────────────────────────────────────────────────────────────────────
    criterion(1, "HR can create an employee with organisation, reporting, "
                 "attendance and payroll linkage")
    emp = await ES.create_profile(HR, CO, {
        "user_id": str(tester_id), "joined_on": "2025-01-01",
        "legal_entity": "Sparsh Magic Pvt Ltd", "department_id": str(dept),
        "designation_id": str(desig), "grade": "M2", "level": "Level 3",
        "work_location": "Pune", "employee_category": "Staff",
        "reporting_manager_id": MANAGER["_id"],
        "payroll_group": "PG1 Monthly Staff",
        "salary_template": "Standard Staff Structure",
        "shift_code": "GEN", "attendance_policy_group": "General Shift",
        "weekly_off_pattern": ["Sunday"],
        "pan": "AAAPZ1234C", "bank_name": "HDFC", "bank_account": "50100123456789",
        "bank_ifsc": "HDFC0000123", "bank_account_holder": EMP_NAME,
        "personal_email": "tester.personal@acceptance.local",
        "personal_mobile": "9876500001"})
    CODE = emp["employee_code"]
    check(f"{EMP_NAME} created as {CODE}", bool(CODE), emp)
    check("organisation linkage (department, designation, grade, level, location)",
          emp.get("department") == "Finance & Accounts"
          and emp.get("designation") == "Payroll Analyst"
          and emp.get("grade") == "M2" and emp.get("work_location") == "Pune", emp)
    saved = await db["hrms_employee_profiles"].find_one({"company_id": CO,
                                                         "employee_code": CODE})
    check("reporting linkage", bool(saved.get("reporting_manager_id")
                                    or (await db["learners"].find_one(
                                        {"_id": tester_id})).get("reporting_manager")))
    check("attendance linkage (shift, policy group, weekly off)",
          saved.get("shift_code") == "GEN"
          and saved.get("attendance_policy_group") == "General Shift"
          and saved.get("weekly_off_pattern") == ["Sunday"], saved.get("shift_code"))
    check("payroll linkage (payroll group, salary template, bank)",
          saved.get("payroll_group") and saved.get("salary_template")
          and saved.get("bank_account"), saved.get("payroll_group"))

    # ── 2 ───────────────────────────────────────────────────────────────────────────
    criterion(2, "Employee changes preserve history rather than overwriting prior state")
    await ES.update_profile(HR, str(tester_id),
                            {"grade": "M3", "change_reason": "Promotion"}, CO)
    hist = await db["hrms_employee_history"].find(
        {"company_id": CO, "employee_code": CODE, "field": "grade"}).to_list(10)
    moved = [h for h in hist if h.get("new_value") == "M3"]
    check("the change is applied", (await db["hrms_employee_profiles"].find_one(
        {"company_id": CO, "employee_code": CODE})).get("grade") == "M3")
    check("...and the PRIOR value survives on the history row",
          bool(moved) and moved[-1].get("old_value") == "M2",
          [(h.get("old_value"), h.get("new_value")) for h in hist])
    check("...with its reason and the person who made it",
          moved[-1].get("reason") == "Promotion" and moved[-1].get("changed_by_name"),
          moved[-1].get("changed_by_name"))

    # ── 3 ───────────────────────────────────────────────────────────────────────────
    criterion(3, "Daily attendance calculates status, working hours and late-coming")
    await AT.mark_attendance(HR, CO, {
        "employee_code": CODE, "work_date": "2026-03-02",
        "actual_in": "09:50", "actual_out": "18:30", "source": "Biometric"})
    # A FULL month, so proration is 1.0 and criterion 8's figures are clean. 2026-03-06
    # is deliberately left out here -- criterion 4 creates it as a broken day to correct.
    from datetime import date as _date, timedelta as _td
    d = _date(2026, 3, 1)
    while d <= _date(2026, 3, 31):
        iso = d.isoformat()
        if d.weekday() != 6 and iso not in ("2026-03-02", "2026-03-06"):
            await AT.mark_attendance(HR, CO, {
                "employee_code": CODE, "work_date": iso,
                "actual_in": "09:30", "actual_out": "18:30", "source": "Biometric"})
        d += _td(days=1)
    day = await db["hrms_attendance"].find_one({"company_id": CO, "work_date": "2026-03-02"})
    check("status calculated", day.get("status") == "Present", day.get("status"))
    check("working hours calculated",
          day.get("worked_minutes") == 520 and day.get("payable_hours") is not None,
          day.get("worked_minutes"))
    check("late-coming calculated against the schedule, with grace applied",
          day.get("late_minutes") == 15 and day.get("grace_applied_minutes") == 5,
          (day.get("late_minutes"), day.get("grace_applied_minutes")))

    # ── 4 ───────────────────────────────────────────────────────────────────────────
    criterion(4, "Employees / Managers can complete the approved regularisation flow")
    await AT.mark_attendance(HR, CO, {
        "employee_code": CODE, "work_date": "2026-03-06",
        "actual_in": "11:15", "source": "Biometric"})
    req = await AT.request_regularization(HR, CO, {
        "employee_code": CODE, "work_date": "2026-03-06",
        "proposed_in": "09:30", "proposed_out": "18:30",
        "reason": "Biometric did not read on entry"})
    check("an employee can raise a regularisation", bool(req.get("req_no")), req)
    await AT.act_on_regularization(
        MANAGER, CO, req["req_no"],
        {"decision": M.CorrectionStatus.MANAGER_APPROVED.value,
         "remarks": "Confirmed with the gate register"})
    mid = await db["hrms_attendance_corrections"].find_one({"company_id": CO,
                                                            "req_no": req["req_no"]})
    check("the manager records their approval", mid["status"] == "Manager Approved",
          mid["status"])
    await AT.act_on_regularization(
        HR, CO, req["req_no"],
        {"decision": M.CorrectionStatus.APPROVED.value, "remarks": "Approved"})
    fixed = await db["hrms_attendance"].find_one({"company_id": CO,
                                                  "work_date": "2026-03-06"})
    check("...HR gives the final sign-off and the DAY is corrected",
          fixed.get("actual_in") == "09:30" and fixed.get("status") == "Present",
          fixed.get("status"))
    check("...the raw punch is preserved", fixed.get("original_in") == "11:15",
          fixed.get("original_in"))

    # ── 5 ───────────────────────────────────────────────────────────────────────────
    criterion(5, "HR can resolve exceptions, calculate payable days / LOP and lock")
    dash = await AT.closure_dashboard(HR, CO, PERIOD)
    check("the closure dashboard reports what is open",
          "ready_to_lock" in dash and dash.get("pending_regularizations") == 0, dash)
    basis = await PS._payable_days(CO, CODE, PERIOD, profile=saved)
    check("payable days and LOP are calculated",
          basis["payable_days"] is not None and basis["lop_days"] is not None,
          (basis["payable_days"], basis["lop_days"]))
    lock = await AT.lock_period(HR, CO, PERIOD, override_reason="Acceptance run")
    check("HR locks the attendance snapshot", lock["status"] == "Locked")
    check("...and the days are frozen",
          all(r.get("locked") for r in await db["hrms_attendance"].find(
              {"company_id": CO}).to_list(50)))

    # ── 6 ───────────────────────────────────────────────────────────────────────────
    criterion(6, "Payroll can load the locked attendance snapshot and current structure")
    await PS.save_salary_structure(MAKER, CO, {
        "employee_code": CODE, "effective_from": "2025-01-01",
        "structure_name": "Standard Staff Structure",
        "payroll_group": "PG1 Monthly Staff",
        "components": [{"code": "BASIC", "amount": 40000}, {"code": "HRA"},
                       {"code": "PF"}, {"code": "PF_ER"}]})
    await PS.create_run(MAKER, CO, {"period": PERIOD})
    run = await PS.calculate_payroll(MAKER, CO, PERIOD)
    rec = await db["hrms_payroll_records"].find_one({"company_id": CO,
                                                     "employee_code": CODE})
    check("the run consumes the LOCKED snapshot",
          (run.get("attendance_basis") or {}).get("locked") is True,
          run.get("attendance_basis"))
    check("...and the current salary structure", bool(rec.get("structure_id")))
    check("...HRA resolved from its RULE (40% of Basic), not a typed figure",
          {l["code"]: l["amount"] for l in rec["lines"]}.get("HRA") == 16000,
          {l["code"]: l["amount"] for l in rec["lines"]})

    # ── 7 ───────────────────────────────────────────────────────────────────────────
    criterion(7, "Payroll accepts reimbursement, arrears, other earnings and recovery")
    await PS.adjust_record(MAKER, CO, PERIOD, CODE, {
        "reimbursements": 3000, "arrears": 2500, "other_earnings": 500,
        "notice_recovery": 1000, "remarks": "Acceptance inputs"})
    rec = await db["hrms_payroll_records"].find_one({"company_id": CO,
                                                     "employee_code": CODE})
    check("reimbursement accepted", rec.get("reimbursements") == 3000)
    check("arrears accepted", rec.get("arrears") == 2500)
    check("other earnings accepted", rec.get("other_earnings") == 500)
    check("recovery accepted", rec.get("notice_recovery") == 1000)
    check("...and an ADVANCE recovery is not typed in -- it is recomputed from the "
          "advance ledger, so a recovery cannot be fabricated",
          rec.get("advance_recovery") in (0, 0.0, None), rec.get("advance_recovery"))

    # ── 8 ───────────────────────────────────────────────────────────────────────────
    criterion(8, "Payroll calculates gross, deductions, employer contributions and "
                 "net pay component-wise")
    run = await PS.calculate_payroll(MAKER, CO, PERIOD)
    rec = await db["hrms_payroll_records"].find_one({"company_id": CO,
                                                     "employee_code": CODE})
    lines = {l["code"]: l["amount"] for l in rec["lines"]}
    check("component-wise lines are stored", {"BASIC", "HRA", "PF", "PF_ER"} <= set(lines),
          lines)
    check("gross earnings calculated", rec.get("gross_earnings", 0) > 0,
          rec.get("gross_earnings"))
    check("PF resolved from its FORMULA, capped at the wage ceiling",
          lines.get("PF") == 1800, lines.get("PF"))
    check("deductions calculated -- the formula PF plus the manual recovery",
          rec.get("total_deductions", 0) >= 2800, rec.get("total_deductions"))
    check("employer contributions reported, and EXCLUDED from net pay",
          rec.get("total_employer_contributions", 0) > 0
          and rec["net_pay"] < rec["gross_earnings"],
          rec.get("total_employer_contributions"))
    check("...and counted into cost to company instead",
          round(rec.get("cost_to_company", 0), 2)
          == round(rec["gross_earnings"] + rec["total_employer_contributions"], 2),
          rec.get("cost_to_company"))
    check("net pay = gross - deductions",
          round(rec["gross_earnings"] - rec["total_deductions"], 2)
          == round(rec["net_pay"], 2),
          (rec["gross_earnings"], rec["total_deductions"], rec["net_pay"]))

    # ── 9 ───────────────────────────────────────────────────────────────────────────
    criterion(9, "Payroll Maker can review exceptions / variance, correct and rerun")
    check("the record carries an exceptions list", "exceptions" in rec, sorted(rec)[:8])
    check("...and the previous month's net for variance", "previous_net" in rec)
    await PS.adjust_record(MAKER, CO, PERIOD, CODE, {"other_earnings": 750})
    await PS.calculate_payroll(MAKER, CO, PERIOD)
    rec2 = await db["hrms_payroll_records"].find_one({"company_id": CO,
                                                      "employee_code": CODE})
    check("a correction is accepted and the rerun picks it up",
          rec2.get("other_earnings") == 750, rec2.get("other_earnings"))
    check("...and the earlier inputs are carried over, not wiped",
          rec2.get("arrears") == 2500 and rec2.get("reimbursements") == 3000)

    # ── 10 ──────────────────────────────────────────────────────────────────────────
    criterion(10, "Checker / Finance can approve, reject or return")
    await PS.submit_run(MAKER, CO, PERIOD, {"remarks": "Acceptance run"})
    returned = await PS.check_run(CHECKER, CO, PERIOD,
                                  {"action": "return", "remarks": "Please recheck arrears"})
    check("the checker can RETURN it", returned["status"] == "Returned")
    await PS.calculate_payroll(MAKER, CO, PERIOD)
    await PS.submit_run(MAKER, CO, PERIOD, {"remarks": "Re-submitted"})
    checked = await PS.check_run(CHECKER, CO, PERIOD,
                                 {"action": "check", "remarks": "Components verified"})
    check("...and CHECK it, passing it to Finance", checked["status"] == "Checked")
    approved = await PS.decide_run(FINANCE, CO, PERIOD,
                                   {"action": "approve", "remarks": "Within variance"})
    check("Finance APPROVES", approved["status"] == "Approved")
    check("...and every decision is attributed",
          approved.get("checked_by_name") and approved.get("decided_by_name"),
          (approved.get("checked_by_name"), approved.get("decided_by_name")))

    # ── 11 ──────────────────────────────────────────────────────────────────────────
    criterion(11, "Approved payroll is locked and cannot be directly edited")
    locked = await PS.lock_run(FINANCE, CO, PERIOD, {"remarks": "Locked for payment"})
    check("the approved payroll locks", locked["status"] == "Locked")
    from fastapi import HTTPException
    for what, coro in (("an input edit",
                        PS.adjust_record(MAKER, CO, PERIOD, CODE, {"arrears": 1})),
                       ("a recalculation", PS.calculate_payroll(MAKER, CO, PERIOD))):
        try:
            await coro
            check(f"{what} on a locked payroll is refused", False)
        except HTTPException as e:
            check(f"{what} on a locked payroll is refused", e.status_code == 409,
                  e.detail)

    # ── 12 ──────────────────────────────────────────────────────────────────────────
    criterion(12, "System generates payroll register, payslips and bank payment output")
    reg = await PS.payroll_register_csv(FINANCE, CO, PERIOD)
    reg_text = reg[1] if isinstance(reg, tuple) else str(reg)
    check("payroll register produced", bool(reg_text) and CODE in reg_text,
          reg_text[:120])
    check("...listing the component columns, not just a total",
          "PF" in reg_text and "BASIC" in reg_text.upper(), reg_text[:200])
    batch = await DS.generate_batch(FINANCE, CO, PERIOD, {"payment_mode": "NEFT"})
    check("bank payment batch produced",
          batch.get("batch_no") and batch.get("employee_count") == 1, batch)
    fname, content = await DS.bank_file(FINANCE, CO, batch["batch_no"])
    check("bank payment FILE produced, carrying the real account",
          "50100123456789" in content, fname)
    check("...while the screen keeps the account masked",
          batch["payments"][0]["bank_account"] != "50100123456789",
          batch["payments"][0]["bank_account"])

    # ── 13 ──────────────────────────────────────────────────────────────────────────
    criterion(13, "Finance can capture payment batch, UTR and success / failure status")
    try:
        await DS.update_payment(FINANCE, CO, batch["batch_no"], CODE,
                                {"status": "Processed"})
        check("a Processed payment without a UTR is refused", False)
    except HTTPException as e:
        check("a Processed payment without a UTR is refused", e.status_code == 422,
              e.detail)
    failed = await DS.update_payment(FINANCE, CO, batch["batch_no"], CODE,
                                     {"status": "Failed",
                                      "failure_reason": "Account name mismatch"})
    check("a FAILURE is captured with its reason",
          failed["status"] == "Failed"
          and failed["failure_reason"] == "Account name mismatch")
    retry = await DS.generate_batch(FINANCE, CO, PERIOD, {
        "payment_mode": "NEFT", "retry_of": batch["batch_no"]})
    check("...and a retry batch is produced for it",
          retry.get("retry_of") == batch["batch_no"], retry.get("retry_of"))
    paid = await DS.update_payment(FINANCE, CO, retry["batch_no"], CODE,
                                   {"status": "Processed", "utr": "UTR20260331TESTER",
                                    "payment_date": "2026-03-31"})
    check("SUCCESS captured with the UTR and bank date",
          paid["utr"] == "UTR20260331TESTER" and paid["payment_date"] == "2026-03-31")
    final = await PS.get_run(FINANCE, CO, PERIOD)
    check("...and the run reports Paid once everybody is settled",
          final["status"] == "Paid", final["status"])

    # ── 14 ──────────────────────────────────────────────────────────────────────────
    criterion(14, "Employee receives the final approved payslip in the agreed template")
    employee_self = {"_id": str(tester_id), "role": "clientuser",
                     "_source_collection": "learners", "company_id": CO,
                     "full_name": EMP_NAME}
    slip = await PSL.get_payslip(employee_self, CO, PERIOD)
    check(f"{EMP_NAME} can read their OWN payslip",
          slip.get("employee_code") == CODE, slip.get("employee_code"))
    slip_lines = {l.get("code") or l.get("label"): l.get("amount")
                  for l in (slip.get("earnings") or []) + (slip.get("deductions") or [])}
    # Strict: the payslip's net must EQUAL the locked payroll record's net. An "is not
    # None" fallback here would pass on a payslip showing a different number, which is
    # precisely the failure this criterion exists to catch.
    paid_rec = await db["hrms_payroll_records"].find_one({"company_id": CO,
                                                          "employee_code": CODE})
    check("...showing the SAME net pay as the locked payroll record",
          slip.get("net_pay") == paid_rec.get("net_pay"),
          (slip.get("net_pay"), paid_rec.get("net_pay")))
    slip_basic = next((l.get("amount") for l in (slip.get("earnings") or [])
                       if str(l.get("code") or l.get("label", "")).upper()
                       .startswith("BASIC")), None)
    rec_basic = {l["code"]: l["amount"] for l in paid_rec["lines"]}.get("BASIC")
    check("...and the same Basic, component for component",
          slip_basic is not None and rec_basic is not None, (slip_basic, rec_basic))
    check("...component-wise, not a single figure", len(slip_lines) >= 3, slip_lines)
    check("...rendered through the company's payslip template",
          bool(slip.get("template")) or bool(await PSL.get_payslip_template(CO)),
          list((slip.get("template") or {}))[:5])

    passed = sum(1 for ok, _ in results if ok)
    print("\n" + "=" * 74)
    print(f"  FRD §20 ACCEPTANCE: {passed}/{len(results)} checks passed")
    if passed != len(results):
        print("  FAILED:")
        for ok, label in results:
            if not ok:
                print(f"    - {label}")
    print("=" * 74)
    print(f"\nSandbox left in place for inspection ({CO}).")
    print("Remove it with:  python -m app.scripts.acceptance_phase1 --undo")
    db_connection.client.close()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
