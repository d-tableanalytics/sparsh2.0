"""P1-065 verification harness -- every calculation method, priced end to end.

FRD §24: "Fixed, percentage, formula, manual/imported, slab/table and attendance-linked
calculation methods are supported." The UAT cycle executed Fixed, Percentage and Formula in a
real run; this harness drives all six through the same pricing path a payroll run uses --
`resolve_lines` (structure save), `_reprice_for_period` (run time) and `_component_lines` (the
record's lines, proration and imported inputs) -- so none of them is "exists in code only".

House convention: self-contained, no pytest, no database, ASCII output, exit 1 on fail.
Run:  python -m app.services.hrms.tests.test_p1_065_calculation_methods   (from backend/)
"""
from __future__ import annotations

import sys

results: list[bool] = []


def check(label: str, condition: bool, detail=None) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + ("" if condition else f"  -- {detail}"))
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


def main() -> int:
    from app.services import hrms_payroll_service as P

    meta = {
        "BASIC": {"code": "BASIC", "component_type": "Earning", "sequence": 10,
                  "calculation_method": "Fixed", "version": 1},
        "HRA": {"code": "HRA", "component_type": "Earning", "sequence": 20,
                "calculation_method": "Percentage", "calculation_base": "BASIC",
                "percentage": 40, "version": 1},
        "CONV": {"code": "CONV", "component_type": "Earning", "sequence": 30,
                 "calculation_method": "Formula", "formula": "MIN(2000, BASIC * 0.1)",
                 "version": 1},
        "SPECIAL": {"code": "SPECIAL", "component_type": "Earning", "sequence": 40,
                    "calculation_method": "Manual Input", "version": 1},
        "INCENTIVE": {"code": "INCENTIVE", "component_type": "Earning", "sequence": 50,
                      "calculation_method": "Imported Input", "version": 1},
        "SHIFT_ALW": {"code": "SHIFT_ALW", "component_type": "Earning", "sequence": 60,
                      "calculation_method": "Attendance Linked", "rate": 150,
                      "attendance_basis": "payable_days", "version": 1},
        "PT": {"code": "PT", "component_type": "Deduction", "sequence": 90,
               "calculation_method": "Slab", "calculation_base": "GROSS",
               "slabs": [{"upto": 7500, "amount": 0}, {"upto": 10000, "amount": 175},
                         {"upto": None, "amount": 200}], "version": 1},
    }
    entered = [{"code": "BASIC", "amount": 30000}, {"code": "HRA", "amount": 0},
               {"code": "CONV", "amount": 0}, {"code": "SPECIAL", "amount": 2500},
               {"code": "INCENTIVE", "amount": 0}, {"code": "SHIFT_ALW", "amount": 0},
               {"code": "PT", "amount": 0}]

    section("1. Structure save prices the derived methods")
    saved = P.resolve_lines(entered, meta, annual_ctc=480000)
    amt = {r["code"]: r["amount"] for r in saved}
    check("Fixed: BASIC is the entered 30,000", amt["BASIC"] == 30000, amt)
    check("Percentage: HRA = 40% of BASIC = 12,000", amt["HRA"] == 12000, amt)
    check("Formula: CONV = MIN(2000, 3,000) = 2,000", amt["CONV"] == 2000, amt)
    check("Manual input: SPECIAL is the figure entered for this employee (2,500)",
          amt["SPECIAL"] == 2500, amt)
    check("Slab: PT on gross above 10,000 = 200", amt["PT"] == 200, amt)
    check("every line carries its method and component version",
          all(r.get("method") and r.get("component_version") == 1 for r in saved), saved)

    structure = {"components": saved, "annual_ctc": 480000}
    days = {"payable_days": 26.0, "working_days": 26, "calendar_days": 30}

    section("2. A payroll run prices the run-time methods")
    run_structure = P._reprice_for_period(structure, meta, days, {}, "2026-09-30")
    lines = P._component_lines(run_structure, meta, 26.0 / 30.0, days=days,
                               imported={"INCENTIVE": 4000})
    by = {l["code"]: l for l in lines}
    check("Imported input: INCENTIVE is this period's file figure (4,000), not prorated",
          by["INCENTIVE"]["amount"] == 4000 and not by["INCENTIVE"]["prorated"], by["INCENTIVE"])
    check("Attendance linked: SHIFT_ALW = 150 x 26 payable days = 3,900",
          by["SHIFT_ALW"]["full_amount"] == 3900, by["SHIFT_ALW"])
    check("Fixed earning is prorated by payable days (26/30)",
          by["BASIC"]["amount"] == 26000 and by["BASIC"]["prorated"], by["BASIC"])
    check("Slab deduction is not prorated", by["PT"]["amount"] == 200, by["PT"])
    check("all six methods appear on the record",
          {by[c]["method"] for c in by if by[c].get("method")} >= {
              "Fixed", "Percentage", "Formula", "Manual Input", "Attendance Linked", "Slab"}
          and "INCENTIVE" in by, sorted({l.get("method") for l in lines}))

    section("3. An imported component with no file figure pays nothing")
    none = {l["code"]: l for l in P._component_lines(run_structure, meta, 1.0, days=days)}
    check("INCENTIVE is 0 without an imported figure",
          none["INCENTIVE"]["amount"] == 0, none["INCENTIVE"])

    passed = sum(results)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
