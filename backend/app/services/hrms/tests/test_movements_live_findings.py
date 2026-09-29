"""Movements & Discipline page — defects found by the live test, pinned.

Movements: a Compensation Change never reached payroll; the proposer could approve their own
proposal (and anyone could propose their own raise); duplicate and no-change movements were
accepted; a manager could act on, and read, people outside their team.
Discipline: the accused could read and run their own case. Absconding: a future flag date.
Retirement: someone already past retirement age never appeared.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_movements_live_findings   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import date

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


from app.services.hrms.tests.test_phase2_employee import (  # noqa: E402
    FakeCollection as _BaseFake, _matches,
)


class FakeCollection(_BaseFake):
    async def find_one(self, query, projection=None, sort=None):
        hits = [d for d in self.docs if _matches(d, query)]
        for key, direction in reversed(sort or []):
            hits.sort(key=lambda d: d.get(key) or "", reverse=direction < 0)
        return hits[0] if hits else None


CO = "C1"


async def main() -> int:
    from bson import ObjectId
    from fastapi import HTTPException

    from app.models import hrms as M
    import app.db.mongodb as mongo

    today = date.today().isoformat()
    store = {
        M.COLL_EMPLOYEE_PROFILES: FakeCollection([
            {"company_id": CO, "employee_code": c, "user_id": str(ObjectId()), "employment_status": "Active", **extra}
            for c, extra in (("E-HR", {}), ("E-TEAM", {"date_of_birth": "1966-12-15"}),
                             ("E-OUT", {"date_of_birth": "1965-06-01"}))]),
        M.COLL_SALARY_COMPONENTS: FakeCollection([
            {"company_id": CO, "code": "BASIC", "name": "Basic", "component_type": "Earning", "active": True},
            {"company_id": CO, "code": "HRA", "name": "HRA", "component_type": "Earning", "active": True},
            {"company_id": CO, "code": "PT", "name": "PT", "component_type": "Deduction", "active": True}]),
        M.COLL_SALARY_STRUCTURES: FakeCollection([
            {"company_id": CO, "employee_code": "E-TEAM", "effective_from": "2025-01-01",
             "components": [{"code": "BASIC", "amount": 20000}, {"code": "HRA", "amount": 8000}, {"code": "PT", "amount": 200}]}]),
        "staff": FakeCollection(), "learners": FakeCollection(),
    }
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_movement_service as MV
    import app.services.hrms_absconding_service as AB
    import app.services.hrms_retirement_service as RT
    import app.services.hrms_discipline_service as DS
    import app.services.hrms_people_scope as SC
    import app.services.hrms_payroll_service as PR
    import app.services.hrms_audit_service as AU
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_access as HA
    for mod in (MV, AB, RT, DS, SC, PR, AU, IDS, HA):
        mod.get_collection = mongo.get_collection

    roles = {"hr": M.HrmsRole.HR, "md": M.HrmsRole.MD, "mgr": M.HrmsRole.MANAGER}
    HA.hrms_role = SC.hrms_role = lambda a: roles[a["_id"]]
    own = {"hr": "E-HR", "md": None, "mgr": None}

    async def own_code(actor, company_id):
        return own[actor["_id"]]

    async def team(actor, company_id):
        return ["E-TEAM"] if actor["_id"] == "mgr" else []
    SC.own_code, SC.team_codes = own_code, team
    HR, MDU, MGR = {"_id": "hr"}, {"_id": "md"}, {"_id": "mgr"}

    async def attempt(coro):
        try:
            return await coro
        except HTTPException as e:
            return e

    def is_err(r, code):
        return isinstance(r, HTTPException) and r.status_code == code

    print("\n-- Movements --")
    comp = await MV.initiate_movement(HR, CO, {"employee_code": "E-TEAM", "movement_type": "Compensation Change",
                                               "to_value": "35000", "effective_date": today})
    check("the before-value is what payroll pays (28000)", comp["current_value"] == "28000")
    check("the proposer cannot approve it", is_err(await attempt(MV.act_on_movement(HR, CO, comp["move_no"], {"approved": True})), 403))
    check("a duplicate open Compensation Change is refused",
          is_err(await attempt(MV.initiate_movement(HR, CO, {"employee_code": "E-TEAM", "movement_type": "Compensation Change",
                                                             "to_value": "36000", "effective_date": today})), 409))
    applied = await MV.act_on_movement(MDU, CO, comp["move_no"], {"approved": True})
    check("MD approves -> Applied", applied["status"] == "Applied")
    cur = await PR.get_current_structure(CO, "E-TEAM", today)
    lines = {c["code"]: c["amount"] for c in cur["components"]}
    check("payroll now pays 35000: BASIC 25000 + HRA 10000, PT 200 kept", lines == {"BASIC": 25000, "HRA": 10000, "PT": 200})
    check("a change to what they already have is refused",
          is_err(await attempt(MV.initiate_movement(HR, CO, {"employee_code": "E-TEAM", "movement_type": "Compensation Change",
                                                             "to_value": "35000", "effective_date": today})), 422))
    check("nobody proposes a movement for themselves",
          is_err(await attempt(MV.initiate_movement(HR, CO, {"employee_code": "E-HR", "movement_type": "Location Change",
                                                             "to_value": "Pune", "effective_date": today})), 403))
    check("a manager cannot propose outside their team",
          is_err(await attempt(MV.initiate_movement(MGR, CO, {"employee_code": "E-OUT", "movement_type": "Location Change",
                                                              "to_value": "Pune", "effective_date": today})), 403))
    await MV.initiate_movement(HR, CO, {"employee_code": "E-OUT", "movement_type": "Location Change",
                                        "to_value": "Delhi", "effective_date": today})
    seen = {m["employee_code"] for m in await MV.list_movements(MGR, CO)}
    check("a manager's list holds only their team", seen == {"E-TEAM"})

    print("\n-- Discipline --")
    r = await attempt(DS.create_case(HR, CO, {"category": "Misconduct", "description": "x",
                                              "persons_involved": [{"employee_code": "E-HR", "role": "Respondent"}]}))
    check("nobody files a case they are part of", is_err(r, 403))
    case = await DS.create_case(MDU, CO, {"category": "Misconduct", "description": "x",
                                          "persons_involved": [{"employee_code": "E-HR", "role": "Respondent"}]})
    check("the accused cannot open their own case", is_err(await attempt(DS.get_case(HR, CO, case["case_no"])), 403))
    check("...nor see it in their list", case["case_no"] not in {c["case_no"] for c in await DS.list_cases(HR, CO)})

    print("\n-- Absconding --")
    check("a future flag date is refused",
          is_err(await attempt(AB.flag_case(MGR, CO, {"employee_code": "E-TEAM", "flagged_date": "2999-01-01"})), 422))
    check("a manager cannot flag outside their team",
          is_err(await attempt(AB.flag_case(MGR, CO, {"employee_code": "E-OUT"})), 403))

    print("\n-- Retirement --")
    rows = {r["employee_code"]: r for r in await RT.list_upcoming_retirements(HR, CO)}
    check("already past retirement age and still active -> listed as overdue", rows.get("E-OUT", {}).get("overdue") is True)
    mgr_rows = {r["employee_code"] for r in await RT.list_upcoming_retirements(MGR, CO)}
    check("a manager sees only their team's alerts", "E-OUT" not in mgr_rows)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
