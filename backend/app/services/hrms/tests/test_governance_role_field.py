"""The governance role survives account CREATION, and resolves the way the ERP expects.

`governance_role` is platform-wide, not an HRMS field: auth_controller.client_rank ranks
MD > HR > HOD > Implementor to decide who may assign work to whom, Task & Delegation gives a
company MD authority over their own company's tasks, TPMS keys its governance departments
and escalations off it, Leadership Score gates on HR/MD, Forms targets an audience by it,
and HRMS resolves it onto the hiring ladder.

It was readable on UserResponse and writable only from the HRMS Role & Access screen;
UserCreate did not declare it, so a value sent at registration was silently dropped by
pydantic and the new HOD was quietly an ordinary user. This asserts the field is accepted,
normalised, validated, and understood afterwards.

Lives beside the HRMS suites because the vocabulary it validates against is declared in
models/hrms.py, and that agreement is the thing most likely to drift.

House convention: self-contained, no pytest, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_governance_role_field   (from backend/)
"""
from __future__ import annotations

import sys

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


from app.models.user import GOVERNANCE_ROLES, UserBase, UserCreate  # noqa: E402
from app.models import hrms as M  # noqa: E402
from app.utils import hrms_access as HA  # noqa: E402


def staff(**over) -> dict:
    """A Sparsh staff account, as get_user_from_token would hand it over."""
    return {"_source_collection": "staff", "role": "coach", **over}


def main() -> int:
    section("The vocabulary is the one HRMS enforces")
    check("models/user.GOVERNANCE_ROLES == hrms.ASSIGNABLE_GOVERNANCE_ROLES",
          GOVERNANCE_ROLES == M.ASSIGNABLE_GOVERNANCE_ROLES)
    check("every value maps onto an HRMS role",
          all(v in M.GOVERNANCE_TO_HRMS for v in GOVERNANCE_ROLES))

    section("It is accepted when the account is CREATED, not only afterwards")
    check("declared on the base, so UserCreate carries it",
          "governance_role" in UserBase.model_fields)
    made = UserCreate(email="new.hod@sparshmagic.com", password="x", first_name="New",
                      governance_role="HOD")
    check("a registration keeps it", made.governance_role == "HOD")
    check("it survives model_dump, which is what register() inserts",
          made.model_dump().get("governance_role") == "HOD")

    section("Normalised, so 'hod' and 'HOD' are the same rung")
    check("lower case is raised", UserCreate(
        email="a@b.com", password="x", governance_role="hod").governance_role == "HOD")
    check("padding is trimmed", UserCreate(
        email="a@b.com", password="x", governance_role="  hr  ").governance_role == "HR")
    check("blank means unset", UserCreate(
        email="a@b.com", password="x", governance_role="").governance_role is None)
    check("absent stays absent", UserCreate(
        email="a@b.com", password="x").governance_role is None)

    section("A value nobody understands is refused, not stored")
    for bad in ("CHIEF", "Head of Dept", "manager", "HOD "[:3] + "X"):
        try:
            UserCreate(email="a@b.com", password="x", governance_role=bad)
            check(f"{bad!r} refused", False)
        except Exception as e:                       # pydantic ValidationError
            check(f"{bad!r} refused", "governance_role must be one of" in str(e))

    section("What the value BUYS, once it is on the account")
    check("HR resolves to the HR rung",
          HA.hrms_role(staff(governance_role="HR")) == M.HrmsRole.HR)
    check("HOD resolves to the hiring manager rung",
          HA.hrms_role(staff(governance_role="HOD")) == M.HrmsRole.MANAGER)
    check("FINANCE resolves to the budget rung",
          HA.hrms_role(staff(governance_role="FINANCE")) == M.HrmsRole.FINANCE)
    check("MD resolves to the MD rung",
          HA.hrms_role(staff(governance_role="MD")) == M.HrmsRole.MD)
    check("no rung means the ordinary internal role",
          HA.hrms_role(staff()) == M.HrmsRole.INTERNAL)

    section("It is a governance rung, NOT a platform role")
    # The distinction this whole change rests on: `role` is what the account may reach,
    # `governance_role` is what the person is. Naming somebody HOD must not touch the first.
    hod = staff(governance_role="HOD")
    check("the platform role is untouched", hod["role"] == "coach")
    check("HOD is not a platform role in its own right",
          "hod" not in M.INTERNAL_STAFF_ROLES and "hod" not in M.INTERNAL_OWNER_ROLES)
    check("neither is HR",
          "hr" not in M.INTERNAL_STAFF_ROLES and "hr" not in M.INTERNAL_OWNER_ROLES)
    check("a HOD still counts as internal staff",
          HA.is_internal_user(hod) is True)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
