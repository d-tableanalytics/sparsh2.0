"""FRD 8 -- Attendance Processing & Monthly Closure, walked as one chain.

8 is four claims in sequence, and each only means anything if the one before it held:

  1. a day is calculated from the ASSIGNED SCHEDULE and the source punches;
  2. approved OD / leave / regularisation are applied BEFORE the day is used for payroll;
  3. at month-end HR sees what is still open, payable days and LOP are computed, and the
     snapshot is locked;
  4. after the lock, a correction flows as an AUTHORISED ADJUSTMENT and never as a direct
     edit of the locked basis.

So this suite is deliberately one story told forward, not ten independent assertions: the
interesting failures live in the joins (a day that leave touched but payroll valued from
the stale status, a locked row something still wrote to), and a per-piece test cannot see
those.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_monthly_closure_flow   (from backend/)
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
HR = {"_id": "hr-1", "role": "admin", "full_name": "Hana HR"}


async def main() -> int:
    from bson import ObjectId
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_attendance_rules_service as AR
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_payroll_service as PS
    import app.services.hrms_shift_service as SH
    import app.services.hrms_policy_version_service as PV

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AR, AT, PS, SH, PV):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    AT.audit = no_audit
    PS.audit = no_audit

    async def _allow(*a, **k):
        return None

    async def _same_query(actor, company_id, query):
        return query

    AT.can = lambda user, cap: True
    AT._assert_self_or_privileged = _allow
    AT._assert_may_decide = _allow
    AT._scope_query = _same_query
    # The actor is HR: the final sign-off on a regularisation is HR's by design (§17), and
    # WHO may decide is another suite's subject -- this one is about what the decision
    # does to the day and to the month.
    AT.hrms_role = lambda actor: M.HrmsRole.HR

    user_id = ObjectId()
    store.setdefault(M.COLL_SETTINGS, FakeCollection()).docs.append(
        {"company_id": CO, "shift_policy": {**M.DEFAULT_SHIFT_POLICY}})
    store.setdefault("learners", FakeCollection()).docs.append(
        {"_id": user_id, "company_id": CO, "full_name": "Asha A"})
    store.setdefault("staff", FakeCollection())
    store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection()).docs.append(
        {"_id": ObjectId(), "company_id": CO, "employee_code": "E1",
         "user_id": str(user_id), "joined_on": "2025-01-01", "work_location": "Pune"})

    # -- 1 ---------------------------------------------------------------------------
    section("1. A day is calculated from the assigned schedule and the source punches")

    await AT.mark_attendance(HR, CO, {
        "employee_code": "E1", "work_date": "2026-03-02",
        "actual_in": "09:50", "actual_out": "18:30", "source": "Biometric"})
    row = store[M.COLL_ATTENDANCE].docs[0]
    check("the company schedule decided the scheduled window, not the punch",
          row.get("scheduled_in") == "09:30" and row.get("scheduled_out") == "18:30", row)
    check("late is measured against that schedule, with grace applied",
          row.get("late_minutes") == 15 and row.get("grace_applied_minutes") == 5, row)
    check("the day is valued as it is judged (payable_day frozen on the row)",
          row.get("payable_day") == 1.0, row.get("payable_day"))

    # A day with no punch at all.
    await AT.mark_attendance(HR, CO, {
        "employee_code": "E1", "work_date": "2026-03-03", "status": "Absent"})

    # -- 2 ---------------------------------------------------------------------------
    section("2. Approved OD / leave / regularisation are applied BEFORE payroll reads the day")

    # 2a. OD.
    store.setdefault(M.COLL_OD_REQUESTS, FakeCollection()).docs.append({
        "company_id": CO, "od_no": "OD-1", "employee_code": "E1", "od_date": "2026-03-04",
        "status": M.OdStatus.MANAGER_APPROVED.value, "purpose": "Client visit"})
    AT._od_approval_levels = None
    await AT.act_on_od(HR, CO, "OD-1", {"approved": True})
    od_day = next(r for r in store[M.COLL_ATTENDANCE].docs if r["work_date"] == "2026-03-04")
    check("an approved OD becomes the day's status, fully payable",
          od_day["status"] == "On OD" and od_day["payable_day"] == 1.0
          and od_day["od_ref"] == "OD-1", od_day)

    # 2b. Regularisation turns the Absent day into a judged day.
    store.setdefault(M.COLL_ATTENDANCE_CORRECTIONS, FakeCollection()).docs.append({
        "company_id": CO, "req_no": "REG-1", "employee_code": "E1",
        "work_date": "2026-03-03", "proposed_in": "09:30", "proposed_out": "18:30",
        "reason": "Biometric did not read my thumb", "request_type": "Missing punch",
        "status": M.CorrectionStatus.MANAGER_APPROVED.value})
    await AT.act_on_regularization(HR, CO, "REG-1", {
        "decision": M.CorrectionStatus.APPROVED.value,
        "remarks": "Gate register checked"})
    reg_day = next(r for r in store[M.COLL_ATTENDANCE].docs if r["work_date"] == "2026-03-03")
    check("an approved regularisation REPLACES the absent day before payroll sees it",
          reg_day["status"] == "Present" and reg_day["payable_day"] == 1.0, reg_day)
    check("...and the day says why it changed (§6 Correction)",
          reg_day.get("regularisation_reason") == "Biometric did not read my thumb", reg_day)

    # 2c. A biometric re-import must NOT overwrite any of those decisions.
    for d, label in (("2026-03-04", "an OD day"), ("2026-03-03", "a regularised day")):
        existing = next(r for r in store[M.COLL_ATTENDANCE].docs if r["work_date"] == d)
        protected = (existing.get("status") in AR.PROTECTED_STATUSES
                     or existing.get("source") in AR.PROTECTED_SOURCES)
        check(f"{label} is protected from a later biometric import", protected,
              (existing.get("status"), existing.get("source")))

    # 2d. Unpaid leave is LOP; paid leave is not. The leave TYPE decides, not the day row.
    store.setdefault(M.COLL_LEAVE_TYPES, FakeCollection()).docs.extend([
        {"company_id": CO, "code": "EL", "name": "Earned", "paid": True},
        {"company_id": CO, "code": "LWP", "name": "Leave without pay", "paid": False},
    ])
    store.setdefault(M.COLL_LEAVES, FakeCollection()).docs.extend([
        {"company_id": CO, "leave_no": "LV-1", "employee_code": "E1", "leave_type": "EL"},
        {"company_id": CO, "leave_no": "LV-2", "employee_code": "E1", "leave_type": "LWP"},
    ])
    for d, ref in (("2026-03-05", "LV-1"), ("2026-03-06", "LV-2")):
        store[M.COLL_ATTENDANCE].docs.append({
            "company_id": CO, "employee_code": "E1", "work_date": d,
            "status": "On Leave", "source": "leave", "leave_ref": ref, "locked": False})

    # -- 3 ---------------------------------------------------------------------------
    section("3. Month-end: open exceptions are visible, payable days and LOP computed")

    store[M.COLL_OD_REQUESTS].docs.append({
        "company_id": CO, "od_no": "OD-2", "employee_code": "E1", "od_date": "2026-03-09",
        "status": M.OdStatus.PENDING.value})
    dash = await AT.closure_dashboard(HR, CO, PERIOD)
    check("an undecided OD is reported as still open", dash["pending_od"] == 1, dash)
    check("...so the month is not ready to lock", dash["ready_to_lock"] is False, dash)

    await expect("locking a month with open items and NO reason is refused",
                 AT.lock_period(HR, CO, PERIOD), 409, "resolve them")

    basis = await PS._payable_days(CO, "E1", PERIOD,
                                   profile=store[M.COLL_EMPLOYEE_PROFILES].docs[0])
    buckets = {b["date"]: b["bucket"] for b in basis["basis"]}
    check("the OD day is payable, not LOP", buckets.get("2026-03-04") == "present",
          buckets.get("2026-03-04"))
    check("the regularised day is payable", buckets.get("2026-03-03") == "present",
          buckets.get("2026-03-03"))
    check("PAID leave costs nothing", buckets.get("2026-03-05") == "leave",
          buckets.get("2026-03-05"))
    check("UNPAID leave is LOP -- decided by the leave TYPE, not the day's status",
          buckets.get("2026-03-06") == "lwp", buckets.get("2026-03-06"))
    check("payable days and LOP are both reported",
          basis["payable_days"] is not None and basis["lop_days"] >= 1.0, basis["lop_days"])
    check("every in-service day is recorded in the basis, so the figure is reproducible",
          len(basis["basis"]) == basis["days_in_period"], len(basis["basis"]))

    # HR resolves the exception, then locks.
    store[M.COLL_OD_REQUESTS].docs[-1]["status"] = M.OdStatus.REJECTED.value
    dash = await AT.closure_dashboard(HR, CO, PERIOD)
    check("once resolved, the month reports ready to lock",
          dash["ready_to_lock"] is True, dash)

    lock = await AT.lock_period(HR, CO, PERIOD)
    check("the snapshot is locked", lock["status"] == "Locked", lock)
    check("...and WHAT was open at the moment of locking is frozen on the lock",
          "exceptions_at_lock" in lock, sorted(lock))
    check("every day of the period is frozen, not just the lock document",
          all(r.get("locked") for r in store[M.COLL_ATTENDANCE].docs),
          [r["work_date"] for r in store[M.COLL_ATTENDANCE].docs if not r.get("locked")])

    # -- 3b --------------------------------------------------------------------------
    section("3b. Payroll may only rest on a locked snapshot, and notices if it moves")

    policy = await PS.get_payroll_policy(CO)
    check("a company that configures nothing REQUIRES the lock before calculating",
          policy.get("require_attendance_lock") is True,
          policy.get("require_attendance_lock"))

    # The lock gate at calculate time is only half the promise: HR can unlock afterwards,
    # correct a day, and leave a calculated run quietly resting on figures that no longer
    # match. attendance_basis_moved is what closes that, so it is checked both ways.
    # `locked_at` is the version marker: reopening and re-locking stamps a new one on the
    # same row, which is exactly the move this has to catch. (lock_id is left out because
    # the fake collection does not mint _id on upsert; locked_at is the stronger check
    # anyway -- it moves even when the row does not.)
    this_lock = store[M.COLL_ATTENDANCE_LOCKS].docs[0]
    run = {"attendance_basis": {"locked": True,
                                "locked_at": this_lock.get("locked_at")}}
    check("a run calculated on THIS lock is not stale",
          await PS.attendance_basis_moved(CO, PERIOD, run) is None)

    stale = {"attendance_basis": {"locked": True, "locked_at": "an-earlier-stamp"}}
    moved = await PS.attendance_basis_moved(CO, PERIOD, stale)
    check("a run whose month was reopened and re-locked IS stale, and says so",
          bool(moved) and "locked again" in moved, moved)

    this_lock["status"] = "Open"
    reopened_msg = await PS.attendance_basis_moved(CO, PERIOD, run)
    check("...and a run whose month was simply reopened is stale too",
          bool(reopened_msg) and "unlocked" in reopened_msg, reopened_msg)
    this_lock["status"] = "Locked"

    check("a run that never claimed a locked basis is left to the calculate gate",
          await PS.attendance_basis_moved(
              CO, PERIOD, {"attendance_basis": {"locked": False}}) is None)

    # -- 4 ---------------------------------------------------------------------------
    section("4. After the lock, nothing edits the basis directly")

    await expect("marking a locked day",
                 AT.mark_attendance(HR, CO, {"employee_code": "E1",
                                             "work_date": "2026-03-02",
                                             "actual_in": "09:00"}), 409, "locked")
    await expect("raising a regularisation inside a locked month",
                 AT.request_regularization(HR, CO, {"employee_code": "E1",
                                                    "work_date": "2026-03-02",
                                                    "proposed_in": "09:00"}), 409, "locked")
    store[M.COLL_OD_REQUESTS].docs.append({
        "company_id": CO, "od_no": "OD-3", "employee_code": "E1", "od_date": "2026-03-10",
        "status": M.OdStatus.MANAGER_APPROVED.value})
    await expect("approving an OD into a locked month",
                 AT.act_on_od(HR, CO, "OD-3", {"approved": True}), 409, "locked")

    # The ONE legitimate door, while payroll has not yet closed on the snapshot.
    reopened = await AT.unlock_period(HR, CO, PERIOD, "corrected punch for E1")
    check("an authorised, reasoned reopen is allowed while payroll is still open",
          reopened["status"] == "Open", reopened)
    check("...and the reopen is recorded with its reason",
          reopened["unlock_history"][-1]["reason"] == "corrected punch for E1",
          reopened.get("unlock_history"))
    check("...and the days are editable again",
          not any(r.get("locked") for r in store[M.COLL_ATTENDANCE].docs))

    # Once payroll has closed ON that snapshot, the door shuts.
    #
    # OD-3 is still undecided -- the refusal above stopped it from writing the day, it did
    # not close the request -- so the month is legitimately not ready to lock again until
    # HR deals with it. That is the control working, so the test resolves it the way HR
    # would rather than locking around it.
    await expect("re-locking while OD-3 is still undecided",
                 AT.lock_period(HR, CO, PERIOD), 409, "open od")
    store[M.COLL_OD_REQUESTS].docs[-1]["status"] = M.OdStatus.REJECTED.value
    await AT.lock_period(HR, CO, PERIOD)
    store.setdefault(M.COLL_PAYROLL_RUNS, FakeCollection()).docs.append(
        {"company_id": CO, "period": PERIOD, "status": "Locked"})
    await expect("reopening a month whose payroll is already final",
                 AT.unlock_period(HR, CO, PERIOD, "late correction"), 409,
                 "post-lock payroll adjustment")
    check("...and the attendance stayed locked through the refusal",
          all(r.get("locked") for r in store[M.COLL_ATTENDANCE].docs))

    # So the correction has to be an authorised adjustment, in a LATER period.
    store.setdefault(M.COLL_PAYROLL_RECORDS, FakeCollection()).docs.append(
        {"company_id": CO, "period": PERIOD, "employee_code": "E1",
         "employee_name": "Asha A", "net_pay": 50000})
    adj = await PS.create_post_lock_adjustment(HR, CO, PERIOD, {
        "employee_code": "E1", "adjustment_type": "Arrear", "amount": 1200,
        "reason": "March punch corrected after lock"})
    check("the correction lands as an ADJUSTMENT, not an edit",
          adj["adjustment_type"] == "Arrear" and adj["amount"] == 1200, adj)
    check("...carried into a LATER period, leaving March's basis untouched",
          adj["target_period"] > PERIOD, adj["target_period"])
    check("...with a reason and an owner on it",
          bool(adj["reason"]) and bool(adj["created_by"]), adj)
    await expect("an adjustment with no reason",
                 PS.create_post_lock_adjustment(HR, CO, PERIOD, {
                     "employee_code": "E1", "adjustment_type": "Arrear",
                     "amount": 10, "reason": "  "}), 422, "reason is required")
    await expect("an adjustment backdated into the locked period itself",
                 PS.create_post_lock_adjustment(HR, CO, PERIOD, {
                     "employee_code": "E1", "adjustment_type": "Arrear", "amount": 10,
                     "reason": "x", "target_period": PERIOD}), 422, "later period")

    check("March's own figures never moved",
          store[M.COLL_PAYROLL_RECORDS].docs[0]["net_pay"] == 50000)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
