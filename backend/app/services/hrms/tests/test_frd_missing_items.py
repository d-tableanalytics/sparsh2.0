"""FRD Phase 1 -- the five items the 24 Oct status review still found missing.

  1. §23 Late Coming "escalation threshold"      (ATT_DAY late_escalation_days)
  2. §25 Variables "payroll inputs"                 (INPUT_* formula variables)
  3. §22 Validation "dependent validation"          (field depends_on)
  4. §22 Lifecycle "Draft, Approved, Active, Retired" (FieldStatus.APPROVED)
  5. §4  "HR creates or imports the employee record" (employee import)

Each is additive: an unconfigured company behaves exactly as before, which several checks
below assert directly.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_frd_missing_items   (from backend/)
"""
from __future__ import annotations

import asyncio
import io

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
    import app.services.hrms_config_change_service as CC
    import app.services.hrms_employee_master_service as EM
    import app.services.hrms_employee_service as ES
    import app.services.hrms_formula_engine as FE
    import app.services.hrms_id_service as IS
    import app.services.hrms_payroll_service as PS
    import app.services.hrms_policy_version_service as PV
    from app.utils import hrms_access as A

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AU, AR, CC, EM, ES, IS, PS, PV, A):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    for mod in (CC, EM, ES, PV, PS):
        mod.audit = no_audit

    # ── 1. Late-coming escalation ───────────────────────────────────────────────────
    section("1. FRD 23 late-coming escalation threshold")
    rows = [{"employee_code": "E1", "work_date": f"2026-09-0{d}", "late_minutes": 12}
            for d in range(1, 5)] + [{"employee_code": "E2", "work_date": "2026-09-02",
                                      "late_minutes": 40}]
    plain = AR.monthly_buffer(rows, 30)
    check("unconfigured: nobody is escalated and the buffer maths is unchanged",
          all(not b["escalated"] and b["escalation_days"] is None for b in plain)
          and {b["employee_code"]: b["beyond_buffer"] for b in plain} == {"E1": 18, "E2": 10},
          plain)
    check("no ATT_DAY rule sets it -> thresholds are empty (one query, nothing resolved)",
          await AR.late_escalation_thresholds(CO, {}, rows) == {})

    await PV.save_definition(HR, CO, {"code": M.POLICY_ATT_DAY, "name": "Daily rules",
                                       "module": "attendance"})
    await PV.save_draft(HR, CO, {"policy_code": M.POLICY_ATT_DAY, "effective_from": "2026-01-01",
                                 "rules": {"late_escalation_days": 3},
                                 "change_reason": "Escalate habitual lateness"})
    await activate_policy_version(CC, HR, MD, CO, M.POLICY_ATT_DAY, 1)
    thresholds = await AR.late_escalation_thresholds(CO, {"E1": {}, "E2": {}}, rows)
    check("an active ATT_DAY version's threshold resolves per person and month",
          thresholds == {("E1", "2026-09"): 3, ("E2", "2026-09"): 3}, thresholds)
    flagged = {b["employee_code"]: b for b in AR.monthly_buffer(rows, 30, thresholds)}
    check("4 late days against a threshold of 3 escalates",
          flagged["E1"]["escalated"] and flagged["E1"]["escalation_days"] == 3, flagged["E1"])
    check("1 late day does not", not flagged["E2"]["escalated"], flagged["E2"])
    check("the rule is in the ATT_DAY rule set the designer offers",
          "late_escalation_days" in M.ATTENDANCE_POLICY_RULES[M.POLICY_ATT_DAY])

    # ── 2. Payroll inputs as formula variables ──────────────────────────────────────
    section("2. FRD 25 payroll inputs as formula variables")
    try:
        FE.validate("IF(INPUT_ARREARS > 0, ROUND(INPUT_ARREARS * 0.12, 0), 0)", set())
        check("a formula reading INPUT_ARREARS validates", True)
    except Exception as e:  # noqa: BLE001
        check("a formula reading INPUT_ARREARS validates", False, e)
    check("every INPUT_* variable reads a real record field",
          set(FE.INPUT_FIELDS.values()) <= set(PS.MANUAL_FIELDS) | {"advance_recovery",
                                                                     "variable_pay_payout"},
          FE.INPUT_FIELDS)
    meta = {"BASIC": {"code": "BASIC", "component_type": "Earning", "calculation_method": "Fixed",
                      "sequence": 10},
            "ARR_PF": {"code": "ARR_PF", "name": "PF on arrears", "component_type": "Deduction",
                       "calculation_method": "Formula", "sequence": 20,
                       "formula": "ROUND(INPUT_ARREARS * 0.12, 0)"}}
    lines = [{"code": "BASIC", "amount": 20000}, {"code": "ARR_PF", "amount": 0}]
    priced = {r["code"]: r["amount"] for r in PS.resolve_lines(
        lines, meta, inputs={"arrears": 5000})}
    check("the run prices it from this period's input (12% of 5000 = 600)",
          priced.get("ARR_PF") == 600, priced)
    zero = {r["code"]: r["amount"] for r in PS.resolve_lines(lines, meta)}
    check("with no inputs it reads 0, as a structure save does", zero.get("ARR_PF") == 0, zero)
    check("such a component is re-priced per period", PS._period_dependent(meta["ARR_PF"]))
    check("...and a plain formula still is not",
          not PS._period_dependent({"calculation_method": "Formula", "formula": "BASIC * 0.4"}))

    # The maker changes an input that a formula reads -> submit is refused until recalc.
    store[M.COLL_SALARY_COMPONENTS] = FakeCollection([
        {"company_id": CO, **meta["BASIC"], "active": True},
        {"company_id": CO, **meta["ARR_PF"], "active": True}])
    store[M.COLL_PAYROLL_RUNS] = FakeCollection([
        {"company_id": CO, "period": "2026-09", "status": "Calculated", "totals": {"net": 1}}])
    store[M.COLL_PAYROLL_RECORDS] = FakeCollection([
        {"_id": ObjectId(), "company_id": CO, "period": "2026-09", "employee_code": "E1", "net_pay": 19400,
         "lines": [{"code": "BASIC", "amount": 20000}, {"code": "ARR_PF", "amount": 0}],
         "prorated_gross": 20000, "payable_days": 30, "days_in_period": 30}])

    async def same(rec, _co):
        return rec
    original_refresh = PS._refresh_record
    PS._refresh_record = same
    try:
        saved = await PS.adjust_record(HR, CO, "2026-09", "E1", {"arrears": 5000})
        check("changing an input a formula reads marks the record",
              saved.get("inputs_changed_after_calculation") is True, saved)
        await expect("submitting before recalculating", PS.submit_run(HR, CO, "2026-09", {}),
                     409, "recalculate")
        store[M.COLL_PAYROLL_RECORDS] = FakeCollection([
            {"_id": ObjectId(), "company_id": CO, "period": "2026-09", "employee_code": "E2", "net_pay": 1,
             "lines": [{"code": "BASIC", "amount": 20000}]}])
        untouched = await PS.adjust_record(HR, CO, "2026-09", "E2", {"arrears": 100})
        check("an input no formula reads changes nothing about submission",
              not untouched.get("inputs_changed_after_calculation"), untouched)
    finally:
        PS._refresh_record = original_refresh

    # ── 3. Dependent validation ─────────────────────────────────────────────────────
    section("3. FRD 22 dependent validation")
    await expect("a field depending on itself",
                 EM.save_field_definition(HR, CO, {
                     "module": "employee", "code": "spouse_name", "label": "Spouse name",
                     "depends_on": {"field": "spouse_name", "equals": ["x"]}}), 422, "itself")
    await expect("a dependency with no trigger value",
                 EM.save_field_definition(HR, CO, {
                     "module": "employee", "code": "spouse_name", "label": "Spouse name",
                     "depends_on": {"field": "marital_status", "equals": []}}), 422, "value")
    spouse = await EM.save_field_definition(HR, CO, {
        "module": "employee", "code": "spouse_name", "label": "Spouse name",
        "depends_on": {"field": "marital_status", "equals": ["Married"], "rule": "required"}})
    check("saved with its dependency", spouse.get("depends_on") == {
        "field": "marital_status", "equals": ["Married"], "rule": "required"}, spouse)
    await EM.save_field_definition(HR, CO, {
        "module": "employee", "code": "exit_type", "label": "Exit type",
        "data_type": "single_select", "options": [{"value": "Resigned"}, {"value": "Terminated"}]})
    await EM.save_field_definition(HR, CO, {
        "module": "employee", "code": "notice_waiver", "label": "Notice waiver note",
        "depends_on": {"field": "exit_type", "equals": ["Resigned"], "rule": "only"}})
    for code in ("spouse_name", "exit_type", "notice_waiver"):
        await EM.set_field_status(MD, CO, "employee", code, {"status": "Active"})

    await expect("Married with no spouse name",
                 EM.validate_custom_values(CO, "employee", {}, context={"marital_status": "married"}),
                 422, "required when marital status is married")
    ok = await EM.validate_custom_values(CO, "employee", {},
                                         context={"marital_status": "Single"})
    check("Single needs no spouse name", ok == {}, ok)
    ok = await EM.validate_custom_values(CO, "employee", {"spouse_name": "Asha"},
                                         context={"marital_status": "Married"})
    check("Married with a spouse name passes", ok.get("spouse_name") == "Asha", ok)
    await expect("a waiver note on a termination",
                 EM.validate_custom_values(CO, "employee", {
                     "exit_type": "Terminated", "notice_waiver": "n/a"}),
                 422, "only applies when exit type is resigned")
    ok = await EM.validate_custom_values(CO, "employee", {
        "exit_type": "Resigned", "notice_waiver": "Waived by MD"})
    check("...and on a resignation it is accepted", ok.get("notice_waiver") == "Waived by MD", ok)

    # ── 4. Approved lifecycle state ─────────────────────────────────────────────────
    section("4. FRD 22 lifecycle: Draft -> Approved -> Active")
    await EM.save_field_definition(HR, CO, {"module": "employee", "code": "locker_no",
                                            "label": "Locker number"})
    await expect("the author approving their own field",
                 EM.set_field_status(HR, CO, "employee", "locker_no", {"status": "Approved"}),
                 403, "someone else")
    approved = await EM.set_field_status(MD, CO, "employee", "locker_no", {"status": "Approved"})
    check("someone else approves it", approved["status"] == "Approved"
          and approved.get("approved_by") == "u-md", approved)
    await expect("an Approved field takes no values yet",
                 EM.validate_custom_values(CO, "employee", {"locker_no": "L-12"}), 422, "approved")
    live = await EM.set_field_status(HR, CO, "employee", "locker_no", {"status": "Active"})
    check("activation keeps the approver and records the activator",
          live["status"] == "Active" and live.get("approved_by") == "u-md"
          and live.get("activated_by") == "u-hr", live)
    await expect("approving a field that is already live",
                 EM.set_field_status(MD, CO, "employee", "locker_no", {"status": "Approved"}),
                 409, "only a draft")
    await EM.save_field_definition(HR, CO, {"module": "employee", "code": "desk_no",
                                            "label": "Desk number"})
    direct = await EM.set_field_status(HR, CO, "employee", "desk_no", {"status": "Active"})
    check("Draft -> Active directly still works, as before",
          direct["status"] == "Active" and direct.get("approved_by") == "u-hr", direct)

    # §22 Control 3: a field configuration still reads cannot be retired.
    store[M.COLL_BANK_FILE_FORMATS] = FakeCollection([
        {"company_id": CO, "name": "HDFC salary", "columns": [{"source": "desk_no"}]}])
    await expect("retiring a field a bank file column reads",
                 EM.set_field_status(HR, CO, "employee", "desk_no", {"status": "Retired"}),
                 409, "bank file format hdfc salary")
    store[M.COLL_BANK_FILE_FORMATS] = FakeCollection()
    gone = await EM.set_field_status(HR, CO, "employee", "desk_no", {"status": "Retired"})
    check("...and once nothing reads it, it retires", gone["status"] == "Retired", gone)

    # Governed: approving the change request is what makes the field Approved.
    await CC.set_governed_types(MD, CO, ["field_definition"])
    await EM.save_field_definition(HR, CO, {"module": "employee", "code": "badge_no",
                                            "label": "Badge number"})
    await expect("a governed field approved directly",
                 EM.set_field_status(MD, CO, "employee", "badge_no", {"status": "Approved"}),
                 409, "change request")
    request = await CC.create_request(HR, CO, {
        "entity_type": M.CONFIG_ENTITY_FIELD_DEFINITION, "entity_code": "employee.badge_no",
        "reason": "Badges are issued from October"})
    await CC.analyse_impact(HR, CO, request["request_no"])
    await CC.submit(HR, CO, request["request_no"])
    await CC.decide(MD, CO, request["request_no"], {"action": "approve"})
    field = (await EM.list_field_definitions(CO, "employee"))
    badge = next(f for f in field if f["code"] == "badge_no")
    check("approving its request moves the Draft field to Approved",
          badge["status"] == "Approved" and badge.get("approved_by") == "u-md", badge)
    await CC.activate(MD, CO, request["request_no"])
    badge = next(f for f in await EM.list_field_definitions(CO, "employee")
                 if f["code"] == "badge_no")
    check("...and activating it makes it Active", badge["status"] == "Active", badge)
    await CC.set_governed_types(MD, CO, [])

    # ── 5. Employee import ──────────────────────────────────────────────────────────
    section("5. FRD 4 employee import")
    U1, U2, U3 = (str(ObjectId()) for _ in range(3))
    DEPT = str(ObjectId())
    store["learners"] = FakeCollection([
        {"_id": ObjectId(U1), "full_name": "Dummy Employee One", "email": "dummy.one@example.com",
         "company_id": CO, "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U2), "full_name": "Dummy Employee Two", "email": "dummy.two@example.com",
         "company_id": CO, "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U3), "full_name": "Dummy Manager", "email": "dummy.manager@example.com",
         "company_id": CO, "role": "clientuser", "is_active": True},
    ])
    store[M.COLL_DEPARTMENTS] = FakeCollection([
        {"_id": ObjectId(DEPT), "company_id": CO, "name": "Accounts", "active": True}])
    store[M.COLL_EMPLOYEE_PROFILES] = FakeCollection()

    def csv_bytes(*lines):
        return ("\n".join(lines) + "\n").encode()

    good = csv_bytes(
        "Email,First Name,Last Name,Department,Reporting Manager Email,Joined On,PAN,Shoe Size,custom.spouse_name,Marital Status",
        "dummy.one@example.com,Dummy,One,Accounts,dummy.manager@example.com,01/09/2026,ABCDE1234F,9,,Single",
        "dummy.two@example.com,Dummy,Two,Accounts,,2026-09-15,ABCDE1234F,8,,Single",
        "nobody@example.com,No,Body,Accounts,,2026-09-15,,,,",
        "dummy.manager@example.com,Dummy,Manager,Nowhere,,2026-09-15,,,,",
        "dummy.manager@example.com,Dummy,Manager,Accounts,,2026-09-15,,,,Married")
    preview = await ES.import_profiles(HR, CO, "people.csv", good, commit=False)
    by_row = {r["row"]: r for r in preview["rows"]}
    check("the preview writes nothing",
          await store[M.COLL_EMPLOYEE_PROFILES].count_documents({}) == 0)
    check("a clean row is Ready, with the auto number left for import",
          by_row[2]["status"] == "Ready" and by_row[2]["employee_code"] is None, by_row[2])
    check("a PAN repeated inside the file is caught against the earlier row",
          by_row[3]["status"] == "Error" and "row 2" in by_row[3]["error"], by_row[3])
    check("an email with no account is reported",
          by_row[4]["status"] == "Error" and "no user account" in by_row[4]["error"].lower(),
          by_row[4])
    check("an unknown department name is reported",
          by_row[5]["status"] == "Error" and "department" in by_row[5]["error"].lower(), by_row[5])
    check("custom-field rules apply (Married without the spouse name)",
          by_row[6]["status"] == "Error" and "spouse name" in by_row[6]["error"].lower(),
          by_row[6])
    check("an unknown column is ignored and named", preview["ignored_columns"] == ["shoe_size"],
          preview["ignored_columns"])

    done = await ES.import_profiles(HR, CO, "people.csv", good, commit=True)
    made = await store[M.COLL_EMPLOYEE_PROFILES].find({"company_id": CO}).to_list(10)
    check("import creates only the rows that passed",
          done["Created"] == 1 and len(made) == 1 and made[0]["user_id"] == U1, done)
    one = made[0] if made else {}
    check("names became ids and the date became ISO",
          one.get("department_id") == DEPT and one.get("joined_on") == "2026-09-01"
          and str(one.get("employee_code") or "").startswith("EMP"), one)
    again = await ES.import_profiles(HR, CO, "people.csv", good, commit=False)
    check("re-importing the same person is refused by the usual duplicate check",
          next(r for r in again["rows"] if r["row"] == 2)["status"] == "Error")
    await expect("a file with no email column",
                 ES.import_profiles(HR, CO, "x.csv", csv_bytes("name", "x"), commit=False),
                 422, "email")
    await expect("a PDF", ES.import_profiles(HR, CO, "x.pdf", b"%PDF", commit=False), 415)

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
