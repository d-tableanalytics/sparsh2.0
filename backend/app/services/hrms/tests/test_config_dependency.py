"""Phase 1 FRD §22/§29/§30 -- the configuration impact / dependency check.

  1. References and HISTORY are reported separately -- they have opposite consequences,
     and merging them would make every long-serving component look un-retirable.
  2. A component used by a live formula cannot be retired, and the refusal NAMES what
     uses it (§22 Control 3).
  3. A component only ever PAID can be retired -- that is the whole reason §21 says
     retire rather than delete.
  4. The same check answers for configurable fields and policies.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_config_dependency   (from backend/)
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


async def main() -> int:
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_config_dependency_service as DEP

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    DEP.get_collection = getter

    # BASIC is referenced by HRA's percentage and by PF's formula. BONUS is referenced by
    # nothing, but has been paid.
    store.setdefault(M.COLL_SALARY_COMPONENTS, FakeCollection()).docs.extend([
        {"company_id": CO, "code": "BASIC", "name": "Basic", "component_type": "Earning",
         "calculation_method": "Fixed"},
        {"company_id": CO, "code": "HRA", "name": "HRA", "component_type": "Earning",
         "calculation_method": "Percentage", "calculation_base": "BASIC", "percentage": 40},
        {"company_id": CO, "code": "PF", "name": "PF", "component_type": "Deduction",
         "calculation_method": "Formula", "formula": "BASIC * 0.12"},
        {"company_id": CO, "code": "BONUS", "name": "Bonus", "component_type": "Earning",
         "calculation_method": "Fixed"},
    ])
    store.setdefault(M.COLL_SALARY_STRUCTURES, FakeCollection()).docs.append(
        {"company_id": CO, "employee_code": "E1", "status": "Active",
         "components": [{"code": "BASIC", "amount": 30000}]})
    store.setdefault(M.COLL_PAYROLL_RECORDS, FakeCollection()).docs.extend([
        {"company_id": CO, "period": "2026-01", "employee_code": "E1",
         "lines": [{"code": "BASIC"}, {"code": "BONUS"}]},
        {"company_id": CO, "period": "2026-02", "employee_code": "E1",
         "lines": [{"code": "BONUS"}]},
    ])

    # ── 1. References and history are separate ──────────────────────────────────────
    section("1. A reference is not the same thing as history (§21, §30)")

    basic = await DEP.where_used(CO, DEP.ENTITY_COMPONENT, "BASIC")
    kinds = {r["kind"] for r in basic["references"]}
    check("a percentage base and a formula both count as references",
          "component" in kinds
          and {r["name"] for r in basic["references"] if r["kind"] == "component"}
              == {"HRA", "PF"})
    check("a live salary structure counts too", "salary structure" in kinds)
    check("having been paid is HISTORY, not a reference",
          any(h["kind"] == "payroll record" for h in basic["history"]))
    check("BASIC cannot be retired -- things would break",
          basic["can_retire"] is False and basic["blocking_count"] >= 2)

    bonus = await DEP.where_used(CO, DEP.ENTITY_COMPONENT, "BONUS")
    check("BONUS is referenced by nothing", bonus["references"] == [])
    check("...but it HAS been paid twice",
          any("2 payroll record" in h["name"] for h in bonus["history"]))
    check("...so it CAN be retired -- history never blocks (§21)",
          bonus["can_retire"] is True)
    check("the summary says so plainly", "safe to retire" in bonus["summary"])

    # ── 2. The refusal names what uses it ───────────────────────────────────────────
    section("2. A refusal that names the dependants (§22 Control 3)")

    await expect("retiring a component a formula still uses",
                 DEP.assert_retirable(CO, DEP.ENTITY_COMPONENT, "BASIC"), 409, "HRA")
    try:
        await DEP.assert_retirable(CO, DEP.ENTITY_COMPONENT, "BASIC")
    except Exception as e:
        check("...and names every one of them, not just the first",
              "HRA" in str(e) and "PF" in str(e) and "salary structure" in str(e))
    await DEP.assert_retirable(CO, DEP.ENTITY_COMPONENT, "BONUS")
    check("retiring a merely-paid component is allowed", True)

    # ── 3. Fields ───────────────────────────────────────────────────────────────────
    section("3. The same check answers for a configurable field")

    store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection()).docs.extend([
        {"company_id": CO, "employee_code": "E1", "custom_fields": {"gmp_id": "G-1"}},
        {"company_id": CO, "employee_code": "E2", "custom_fields": {}},
    ])
    store.setdefault(M.COLL_BANK_FILE_FORMATS, FakeCollection()).docs.append(
        {"company_id": CO, "name": "HDFC", "columns": [{"source": "gmp_id"}]})
    store.setdefault(M.COLL_POLICY_ASSIGNMENTS, FakeCollection()).docs.append(
        {"company_id": CO, "policy_code": "ATT_DAY", "version_no": 1,
         "scope": {"grades": ["M3"]}})

    gmp = await DEP.where_used(CO, DEP.ENTITY_FIELD, "gmp_id")
    check("one employee holds a value -- history, so it does not block",
          any("1 employee" in h["name"] for h in gmp["history"]))
    check("a bank format emitting the field IS a reference",
          any(r["kind"] == "bank file format" for r in gmp["references"]))
    check("...so the field cannot be retired while that format exists",
          gmp["can_retire"] is False)

    grades = await DEP.where_used(CO, DEP.ENTITY_FIELD, "grades")
    check("a policy scoped on a field references it",
          any(r["kind"] == "policy scope" for r in grades["references"]))

    # ── 4. Policies ─────────────────────────────────────────────────────────────────
    section("4. ...and for a policy")

    store.setdefault(M.COLL_POLICY_VERSIONS, FakeCollection()).docs.extend([
        {"company_id": CO, "policy_code": "ATT_DAY", "version_no": 1, "status": "Superseded"},
        {"company_id": CO, "policy_code": "ATT_DAY", "version_no": 2, "status": "Active"},
    ])
    att = await DEP.where_used(CO, DEP.ENTITY_POLICY, "ATT_DAY")
    check("an Active version is a reference", any(
        r["kind"] == "policy version" and "v2" in r["name"] for r in att["references"]))
    check("a superseded version is history -- closed periods still resolve to it",
          any(h["kind"] == "policy version" for h in att["history"]))
    check("an actively-judging policy cannot be retired", att["can_retire"] is False)

    await expect("an entity with no dependency check",
                 DEP.where_used(CO, "favourite_colour", "X"), 422, "no dependency check")

    print("\n" + "=" * 60)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 60)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
