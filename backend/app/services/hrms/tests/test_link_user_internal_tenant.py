"""`link_user` resolves membership the way every other tenant check does.

Found while linking a login account to an onboarding-created profile at Sparsh Magic.

`link_user` demanded that the account live in `learners` AND carry a matching
`company_id`. That is the rule for a CLIENT company and the wrong one for the INTERNAL
tenant, whose people are `staff` and carry no `company_id` at all -- so at Sparsh Magic
every link was refused with "The account must belong to a user of this company", and an
onboarding-created employee could never be attached to their account. Linking is the step
that turns a profile into somebody the directory, payroll and self-service all recognise,
so the employee stayed permanently half-created.

This is the SAME defect `create_profile` carries a comment about having fixed: "This used
to accept learners only, so Add Employee offered Sparsh's staff and then refused every one
of them -- nobody at Sparsh could get a profile, and so nobody could be paid." The two
checks were written separately and only one of them was corrected. `tenant_member` is the
one answer to "is this person in this company", and both now ask it.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_link_user_internal_tenant   (from backend/)
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


from app.services.hrms.tests.test_payroll_live_findings import FakeCollection  # noqa: E402

INTERNAL = "6ab0d3a3ad0e6d5141a1bb22"      # the tenant whose people are `staff`
CLIENT = "69d782804c39e25a85456dc2"        # an ordinary company, whose people are `learners`
HR = {"_id": "hr-1", "role": "superadmin", "governance_role": "HR", "full_name": "Dummy HR"}


async def main() -> int:
    from bson import ObjectId

    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_audit_service as AU
    import app.services.hrms_employee_master_service as EM
    import app.services.hrms_employee_service as ES
    import app.utils.hrms_access as HA

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AU, EM, ES, HA):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    ES.audit = no_audit

    STAFF_U, LEARNER_U, OUTSIDER_U = ObjectId(), ObjectId(), ObjectId()
    store["companies"] = FakeCollection([
        {"_id": ObjectId(INTERNAL), "name": "Sparsh Magic", "is_internal": True},
        {"_id": ObjectId(CLIENT), "name": "People to Process", "is_internal": False},
    ])
    # The internal tenant's person: `staff`, and NO company_id. That absence is the whole
    # point -- it is what the old check tripped over.
    store["staff"] = FakeCollection([
        {"_id": STAFF_U, "full_name": "Manoj Patel", "email": "manoj@example.com",
         "role": "staff", "company_id": None, "is_active": True},
    ])
    store["learners"] = FakeCollection([
        {"_id": LEARNER_U, "full_name": "Client Person", "email": "cp@example.com",
         "role": "clientuser", "company_id": CLIENT, "is_active": True},
        {"_id": OUTSIDER_U, "full_name": "Other Company", "email": "oc@example.com",
         "role": "clientuser", "company_id": "some-third-company", "is_active": True},
    ])
    store[M.COLL_EMPLOYEE_PROFILES] = FakeCollection([
        {"company_id": INTERNAL, "employee_code": "EMP-INTERNAL", "employment_status": "Active"},
        {"company_id": CLIENT, "employee_code": "EMP-CLIENT", "employment_status": "Active"},
        {"company_id": INTERNAL, "employee_code": "EMP-SPARE", "employment_status": "Active"},
        {"company_id": CLIENT, "employee_code": "EMP-SPARE-CLIENT",
         "employment_status": "Active"},
    ])

    # ── 1. The internal tenant ──────────────────────────────────────────────────────
    section("1. A staff account links to an internal-tenant profile")

    check("the deployment's internal company resolves",
          await HA.internal_company_id() == INTERNAL, await HA.internal_company_id())
    check("...so its identity source is `staff` with no company filter",
          await HA.tenant_identity_source(INTERNAL) == ("staff", {}),
          await HA.tenant_identity_source(INTERNAL))

    linked = await ES.link_user(HR, INTERNAL, "EMP-INTERNAL", str(STAFF_U))
    check("the link is accepted (it was refused 422 before this fix)",
          linked.get("employee_code") == "EMP-INTERNAL", linked.get("employee_code"))
    saved = next(p for p in store[M.COLL_EMPLOYEE_PROFILES].docs
                 if p["employee_code"] == "EMP-INTERNAL")
    check("...and the profile now carries the account's id",
          saved.get("user_id") == str(STAFF_U), saved.get("user_id"))
    check("...with the moment it was linked recorded",
          saved.get("linked_at") is not None)

    # ── 2. A client company still behaves exactly as before ────────────────────────
    section("2. A client company is unchanged")

    await ES.link_user(HR, CLIENT, "EMP-CLIENT", str(LEARNER_U))
    client_saved = next(p for p in store[M.COLL_EMPLOYEE_PROFILES].docs
                        if p["employee_code"] == "EMP-CLIENT")
    check("a learner of that company still links",
          client_saved.get("user_id") == str(LEARNER_U), client_saved.get("user_id"))

    # ── 3. The guard still guards ──────────────────────────────────────────────────
    section("3. What must still be refused")

    await expect("a learner of ANOTHER company",
                 ES.link_user(HR, CLIENT, "EMP-SPARE-CLIENT", str(OUTSIDER_U)),
                 422, "must belong to a user of this company")
    # A staff account is not a member of a CLIENT company -- the original guard's real
    # purpose, which the fix must not have widened away.
    await expect("a staff account offered to a CLIENT company",
                 ES.link_user(HR, CLIENT, "EMP-SPARE-CLIENT", str(STAFF_U)),
                 422, "must belong to a user of this company")
    await expect("an account that already has a profile",
                 ES.link_user(HR, INTERNAL, "EMP-SPARE", str(STAFF_U)),
                 409, "already has an employee profile")
    await expect("a profile that is already linked",
                 ES.link_user(HR, INTERNAL, "EMP-INTERNAL", str(ObjectId())),
                 409, "already linked")
    await expect("an id no account holds",
                 ES.link_user(HR, INTERNAL, "EMP-SPARE", str(ObjectId())),
                 404, "user not found")

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
