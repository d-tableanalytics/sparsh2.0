"""Whose payslip does GET /payslips/{period} return?

"My Payslip" sends no employee_code. For an EMPLOYEE that always meant their own. For HR it
used to be a 422 "employee_code is required." — printed verbatim on the My Payslip tab, which
HR sees too. Now naming nobody means "mine" for every role, and a caller with no employee
profile is told so in words.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_payslip_whose   (from backend/)
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
    from fastapi import HTTPException

    from app.models import hrms as M
    import app.services.hrms_payslip_service as PS

    profiles = FakeCollection([
        {"company_id": CO, "user_id": "u-emp", "employee_code": "EMP-001"},
        {"company_id": CO, "user_id": "u-hr-emp", "employee_code": "EMP-HR"},
    ])
    PS.get_collection = lambda name: profiles if name == M.COLL_EMPLOYEE_PROFILES else FakeCollection()

    profiles.docs += [{"company_id": CO, "user_id": "u-mgr", "employee_code": "EMP-MGR"}]
    roles = {"u-emp": M.HrmsRole.EMPLOYEE, "u-hr-emp": M.HrmsRole.HR, "u-hr": M.HrmsRole.HR,
             "u-mgr": M.HrmsRole.MANAGER, "u-fin": M.HrmsRole.FINANCE,
             "u-support": M.HrmsRole.INTERNAL}
    PS.hrms_role = lambda actor: roles[actor["_id"]]
    import app.utils.hrms_access as _HA
    _HA.hrms_role = lambda actor: roles[actor["_id"]]

    async def resolve(uid, requested=None):
        try:
            return await PS._resolve_employee_code({"_id": uid}, CO, requested)
        except HTTPException as e:
            return e

    print("\n-- An employee only ever sees their own --")
    check("no code -> their own", await resolve("u-emp") == "EMP-001")
    check("someone else's code is ignored -> still their own",
          await resolve("u-emp", "EMP-HR") == "EMP-001")

    print("\n-- Every staff member holds payslip access for THEMSELVES --")
    check("a manager asking for someone else's payslip gets their OWN",
          await resolve("u-mgr", "EMP-001") == "EMP-MGR")
    r = await resolve("u-support", "EMP-001")
    check("a support user with no profile gets nobody's (404), not the one they named",
          isinstance(r, HTTPException) and r.status_code == 404)
    check("Finance (who approves pay) may name an employee",
          await resolve("u-fin", "EMP-001") == "EMP-001")

    print("\n-- HR --")
    check("naming an employee -> that employee", await resolve("u-hr", "EMP-001") == "EMP-001")
    check("naming nobody, with a profile -> their own (the My Payslip tab)",
          await resolve("u-hr-emp") == "EMP-HR")
    r = await resolve("u-hr")
    check("naming nobody, no profile -> 404, not 422",
          isinstance(r, HTTPException) and r.status_code == 404)
    check("and the message says why in words, not a field name",
          isinstance(r, HTTPException) and "no employee profile" in r.detail
          and "employee_code" not in r.detail)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
