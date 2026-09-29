"""Eight leave / C-Off defects found by the live test (Dummy HOD, LV-2026-001..005), pinned.

  1. Weekends were charged as leave (Fri-Mon = 4 days).
  2. One person could give both the manager approval and the final approval.
  3. Two requests for the same dates were both accepted.
  4. Two pending requests could together over-draw the balance (CL went 8 -> -4).
  5. Cancelling an approved leave left its days "On Leave" in attendance.
  6. The same worked day could be claimed for C-Off twice.
  7. A normal working day could be claimed as a "worked holiday".
  8. A half-day C-Off used up the whole day.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_leave_live_findings   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


from app.services.hrms.tests.test_phase2_employee import (  # noqa: E402
    FakeCollection as _BaseFake, _matches,
)


class FakeCollection(_BaseFake):
    """+ sorted find_one, $inc, and $pull by a sub-document condition."""

    async def find_one(self, query, projection=None, sort=None):
        hits = [d for d in self.docs if _matches(d, query)]
        for key, direction in reversed(sort or []):
            hits.sort(key=lambda d: d.get(key) or "", reverse=direction < 0)
        return hits[0] if hits else None

    async def update_one(self, query, update, upsert=False):
        update = dict(update)
        inc = update.pop("$inc", None)
        pull = update.pop("$pull", None)
        res = await super().update_one(query, update, upsert=upsert) if update else None
        from bson import ObjectId
        for d in self.docs:               # a real upsert always gives the new row an _id
            d.setdefault("_id", ObjectId())
        doc = next((d for d in self.docs if _matches(d, query)), None)
        if doc is not None:
            for k, v in (inc or {}).items():
                doc[k] = (doc.get(k) or 0) + v
            for k, cond in (pull or {}).items():
                doc[k] = [x for x in doc.get(k, [])
                          if not (isinstance(cond, dict) and all(x.get(a) == b for a, b in cond.items()))]
        return res


CO = "C1"
EMP = "EMP-1"


async def main() -> int:
    from bson import ObjectId
    from fastapi import HTTPException

    from app.models import hrms as M
    import app.db.mongodb as mongo

    store = {
        M.COLL_EMPLOYEE_PROFILES: FakeCollection([{"company_id": CO, "employee_code": EMP, "user_id": "u-emp"}]),
        M.COLL_HOLIDAYS: FakeCollection([{"company_id": CO, "holiday_date": "2026-12-25"}]),
        "staff": FakeCollection(), "learners": FakeCollection(),
    }
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_leave_service as LV
    import app.services.hrms_payroll_service as PR
    import app.services.hrms_audit_service as AU
    import app.services.hrms_id_service as IDS
    for mod in (LV, PR, AU, IDS):
        mod.get_collection = mongo.get_collection
    LV._today = lambda: "2026-09-26"

    async def _ok(*_a, **_k):
        return None
    LV._assert_self_or_privileged = _ok
    LV._reporting_manager_id = _ok

    MGR, HR, HR2 = {"_id": "mgr"}, {"_id": "hr"}, {"_id": "hr2"}

    async def attempt(coro):
        try:
            return await coro
        except HTTPException as e:
            return e

    def apply(**kw):
        return attempt(LV.apply_leave(HR, CO, {"employee_code": EMP, "reason": "t", **kw}))

    async def approve(no, final_by=HR):
        await LV.act_on_leave(MGR, CO, no, {"decision": "Manager Approved"})
        return await attempt(LV.act_on_leave(final_by, CO, no, {"decision": "Approved"}))

    async def closing(t):
        bal = await LV._get_balance(CO, EMP, t, 2026)
        return LV._closing(bal)

    att = store.setdefault("hrms_attendance", FakeCollection())

    section("1. Only working days are charged")
    a = await apply(leave_type="CL", start_date="2026-12-04", end_date="2026-12-07")
    check("Fri 4 - Mon 7 Dec = 2 days", a["days_count"] == 2)
    check("...on the Friday and the Monday", a["leave_dates"] == ["2026-12-04", "2026-12-07"])
    x = await apply(leave_type="CL", start_date="2026-12-24", end_date="2026-12-28")
    check("a company holiday (25 Dec) is not charged: 24-28 Dec = 2 days", x["days_count"] == 2)
    await LV.cancel_leave(HR, CO, x["leave_no"], "t")
    r = await apply(leave_type="CL", start_date="2026-12-05", end_date="2026-12-06")
    check("a weekend-only request is refused", isinstance(r, HTTPException) and r.status_code == 422)

    section("3. Overlapping leave is refused")
    r = await apply(leave_type="SL", start_date="2026-12-07", end_date="2026-12-07")
    check("a day already inside another leave -> 409", isinstance(r, HTTPException) and r.status_code == 409)

    section("2. Two approvals need two people")
    await LV.act_on_leave(MGR, CO, a["leave_no"], {"decision": "Manager Approved"})
    r = await attempt(LV.act_on_leave(MGR, CO, a["leave_no"], {"decision": "Approved"}))
    check("the manager who approved cannot also give the final approval",
          isinstance(r, HTTPException) and r.status_code == 409)
    done = await LV.act_on_leave(HR, CO, a["leave_no"], {"decision": "Approved"})
    check("...someone else can", done["status"] == "Approved")
    check("CL 12 -> 10", await closing("CL") == 10)
    marked = sorted(d["work_date"] for d in att.docs if d.get("leave_ref") == a["leave_no"])
    check("attendance marks only the working days", marked == ["2026-12-04", "2026-12-07"])

    section("4. The balance cannot be over-drawn")
    big = await apply(leave_type="CL", start_date="2026-12-08", end_date="2026-12-17")
    check("8 working days accepted against 10", big["days_count"] == 8)
    r = await apply(leave_type="CL", start_date="2026-12-18", end_date="2026-12-23")
    check("4 more refused while the 8 are pending",
          isinstance(r, HTTPException) and r.status_code == 422 and "awaiting approval" in r.detail)
    # Squeeze the balance behind an approved request's back: the final approval re-checks.
    bal = await LV._get_balance(CO, EMP, "CL", 2026)
    bal["adjusted"] = -5
    r = await approve(big["leave_no"])
    check("final approval refuses when the balance has since dropped below the request",
          isinstance(r, HTTPException) and r.status_code == 409)
    bal["adjusted"] = 0
    await LV.cancel_leave(HR, CO, big["leave_no"], "t")

    section("5. Cancelling restores the calendar too")
    att.docs.append({"_id": ObjectId(), "company_id": CO, "employee_code": EMP, "work_date": "2026-12-21",
                     "status": "Present", "locked": False})
    y = await apply(leave_type="CL", start_date="2026-12-21", end_date="2026-12-22")
    await approve(y["leave_no"])
    await LV.cancel_leave(HR, CO, y["leave_no"], "t")
    left = {d["work_date"]: d["status"] for d in att.docs if d["work_date"] in ("2026-12-21", "2026-12-22")}
    check("a day that was Present before the leave is Present again", left.get("2026-12-21") == "Present")
    check("a day the leave itself created is removed", "2026-12-22" not in left)
    await LV.cancel_leave(HR, CO, a["leave_no"], "t")
    check("cancelling gives the days back (CL 12)", await closing("CL") == 12)

    section("6/7. C-Off: a real day off, in the past, once")
    r = await attempt(LV.request_coff_earn(HR, CO, {"employee_code": EMP, "earned_for_date": "2026-09-15"}))
    check("a normal Tuesday -> 422", isinstance(r, HTTPException) and r.status_code == 422)
    r = await attempt(LV.request_coff_earn(HR, CO, {"employee_code": EMP, "earned_for_date": "2026-10-04"}))
    check("a Sunday not yet worked -> 422", isinstance(r, HTTPException) and r.status_code == 422)
    earn = await LV.request_coff_earn(HR, CO, {"employee_code": EMP, "earned_for_date": "2026-09-13"})
    r = await attempt(LV.request_coff_earn(HR, CO, {"employee_code": EMP, "earned_for_date": "2026-09-13"}))
    check("the same Sunday twice -> 409", isinstance(r, HTTPException) and r.status_code == 409)
    await LV.act_on_coff_earn(HR, CO, earn["id"], {"approved": True})

    section("8. A half-day C-Off takes half a day")
    h = await apply(leave_type="C-Off", start_date="2026-12-09", end_date="2026-12-09",
                    half_day=True, half_session="First Half")
    await approve(h["leave_no"])
    check("balance 1 -> 0.5", await LV._coff_available_balance(CO, EMP) == 0.5)
    h2 = await apply(leave_type="C-Off", start_date="2026-12-10", end_date="2026-12-10",
                     half_day=True, half_session="First Half")
    check("...so a second half day still fits", h2["days_count"] == 0.5)
    await LV.cancel_leave(HR, CO, h2["leave_no"], "t")
    await LV.cancel_leave(HR, CO, h["leave_no"], "t")
    check("cancelling the first gives back exactly its half (balance 1)",
          await LV._coff_available_balance(CO, EMP) == 1)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
