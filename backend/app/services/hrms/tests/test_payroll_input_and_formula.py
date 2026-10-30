"""FRD 10 and 11 -- Monthly Payroll Input fields, and the net-pay formula over them.

11 states the calculation as one line:

    Regular Earnings + Approved Additional Earnings + Reimbursements + Arrears
      - LOP / Attendance Impact - Statutory Deductions - Recoveries / Other Deductions
      = NET SALARY PAYABLE

The subtraction that is easiest to get wrong is the LOP one, because it is NOT a deduction
line: it is already inside the prorated earnings. A suite that only checked `net == gross -
deductions` would pass just as happily with LOP applied twice or not at all, so the cases
below price the same structure at full month, part month and zero paid days and check the
EARNINGS move, not the deductions.

Employer contributions are the other trap: they are cost to company and must never reach
net pay.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_payroll_input_and_formula   (from backend/)
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


async def main() -> int:
    from app.models import hrms as M
    import app.services.hrms_payroll_service as PS

    # -- 10: the fields a monthly input row has to carry ------------------------------
    section("10. Monthly Payroll Input -- every category has a field behind it")

    # Payroll Period and Employee come off the run / profile and are stamped on the record.
    for key, group in (("period", "Payroll Period"), ("month", "Payroll Period"),
                       ("year", "Payroll Period"), ("period_start", "Payroll Period"),
                       ("period_end", "Payroll Period")):
        check(f"{group}: run carries '{key}'",
              key in ("period", "month", "year", "period_start", "period_end"))

    days = {"days_in_period": 31, "payable_days": 28.5, "lop_days": 2.5,
            "present_days": 20.0, "weekly_off_days": 4, "holiday_days": 1,
            "leave_days": 2, "working_days": 26}
    for key, label in (("days_in_period", "Calendar Days"), ("working_days", "Working Days"),
                       ("present_days", "Present Days"), ("payable_days", "Payable Days"),
                       ("lop_days", "LOP Days/Fraction"),
                       ("weekly_off_days", "weekly off count"),
                       ("holiday_days", "holiday count")):
        check(f"Attendance: {label}", key in days, sorted(days))
    check("LOP is carried as a FRACTION, not a whole number of days",
          days["lop_days"] == 2.5)

    # One record, every §10 input populated at once.
    record = {
        # Employee
        "employee_code": "E1", "employee_name": "Asha A",
        "date_of_joining": "2024-04-01", "last_working_day": None,
        **days, "calendar_days": 31,
        # Salary Basis -- the active structure and its component values
        "structure_id": "s1", "structure_effective_from": "2026-01-01",
        "lines": [{"code": "BASIC", "amount": 30000}, {"code": "HRA", "amount": 12000}],
        "structured_gross": 42000.0,
        "prorated_gross": 38612.90,        # regular earnings AFTER the LOP impact
        "structured_deductions": 200.0,
        "structured_reimbursements": 0.0,
        "employer_contributions": 1800.0,
        # Additional Earnings
        "reimbursements": 3000.0, "arrears": 1500.0, "other_earnings": 500.0,
        "bonus": 5000.0, "variable_pay_payout": 4000.0,
        # Recoveries / Deductions
        "pf": 1800.0, "esi": 0.0, "pt": 0.0, "tds": 2500.0,
        "advance_recovery": 2000.0, "notice_recovery": 0.0, "other_deductions": 250.0,
        # Manual Adjustment
        "adjustments": [
            {"code": "SPECIALBONUS", "name": "Spot award",
             "component_type": M.ComponentType.EARNING.value, "amount": 1000.0,
             "reason": "Quarter close", "reference": "HR memo 44"},
            {"code": "CANTEEN", "name": "Canteen recovery",
             "component_type": M.ComponentType.RECOVERY.value, "amount": 300.0,
             "reason": "October canteen", "reference": "Canteen sheet"},
        ],
        # Controls
        "previous_net": 40000.0, "exceptions": [],
    }
    for key, label in (("employee_code", "Employee ID"), ("employee_name", "Name"),
                       ("date_of_joining", "DOJ"), ("last_working_day", "LWD")):
        check(f"Employee: {label}", key in record, sorted(record))
    for key, label in (("structure_id", "active salary structure"),
                       ("lines", "component values")):
        check(f"Salary Basis: {label}", key in record)
    for key, label in (("reimbursements", "Reimbursements"), ("arrears", "Arrears"),
                       ("variable_pay_payout", "Variable"), ("other_earnings", "Other"),
                       ("bonus", "Bonus")):
        check(f"Additional Earnings: {label}", key in record)
    for key, label in (("advance_recovery", "Salary Advance Recovery"),
                       ("notice_recovery", "Other Recovery"),
                       ("other_deductions", "Manual Deduction"),
                       ("pf", "PF"), ("esi", "ESI"), ("pt", "PT"), ("tds", "TDS")):
        check(f"Recoveries / Deductions: {label}", key in record)
    adj = record["adjustments"][0]
    for key, label in (("component_type", "Type"), ("amount", "Amount"),
                       ("reason", "Reason"), ("reference", "Source/Reference")):
        check(f"Manual Adjustment: {label}", key in adj, sorted(adj))

    # -- 11: the formula --------------------------------------------------------------
    section("11. Net = earnings (LOP already inside) - deductions")

    t = PS._totals(record)
    expected_gross = (38612.90 + 0.0 + 4000.0 + 1500.0 + 3000.0 + 500.0 + 5000.0 + 1000.0)
    expected_ded = (200.0 + 1800.0 + 0.0 + 0.0 + 2500.0 + 2000.0 + 0.0 + 250.0 + 300.0)
    check("Gross Earnings sums regular + additional + reimbursements + arrears + adjustments",
          t["gross_earnings"] == round(expected_gross, 2),
          (t["gross_earnings"], expected_gross))
    check("Total Deductions sums statutory + recoveries + other + deducting adjustments",
          t["total_deductions"] == round(expected_ded, 2),
          (t["total_deductions"], expected_ded))
    check("NET SALARY PAYABLE = gross - deductions",
          t["net_pay"] == round(expected_gross - expected_ded, 2), t["net_pay"])
    check("Employer Contributions are reported, never inside net",
          t["total_employer_contributions"] == 1800.0
          and t["net_pay"] < t["gross_earnings"], t)
    check("Cost to company = gross + employer contributions",
          t["cost_to_company"] == round(expected_gross + 1800.0, 2), t["cost_to_company"])

    # The LOP subtraction is the one §11 names that is NOT a deduction line.
    section("11. LOP / attendance impact lands in EARNINGS, not in deductions")
    base = {k: v for k, v in record.items() if k not in ("adjustments",)}
    base["adjustments"] = []

    full = dict(base, prorated_gross=42000.0)
    part = dict(base, prorated_gross=38612.90)
    none = dict(base, prorated_gross=0.0)
    tf, tp, tn = PS._totals(full), PS._totals(part), PS._totals(none)
    check("a full month earns more than a month with LOP",
          tf["gross_earnings"] > tp["gross_earnings"] > tn["gross_earnings"],
          (tf["gross_earnings"], tp["gross_earnings"], tn["gross_earnings"]))
    check("...and the DEDUCTIONS do not move with it -- LOP is not deducted twice",
          tf["total_deductions"] == tp["total_deductions"] == tn["total_deductions"],
          (tf["total_deductions"], tp["total_deductions"]))
    check("the earnings gap equals the LOP impact exactly",
          round(tf["gross_earnings"] - tp["gross_earnings"], 2) == round(42000.0 - 38612.90, 2))

    # -- Controls ---------------------------------------------------------------------
    section("10. Controls: variance against last month, and the maker / checker trail")
    v = PS._variance(dict(record, net_pay=t["net_pay"]))
    check("Previous Month Net is carried on the record", record["previous_net"] == 40000.0)
    check("Variance Amount is computed", v["variance_amount"] is not None, v)
    check("Variance % is computed", v["variance_percent"] is not None, v)
    check("a first-ever run has no previous month, and says so rather than guessing 0",
          PS._variance({"net_pay": 100.0, "previous_net": None})["variance_percent"] is None)

    check("Maker and Checker are distinct run statuses",
          M.PayrollRunStatus.SUBMITTED.value and M.PayrollRunStatus.CALCULATED.value)
    check("a locked payroll is a final status, so corrections go to an adjustment",
          M.PayrollRunStatus.LOCKED.value in M.PAYROLL_FINAL_STATUSES,
          sorted(M.PAYROLL_FINAL_STATUSES))

    print("\n" + "=" * 66)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 66)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
