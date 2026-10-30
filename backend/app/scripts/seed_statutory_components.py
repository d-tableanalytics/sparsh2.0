"""A STARTER catalogue of the statutory components most Indian employers run (FRD §19.6).

-- Why this is a script you run, and not a default -------------------------------------
Every other §19 default in this system is a safe one: off, empty, or today's behaviour.
Statutory deductions cannot be defaulted that way, because there is no safe wrong answer.
A silent default here would mean PF appearing on a payslip at a rate nobody chose, for a
company that may not be covered by the Act at all, computed against a ceiling that
Parliament can change without telling us.

So this is OPT-IN and VISIBLE: it prints exactly what it will create, writes nothing
without `--apply`, and leaves every figure editable afterwards in Salary Components. The
company applies it, sees it, and owns it.

-- What this is NOT --------------------------------------------------------------------
It is not compliance advice, and the figures below are a STARTING POINT to be confirmed
against current law and against the company's own registration status before any real
payroll runs. Specifically:

  * the PF wage ceiling, the ESI rates and the ESI gross limit all change by notification;
  * PT is a STATE tax -- the slab here is Maharashtra's shape, and is wrong for Karnataka,
    West Bengal, Telangana and the rest. `--state` is deliberately required so nobody
    applies one state's slab to another by accident;
  * TDS is NOT included, and that is on purpose. It depends on the employee's regime
    choice, declarations, exemptions and projected annual income -- there is no rate to
    default. It stays a per-employee monthly input until the payroll workshop decides how
    it will be computed.

-- Why formulas rather than fixed amounts ----------------------------------------------
Each component carries its RULE, not a number, so it reprices itself when Basic changes
and so an auditor can read why a figure is what it is (FRD §11 "each component uses its
configured rule and source").

Run from backend/:
    python -m app.scripts.seed_statutory_components --company <id> --state MH
    python -m app.scripts.seed_statutory_components --company <id> --state MH --apply
    python -m app.scripts.seed_statutory_components --company <id> --undo
"""
from __future__ import annotations

import asyncio
import sys

SEED_MARK = "statutory-starter"

# Figures a reviewer must confirm. Named here rather than inlined so the whole list of
# "numbers somebody has to check" is in one place.
PF_WAGE_CEILING = 15000      # EPF: contribution computed on Basic capped at this
PF_RATE = 12                 # per cent, employee and employer alike
ESI_GROSS_LIMIT = 21000      # ESI applies only while monthly gross is at or below this
ESI_EMPLOYEE_RATE = 0.75     # per cent
ESI_EMPLOYER_RATE = 3.25     # per cent

# PT is a state tax. Each entry is the slab shape that state uses, as `upto` ceilings on
# monthly gross. ONLY add a state here with its actual notified slabs.
PT_SLABS = {
    "MH": [  # Maharashtra
        {"upto": 7500, "amount": 0},
        {"upto": 10000, "amount": 175},
        {"upto": None, "amount": 200},
    ],
    "KA": [  # Karnataka
        {"upto": 24999, "amount": 0},
        {"upto": None, "amount": 200},
    ],
}


def catalogue(state: str) -> list:
    """The components, in the sequence payroll resolves them.

    Sequence matters: PF reads BASIC, ESI reads GROSS (the earnings resolved before it),
    so both must come AFTER the earnings and ESI after nothing that it feeds. The engine
    refuses a forward reference rather than guessing, so these numbers are load-bearing.
    """
    return [
        {
            "code": "PF", "name": "Provident Fund (employee)",
            "component_type": "Deduction", "calculation_method": "Formula",
            "sequence": 80, "taxable": False,
            # 12% of Basic, with Basic capped at the statutory wage ceiling.
            "formula": f"ROUND(MIN(BASIC, {PF_WAGE_CEILING}) * {PF_RATE} / 100, 0)",
            "description": (f"{PF_RATE}% of Basic, Basic capped at {PF_WAGE_CEILING}. "
                            f"Confirm the ceiling against current EPF notification."),
        },
        {
            "code": "PF_ER", "name": "Provident Fund (employer)",
            "component_type": "Employer Contribution", "calculation_method": "Formula",
            "sequence": 81,
            "formula": f"ROUND(MIN(BASIC, {PF_WAGE_CEILING}) * {PF_RATE} / 100, 0)",
            "description": ("Employer share. Cost to company, never deducted from net. "
                            "Some employers split this between EPF and EPS -- if yours "
                            "does, replace this with two components."),
        },
        {
            "code": "ESI", "name": "Employees' State Insurance (employee)",
            "component_type": "Deduction", "calculation_method": "Formula",
            "sequence": 82, "taxable": False,
            # Applies only while gross is within the limit; zero above it.
            "formula": (f"IF(GROSS <= {ESI_GROSS_LIMIT}, "
                        f"ROUND(GROSS * {ESI_EMPLOYEE_RATE} / 100, 0), 0)"),
            "description": (f"{ESI_EMPLOYEE_RATE}% of gross, only while gross is at or "
                            f"below {ESI_GROSS_LIMIT}. Above that the formula returns 0."),
        },
        {
            "code": "ESI_ER", "name": "Employees' State Insurance (employer)",
            "component_type": "Employer Contribution", "calculation_method": "Formula",
            "sequence": 83,
            "formula": (f"IF(GROSS <= {ESI_GROSS_LIMIT}, "
                        f"ROUND(GROSS * {ESI_EMPLOYER_RATE} / 100, 0), 0)"),
            "description": f"{ESI_EMPLOYER_RATE}% of gross, same eligibility test.",
        },
        {
            "code": "PT", "name": f"Professional Tax ({state})",
            "component_type": "Deduction", "calculation_method": "Slab",
            "sequence": 90, "taxable": False,
            "calculation_base": "GROSS", "slabs": PT_SLABS[state],
            "description": (f"{state} slab on monthly gross. PT is a STATE tax -- confirm "
                            f"these slabs, and use a separate component per state if the "
                            f"company pays in more than one."),
        },
    ]


async def main() -> None:
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args else default

    company_id = opt("--company")
    state = (opt("--state") or "").upper()
    apply_it = "--apply" in args
    undo = "--undo" in args

    if not company_id:
        print("Give --company <id>.  See --help in the module docstring.")
        return
    if not undo and state not in PT_SLABS:
        print(f"Give --state, one of: {', '.join(sorted(PT_SLABS))}.\n"
              f"PT is a state tax and there is no safe default -- see the docstring.")
        return

    from app.db.mongodb import connect_to_mongo, db_connection
    await connect_to_mongo()
    db = db_connection.db
    coll = db["hrms_salary_components"]

    if undo:
        res = await coll.delete_many({"company_id": str(company_id), "demo_seed": SEED_MARK})
        print(f"Removed {res.deleted_count} component(s) this script created.")
        db_connection.client.close()
        return

    rows = catalogue(state)
    existing = {c["code"] for c in await coll.find(
        {"company_id": str(company_id)}, {"code": 1}).to_list(200)}

    print(f"\ndatabase : {db.name}\ncompany  : {company_id}\nstate    : {state}")
    print(f"mode     : {'APPLY (writing)' if apply_it else 'DRY RUN (writing nothing)'}\n")
    print(f"{'CODE':<8} {'TYPE':<24} {'RULE':<46} STATUS")
    print("-" * 104)
    todo = []
    for r in rows:
        rule = r.get("formula") or f"slab on {r.get('calculation_base')}"
        status = "already exists, left alone" if r["code"] in existing else "would create"
        if r["code"] not in existing:
            todo.append(r)
        print(f"{r['code']:<8} {r['component_type']:<24} {rule[:45]:<46} {status}")

    print("\nCONFIRM BEFORE RUNNING A REAL PAYROLL:")
    print(f"  * PF ceiling {PF_WAGE_CEILING} and rate {PF_RATE}%")
    print(f"  * ESI limit {ESI_GROSS_LIMIT}, rates {ESI_EMPLOYEE_RATE}% / {ESI_EMPLOYER_RATE}%")
    print(f"  * PT slabs for {state}, and whether the company pays PT in other states")
    print("  * whether the company is registered for EPF / ESI at all")
    print("  * TDS is NOT created here -- it stays a monthly input per employee")

    if not apply_it:
        print(f"\nDry run. {len(todo)} component(s) would be created. "
              f"Re-run with --apply to write them.")
        db_connection.client.close()
        return

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for r in todo:
        await coll.insert_one({**r, "company_id": str(company_id), "active": True,
                               "proration_rule": "None", "demo_seed": SEED_MARK,
                               "created_at": now, "updated_at": now})
    print(f"\nCreated {len(todo)} component(s). Edit them in Payroll > Salary Components; "
          f"--undo removes only what this script added.")
    db_connection.client.close()


if __name__ == "__main__":
    asyncio.run(main())
