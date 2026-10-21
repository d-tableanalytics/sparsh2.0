"""Post-review Gap 8 -- the leave-mismatch exception on month-end closure.

Checklist row P1-054.

`closure_dashboard` counted OPEN leave requests, which answers "has everybody decided
yet". It could not answer "do the decisions agree with the attendance", and those are the
two days that cost money:

  * PUNCHED WHILE ON LEAVE -- an approved leave day that also carries a punch. Payroll pays
    the leave and ignores the punch, so either the leave should be cancelled or somebody
    punched on a colleague's behalf, and nobody finds out which.
  * ABSENT WITH NOTHING BEHIND IT -- an Absent day with no leave reference, no OD and no
    approved leave covering it. A full day of LOP about to be deducted with no record of
    why, which is the most disputed line on a payslip.

NOT added to the lock-blocking set, and section 3 pins that. Locking is how payroll gets
its basis, so a company with one disputed day would be unable to run payroll at all --
`unexplained_absence` has always been reported without blocking for the same reason, and
changing that for every existing company is the client's call.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_gap8_leave_mismatch   (from backend/)
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
PERIOD = "2026-05"


def pair(items):
    return sorted((m["employee_code"], m["work_date"]) for m in items)


async def main() -> int:
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_audit_service as AU

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AT, AU):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    AT.audit = no_audit
    AT._today = lambda: f"{PERIOD}-31"

    store[M.COLL_SETTINGS] = FakeCollection([
        {"company_id": CO, "shift_policy": {**M.DEFAULT_SHIFT_POLICY}}])
    store[M.COLL_EMPLOYEE_PROFILES] = FakeCollection([
        {"company_id": CO, "employee_code": c, "user_id": f"u-{c}",
         "employment_status": "Active"} for c in ("E-001", "E-002", "E-003")])

    # E-001 is on approved leave 11-13 May. E-002's leave is only PENDING, so it is not a
    # mismatch -- it is an open request, which the dashboard already counted.
    store[M.COLL_LEAVES] = FakeCollection([
        {"company_id": CO, "leave_no": "LV-0001", "employee_code": "E-001",
         "start_date": f"{PERIOD}-11", "end_date": f"{PERIOD}-13", "status": "Approved"},
        {"company_id": CO, "leave_no": "LV-0002", "employee_code": "E-002",
         "start_date": f"{PERIOD}-20", "end_date": f"{PERIOD}-20", "status": "Pending"},
        # Approved leave that STARTS BEFORE the period and runs into it: only the days
        # inside the month may be compared, and the range has to be clipped to find them.
        {"company_id": CO, "leave_no": "LV-0003", "employee_code": "E-003",
         "start_date": "2026-04-28", "end_date": f"{PERIOD}-02", "status": "Approved"},
    ])

    att = store.setdefault(M.COLL_ATTENDANCE, FakeCollection())
    att.docs.extend([
        # E-001: on leave 11-13. The 12th carries a punch -- a mismatch.
        {"company_id": CO, "employee_code": "E-001", "work_date": f"{PERIOD}-11",
         "status": "On Leave", "leave_ref": "LV-0001"},
        {"company_id": CO, "employee_code": "E-001", "work_date": f"{PERIOD}-12",
         "status": "On Leave", "leave_ref": "LV-0001",
         "actual_in": "09:40", "actual_out": "18:20"},
        {"company_id": CO, "employee_code": "E-001", "work_date": f"{PERIOD}-13",
         "status": "On Leave", "leave_ref": "LV-0001"},
        # E-002: an Absent day with nothing behind it -- a mismatch.
        {"company_id": CO, "employee_code": "E-002", "work_date": f"{PERIOD}-05",
         "status": "Absent"},
        # ...and one that IS explained, by a leave reference. Not a mismatch.
        {"company_id": CO, "employee_code": "E-002", "work_date": f"{PERIOD}-06",
         "status": "Absent", "leave_ref": "LV-OLD"},
        # ...and one explained by an OD. Not a mismatch either.
        {"company_id": CO, "employee_code": "E-002", "work_date": f"{PERIOD}-07",
         "status": "Absent", "od_ref": "OD-0001"},
        # E-003: the 1st is inside the leave that began in April and carries a punch.
        {"company_id": CO, "employee_code": "E-003", "work_date": f"{PERIOD}-01",
         "status": "On Leave", "actual_in": "10:05"},
        # A plain present day is not a mismatch however it is punched.
        {"company_id": CO, "employee_code": "E-003", "work_date": f"{PERIOD}-04",
         "status": "Present", "actual_in": "09:30", "actual_out": "18:30"},
    ])

    # ── 1. What counts as a mismatch ────────────────────────────────────────────────
    section("1. The two shapes, found and told apart")

    out = await AT.leave_mismatches(CO, PERIOD)
    check("three mismatching days in all", out["leave_mismatch"] == 3, out["leave_mismatch"])
    check("two of them are punches on an approved leave day",
          out["punched_while_on_leave"] == 2, out["punched_while_on_leave"])
    check("one is an absence with nothing behind it",
          out["absent_without_leave_or_od"] == 1, out["absent_without_leave_or_od"])
    check("and they are exactly the right days",
          pair(out["examples"]) == sorted([("E-003", f"{PERIOD}-01"),
                                           ("E-002", f"{PERIOD}-05"),
                                           ("E-001", f"{PERIOD}-12")]),
          pair(out["examples"]))
    check("a leave that began in the PREVIOUS month still covers its days in this one",
          ("E-003", f"{PERIOD}-01") in pair(out["examples"]), pair(out["examples"]))
    check("each example says what is wrong, so HR does not have to work it out",
          all(m.get("why") for m in out["examples"]), out["examples"])
    check("...and a punched-on-leave example names the leave it contradicts",
          any(m.get("leave_no") == "LV-0001" for m in out["examples"]), out["examples"])

    # ── 2. What does NOT count ──────────────────────────────────────────────────────
    section("2. What is deliberately not a mismatch")

    reported = pair(out["examples"])
    check("an Absent day with a leave reference is explained",
          ("E-002", f"{PERIOD}-06") not in reported, reported)
    check("an Absent day with an OD is explained",
          ("E-002", f"{PERIOD}-07") not in reported, reported)
    check("a leave day with no punch is just a leave day",
          ("E-001", f"{PERIOD}-11") not in reported
          and ("E-001", f"{PERIOD}-13") not in reported, reported)
    check("a normal present day is not a mismatch however it is punched",
          ("E-003", f"{PERIOD}-04") not in reported, reported)

    # A PENDING leave is an open request, which the dashboard counts separately. Punching
    # on a day whose leave nobody has approved is not a contradiction yet.
    att.docs.append({"company_id": CO, "employee_code": "E-002",
                     "work_date": f"{PERIOD}-20", "status": "Present",
                     "actual_in": "09:30", "actual_out": "18:30"})
    still = await AT.leave_mismatches(CO, PERIOD)
    check("punching on a day whose leave is only PENDING is not yet a contradiction",
          still["leave_mismatch"] == 3, still["leave_mismatch"])

    # ── 3. Reported, not blocking ───────────────────────────────────────────────────
    section("3. It does not block the lock (behaviour unchanged)")

    dash = await AT.closure_dashboard(HR, CO, PERIOD)
    check("the dashboard reports the count", dash["leave_mismatch"] == 3,
          dash.get("leave_mismatch"))
    check("...and the split, which is what decides how each is fixed",
          (dash["punched_while_on_leave"], dash["absent_without_leave_or_od"]) == (2, 1),
          (dash.get("punched_while_on_leave"), dash.get("absent_without_leave_or_od")))
    check("...and names the days", len(dash["examples"]) == 3, dash.get("examples"))

    # Nothing else is open in this period: no pending days, no open regularisation, no OD,
    # and the one open leave request is cleared below. So ready_to_lock is decided by the
    # mismatches alone, which is what makes this check meaningful.
    store[M.COLL_LEAVES].docs = [lv for lv in store[M.COLL_LEAVES].docs
                                 if lv["status"] == "Approved"]
    clean = await AT.closure_dashboard(HR, CO, PERIOD)
    check("the period is STILL ready to lock with three mismatches outstanding",
          clean["ready_to_lock"] is True and clean["leave_mismatch"] == 3,
          (clean["ready_to_lock"], clean["leave_mismatch"]))
    # ...while the exceptions that DID block still do, so this change added a report and
    # moved no gate.
    att.docs.append({"company_id": CO, "employee_code": "E-001",
                     "work_date": f"{PERIOD}-25", "status": "Pending"})
    blocked = await AT.closure_dashboard(HR, CO, PERIOD)
    check("a day still Pending does stop it, exactly as before",
          blocked["ready_to_lock"] is False and blocked["missing_punches"] == 1,
          (blocked["ready_to_lock"], blocked["missing_punches"]))

    # ── 4. A quiet month stays quiet ────────────────────────────────────────────────
    section("4. A month with nothing wrong reports nothing")

    empty = await AT.leave_mismatches(CO, "2026-09")
    check("no attendance and no leave -> no mismatches, not an error",
          empty["leave_mismatch"] == 0 and empty["examples"] == [], empty)

    # The count is exact even when the examples are capped -- a screen listing four hundred
    # dates helps nobody, but an understated count would hide the problem.
    att.docs.extend([
        {"company_id": CO, "employee_code": f"E-BULK{i:03d}", "work_date": f"2026-07-{d:02d}",
         "status": "Absent"}
        for i in range(1, 6) for d in range(1, 11)])
    bulk = await AT.leave_mismatches(CO, "2026-07")
    check("the count is exact above the example cap",
          bulk["leave_mismatch"] == 50, bulk["leave_mismatch"])
    check("...and the examples are capped and say so",
          len(bulk["examples"]) == AT.MAX_MISMATCH_EXAMPLES
          and bulk["examples_truncated"] is True,
          (len(bulk["examples"]), bulk["examples_truncated"]))

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
