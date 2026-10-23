"""Read back the Employee Master dropdown lists, to answer "I seeded it, why is it empty?".

Reads only. Reports, for every company that has a settings document, how many values each
master list holds, which companies the seed script has stamped, and -- for a company named
with --company -- the actual values the API would return for that id.

The usual answer is that the id passed to the seed script is not the id the screen is
scoped to: the Employee Master Setup screen reads
`GET /hrms/employee-master/lists?company_id=<X>`, where X comes from the scope bar, and a
company_id is an opaque string that is easy to take from the wrong place.

Usage (from backend/):
    python scripts/check_employee_master_lists.py
    python scripts/check_employee_master_lists.py --company <company_id>
"""
from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, ".")

import app.db.mongodb as mongo                                        # noqa: E402
from scripts.seed_hrms_recruitment_demo import connect, log           # noqa: E402

SETTINGS = "hrms_settings"
SEED_FIELD = "employee_master_seed"


async def overview() -> None:
    docs = await mongo.get_collection(SETTINGS).find(
        {}, {"company_id": 1, "employee_master_lists": 1, SEED_FIELD: 1}).to_list(500)
    if not docs:
        log("No hrms_settings documents at all — nothing has been seeded anywhere.")
        return

    log(f"{len(docs)} settings document(s):")
    log("")
    log(f"  {'company_id':<28}{'type':<10}{'values':>8}  {'lists':>6}  seeded")
    for d in sorted(docs, key=lambda x: str(x.get("company_id"))):
        lists = d.get("employee_master_lists") or {}
        total = sum(len(v or []) for v in lists.values())
        filled = sum(1 for v in lists.values() if v)
        stamp = (d.get(SEED_FIELD) or {}).get("marker") or "-"
        # The TYPE is reported because it is a real failure mode: the services query
        # `{"company_id": str(company_id)}`, so a document holding an ObjectId here is
        # invisible to them and an upsert would have quietly created a second one.
        cid = d.get("company_id")
        log(f"  {str(cid):<28}{type(cid).__name__:<10}{total:>8}  {filled:>6}  {stamp}")
    log("")
    log("Compare the company_id column against the one in the browser's URL or the")
    log("scope bar. If the seeded row is not the company you are looking at, re-run the")
    log("seed script with that id.")


async def detail(company_id: str) -> None:
    from app.services.hrms_employee_master_service import get_master_lists

    # Exactly what the endpoint would return for this id -- same function, same query.
    lists = await get_master_lists(company_id)
    total = sum(len(v or []) for v in lists.values())
    log("")
    log(f"What GET /hrms/employee-master/lists?company_id={company_id} would return:")
    log("")
    width = max(len(k) for k in lists)
    for key, values in lists.items():
        shown = ", ".join(values[:6]) + ("  …" if len(values) > 6 else "")
        log(f"  {key.ljust(width)}  {len(values):>3}  {shown or '(empty)'}")
    log("")
    if total:
        log(f"{total} value(s). If the screen still shows none, the screen is scoped to a")
        log("different company — check the scope bar — or the browser is serving a cached")
        log("response; reload with cache disabled.")
    else:
        log("Nothing stored against THIS id. The seed went to a different company_id, or")
        log("the seed script reported an error. Run the overview above to find it.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", help="also show the values for this company_id")
    args = parser.parse_args()

    client = await connect()
    try:
        await overview()
        if args.company:
            await detail(args.company)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
