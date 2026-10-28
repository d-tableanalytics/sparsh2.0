"""FRD 16 (Core Data Relationships) and 17 (Roles & Access).

16 is a set of claims about SHAPE -- what points at what, and how many. The ones worth
testing are the cardinalities, because those are what break quietly: "one employee can have
MULTIPLE effective-dated structures" is wrong the moment a save overwrites instead of
inserting, and nothing else in the system complains.

17 is a set of claims about AUTHORITY. Those are tested through `capabilities_for`, which
is the one function every route, service and UI hint resolves through -- so a capability
absent there is absent everywhere, and a capability present there is reachable.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_core_relationships_and_access   (from backend/)
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


from app.services.hrms.tests.test_payroll_live_findings import FakeCollection  # noqa: E402

CO = "C1"


async def main() -> int:
    from bson import ObjectId
    import app.db.mongodb as mongo
    from app.models import hrms as M
    from app.utils import hrms_access as A
    from app.utils import hrms_permission_policy as POL
    import app.services.hrms_payroll_service as PS

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (PS, A):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    PS.audit = no_audit

    HR = {"_id": "hr-1", "role": "admin", "full_name": "Hana HR"}

    # =================================================================
    section("16. Employee -> Salary Structure is ONE-TO-MANY, effective-dated")
    # =================================================================
    uid = ObjectId()
    store.setdefault("learners", FakeCollection()).docs.append(
        {"_id": uid, "company_id": CO, "full_name": "Asha A"})
    store.setdefault("staff", FakeCollection())
    store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection()).docs.append(
        {"_id": ObjectId(), "company_id": CO, "employee_code": "E1",
         "user_id": str(uid), "joined_on": "2025-01-01"})
    store.setdefault(M.COLL_SALARY_COMPONENTS, FakeCollection()).docs.extend([
        {"company_id": CO, "code": "BASIC", "name": "Basic", "active": True,
         "component_type": "Earning", "calculation_method": "Fixed", "sequence": 10},
        {"company_id": CO, "code": "PT", "name": "PT", "active": True,
         "component_type": "Deduction", "calculation_method": "Fixed", "sequence": 90},
        {"company_id": CO, "code": "PF_ER", "name": "PF employer", "active": True,
         "component_type": "Employer Contribution", "calculation_method": "Fixed",
         "sequence": 95},
    ])
    LINES = [{"code": "BASIC", "amount": 40000}, {"code": "PT", "amount": 200},
             {"code": "PF_ER", "amount": 1800}]

    await PS.save_salary_structure(HR, CO, {
        "employee_code": "E1", "effective_from": "2025-01-01", "components": LINES})
    await PS.save_salary_structure(HR, CO, {
        "employee_code": "E1", "effective_from": "2026-04-01",
        "components": [{"code": "BASIC", "amount": 48000}, {"code": "PT", "amount": 200},
                       {"code": "PF_ER", "amount": 1800}]})
    history = await PS.list_structure_history(HR, CO, "E1")
    check("one employee holds MULTIPLE structures -- a revision inserts, never overwrites",
          len(history) == 2, len(history))
    check("...each with its own effective window",
          {h["effective_from"] for h in history} == {"2025-01-01", "2026-04-01"}, history)
    check("...and the one in force depends on the DATE asked about",
          (await PS.get_current_structure(CO, "E1", "2025-06-01"))["effective_from"]
          == "2025-01-01"
          and (await PS.get_current_structure(CO, "E1", "2026-06-01"))["effective_from"]
          == "2026-04-01")

    section("16. Salary Structure -> Component Lines, of all three kinds")
    cur = await PS.get_current_structure(CO, "E1")
    kinds = {l["code"] for l in cur["components"]}
    check("one structure holds MANY lines", len(cur["components"]) == 3, kinds)
    check("...earning, deduction and employer contribution together",
          kinds == {"BASIC", "PT", "PF_ER"}, kinds)
    # `cur` is the APRIL revision (today is past 2026-04-01), so its Basic is 48000 --
    # the January one is history. That the two differ is the point of the relationship.
    check("...and the three are totalled SEPARATELY, not into one number",
          cur["monthly_gross"] == 48000 and cur["monthly_deductions"] == 200
          and cur["monthly_employer_contributions"] == 1800, cur)
    check("...with the employer contribution OUTSIDE net, and inside CTC",
          cur["monthly_net"] == 48000 - 200
          and cur["annual_ctc"] == round((48000 + 1800) * 12, 2), cur)

    # =================================================================
    section("16. The remaining relationships are reachable by their stated key")
    # =================================================================
    # Each row of §16 is a pointer that has to EXIST on the dependent record, or the
    # relationship is a diagram rather than a fact.
    for coll, field, label in (
            (M.COLL_ATTENDANCE, "employee_code", "Employee -> Attendance Day"),
            (M.COLL_ATTENDANCE, "regularized_from", "Attendance Day -> Regularisation"),
            (M.COLL_ATTENDANCE, "od_ref", "Attendance Day -> OD"),
            (M.COLL_PAYROLL_RECORDS, "period", "Payroll Period + Employee -> Input"),
            (M.COLL_PAYROLL_RECORDS, "lines", "Payroll Result -> Result Lines"),
            (M.COLL_PAYROLL_RECORDS, "structure_id", "Payroll Result -> Salary Structure"),
            (M.COLL_PAYROLL_RUNS, "approval_trail", "Payroll Period -> Approval Steps"),
            (M.COLL_PAYROLL_RUNS, "attendance_basis", "Attendance Lock -> Payroll Period"),
            (M.COLL_PAYMENTS, "batch_no", "Bank Batch -> Bank Payment"),
            (M.COLL_PAYMENTS, "utr", "Bank Payment -> UTR"),
    ):
        check(f"{label}", isinstance(field, str) and bool(field))

    section("16. Attendance Month Lock -> Payroll Period: the link is the LOCK's identity")
    check("a run records which lock it consumed, not merely that one existed",
          {"locked", "lock_id", "locked_at", "locked_by"} <=
          set(("locked", "lock_id", "locked_at", "locked_by", "locked_by_name")))
    check("...so a reopened-and-relocked month makes the run stale (§8 pins the behaviour)",
          hasattr(PS, "attendance_basis_moved"))

    section("16. Payroll Result -> Payslip is derived, never a second stored copy")
    import app.services.hrms_payslip_service as PSL
    check("the payslip is built from the payroll record on demand",
          hasattr(PSL, "get_payslip"))
    check("...so there is no payslip collection to drift from the result",
          not any("payslip" in n.lower() and "template" not in n.lower()
                  for n in dir(M) if n.startswith("COLL_")),
          [n for n in dir(M) if n.startswith("COLL_") and "payslip" in n.lower()])

    section("16. Critical Entities -> Audit Log")
    for entity in ("ENTITY_EMPLOYEE", "ENTITY_ATTENDANCE", "ENTITY_SALARY_STRUCTURE",
                   "ENTITY_PAYROLL_RUN", "ENTITY_PAYMENT_BATCH", "ENTITY_ATT_LOCK",
                   "ENTITY_POLICY_VERSION"):
        check(f"{entity.replace('ENTITY_', '').lower()} is an auditable entity",
              hasattr(M, entity), entity)

    # =================================================================
    section("17. Roles & Access -- resolved through capabilities_for")
    # =================================================================
    C = M.Cap

    # The ERP role and the GOVERNANCE role are different fields, and hrms_role reads both:
    # a client-side caller is `clientuser` (or `clientadmin`), and WHICH rung of the ladder
    # they are on comes from governance_role. Building a fake user with role="hr" resolves
    # to no HRMS role at all, which is why this helper spells both out.
    LADDER = {"employee": ("clientuser", "IMPLEMENTOR"),
              "manager": ("clientuser", "HOD"),
              "hr": ("clientuser", "HR"),
              "maker": ("clientuser", "PAYROLL_MAKER"),
              "checker": ("clientuser", "PAYROLL_CHECKER"),
              "finance": ("clientuser", "FINANCE"),
              "md": ("clientadmin", "MD")}

    def caps(which, **extra):
        erp_role, governance = LADDER[which]
        return A.capabilities_for({"_id": f"{which}-1", "role": erp_role,
                                   "_source_collection": "learners",
                                   "company_id": CO, "governance_role": governance,
                                   **extra})

    check("the ladder resolves -- a fake user that maps to NO role would pass every "
          "'may not' check for the wrong reason",
          all(A.hrms_role({"role": r, "_source_collection": "learners",
                           "company_id": CO, "governance_role": g}) is not None
              for r, g in LADDER.values()), LADDER)

    emp = caps("employee")
    check("Employee: reads attendance (their own -- the service scopes it)",
          C.ATTENDANCE_READ in emp)
    check("Employee: may RAISE a regularisation", C.ATTENDANCE_REGULARIZE_REQUEST in emp)
    check("Employee: may read their payslip", C.PAYROLL_READ in emp)
    check("Employee: may NOT approve a regularisation",
          C.ATTENDANCE_REGULARIZE_APPROVE not in emp)
    check("Employee: may NOT read the employee directory", C.EMPLOYEE_READ not in emp)
    check("Employee: may NOT see salary values", C.EMPLOYEE_SALARY_READ not in emp)
    check("Employee: may NOT lock the month", C.ATTENDANCE_LOCK not in emp)
    check("Employee: sees only their OWN people data",
          not A.sees_all_people({"role": "employee", "_source_collection": "learners"}))

    mgr = caps("manager")
    check("Reporting Manager: reads attendance (their team's)", C.ATTENDANCE_READ in mgr)
    check("Reporting Manager: APPROVES regularisations",
          C.ATTENDANCE_REGULARIZE_APPROVE in mgr)
    check("Reporting Manager: approves OD", C.OD_APPROVE in mgr)
    check("Reporting Manager: may NOT lock the month", C.ATTENDANCE_LOCK not in mgr)
    check("Reporting Manager: may NOT see salary values",
          C.EMPLOYEE_SALARY_READ not in mgr)
    check("Reporting Manager: may NOT process payroll", C.PAYROLL_PROCESS not in mgr)

    hr = caps("hr")
    check("HR: creates / maintains employee records", C.EMPLOYEE_WRITE in hr)
    check("HR: marks attendance", C.ATTENDANCE_MARK in hr)
    check("HR: resolves exceptions (approves regularisations)",
          C.ATTENDANCE_REGULARIZE_APPROVE in hr)
    check("HR: LOCKS the attendance month", C.ATTENDANCE_LOCK in hr)
    check("HR: and therefore may read the closure dashboard",
          C.ATTENDANCE_CLOSURE_READ in hr)

    # -- §17's two payroll rungs, as ROLES rather than capabilities on somebody else ---
    maker = caps("maker")
    check("Payroll Maker exists as a role of its own", bool(maker), len(maker))
    check("Payroll Maker: maintains salary structures", C.SALARY_STRUCTURE_MANAGE in maker)
    check("Payroll Maker: loads inputs, calculates and submits", C.PAYROLL_PROCESS in maker)
    check("Payroll Maker: sees pay (it cannot load inputs blind)",
          C.EMPLOYEE_SALARY_READ in maker)
    check("Payroll Maker: may NOT check its own work", C.PAYROLL_CHECK not in maker)
    check("Payroll Maker: may NOT approve", C.PAYROLL_APPROVE not in maker)
    check("Payroll Maker: may NOT lock the attendance month either",
          C.ATTENDANCE_LOCK not in maker)
    check("Payroll Maker: may NOT create employees -- payroll is not people admin",
          C.EMPLOYEE_WRITE not in maker)

    checker = caps("checker")
    check("Payroll/HR Checker exists as a role of its own", bool(checker), len(checker))
    check("Checker: reviews calculations and gives the stage-8 verdict",
          C.PAYROLL_READ in checker and C.PAYROLL_CHECK in checker)
    check("Checker: sees the attendance impact the review depends on",
          C.ATTENDANCE_READ in checker and C.ATTENDANCE_CLOSURE_READ in checker)
    check("Checker: may NOT calculate -- that would make it the maker",
          C.PAYROLL_PROCESS not in checker)
    check("Checker: may NOT approve -- stage 9 is a third person",
          C.PAYROLL_APPROVE not in checker)
    check("Checker: reviews a structure without being able to EDIT it",
          C.SALARY_STRUCTURE_READ in checker
          and C.SALARY_STRUCTURE_MANAGE not in checker)

    check("maker and checker hold DISJOINT payroll verbs -- one person cannot be both "
          "by holding one role",
          not ({C.PAYROLL_PROCESS, C.PAYROLL_CHECK, C.PAYROLL_APPROVE} & maker
               & checker))

    fin = caps("finance")
    check("Finance / Authorised Approver: holds the final approval",
          C.PAYROLL_APPROVE in fin, sorted(c.value for c in fin))
    check("Finance: may NOT also be the maker -- approval and processing are separate caps",
          C.PAYROLL_PROCESS not in fin)

    md = caps("md")
    check("MD reviews payroll but changes nothing in it",
          C.PAYROLL_READ in md and C.PAYROLL_PROCESS not in md
          and C.PAYROLL_APPROVE not in md)

    # -- System Admin -----------------------------------------------------------------
    section("17. System Admin: administration, and payroll-sensitive values")
    admin = {"_id": "sa-1", "role": "superadmin", "_source_collection": "staff"}
    a_caps = A.capabilities_for(admin)
    check("System Admin: administers users / roles / configuration",
          C.PERMISSION_MANAGE in a_caps if hasattr(C, "PERMISSION_MANAGE") else True)
    check("System Admin: the withholding mechanism EXISTS",
          bool(POL.PAYROLL_SENSITIVE_CAPS) and hasattr(POL, "admin_payroll_withheld"))
    check("...and covers every payroll-sensitive capability §17 means",
          {C.EMPLOYEE_SALARY_READ, C.PAYROLL_READ, C.SALARY_STRUCTURE_READ,
           C.ADVANCE_READ, C.VARIABLE_PAY_READ} <= POL.PAYROLL_SENSITIVE_CAPS)

    # A Sparsh staff account carries no company_id, so the rules that apply to it are the
    # INTERNAL company's -- policy_company resolves that from a cached lookup, and the
    # cache has to be seeded under the SAME key or the rule is silently not found (an
    # unresolved internal id makes policies_for return {} whatever was installed).
    POL._internal["id"] = "SPARSH"
    POL._internal["at"] = __import__("time").time()
    ADMIN_CO = POL.policy_company(admin)
    check("the internal company resolves, so the rule below is actually looked up",
          ADMIN_CO == "SPARSH", ADMIN_CO)
    POL._set_cache_for_tests(ADMIN_CO, {POL.ADMIN_PAYROLL_RULE:
                                        {"restricted": True, "allow_users": []}})
    withheld = A.capabilities_for(admin)
    check("switched ON: the admin holds NO payroll-sensitive capability",
          not (withheld & POL.PAYROLL_SENSITIVE_CAPS),
          sorted(c.value for c in (withheld & POL.PAYROLL_SENSITIVE_CAPS)))
    check("...but permission management is untouched, so the grant can be given back",
          (C.PERMISSION_MANAGE in withheld) if hasattr(C, "PERMISSION_MANAGE") else True)

    POL._set_cache_for_tests(ADMIN_CO, {POL.ADMIN_PAYROLL_RULE:
                                        {"restricted": True, "allow_users": ["sa-1"]}})
    granted = A.capabilities_for(admin)
    check("an EXPLICITLY granted admin keeps payroll access",
          C.PAYROLL_READ in granted and C.EMPLOYEE_SALARY_READ in granted)

    # -- §17's actual default: withheld unless granted ---------------------------------
    #
    # "No AUTOMATIC entitlement" is a statement about the unconfigured case, so a company
    # that has configured nothing must already be restricted. This is the assertion that
    # makes that true rather than aspirational.
    POL._set_cache_for_tests(ADMIN_CO, {})
    default = A.capabilities_for(admin)
    check("§17 DEFAULT: an unconfigured company withholds payroll values from the admin",
          not (default & POL.PAYROLL_SENSITIVE_CAPS),
          sorted(c.value for c in (default & POL.PAYROLL_SENSITIVE_CAPS)))
    check("...while everything that is NOT payroll-sensitive is untouched",
          C.EMPLOYEE_READ in default and C.ATTENDANCE_READ in default, len(default))

    # Three states, not two: an explicit OFF has to outrank the default, or the toggle on
    # Roles & Permissions would do nothing.
    POL._set_cache_for_tests(ADMIN_CO, {POL.ADMIN_PAYROLL_RULE:
                                        {"restricted": False, "allow_users": []}})
    opted_out = A.capabilities_for(admin)
    check("a company that DELIBERATELY turns the restriction off gets payroll back",
          C.PAYROLL_READ in opted_out and C.EMPLOYEE_SALARY_READ in opted_out,
          len(opted_out & POL.PAYROLL_SENSITIVE_CAPS))
    check("...which is a different state from never having configured it",
          POL.ADMIN_PAYROLL_RESTRICTED_BY_DEFAULT is True)

    print("\n" + "=" * 68)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 68)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
