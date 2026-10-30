"""FRD Phase 1 -- the Partially Built rows of the 24 Oct status review, completed.

Covers, one section each:
  1. Payroll policy: approval matrix accepted, eligibility, input cut-off, adjustment approval
  2. Salary component governance: staged revision, Superseded version, Approved lifecycle
  3. Attendance: closure blocks on open requests, approved-exception half day, versioned
     company rules, regularisation evidence file and request type, previews
  4. Employee master: PSC type, history Effective To, ID format, activation switches,
     directory search / filter / columns, attendance source mapping
  5. Payroll extras: imported inputs, LOP as a payslip deduction line, impact periods,
     superadmin payroll restriction

Every new setting is OFF by default, and several checks assert that the default behaves
exactly as before.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_frd_partial_items   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

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
from app.services.hrms.tests.governance_helper import activate_policy_version  # noqa: E402

CO = "C1"
HR = {"_id": "u-hr", "role": "superadmin", "governance_role": "HR", "full_name": "Dummy HR"}
MD = {"_id": "u-md", "role": "superadmin", "governance_role": "MD", "full_name": "Dummy MD"}


async def main() -> int:
    from bson import ObjectId
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_audit_service as AU
    import app.services.hrms_attendance_rules_service as AR
    import app.services.hrms_attendance_service as AS
    import app.services.hrms_attendance_simulation_service as SIM
    import app.services.hrms_config_change_service as CC
    import app.services.hrms_document_service as DOC
    import app.services.hrms_employee_master_service as EM
    import app.services.hrms_employee_service as ES
    import app.services.hrms_id_service as IS
    import app.services.hrms_payroll_service as PS
    import app.services.hrms_payslip_service as SLIP
    import app.services.hrms_permission_service as PERM
    import app.services.hrms_policy_version_service as PV
    from app.utils import hrms_access as A
    from app.utils import hrms_permission_policy as POL

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AU, AR, AS, SIM, CC, DOC, EM, ES, IS, PS, SLIP, PERM, PV, A, POL):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    for mod in (CC, EM, ES, PV, PS, AS, AR, DOC, PERM, SLIP):
        mod.audit = no_audit

    # ── 1. Payroll policy ───────────────────────────────────────────────────────────
    section("1. Payroll policy: matrix, eligibility, cut-off, adjustment approval")
    body = M.PayrollPolicyIn(checker_required=False, lock_cap="payroll.check",
                             excluded_employee_categories=["Consultant"],
                             enforce_input_cutoff=True, adjustment_approval_above=1000,
                             effective_to="2026-12-31", scope={"grades": ["M1"]},
                             change_reason="x").model_dump(exclude_unset=True)
    check("the screen's approval-matrix keys now survive the request model",
          body.get("checker_required") is False and body.get("lock_cap") == "payroll.check",
          body)
    check("every new policy key is classed run- or employee-level (the suite's own rule)",
          set(M.DEFAULT_PAYROLL_POLICY) == set(M.PAYROLL_POLICY_RUN_LEVEL_KEYS)
          | set(M.PAYROLL_POLICY_EMPLOYEE_LEVEL_KEYS))
    check("new keys default to today's behaviour",
          M.DEFAULT_PAYROLL_POLICY["excluded_employee_categories"] == []
          and M.DEFAULT_PAYROLL_POLICY["enforce_input_cutoff"] is False
          and M.DEFAULT_PAYROLL_POLICY["adjustment_approval_above"] is None)

    store[M.COLL_EMPLOYEE_PROFILES] = FakeCollection([
        {"company_id": CO, "employee_code": "E1", "employment_status": "Active",
         "employee_category": "Permanent"},
        {"company_id": CO, "employee_code": "E2", "employment_status": "Active",
         "employee_category": "Consultant"},
        {"company_id": CO, "employee_code": "E3", "employment_status": "Active",
         "payroll_active": False}])
    everyone = {p["employee_code"] for p in await PS._eligible_profiles(CO, "2026-09-01", "2026-09-30")}
    check("unconfigured: everyone active is paid except an employee switched off",
          everyone == {"E1", "E2"}, everyone)
    some = {p["employee_code"] for p in await PS._eligible_profiles(
        CO, "2026-09-01", "2026-09-30", ["consultant"])}
    check("a category the policy leaves out is not in the run", some == {"E1"}, some)

    store[M.COLL_SETTINGS] = FakeCollection([{"company_id": CO, "payroll_policy": {
        "enforce_input_cutoff": True, "input_cutoff_day": 5,
        "adjustment_approval_above": 1000}}])
    maker = {"_id": "u-maker", "role": "clientuser", "company_id": CO,
             "_source_collection": "learners", "governance_role": "HR"}
    await expect("a maker editing inputs after the cut-off",
                 PS._assert_inputs_open(maker, CO, "2026-01"), 409, "closed on 2026-01-05")
    store[M.COLL_SETTINGS] = FakeCollection([{"company_id": CO, "payroll_policy": {
        "adjustment_approval_above": 1000}}])
    await PS._assert_inputs_open(maker, CO, "2026-01")
    check("not enforced (the default): the cut-off day stays advisory", True)

    store[M.COLL_PAYROLL_RUNS] = FakeCollection([
        {"_id": ObjectId(), "company_id": CO, "period": "2026-09", "status": "Calculated",
         "totals": {"net": 1}}])
    store[M.COLL_PAYROLL_RECORDS] = FakeCollection([
        {"_id": ObjectId(), "company_id": CO, "period": "2026-09", "employee_code": "E1",
         "net_pay": 1000, "lines": [], "adjustments": []}])
    store[M.COLL_SALARY_COMPONENTS] = FakeCollection([
        {"company_id": CO, "code": "BONUS1", "name": "Spot bonus", "component_type": "Earning",
         "active": True}])

    async def same(rec, _co):
        return rec
    original_refresh = PS._refresh_record
    PS._refresh_record = same
    try:
        rec = await PS.set_adjustments(HR, CO, "2026-09", "E1", {"adjustments": [
            {"code": "BONUS1", "amount": 5000, "reason": "Quarter close"},
            {"code": "BONUS1", "amount": 200, "reason": "Small"}]})
        check("a line above the approval amount waits; one below does not",
              rec["adjustments"][0].get("approval_status") == "Pending"
              and not rec["adjustments"][1].get("approval_status"), rec["adjustments"])
        await expect("submitting with a line waiting", PS.submit_run(HR, CO, "2026-09", {}),
                     409, "waiting for a second person")
        await expect("the person who entered it approving it",
                     PS.approve_adjustment(HR, CO, "2026-09", "E1", 0), 403, "someone else")
        rec = await PS.approve_adjustment(MD, CO, "2026-09", "E1", 0)
        check("someone else approves it", rec["adjustments"][0]["approval_status"] == "Approved"
              and rec["adjustments"][0]["approved_by"] == "u-md", rec["adjustments"][0])
        rec = await PS.set_adjustments(HR, CO, "2026-09", "E1", {"adjustments": [
            {"code": "BONUS1", "amount": 5000, "reason": "Quarter close"}]})
        check("re-posting the same line keeps its approval",
              rec["adjustments"][0].get("approval_status") == "Approved", rec["adjustments"])
    finally:
        PS._refresh_record = original_refresh

    # ── 2. Salary component governance ──────────────────────────────────────────────
    section("2. Salary components: a live revision goes through approval")
    store[M.COLL_SALARY_COMPONENTS] = FakeCollection()
    store[M.COLL_SETTINGS] = FakeCollection()
    created = await PS.save_salary_component(HR, CO, {"code": "HRA", "name": "HRA",
                                                      "component_type": "Earning",
                                                      "calculation_method": "Fixed"})
    check("a NEW component is created as Draft behind a change request, not live (DEF-02)",
          created.get("lifecycle") == "Draft" and bool(created.get("pending_request")),
          created)
    await expect("creating a new component straight into Active",
                 PS.save_salary_component(HR, CO, {"code": "TA", "name": "TA",
                                                   "component_type": "Earning",
                                                   "lifecycle": "Active"}),
                 409, "start as Draft")
    # Put it live as its activated request would, so the revision path below has a live
    # component to revise.
    await store[M.COLL_SALARY_COMPONENTS].update_one(
        {"code": "HRA"}, {"$set": {"lifecycle": "Active", "pending_request_no": None}})
    staged = await PS.save_salary_component(HR, CO, {
        "code": "HRA", "name": "HRA", "component_type": "Earning",
        "calculation_method": "Formula", "formula": "1500", "change_reason": "Flat HRA"})
    live = await store[M.COLL_SALARY_COMPONENTS].find_one({"code": "HRA"})
    check("editing a live component stages the change and raises a request",
          bool(staged.get("pending_request")) and live.get("calculation_method") == "Fixed"
          and (live.get("pending_definition") or {}).get("formula") == "1500", live)
    await expect("a live revision with no reason",
                 PS.save_salary_component(HR, CO, {"code": "HRA", "name": "HRA (new)",
                                                   "component_type": "Earning"}), 422, "why")
    await expect("a second revision while the first is open",
                 PS.save_salary_component(HR, CO, {"code": "HRA", "name": "House rent",
                                                   "component_type": "Earning",
                                                   "change_reason": "rename"}),
                 409, "already has a change waiting")
    unchanged = await PS.save_salary_component(HR, CO, {
        "code": "HRA", "name": "HRA", "component_type": "Earning",
        "calculation_method": "Fixed", "frequency": "Monthly", "rounding": "None"})
    check("an untouched save of a live component raises nothing",
          not unchanged.get("pending_request"), unchanged)
    no = staged["pending_request"]["request_no"]
    await CC.analyse_impact(HR, CO, no)
    await CC.submit(HR, CO, no)
    await CC.decide(MD, CO, no, {"action": "approve"})
    await CC.activate(MD, CO, no)
    live = await store[M.COLL_SALARY_COMPONENTS].find_one({"code": "HRA"})
    check("activation applies the revision and keeps the old one as Superseded",
          live["calculation_method"] == "Formula" and live["formula"] == "1500"
          and live["versions"][0]["status"] == "Superseded"
          and live["versions"][0]["definition"]["calculation_method"] == "Fixed"
          and not live.get("pending_definition") and live.get("approved_by") == "u-md", live)

    await PS.save_salary_component(HR, CO, {"code": "LTA", "name": "LTA",
                                            "component_type": "Earning", "lifecycle": "Draft"})
    await expect("making a Draft Active directly",
                 PS.save_salary_component(HR, CO, {"code": "LTA", "name": "LTA",
                                                   "component_type": "Earning",
                                                   "lifecycle": "Active"}),
                 409, "change request")
    draft_edit = await PS.save_salary_component(HR, CO, {
        "code": "LTA", "name": "Leave travel", "component_type": "Earning",
        "lifecycle": "Draft"})
    check("a Draft is still edited freely", draft_edit.get("name") == "Leave travel"
          and not draft_edit.get("pending_request"), draft_edit)
    req = await CC.create_request(HR, CO, {"entity_type": M.CONFIG_ENTITY_SALARY_COMPONENT,
                                           "entity_code": "LTA", "reason": "Launch LTA"})
    await CC.analyse_impact(HR, CO, req["request_no"])
    sim = await CC.run_simulation(HR, CO, req["request_no"], "2026-09")
    check("the simulation stage runs from the request and is recorded on it",
          sim["status"] == "Simulated" and isinstance(sim.get("simulation"), dict), sim["status"])
    await CC.submit(HR, CO, req["request_no"])
    await CC.decide(MD, CO, req["request_no"], {"action": "approve"})
    check("approving a Draft component's request makes it Approved",
          (await store[M.COLL_SALARY_COMPONENTS].find_one({"code": "LTA"}))["lifecycle"]
          == "Approved")

    # ── 3. Attendance ───────────────────────────────────────────────────────────────
    section("3. Attendance: closure, half-day exceptions, versioned rules, evidence")
    out = M.compute_daily_status(scheduled_in="09:30", scheduled_out="18:30",
                                 actual_in="11:00", actual_out="18:30",
                                 daily_grace_minutes=10, half_day_threshold_minutes=240,
                                 half_day_late_minutes=60)
    check("a late half day says which rule cut it", out["status"] == "Half Day"
          and out["half_day_basis"] == "late", out)

    await PV.save_definition(HR, CO, {"code": M.POLICY_ATT_DAY, "name": "Daily",
                                      "module": "attendance"})
    await PV.save_draft(HR, CO, {"policy_code": M.POLICY_ATT_DAY, "effective_from": "2026-01-01",
                                 "rules": {"half_day_late_minutes": 60,
                                           "half_day_exception_types": ["Late approval"]},
                                 "change_reason": "late approvals waive"})
    await activate_policy_version(CC, HR, MD, CO, M.POLICY_ATT_DAY, 1)
    store[M.COLL_EMPLOYEE_PROFILES] = FakeCollection([
        {"company_id": CO, "employee_code": "E1", "employment_status": "Active"}])
    plain = await AR.compute_day(CO, "E1", "2026-09-10", "11:00", "18:30")
    waived = await AR.compute_day(CO, "E1", "2026-09-10", "11:00", "18:30",
                                  approved_exception="Late approval")
    other = await AR.compute_day(CO, "E1", "2026-09-10", "11:00", "18:30",
                                 approved_exception="Missing punch")
    check("without an approved exception the late half day stands", plain["status"] == "Half Day",
          plain["status"])
    check("an approved request of a waiving type makes it a full day",
          waived["status"] == "Present" and waived["payable_day"] == 1.0
          and "waived" in (waived.get("half_day_reason") or ""), waived)
    check("a type the policy does not name waives nothing", other["status"] == "Half Day")

    store[M.COLL_SETTINGS] = FakeCollection()
    await AS.save_shift_policy(HR, CO, {"daily_grace_minutes": 15, "change_reason": "softer"})
    await AS.save_shift_policy(HR, CO, {"daily_grace_minutes": 15})
    await AS.save_shift_policy(HR, CO, {"daily_grace_minutes": 20})
    settings = await store[M.COLL_SETTINGS].find_one({"company_id": CO})
    versions = settings.get("shift_policy_versions") or []
    check("each material save of the company rules is a numbered version, a no-op is not",
          settings.get("shift_policy_version") == 2 and len(versions) == 2
          and versions[0]["reason"] == "softer"
          and versions[1]["old"] == {"daily_grace_minutes": 15}, versions)
    check("the change reason is not stored as a rule", "change_reason" not in settings["shift_policy"])

    await PV.save_definition(HR, CO, {"code": M.POLICY_ATT_CLOSURE, "name": "Closure",
                                      "module": "attendance"})
    await PV.save_draft(HR, CO, {"policy_code": M.POLICY_ATT_CLOSURE, "effective_from": "2026-01-01",
                                 "rules": {"block_pending_requests": True}, "change_reason": "x"})
    store[M.COLL_ATTENDANCE_CORRECTIONS] = FakeCollection([
        {"company_id": CO, "req_no": "REG-1", "employee_code": "E1", "work_date": "2026-08-05",
         "status": "Pending", "created_at": datetime(2026, 8, 6, tzinfo=timezone.utc)}])
    preview = await SIM.preview_closure_policy(MD, CO, "2026-08", version_no=1)
    check("the closure preview says the draft would block locking",
          preview["pending_requests"] == 1 and preview["was"]["locking_blocked"] is False
          and preview["now"]["locking_blocked"] is True, preview)
    await activate_policy_version(CC, HR, MD, CO, M.POLICY_ATT_CLOSURE, 1)
    await expect("locking with a request still open, when the policy blocks it",
                 AS.lock_period(MD, CO, "2026-08", override_reason="month end"), 409,
                 "waiting for a decision")

    await PV.save_definition(HR, CO, {"code": M.POLICY_ATT_REGULARISATION, "name": "Reg",
                                      "module": "attendance"})
    await PV.save_draft(HR, CO, {"policy_code": M.POLICY_ATT_REGULARISATION,
                                 "effective_from": "2026-01-01",
                                 "rules": {"evidence_required": True}, "change_reason": "x"})
    reg = await SIM.preview_regularisation_policy(CO, "2026-08", version_no=1)
    check("the regularisation preview names the request the draft would refuse",
          reg["would_refuse"] == 1 and reg["changes"][0]["request_no"] == "REG-1"
          and "no evidence" in reg["changes"][0]["would_be_refused"][0], reg)
    check("a request carrying an evidence FILE meets the evidence rule",
          SIM._regularisation_refusals({"evidence_file": {"s3_key": "k"}},
                                       {"evidence_required": True}, 0) == [])
    check("the request model now carries request_type and an evidence file",
          {"request_type", "evidence_file"} <= set(M.RegularizationIn.model_fields))

    # ── 4. Employee master ──────────────────────────────────────────────────────────
    section("4. Employee master: PSC, Effective To, ID format, activation, directory")
    store[M.COLL_DOCUMENT_TYPES] = FakeCollection([
        {"_id": ObjectId(), "company_id": CO, "name": "PAN Card", "category": "Identity",
         "active": True}])
    store[M.COLL_SETTINGS] = FakeCollection()
    await DOC.list_document_types(CO)
    psc = await store[M.COLL_DOCUMENT_TYPES].count_documents({"company_id": CO, "category": "PSC"})
    check("a company seeded before PSC was a default is offered it once", psc == 1, psc)
    await store[M.COLL_DOCUMENT_TYPES].delete_many({"company_id": CO, "category": "PSC"})
    await DOC.list_document_types(CO)
    check("...and it does not come back once HR removed it",
          await store[M.COLL_DOCUMENT_TYPES].count_documents({"category": "PSC"}) == 0)
    check("PSC is a default type for new companies",
          any(name == "PSC" for name, *_ in M.DEFAULT_DOCUMENT_TYPES))

    store[M.COLL_EMPLOYEE_HISTORY] = FakeCollection([
        {"_id": ObjectId(), "company_id": CO, "employee_code": "E1", "field": "grade", "old_value": "M1",
         "new_value": "M2", "effective_from": "2026-04-01", "status": "Applied",
         "changed_at": datetime(2026, 4, 1, tzinfo=timezone.utc)},
        {"_id": ObjectId(), "company_id": CO, "employee_code": "E1", "field": "grade", "old_value": "M2",
         "new_value": "M3", "effective_from": "2026-10-01", "status": "Applied",
         "changed_at": datetime(2026, 10, 1, tzinfo=timezone.utc)}])
    rows = {r["new_value"]: r for r in await EM.list_history(CO, "E1", include_sensitive=True)}
    check("a value is in force until the day before the next change",
          rows["M2"]["effective_to"] == "2026-09-30" and rows["M3"]["effective_to"] is None, rows)

    store[M.COLL_COUNTERS] = FakeCollection()
    store[M.COLL_EMPLOYEE_PROFILES] = FakeCollection([
        {"company_id": CO, "employee_code": "SM-0001"}])
    default_code = await EM.next_employee_code(CO, 2026)
    check("the default format numbers exactly as before", default_code == "EMP-2026-001",
          default_code)
    saved = await EM.save_employee_id_format(HR, CO, {"prefix": "sm", "include_year": False,
                                                      "digits": 4})
    nxt = await EM.next_employee_code(CO, 2026)
    check("a configured format is used, skipping a code already taken",
          saved["example"] == "SM-0001" and nxt == "SM-0002", (saved, nxt))
    await expect("a prefix with symbols",
                 EM.save_employee_id_format(HR, CO, {"prefix": "S M!"}), 422, "prefix")

    off = {"employee_code": "E9", "attendance_active": False}
    try:
        AS.assert_attendance_active(off)
        check("an employee switched off for attendance cannot be marked", False)
    except Exception as e:  # noqa: BLE001
        check("an employee switched off for attendance cannot be marked",
              getattr(e, "status_code", None) == 409, e)
    AS.assert_attendance_active({"employee_code": "E1"})
    check("unset means active, as before", True)

    rows = [["Employee Code", "Date", "Time", "Site"],
            ["E1", "2026-09-01", "09:05", "Pune"], ["E1", "2026-09-01", "18:00", ""]]
    mapped = AR.mapped_values_from_rows(rows, {"site": "Site"})
    check("an attendance field mapped to a column is read from the import file",
          mapped == {("E1", "2026-09-01"): {"site": "Pune"}}, mapped)
    check("no mapping, nothing read", AR.mapped_values_from_rows(rows, {}) == {})

    # ── 5. Payroll extras and access ────────────────────────────────────────────────
    section("5. Imported inputs, LOP line, impact periods, superadmin payroll access")
    meta = {"INCENT": {"code": "INCENT", "name": "Incentive", "component_type": "Earning",
                       "calculation_method": "Imported Input"},
            "BASIC": {"code": "BASIC", "name": "Basic", "component_type": "Earning"}}
    structure = {"components": [{"code": "BASIC", "amount": 20000}]}
    days = {"payable_days": 15, "days_in_period": 30}
    lines = {l["code"]: l for l in PS._component_lines(structure, meta, 0.5, days=days,
                                                       imported={"INCENT": 3000})}
    check("an imported amount is paid as given, not prorated, even outside the structure",
          lines["INCENT"]["amount"] == 3000 and lines["BASIC"]["amount"] == 10000, lines)
    check("without an import nothing extra is paid",
          [l["code"] for l in PS._component_lines(structure, meta, 0.5, days=days)] == ["BASIC"])

    record = {"employee_code": "E1", "days_in_period": 30, "payable_days": 27, "lop_days": 3,
              "gross_earnings": 18000, "total_deductions": 1000, "net_pay": 17000,
              "lines": [{"code": "BASIC", "name": "Basic", "component_type": "Earning",
                         "section": "Regular Earnings", "amount": 18000, "full_amount": 20000}]}
    kw = dict(period="2026-09", run_status="Locked", employee_name="E1", department_name=None,
              designation_name=None)
    plain = SLIP._compose_from_lines(record, template={}, **kw)
    lop = SLIP._compose_from_lines(record, template={"lop_as_deduction": True}, **kw)
    check("default payslip: LOP stays inside the prorated earnings",
          plain["earnings"][0]["amount"] == 18000 and plain["gross_earnings"] == 18000
          and not any("Loss of Pay" in d["label"] for d in plain["deductions"]))
    check("with the option on: full earnings, one LOP deduction line, same net pay",
          lop["earnings"][0]["amount"] == 20000 and lop["deductions"][0]["amount"] == 2000
          and "Loss of Pay" in lop["deductions"][0]["label"] and lop["net_pay"] == 17000
          and lop["gross_earnings"] - lop["total_deductions"] == 17000, lop)

    store[M.COLL_ATTENDANCE_LOCKS] = FakeCollection([
        {"company_id": CO, "period": "2026-08", "status": "Locked"}])
    periods = await CC._periods_reached(CO, {"effective_from": "2026-08-01"}, {})
    check("impact analysis splits the months reached into open and closed",
          "2026-08" in periods["closed"] and "2026-08" not in periods["open"], periods)

    POL._internal["id"] = CO
    owner = {"_id": "sa-1", "role": "superadmin", "_source_collection": "staff"}
    # FRD §17: "no AUTOMATIC entitlement to payroll-sensitive values unless explicitly
    # granted". The default was permissive until 2026-10-27; it is now withheld, so an
    # unconfigured company already has §17's posture rather than having to find a toggle.
    check("by default the superadmin holds NO payroll capability (§17)",
          M.Cap.PAYROLL_READ not in A.capabilities_for(owner)
          and not A.sees_all_payroll(owner))
    POL._set_cache_for_tests(CO, {POL.ADMIN_PAYROLL_RULE: {"restricted": False,
                                                           "allow_users": []}})
    check("...unless the company deliberately turns the restriction off",
          M.Cap.PAYROLL_READ in A.capabilities_for(owner) and A.sees_all_payroll(owner))
    POL._set_cache_for_tests(CO, {POL.ADMIN_PAYROLL_RULE: {"restricted": True,
                                                           "allow_users": []}})
    caps = A.capabilities_for(owner)
    check("switched on: no payroll values without an explicit grant, permissions intact",
          M.Cap.PAYROLL_READ not in caps and M.Cap.EMPLOYEE_SALARY_READ not in caps
          and M.Cap.PERMISSIONS_MANAGE in caps and not A.sees_all_payroll(owner))
    POL._set_cache_for_tests(CO, {POL.ADMIN_PAYROLL_RULE: {"restricted": True,
                                                           "allow_users": ["sa-1"]}})
    check("an explicitly granted superadmin keeps payroll access",
          M.Cap.PAYROLL_READ in A.capabilities_for(owner))
    POL._set_cache_for_tests(CO, {})

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
