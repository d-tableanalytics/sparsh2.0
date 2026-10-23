"""Post-review Gap 2 -- §23 `approval_levels`, enforced rather than displayed.

Checklist rows P1-034, P1-051.

ATT_REGULARISATION.approval_levels (1 = manager only, 2 = manager then HR) was resolved per
employee and per date, editable in the Attendance Policy Designer, shown back on the screen
-- and read by nothing. `act_on_regularization` always required Manager Approved then HR
Approved. A company that configured one level had every request stop at Manager Approved
and sit there: the day was never recalculated, so the employee's punch correction simply did
not happen, and the screen said the rule was in force.

The setting the designer labels "OD / Regularisation" governs both flows and ignored both --
regularisation hard-wired to two levels, an OD hard-wired to one. Each flow's DEFAULT stays
its own current behaviour, because the number has never been read and no company's stored
value should silently flip either flow:

    levels    regularisation          outdoor duty
    unset     manager then HR (as today)   single decision (as today)
    1         manager is final             single decision
    2         manager then HR              manager then HR

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_gap2_approval_levels   (from backend/)
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
from app.services.hrms.tests.governance_helper import activate_policy_version  # noqa: E402

CO = "C1"
HR = {"_id": "hr-1", "role": "superadmin", "governance_role": "HR", "full_name": "Dummy HR"}
MGR = {"_id": "mgr-1", "role": "staff", "governance_role": "HOD", "full_name": "Dummy Manager"}

# Pune gets a one-level policy; Mumbai is outside its scope and keeps today's two.
DAY = "2026-05-11"
LOCKED_DAY = "2026-04-13"


async def main() -> int:
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_attendance_rules_service as AR
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_audit_service as AU
    import app.services.hrms_config_change_service as CC
    import app.services.hrms_id_service as ID
    import app.services.hrms_policy_version_service as PV
    import app.services.hrms_shift_service as SH

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AR, AT, AU, CC, ID, PV, SH):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    for mod in (AT, CC, PV):
        mod.audit = no_audit

    # The §23 regularisation window is relative to TODAY, so the suite pins today rather
    # than quietly expiring whenever the real clock moves past the window.
    AT._today = lambda: "2026-05-12"

    counter = {"n": 0}

    async def fake_id(kind, company, year):
        counter["n"] += 1
        return f"{kind[:3].upper()}-{counter['n']:04d}"
    AT.next_business_id = fake_id

    # Both employees report to the same manager, so _assert_may_decide lets MGR act. The
    # team is read off `reporting_manager` on the USER document, not off the profile.
    store["staff"] = FakeCollection([
        {"_id": "u-one", "full_name": "One", "reporting_manager": "mgr-1"},
        {"_id": "u-two", "full_name": "Two", "reporting_manager": "mgr-1"},
        {"_id": "mgr-1", "full_name": "Dummy Manager"},
    ])
    store[M.COLL_SETTINGS] = FakeCollection([
        {"company_id": CO, "shift_policy": {**M.DEFAULT_SHIFT_POLICY}}])
    store[M.COLL_EMPLOYEE_PROFILES] = FakeCollection([
        {"company_id": CO, "employee_code": "E-ONE", "user_id": "u-one",
         "employment_status": "Active", "work_location": "Pune",
         "reporting_manager_id": "mgr-1"},
        {"company_id": CO, "employee_code": "E-TWO", "user_id": "u-two",
         "employment_status": "Active", "work_location": "Mumbai",
         "reporting_manager_id": "mgr-1"},
    ])

    # ── 0. The resolver must not invent a level nobody configured ─────────────────────
    section("0. unset stays unset (it used to be reported as 1)")

    bare = await AT.regularisation_rules(CO, {}, DAY)
    check("an unconfigured company resolves approval_levels None, not 1",
          bare.get("approval_levels") is None, bare)

    await PV.save_definition(HR, CO, {"code": M.POLICY_ATT_REGULARISATION,
                                      "name": "Regularisation", "module": "attendance"})
    await PV.save_draft(HR, CO, {
        "policy_code": M.POLICY_ATT_REGULARISATION, "effective_from": "2026-01-01",
        "rules": {"approval_levels": 1}})
    await PV.assign_scope(HR, CO, {"policy_code": M.POLICY_ATT_REGULARISATION,
                                   "version_no": 1, "scope": {"locations": ["Pune"]}})
    await activate_policy_version(CC, HR, MGR, CO, M.POLICY_ATT_REGULARISATION, 1)

    pune = await AT.regularisation_rules(
        CO, {"work_location": "Pune"}, DAY)
    check("the scoped policy resolves 1 for Pune", pune.get("approval_levels") == 1, pune)
    mumbai = await AT.regularisation_rules(CO, {"work_location": "Mumbai"}, DAY)
    check("...and leaves Mumbai unconfigured",
          mumbai.get("approval_levels") is None, mumbai)

    # ── 1. One level: the manager's approval is the decision ──────────────────────────
    section("1. Level 1 -- the manager's approval recalculates the day")

    att = store.setdefault(M.COLL_ATTENDANCE, FakeCollection())
    att.docs.append({"company_id": CO, "employee_code": "E-ONE", "work_date": DAY,
                     "actual_in": "11:10", "actual_out": None, "status": "Pending",
                     "source": "Manual"})

    req = await AT.request_regularization(HR, CO, {
        "employee_code": "E-ONE", "work_date": DAY, "exception_type": "Missing punch",
        "proposed_in": "09:30", "proposed_out": "18:30", "reason": "Forgot to punch out"})
    check("the request freezes the level it was raised under",
          req["approval_levels"] == 1, req.get("approval_levels"))

    done = await AT.act_on_regularization(MGR, CO, req["req_no"], {
        "decision": "Manager Approved", "remarks": "Confirmed with the team"})
    check("the manager's approval lands the request on Approved, not Manager Approved",
          done["status"] == "Approved", done["status"])
    check("...and records the manager as the one who acted",
          done["manager_action_by"] == "mgr-1" and done["manager_action_at"] is not None, done)
    check("no HR sign-off is claimed, because none was given",
          done.get("hr_action_by") in (None, ""), done.get("hr_action_by"))

    row = next(r for r in att.docs if r["employee_code"] == "E-ONE")
    check("the DAY was recalculated from the approved punches",
          row["actual_in"] == "09:30" and row["actual_out"] == "18:30"
          and row["status"] == "Present", row)
    check("...flagged as regularised, through this request",
          row["regularization_flag"] is True and row["regularized_from"] == req["req_no"], row)
    check("the raw values are kept -- the original record is preserved (FRD 18)",
          row["corrected_in"] == "09:30" and len(row["modification_history"]) == 1
          and row["modification_history"][0]["old"]["actual_in"] == "11:10", row)
    check("hr_status is not forged on the day either",
          row.get("hr_status") is None, row.get("hr_status"))

    # There is no second level to reach, so asking for one is a 409 that says why.
    att.docs.append({"company_id": CO, "employee_code": "E-ONE",
                     "work_date": "2026-05-12", "status": "Pending"})
    solo = await AT.request_regularization(HR, CO, {
        "employee_code": "E-ONE", "work_date": "2026-05-12",
        "exception_type": "Missing punch", "proposed_in": "09:30", "proposed_out": "18:30"})
    await expect("asking for an HR sign-off under one level",
                 AT.act_on_regularization(HR, CO, solo["req_no"], {"decision": "Approved"}),
                 409, "one approval only")

    # ── 2. Two levels (and unset) behave exactly as before ────────────────────────────
    section("2. Unset -- the manager's approval still only passes it to HR")

    att.docs.append({"company_id": CO, "employee_code": "E-TWO", "work_date": DAY,
                     "actual_in": "11:10", "actual_out": None, "status": "Pending",
                     "source": "Manual"})
    req2 = await AT.request_regularization(HR, CO, {
        "employee_code": "E-TWO", "work_date": DAY, "exception_type": "Missing punch",
        "proposed_in": "09:30", "proposed_out": "18:30"})
    check("the Mumbai request freezes no level", req2["approval_levels"] is None, req2)

    mid = await AT.act_on_regularization(MGR, CO, req2["req_no"], {
        "decision": "Manager Approved"})
    check("the request waits at Manager Approved",
          mid["status"] == "Manager Approved", mid["status"])
    two_row = next(r for r in att.docs if r["employee_code"] == "E-TWO")
    check("...and the day is untouched until HR signs",
          two_row["actual_in"] == "11:10" and two_row["status"] == "Pending", two_row)

    final = await AT.act_on_regularization(HR, CO, req2["req_no"], {"decision": "Approved"})
    check("HR's sign-off then approves it and rewrites the day",
          final["status"] == "Approved"
          and next(r for r in att.docs if r["employee_code"] == "E-TWO")["status"] == "Present")
    check("the HR path still records an hr_status on the day",
          next(r for r in att.docs
               if r["employee_code"] == "E-TWO")["hr_status"] == "Approved")

    # ── 3. A locked month refuses BOTH paths ──────────────────────────────────────────
    section("3. A locked month is refused on the one-level path too")

    store[M.COLL_ATTENDANCE_LOCKS] = FakeCollection([
        {"company_id": CO, "period": "2026-04", "status": "Locked"}])
    # The request itself is raised before the lock; the lock lands while it is in flight,
    # which is the case the check has to catch.
    corrections = store.setdefault(M.COLL_ATTENDANCE_CORRECTIONS, FakeCollection())
    corrections.docs.extend([
        {"company_id": CO, "req_no": "REG-LOCK-1", "employee_code": "E-ONE",
         "work_date": LOCKED_DAY, "status": "Pending", "approval_levels": 1,
         "proposed_in": "09:30", "proposed_out": "18:30"},
        {"company_id": CO, "req_no": "REG-LOCK-2", "employee_code": "E-TWO",
         "work_date": LOCKED_DAY, "status": "Manager Approved", "approval_levels": 2,
         "proposed_in": "09:30", "proposed_out": "18:30"},
    ])
    await expect("one level: the manager's (final) approval in a locked month",
                 AT.act_on_regularization(MGR, CO, "REG-LOCK-1",
                                          {"decision": "Manager Approved"}),
                 409, "locked month")
    await expect("two levels: HR's sign-off in a locked month",
                 AT.act_on_regularization(HR, CO, "REG-LOCK-2", {"decision": "Approved"}),
                 409, "locked month")
    check("neither refusal left a half-finished write on the day",
          not any(r.get("work_date") == LOCKED_DAY for r in att.docs),
          [r for r in att.docs if r.get("work_date") == LOCKED_DAY])

    # ── 4. The same setting governs Outdoor Duty ──────────────────────────────────────
    section("4. Outdoor Duty honours the level the designer offers for it")

    od_one = await AT.request_od(HR, CO, {
        "employee_code": "E-ONE", "od_date": DAY, "purpose": "Client visit"})
    check("a one-level OD is a single decision, as every OD has been",
          od_one["approval_levels"] == 1, od_one.get("approval_levels"))
    acted = await AT.act_on_od(MGR, CO, od_one["od_no"], {"approved": True})
    check("...so the manager's approval marks the day On OD",
          acted["status"] == "Approved"
          and next(r for r in att.docs if r["employee_code"] == "E-ONE"
                   and r["work_date"] == DAY)["status"] == "On OD", acted["status"])

    await PV.save_draft(HR, CO, {
        "policy_code": M.POLICY_ATT_REGULARISATION, "effective_from": "2026-01-01",
        "rules": {"approval_levels": 2}})
    await PV.assign_scope(HR, CO, {"policy_code": M.POLICY_ATT_REGULARISATION,
                                   "version_no": 2, "scope": {"locations": ["Mumbai"]}})
    await activate_policy_version(CC, HR, MGR, CO, M.POLICY_ATT_REGULARISATION, 2)

    od_two = await AT.request_od(HR, CO, {
        "employee_code": "E-TWO", "od_date": "2026-05-20", "purpose": "Site audit"})
    check("a two-level OD freezes 2", od_two["approval_levels"] == 2, od_two)
    step = await AT.act_on_od(MGR, CO, od_two["od_no"], {"approved": True})
    check("the manager's approval stops at Manager Approved",
          step["status"] == "Manager Approved", step["status"])
    check("...and the day is NOT yet On OD",
          not any(r["employee_code"] == "E-TWO" and r["work_date"] == "2026-05-20"
                  for r in att.docs))
    await expect("a manager cannot also give the OD's final sign-off",
                 AT.act_on_od(MGR, CO, od_two["od_no"], {"approved": True}),
                 403, "final sign-off")
    closed = await AT.act_on_od(HR, CO, od_two["od_no"], {"approved": True})
    check("HR's sign-off marks the day On OD",
          closed["status"] == "Approved"
          and next(r for r in att.docs if r["employee_code"] == "E-TWO"
                   and r["work_date"] == "2026-05-20")["status"] == "On OD", closed["status"])

    # A Manager Approved OD has not written the day, so the month is not ready to lock.
    section("5. A half-approved OD still blocks the month")
    store[M.COLL_OD_REQUESTS].docs.append({
        "company_id": CO, "od_no": "OD-OPEN", "employee_code": "E-TWO",
        "od_date": "2026-06-04", "status": "Manager Approved", "approval_levels": 2})
    dash = await AT.closure_dashboard(HR, CO, "2026-06")
    check("the closure dashboard counts it as open",
          dash["pending_od"] == 1 and dash["ready_to_lock"] is False, dash["pending_od"])

    # ── 6. The approver screen can see which it is ────────────────────────────────────
    section("6. The level is reported on the list, resolved for legacy rows")

    corrections.docs.append({
        "company_id": CO, "req_no": "REG-LEGACY", "employee_code": "E-ONE",
        "work_date": DAY, "status": "Pending", "proposed_in": "09:30",
        "created_at": "2026-05-01"})
    listed = {r["req_no"]: r for r in await AT.list_regularizations(HR, CO)}
    check("a legacy row with no frozen level has it resolved for the approver",
          listed["REG-LEGACY"]["approval_levels"] == 1,
          listed["REG-LEGACY"].get("approval_levels"))
    check("a decided row is left alone rather than resolved pointlessly",
          listed[req["req_no"]]["approval_levels"] == 1
          and listed[req2["req_no"]]["approval_levels"] is None)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
