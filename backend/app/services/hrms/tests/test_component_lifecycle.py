"""Phase 1 FRD §24/§25 -- component lifecycle, proration, frequency and formula variables.

  1. Proration: the four §24 rules, and what their DENOMINATORS do to a real month.
  2. Applicability and lifecycle: a Draft is not paid, a scope excludes, dates gate.
  3. Frequency: a quarterly component is not paid every month.
  4. Formula variables: attendance and employee fields reach a formula (§25), and a
     formula that depends on the period is re-priced per period rather than frozen at
     structure-approval time.
  5. Nothing above changes a component that configures none of it.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_component_lifecycle   (from backend/)
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
    import app.db.mongodb as mongo
    import app.services.hrms_formula_engine as FE
    import app.services.hrms_payroll_service as PR

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    PR.get_collection = getter

    # A 30-day month: 26 payable, 4 weekly offs, 22 working days.
    DAYS = {"days_in_period": 30, "payable_days": 26.0, "lop_days": 4.0,
            "present_days": 22.0, "working_days": 22, "weekly_off_days": 4,
            "holiday_days": 0, "leave_days": 0}
    RATIO = DAYS["payable_days"] / DAYS["days_in_period"]

    # ── 1. Proration ────────────────────────────────────────────────────────────────
    section("1. §24 proration — four rules, three denominators")

    r = PR._proration_ratio
    check("Payable Days divides by CALENDAR days: 26/30",
          round(r("Payable Days", DAYS, RATIO), 4) == round(26 / 30, 4))
    check("Working Days excludes offs from BOTH sides: (26-4)/22 = 1.0",
          r("Working Days", DAYS, RATIO) == 1.0)
    check("Full Month pays in full", r("Full Month", DAYS, RATIO) == 1.0)
    check("None pays in full", r("None", DAYS, RATIO) == 1.0)
    check("Working Days falls back to the payable ratio with no working-day count",
          r("Working Days", {**DAYS, "working_days": 0}, RATIO) == RATIO)

    meta = {
        "BASIC": {"code": "BASIC", "name": "Basic", "component_type": "Earning",
                  "calculation_method": "Fixed", "proration": "Payable Days"},
        "CONV": {"code": "CONV", "name": "Conveyance", "component_type": "Earning",
                 "calculation_method": "Fixed", "proration": "Working Days"},
        "LTA": {"code": "LTA", "name": "LTA", "component_type": "Earning",
                "calculation_method": "Fixed", "proration": "Full Month"},
    }
    structure = {"components": [{"code": "BASIC", "amount": 30000},
                                {"code": "CONV", "amount": 2200},
                                {"code": "LTA", "amount": 5000}]}
    lines = {l["code"]: l for l in PR._component_lines(structure, meta, RATIO, days=DAYS,
                                                       profile={}, period="2026-04",
                                                       period_end="2026-04-30")}
    check("Basic is cut by the 4 LOP days: 30,000 x 26/30 = 26,000",
          lines["BASIC"]["amount"] == 26000.0)
    check("Conveyance is NOT cut -- every working day was worked",
          lines["CONV"]["amount"] == 2200.0)
    check("LTA is paid in full regardless", lines["LTA"]["amount"] == 5000.0)

    # ── 2. Lifecycle and applicability ──────────────────────────────────────────────
    section("2. §24 lifecycle and applicability")

    applies = PR._applies_to
    check("a component with no lifecycle at all is paid (pre-§24 components)",
          applies({"code": "X"}, {}, "2026-04-30") is True)
    check("...and its `active: False` still retires it",
          applies({"code": "X", "active": False}, {}, "2026-04-30") is False)
    check("a Draft is NOT paid -- approving it would otherwise mean nothing",
          applies({"lifecycle": "Draft"}, {}, "2026-04-30") is False)
    check("an Approved-but-not-Active one is not paid either",
          applies({"lifecycle": "Approved"}, {}, "2026-04-30") is False)
    check("an Active one is paid", applies({"lifecycle": "Active"}, {}, "2026-04-30") is True)
    check("a Retired one is not", applies({"lifecycle": "Retired"}, {}, "2026-04-30") is False)
    check("a component effective next month is not paid this month",
          applies({"lifecycle": "Active", "effective_from": "2026-05-01"}, {},
                  "2026-04-30") is False)
    check("one that ended last month is not paid either",
          applies({"lifecycle": "Active", "effective_to": "2026-03-31"}, {},
                  "2026-04-30") is False)
    check("a Pune-scoped component reaches a Pune employee",
          applies({"lifecycle": "Active", "applicability": {"locations": ["Pune"]}},
                  {"work_location": "Pune"}, "2026-04-30") is True)
    check("...and not a Mumbai one",
          applies({"lifecycle": "Active", "applicability": {"locations": ["Pune"]}},
                  {"work_location": "Mumbai"}, "2026-04-30") is False)

    # ── 3. Frequency ────────────────────────────────────────────────────────────────
    section("3. §24 frequency — not everything is monthly")

    due = PR._due_this_period
    check("no frequency means monthly", due({}, "2026-04") is True)
    check("Monthly is paid every month", due({"frequency": "Monthly"}, "2026-07") is True)
    q = {"frequency": "Quarterly", "effective_from": "2026-01-15"}
    check("Quarterly pays in its anchor month", due(q, "2026-01") is True)
    check("...not the month after", due(q, "2026-02") is False)
    check("...and again three months on", due(q, "2026-04") is True)
    a = {"frequency": "Annual", "effective_from": "2026-03-01"}
    check("Annual pays once a year", due(a, "2026-03") is True and due(a, "2027-03") is True)
    check("...and not in between", due(a, "2026-09") is False)
    check("One-time is never paid automatically",
          due({"frequency": "One-time"}, "2026-04") is False)
    check("a component is not paid before its own start",
          due(q, "2025-10") is False)

    # ── 4. Formula variables (§25) ──────────────────────────────────────────────────
    section("4. §25 variables reach a formula")

    av = FE.attendance_variables(DAYS)
    check("attendance variables come off the FROZEN basis, not a re-derivation",
          av["PAYABLE_DAYS"] == 26.0 and av["LOP_DAYS"] == 4.0
          and av["CALENDAR_DAYS"] == 30.0)
    check("LOP_RATIO and PAYABLE_RATIO are derived consistently",
          round(av["LOP_RATIO"] + av["PAYABLE_RATIO"], 6) == 1.0)
    ev = FE.employee_variables({"grade": "M3", "joined_on": "2025-04-10"}, "2026-04-30")
    check("a grade resolves to its number for arithmetic", ev["EMP_GRADE"] == 3.0)
    check("service months are counted to the period end", ev["EMP_SERVICE_MONTHS"] == 12.0)

    check("a formula may now read attendance",
          FE.validate("IF(PAYABLE_DAYS < 15, 0, 1500)", {"BASIC"}) == {"PAYABLE_DAYS"})
    try:
        FE.validate("IF(MOON_PHASE > 1, 1, 0)", {"BASIC"})
        check("an unknown name is still refused", False)
    except Exception as e:
        check("an unknown name is still refused -- which is why adding variables is safe",
              "MOON_PHASE" in str(e))

    # The re-pricing rule: only a formula that reads the period is re-evaluated.
    check("a plain percentage formula is NOT period dependent",
          PR._period_dependent({"calculation_method": "Formula",
                                "formula": "BASIC * 0.4"}) is False)
    check("one reading PAYABLE_DAYS is",
          PR._period_dependent({"calculation_method": "Formula",
                                "formula": "IF(PAYABLE_DAYS < 15, 0, 1500)"}) is True)
    check("one reading an employee field is too",
          PR._period_dependent({"calculation_method": "Formula",
                                "formula": "EMP_SERVICE_MONTHS * 100"}) is True)
    check("a Fixed component never is",
          PR._period_dependent({"calculation_method": "Fixed"}) is False)

    meta2 = {**meta, "ATT": {"code": "ATT", "name": "Attendance bonus",
                             "component_type": "Earning", "calculation_method": "Formula",
                             "formula": "IF(PAYABLE_DAYS < 15, 0, 1500)",
                             "proration": "None"}}
    struct2 = {"components": [{"code": "BASIC", "amount": 30000},
                              {"code": "ATT", "amount": 0}],   # frozen at 0 when approved
               "annual_ctc": 400000}
    repriced = PR._reprice_for_period(struct2, meta2, DAYS, {}, "2026-04-30")
    att = next(c for c in repriced["components"] if c["code"] == "ATT")
    check("a formula frozen at 0 when the structure was approved is re-priced for the month",
          att["amount"] == 1500.0)
    basic = next(c for c in repriced["components"] if c["code"] == "BASIC")
    check("...and a component that does NOT depend on the period is left exactly alone",
          basic["amount"] == 30000)

    lean = PR._reprice_for_period(structure, meta, DAYS, {}, "2026-04-30")
    check("a structure with nothing period-dependent is returned untouched",
          lean is structure)

    # ── 5. Nothing moves for an unconfigured component ──────────────────────────────
    section("5. A component configuring none of this is unchanged")

    plain_meta = {"BASIC": {"code": "BASIC", "name": "Basic", "component_type": "Earning"}}
    plain = PR._component_lines({"components": [{"code": "BASIC", "amount": 30000}]},
                                plain_meta, RATIO, days=DAYS, profile={},
                                period="2026-04", period_end="2026-04-30")
    check("an earning with no proration configured still prorates by payable days",
          plain[0]["amount"] == 26000.0)
    old_style = PR._component_lines({"components": [{"code": "BASIC", "amount": 30000}]},
                                    plain_meta, RATIO)
    check("...and the pre-§24 call signature gives exactly the same answer",
          old_style[0]["amount"] == plain[0]["amount"])

    print("\n" + "=" * 60)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 60)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
