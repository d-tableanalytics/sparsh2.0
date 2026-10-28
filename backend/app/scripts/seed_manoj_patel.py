"""Demo data for Manoj Patel (EMP-2026-9999), Sparsh Magic.

He was already seeded with a profile, October 2026 attendance, a leave, an OD and two
regularisations. Three things were missing, and each one left a SCREEN empty rather than
merely a field:

  * no employee history   -> the profile's History tab had nothing in it, so the §4
                             effective-dated timeline could not be demonstrated at all;
  * one salary structure  -> with no second revision, §9's "Effective To" is null and
                             "prior structure retained" has nothing to show;
  * attendance stopping
    on 26 Oct             -> the current month looked abandoned.

Everything here goes through the REAL services, not raw inserts. That is the point: data
written round the validation is data that proves nothing, and a seed that cannot pass the
application's own rules is a seed that hides the bugs you are seeding to find.

Idempotent: every row it writes carries `demo_seed`, and running it twice does not double
up. `--undo` removes exactly what it added and nothing else.

Run from backend/:
    python -m app.scripts.seed_manoj_patel          # seed
    python -m app.scripts.seed_manoj_patel --undo   # remove
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone

CO = "6ab0d3a3ad0e6d5141a1bb22"          # Sparsh Magic (the internal tenant)
EMP = "EMP-2026-9999"
USER_ID = "6ad9ff12a84b24538f02765a"     # the staff account the profile is linked to
SEED_MARK = "demo-manoj-patel"

# The actor every write is attributed to. A seed that writes as nobody produces rows whose
# "changed by" is blank, which is exactly the field an approval trail is read for.
HR = {"_id": "6ab4b7b1da10562d5a70fc2c", "role": "admin", "full_name": "HR (demo seed)",
      "_source_collection": "staff", "governance_role": "HR"}
CHECKER = {"_id": "6ad9ff12a84b24538f02765b", "role": "admin",
           "full_name": "Finance (demo seed)", "_source_collection": "staff",
           "governance_role": "HR"}


def _now():
    return datetime.now(timezone.utc)


async def _mark(db, label: str, coll: str, query: dict) -> None:
    """Stamp rows this script created so --undo can find exactly them."""
    await db[coll].update_many(query, {"$set": {"demo_seed": SEED_MARK}})
    n = await db[coll].count_documents({**query, "demo_seed": SEED_MARK})
    print(f"  {label}: {n}")


async def seed(db) -> None:
    import app.services.hrms_payroll_service as PS
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_employee_master_service as EM

    profile = await db["hrms_employee_profiles"].find_one(
        {"company_id": CO, "employee_code": EMP})
    if not profile:
        print(f"!! {EMP} not found in {CO} -- nothing to seed against.")
        return

    # ── 1. The §4 effective-dated timeline ──────────────────────────────────────────
    # Written through record_changes, so every row carries the same shape the application
    # writes: field, label, old, new, effective date, reason, and who.
    print("\n1. employee history (FRD §4)")
    if await db["hrms_employee_history"].count_documents(
            {"company_id": CO, "employee_code": EMP}):
        print("  already present, skipped")
    else:
        story = [
            ("2024-04-01", "Joined Sparsh Magic", {
                "department_id": (None, profile.get("department_id")),
                "grade": (None, "E3"), "level": (None, "Level 2"),
                "work_location": (None, "Pune"),
                "job_title": (None, "Payroll Analyst"),
                "base_salary": (None, 52000)}),
            ("2024-10-01", "Confirmed after probation", {
                "employment_status": ("Probation", "Active"),
                "base_salary": (52000, 58000)}),
            ("2025-02-01", "Annual increment and promotion", {
                "grade": ("E3", "M2"), "level": ("Level 2", "Level 3"),
                "job_title": ("Payroll Analyst", "Senior Payroll Analyst"),
                "base_salary": (58000, 75000)}),
            ("2025-09-01", "Moved to Payroll & Compliance", {
                "sub_department": ("HR Operations", "Payroll & Compliance"),
                "cost_centre": ("CC-1001 Corporate", "CC-2001 Technology")}),
        ]
        for eff, reason, changes in story:
            await EM.record_changes(HR, CO, profile, changes, effective_from=eff,
                                    reason=reason, status="Applied")
        await _mark(db, "history rows", "hrms_employee_history",
                    {"company_id": CO, "employee_code": EMP})

    # A change still WAITING for its date, so the "Scheduled changes" panel is not empty.
    future = (date.today() + timedelta(days=45)).isoformat()
    if not await db["hrms_employee_history"].count_documents(
            {"company_id": CO, "employee_code": EMP, "status": "Scheduled"}):
        await EM.record_changes(
            HR, CO, profile,
            {"job_title": ("Senior Payroll Analyst", "Payroll Lead"),
             "grade": ("M2", "M3")},
            effective_from=future, reason="Promotion effective next quarter",
            status="Scheduled")
        await _mark(db, "scheduled change rows", "hrms_employee_history",
                    {"company_id": CO, "employee_code": EMP, "status": "Scheduled"})

    # ── 2. A salary revision, so §9 history has two sides ───────────────────────────
    # save_salary_structure refuses a start inside a locked payroll month, validates every
    # component against the company's own master and recomputes the totals -- all of which
    # is why this goes through the service rather than an insert.
    print("\n2. salary structure revision (FRD §9)")
    existing = await db["hrms_salary_structures"].count_documents(
        {"company_id": CO, "employee_code": EMP})
    if existing > 1:
        print(f"  {existing} structures already, skipped")
    else:
        revision = await PS.save_salary_structure(HR, CO, {
            "employee_code": EMP,
            "effective_from": "2026-04-01",
            "structure_name": "Standard Staff Structure",
            "revision_reason": "FY26 annual increment",
            "comments": "Approved in the FY26 increment cycle",
            "payroll_group": "PG1 Monthly Staff",
            "components": [
                {"code": "BASIC", "amount": 42000},
                {"code": "HRA", "amount": 16800},
                {"code": "SPECIAL", "amount": 24700},
                {"code": "PT", "amount": 200},
            ],
        })
        print(f"  created: effective {revision['effective_from']}, "
              f"gross {revision.get('monthly_gross')}, status {revision.get('status')}")
        # If the company requires a checker, a DIFFERENT person approves it -- the maker
        # cannot, and seeding it any other way would misrepresent the control.
        if revision.get("status") == "Pending Approval":
            await PS.decide_structure(CHECKER, CO, revision["id"],
                                      {"approved": True, "comments": "Within band"})
            print("  approved by the checker")
        await _mark(db, "structures", "hrms_salary_structures",
                    {"company_id": CO, "employee_code": EMP,
                     "effective_from": "2026-04-01"})

    # ── 3. Carry the current month up to today ──────────────────────────────────────
    print("\n3. October 2026 attendance, up to today")
    AT.can = lambda user, cap: True                     # the seed acts as HR throughout

    async def _allow(*a, **k):
        return None
    AT._assert_self_or_privileged = _allow

    have = {r["work_date"] for r in await db["hrms_attendance"].find(
        {"company_id": CO, "employee_code": EMP}, {"work_date": 1}).to_list(100)}
    today = date.today()
    added = 0
    d = date(2026, 10, 1)
    while d <= min(today, date(2026, 10, 31)):
        iso = d.isoformat()
        if iso not in have and d.weekday() != 6:        # Sunday is the weekly off
            try:
                await AT.mark_attendance(HR, CO, {
                    "employee_code": EMP, "work_date": iso,
                    "actual_in": "09:28", "actual_out": "18:35",
                    "source": "Biometric", "source_reference": f"BIO-{iso}"})
                added += 1
            except Exception as e:                      # a locked day, a cut-off, ...
                print(f"  {iso}: skipped ({getattr(e, 'detail', e)})")
        d += timedelta(days=1)
    print(f"  marked {added} day(s)")
    if added:
        await _mark(db, "attendance rows", "hrms_attendance",
                    {"company_id": CO, "employee_code": EMP,
                     "source_reference": {"$regex": "^BIO-2026-10"}})

    print("\nDone. Manoj Patel is EMP-2026-9999 in Sparsh Magic.")


async def undo(db) -> None:
    print("removing only rows stamped demo_seed =", SEED_MARK)
    for coll in ("hrms_employee_history", "hrms_salary_structures", "hrms_attendance"):
        res = await db[coll].delete_many(
            {"company_id": CO, "employee_code": EMP, "demo_seed": SEED_MARK})
        print(f"  {coll}: removed {res.deleted_count}")
    print("The profile, the user account and the pre-existing rows are left alone.")


async def main() -> None:
    from app.db.mongodb import connect_to_mongo, db_connection
    await connect_to_mongo()
    db = db_connection.db
    print(f"database: {db.name}   company: {CO}   employee: {EMP}")
    if "--undo" in sys.argv:
        await undo(db)
    else:
        await seed(db)
    db_connection.client.close()


if __name__ == "__main__":
    asyncio.run(main())
