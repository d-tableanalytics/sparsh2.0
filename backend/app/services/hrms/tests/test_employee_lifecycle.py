"""FRD 4 -- the Employee Creation / Change process, walked end to end in its stated order.

Each section is one numbered step of the process. The point is not that the pieces exist
(other suites pin those individually) but that they CHAIN: the record HR commits in step 1
is the one numbering stamps in step 3, carries the assignments of steps 4-7, and is the one
whose step-10 changes are effective-dated with the old value preserved.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_employee_lifecycle   (from backend/)
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


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

CO = "C1"


async def main() -> int:
    from datetime import datetime, timedelta, timezone
    from bson import ObjectId
    from app.models import hrms as M
    from app.utils import hrms_access as A
    import app.db.mongodb as mongo

    U_HR, U_A, U_B, U_MGR = (str(ObjectId()) for _ in range(4))
    DEPT, DEPT2 = str(ObjectId()), str(ObjectId())
    DESIG, DESIG2 = str(ObjectId()), str(ObjectId())

    store = {
        "learners": FakeCollection([
            {"_id": ObjectId(U_HR), "full_name": "Hana HR", "email": "hr@c1.com",
             "company_id": CO, "role": "clientuser", "governance_role": "HR",
             "is_active": True},
            {"_id": ObjectId(U_A), "full_name": "Asha A", "email": "asha@c1.com",
             "company_id": CO, "role": "clientuser", "is_active": True},
            {"_id": ObjectId(U_B), "full_name": "Bela B", "email": "bela@c1.com",
             "company_id": CO, "role": "clientuser", "is_active": True},
            {"_id": ObjectId(U_MGR), "full_name": "Manu Mgr", "email": "mgr@c1.com",
             "company_id": CO, "role": "clientuser", "is_active": True},
        ]),
        "staff": FakeCollection(),
        M.COLL_DEPARTMENTS: FakeCollection([
            {"_id": ObjectId(DEPT), "company_id": CO, "name": "Accounts", "active": True},
            {"_id": ObjectId(DEPT2), "company_id": CO, "name": "Field Ops", "active": True},
        ]),
        M.COLL_DESIGNATIONS: FakeCollection([
            {"_id": ObjectId(DESIG), "company_id": CO, "name": "Analyst", "active": True},
            {"_id": ObjectId(DESIG2), "company_id": CO, "name": "Senior Analyst",
             "active": True},
        ]),
        # The shift the profile names has to EXIST -- validate_master_values checks it,
        # which is the point: a person cannot be assigned a shift nobody configured.
        M.COLL_SHIFTS: FakeCollection([
            {"_id": ObjectId(), "company_id": CO, "code": "GEN", "name": "General",
             "active": True,
             "versions": [{"effective_from": "2026-01-01", "start": "09:30",
                           "end": "18:30", "daily_grace_minutes": 5}]},
        ]),
        "companies": FakeCollection([{"_id": CO, "is_internal": False}]),
    }
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_employee_service as ES
    import app.services.hrms_employee_master_service as EM
    import app.services.hrms_audit_service as AS
    import app.services.hrms_id_service as IS
    import app.services.hrms_masters_service as MS
    import app.services.hrms_shift_service as SH
    for mod in (ES, EM, AS, IS, MS, SH, A):
        mod.get_collection = mongo.get_collection

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": CO, "governance_role": "HR"}

    today = datetime.now(timezone.utc).date()
    later = (today + timedelta(days=30)).isoformat()

    # -- 1 / 2 / 3 -------------------------------------------------------------------
    section("1-3. HR creates the record; duplicate check and numbering run first")

    await EM.save_master_lists(HR, CO, {"lists": {
        "locations": ["Pune", "Mumbai"], "grades": ["G3", "G4"], "levels": ["L2", "L3"],
        "legal_entities": ["Sparsh India Pvt Ltd"], "employee_categories": ["Staff"],
        "payroll_groups": ["Monthly"], "salary_templates": ["STD"],
        "attendance_policy_groups": ["General"], "holiday_calendars": ["India-2026"],
    }})

    asha = await ES.create_profile(HR, CO, {
        "user_id": U_A, "joined_on": "2026-01-01",
        # 4. company / department / designation / grade / level / location / manager
        "legal_entity": "Sparsh India Pvt Ltd", "department_id": DEPT,
        "designation_id": DESIG, "grade": "G3", "level": "L2",
        "work_location": "Pune", "reporting_manager_id": U_MGR,
        "employee_category": "Staff",
        # 5. bank / statutory / contact
        "pan": "abcde1234f", "aadhaar": "123456789012", "uan": "100200300400",
        "bank_name": "HDFC", "bank_account": "123456789012", "bank_ifsc": "hdfc0001234",
        "personal_email": "asha@example.com", "personal_mobile": "9876543210",
        # 6. payroll group / salary template
        "payroll_group": "Monthly", "salary_template": "STD",
        # 7. shift / attendance policy / weekly off / holiday group
        "shift_code": "GEN", "attendance_policy_group": "General",
        "weekly_off_pattern": ["Sunday"], "holiday_calendar": "India-2026",
    })
    check("1. the record is committed", asha["employee_code"] is not None, asha)
    check("3. the employee number is minted to the configured format",
          asha["employee_code"].startswith("EMP-"), asha["employee_code"])
    check("identity is NOT copied onto the profile -- it is composed",
          asha["name"] == "Asha A")
    check("5. a lowercase PAN / IFSC is normalised, not refused",
          asha.get("pan") == "ABCDE1234F" and asha.get("bank_ifsc") == "HDFC0001234", asha)

    # 2. duplicate / identity validation BEFORE a second record is committed.
    for field, value, label in (("pan", "ABCDE1234F", "PAN"),
                                ("aadhaar", "123456789012", "Aadhaar"),
                                ("uan", "100200300400", "UAN"),
                                ("bank_account", "123456789012", "Bank account"),
                                ("personal_email", "ASHA@example.com", "Personal email"),
                                ("personal_mobile", "9876543210", "Personal mobile")):
        await expect(f"2. a second employee carrying that {label} is refused",
                     ES.create_profile(HR, CO, {"user_id": U_B, field: value}), 409,
                     "already recorded")
    check("2. ...and nothing was committed for the refused record",
          len(store[M.COLL_EMPLOYEE_PROFILES].docs) == 1,
          len(store[M.COLL_EMPLOYEE_PROFILES].docs))

    await expect("4. a department from outside the company is refused",
                 ES.create_profile(HR, CO,
                                   {"user_id": U_B, "department_id": str(ObjectId())}),
                 422, "does not exist")
    await expect("4. a location not on the company's list is refused",
                 ES.create_profile(HR, CO, {"user_id": U_B, "work_location": "Delhi"}),
                 422, "not in the company")
    await expect("5. a malformed Aadhaar is refused",
                 ES.create_profile(HR, CO, {"user_id": U_B, "aadhaar": "123"}),
                 422, "aadhaar")

    # -- 4-7 -------------------------------------------------------------------------
    section("4-7. every assignment the process names is stored")

    saved = store[M.COLL_EMPLOYEE_PROFILES].docs[0]
    for field, label in (("legal_entity", "company / legal entity"),
                         ("department_id", "department"),
                         ("designation_id", "designation"),
                         ("grade", "grade"), ("level", "level"),
                         ("work_location", "location"),
                         ("payroll_group", "payroll group"),
                         ("salary_template", "salary structure template"),
                         ("shift_code", "shift"),
                         ("attendance_policy_group", "attendance policy group"),
                         ("weekly_off_pattern", "weekly off"),
                         ("holiday_calendar", "holiday group")):
        check(f"{label} is stored", saved.get(field) not in (None, "", []), field)
    check("4. the reporting manager is written to the USER doc, which owns the line",
          store["learners"].docs[1].get("reporting_manager") == U_MGR)

    # -- 9 ---------------------------------------------------------------------------
    section("9. activated for Attendance and Payroll")

    from app.services.hrms_attendance_service import assert_attendance_active
    check("unset means active -- nobody is silently excluded",
          assert_attendance_active(saved) is None)
    off = await ES.update_profile(HR, U_A, {"attendance_active": False}, CO)
    check("HR can switch attendance off", off.get("attendance_active") is False, off)
    try:
        assert_attendance_active(store[M.COLL_EMPLOYEE_PROFILES].docs[0])
        check("9. ...and attendance capture then refuses the person", False)
    except Exception as e:
        check("9. ...and attendance capture then refuses the person",
              getattr(e, "status_code", None) == 409, e)
    await ES.update_profile(HR, U_A, {"attendance_active": True}, CO)

    # -- 10 --------------------------------------------------------------------------
    section("10. a future change is scheduled; the old value survives")

    await ES.update_profile(HR, U_A, {
        "department_id": DEPT2, "designation_id": DESIG2, "grade": "G4",
        "work_location": "Mumbai", "base_salary": 90000,
        "effective_from": later, "change_reason": "Promotion"}, CO)
    live = store[M.COLL_EMPLOYEE_PROFILES].docs[0]
    check("10. the live record is UNCHANGED until the date arrives",
          live["department_id"] == DEPT and live["grade"] == "G3"
          and live["work_location"] == "Pune", live)

    sched = await EM.scheduled_for(CO, asha["employee_code"])
    check("10. every changed field is scheduled",
          {r["field"] for r in sched} == {"department_id", "designation_id", "grade",
                                          "work_location", "base_salary"}, sched)
    check("10. ...all from the effective date asked for",
          all(r["effective_from"] == later for r in sched), sched)

    hist = store[M.COLL_EMPLOYEE_HISTORY].docs
    check("10. the reason is kept on the history row",
          any(r.get("reason") == "Promotion" for r in hist))

    for r in hist:                                   # its day arrives
        if r["status"] == M.HISTORY_SCHEDULED:
            r["effective_from"] = today.isoformat()
    applied = await EM.apply_due_changes(CO)
    live = store[M.COLL_EMPLOYEE_PROFILES].docs[0]
    check("10. on the day, all five are applied", applied == 5, applied)
    check("10. ...and the record now reads the new values",
          live["department_id"] == DEPT2 and live["grade"] == "G4"
          and live["work_location"] == "Mumbai" and live["base_salary"] == 90000, live)
    moved = [r for r in hist if r["field"] == "work_location" and r["status"] == "Applied"]
    check("10. HISTORY PRESERVED: the row still says Pune -> Mumbai",
          bool(moved) and moved[-1]["old_value"] == "Pune"
          and moved[-1]["new_value"] == "Mumbai", moved)
    check("10. the creation rows are still there, so the timeline starts at joining",
          any(r.get("reason") == "Employee created" for r in hist))

    await ES.update_profile(HR, U_A, {"grade": "G3", "change_reason": "Correction"}, CO)
    check("10. a same-day change applies immediately",
          store[M.COLL_EMPLOYEE_PROFILES].docs[0]["grade"] == "G3")

    await ES.update_profile(HR, U_A, {"work_location": "Pune", "effective_from": later}, CO)
    pend = await EM.scheduled_for(CO, asha["employee_code"])
    await EM.cancel_scheduled(HR, CO, pend[0]["id"])
    check("10. a scheduled change can be cancelled before its date",
          not await EM.scheduled_for(CO, asha["employee_code"]))
    await expect("10. ...but an APPLIED one is history and cannot be",
                 EM.cancel_scheduled(HR, CO, str(moved[-1]["_id"])), 409, "history")

    print("\n" + "=" * 62)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 62)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
