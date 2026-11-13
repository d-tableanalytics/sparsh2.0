"""Reporting-hierarchy data scope -- UAT finding "a Manager sees every employee".

A manager must see only their own reporting line (direct reports, or the downline where the
company explicitly approved hierarchy scope); company-wide visibility is for HR / Admin
(and payroll) roles. Verified across the Employee Directory, the single-profile view (by id
and by employee code -- the Employee 360 path), profile-only rows (no login yet), and the
team that leave / attendance manager actions are scoped to. Several managers on different
reporting lines, including two who share a department.

House convention: self-contained, no pytest, fake collections, non-zero exit on failure.

Run:  python -m app.services.hrms.tests.test_reporting_hierarchy_scope   (from backend/)
"""
from __future__ import annotations

import asyncio
import sys

from app.services.hrms.tests.test_phase2_employee import FakeCollection, check, section, results


async def expect_404(label, coro):
    from fastapi import HTTPException
    try:
        await coro
        check(f"{label} -> 404", False)
    except HTTPException as e:
        check(f"{label} -> 404", e.status_code == 404)


async def main() -> None:
    from bson import ObjectId
    import app.db.mongodb as mongo
    from app.models import hrms as M

    C = str(ObjectId())
    ids = {k: str(ObjectId()) for k in
           ("HR", "FIN", "M1", "M2", "M3", "E1", "E2", "E3", "E4", "E5")}
    DEPT = str(ObjectId())

    def person(key, gov=None, manager=None):
        d = {"_id": ObjectId(ids[key]), "full_name": f"{key} person", "email": f"{key.lower()}@c.com",
             "company_id": C, "role": "clientuser", "is_active": True}
        if gov:
            d["governance_role"] = gov
        if manager:
            d["reporting_manager"] = ids[manager]
        return d

    # Org chart:   M1 -> E1, E2, M2 ;  M2 -> E3 ;  M3 -> E4 ;  E5 reports to nobody.
    # M1 and M3 share a department (the old rule leaked M3's team to M1 through it).
    learners = FakeCollection([
        person("HR", "HR"), person("FIN", "FINANCE"),
        person("M1", "HOD"), person("M2", "HOD", "M1"), person("M3", "HOD"),
        person("E1", manager="M1"), person("E2", manager="M1"), person("E3", manager="M2"),
        person("E4", manager="M3"), person("E5"),
    ])
    profiles = FakeCollection(
        [{"company_id": C, "user_id": ids[k], "employee_code": f"EMP-{k}", "department_id": DEPT}
         for k in ids]
        # Joiners from onboarding: a profile, no login yet.
        + [{"company_id": C, "employee_code": "EMP-NEW1", "reporting_manager_id": ids["M1"],
            "department_id": DEPT, "first_name": "New", "last_name": "One"},
           {"company_id": C, "employee_code": "EMP-NEW3", "reporting_manager_id": ids["M3"],
            "department_id": DEPT, "first_name": "New", "last_name": "Three"}])
    companies = FakeCollection([{"_id": ObjectId(C), "name": "UAT Co", "hrms_enabled": True}])
    store = {"learners": learners, "staff": FakeCollection(), "companies": companies,
             M.COLL_EMPLOYEE_PROFILES: profiles,
             M.COLL_DEPARTMENTS: FakeCollection([{"_id": ObjectId(DEPT), "company_id": C, "name": "Ops"}])}
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_employee_service as ES
    import app.services.hrms_reporting_scope as RS
    import app.services.hrms_leave_service as LS
    import app.services.hrms_attendance_service as ATT
    import app.services.hrms_employee_master_service as MS
    import app.utils.hrms_access as A
    for mod in (ES, RS, LS, ATT, MS, A):
        mod.get_collection = mongo.get_collection

    def actor(key, gov):
        return {"_id": ids[key], "role": "clientuser", "_source_collection": "learners",
                "company_id": C, "governance_role": gov}
    HR, FIN = actor("HR", "HR"), actor("FIN", "FINANCE")
    M1, M2, M3 = actor("M1", "HOD"), actor("M2", "HOD"), actor("M3", "HOD")

    async def directory(a):
        rows = (await ES.list_employees(a, C))["employees"]
        return {r.get("user_id") or r.get("employee_code") for r in rows if r.get("user_id") or r.get("employee_code")}

    def names(*keys):
        return {ids[k] for k in keys}

    section("Employee Directory -- default scope: direct reports only")
    d1 = await directory(M1)
    check("M1 sees self + direct reports E1, E2, M2", names("M1", "E1", "E2", "M2") <= d1)
    check("M1 sees their own not-yet-linked joiner", "EMP-NEW1" in d1)
    check("M1 does NOT see E3 (indirect report -- hierarchy not approved)", ids["E3"] not in d1)
    check("M1 does NOT see department peer M3 or M3's team E4",
          not (names("M3", "E4") & d1))
    check("M1 does NOT see E5, HR, Finance", not (names("E5", "HR", "FIN") & d1))
    check("M1 does NOT see M3's unlinked joiner", "EMP-NEW3" not in d1)
    d3 = await directory(M3)
    check("M3 sees only self + E4 (+ own joiner)", d3 == names("M3", "E4") | {"EMP-NEW3"})
    d2 = await directory(M2)
    check("M2 sees only self + E3", d2 == names("M2", "E3"))

    section("Company-wide roles see everyone")
    everyone = set(ids.values()) | {"EMP-NEW1", "EMP-NEW3"}
    check("HR sees the whole company", await directory(HR) == everyone)
    check("Finance (payroll operator) sees the whole company", await directory(FIN) == everyone)

    section("Employee profile / 360 by user id")
    check("M1 opens direct report E1", (await ES.get_employee(M1, ids["E1"], company_id=C))["user_id"] == ids["E1"])
    await expect_404("M1 opens M3's report E4", ES.get_employee(M1, ids["E4"], company_id=C))
    await expect_404("M1 opens indirect report E3 (direct scope)", ES.get_employee(M1, ids["E3"], company_id=C))
    await expect_404("M3 opens M1's report E1", ES.get_employee(M3, ids["E1"], company_id=C))
    check("HR opens anyone (E4)", (await ES.get_employee(HR, ids["E4"], company_id=C))["user_id"] == ids["E4"])

    section("Employee 360 by employee code (previously unscoped)")
    check("M1 opens EMP-E1 by code", (await ES.get_employee_by_code(M1, C, "EMP-E1")) is not None)
    check("M1 opens own joiner EMP-NEW1 by code", (await ES.get_employee_by_code(M1, C, "EMP-NEW1")) is not None)
    await expect_404("M1 opens EMP-E4 by code", ES.get_employee_by_code(M1, C, "EMP-E4"))
    await expect_404("M1 opens EMP-E5 by code", ES.get_employee_by_code(M1, C, "EMP-E5"))
    await expect_404("M1 opens M3's joiner EMP-NEW3 by code", ES.get_employee_by_code(M1, C, "EMP-NEW3"))
    check("HR opens EMP-E4 by code", (await ES.get_employee_by_code(HR, C, "EMP-E4")) is not None)

    section("Manager actions (leave / attendance) use the same team")
    lt = set(await LS._team_employee_codes(M1, C))
    check("leave team of M1 = E1, E2, M2", lt == {"EMP-E1", "EMP-E2", "EMP-M2"})
    at = set(await ATT._team_employee_codes(M1, C))
    check("attendance team of M1 = E1, E2, M2", at == {"EMP-E1", "EMP-E2", "EMP-M2"})
    check("leave team of M3 = E4 only", set(await LS._team_employee_codes(M3, C)) == {"EMP-E4"})

    section("Approved hierarchy scope (company opt-in)")
    companies.docs[0]["hrms_manager_scope"] = "hierarchy"
    d1h = await directory(M1)
    check("M1 now also sees indirect report E3", ids["E3"] in d1h)
    check("...but still not M3's line or E5", not (names("M3", "E4", "E5") & d1h))
    check("M1 opens E3 under hierarchy scope",
          (await ES.get_employee(M1, ids["E3"], company_id=C))["user_id"] == ids["E3"])
    check("leave team of M1 includes E3", "EMP-E3" in set(await LS._team_employee_codes(M1, C)))
    check("M2 is unaffected upward (does not see M1)", ids["M1"] not in await directory(M2))

    passed = sum(results)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
