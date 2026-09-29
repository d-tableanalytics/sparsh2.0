"""An employee may request a salary advance for THEMSELVES only.

request_advance and check_eligibility used to take any employee_code from the caller. An
employee could raise an advance in a colleague's name — recovered from the colleague's next
payroll — and read anyone's maximum eligible amount, which is 40% of their gross: their salary.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_advance_self_only   (from backend/)
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
    from fastapi import HTTPException

    from app.models import hrms as M
    import app.db.mongodb as mongo

    store = {
        M.COLL_EMPLOYEE_PROFILES: FakeCollection([
            {"company_id": CO, "user_id": "u-me", "employee_code": "EMP-ME"},
            {"company_id": CO, "user_id": "u-col", "employee_code": "EMP-COLLEAGUE"},
        ]),
        M.COLL_SALARY_COMPONENTS: FakeCollection([
            {"company_id": CO, "code": "BASIC", "name": "Basic", "component_type": "Earning", "active": True}]),
        M.COLL_SALARY_STRUCTURES: FakeCollection([
            {"company_id": CO, "employee_code": c, "effective_from": "2025-01-01",
             "components": [{"code": "BASIC", "amount": amt}]}
            for c, amt in (("EMP-ME", 50000), ("EMP-COLLEAGUE", 90000))]),
        "staff": FakeCollection(), "learners": FakeCollection(),
    }
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_salary_advance_service as SA
    import app.services.hrms_payroll_service as PR
    import app.services.hrms_audit_service as AU
    import app.services.hrms_id_service as IDS
    for mod in (SA, PR, AU, IDS):
        mod.get_collection = mongo.get_collection
    SA._today = lambda: date(2026, 10, 22)          # inside the default 20th-25th window

    roles = {"u-me": M.HrmsRole.EMPLOYEE, "u-noprofile": M.HrmsRole.EMPLOYEE,
             "u-hr": M.HrmsRole.HR, "u-md": M.HrmsRole.MD}
    SA.hrms_role = lambda actor: roles[actor["_id"]]
    import app.utils.hrms_access as _HA
    _HA.hrms_role = lambda actor: roles[actor["_id"]]
    ME, NOPROFILE, HR, MD = ({"_id": k} for k in ("u-me", "u-noprofile", "u-hr", "u-md"))

    async def attempt(coro):
        try:
            return await coro
        except HTTPException as e:
            return e

    print("\n-- An employee cannot act for a colleague --")
    r = await attempt(SA.request_advance(ME, CO, {"employee_code": "EMP-COLLEAGUE", "amount": 1000}))
    check("requesting in a colleague's name -> 403",
          isinstance(r, HTTPException) and r.status_code == 403 and "yourself" in r.detail)
    check("...and nothing was created", not store.get(M.COLL_SALARY_ADVANCES, FakeCollection()).docs)
    r = await attempt(SA.check_eligibility(ME, CO, "EMP-COLLEAGUE"))
    check("reading a colleague's eligibility (= 40% of their salary) -> 403",
          isinstance(r, HTTPException) and r.status_code == 403)

    print("\n-- ...but can act for themselves --")
    mine = await SA.check_eligibility(ME, CO, None)
    check("their own eligibility (the form's 'my eligibility') is 40% of THEIR gross",
          mine["max_eligible_amount"] == 20000 and mine["eligible"])
    adv = await SA.request_advance(ME, CO, {"amount": 5000, "reason": "rent"})
    check("a request with no code is filed against their own profile",
          adv["employee_code"] == "EMP-ME" and adv["status"] == "Pending")
    check("naming themselves explicitly is fine too",
          (await SA.check_eligibility(ME, CO, "EMP-ME"))["quarter"] == "2026-Q4")

    roles["u-fin"] = M.HrmsRole.FINANCE
    r = await attempt(SA.request_advance({"_id": "u-fin"}, CO, {"employee_code": "EMP-COLLEAGUE", "amount": 100}))
    check("Finance (now holding self-service) cannot request in a colleague's name -> 404/403",
          isinstance(r, HTTPException) and r.status_code in (403, 404))

    print("\n-- No profile, no advance --")
    r = await attempt(SA.request_advance(NOPROFILE, CO, {"amount": 100}))
    check("an employee account with no profile -> 404 that says why",
          isinstance(r, HTTPException) and r.status_code == 404 and "no employee profile" in r.detail)

    print("\n-- HR and MD still act on someone's behalf --")
    check("MD may check a named employee",
          (await SA.check_eligibility(MD, CO, "EMP-COLLEAGUE"))["max_eligible_amount"] == 36000)
    r = await attempt(SA.request_advance(HR, CO, {"amount": 100}))
    check("but must NAME the employee (no silent 'self' for them) -> 422",
          isinstance(r, HTTPException) and r.status_code == 422)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
