"""Dynamic Roles & Permissions -- a company's rules decide who may do each HRMS action.

Run:  python -m app.services.hrms.tests.test_dynamic_permissions   (from backend/)
"""
RESULTS = []


def check(label: str, ok: bool) -> None:
    RESULTS.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")


def section(title: str) -> None:
    print(f"\n-- {title} --")


def main() -> None:
    from bson import ObjectId
    from fastapi import HTTPException

    from app.models.hrms import Cap, HrmsRole
    from app.utils import hrms_permission_policy as policy
    from app.utils.hrms_access import can, hrms_role
    from app.services import hrms_permission_service as perms

    COMPANY = "C-INTERNAL"
    policy._internal.update({"id": COMPANY, "at": 10 ** 12})    # Sparsh staff -> this company

    def staff(gov=None, role="staff"):
        u = {"_id": str(ObjectId()), "role": role, "_source_collection": "staff",
             "full_name": gov or role, "email": f"{gov or role}@x.com"}
        if gov:
            u["governance_role"] = gov
        return u

    HR, HOD, MD, FIN, EMP = staff("HR"), staff("HOD"), staff("MD"), staff("FINANCE"), staff()
    SUPER = staff(role="superadmin")
    check("the test users resolve to the expected roles",
          [hrms_role(u) for u in (HR, HOD, MD, FIN, EMP, SUPER)]
          == [HrmsRole.HR, HrmsRole.MANAGER, HrmsRole.MD, HrmsRole.FINANCE, HrmsRole.EMPLOYEE,
              HrmsRole.ADMIN])

    section("No rules: the defaults apply unchanged")
    policy._set_cache_for_tests(COMPANY, {})
    check("HR verifies requisitions by default", can(HR, Cap.REQUISITION_REVIEW_HR))
    check("an employee does not", not can(EMP, Cap.REQUISITION_REVIEW_HR))
    check("the defaults the page shows match the code",
          perms.default_roles(Cap.REQUISITION_REVIEW_HR) == ["hr"] or "hr" in perms.default_roles(Cap.REQUISITION_REVIEW_HR))

    section("A rule chooses the roles for one action")
    policy._set_cache_for_tests(COMPANY, {
        "requisition.create": {"cap": "requisition.create", "roles": ["manager"]}})
    check("raising a requisition: HOD keeps it", can(HOD, Cap.REQUISITION_CREATE))
    check("...an employee loses it", not can(EMP, Cap.REQUISITION_CREATE))
    check("...HR loses it", not can(HR, Cap.REQUISITION_CREATE))
    check("other actions are untouched", can(HR, Cap.REQUISITION_REVIEW_HR))
    check("the superadmin always keeps everything", can(SUPER, Cap.REQUISITION_CREATE))

    section("People: always allowed / blocked (a block wins)")
    policy._set_cache_for_tests(COMPANY, {
        "requisition.review_hr": {"cap": "requisition.review_hr", "roles": ["hr"],
                                  "allow_users": [EMP["_id"]], "deny_users": [HR["_id"]]}})
    check("a named employee may now verify requisitions", can(EMP, Cap.REQUISITION_REVIEW_HR))
    check("a blocked HR user may not, though HR is allowed", not can(HR, Cap.REQUISITION_REVIEW_HR))
    other_hr = staff("HR")
    check("another HR user still may", can(other_hr, Cap.REQUISITION_REVIEW_HR))

    section("An explicit rule beats a built-in default")
    policy._set_cache_for_tests(COMPANY, {
        "payroll.approve": {"cap": "payroll.approve", "roles": ["finance", "md"]}})
    check("the MD (review-only by default) can approve payroll once the rule says so",
          can(MD, Cap.PAYROLL_APPROVE))
    check("Finance still can", can(FIN, Cap.PAYROLL_APPROVE))

    section("What stays fixed")
    policy._set_cache_for_tests(COMPANY, {
        "permissions.manage": {"cap": "permissions.manage", "roles": []},
        "module.access": {"cap": "module.access", "roles": []}})
    check("nobody can remove the right to manage permissions (MD keeps it)",
          can(MD, Cap.PERMISSIONS_MANAGE))
    check("nobody can remove basic module entry", can(EMP, Cap.MODULE_ACCESS))
    for value, why in (("permissions.manage", "managing permissions"),
                       ("client_offer.release", "a client-hiring action")):
        try:
            perms._cap(value)
            check(f"{why} is refused as configurable", False)
        except HTTPException as e:
            check(f"{why} is refused as configurable -> {e.status_code}", e.status_code == 422)
    try:
        perms._cap("no.such_action")
        check("an unknown action is refused", False)
    except HTTPException as e:
        check("an unknown action is refused -> 404", e.status_code == 404)

    section("The catalogue")
    listed = {v for _m, steps in perms.CATALOGUE for _s, acts in steps for v, _l in acts}
    check("every configurable action appears in the catalogue",
          all(c.value in listed for c in Cap if policy.is_editable(c)))
    check("the process starts with raising a manpower requisition",
          perms.CATALOGUE[0][1][0][1][0] == ("requisition.create", "Raise a manpower requisition"))

    policy._set_cache_for_tests(COMPANY, {})
    passed = sum(RESULTS)
    print(f"\n=== {passed}/{len(RESULTS)} checks passed ===")
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
