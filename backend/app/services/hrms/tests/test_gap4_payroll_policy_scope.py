"""Post-review Gap 4 -- a scoped PAY_POLICY version reaches the employees it names.

Checklist row P1-073.

`get_payroll_policy()` has always accepted `profile=` so a version scoped by grade,
location, category or payroll group could be resolved against an employee. EVERY caller
passed None -- `calculate_payroll`, the structure save, the payslip gate, the record
refresh. So a version aimed at Grade M1 applied to nobody, and the scope UI offered a
filter that changed no figure anywhere in the system.

Fixing it meant deciding which keys may legitimately differ between two people in one run.

  * RUN-LEVEL keys describe the RUN and have one answer by construction: whether it needed
    a checker, when its inputs closed, whether the month had to be locked. These are
    resolved once and then laid back over each employee's policy AFTER resolution -- not
    merely left out of it. Resolving only the employee-level keys would be cheaper and
    would leave a grade-scoped version setting `checker_required: false` working, which is
    a separation-of-duties hole wearing a scope.
  * EMPLOYEE-LEVEL keys change what somebody is paid or what their own records require --
    rounding, the sandwich rule, whether their structure needs a second approval. Two
    people in one run differing is the point.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_gap4_payroll_policy_scope   (from backend/)
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


from app.services.hrms.tests.test_payroll_live_findings import FakeCollection  # noqa: E402

CO = "C1"
HR = {"_id": "hr-1", "role": "superadmin", "governance_role": "HR", "full_name": "Dummy HR"}
APPROVER = {"_id": "md-1", "role": "superadmin", "governance_role": "MD",
            "full_name": "Dummy MD"}
PERIOD = "2026-03"          # 31 days
END = f"{PERIOD}-31"


async def main() -> int:
    from bson import ObjectId

    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_audit_service as AU
    import app.services.hrms_payroll_service as PR
    import app.services.hrms_policy_version_service as PV
    import app.services.hrms_shift_service as SH

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AU, PR, PV, SH):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    for mod in (PR, PV):
        mod.audit = no_audit

    # ── 0. Every key belongs to exactly one level ────────────────────────────────────
    section("0. The split covers the policy with no key left unscoped")

    run_keys = M.PAYROLL_POLICY_RUN_LEVEL_KEYS
    emp_keys = M.PAYROLL_POLICY_EMPLOYEE_LEVEL_KEYS
    policy_keys = set(M.DEFAULT_PAYROLL_POLICY)
    check("no key is in both sets", not (run_keys & emp_keys), run_keys & emp_keys)
    check("no policy key is in neither (an unclassified key loses its scoping)",
          not (policy_keys - run_keys - emp_keys), policy_keys - run_keys - emp_keys)
    check("neither set invents a key the policy does not have",
          not ((run_keys | emp_keys) - policy_keys), (run_keys | emp_keys) - policy_keys)

    # ── Setup: two grades, one of them scoped ────────────────────────────────────────
    store[M.COLL_SETTINGS] = FakeCollection([
        {"company_id": CO, "payroll_policy": {"net_rounding": "None",
                                              "checker_required": True,
                                              "variance_threshold_percent": 10.0}}])
    store[M.COLL_EMPLOYEE_PROFILES] = FakeCollection([
        {"company_id": CO, "employee_code": "E-M1", "user_id": str(ObjectId()),
         "employment_status": "Active", "grade": "M1", "work_location": "Pune"},
        {"company_id": CO, "employee_code": "E-M2", "user_id": str(ObjectId()),
         "employment_status": "Active", "grade": "M2", "work_location": "Pune"},
    ])
    store[M.COLL_SALARY_COMPONENTS] = FakeCollection([
        {"company_id": CO, "code": "BASIC", "name": "Basic", "component_type": "Earning",
         "active": True}])
    # 30,000.40 over 31 days with every day present: the paise are what rounding moves.
    store[M.COLL_SALARY_STRUCTURES] = FakeCollection([
        {"company_id": CO, "employee_code": code, "effective_from": "2026-01-01",
         "components": [{"code": "BASIC", "amount": 30000.40}]}
        for code in ("E-M1", "E-M2")])
    store[M.COLL_ATTENDANCE] = FakeCollection([
        {"company_id": CO, "employee_code": code, "work_date": f"{PERIOD}-{d:02d}",
         "status": "Present", "payable_day": 1.0, "lop_fraction": 0.0}
        for code in ("E-M1", "E-M2") for d in range(1, 32)])
    store[M.COLL_ATTENDANCE_LOCKS] = FakeCollection([
        {"company_id": CO, "period": PERIOD, "status": "Locked"}])

    await PV.save_definition(HR, CO, {"code": M.POLICY_PAY_POLICY, "name": "Payroll policy",
                                      "module": "payroll"})
    # A version scoped to GRADE M1 that rounds to the rupee -- and that also tries to drop
    # the checker stage, which it must not be allowed to do.
    await PV.save_draft(HR, CO, {
        "policy_code": M.POLICY_PAY_POLICY, "effective_from": "2026-01-01",
        "rules": {"net_rounding": "Nearest", "checker_required": False}})
    await PV.set_status(HR, CO, M.POLICY_PAY_POLICY, 1, "Pending Approval")
    await PV.set_status(APPROVER, CO, M.POLICY_PAY_POLICY, 1, "Approved")
    await PV.assign_scope(HR, CO, {"policy_code": M.POLICY_PAY_POLICY, "version_no": 1,
                                   "scope": {"grades": ["M1"]}})
    await PV.set_status(APPROVER, CO, M.POLICY_PAY_POLICY, 1, "Active")

    # ── 1. The resolver answers differently for the two employees ────────────────────
    section("1. The scoped version resolves for M1 and not for M2")

    m1 = await PR.get_payroll_policy(CO, profile={"grade": "M1"}, on_date=END)
    m2 = await PR.get_payroll_policy(CO, profile={"grade": "M2"}, on_date=END)
    check("M1 gets the scoped rounding", m1["net_rounding"] == "Nearest", m1["net_rounding"])
    check("M2 falls back to the company default",
          m2["net_rounding"] == "None", m2["net_rounding"])
    company = await PR.get_payroll_policy(CO, on_date=END)
    check("asking with no profile at all still answers the company-wide policy",
          company["net_rounding"] == "None", company["net_rounding"])

    # ── 2. One run, two different employee-level answers ────────────────────────────
    section("2. Two grades in ONE run are paid under their own policies")

    store[M.COLL_PAYROLL_RUNS] = FakeCollection([
        {"_id": ObjectId(), "company_id": CO, "period": PERIOD, "status": "Draft"}])
    store[M.COLL_PAYROLL_RECORDS] = FakeCollection()
    await PR.calculate_payroll(HR, CO, PERIOD)
    by = {r["employee_code"]: r for r in store[M.COLL_PAYROLL_RECORDS].docs}

    check("M1's net is rounded to the rupee by the grade-scoped version",
          by["E-M1"]["net_pay"] == 30000.0, by["E-M1"]["net_pay"])
    check("M2's net keeps its paise -- the same run, a different policy",
          by["E-M2"]["net_pay"] == 30000.4, by["E-M2"]["net_pay"])
    check("...and the rounding adjustment is recorded only where it happened",
          by["E-M1"]["net_rounding_adjustment"] == -0.4
          and by["E-M2"]["net_rounding_adjustment"] == 0.0,
          {k: by[k]["net_rounding_adjustment"] for k in by})

    # ── 3. Each record names the version that decided ITS amounts (FRD 30) ──────────
    section("3. The version used is stamped per record, not only per run")

    check("M1's record names version 1",
          (by["E-M1"]["payroll_policy_version"] or {}).get("version_no") == 1,
          by["E-M1"]["payroll_policy_version"])
    check("...and says which scope matched, so the stamp can be explained",
          (by["E-M1"]["payroll_policy_version"] or {}).get("matched_scope") == {"grades": ["M1"]},
          by["E-M1"]["payroll_policy_version"])
    check("M2's record names no version -- it ran on the stored settings",
          by["E-M2"]["payroll_policy_version"] is None,
          by["E-M2"]["payroll_policy_version"])
    run = store[M.COLL_PAYROLL_RUNS].docs[0]
    check("the RUN's own stamp is still the company-wide answer (None here)",
          run["payroll_policy_version"] is None, run.get("payroll_policy_version"))

    # ── 4. A scope cannot reach a run-level decision ────────────────────────────────
    section("4. Run-level keys are unaffected by scoping")

    scoped = await PR._employee_policy(
        CO, await PR.get_payroll_policy(CO, on_date=END),
        {"grade": "M1"}, END)
    check("the version asked for checker_required False and did not get it",
          scoped["checker_required"] is True, scoped["checker_required"])
    check("...while its employee-level key did apply",
          scoped["net_rounding"] == "Nearest", scoped["net_rounding"])
    # The naive implementation -- resolve the whole policy for the employee -- would have
    # returned False here, which is what this check exists to catch.
    raw = await PR.get_payroll_policy(CO, profile={"grade": "M1"}, on_date=END)
    check("the raw resolver DOES return the scoped value, so the overlay is what stops it",
          raw["checker_required"] is False, raw["checker_required"])

    # ── 5. The sandwich rule is per employee too ────────────────────────────────────
    section("5. A scoped sandwich rule changes only its own employees' LOP")

    await PV.save_draft(HR, CO, {
        "policy_code": M.POLICY_PAY_POLICY, "effective_from": "2026-01-01",
        "rules": {"sandwich_weekly_off": True}})
    await PV.set_status(HR, CO, M.POLICY_PAY_POLICY, 2, "Pending Approval")
    await PV.set_status(APPROVER, CO, M.POLICY_PAY_POLICY, 2, "Approved")
    await PV.assign_scope(HR, CO, {"policy_code": M.POLICY_PAY_POLICY, "version_no": 2,
                                   "scope": {"locations": ["Mumbai"]}})
    await PV.set_status(APPROVER, CO, M.POLICY_PAY_POLICY, 2, "Active")
    # The stored settings say nothing about the sandwich rule, so Pune inherits the
    # DEFAULT_PAYROLL_POLICY value and Mumbai gets the version's.
    store[M.COLL_EMPLOYEE_PROFILES].docs.append(
        {"company_id": CO, "employee_code": "E-MUM", "user_id": str(ObjectId()),
         "employment_status": "Active", "grade": "M2", "work_location": "Mumbai"})
    mum = await PR.get_payroll_policy(CO, profile={"work_location": "Mumbai", "grade": "M2"},
                                      on_date=END)
    pune = await PR.get_payroll_policy(CO, profile={"work_location": "Pune", "grade": "M2"},
                                       on_date=END)
    check("the Mumbai version is the one that resolves there",
          mum["sandwich_weekly_off"] is True, mum["sandwich_weekly_off"])
    check("a Pune M2 employee matches neither scoped version",
          pune["net_rounding"] == "None", pune["net_rounding"])

    # ── 6. The structure save asks for the right employee ──────────────────────────
    section("6. structure_approval_required is resolved for the employee")

    await PV.save_draft(HR, CO, {
        "policy_code": M.POLICY_PAY_POLICY, "effective_from": "2026-01-01",
        "rules": {"structure_approval_required": True}})
    await PV.set_status(HR, CO, M.POLICY_PAY_POLICY, 3, "Pending Approval")
    await PV.set_status(APPROVER, CO, M.POLICY_PAY_POLICY, 3, "Approved")
    await PV.assign_scope(HR, CO, {"policy_code": M.POLICY_PAY_POLICY, "version_no": 3,
                                   "scope": {"grades": ["M3"]}})
    await PV.set_status(APPROVER, CO, M.POLICY_PAY_POLICY, 3, "Active")
    store[M.COLL_EMPLOYEE_PROFILES].docs.append(
        {"company_id": CO, "employee_code": "E-M3", "user_id": str(ObjectId()),
         "employment_status": "Active", "grade": "M3", "work_location": "Pune"})

    senior = await PR.save_salary_structure(HR, CO, {
        "employee_code": "E-M3", "effective_from": "2026-04-01",
        "components": [{"code": "BASIC", "amount": 90000}]})
    check("a senior grade's structure needs the second approval the scope asked for",
          senior["status"] == "Pending Approval", senior["status"])
    junior = await PR.save_salary_structure(HR, CO, {
        "employee_code": "E-M2", "effective_from": "2026-04-01",
        "components": [{"code": "BASIC", "amount": 30000}]})
    check("...and a grade outside the scope goes live outright, as before",
          junior["status"] == "Active", junior["status"])

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
