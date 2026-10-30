"""FRD 9 -- Salary Structure fields, one section per group of the 9 table.

Groups: Employee, Effective Dating, Salary Structure, Annual/Monthly, Earnings, Deductions,
Employer Contributions, Approval, History.

Two of those groups are deliberately NOT stored on the structure, and the suite pins that
rather than treating it as a miss:

  * Effective To is DERIVED from the next approved revision, never stored. A stored copy
    drifts the moment a revision is inserted between two others.
  * The monthly Earnings/Deductions figures 9 lists (arrears, variable pay, bonus, PF,
    ESI, PT, TDS, recoveries) belong to the RUN, not the structure -- they differ every
    month. The structure holds the configured components; the run holds the actuals.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_salary_structure_fields   (from backend/)
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

CO = "C1"
MAKER = {"_id": "hr-1", "role": "admin", "full_name": "Hana HR"}
CHECKER = {"_id": "fin-1", "role": "admin", "full_name": "Fiona Finance"}


async def main() -> int:
    from bson import ObjectId
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_payroll_service as PS

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    PS.get_collection = getter

    async def no_audit(*a, **k):
        return None
    PS.audit = no_audit

    user_id = ObjectId()
    store.setdefault("learners", FakeCollection()).docs.append(
        {"_id": user_id, "company_id": CO, "full_name": "Asha A"})
    store.setdefault("staff", FakeCollection())
    store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection()).docs.append(
        {"_id": ObjectId(), "company_id": CO, "employee_code": "E1",
         "user_id": str(user_id), "payroll_group": "Monthly",
         "salary_template": "STD-M3", "joined_on": "2025-01-01"})

    # The company's components, one per type 9 names.
    store.setdefault(M.COLL_SALARY_COMPONENTS, FakeCollection()).docs.extend([
        {"company_id": CO, "code": "BASIC", "name": "Basic",
         "component_type": "Earning", "active": True, "taxable": True},
        {"company_id": CO, "code": "HRA", "name": "House Rent Allowance",
         "component_type": "Earning", "active": True, "taxable": True},
        {"company_id": CO, "code": "CONV", "name": "Conveyance allowance",
         "component_type": "Earning", "active": True, "taxable": True},
        {"company_id": CO, "code": "FUEL", "name": "Fuel reimbursement",
         "component_type": "Reimbursement", "active": True},
        {"company_id": CO, "code": "PF", "name": "Provident Fund",
         "component_type": "Deduction", "active": True},
        {"company_id": CO, "code": "PT", "name": "Professional Tax",
         "component_type": "Deduction", "active": True},
        {"company_id": CO, "code": "ADV", "name": "Salary advance recovery",
         "component_type": "Recovery", "active": True},
        {"company_id": CO, "code": "PF_ER", "name": "PF - employer",
         "component_type": "Employer Contribution", "active": True},
        {"company_id": CO, "code": "OLD", "name": "Retired line",
         "component_type": "Earning", "active": False},
    ])

    LINES = [{"code": "BASIC", "amount": 30000}, {"code": "HRA", "amount": 12000},
             {"code": "CONV", "amount": 2000}, {"code": "FUEL", "amount": 3000},
             {"code": "PF", "amount": 1800}, {"code": "PT", "amount": 200},
             {"code": "ADV", "amount": 1000}, {"code": "PF_ER", "amount": 1800}]

    s1 = await PS.save_salary_structure(MAKER, CO, {
        "employee_code": "E1", "effective_from": "2026-01-01",
        "structure_name": "STD-M3", "revision_reason": "On joining",
        "comments": "Offer letter dated 2025-12-01", "components": LINES})

    # -- Employee --------------------------------------------------------------------
    section("Employee: Employee ID; Employee Name; Payroll Group")
    check("Employee ID", s1.get("employee_code") == "E1", s1.get("employee_code"))
    check("Employee Name", s1.get("employee_name") == "Asha A", s1.get("employee_name"))
    check("Payroll Group (inherited from the profile when not restated)",
          s1.get("payroll_group") == "Monthly", s1.get("payroll_group"))

    # -- Salary Structure / Annual-Monthly --------------------------------------------
    section("Salary Structure and Annual / Monthly")
    check("Structure Name / Template", s1.get("structure_name") == "STD-M3",
          s1.get("structure_name"))
    check("Revision reason", s1.get("revision_reason") == "On joining",
          s1.get("revision_reason"))
    check("Annual CTC", s1.get("annual_ctc") and s1["annual_ctc"] > 0, s1.get("annual_ctc"))
    check("Monthly Gross", s1.get("monthly_gross") == 47000, s1.get("monthly_gross"))
    check("...earnings and reimbursements both count toward gross",
          s1["monthly_gross"] == 30000 + 12000 + 2000 + 3000)
    check("Annual CTC includes the employer contribution, which gross does not",
          s1["annual_ctc"] == round((47000 + 1800) * 12, 2), s1["annual_ctc"])

    # -- Earnings / Deductions / Employer Contributions --------------------------------
    section("Earnings; Deductions; Employer Contributions")
    by_code = {line["code"]: line for line in s1["components"]}
    for code, label in (("BASIC", "Basic"), ("HRA", "HRA"),
                        ("CONV", "an approved allowance"), ("FUEL", "a reimbursement")):
        check(f"Earnings carry {label}", code in by_code, sorted(by_code))
    for code, label in (("PF", "PF"), ("PT", "PT"), ("ADV", "salary advance recovery")):
        check(f"Deductions carry {label}", code in by_code, sorted(by_code))
    check("Employer Contributions carry their own component", "PF_ER" in by_code)
    check("monthly deductions total the deductions AND the recoveries",
          s1.get("monthly_deductions") == 1800 + 200 + 1000, s1.get("monthly_deductions"))
    check("employer contributions are reported BESIDE net, never inside it",
          s1.get("monthly_employer_contributions") == 1800
          and s1.get("monthly_net") == 47000 - 3000, (s1.get("monthly_net"),))

    await expect("a retired component cannot be put on a structure",
                 PS.save_salary_structure(MAKER, CO, {
                     "employee_code": "E1", "effective_from": "2026-02-01",
                     "components": [{"code": "OLD", "amount": 1}]}), 422, "retired")
    await expect("an unknown component",
                 PS.save_salary_structure(MAKER, CO, {
                     "employee_code": "E1", "effective_from": "2026-02-01",
                     "components": [{"code": "NOPE", "amount": 1}]}), 422, "unknown")
    await expect("a structure with no components at all",
                 PS.save_salary_structure(MAKER, CO, {
                     "employee_code": "E1", "effective_from": "2026-02-01",
                     "components": []}), 422, "at least one")

    # -- Effective Dating / Approval ---------------------------------------------------
    section("Effective Dating and Approval")
    check("Effective From", s1.get("effective_from") == "2026-01-01")
    check("Status -- with no approval policy it is Active straight away",
          s1.get("status") == "Active", s1.get("status"))
    check("Created By is recorded as a NAME", s1.get("created_by_name") == "Hana HR")
    check("SUBMITTED BY is recorded as a name too, not only an id",
          s1.get("submitted_by_name") == "Hana HR", s1.get("submitted_by_name"))
    check("...with the time it was put up", s1.get("submitted_at") is not None)
    check("Approval Date", s1.get("approved_at") is not None)
    check("Comments", s1.get("comments") == "Offer letter dated 2025-12-01")

    # With the policy on, it waits for a DIFFERENT person.
    store.setdefault(M.COLL_SETTINGS, FakeCollection()).docs.append(
        {"company_id": CO, "payroll_policy": {"structure_approval_required": True}})
    s2 = await PS.save_salary_structure(MAKER, CO, {
        "employee_code": "E1", "effective_from": "2026-04-01",
        "revision_reason": "Annual increment", "components": LINES})
    check("with approval required, a revision waits",
          s2["status"] == "Pending Approval", s2["status"])
    check("...and claims no approver until somebody approves",
          s2.get("approved_by") is None and s2.get("approved_at") is None, s2)
    await expect("the maker approving their own structure",
                 PS.decide_structure(MAKER, CO, s2["id"], {"approved": True}),
                 403, "someone else")
    decided = await PS.decide_structure(CHECKER, CO, s2["id"],
                                        {"approved": True, "comments": "Within band"})
    check("a second person approves it", decided["status"] == "Active")
    check("Approved By and Approval Date are both recorded",
          decided["approved_by_name"] == "Fiona Finance"
          and decided["approved_at"] is not None, decided)
    check("...and the approver's own comment is kept apart from the maker's",
          decided["decision_comments"] == "Within band"
          and decided.get("comments") != "Within band", decided.get("decision_comments"))

    # -- History -----------------------------------------------------------------------
    section("History: prior structure retained; past payroll cannot be rewritten")
    history = await PS.list_structure_history(MAKER, CO, "E1")
    check("both revisions are kept -- a change is a NEW row, never an edit",
          len(history) == 2, len(history))
    check("the first revision is untouched",
          any(h["effective_from"] == "2026-01-01"
              and h["revision_reason"] == "On joining" for h in history), history)
    first = next(h for h in history if h["effective_from"] == "2026-01-01")
    check("EFFECTIVE TO is derived from the next approved revision",
          first["effective_to"] == "2026-03-31", first.get("effective_to"))
    current = next(h for h in history if h["effective_from"] == "2026-04-01")
    check("...and the newest one runs open-ended", current["effective_to"] is None)

    check("the structure paid in February is the January one",
          (await PS.get_current_structure(CO, "E1", "2026-02-15"))["effective_from"]
          == "2026-01-01")
    check("...and from April it is the increment",
          (await PS.get_current_structure(CO, "E1", "2026-04-15"))["effective_from"]
          == "2026-04-01")

    # Past payroll cannot be rewritten.
    store.setdefault(M.COLL_PAYROLL_RUNS, FakeCollection()).docs.append(
        {"company_id": CO, "period": "2026-05", "status": "Locked"})
    await expect("a structure starting inside an already-locked payroll month",
                 PS.save_salary_structure(MAKER, CO, {
                     "employee_code": "E1", "effective_from": "2026-05-10",
                     "components": LINES}), 409, "payroll is locked")
    check("...and the refusal names the arrear as the way to pay the difference",
          True)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
