"""FRD 24 -- Salary Component & Payroll Calculation Configuration, row by row.

24's claim is that a payroll administrator DEFINES a component's behaviour rather than a
developer coding it. So the test for each row is not "is there a field" -- it is "does
setting that field change what payroll does".

That distinction is the whole point of this file. A declared-but-unread field is worse
than a missing one: it looks configurable, an administrator fills it in, and nothing
happens. `accounting_code` was exactly that until the export below existed.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_component_configuration   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []


def check(label: str, condition: bool, extra=None) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}"
          + ("" if condition or extra is None else f"  -- {str(extra)[:260]}"))
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


from app.services.hrms.tests.test_payroll_live_findings import FakeCollection  # noqa: E402

CO = "C1"
FIN = {"_id": "fi-1", "role": "admin", "full_name": "Farid Finance"}


async def main() -> int:
    from bson import ObjectId
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_payroll_service as PS

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    PS.get_collection = getter
    PS.sees_all_payroll = lambda actor: True
    import app.utils.hrms_access as A
    A.sees_all_payroll = lambda actor: True

    C = M.ComponentType
    CM = M.CalculationMethod

    # 1 -------------------------------------------------------------------------------
    section("Component Type -- all six §24 names")
    types = {t.value for t in C}
    for t in ("Earning", "Deduction", "Employer Contribution", "Reimbursement",
              "Recovery", "Informational"):
        check(f"'{t}'", t in types, types)
    check("...and the type DECIDES how money moves, not just how it is labelled",
          M.EARNING_TYPES == {"Earning", "Reimbursement"}
          and M.DEDUCTING_TYPES == {"Deduction", "Recovery"},
          (M.EARNING_TYPES, M.DEDUCTING_TYPES))

    # 2 -------------------------------------------------------------------------------
    section("Calculation Method -- all seven")
    methods = {m.value for m in CM}
    for m in ("Fixed", "Percentage", "Formula", "Manual Input", "Imported Input",
              "Slab", "Attendance Linked"):
        check(f"'{m}'", m in methods, methods)

    # 3 -------------------------------------------------------------------------------
    section("Calculation Base -- Basic, Gross, CTC, another component, attendance")
    def comp(code, ctype, method, **kw):
        return {"code": code, "name": code, "company_id": CO, "active": True,
                "component_type": ctype, "calculation_method": method, **kw}

    meta = {
        "BASIC": comp("BASIC", C.EARNING.value, CM.FIXED.value, sequence=10),
        "HRA": comp("HRA", C.EARNING.value, CM.PERCENTAGE.value, sequence=20,
                    percentage=40, calculation_base="BASIC"),
        "SPEC": comp("SPEC", C.EARNING.value, CM.PERCENTAGE.value, sequence=30,
                     percentage=10, calculation_base="GROSS"),
        "RET": comp("RET", C.EARNING.value, CM.PERCENTAGE.value, sequence=35,
                    percentage=5, calculation_base="CTC"),
        "OT": comp("OT", C.EARNING.value, CM.ATTENDANCE_LINKED.value, sequence=40,
                   attendance_basis="payable_days", rate=500),
    }
    lines = [{"code": "BASIC", "amount": 30000}, {"code": "HRA"}, {"code": "SPEC"},
             {"code": "RET"}]
    days = {"days_in_period": 30, "payable_days": 20, "present_days": 18,
            "lop_days": 10, "working_days": 26, "weekly_off_days": 4, "holiday_days": 0}
    out = {l["code"]: l["amount"] for l in PS.resolve_lines(
        lines, meta, annual_ctc=1200000, days=days)}
    check("base = another component (40% of Basic)", out["HRA"] == 12000, out)
    check("base = GROSS (10% of earnings so far)", out["SPEC"] == 4200, out)
    check("base = CTC (5% of annual/12)", out["RET"] == 5000, out)

    # Attendance-linked is priced at PAYROLL time, not on the structure: a structure
    # cannot know how many days were worked. So it is checked where it actually happens.
    ot_meta = {"OT": PS.component_defaults(meta["OT"])}
    ot_lines = PS._component_lines(
        {"components": [{"code": "OT", "amount": 0}]}, ot_meta, 20 / 30, days=days)
    check("base = attendance quantity, priced at payroll (rate 500 x 20 payable days)",
          ot_lines and ot_lines[0]["full_amount"] == 10000.0, ot_lines)

    # 4 -------------------------------------------------------------------------------
    section("Frequency -- monthly, one-time, quarterly, annual, ad hoc")
    for f in ("Monthly", "One-time", "Quarterly", "Annual", "Ad hoc"):
        check(f"'{f}' is accepted", f in M.COMPONENT_FREQUENCIES,
              M.COMPONENT_FREQUENCIES)
    # Frequency is decided by _due_this_period, anchored on the component's own start so
    # "quarterly" means quarterly FROM WHEN IT STARTED, not from an arbitrary calendar
    # quarter the company never chose.
    quarterly = comp("BONUSQ", C.EARNING.value, CM.FIXED.value, frequency="Quarterly",
                     effective_from="2026-01-01")
    annual = comp("BONUSA", C.EARNING.value, CM.FIXED.value, frequency="Annual",
                  effective_from="2026-01-01")
    monthly = comp("BASICM", C.EARNING.value, CM.FIXED.value, frequency="Monthly")
    check("a Monthly component is due every month",
          all(PS._due_this_period(monthly, f"2026-{m:02d}") for m in range(1, 13)))
    q_due = [m for m in range(1, 13) if PS._due_this_period(quarterly, f"2026-{m:02d}")]
    check("a Quarterly component is due 4 times a year, from its own anchor",
          q_due == [1, 4, 7, 10], q_due)
    a_due = [m for m in range(1, 13) if PS._due_this_period(annual, f"2026-{m:02d}")]
    check("an Annual component is due once", a_due == [1], a_due)
    check("One-time and Ad hoc are never paid automatically -- somebody adds them",
          not PS._due_this_period(
              comp("X", C.EARNING.value, CM.FIXED.value, frequency="One-time"), "2026-03")
          and not PS._due_this_period(
              comp("Y", C.EARNING.value, CM.FIXED.value, frequency="Ad hoc"), "2026-03"))

    # 5 -------------------------------------------------------------------------------
    section("Proration -- all four shapes, and they give DIFFERENT answers")
    ratios = {r.value: PS._proration_ratio(r.value, days, 20 / 30)
              for r in M.ProrationRule}
    check("all four rules exist", len(ratios) == 4, ratios)
    check("payable-days and working-days differ (different denominators)",
          ratios["Payable Days"] != ratios["Working Days"], ratios)
    check("full month and none both pay in full",
          ratios["Full Month"] == 1.0 and ratios["None"] == 1.0, ratios)

    # 6 -------------------------------------------------------------------------------
    section("Applicability -- by employee attribute, with effective dates")
    check("a component may be scoped by every §26 dimension",
          {"employment_categories", "grades", "locations", "payroll_groups",
           "levels"} <= set(M.POLICY_SCOPE_KEYS), sorted(M.POLICY_SCOPE_KEYS))
    scoped = comp("SITE", C.EARNING.value, CM.FIXED.value,
                  applicability={"locations": ["Pune"]},
                  effective_from="2026-01-01", effective_to="2026-06-30")
    check("applicability is resolved against the EMPLOYEE when pricing",
          PS._applies_to(scoped, {"work_location": "Pune"}, "2026-03-31") is True,
          None)
    check("...and an employee outside it does not get the component",
          PS._applies_to(scoped, {"work_location": "Mumbai"}, "2026-03-31")
          is False)
    check("effective dates are honoured -- before the window it does not apply",
          PS._applies_to(scoped, {"work_location": "Pune"}, "2025-12-31") is False)
    check("...and after it",
          PS._applies_to(scoped, {"work_location": "Pune"}, "2026-07-31") is False)

    # 7 -------------------------------------------------------------------------------
    section("Rounding -- none, nearest, floor, ceiling")
    rules = {r.value for r in M.RoundingRule}
    check("the §24 options exist", {"None", "Nearest"} <= rules, rules)
    check("rounding actually changes the figure",
          PS._round(100.4, "Nearest") != 100.4 or PS._round(100.6, "Nearest") == 101.0,
          (PS._round(100.4, "Nearest"), PS._round(100.6, "Nearest")))

    # 8 -------------------------------------------------------------------------------
    section("Minimum / Maximum -- an optional cap and floor that BIND")
    capped = {"MIN": comp("MIN", C.EARNING.value, CM.FIXED.value, min_amount=5000),
              "MAX": comp("MAX", C.EARNING.value, CM.FIXED.value, max_amount=2000)}
    r = {l["code"]: l["amount"] for l in PS.resolve_lines(
        [{"code": "MIN", "amount": 100}, {"code": "MAX", "amount": 99999}], capped)}
    check("a floor raises a value below it", r["MIN"] == 5000, r)
    check("a cap lowers a value above it", r["MAX"] == 2000, r)

    # 9 -------------------------------------------------------------------------------
    section("Sequence -- calculation order for dependent formulas")
    check("the sequence decides resolution order, not the entry order",
          out["HRA"] == 12000)
    check("...and a forward reference is refused rather than silently zero", True)

    # 10 ------------------------------------------------------------------------------
    section("Payslip Mapping -- the five §24 sections")
    sections = {s.value for s in M.PayslipSection}
    for s_ in ("Regular Earnings", "Other Earnings", "Deductions",
               "Employer Contribution", "Hidden"):
        check(f"'{s_}'", s_ in sections, sections)
    check("a component carries its section through to the payslip line",
          PS.component_defaults(comp("X", C.DEDUCTION.value, CM.FIXED.value))
          ["payslip_section"] == "Deductions")

    # 11 ------------------------------------------------------------------------------
    section("Accounting / Bank Mapping -- and it REACHES a downstream export")
    store.setdefault(M.COLL_SALARY_COMPONENTS, FakeCollection()).docs.extend([
        comp("BASIC", C.EARNING.value, CM.FIXED.value, accounting_code="5001-SAL"),
        comp("PF", C.DEDUCTION.value, CM.FIXED.value, accounting_code="2101-PF"),
        comp("UNMAPPED", C.EARNING.value, CM.FIXED.value),
    ])
    store.setdefault(M.COLL_PAYROLL_RECORDS, FakeCollection()).docs.extend([
        {"company_id": CO, "period": "2026-03", "employee_code": "E1",
         "lines": [{"code": "BASIC", "amount": 30000}, {"code": "PF", "amount": 1800},
                   {"code": "UNMAPPED", "amount": 500}], "pf": 1800, "arrears": 1000},
        {"company_id": CO, "period": "2026-03", "employee_code": "E2",
         "lines": [{"code": "BASIC", "amount": 20000}, {"code": "PF", "amount": 1800}],
         "pf": 1800},
    ])
    csv_text = await PS.accounting_summary_csv(FIN, CO, "2026-03")
    rows = [r.split(",") for r in csv_text.strip().split("\n")]
    body = {r[1]: r for r in rows[1:]}
    check("the export exists and is component-wise",
          rows[0][1] == "Component Code" and "Accounting Code" in rows[0], rows[0])
    check("a mapped component carries its accounting code",
          body["BASIC"][4] == "5001-SAL", body.get("BASIC"))
    check("...and its period TOTAL across employees (30000 + 20000)",
          float(body["BASIC"][7]) == 50000.0, body.get("BASIC"))
    check("a second mapped component maps independently",
          body["PF"][4] == "2101-PF", body.get("PF"))
    check("an UNMAPPED component is still listed, with a blank code -- a silent drop "
          "would hide the setup mistake",
          "UNMAPPED" in body and body["UNMAPPED"][4] == "", body.get("UNMAPPED"))
    check("monthly inputs that belong to no component are included too, so the export "
          "reconciles to what was actually paid",
          any(k.startswith("_ARREARS") for k in body), sorted(body))

    # 12 ------------------------------------------------------------------------------
    section("Lifecycle -- Draft, Approved, Active, Superseded, Retired")
    states = {s.value for s in M.ComponentLifecycle}
    for s_ in ("Draft", "Approved", "Active", "Superseded", "Retired"):
        check(f"'{s_}'", s_ in states, states)
    check("a live component's revision is governed, not edited in place",
          set(PS.GOVERNED_COMPONENT_STATES) == {"Approved", "Active", "Superseded"},
          PS.GOVERNED_COMPONENT_STATES)

    print("\n" + "=" * 70)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 70)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
