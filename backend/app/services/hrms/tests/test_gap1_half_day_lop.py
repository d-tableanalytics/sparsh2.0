"""Post-review Gap 1 -- the half-day LOP fraction must mean the same thing twice.

Checklist rows P1-030, P1-047, P1-056, P1-077.

`half_day_fraction` (ATT_DAY, FRD §23) was configurable, applied by the day calculator and
frozen on the attendance row as `payable_day` / `lop_fraction`. Payroll then threw it away:
`_payable_days` read only `status` and valued every Half Day at a flat half. A company that
configured a half day to cost a quarter saw a quarter on the attendance screen and was
charged a half in pay -- the two screens disagreeing about the same day, with the pay one
wrong.

The same figure was wrong one layer up. An HR OVERRIDE to Half Day went through
`_status_only`, which hard-coded 0.5, so what a day was worth depended on whether a human
or the calculator decided it. That was invisible while payroll ignored the field; it is a
pay difference now that payroll reads it.

Two statuses deliberately keep payroll's own answer, and section 4 pins that:
  * ON LEAVE is decided by the LEAVE TYPE. The row stores 1.0 for every leave day, so
    honouring it would pay LWP.
  * WEEKLY OFF / HOLIDAY are "off" days whose LOP share the sandwich rule may set, which is
    a payroll policy rather than an attendance fact.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_gap1_half_day_lop   (from backend/)
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
from app.services.hrms.tests.governance_helper import activate_policy_version  # noqa: E402

CO = "C1"
HR = {"_id": "hr-1", "role": "superadmin", "governance_role": "HR", "full_name": "Dummy HR"}
APPROVER = {"_id": "fin-1", "role": "superadmin", "governance_role": "MD",
            "full_name": "Dummy Finance"}
PERIOD = "2026-03"          # 31 days
SALARY = [{"code": "BASIC", "amount": 31000}]


async def main() -> int:
    from bson import ObjectId

    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_attendance_rules_service as AR
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_audit_service as AU
    import app.services.hrms_config_change_service as CC
    import app.services.hrms_payroll_service as PR
    import app.services.hrms_policy_version_service as PV
    import app.services.hrms_shift_service as SH

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AR, AT, AU, CC, PR, PV, SH):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    for mod in (AT, CC, PR, PV):
        mod.audit = no_audit

    store[M.COLL_SETTINGS] = FakeCollection([
        {"company_id": CO, "shift_policy": {**M.DEFAULT_SHIFT_POLICY}}])
    # E-CFG is in Pune, where the quarter-day policy applies. E-LEGACY is in Mumbai and
    # outside its scope, which is also how the fallback half gets exercised.
    store[M.COLL_EMPLOYEE_PROFILES] = FakeCollection([
        {"company_id": CO, "employee_code": "E-CFG", "user_id": str(ObjectId()),
         "employment_status": "Active", "work_location": "Pune", "grade": "M2"},
        {"company_id": CO, "employee_code": "E-LEGACY", "user_id": str(ObjectId()),
         "employment_status": "Active", "work_location": "Mumbai", "grade": "M2"},
        {"company_id": CO, "employee_code": "E-LEAVE", "user_id": str(ObjectId()),
         "employment_status": "Active", "work_location": "Pune", "grade": "M2"},
    ])
    store[M.COLL_SALARY_COMPONENTS] = FakeCollection([
        {"company_id": CO, "code": "BASIC", "name": "Basic",
         "component_type": "Earning", "active": True}])
    store[M.COLL_SALARY_STRUCTURES] = FakeCollection([
        {"company_id": CO, "employee_code": code, "effective_from": "2026-01-01",
         "components": SALARY}
        for code in ("E-CFG", "E-LEGACY", "E-LEAVE")])

    # ── 1. An ATT_DAY policy of 0.75 reaches the row, however the day was decided ──────
    section("1. half_day_fraction 0.75 is frozen on the row (computed AND overridden)")

    await PV.save_definition(HR, CO, {"code": M.POLICY_ATT_DAY, "name": "Daily rules",
                                      "module": "attendance"})
    await PV.save_draft(HR, CO, {
        "policy_code": M.POLICY_ATT_DAY, "effective_from": "2026-01-01",
        "rules": {"half_day_fraction": 0.75}})
    await PV.assign_scope(HR, CO, {"policy_code": M.POLICY_ATT_DAY, "version_no": 1,
                                   "scope": {"locations": ["Pune"]}})
    await activate_policy_version(CC, HR, APPROVER, CO, M.POLICY_ATT_DAY, 1)

    computed = await AR.compute_day(CO, "E-CFG", f"{PERIOD}-30", "09:30", "12:00")
    check("the CALCULATOR applies it: a short day is worth 0.75, LOP 0.25",
          computed["status"] == "Half Day" and computed["payable_day"] == 0.75
          and computed["lop_fraction"] == 0.25, computed)

    row = await AT.mark_attendance(HR, CO, {
        "employee_code": "E-CFG", "work_date": f"{PERIOD}-31",
        "override_status": "Half Day"})
    check("an HR OVERRIDE applies it too (was a hard-coded 0.5)",
          row["payable_day"] == 0.75 and row["lop_fraction"] == 0.25, row)

    mumbai = await AT.mark_attendance(HR, CO, {
        "employee_code": "E-LEGACY", "work_date": f"{PERIOD}-31",
        "override_status": "Half Day"})
    check("an employee outside the policy's scope still gets the flat half",
          mumbai["payable_day"] == 0.5 and mumbai["lop_fraction"] == 0.5, mumbai)

    # ── 2. Payroll values the day from the frozen fraction ────────────────────────────
    section("2. _payable_days reads the frozen fraction, not the status")

    att = store.setdefault(M.COLL_ATTENDANCE, FakeCollection())
    att.docs[:] = []            # section 1 wrote through mark_attendance; start clean

    def rows(code, *, fractions: bool):
        """29 Present + 2 Half Day. `fractions=False` is a row written before the policy
        existed: no payable_day, no lop_fraction, nothing for payroll to read."""
        out = []
        for d in range(1, 32):
            half = d in (30, 31)
            doc = {"company_id": CO, "employee_code": code,
                   "work_date": f"{PERIOD}-{d:02d}",
                   "status": "Half Day" if half else "Present"}
            if fractions:
                doc["payable_day"] = 0.75 if half else 1.0
                doc["lop_fraction"] = 0.25 if half else 0.0
            out.append(doc)
        return out

    att.docs.extend(rows("E-CFG", fractions=True))
    att.docs.extend(rows("E-LEGACY", fractions=False))

    cfg = await PR._payable_days(CO, "E-CFG", PERIOD, {}, {}, sandwich=False)
    check("a 0.75 half day costs 0.25 LOP: 2 halves -> 0.5 LOP, 30.5 payable",
          cfg["lop_days"] == 0.5 and cfg["payable_days"] == 30.5, cfg)

    legacy = await PR._payable_days(CO, "E-LEGACY", PERIOD, {}, {}, sandwich=False)
    check("a legacy row with NEITHER field still costs 0.5 -> 1.0 LOP, 30.0 payable",
          legacy["lop_days"] == 1.0 and legacy["payable_days"] == 30.0, legacy)

    check("payable days equal the sum of payable_day across the rows",
          cfg["payable_days"] == round(sum(
              r["payable_day"] for r in att.docs if r["employee_code"] == "E-CFG"), 2),
          cfg["payable_days"])
    check("present days follow payable_day, not the status either",
          cfg["present_days"] == 30.5, cfg["present_days"])

    # Half of the point of the frozen basis is being able to see WHICH fraction was used
    # months later; a basis still saying 0.5 would be a trail of the wrong number.
    basis = {b["date"]: b for b in cfg["basis"]}
    check("the frozen basis records the fraction actually used, and names the day",
          basis[f"{PERIOD}-30"]["lop"] == 0.25
          and basis[f"{PERIOD}-30"]["present"] == 0.75
          and basis[f"{PERIOD}-30"]["bucket"] == "half_day", basis[f"{PERIOD}-30"])

    # One field alone is enough: the calculator writes them as complements, and a row
    # carrying only one should not silently fall back to the hard-coded half.
    att.docs.append({"company_id": CO, "employee_code": "E-ONE",
                     "work_date": f"{PERIOD}-01", "status": "Half Day",
                     "lop_fraction": 0.25})
    one = await PR._payable_days(
        CO, "E-ONE", PERIOD, {"joined_on": f"{PERIOD}-01", "resigned_on": f"{PERIOD}-01"},
        {}, sandwich=False)
    check("a row carrying only lop_fraction has the present share derived",
          one["lop_days"] == 0.25 and one["present_days"] == 0.75, one)

    # ── 3. End to end: the run's own figures move with the policy ──────────────────────
    section("3. calculate_payroll pays the configured fraction")

    store[M.COLL_PAYROLL_RUNS] = FakeCollection([
        {"_id": ObjectId(), "company_id": CO, "period": PERIOD, "status": "Draft"}])
    store[M.COLL_ATTENDANCE_LOCKS] = FakeCollection([
        {"company_id": CO, "period": PERIOD, "status": "Locked"}])
    store[M.COLL_PAYROLL_RECORDS] = FakeCollection()
    att.docs[:] = [r for r in att.docs if r["employee_code"] != "E-ONE"]

    await PR.calculate_payroll(HR, CO, PERIOD)
    by = {r["employee_code"]: r for r in store[M.COLL_PAYROLL_RECORDS].docs}
    check("both employees were calculated", set(by) >= {"E-CFG", "E-LEGACY"}, sorted(by))
    check("the record carries the payable days payroll actually used",
          by["E-CFG"]["payable_days"] == 30.5
          and by["E-LEGACY"]["payable_days"] == 30.0,
          {k: by[k]["payable_days"] for k in by})
    # 31,000 over 31 days is 1,000 a day, so the quarter-day difference is exactly 500.
    check("...and that is 500 more pay on the same two half days",
          by["E-CFG"]["prorated_gross"] == 30500
          and by["E-LEGACY"]["prorated_gross"] == 30000,
          {k: by[k]["prorated_gross"] for k in by})

    # ── 4. What payroll must keep deciding for itself ─────────────────────────────────
    section("4. On Leave and off days keep payroll's own answer")

    # `_status_only` stores payable_day 1.0 for EVERY leave day, paid or not. Payroll must
    # keep asking the leave type, or an LWP day would be paid in full.
    store[M.COLL_LEAVE_TYPES] = FakeCollection([
        {"company_id": CO, "code": "LWP", "paid": False},
        {"company_id": CO, "code": "EL", "paid": True}])
    store[M.COLL_LEAVES] = FakeCollection([
        {"company_id": CO, "leave_no": "LV-UNPAID", "leave_type": "LWP"},
        {"company_id": CO, "leave_no": "LV-PAID", "leave_type": "EL"}])
    att.docs.extend([
        {"company_id": CO, "employee_code": "E-LEAVE", "work_date": f"{PERIOD}-{d:02d}",
         "status": "Present", "payable_day": 1.0, "lop_fraction": 0.0}
        for d in range(1, 30)]
        + [{"company_id": CO, "employee_code": "E-LEAVE", "work_date": f"{PERIOD}-30",
            "status": "On Leave", "leave_ref": "LV-UNPAID",
            "payable_day": 1.0, "lop_fraction": 0.0},
           {"company_id": CO, "employee_code": "E-LEAVE", "work_date": f"{PERIOD}-31",
            "status": "On Leave", "leave_ref": "LV-PAID",
            "payable_day": 1.0, "lop_fraction": 0.0}])

    lv = await PR._payable_days(CO, "E-LEAVE", PERIOD, {}, {}, sandwich=False)
    check("an LWP day is still 1.0 LOP although the row says payable 1.0",
          lv["lop_days"] == 1.0 and lv["payable_days"] == 30.0, lv)
    check("...and the paid leave day is still not LOP", lv["leave_days"] == 1, lv)

    # A Sunday the sandwich rule claims must stay claimable: the row says payable 1.0.
    att.docs.extend([
        {"company_id": CO, "employee_code": "E-SAND", "work_date": f"{PERIOD}-01",
         "status": "Absent", "payable_day": 0.0, "lop_fraction": 1.0},
        {"company_id": CO, "employee_code": "E-SAND", "work_date": f"{PERIOD}-02",
         "status": "Weekly Off", "payable_day": 1.0, "lop_fraction": 0.0},
        {"company_id": CO, "employee_code": "E-SAND", "work_date": f"{PERIOD}-03",
         "status": "Absent", "payable_day": 0.0, "lop_fraction": 1.0}])
    sand = await PR._payable_days(
        CO, "E-SAND", PERIOD,
        {"joined_on": f"{PERIOD}-01", "resigned_on": f"{PERIOD}-03"}, {}, sandwich=True)
    check("the sandwich rule still claims the Sunday between two LOP days",
          sand["sandwiched_off_days"] == 1 and sand["lop_days"] == 3.0, sand)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
