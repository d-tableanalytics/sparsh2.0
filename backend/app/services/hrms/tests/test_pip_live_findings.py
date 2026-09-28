"""PIP defects found by the live test (PIP-2026-001..004), pinned.

  - "Extended" CLOSED the plan (and needed no new date) — it could not actually continue.
  - An end date before the start, and a second open plan for the same person, were accepted.
  - A plan the employee never acknowledged could be closed as "Separation Recommended".
  - The person on a plan could only acknowledge it with the EMPLOYEE/MD role — an HOD placed
    on one could not, so it sat in Draft forever.
  - A manager could read every PIP in the company; plans carried no employee name.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_pip_live_findings   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

CO = "C1"


async def main() -> int:
    from bson import ObjectId
    from fastapi import HTTPException

    from app.models import hrms as M
    import app.db.mongodb as mongo

    uid = {k: ObjectId() for k in ("hr", "mgr", "hod", "other")}
    store = {
        M.COLL_EMPLOYEE_PROFILES: FakeCollection([
            {"company_id": CO, "employee_code": "E-HR", "user_id": str(uid["hr"])},
            {"company_id": CO, "employee_code": "E-HOD", "user_id": str(uid["hod"])},
            {"company_id": CO, "employee_code": "E-OTHER", "user_id": str(uid["other"])},
        ]),
        "staff": FakeCollection([{"_id": uid["hod"], "full_name": "Dummy HOD"},
                                 {"_id": uid["other"], "full_name": "Someone Else"}]),
        "learners": FakeCollection(),
    }
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_pip_service as PIP
    import app.services.hrms_payroll_service as PR
    import app.services.hrms_audit_service as AU
    import app.services.hrms_id_service as IDS
    import app.services.hrms_leave_service as LV
    for mod in (PIP, PR, AU, IDS, LV):
        mod.get_collection = mongo.get_collection

    roles = {str(uid["hr"]): M.HrmsRole.HR, str(uid["mgr"]): M.HrmsRole.MANAGER,
             str(uid["hod"]): M.HrmsRole.MANAGER, str(uid["other"]): M.HrmsRole.INTERNAL}
    PIP.hrms_role = lambda a: roles[a["_id"]]
    import app.utils.hrms_access as _HA
    _HA.hrms_role = lambda a: roles[a["_id"]]

    async def team(actor, company_id):
        return ["E-HOD"] if actor["_id"] == str(uid["mgr"]) else []
    LV._team_employee_codes = team

    HR, MGR, HOD, OTHER = ({"_id": str(uid[k])} for k in ("hr", "mgr", "hod", "other"))

    async def attempt(coro):
        try:
            return await coro
        except HTTPException as e:
            return e

    def plan(code, start="2026-10-01", end="2026-12-31", actor=HR):
        return attempt(PIP.initiate_pip(actor, CO, {"employee_code": code, "gap_statement": "gap",
                                                    "start_date": start, "target_end_date": end}))

    print("\n-- Creating a plan --")
    r = await plan("E-HOD", "2026-12-31", "2026-10-01")
    check("end before start -> 422", isinstance(r, HTTPException) and r.status_code == 422)
    p = await plan("E-HOD")
    check("a valid plan carries the employee's name", p["employee_name"] == "Dummy HOD")
    r = await plan("E-HOD")
    check("a second open plan for the same person -> 409", isinstance(r, HTTPException) and r.status_code == 409)
    r = await plan("E-HR")
    check("HR cannot put themselves on a PIP -> 403", isinstance(r, HTTPException) and r.status_code == 403)
    r = await plan("E-OTHER", actor=MGR)
    check("a manager cannot start a PIP outside their team -> 403", isinstance(r, HTTPException) and r.status_code == 403)
    other = await plan("E-OTHER")

    print("\n-- Who sees what --")
    seen = {x["pip_no"] for x in await PIP.list_pips(MGR, CO)}
    check("the manager sees their team's plan and not the other one", p["pip_no"] in seen and other["pip_no"] not in seen)
    mine = await PIP.list_pips(OTHER, CO)
    check("an INTERNAL-role subject sees exactly their own", [x["pip_no"] for x in mine] == [other["pip_no"]] and mine[0]["is_mine"])

    print("\n-- Acknowledge, review, decide --")
    r = await attempt(PIP.decide_pip(HR, CO, p["pip_no"], {"closure_result": "Separation Recommended"}))
    check("no outcome before the employee acknowledges -> 409", isinstance(r, HTTPException) and r.status_code == 409)
    r = await attempt(PIP.acknowledge_pip(HR, CO, p["pip_no"]))
    check("nobody else can acknowledge it -> 403", isinstance(r, HTTPException) and r.status_code == 403)
    a = await PIP.acknowledge_pip(HOD, CO, p["pip_no"])
    check("the subject acknowledges, whatever their role (a MANAGER here)", a["status"] == "Active")
    r = await attempt(PIP.add_review(HOD, CO, p["pip_no"], {"progress": "self"}))
    check("the subject cannot review their own plan -> 403", isinstance(r, HTTPException) and r.status_code == 403)
    await PIP.add_review(MGR, CO, p["pip_no"], {"progress": "ok"})

    print("\n-- Extended keeps it going --")
    r = await attempt(PIP.decide_pip(HR, CO, p["pip_no"], {"closure_result": "Extended"}))
    check("Extended without a new date -> 422", isinstance(r, HTTPException) and r.status_code == 422)
    e = await PIP.decide_pip(HR, CO, p["pip_no"], {"closure_result": "Extended", "extension_date": "2027-01-31"})
    check("Extended -> still Active, target end moves", e["status"] == "Active" and e["target_end_date"] == "2027-01-31")
    check("...with the extension recorded", len(e["extensions"]) == 1 and e["extensions"][0]["from"] == "2026-12-31")
    rv = await PIP.add_review(MGR, CO, p["pip_no"], {"progress": "after extension"})
    check("reviews continue after an extension", len(rv["reviews"]) == 2)
    c = await PIP.decide_pip(HR, CO, p["pip_no"], {"closure_result": "Successfully Closed"})
    check("a real outcome closes it", c["status"] == "Closed")

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
