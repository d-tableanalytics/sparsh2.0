"""Phase 1 FRD (Configurable Employee, Attendance & Payroll) -- the controls it asks for.

  1. Daily attendance measures: early minutes, grace applied, payable hours, payable day /
     LOP fraction (FRD §6).
  2. Shift master: versioned rules by effective date, applicability priority, weekly-off
     patterns incl. "2nd Saturday" (FRD §5, §23, §26).
  3. Employee master: duplicate check, company lists, effective-dated history with future
     changes scheduled then applied, sensitive fields masked (FRD §3, §4, §18).
  4. Configurable fields: type / options / mandatory / retire-not-delete (FRD §21-22).
  5. Salary components: percentage of a base, circular dependency refused (FRD §24-25).
  6. Payroll: locked attendance required, weekly offs paid, DOJ proration, maker-checker
     (submit / return / approve / lock), critical exceptions block submission, variance,
     post-lock arrear carried into the next period (FRD §10-12, §18).
  7. Disbursal: batch only from a locked payroll, missing bank skipped, UTR required,
     failed payment retried, run marked Paid (FRD §13).
  8. Payslip: not released to the employee before lock; template version frozen (FRD §14).

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_frd_phase1   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

results: list[bool] = []


def check(label: str, condition: bool, extra=None) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + ("" if condition or extra is None else f"  -- {str(extra)[:300]}"))
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


async def expect(label, coro, status, needle=""):
    from fastapi import HTTPException
    try:
        await coro
    except HTTPException as e:
        return check(f"{label} -> {status}", e.status_code == status
                     and needle.lower() in str(e.detail).lower())
    return check(f"{label} -> {status} (no error raised)", False)


from app.services.hrms.tests.test_payroll_live_findings import FakeCollection  # noqa: E402

CO = "C1"


async def main() -> int:
    from bson import ObjectId

    import app.db.mongodb as mongo
    from app.models import hrms as M

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    import app.services.hrms_attendance_rules_service as AR
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_audit_service as AU
    import app.services.hrms_disbursal_service as DS
    import app.services.hrms_employee_master_service as EM
    import app.services.hrms_id_service as ID
    import app.services.hrms_payroll_service as PR
    import app.services.hrms_payslip_service as PS
    import app.services.hrms_shift_service as SH
    for mod in (AR, AT, AU, DS, EM, ID, PR, PS, SH):
        mod.get_collection = getter

    # Payroll-data visibility is a role question answered elsewhere; here every actor but the
    # employee is a payroll role.
    import app.utils.hrms_access as HA
    HA.sees_all_payroll = lambda u: u.get("role") != "employee"
    HR = {"_id": "hr-1", "role": "admin", "full_name": "Dummy HR"}
    CHECKER = {"_id": "fin-1", "role": "admin", "full_name": "Dummy Finance"}

    # ── 1 ──
    section("1. Daily attendance measures (FRD §6)")
    d = M.compute_daily_status(scheduled_in="09:30", scheduled_out="18:30", actual_in="09:33",
                               actual_out="18:00", daily_grace_minutes=5,
                               half_day_threshold_minutes=240, break_minutes=60)
    check("arrived 3 min after start: within grace, 3 grace minutes applied, not late",
          d["late_minutes"] == 0 and d["grace_applied_minutes"] == 3)
    check("left 30 min early -> early_minutes 30", d["early_minutes"] == 30)
    check("worked 507 min, payable = worked - 60 min break = 447 min (7.45 h)",
          d["worked_minutes"] == 507 and d["payable_minutes"] == 447 and d["payable_hours"] == 7.45)
    check("Present -> payable day 1, LOP 0", d["payable_day"] == 1 and d["lop_fraction"] == 0)
    h = M.compute_daily_status(scheduled_in="09:30", scheduled_out="18:30", actual_in="09:30",
                               actual_out="15:00", daily_grace_minutes=5,
                               half_day_threshold_minutes=240, min_hours=8)
    check("5.5 h worked against 8 minimum hours -> Half Day, LOP 0.5",
          h["status"] == "Half Day" and h["lop_fraction"] == 0.5)
    o = M.compute_daily_status(scheduled_in="09:30", scheduled_out="18:30", actual_in="09:50",
                               actual_out=None, daily_grace_minutes=5,
                               half_day_threshold_minutes=240)
    check("in without out -> flagged missing_out_punch, late 15", o["missing_out_punch"]
          and o["late_minutes"] == 15)

    # ── 2 ──
    section("2. Shift master: versions, applicability, weekly offs (FRD §5, §23)")
    today = date.today()
    tomorrow = (today + timedelta(days=1)).isoformat()
    await SH.save_shift(HR, CO, {"code": "gen", "name": "General", "start": "09:30",
                                 "end": "18:30", "daily_grace_minutes": 5,
                                 "weekly_off_pattern": ["Sunday", "Saturday#2"],
                                 "applicability": {"locations": ["Pune"]}})
    await SH.save_shift(HR, CO, {"code": "GEN", "daily_grace_minutes": 10,
                                 "effective_from": tomorrow, "reason": "Policy change"})
    shift = await SH.get_shift(CO, "GEN")
    check("code normalised to GEN, two versions kept", shift["code"] == "GEN"
          and len(shift["versions"]) == 2)
    check("today's version keeps grace 5", SH.version_on(shift, today.isoformat())[
        "daily_grace_minutes"] == 5)
    check("tomorrow's version has grace 10 and inherits the times",
          SH.version_on(shift, tomorrow)["daily_grace_minutes"] == 10
          and SH.version_on(shift, tomorrow)["start"] == "09:30")
    await expect("a back-dated change without a reason", SH.save_shift(HR, CO, {
        "code": "GEN", "daily_grace_minutes": 15,
        "effective_from": (today - timedelta(days=3)).isoformat()}), 422, "needs a reason")
    past = (today - timedelta(days=40)).isoformat()
    store.setdefault(M.COLL_ATTENDANCE_LOCKS, FakeCollection()).docs.append(
        {"company_id": CO, "period": past[:7], "status": "Locked"})
    await expect("a back-dated change into a locked month", SH.save_shift(HR, CO, {
        "code": "GEN", "daily_grace_minutes": 15, "effective_from": past,
        "reason": "x"}), 422, "locked")
    store[M.COLL_ATTENDANCE_LOCKS].docs.clear()
    pune = {"employee_code": "E1", "work_location": "Pune"}
    mumbai = {"employee_code": "E2", "work_location": "Mumbai"}
    r_pune = await SH.resolve_rules(CO, pune, today.isoformat())
    r_mum = await SH.resolve_rules(CO, mumbai, today.isoformat())
    check("a Pune employee gets GEN by applicability", r_pune["shift_code"] == "GEN"
          and r_pune["rule_source"] == "policy applicability")
    check("a Mumbai employee falls back to the company timing", r_mum["shift_code"] is None)
    check("2nd Saturday of Nov 2026 (14th) is off; 1st (7th) is not",
          SH.is_weekly_off(["Sunday", "Saturday#2"], "2026-11-14")
          and not SH.is_weekly_off(["Sunday", "Saturday#2"], "2026-11-07"))

    # ── 3 ──
    section("3. Employee master (FRD §3, §4, §18)")
    profiles = store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection())
    profiles.docs.extend([
        {"_id": ObjectId(), "company_id": CO, "employee_code": "E1", "user_id": "u1",
         "pan": "ABCDE1234F", "personal_email": "asha@example.com", "employment_status": "Active",
         "work_location": "Pune", "bank_account": "123456789012", "bank_ifsc": "HDFC0001234",
         "joined_on": "2025-01-01", "first_name": "Asha"},
        {"_id": ObjectId(), "company_id": CO, "employee_code": "E2", "user_id": "u2",
         "employment_status": "Active", "work_location": "Mumbai", "joined_on": "2025-01-16"},
    ])
    dup = await EM.find_duplicates(CO, {"pan": "abcde1234f",
                                        "personal_email": "ASHA@example.com"},
                                   exclude_user_id="u2")
    check("PAN and email found on E1 (case-insensitive)",
          {x["field"] for x in dup} == {"pan", "personal_email"})
    check("...but not when it is E1's own record",
          not await EM.find_duplicates(CO, {"pan": "ABCDE1234F"}, exclude_user_id="u1"))
    await EM.save_master_lists(HR, CO, {"lists": {"locations": ["Pune", "Mumbai", "pune"]}})
    lists = await EM.get_master_lists(CO)
    check("list values de-duplicated (case-insensitive)", lists["locations"] == ["Pune", "Mumbai"])
    clean = {"work_location": "mumbai"}
    await EM.validate_master_values(CO, clean)
    check("a list value is stored in the list's spelling", clean["work_location"] == "Mumbai")
    await expect("a location not on the list", EM.validate_master_values(
        CO, {"work_location": "Delhi"}), 422, "not in the company")
    check("unconfigured list accepts free text",
          await EM.validate_master_values(CO, {"grade": "G7"}) is None)
    e1 = profiles.docs[0]
    await EM.record_changes(HR, CO, e1, {"work_location": ("Pune", "Mumbai")},
                            effective_from=tomorrow, reason="Transfer", status=M.HISTORY_SCHEDULED)
    check("a future change is scheduled, not applied", e1["work_location"] == "Pune")
    hist = store[M.COLL_EMPLOYEE_HISTORY].docs
    hist[-1]["effective_from"] = today.isoformat()        # its day arrives
    applied = await EM.apply_due_changes(CO)
    check("on its day it is applied and the history row says so",
          applied == 1 and e1["work_location"] == "Mumbai" and hist[-1]["status"] == "Applied")
    view = EM.mask_view({"bank_account": "123456789012", "pan": "ABCDE1234F"})
    check("bank account and PAN masked for viewers without sensitive access",
          view["bank_account"] == "XXXX9012" and view["pan"] == "XXXX234F")

    # ── 4 ──
    section("4. Configurable fields (FRD §21-22)")
    f = await EM.save_field_definition(HR, CO, {
        "module": "employee", "code": "psc_status", "label": "PSC status",
        "data_type": "single_select", "mandatory": True,
        "options": [{"value": "Cleared"}, {"value": "Pending"}]})
    check("a new field starts as Draft", f["status"] == "Draft")
    await expect("a Draft field takes no values", EM.validate_custom_values(
        CO, "employee", {"psc_status": "Cleared"}), 422, "draft")
    await EM.set_field_status(HR, CO, "employee", "psc_status", {"status": "Active"})
    await expect("mandatory once active", EM.validate_custom_values(
        CO, "employee", {}, enforce_mandatory=True), 422, "required")
    await expect("an option that does not exist", EM.validate_custom_values(
        CO, "employee", {"psc_status": "Maybe"}), 422, "options")
    ok = await EM.validate_custom_values(CO, "employee", {"psc_status": "Cleared"})
    check("a valid option is accepted", ok == {"psc_status": "Cleared"})
    e1["custom_fields"] = ok
    await expect("data type cannot change once values exist", EM.save_field_definition(
        HR, CO, {"module": "employee", "code": "psc_status", "label": "PSC status",
                 "data_type": "text"}), 409, "data type")
    await expect("a used field cannot be deleted", EM.set_field_status(
        HR, CO, "employee", "psc_status", {"status": "Deleted"}), 409, "retire")
    retired = await EM.set_field_status(HR, CO, "employee", "psc_status", {"status": "Retired"})
    check("...it is retired instead, values kept", retired["status"] == "Retired"
          and e1["custom_fields"]["psc_status"] == "Cleared")

    # ── 5 ──
    section("5. Salary components (FRD §24-25)")
    for c in ({"code": "BASIC", "name": "Basic", "component_type": "Earning", "sequence": 10},
              {"code": "HRA", "name": "HRA", "component_type": "Earning", "sequence": 20,
               "calculation_method": "Percentage", "calculation_base": "BASIC", "percentage": 40},
              {"code": "SPECIAL", "name": "Special", "component_type": "Earning", "sequence": 30},
              {"code": "PT", "name": "Professional Tax", "component_type": "Deduction"},
              {"code": "EPF_ER", "name": "Employer PF", "component_type": "Employer Contribution",
               "calculation_method": "Percentage", "calculation_base": "BASIC", "percentage": 12,
               "sequence": 40}):
        await PR.save_salary_component(HR, CO, c)
    await expect("BASIC as a % of HRA (circular)", PR.save_salary_component(HR, CO, {
        "code": "BASIC", "name": "Basic", "component_type": "Earning",
        "calculation_method": "Percentage", "calculation_base": "HRA", "percentage": 50}),
        422, "depend on itself")
    s = await PR.save_salary_structure(HR, CO, {
        "employee_code": "E1", "effective_from": "2025-01-01", "revision_reason": "Joining",
        "structure_name": "Staff", "components": [
            {"code": "BASIC", "amount": 30000}, {"code": "HRA"}, {"code": "SPECIAL", "amount": 8000},
            {"code": "PT", "amount": 200}, {"code": "EPF_ER"}]})
    lines = {l["code"]: l["amount"] for l in s["components"]}
    check("HRA = 40% of Basic = 12,000; employer PF = 12% = 3,600",
          lines["HRA"] == 12000 and lines["EPF_ER"] == 3600)
    check("monthly gross 50,000, employer 3,600, annual CTC 6,43,200",
          s["monthly_gross"] == 50000 and s["monthly_employer_contributions"] == 3600
          and s["annual_ctc"] == 643200)
    check("approval not required -> Active, approver recorded", s["status"] == "Active"
          and s["approved_by"] == "hr-1")
    await PR.save_salary_structure(HR, CO, {"employee_code": "E2", "effective_from": "2025-01-01",
                                            "components": [{"code": "BASIC", "amount": 20000}]})

    # ── 6 ──
    section("6. Payroll run (FRD §10-12, §18)")
    P = "2025-02"
    att = store.setdefault(M.COLL_ATTENDANCE, FakeCollection())
    for dd in range(1, 29):
        ds = f"{P}-{dd:02d}"
        if SH.is_weekly_off(["Sunday"], ds):
            continue                                    # Sundays left blank on purpose
        att.docs.append({"company_id": CO, "employee_code": "E1", "work_date": ds,
                         "status": "Present"})
        att.docs.append({"company_id": CO, "employee_code": "E2", "work_date": ds,
                         "status": "Absent" if dd in (3, 4) else "Present"})   # Mon, Tue
    await PR.create_run(HR, CO, {"period": P})
    await expect("calculate before attendance is locked", PR.calculate_payroll(HR, CO, P),
                 409, "not locked")
    store[M.COLL_ATTENDANCE_LOCKS].docs.append({"company_id": CO, "period": P, "status": "Locked"})
    await PR.calculate_payroll(HR, CO, P)
    recs = {r["employee_code"]: r for r in store[M.COLL_PAYROLL_RECORDS].docs}
    r1, r2 = recs["E1"], recs["E2"]
    check("E1: blank Sundays count as paid weekly offs -> full month, 0 LOP",
          r1["payable_days"] == 28 and r1["lop_days"] == 0 and r1["weekly_off_days"] == 4)
    check("E1 gross 50,000 (component-wise), PT 200, employer PF 3,600 outside net",
          r1["gross_earnings"] == 50000 and r1["total_deductions"] == 200
          and r1["net_pay"] == 49800 and r1["total_employer_contributions"] == 3600)
    check("E2: 2 absences -> 2 LOP days", r2["lop_days"] == 2 and r2["payable_days"] == 26)
    check("E2 has no bank details -> a NO_BANK warning",
          any(x["code"] == "NO_BANK" for x in r2["exception_details"]))
    await PR.adjust_record(HR, CO, P, "E1", {"tds": 1000, "reimbursements": 500})
    await PR.set_adjustments(HR, CO, P, "E1", {"adjustments": [
        {"code": "SPECIAL", "amount": 750, "reason": "Spot award", "reference": "MAIL-12"}]})
    await PR.calculate_payroll(HR, CO, P)                # rerun keeps the maker's inputs
    r1 = next(r for r in store[M.COLL_PAYROLL_RECORDS].docs if r["employee_code"] == "E1")
    check("a rerun KEEPS hand-entered TDS, reimbursement and the reasoned adjustment",
          r1["tds"] == 1000 and r1["reimbursements"] == 500
          and r1["adjustments"][0]["reason"] == "Spot award")
    check("net = 50,000 + 500 + 750 - 200 - 1,000 = 50,050", r1["net_pay"] == 50050)
    await expect("checker decides before submission", PR.decide_run(
        CHECKER, CO, P, {"action": "approve"}), 409, "submitted")
    await PR.submit_run(HR, CO, P, {})
    await expect("the maker cannot check their own payroll", PR.decide_run(
        HR, CO, P, {"action": "approve"}), 403, "maker-checker")
    await expect("a return needs a reason", PR.decide_run(
        CHECKER, CO, P, {"action": "return"}), 422, "why")
    await PR.decide_run(CHECKER, CO, P, {"action": "return", "remarks": "Recheck TDS"})
    run = await PR.get_run(HR, CO, P)
    check("returned to the maker", run["status"] == "Returned")
    await PR.adjust_record(HR, CO, P, "E1", {"tds": 900})
    await PR.calculate_payroll(HR, CO, P)
    await PR.submit_run(HR, CO, P, {})
    await PR.decide_run(CHECKER, CO, P, {"action": "approve"})
    check("approved is NOT locked", (await PR.get_run(HR, CO, P))["status"] == "Approved")
    await expect("edits after approval", PR.adjust_record(HR, CO, P, "E1", {"tds": 1}),
                 409, "with the maker")
    await PS.save_payslip_template(HR, CO, {"company_name": "Sparsh Magic LLP",
                                            "footer_note": "v1"})
    await PR.lock_run(CHECKER, CO, P, {})
    run = await PR.get_run(HR, CO, P)
    check("locked by Finance with the payslip template version frozen",
          run["status"] == "Locked" and run["payslip_template_version"] == 1)
    check("approval trail has maker, checker and finance steps",
          [t["stage"] for t in run["approval_trail"]][-3:] == ["Maker", "Checker", "Finance"])
    await expect("calculating a locked payroll", PR.calculate_payroll(HR, CO, P), 409,
                 "post-lock")
    adj = await PR.create_post_lock_adjustment(HR, CO, P, {
        "employee_code": "E1", "adjustment_type": "Arrear", "amount": 1200,
        "reason": "Missed increment"})
    check("post-lock arrear lands in the next period", adj["target_period"] == "2025-03")

    # next month: the arrear is carried in, and variance against Feb is computed
    P2 = "2025-03"
    for dd in range(1, 32):
        att.docs.append({"company_id": CO, "employee_code": "E1", "work_date": f"{P2}-{dd:02d}",
                         "status": "Present"})
    store[M.COLL_ATTENDANCE_LOCKS].docs.append({"company_id": CO, "period": P2, "status": "Locked"})
    await PR.create_run(HR, CO, {"period": P2})
    await PR.calculate_payroll(HR, CO, P2)
    m1 = next(r for r in store[M.COLL_PAYROLL_RECORDS].docs
              if r["employee_code"] == "E1" and r["period"] == P2)
    check("the Feb arrear is an adjustment line in March, with its source",
          any(a.get("carry_forward_id") and a["amount"] == 1200 for a in m1["adjustments"]))
    check("previous-month net and variance are on the record",
          m1["previous_net"] is not None and m1["variance_amount"] is not None)

    # ── 7 ──
    section("7. Disbursal (FRD §13)")
    await expect("a batch from an unlocked payroll", DS.generate_batch(
        CHECKER, CO, P2, {"payment_mode": "NEFT"}), 409, "locked")
    batch = await DS.generate_batch(CHECKER, CO, P, {"payment_mode": "NEFT"})
    check("batch numbered PAYB-, one payment (E2 skipped: no bank details)",
          batch["batch_no"].startswith("PAYB-") and batch["employee_count"] == 1
          and batch["skipped"][0]["employee_code"] == "E2")
    check("account masked in the batch view", batch["payments"][0]["bank_account"] == "XXXX9012")
    name, text = await DS.bank_file(CHECKER, CO, batch["batch_no"])
    check("bank file carries the full account number", "123456789012" in text)
    bn = batch["batch_no"]
    await expect("processed without UTR", DS.update_payment(
        CHECKER, CO, bn, "E1", {"status": "Processed", "payment_date": "2025-03-01"}), 422, "utr")
    await DS.update_payment(CHECKER, CO, bn, "E1", {"status": "Failed",
                                                    "failure_reason": "Account closed"})
    retry = await DS.generate_batch(CHECKER, CO, P, {"payment_mode": "NEFT", "retry_of": bn})
    check("a retry batch picks up the failed payment", retry["employee_count"] == 1
          and retry["retry_of"] == bn)
    await DS.update_payment(CHECKER, CO, retry["batch_no"], "E1", {
        "status": "Processed", "utr": "UTR123", "payment_date": "2025-03-02"})
    run = await PR.get_run(HR, CO, P)
    summary = await DS.payment_summary(CO, P)
    check("E1 paid; E2 unpaid (no bank) -> run stays Locked, 1 unpaid",
          summary["paid"] == 1 and summary["unpaid"] == 1 and run["status"] == "Locked")
    await expect("closing with unpaid employees and no reason", PR.close_run(
        CHECKER, CO, P, {}), 409, "not yet paid")
    await PR.close_run(CHECKER, CO, P, {"remarks": "E2 paid by cheque outside the batch"})
    check("closed with a reason", (await PR.get_run(HR, CO, P))["status"] == "Closed")

    # ── 8 ──
    section("8. Payslip release and template (FRD §14)")
    await PS.save_payslip_template(HR, CO, {"company_name": "Sparsh Magic LLP",
                                            "footer_note": "v2"})
    slip = await PS.get_payslip(HR, CO, P, "E1")
    check("the Feb payslip keeps template v1 although v2 now exists",
          slip["template"]["version"] == 1 and slip["template"]["footer_note"] == "v1")
    check("lines come from the final payroll; employer PF hidden by template default",
          any(e["label"] == "HRA" and e["amount"] == 12000 for e in slip["earnings"])
          and slip["employer_contributions"] == [])
    check("net pay in words", slip["net_pay_words"].startswith("Rupees Fifty Thousand"))
    import app.services.hrms_payslip_service as PSmod
    employee = {"_id": "u2", "role": "employee"}
    orig = PSmod._resolve_employee_code

    async def own(actor, company_id, requested):
        return "E2"
    PSmod._resolve_employee_code = own
    try:
        await expect("an employee cannot see an unreleased (Calculated) March payslip",
                     PS.get_payslip(employee, CO, P2), 404, "not released")
        s2 = await PS.get_payslip(employee, CO, P)
        check("...but sees the closed February one", s2["employee_code"] == "E2")
    finally:
        PSmod._resolve_employee_code = orig

    # ── 9 ──
    section("9. LOP sandwich rule and net rounding (FRD §23 LOP, §24 Rounding)")
    P3 = "2026-07"   # 1st = Wednesday; Sundays 5/12/19/26
    cal = {"days": {f"{P3}-{d:02d}": "Weekly Off" for d in (5, 12, 19, 26)}}
    nobody = await PR._payable_days(CO, "E-NONE", P3, {}, cal, sandwich=True)
    check("no attendance at all: every Sunday is sandwiched -> 0 payable, 31 LOP",
          nobody["payable_days"] == 0 and nobody["sandwiched_off_days"] == 4)
    old = await PR._payable_days(CO, "E-NONE", P3, {}, cal, sandwich=False)
    check("...without the rule the 4 Sundays would have been paid", old["payable_days"] == 4)
    att.docs.extend({"company_id": CO, "employee_code": "E-PART", "work_date": f"{P3}-{d:02d}",
                     "status": "Present"} for d in range(1, 11) if d != 5)
    part = await PR._payable_days(CO, "E-PART", P3, {}, cal, sandwich=True)
    check("worked 1-10 then nothing: Sunday 5th paid, 12/19/26 sandwiched",
          part["sandwiched_off_days"] == 3 and part["payable_days"] == 10)
    check("net rounding to the rupee keeps the adjustment",
          PR._net_rounding({"net_pay": 1234.56}, "Nearest") ==
          {"net_pay": 1235.0, "net_rounding_adjustment": 0.44})

    # ── 10 ──
    section("10. Formula + slab components, dependency check, simulation (FRD §24-§25)")
    await PR.save_salary_component(HR, CO, {
        "code": "ESI_EE", "name": "ESI (Employee)", "component_type": "Deduction", "sequence": 80,
        "calculation_method": "Formula",
        "formula": "IF(GROSS > 21000, 0, ROUND(GROSS * 0.0075, 0))"})
    await PR.save_salary_component(HR, CO, {
        "code": "PT_SLAB", "name": "Professional Tax", "component_type": "Deduction",
        "sequence": 90, "calculation_method": "Slab", "calculation_base": "GROSS",
        "slabs": [{"upto": 7500, "amount": 0}, {"upto": 10000, "amount": 175},
                  {"upto": None, "amount": 200}]})
    await expect("a formula reading an unknown name", PR.save_salary_component(HR, CO, {
        "code": "BAD", "name": "Bad", "component_type": "Earning",
        "calculation_method": "Formula", "formula": "SALARY * 2"}), 422, "unknown name")
    await expect("a formula calling code", PR.save_salary_component(HR, CO, {
        "code": "BAD", "name": "Bad", "component_type": "Earning",
        "calculation_method": "Formula", "formula": "__import__('os')"}), 422, "")
    await PR.save_salary_component(HR, CO, {
        "code": "LOOP_A", "name": "Loop A", "component_type": "Earning",
        "calculation_method": "Formula", "formula": "BASIC * 0.1"})
    await expect("a formula loop through two components", PR.save_salary_component(HR, CO, {
        "code": "BASIC", "name": "Basic", "component_type": "Earning", "sequence": 10,
        "calculation_method": "Formula", "formula": "LOOP_A * 2"}), 422, "depend on itself")
    meta = {c["code"]: c for c in await PR.list_salary_components(HR, CO)}
    low = PR.resolve_lines([{"code": "BASIC", "amount": 12000}, {"code": "ESI_EE"},
                            {"code": "PT_SLAB"}], meta)
    amt = {l["code"]: l["amount"] for l in low}
    check("ESI formula: 0.75% of 12,000 gross = 90; PT slab for 12,000 = 200",
          amt["ESI_EE"] == 90 and amt["PT_SLAB"] == 200, amt)
    high = {l["code"]: l["amount"] for l in PR.resolve_lines(
        [{"code": "BASIC", "amount": 30000}, {"code": "ESI_EE"}, {"code": "PT_SLAB"}], meta)}
    check("ESI formula above the ceiling = 0", high["ESI_EE"] == 0, high)
    mid = {l["code"]: l["amount"] for l in PR.resolve_lines(
        [{"code": "BASIC", "amount": 9000}, {"code": "PT_SLAB"}], meta)}
    check("PT slab for 9,000 = 175", mid["PT_SLAB"] == 175, mid)
    sim = await PR.simulate_component(HR, CO, "HRA", {"percentage": 50})
    e1sim = next((r for r in sim["employees"] if r["employee_code"] == "E1"), None)
    check("simulating HRA 40% -> 50% shows E1's HRA 12,000 -> 15,000, nothing saved",
          e1sim and e1sim["components"]["HRA"] == {"old": 12000, "new": 15000}
          and meta["HRA"]["percentage"] == 40, sim)
    check("simulation lists the components that depend on BASIC",
          {"HRA", "EPF_ER", "LOOP_A"} <= set((await PR.simulate_component(
              HR, CO, "BASIC", {}))["dependants"]))

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
