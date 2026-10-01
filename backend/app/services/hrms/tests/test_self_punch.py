"""Self check-in / check-out, geo-fenced to the company's offices.

Run:  python -m app.services.hrms.tests.test_self_punch   (from backend/)
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
# An office in Pune, and points around it.
OFFICE = {"name": "Pune HQ", "lat": 18.5204, "lng": 73.8567, "radius_m": 200}
INSIDE = (18.5210, 73.8570)      # ~75 m away
OUTSIDE = (18.5300, 73.8567)     # ~1.07 km away


async def main() -> None:
    from app.models import hrms as M
    import app.db.mongodb as mongo
    import app.services.hrms_self_punch_service as SP
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_attendance_service as ATT

    store = {M.COLL_SETTINGS: FakeCollection(), M.COLL_ATTENDANCE: FakeCollection(),
             M.COLL_PUNCH_SEGMENTS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())
    for mod in (SP, AUD, ATT):
        mod.get_collection = mongo.get_collection

    code = {"value": "EMP-001"}

    async def own(actor, company_id):
        if not code["value"]:
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail="You have no employee record here yet")
        return code["value"]
    SP._own_code = own
    clock = {"t": ("2026-10-01", "09:20")}

    def local_now():
        from datetime import datetime
        return datetime.now(), clock["t"][0], clock["t"][1]
    SP._local_now = local_now

    ME = {"_id": "u1", "full_name": "Emp One"}
    try:
        section("Distance")
        d_in = SP.distance_m(OFFICE["lat"], OFFICE["lng"], *INSIDE)
        d_out = SP.distance_m(OFFICE["lat"], OFFICE["lng"], *OUTSIDE)
        check(f"a point ~75 m away measures {round(d_in)} m", 50 < d_in < 100)
        check(f"a point ~1 km away measures {round(d_out)} m", 1000 < d_out < 1100)

        section("No office yet")
        await expect_http("checking in before HR has set an office",
                          SP.punch(ME, COMPANY, {"action": "in", "lat": INSIDE[0], "lng": INSIDE[1]}),
                          409, "no office location")

        section("HR sets up the office")
        await expect_http("an office with no name",
                          SP.save_offices(ME, COMPANY, [{"lat": 1, "lng": 1}]), 422, "name")
        await expect_http("a latitude off the globe",
                          SP.save_offices(ME, COMPANY, [{**OFFICE, "lat": 123}]), 422, "range")
        await expect_http("a 5-metre radius",
                          SP.save_offices(ME, COMPANY, [{**OFFICE, "radius_m": 5}]), 422, "radius")
        saved = await SP.save_offices(ME, COMPANY, [OFFICE])
        check("the office is saved", saved[0]["name"] == "Pune HQ" and saved[0]["radius_m"] == 200)

        section("Check-in is refused outside the office")
        await expect_http("checking in from ~1 km away",
                          SP.punch(ME, COMPANY, {"action": "in", "lat": OUTSIDE[0], "lng": OUTSIDE[1]}),
                          403, "within 200 m")
        await expect_http("a location only accurate to 900 m",
                          SP.punch(ME, COMPANY, {"action": "in", "lat": INSIDE[0], "lng": INSIDE[1],
                                                 "accuracy": 900}), 422, "too rough")
        check("nothing was written by the refusals", store[M.COLL_ATTENDANCE].docs == [])
        await expect_http("checking out before checking in",
                          SP.punch(ME, COMPANY, {"action": "out", "lat": INSIDE[0], "lng": INSIDE[1]}),
                          409, "check in first")

        section("Check-in inside the office")
        r = await SP.punch(ME, COMPANY, {"action": "in", "lat": INSIDE[0], "lng": INSIDE[1], "accuracy": 20})
        rec = store[M.COLL_ATTENDANCE].docs[0]
        check("the day is recorded with the check-in time", rec["actual_in"] == "09:20")
        check("...as a self punch, from Pune HQ, with the distance",
              rec["source"] == "self" and rec["self_in"]["office"] == "Pune HQ"
              and 50 < rec["self_in"]["distance_m"] < 100)
        check("...and late minutes come from the shift policy", isinstance(rec["late_minutes"], int))
        check("the reply confirms it", "Checked in at 09:20" in r["message"] and r["can_check_out"])
        check("a raw punch segment is kept", store[M.COLL_PUNCH_SEGMENTS].docs[0]["source"] == "self")
        await expect_http("checking in twice",
                          SP.punch(ME, COMPANY, {"action": "in", "lat": INSIDE[0], "lng": INSIDE[1]}),
                          409, "already checked in")

        section("Check-out")
        clock["t"] = ("2026-10-01", "18:30")
        r = await SP.punch(ME, COMPANY, {"action": "out", "lat": INSIDE[0], "lng": INSIDE[1]})
        rec = store[M.COLL_ATTENDANCE].docs[0]
        check("the check-out time is recorded and worked minutes computed",
              rec["actual_out"] == "18:30" and rec["worked_minutes"] == 550)
        check("both punches carry their location", rec["self_out"]["office"] == "Pune HQ")
        await expect_http("checking out twice",
                          SP.punch(ME, COMPANY, {"action": "out", "lat": INSIDE[0], "lng": INSIDE[1]}),
                          409, "already checked out")

        section("A locked day and a person with no employee record")
        rec["locked"] = True
        clock["t"] = ("2026-10-01", "18:40")
        await expect_http("punching on a locked day",
                          SP.punch(ME, COMPANY, {"action": "out", "lat": INSIDE[0], "lng": INSIDE[1]}),
                          409, "locked")
        code["value"] = None
        await expect_http("someone with no employee profile",
                          SP.punch(ME, COMPANY, {"action": "in", "lat": INSIDE[0], "lng": INSIDE[1]}),
                          409, "no employee record")

        section("Who may self-punch by default")
        from app.utils.hrms_access import can
        emp = {"_id": "e", "role": "staff", "_source_collection": "staff"}
        md = {"_id": "m", "role": "staff", "_source_collection": "staff", "governance_role": "MD"}
        check("every staff member may check themselves in", can(emp, M.Cap.ATTENDANCE_SELF_PUNCH))
        check("the MD (not an employee) may not by default", not can(md, M.Cap.ATTENDANCE_SELF_PUNCH))
    finally:
        mongo.get_collection = original

    passed = sum(RESULTS)
    print(f"\n=== {passed}/{len(RESULTS)} checks passed ===")
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
