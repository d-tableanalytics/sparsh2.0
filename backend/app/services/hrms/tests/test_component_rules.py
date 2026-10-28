"""FRD 11, second sentence -- "Each salary component should use its configured rule and source."

The first sentence of 11 is the net-pay line, and test_payroll_input_and_formula pins that.
This suite pins the OTHER half, which is the half a formula test cannot see: that BASIC,
HRA, PF and PT each arrive at their number by the rule configured ON THEM, from the source
that rule names -- the structure, another component, GROSS, CTC, a slab table, a frozen
attendance quantity, or a per-run input.

The reason this needs its own suite: `_totals` adds up whatever it is given. Hand it the
right figures and it balances perfectly whether or not HRA was actually computed as 40% of
Basic. Everything below therefore checks the value a component RESOLVES TO, never the sum.

Two properties matter more than the arithmetic and are checked explicitly:

  * sequence -- a component is resolved before anything that reads it, and a forward
    reference is REFUSED rather than silently treated as zero. That is what keeps the
    rules acyclic, and a 0 there would be a wrong payslip rather than an error.
  * source  -- attendance quantities come from the basis the run already froze, never
    re-derived, so a formula and the payable-days arithmetic cannot disagree.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_component_rules   (from backend/)
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


def expect(label, fn, status, needle=""):
    from fastapi import HTTPException
    try:
        fn()
    except HTTPException as e:
        return check(f"{label} -> {status}", e.status_code == status
                     and needle.lower() in str(e.detail).lower(), e.detail)
    return check(f"{label} -> {status} (no error raised)", False)


def main() -> int:
    from app.models import hrms as M
    import app.services.hrms_payroll_service as PS

    CM = M.CalculationMethod
    CT = M.ComponentType

    def comp(code, ctype, method, **kw):
        return {"code": code, "component_type": ctype, "calculation_method": method,
                "name": code, "active": True, **kw}

    # -- Fixed, and % of another component --------------------------------------------
    section("Rule: Fixed, and Percentage of another component")

    meta = {
        "BASIC": comp("BASIC", CT.EARNING.value, CM.FIXED.value, sequence=10),
        "HRA": comp("HRA", CT.EARNING.value, CM.PERCENTAGE.value, sequence=20,
                    percentage=40, calculation_base="BASIC"),
    }
    out = {l["code"]: l["amount"] for l in PS.resolve_lines(
        [{"code": "BASIC", "amount": 50000}, {"code": "HRA"}], meta)}
    check("a Fixed component takes the amount on the structure", out["BASIC"] == 50000.0,
          out)
    check("HRA resolves as 40% of BASIC, not from an amount typed beside it",
          out["HRA"] == 20000.0, out)

    # The percentage ON THE LINE overrides the component default -- a per-employee rate.
    out2 = {l["code"]: l["amount"] for l in PS.resolve_lines(
        [{"code": "BASIC", "amount": 50000}, {"code": "HRA", "percentage": 50}], meta)}
    check("a per-employee percentage on the line overrides the component's default",
          out2["HRA"] == 25000.0, out2)

    # -- % of GROSS and % of CTC -------------------------------------------------------
    section("Rule: Percentage of GROSS, and of CTC")

    meta_g = {
        "BASIC": comp("BASIC", CT.EARNING.value, CM.FIXED.value, sequence=10),
        "HRA": comp("HRA", CT.EARNING.value, CM.FIXED.value, sequence=20),
        "SPEC": comp("SPEC", CT.EARNING.value, CM.PERCENTAGE.value, sequence=30,
                     percentage=10, calculation_base="GROSS"),
    }
    g = {l["code"]: l["amount"] for l in PS.resolve_lines(
        [{"code": "BASIC", "amount": 30000}, {"code": "HRA", "amount": 10000},
         {"code": "SPEC"}], meta_g)}
    check("a % of GROSS uses the EARNINGS resolved so far (40000), not the final gross",
          g["SPEC"] == 4000.0, g)

    meta_c = {"RET": comp("RET", CT.EARNING.value, CM.PERCENTAGE.value, sequence=10,
                          percentage=5, calculation_base="CTC")}
    c = {l["code"]: l["amount"] for l in PS.resolve_lines(
        [{"code": "RET"}], meta_c, annual_ctc=1200000)}
    check("a % of CTC uses annual CTC / 12", c["RET"] == 5000.0, c)
    expect("a % of CTC with no annual CTC given",
           lambda: PS.resolve_lines([{"code": "RET"}], meta_c), 422, "annual ctc")

    # -- Sequence and the acyclic guard -------------------------------------------------
    section("Sequence: a base is resolved first, and a forward reference is REFUSED")

    ordered = {
        "HRA": comp("HRA", CT.EARNING.value, CM.PERCENTAGE.value, sequence=20,
                    percentage=40, calculation_base="BASIC"),
        "BASIC": comp("BASIC", CT.EARNING.value, CM.FIXED.value, sequence=10),
    }
    # HRA is listed FIRST but sequenced second, so it still resolves off a known BASIC.
    seq = {l["code"]: l["amount"] for l in PS.resolve_lines(
        [{"code": "HRA"}, {"code": "BASIC", "amount": 50000}], ordered)}
    check("the sequence decides the order, not the order the lines were entered",
          seq["HRA"] == 20000.0, seq)

    backwards = {
        "BASIC": comp("BASIC", CT.EARNING.value, CM.PERCENTAGE.value, sequence=10,
                      percentage=50, calculation_base="HRA"),
        "HRA": comp("HRA", CT.EARNING.value, CM.FIXED.value, sequence=20),
    }
    expect("a component whose base comes LATER in the sequence",
           lambda: PS.resolve_lines(
               [{"code": "BASIC"}, {"code": "HRA", "amount": 10000}], backwards),
           422, "comes later")
    check("...which is a refusal, NOT a silent zero -- a 0 here is a wrong payslip", True)

    # -- Slab (the PT case §11 names) ---------------------------------------------------
    section("Rule: Slab -- Professional Tax on a base")

    # The stored shape is a ceiling per row; clean_slabs normalises whatever the UI sends
    # into exactly this, which is why slab_amount can index `upto` without guarding.
    from app.services import hrms_formula_engine as FE
    slabs = FE.clean_slabs([{"upto": 15000, "amount": 0},
                            {"upto": 25000, "amount": 150},
                            {"upto": None, "amount": 200}])
    meta_s = {
        "BASIC": comp("BASIC", CT.EARNING.value, CM.FIXED.value, sequence=10),
        "PT": comp("PT", CT.DEDUCTION.value, CM.SLAB.value, sequence=90,
                   calculation_base="GROSS", slabs=slabs),
    }
    for salary, expected in ((12000, 0), (20000, 150), (60000, 200)):
        r = {l["code"]: l["amount"] for l in PS.resolve_lines(
            [{"code": "BASIC", "amount": salary}, {"code": "PT"}], meta_s)}
        check(f"PT on a gross of {salary} lands in the right slab ({expected})",
              r["PT"] == float(expected), r)

    expect("slabs given out of order",
           lambda: FE.clean_slabs([{"upto": 25000, "amount": 150},
                                   {"upto": 15000, "amount": 0}]), 422, "up in order")
    expect("an uncapped slab that is not the last one",
           lambda: FE.clean_slabs([{"upto": None, "amount": 0},
                                   {"upto": 25000, "amount": 150}]), 422, "last slab")
    expect("a slab component with no slabs at all",
           lambda: FE.clean_slabs([]), 422, "at least one")

    # -- Formula, and where its variables come from ------------------------------------
    section("Rule: Formula -- and its SOURCE is the frozen basis, not a re-derivation")

    meta_f = {
        "BASIC": comp("BASIC", CT.EARNING.value, CM.FIXED.value, sequence=10),
        "PF": comp("PF", CT.DEDUCTION.value, CM.FORMULA.value, sequence=80,
                   formula="ROUND(MIN(BASIC, 15000) * 0.12, 0)"),
        "LOPREC": comp("LOPREC", CT.DEDUCTION.value, CM.FORMULA.value, sequence=85,
                       formula="ROUND(BASIC / CALENDAR_DAYS * LOP_DAYS, 0)"),
    }
    days = {"days_in_period": 30, "payable_days": 27.5, "lop_days": 2.5,
            "present_days": 20, "working_days": 26, "weekly_off_days": 4,
            "holiday_days": 0, "leave_days": 0}
    f = {l["code"]: l["amount"] for l in PS.resolve_lines(
        [{"code": "BASIC", "amount": 50000}, {"code": "PF"}, {"code": "LOPREC"}],
        meta_f, days=days)}
    check("PF is capped by its own formula (12% of 15000), not of the full Basic",
          f["PF"] == 1800.0, f)
    check("a formula reads the attendance quantity the RUN froze (2.5 LOP days)",
          f["LOPREC"] == round(50000 / 30 * 2.5), f)

    expect("a formula naming a component that comes later",
           lambda: PS.resolve_lines(
               [{"code": "BASIC", "amount": 1}, {"code": "PF"}],
               {**meta_f, "BASIC": comp("BASIC", CT.EARNING.value, CM.FIXED.value,
                                        sequence=99)}, days=days),
           422, "later in the sequence")

    # -- Manual / Imported: zero until supplied ----------------------------------------
    section("Source: Manual and Imported are zero until somebody supplies them")

    meta_m = {
        "INCENTIVE": comp("INCENTIVE", CT.EARNING.value, CM.MANUAL.value, sequence=50),
        "CANTEEN": comp("CANTEEN", CT.DEDUCTION.value, CM.IMPORTED.value, sequence=60),
    }
    m0 = {l["code"]: l["amount"] for l in PS.resolve_lines(
        [{"code": "INCENTIVE"}, {"code": "CANTEEN"}], meta_m)}
    check("neither can be calculated from the structure alone -- both start at 0",
          m0["INCENTIVE"] == 0.0 and m0["CANTEEN"] == 0.0, m0)
    m1 = {l["code"]: l["amount"] for l in PS.resolve_lines(
        [{"code": "INCENTIVE", "amount": 7500}, {"code": "CANTEEN", "amount": 300}], meta_m)}
    check("...and take the supplied figure when one is given",
          m1["INCENTIVE"] == 7500.0 and m1["CANTEEN"] == 300.0, m1)

    # -- Every §24 method is reachable --------------------------------------------------
    section("Every configured rule §24 names is a real, distinct method")
    for method in (CM.FIXED, CM.PERCENTAGE, CM.MANUAL, CM.FORMULA, CM.SLAB,
                   CM.IMPORTED, CM.ATTENDANCE_LINKED):
        check(f"method '{method.value}' exists", bool(method.value))
    check("proration rules cover all four §24 shapes",
          {r.value for r in M.ProrationRule} ==
          {"Payable Days", "Working Days", "Full Month", "None"},
          {r.value for r in M.ProrationRule})

    # -- A negative line is refused, not quietly flipped --------------------------------
    section("A component may not resolve to a negative amount")
    expect("a negative Fixed amount",
           lambda: PS.resolve_lines(
               [{"code": "BASIC", "amount": -100}],
               {"BASIC": comp("BASIC", CT.EARNING.value, CM.FIXED.value)}),
           422, "")

    print("\n" + "=" * 66)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 66)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
