"""Attendance capture/import layer and timing rules (client requirement).

Biometric import, flexible-timing approval, effective hours, the monthly buffer.

Run:  python -m app.services.hrms.tests.test_attendance_rules   (from backend/)
"""
import asyncio

RESULTS = []


def check(label: str, ok: bool) -> None:
    RESULTS.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")


def section(title: str) -> None:
    print(f"\n-- {title} --")


async def expect_http(label: str, coro, status: int, fragment: str = None) -> None:
    from fastapi import HTTPException
    try:
        await coro
        check(f"{label} -> {status}", False)
    except HTTPException as e:
        ok = e.status_code == status and (not fragment or fragment.lower() in str(e.detail).lower())
        check(f"{label} -> {status}" + (f" ('{fragment}')" if fragment else "")
              + ("" if ok else f"  [got {e.status_code}: {e.detail}]"), ok)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"


async def main() -> None:
    from app.models import hrms as M
    import app.db.mongodb as mongo
    import app.services.hrms_attendance_rules_service as R
    import app.services.hrms_attendance_service as ATT
    import app.services.hrms_audit_service as AUD

    store = {M.COLL_ATTENDANCE: FakeCollection(), M.COLL_PUNCH_SEGMENTS: FakeCollection(),
             M.COLL_SETTINGS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
             R.COLL_FLEXI: FakeCollection(),
             M.COLL_EMPLOYEE_PROFILES: FakeCollection([
                 {"employee_code": "EMP-001", "company_id": COMPANY, "biometric_id": "501"},
                 {"employee_code": "EMP-002", "company_id": COMPANY}])}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())
    for mod in (R, ATT, AUD):
        mod.get_collection = mongo.get_collection

    counter = {"n": 0}

    async def next_id(kind, company, year):
        counter["n"] += 1
        return f"FT-{year}-{counter['n']:03d}"
    R.next_business_id = next_id

    async def profile(company_id, code):
        return {"employee_code": code, "full_name": code}

    async def ok(*a, **kw):
        return None

    async def manager(profile):
        return "mgr"

    async def scope(actor, company_id, query):
        return query
    ATT._get_profile, ATT._assert_self_or_privileged = profile, ok
    ATT._reporting_manager_id, ATT._assert_may_decide, ATT._scope_query = manager, ok, scope

    HR = {"_id": "hr1", "full_name": "HR"}
    att = store[M.COLL_ATTENDANCE]
    day = lambda code, d: next((r for r in att.docs if r["employee_code"] == code and r["work_date"] == d), None)  # noqa: E731
    try:
        section("Reading a biometric export")
        days, bad = R.punches_from_rows([
            ["Employee Code", "Date", "Time"],
            ["EMP-001", "01/10/2026", "09:41"], ["EMP-001", "01/10/2026", "13:02"],
            ["EMP-001", "01/10/2026", "6:35 PM"], ["", "01/10/2026", "09:00"]])
        check("one row per punch: first and last punch of the day are kept",
              sorted(days[("EMP-001", "2026-10-01")]) == ["09:41", "13:02", "18:35"])
        check("a row with no employee code is reported, not guessed", len(bad) == 1)
        days, _ = R.punches_from_rows([["Emp Code", "Attendance Date", "In Time", "Out Time"],
                                       [501.0, "2026-10-02", "09:25", "18:40"]])
        check("In/Out columns, an Excel number code, ISO dates",
              sorted(days[("501", "2026-10-02")]) == ["09:25", "18:40"])
        days, _ = R.punches_from_rows([["User ID", "Date Time"], ["EMP-002", "2026-10-03 09:50:12"]])
        check("a single Date Time column", days[("EMP-002", "2026-10-03")] == ["09:50"])
        from fastapi import HTTPException
        try:
            R.punches_from_rows([["Name", "Date", "Time"], ["x", "2026-10-01", "09:00"]])
            check("a file with no code column is refused", False)
        except HTTPException as e:
            check("a file with no code column is refused -> 422", e.status_code == 422)

        section("Importing it")
        store[M.COLL_ATTENDANCE].docs.extend([
            {"company_id": COMPANY, "employee_code": "EMP-002", "work_date": "2026-10-01",
             "status": "On Leave", "source": "leave"},
            {"company_id": COMPANY, "employee_code": "EMP-002", "work_date": "2026-10-02",
             "status": "Present", "locked": True}])
        csv_bytes = ("Employee Code,Date,Time\n"
                     "EMP-001,2026-10-01,09:41\nEMP-001,2026-10-01,18:35\n"
                     "501,2026-10-02,09:25\n501,2026-10-02,18:40\n"
                     "EMP-002,2026-10-01,09:30\nEMP-002,2026-10-02,09:30\n"
                     "EMP-999,2026-10-01,09:30\n").encode()
        rep = await R.import_biometric(HR, COMPANY, "punches.csv", csv_bytes)
        d1 = day("EMP-001", "2026-10-01")
        check("EMP-001: in 09:41, out 18:35, from the biometric file",
              d1["actual_in"] == "09:41" and d1["actual_out"] == "18:35" and d1["source"] == "biometric")
        check("...late minutes judged against 9:30 + grace", d1["late_minutes"] == 6)
        check("a biometric ID is matched to its employee (501 -> EMP-001)",
              day("EMP-001", "2026-10-02")["actual_in"] == "09:25")
        check("a day on leave is not overwritten", day("EMP-002", "2026-10-01")["status"] == "On Leave")
        check("a locked day is not overwritten", "actual_in" not in day("EMP-002", "2026-10-02"))
        check("both are reported as skipped, with the reason",
              {s["reason"] for s in rep["skipped"]} == {"already On Leave", "locked"})
        check("an unknown code is reported", rep["unknown_codes"] == ["EMP-999"])
        check("2 days created", rep["days_created"] == 2)

        section("Flexible timing")
        await expect_http("no reason", R.request_flexi(HR, COMPANY, {
            "employee_code": "EMP-001", "from_date": "2026-10-01", "to_date": "2026-10-05",
            "shift_start": "10:30", "shift_end": "19:30"}), 422, "why")
        await expect_http("end time before start", R.request_flexi(HR, COMPANY, {
            "employee_code": "EMP-001", "from_date": "2026-10-01", "shift_start": "19:30",
            "shift_end": "10:30", "reason": "x"}), 422, "after the start")
        req = await R.request_flexi(HR, COMPANY, {
            "employee_code": "EMP-001", "from_date": "2026-10-01", "to_date": "2026-10-05",
            "shift_start": "10:30", "shift_end": "19:30", "reason": "School run this week"})
        check("the request is Pending", req["status"] == "Pending")
        await expect_http("an overlapping request", R.request_flexi(HR, COMPANY, {
            "employee_code": "EMP-001", "from_date": "2026-10-03", "shift_start": "11:00",
            "shift_end": "20:00", "reason": "x"}), 409, "already covers")
        before = await R.compute_day(COMPANY, "EMP-001", "2026-10-02", "10:40", "19:30")
        check("before approval, 10:40 against 9:30 is 65 min late", before["late_minutes"] == 65)
        await expect_http("rejecting with no reason",
                          R.act_on_flexi(HR, COMPANY, req["flexi_no"], {"approved": False}), 422, "why")
        done = await R.act_on_flexi(HR, COMPANY, req["flexi_no"], {"approved": True})
        check("approved", done["status"] == "Approved")
        after = await R.compute_day(COMPANY, "EMP-001", "2026-10-02", "10:40", "19:30")
        check("after approval, 10:40 against the flexible 10:30 is 5 min late (grace 5)",
              after["late_minutes"] == 5 and after["flexi_no"] == req["flexi_no"])
        check("days already recorded in the range were re-judged",
              done["rejudged_days"] == 2 and day("EMP-001", "2026-10-01")["late_minutes"] == 0)
        outside = await R.compute_day(COMPANY, "EMP-001", "2026-10-09", "10:40", "19:30")
        check("outside the range the office timing applies again", outside["late_minutes"] == 65)

        section("Monthly buffer")
        buf = R.monthly_buffer([
            {"employee_code": "A", "work_date": "2026-10-01", "late_minutes": 25},
            {"employee_code": "A", "work_date": "2026-10-07", "late_minutes": 50},
            {"employee_code": "B", "work_date": "2026-10-02", "late_minutes": 20}], 60)
        a = next(x for x in buf if x["employee_code"] == "A")
        b = next(x for x in buf if x["employee_code"] == "B")
        check("A: 75 late minutes -> 60 within the buffer, 15 beyond",
              a["late_minutes"] == 75 and a["within_buffer"] == 60 and a["beyond_buffer"] == 15)
        check("B: 20 late minutes, all within the buffer", b["beyond_buffer"] == 0)
    finally:
        mongo.get_collection = original

    passed = sum(RESULTS)
    print(f"\n=== {passed}/{len(RESULTS)} checks passed ===")
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
