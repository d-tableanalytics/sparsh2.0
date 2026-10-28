"""FRD 6 -- Daily Attendance fields, one section per field group of the 6 table.

The groups are Identity, Date/Schedule, Actual, Calculated, Status, Correction, Approval,
Payroll, Lock and Audit. A day that reaches payroll or a dispute is read on its own, so
each group has to be answerable FROM THE DAY -- not by going to the directory for the
department, to the regularisation list for the reason, or to the lock document for who
closed the month.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_daily_attendance_fields   (from backend/)
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
HR = {"_id": "hr-1", "role": "admin", "full_name": "Hana HR"}


async def main() -> int:
    from bson import ObjectId
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_attendance_rules_service as AR
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_export_service as EX
    import app.services.hrms_shift_service as SH
    import app.services.hrms_policy_version_service as PV
    # The name on a day is resolved by the payroll service's _employee_names/_name_of,
    # which reads the USER doc -- identity is never copied onto the profile (see
    # hrms_employee_service), so this suite has to stand up a real user to see a name.
    import app.services.hrms_payroll_service as PS

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AR, AT, EX, SH, PV, PS):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    AT.audit = no_audit

    dept_id, user_id = ObjectId(), ObjectId()
    store.setdefault(M.COLL_SETTINGS, FakeCollection()).docs.append(
        {"company_id": CO, "shift_policy": {**M.DEFAULT_SHIFT_POLICY}})
    store.setdefault(M.COLL_DEPARTMENTS, FakeCollection()).docs.append(
        {"_id": dept_id, "company_id": CO, "name": "Accounts"})
    store.setdefault("learners", FakeCollection()).docs.append(
        {"_id": user_id, "company_id": CO, "full_name": "Asha A", "email": "asha@c1.com"})
    store.setdefault("staff", FakeCollection())
    store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection()).docs.append(
        {"_id": ObjectId(), "company_id": CO, "employee_code": "E1",
         "user_id": str(user_id), "department_id": str(dept_id), "work_location": "Pune"})

    # 2026-03-10 is a Tuesday.
    WORK_DATE = "2026-03-10"

    # Row scoping and "may I act on this person" are other suites' subjects; this one is
    # about WHICH FIELDS a day carries, so HR is simply allowed through.
    async def _allow(*a, **k):
        return None

    async def _same_query(actor, company_id, query):
        return query

    AT.can = lambda user, cap: True
    AT._assert_self_or_privileged = _allow
    AT._scope_query = _same_query

    await AT.mark_attendance(HR, CO, {
        "employee_code": "E1", "work_date": WORK_DATE,
        "actual_in": "09:50", "actual_out": "17:00",
        "source": "Biometric", "source_reference": "BIO-9921"})

    rows = await AT.list_attendance(HR, CO, employee_code="E1")
    check("a day was recorded and read back", len(rows) == 1, rows)
    r = rows[0]

    # -- Identity --------------------------------------------------------------------
    section("Identity: Employee ID; Employee Name; Department; Location")
    check("Employee ID", r.get("employee_code") == "E1", r.get("employee_code"))
    check("Employee Name", r.get("employee_name") == "Asha A", r.get("employee_name"))
    check("Department", r.get("department") == "Accounts", r.get("department"))
    check("Location", r.get("work_location") == "Pune", r.get("work_location"))

    # -- Date / Schedule -------------------------------------------------------------
    section("Date / Schedule: Attendance Date; Day; Shift; Scheduled In; Scheduled Out")
    check("Attendance Date", r.get("work_date") == WORK_DATE)
    check("Day is the weekday name, not the date again", r.get("day") == "Tuesday",
          r.get("day"))
    check("Shift resolves (code, or the company timing when none applies)",
          "shift_code" in r, r.get("shift_code"))
    check("Scheduled In", r.get("scheduled_in") == "09:30", r.get("scheduled_in"))
    check("Scheduled Out", r.get("scheduled_out") == "18:30", r.get("scheduled_out"))

    # -- Actual ----------------------------------------------------------------------
    section("Actual: Actual In; Actual Out; source / reference")
    check("Actual In", r.get("actual_in") == "09:50")
    check("Actual Out", r.get("actual_out") == "17:00")
    check("Source", r.get("source") == "Biometric", r.get("source"))
    check("Reference", r.get("source_reference") == "BIO-9921", r.get("source_reference"))

    # -- Calculated ------------------------------------------------------------------
    section("Calculated: Worked; Payable; Late; Early; Grace applied")
    check("Worked Hours", r.get("worked_minutes") == 430, r.get("worked_minutes"))
    check("Payable Hours", r.get("payable_hours") is not None, r.get("payable_hours"))
    check("Late Minutes (20 late, 5 forgiven as grace)",
          r.get("late_minutes") == 15, r.get("late_minutes"))
    check("Early Minutes (left 17:00 against an 18:30 out)",
          r.get("early_minutes") == 90, r.get("early_minutes"))
    check("Grace Applied", r.get("grace_applied_minutes") == 5,
          r.get("grace_applied_minutes"))

    # -- Status / Payroll ------------------------------------------------------------
    section("Status and Payroll: status; Payable Day; LOP Day / Fraction")
    check("Status", r.get("status") in {"Present", "Half Day", "Absent", "Weekly Off",
                                        "Holiday", "On Leave", "On OD"}, r.get("status"))
    check("Payable Day", r.get("payable_day") is not None, r.get("payable_day"))
    check("LOP Fraction", r.get("lop_fraction") is not None, r.get("lop_fraction"))

    # -- Audit -----------------------------------------------------------------------
    section("Audit: original / raw values kept beside the corrected ones")
    stored = store[M.COLL_ATTENDANCE].docs[0]
    for key in ("original_in", "original_out", "original_source"):
        check(f"{key} is kept from the first write", key in stored, sorted(stored))
    check("a day nobody has touched carries no modification history to show",
          not stored.get("modification_history"))
    await AT.mark_attendance(HR, CO, {
        "employee_code": "E1", "work_date": WORK_DATE,
        "actual_in": "09:35", "actual_out": "18:35", "source": "Manual"})
    stored = store[M.COLL_ATTENDANCE].docs[0]
    hist = stored.get("modification_history") or []
    check("re-marking it records WHAT changed, not just that it did",
          bool(hist) and hist[-1]["old"]["actual_in"] == "09:50"
          and hist[-1]["new"]["actual_in"] == "09:35", hist)
    check("...and the ORIGINAL raw punch survives the correction (§6 Audit)",
          stored.get("original_in") == "09:50", stored.get("original_in"))

    # -- Correction / Approval / Lock -------------------------------------------------
    # Applied straight onto the day, which is what approving a regularisation does.
    section("Correction and Approval: flag; reason; evidence; manager / HR; comments")
    store[M.COLL_ATTENDANCE].docs[0].update({
        "regularization_flag": True, "regularized_from": "REG-1",
        "regularisation_reason": "Biometric did not read my thumb",
        "regularisation_request_type": "Missing punch",
        "regularisation_evidence": "Gate register page 4",
        "regularisation_has_evidence_file": True,
        "corrected_in": "09:30", "corrected_out": "18:30",
        "manager_status": "Manager Approved", "hr_status": "Approved",
        "approver_comments": "Gate register checked",
    })
    r2 = (await AT.list_attendance(HR, CO, employee_code="E1"))[0]
    check("Regularisation flag", r2.get("regularization_flag") is True)
    check("Proposed / corrected In-Out",
          r2.get("corrected_in") == "09:30" and r2.get("corrected_out") == "18:30")
    check("REASON travels onto the day, not only onto the request",
          r2.get("regularisation_reason") == "Biometric did not read my thumb",
          r2.get("regularisation_reason"))
    check("Evidence reference", r2.get("regularisation_evidence") == "Gate register page 4")
    check("...and the day records that a FILE exists without copying it",
          r2.get("regularisation_has_evidence_file") is True)
    check("Manager Status", r2.get("manager_status") == "Manager Approved")
    check("HR Status", r2.get("hr_status") == "Approved")
    check("Approver comments", r2.get("approver_comments") == "Gate register checked")

    section("Lock: Locked Flag; Locked By; Locked Date")
    store.setdefault(M.COLL_ATTENDANCE_LOCKS, FakeCollection())
    AT.closure_dashboard = _fake_dashboard
    await AT.lock_period(HR, CO, WORK_DATE[:7])
    locked = store[M.COLL_ATTENDANCE].docs[0]
    check("Locked Flag", locked.get("locked") is True)
    check("Locked Date", locked.get("locked_at") is not None)
    check("LOCKED BY is a NAME a person can read, not only an id",
          locked.get("locked_by_name") == "Hana HR", locked.get("locked_by_name"))
    check("...and the id is still there for the audit trail",
          bool(locked.get("locked_by")))

    await AT.unlock_period(HR, CO, WORK_DATE[:7], "correction needed")
    cleared = store[M.COLL_ATTENDANCE].docs[0]
    check("reopening clears the locker's name too -- no stale 'locked by'",
          cleared.get("locked") is False and cleared.get("locked_by_name") is None,
          cleared.get("locked_by_name"))

    # -- The export carries the same groups ------------------------------------------
    section("The daily export carries the same §6 fields")
    keys = {k for k, _ in EX.ATTENDANCE_DAILY_COLUMNS}
    for key in ("employee_code", "employee_name", "department", "work_location",
                "work_date", "day", "status", "shift_code", "actual_in", "actual_out",
                "late_minutes", "early_minutes", "payable_day", "lop_fraction", "source"):
        check(f"export column '{key}'", key in keys, sorted(keys))
    check("no export column asks for a key the rows never carry -- 'weekday' is gone",
          "weekday" not in keys)
    dump = await EX.attendance_daily(HR, CO, WORK_DATE[:7])
    day_col = [k for k, _ in EX.ATTENDANCE_DAILY_COLUMNS].index("day")
    check("...so the exported Day cell is actually filled",
          dump["rows"] and dump["rows"][0][day_col] == "Tuesday",
          dump["rows"][0] if dump["rows"] else None)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


async def _fake_dashboard(actor, company_id, period):
    """Closure readiness is its own suite's subject; this one only needs the lock to run."""
    return {"ready_to_lock": True, "missing_punches": 0, "missing_out_punches": 0,
            "pending_regularizations": 0, "pending_od": 0, "pending_leaves": 0,
            "unexplained_absence": 0}


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
