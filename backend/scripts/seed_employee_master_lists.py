"""Seed the twelve Employee Master dropdown lists for one company (FRD §3, §21-22).

Every one of these lists ships EMPTY, and an empty list makes its field degrade to free
text -- which is why a fresh company's profile screen reads "No list configured — free
text" on Grade, Payroll group, Location and nine others. The product works that way on
purpose (an empty dropdown you cannot get past is worse than a text box), but it makes a
demo look unfinished and lets two people type "Bangalore" and "Bengaluru" into the same
field.

This fills them with a realistic starter set. The values are SAMPLES to be renamed, not a
recommendation: a company's legal entities and cost centres are its own.

-- It drives the real service ---------------------------------------------------------
`save_master_lists` is called rather than the settings document being written directly, so
the values go through the same de-duplication, trimming, 120-character truncation and
MAX_LIST_VALUES cap the screen enforces, and the change is audited like any other.

-- It ADDS; it never replaces ---------------------------------------------------------
`save_master_lists` replaces a list wholesale, so this script reads what is there first and
appends only the values that are missing. A company that has already typed its own payroll
groups keeps them, and re-running the script changes nothing the second time.

-- Undo removes only what it added ----------------------------------------------------
There is nowhere to stamp a marker on an individual list value, so the script records what
it actually added under `employee_master_seed` on the settings document. `--undo` reads
that record and removes exactly those values, leaving anything typed by hand -- including a
sample value somebody has since edited, because an edited value is no longer one of ours.

-- Two lists are deliberately absent ---------------------------------------------------
`shifts` is read-only here: it comes from the shift master under Attendance > Shifts, not
from a free list, and `get_master_lists` injects it. Departments and designations are their
own collections with their own screens, not master-list keys.

Usage (from backend/):
    python scripts/seed_employee_master_lists.py --company <company_id> --dry-run
    python scripts/seed_employee_master_lists.py --company <company_id>
    python scripts/seed_employee_master_lists.py --company <company_id> --undo
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

import app.db.mongodb as mongo                                        # noqa: E402
from scripts.seed_hrms_recruitment_demo import connect, log           # noqa: E402

MARKER = "employee-master-lists"

# ── The sample values ───────────────────────────────────────────────────────────────
#
# Two of these lists are shaped by something other than taste, and changing them casually
# will break a feature:
#
#   * GRADES, LEVELS and PAYROLL GROUPS carry a NUMBER. The formula engine's EMP_GRADE,
#     EMP_LEVEL and EMP_PAYROLL_GROUP variables are numeric -- `_numeric_suffix` pulls the
#     digits out of a code and yields 0.0 when there are none (hrms_formula_engine.py).
#     A grade called "Senior Manager" is therefore 0 to every formula, and so is "A".
#     Codes that carry their rank are what make `EMP_GRADE >= 3` mean anything.
#   * EMPLOYEE CATEGORIES are an OPEN CLIENT DECISION (§19 decision 1: "final list and
#     applicability"). These are the conventional Indian set as a placeholder; they are the
#     one list here that should be confirmed before anybody relies on it, because §24
#     component applicability is scoped by category.
SAMPLES: dict[str, list[str]] = {
    "legal_entities": [
        "Sparsh Magic Pvt Ltd",
        "Sparsh Magic Technologies LLP",
    ],
    "business_units": [
        "Corporate", "Technology Services", "Operations", "Field Sales",
    ],
    "locations": [
        "Pune", "Mumbai", "Bengaluru", "Hyderabad", "Delhi NCR", "Chennai",
        "Remote (India)",
    ],
    "sub_departments": [
        "Talent Acquisition", "HR Operations", "Payroll & Compliance",
        "Accounts Payable", "Quality Assurance", "Customer Support",
        "Inside Sales", "Infrastructure",
    ],
    # E = individual contributor, M = people manager, D = leadership. The digit is the rank.
    "grades": [
        "E1", "E2", "E3", "M1", "M2", "M3", "D1",
    ],
    "levels": [
        "Level 1", "Level 2", "Level 3", "Level 4", "Level 5",
    ],
    "cost_centres": [
        "CC-1001 Corporate", "CC-2001 Technology", "CC-3001 Operations",
        "CC-4001 Sales & Marketing", "CC-5001 Plant",
    ],
    # §19 decision 1 is OPEN -- confirm with the client before relying on these.
    "employee_categories": [
        "Staff", "Worker", "Trainee", "Apprentice", "Contract", "Consultant",
    ],
    # The digit matters: EMP_PAYROLL_GROUP is numeric. See the note above.
    "payroll_groups": [
        "PG1 Monthly Staff", "PG2 Monthly Workers", "PG3 Trainees & Apprentices",
        "PG4 Contract & Consultants",
    ],
    # A NAME only. This list does not define components -- it fills in the structure's
    # title when one is saved (hrms_payroll_service.save_salary_structure). Components are
    # still keyed per employee on the Salary tab.
    "salary_templates": [
        "Standard Staff Structure", "Worker Structure", "Trainee Stipend",
        "Consultant Retainer",
    ],
    "attendance_policy_groups": [
        "General Shift", "Rotational Shift", "Field Staff", "Hybrid",
    ],
    "holiday_calendars": [
        "National Holidays", "Maharashtra", "Karnataka", "Delhi NCR", "Tamil Nadu",
    ],
}

SETTINGS = "hrms_settings"
SEED_FIELD = "employee_master_seed"

# The script acts as a system actor. It changes no account and grants nobody anything; the
# audit row records a seed rather than attributing the change to a colleague who was not
# at their desk.
ACTOR = {"_id": None, "full_name": f"Seed script ({MARKER})", "role": "system"}


async def _record(company_id: str, added: dict) -> None:
    await mongo.get_collection(SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {SEED_FIELD: {"marker": MARKER, "added": added,
                               "at": datetime.now(timezone.utc)}}},
        upsert=True)


async def _seeded(company_id: str) -> dict:
    doc = await mongo.get_collection(SETTINGS).find_one({"company_id": str(company_id)})
    record = (doc or {}).get(SEED_FIELD) or {}
    return record.get("added") or {} if record.get("marker") == MARKER else {}


async def seed(company_id: str, dry_run: bool) -> None:
    from app.services.hrms_employee_master_service import (
        get_master_lists, save_master_lists)

    current = await get_master_lists(company_id)
    additions, merged = {}, {}
    for key, samples in SAMPLES.items():
        existing = list(current.get(key) or [])
        lower = {v.strip().lower() for v in existing}
        new = [v for v in samples if v.lower() not in lower]
        if new:
            additions[key] = new
            merged[key] = existing + new

    if not additions:
        log("Every sample value is already present — nothing to add.")
        return

    width = max(len(k) for k in additions)
    for key, new in additions.items():
        log(f"{key.ljust(width)}  + {len(new):2d}  {', '.join(new)}")
    total = sum(len(v) for v in additions.values())
    log(f"{total} value(s) across {len(additions)} list(s).")

    if dry_run:
        log("Dry run — nothing written.")
        return

    await save_master_lists(ACTOR, company_id, {"lists": merged})
    # Merge the record, so two runs that each add something are both undoable.
    previous = await _seeded(company_id)
    for key, new in additions.items():
        previous[key] = list(previous.get(key) or []) + new
    await _record(company_id, previous)
    log(f"Written. Undo with: --company {company_id} --undo")


async def undo(company_id: str, dry_run: bool) -> None:
    from app.services.hrms_employee_master_service import (
        get_master_lists, save_master_lists)

    added = await _seeded(company_id)
    if not added:
        log("No record of a seed on this company — nothing to undo.")
        return

    current = await get_master_lists(company_id)
    merged, removed = {}, 0
    for key, seeded in added.items():
        lower = {v.strip().lower() for v in seeded}
        existing = list(current.get(key) or [])
        keep = [v for v in existing if v.strip().lower() not in lower]
        if len(keep) != len(existing):
            merged[key] = keep
            removed += len(existing) - len(keep)
            log(f"{key}  - {len(existing) - len(keep)}")

    if not removed:
        log("The seeded values are already gone — nothing to remove.")
    elif dry_run:
        log(f"Dry run — {removed} value(s) would be removed.")
        return
    else:
        await save_master_lists(ACTOR, company_id, {"lists": merged})
        log(f"Removed {removed} seeded value(s); anything typed by hand was left alone.")

    if not dry_run:
        await mongo.get_collection(SETTINGS).update_one(
            {"company_id": str(company_id)}, {"$unset": {SEED_FIELD: ""}})


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True, help="company_id to seed")
    parser.add_argument("--undo", action="store_true",
                        help="remove the values this script added, and nothing else")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change and write nothing")
    args = parser.parse_args()

    client = await connect()
    try:
        log(f"Company {args.company}")
        if args.undo:
            await undo(args.company, args.dry_run)
        else:
            await seed(args.company, args.dry_run)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
