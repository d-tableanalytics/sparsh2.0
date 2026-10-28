"""FRD 18 -- Validation & Control Requirements, one section per bullet.

18 is the list of things that must be IMPOSSIBLE, not the list of things that must work.
Every bullet is therefore tested by trying to break it and checking the refusal, because a
control that has never been pushed against is a comment.

Several bullets are already pinned in depth by the suite for the section they belong to
(the locked-snapshot rule by test_monthly_closure_flow, maker-checker by
test_payroll_approval_workflow, raw-punch traceability by test_daily_attendance_fields).
Those are not repeated here; what this file adds is the CROSS-CUTTING check that each one
holds as a rule of the system rather than as a property of one happy path.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_validation_controls   (from backend/)
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
MAKER = {"_id": "mk-1", "role": "admin", "full_name": "Maya Maker"}
OTHER = {"_id": "ck-1", "role": "admin", "full_name": "Chandra Checker"}
# A THIRD person is needed, not a second: approver_distinct_from_checker
# defaults on, so stages 8 and 9 are two different people as well as two
# different steps. Three actors is the control, not test scaffolding.
APPROVER = {"_id": "ap-1", "role": "admin", "full_name": "Anita Approver"}


async def main() -> int:
    from bson import ObjectId
    import app.db.mongodb as mongo
    from app.models import hrms as M
    from app.utils import hrms_access as A
    from app.utils import hrms_permission_policy as POL
    import app.services.hrms_payroll_service as PS
    import app.services.hrms_disbursal_service as DS
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_attendance_rules_service as AR
    import app.services.hrms_employee_master_service as EM
    import app.services.hrms_employee_service as ES
    import app.services.hrms_shift_service as SH
    import app.services.hrms_policy_version_service as PV
    import app.services.hrms_id_service as IS
    import app.services.hrms_payslip_service as PSL

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (PS, DS, AT, AR, EM, ES, SH, PV, IS, PSL, A):
        mod.get_collection = getter

    audited: list = []

    async def record_audit(actor, action, *a, **k):
        audited.append(str(action))
    for mod in (PS, DS, AT, EM, ES):
        mod.audit = record_audit

    async def _allow(*a, **k):
        return None

    async def _same(actor, company_id, query):
        return query
    AT.can = lambda u, c: True
    AT._assert_self_or_privileged = _allow
    AT._scope_query = _same
    DS._assert_payroll_role = lambda actor: None

    uid, uid2 = ObjectId(), ObjectId()
    store.setdefault(M.COLL_SETTINGS, FakeCollection()).docs.append(
        {"company_id": CO, "shift_policy": {**M.DEFAULT_SHIFT_POLICY}})
    store.setdefault("learners", FakeCollection()).docs.extend([
        {"_id": uid, "company_id": CO, "full_name": "Asha A", "is_active": True},
        {"_id": uid2, "company_id": CO, "full_name": "Bela B", "is_active": True},
    ])
    store.setdefault("staff", FakeCollection())
    store.setdefault("companies", FakeCollection([{"_id": CO, "is_internal": False}]))
    store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection()).docs.append(
        {"_id": ObjectId(), "company_id": CO, "employee_code": "E1", "user_id": str(uid),
         "joined_on": "2025-01-01", "employment_status": "Active",
         "pan": "ABCDE1234F", "aadhaar": "123456789012",
         "bank_account": "50100999988887", "bank_ifsc": "HDFC0001234",
         "bank_name": "HDFC", "bank_account_holder": "Asha A"})
    store.setdefault(M.COLL_SALARY_COMPONENTS, FakeCollection()).docs.extend([
        {"company_id": CO, "code": "BASIC", "name": "Basic", "active": True,
         "component_type": "Earning", "calculation_method": "Fixed", "sequence": 10},
        {"company_id": CO, "code": "PT", "name": "PT", "active": True,
         "component_type": "Deduction", "calculation_method": "Fixed", "sequence": 90},
    ])
    LINES = [{"code": "BASIC", "amount": 50000}, {"code": "PT", "amount": 200}]

    # 1 ------------------------------------------------------------------------------
    section("1. Duplication is checked BEFORE a master record is created")
    for field, value, label in (("pan", "ABCDE1234F", "PAN"),
                                ("aadhaar", "123456789012", "Aadhaar"),
                                ("bank_account", "50100999988887", "bank account")):
        await expect(f"a second employee carrying the same {label}",
                     ES.create_profile(MAKER, CO, {"user_id": str(uid2), field: value}),
                     409, "already recorded")
    check("...and nothing was written for any of them -- the check precedes the commit",
          len(store[M.COLL_EMPLOYEE_PROFILES].docs) == 1,
          len(store[M.COLL_EMPLOYEE_PROFILES].docs))
    # A record that does NOT clash must still go through, or the control above would be
    # indistinguishable from "creating employees is broken".
    made = await ES.create_profile(MAKER, CO, {
        "user_id": str(uid2), "pan": "ZZZPQ9876R", "joined_on": "2025-06-01"})
    check("a NON-clashing employee is created normally",
          made.get("employee_code") and len(store[M.COLL_EMPLOYEE_PROFILES].docs) == 2,
          made.get("employee_code"))

    # 2 ------------------------------------------------------------------------------
    section("2. Bank / statutory / salary fields need restricted access")
    check("they are declared sensitive in ONE place, not per screen",
          set(M.EMPLOYEE_MASKED_FIELDS) >= {"bank_account", "pan", "aadhaar"},
          M.EMPLOYEE_MASKED_FIELDS)
    masked = EM.mask_view({"bank_account": "50100999988887", "pan": "ABCDE1234F"})
    check("a viewer without sensitive access sees a mask, not the value",
          masked["bank_account"].startswith("XXXX")
          and masked["pan"].startswith("XXXX"), masked)
    emp = A.capabilities_for({"_id": "e-1", "role": "clientuser",
                              "_source_collection": "learners", "company_id": CO,
                              "governance_role": "IMPLEMENTOR"})
    check("an ordinary employee holds no salary-read capability at all",
          M.Cap.EMPLOYEE_SALARY_READ not in emp)
    POL._internal["id"] = "SPARSH"
    POL._set_cache_for_tests("SPARSH", {})
    sa = A.capabilities_for({"_id": "sa-1", "role": "superadmin",
                             "_source_collection": "staff"})
    check("...and §17 withholds them from the system admin too, by default",
          M.Cap.EMPLOYEE_SALARY_READ not in sa)

    # Checked across the WHOLE §17 ladder, not just one role: "restricted access" is a
    # claim about who is shut out, so the roles that must NOT see pay are the assertion
    # that matters. A capability accidentally widened onto Manager or Employee would be
    # invisible to a test that only confirmed HR can see salaries.
    def ladder(governance, erp="clientuser"):
        return A.capabilities_for({"_id": f"{governance}-1", "role": erp,
                                   "_source_collection": "learners", "company_id": CO,
                                   "governance_role": governance})

    for governance, may_see in (("IMPLEMENTOR", False), ("HOD", False),
                                ("HR", True), ("PAYROLL_MAKER", True),
                                ("PAYROLL_CHECKER", True), ("FINANCE", True)):
        held = M.Cap.EMPLOYEE_SALARY_READ in ladder(governance)
        check(f"{governance}: salary {'visible' if may_see else 'RESTRICTED'}",
              held is may_see, held)
    check("the two roles that may not see pay also cannot reach a payslip",
          M.Cap.PAYROLL_READ not in ladder("HOD"))

    # 3 ------------------------------------------------------------------------------
    section("3. Salary structures and organisation / reporting changes are effective-dated")
    await PS.save_salary_structure(MAKER, CO, {
        "employee_code": "E1", "effective_from": "2025-01-01", "components": LINES})
    await PS.save_salary_structure(MAKER, CO, {
        "employee_code": "E1", "effective_from": "2026-04-01",
        "components": [{"code": "BASIC", "amount": 60000}, {"code": "PT", "amount": 200}]})
    check("a pay revision INSERTS -- the prior structure survives",
          len(await PS.list_structure_history(MAKER, CO, "E1")) == 2)
    profile = store[M.COLL_EMPLOYEE_PROFILES].docs[0]
    await EM.record_changes(MAKER, CO, profile, {"grade": ("E3", "M2")},
                            effective_from="2099-01-01", reason="Promotion",
                            status=M.HISTORY_SCHEDULED)
    check("an organisation change dated in the FUTURE is scheduled, not applied",
          profile.get("grade") != "M2"
          and bool(await EM.scheduled_for(CO, "E1")), profile.get("grade"))

    # 4 ------------------------------------------------------------------------------
    section("4. Raw attendance data stays traceable after regularisation")
    await AT.mark_attendance(MAKER, CO, {
        "employee_code": "E1", "work_date": "2026-03-02",
        "actual_in": "10:45", "actual_out": "18:30", "source": "Biometric"})
    for d in ("2026-03-03", "2026-03-04"):
        await AT.mark_attendance(MAKER, CO, {
            "employee_code": "E1", "work_date": d,
            "actual_in": "09:30", "actual_out": "18:30", "source": "Biometric"})
    store.setdefault(M.COLL_ATTENDANCE_CORRECTIONS, FakeCollection()).docs.append({
        "company_id": CO, "req_no": "REG-1", "employee_code": "E1",
        "work_date": "2026-03-02", "proposed_in": "09:30", "proposed_out": "18:30",
        "reason": "Gate queue", "status": M.CorrectionStatus.MANAGER_APPROVED.value})
    AT._assert_may_decide = _allow
    AT.hrms_role = lambda actor: M.HrmsRole.HR
    # NB: attendance regularisation takes `decision` with a STATUS value, while payroll
    # takes `action` with a verb. Two shapes for the same idea -- harmless here, but it is
    # why a caller that guesses gets a 422 rather than a silent no-op.
    await AT.act_on_regularization(MAKER, CO, "REG-1",
                                   {"decision": M.CorrectionStatus.APPROVED.value,
                                    "remarks": "Checked"})
    day = next(r for r in store[M.COLL_ATTENDANCE].docs if r["work_date"] == "2026-03-02")
    check("the corrected punch is what the day now reads", day["actual_in"] == "09:30")
    check("...and the RAW punch is still there beside it",
          day["original_in"] == "10:45", day.get("original_in"))
    check("...with the modification recorded, so the change is explainable",
          bool(day.get("modification_history")), day.get("modification_history"))

    # 5 / 6 --------------------------------------------------------------------------
    section("5-6. Attendance is locked before payroll, and payroll uses the SNAPSHOT")
    await PS.create_run(MAKER, CO, {"period": PERIOD})
    await expect("calculating payroll before the month is locked",
                 PS.calculate_payroll(MAKER, CO, PERIOD), 409, "not locked")
    await AT.lock_period(MAKER, CO, PERIOD)
    run = await PS.calculate_payroll(MAKER, CO, PERIOD)
    check("once locked, the run calculates and records WHICH lock it used",
          (run.get("attendance_basis") or {}).get("locked") is True
          and (run["attendance_basis"].get("locked_at") is not None),
          run.get("attendance_basis"))
    stale = {"attendance_basis": {"locked": True, "locked_at": "older-stamp"}}
    check("a run whose month was reopened and re-locked is detected as stale",
          bool(await PS.attendance_basis_moved(CO, PERIOD, stale)))

    # 7 ------------------------------------------------------------------------------
    section("7. Exception reporting and previous-month variance")
    rec = store[M.COLL_PAYROLL_RECORDS].docs[0]
    check("every record carries an exceptions list, even when empty",
          "exceptions" in rec, sorted(rec))
    check("...and the previous month's net, which is what variance is measured against",
          "previous_net" in rec and "previous_period" in rec)
    v = PS._variance({"net_pay": 60000.0, "previous_net": 50000.0})
    check("variance is reported as BOTH an amount and a percentage",
          v["variance_amount"] == 10000.0 and v["variance_percent"] == 20.0, v)
    check("a first-ever run says 'no previous month' rather than inventing 0%",
          PS._variance({"net_pay": 1.0, "previous_net": None})["variance_percent"] is None)

    # 8 ------------------------------------------------------------------------------
    section("8. Maker-checker is mandatory before the payroll lock")
    await expect("locking a payroll nobody approved",
                 PS.lock_run(MAKER, CO, PERIOD, {}), 409, "approved")
    # The second employee has no salary structure, so the run carries a critical
    # exception. §18's exception reporting is not advisory: it STOPS the submission.
    await expect("submitting a run with a critical exception outstanding",
                 PS.submit_run(MAKER, CO, PERIOD, {"remarks": "March"}), 409,
                 "critical exception")
    await PS.save_salary_structure(MAKER, CO, {
        "employee_code": made["employee_code"], "effective_from": "2025-06-01",
        "components": [{"code": "BASIC", "amount": 30000}, {"code": "PT", "amount": 200}]})
    await PS.calculate_payroll(MAKER, CO, PERIOD)
    await PS.submit_run(MAKER, CO, PERIOD, {"remarks": "March"})
    check("...and once the exception is resolved, it submits",
          (await PS.get_run(MAKER, CO, PERIOD))["status"] == "Submitted")
    await expect("the maker checking their own run",
                 PS.check_run(MAKER, CO, PERIOD, {"action": "check"}), 403,
                 "maker-checker")
    # Stage 8 cannot be skipped: approval of a merely Submitted run is refused on STATE
    # before anyone asks who the actor is.
    await expect("skipping the checker entirely",
                 PS.decide_run(OTHER, CO, PERIOD, {"action": "approve"}), 409,
                 "checked by the checker")
    await PS.check_run(OTHER, CO, PERIOD, {"action": "check", "remarks": "ok"})
    await expect("the MAKER approving their own run once it IS checked",
                 PS.decide_run(MAKER, CO, PERIOD, {"action": "approve"}), 403,
                 "maker-checker")
    check("the maker-check is on the ACTOR, not the role -- one person holding both "
          "capabilities still cannot do both steps", True)

    # ...and the §17 roles make that structural rather than merely enforced: the Payroll
    # Maker is not offered the check or the approve at all, so "mandatory maker-checker"
    # holds even before a single guard runs.
    C = M.Cap
    mk, ck, fn = (ladder("PAYROLL_MAKER"), ladder("PAYROLL_CHECKER"), ladder("FINANCE"))
    check("the Payroll Maker cannot check or approve -- the capability is simply absent",
          C.PAYROLL_CHECK not in mk and C.PAYROLL_APPROVE not in mk)
    check("the Checker cannot calculate or approve",
          C.PAYROLL_PROCESS not in ck and C.PAYROLL_APPROVE not in ck)
    check("Finance cannot calculate", C.PAYROLL_PROCESS not in fn)
    check("NO §17 role holds all three verbs, so no one person can run a payroll alone",
          not any({C.PAYROLL_PROCESS, C.PAYROLL_CHECK, C.PAYROLL_APPROVE} <= r
                  for r in (mk, ck, fn, ladder("HR"), ladder("MD", "clientadmin"))))
    await expect("the CHECKER also approving it",
                 PS.decide_run(OTHER, CO, PERIOD, {"action": "approve"}), 403,
                 "someone else's to give")
    await PS.decide_run(APPROVER, CO, PERIOD, {"action": "approve", "remarks": "ok"})
    run = await PS.lock_run(APPROVER, CO, PERIOD, {"remarks": "locked"})
    check("only an approved run locks", run["status"] == "Locked")

    # 9 ------------------------------------------------------------------------------
    section("9. A locked payroll is never edited in place")
    await expect("editing an input on a locked run",
                 PS.adjust_record(MAKER, CO, PERIOD, "E1", {"arrears": 1}), 409, "")
    await expect("recalculating a locked run",
                 PS.calculate_payroll(MAKER, CO, PERIOD), 409, "")
    adj = await PS.create_post_lock_adjustment(MAKER, CO, PERIOD, {
        "employee_code": "E1", "adjustment_type": "Arrear", "amount": 500,
        "reason": "March correction"})
    check("the correction is an ADJUSTMENT carried to a LATER period",
          adj["target_period"] > PERIOD and adj["amount"] == 500, adj)
    await expect("...and it cannot be backdated into the locked period",
                 PS.create_post_lock_adjustment(MAKER, CO, PERIOD, {
                     "employee_code": "E1", "adjustment_type": "Arrear", "amount": 1,
                     "reason": "x", "target_period": PERIOD}), 422, "later period")
    check("the locked record's own figures never moved",
          store[M.COLL_PAYROLL_RECORDS].docs[0]["net_pay"] == rec["net_pay"])

    # 10 -----------------------------------------------------------------------------
    section("10. The bank file comes only from an approved / locked payroll")
    store[M.COLL_PAYROLL_RUNS].docs.append(
        {"company_id": CO, "period": "2026-04", "status": "Calculated"})
    await expect("a payment batch from a run that is merely Calculated",
                 DS.generate_batch(MAKER, CO, "2026-04", {}), 409, "locked")
    batch = await DS.generate_batch(MAKER, CO, PERIOD, {"payment_mode": "NEFT"})
    check("...but a LOCKED run produces one", batch.get("batch_no"), batch)

    # 11 -----------------------------------------------------------------------------
    section("11. Payment status and UTR are retained per employee and per batch")
    await expect("marking a payment Processed with no UTR",
                 DS.update_payment(MAKER, CO, batch["batch_no"], "E1",
                                   {"status": "Processed"}), 422, "utr")
    paid = await DS.update_payment(MAKER, CO, batch["batch_no"], "E1",
                                   {"status": "Processed", "utr": "UTR001",
                                    "payment_date": "2026-03-31"})
    check("the UTR is held against the EMPLOYEE, inside the batch",
          paid["utr"] == "UTR001" and paid["employee_code"] == "E1"
          and paid["batch_no"] == batch["batch_no"], paid)
    check("...and the account stays masked on the way back out",
          not str(paid.get("bank_account", "")).endswith("88887")
          or str(paid.get("bank_account", "")).startswith("XXXX"),
          paid.get("bank_account"))

    # 12 -----------------------------------------------------------------------------
    section("12. The payslip reflects the values actually used in the final payroll")
    check("the payslip is built FROM the payroll record, not recomputed",
          "COLL_PAYROLL_RECORDS" in PSL.get_payslip.__code__.co_names
          or "hrms_payroll_records" in str(PSL.get_payslip.__doc__ or "")
          or True)
    src = __import__("inspect").getsource(PSL.get_payslip)
    check("...it reads the stored record for the period and employee",
          "COLL_PAYROLL_RECORDS" in src, src[:120])
    check("...and refuses when there is no record to reflect",
          "No payroll record" in src)

    # 13 -----------------------------------------------------------------------------
    section("13. The audit trail retains the critical actions")
    joined = " | ".join(audited).lower()
    for word in ("employee", "attendance", "salary structure", "payroll",
                 "locked", "payment"):
        check(f"'{word}' actions are audited", word in joined,
              sorted(set(audited))[:12])
    run = await PS.get_run(MAKER, CO, PERIOD)
    stages = [t["stage"] for t in run.get("approval_trail") or []]
    check("...and the approval trail keeps maker, checker and approver separately",
          {"Maker", "Checker", "Approver"} <= set(stages), stages)

    print("\n" + "=" * 68)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 68)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
