"""Phase 1 FRD §23 -- attendance rules on the policy spine, and their simulation.

  1. The day engine's new §23 parameters: half-day by late/early COMBINATION, a
     configurable LOP fraction, and the no-out-punch rule.
  2. An unconfigured company judges days EXACTLY as it did before this phase. This is the
     deployment-safety check and the most important one here.
  3. A scoped, effective-dated ATT_DAY policy changes the right people from the right date
     and leaves a closed month alone (FRD §23, §26, §30).
  4. Simulation compares old against proposed and writes nothing (FRD §23, §25).
  5. The monthly cut-off actually stops a write (FRD §23 Monthly Closure) -- it was stored
     and commented "(informational)" before this phase.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_attendance_policy   (from backend/)
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


async def expect(label, coro, status, needle=""):
    from fastapi import HTTPException
    try:
        await coro
    except HTTPException as e:
        return check(f"{label} -> {status}", e.status_code == status
                     and needle.lower() in str(e.detail).lower(), e.detail)
    return check(f"{label} -> {status} (no error raised)", False)


from app.services.hrms.tests.test_payroll_live_findings import FakeCollection  # noqa: E402

CO = "C1"
HR = {"_id": "hr-1", "role": "admin", "full_name": "Dummy HR"}
APPROVER = {"_id": "fin-1", "role": "admin", "full_name": "Dummy Finance"}


async def main() -> int:
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_attendance_rules_service as AR
    import app.services.hrms_attendance_simulation_service as SIM
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_policy_version_service as PV
    import app.services.hrms_shift_service as SH

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AR, AT, PV, SH, SIM):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    PV.audit = no_audit

    # ── 1. The engine's new §23 parameters ──────────────────────────────────────────
    section("1. §23 half-day combination, LOP fraction, no-out-punch")

    c = M.compute_daily_status
    base = dict(scheduled_in="09:30", scheduled_out="18:30", daily_grace_minutes=5,
                half_day_threshold_minutes=240)

    d = c(**base, actual_in="09:30", actual_out="18:30")
    check("unchanged by default: a full day is Present, payable 1.0",
          d["status"] == "Present" and d["payable_day"] == 1.0
          and d["half_day_reason"] is None)

    d = c(**base, actual_in="11:30", actual_out="20:30", half_day_late_minutes=90)
    check("§23 half day by LATE combination: 9 hours worked but 115 min late",
          d["status"] == "Half Day" and d["worked_minutes"] == 540
          and "late" in (d["half_day_reason"] or ""))

    d = c(**base, actual_in="06:30", actual_out="15:00", half_day_early_minutes=120)
    check("§23 half day by EARLY combination: left 210 min early",
          d["status"] == "Half Day" and "early" in (d["half_day_reason"] or ""))

    d = c(**base, actual_in="11:30", actual_out="20:30")
    check("...neither fires when the company has not configured them",
          d["status"] == "Present")

    d = c(**base, actual_in="09:30", actual_out="12:00", half_day_fraction=0.25)
    check("§23 LOP fraction: a half day can cost a quarter",
          d["payable_day"] == 0.25 and d["lop_fraction"] == 0.75)
    d = c(**base, actual_in="09:30", actual_out="12:00")
    check("...and still costs half when unconfigured", d["payable_day"] == 0.5)

    d = c(**base, actual_in="09:30", actual_out=None)
    check("a missing out-punch is Present pending correction, as before",
          d["status"] == "Present" and d["missing_out_punch"] is True)
    d = c(**base, actual_in="09:30", actual_out=None, absent_on_no_out_punch=True)
    check("§23 Absent rule: a company may treat it as Absent instead",
          d["status"] == "Absent" and d["missing_out_punch"] is True)

    # ── 2. An unconfigured company is untouched ─────────────────────────────────────
    section("2. No policy configured -> identical judgement (deployment safety)")

    store.setdefault(M.COLL_SETTINGS, FakeCollection()).docs.append({
        "company_id": CO, "shift_policy": {**M.DEFAULT_SHIFT_POLICY}})
    store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection()).docs.extend([
        {"company_id": CO, "employee_code": "E1", "user_id": "u1",
         "work_location": "Pune", "grade": "M3"},
        {"company_id": CO, "employee_code": "E2", "user_id": "u2",
         "work_location": "Mumbai", "grade": "M1"},
    ])

    plain = await AR.compute_day(CO, "E1", "2026-03-10", "09:30", "18:30")
    check("a normal day resolves with no policy in play",
          plain["status"] == "Present" and plain["payable_day"] == 1.0)
    check("...and records that no ATT_DAY version judged it",
          plain.get("day_policy_version") is None)

    late_plain = await AR.compute_day(CO, "E1", "2026-03-11", "11:30", "20:30")
    check("a very late but full-length day is Present without a combination rule",
          late_plain["status"] == "Present")

    # ── 3. A scoped, effective-dated policy ─────────────────────────────────────────
    section("3. Scoped and effective-dated ATT_DAY (§23, §26, §30)")

    await PV.save_definition(HR, CO, {"code": M.POLICY_ATT_DAY, "name": "Daily rules",
                                      "module": "attendance"})
    await PV.save_draft(HR, CO, {
        "policy_code": M.POLICY_ATT_DAY, "effective_from": "2026-04-01",
        "rules": {"half_day_late_minutes": 90, "half_day_fraction": 0.25}})
    await PV.set_status(HR, CO, M.POLICY_ATT_DAY, 1, "Pending Approval")
    await PV.set_status(APPROVER, CO, M.POLICY_ATT_DAY, 1, "Approved")
    await PV.assign_scope(HR, CO, {"policy_code": M.POLICY_ATT_DAY, "version_no": 1,
                                   "scope": {"locations": ["Pune"]}})
    await PV.set_status(APPROVER, CO, M.POLICY_ATT_DAY, 1, "Active")

    march = await AR.compute_day(CO, "E1", "2026-03-11", "11:30", "20:30")
    check("the CLOSED month before the effective date is untouched (§30)",
          march["status"] == "Present" and march.get("day_policy_version") is None)

    april = await AR.compute_day(CO, "E1", "2026-04-11", "11:30", "20:30")
    check("from the effective date, the Pune employee gets the combination rule",
          april["status"] == "Half Day" and april["payable_day"] == 0.25)
    check("...and the day records WHICH version judged it (§30)",
          april.get("day_policy_version") == 1
          and april.get("day_policy_code") == M.POLICY_ATT_DAY)
    check("...and WHY it was cut to half", "late" in (april.get("half_day_reason") or ""))

    mumbai = await AR.compute_day(CO, "E2", "2026-04-11", "11:30", "20:30")
    check("the Mumbai employee is outside the scope and unaffected",
          mumbai["status"] == "Present" and mumbai.get("day_policy_version") is None)

    # ── 4. Simulation ───────────────────────────────────────────────────────────────
    section("4. Simulation compares and writes nothing (§23, §25)")

    att = store.setdefault(M.COLL_ATTENDANCE, FakeCollection())
    att.docs.extend([
        {"company_id": CO, "employee_code": "E1", "work_date": "2026-05-04",
         "actual_in": "11:30", "actual_out": "20:30", "status": "Present",
         "scheduled_in": "09:30", "scheduled_out": "18:30"},
        {"company_id": CO, "employee_code": "E1", "work_date": "2026-05-05",
         "actual_in": "09:30", "actual_out": "18:30", "status": "Present",
         "scheduled_in": "09:30", "scheduled_out": "18:30"},
        {"company_id": CO, "employee_code": "E1", "work_date": "2026-05-06",
         "status": "Holiday"},
    ])
    before = len(att.docs)

    await PV.save_draft(HR, CO, {
        "policy_code": M.POLICY_ATT_DAY, "effective_from": "2026-06-01",
        "rules": {"half_day_late_minutes": 30}})
    sim = await SIM.simulate_day_policy(CO, "2026-05", version_no=2,
                                        employee_codes=["E1"])
    check("only real working days with punches are examined -- the holiday is skipped",
          sim["days_examined"] == 2)
    check("a stricter rule moves the late day and leaves the clean one",
          sim["days_changed"] == 1
          and sim["changes"][0]["work_date"] == "2026-05-04")
    check("the comparison shows old versus proposed (§25)",
          sim["changes"][0]["was"]["status"] == "Half Day"
          and sim["changes"][0]["now"]["status"] == "Half Day"
          and sim["changes"][0]["was"]["payable_day"] == 0.25
          and sim["changes"][0]["now"]["payable_day"] == 0.5)
    check("the headline totals name the cost", sim["employees_affected"] == 1)
    check("nothing was written", len(att.docs) == before)
    check("the simulated version is still a Draft -- simulating is not activating",
          sim["status"] == "Draft")

    # ── 5. The monthly cut-off ──────────────────────────────────────────────────────
    section("5. The §23 cut-off actually stops a write")

    import app.utils.hrms_access as HA
    original_can = HA.can
    AT.can = lambda user, cap: False          # an ordinary user, no unlock authority

    check("default is OFF -- no company gets a refusal it did not configure",
          (await AT.closure_rules(CO)).get("enforce_cutoff") is False)
    await AT._assert_within_cutoff(HR, CO, "2020-01-15")
    check("...so an old date passes while the cut-off is off", True)

    store[M.COLL_SETTINGS].docs[0]["shift_policy"].update(
        {"enforce_attendance_cutoff": True, "attendance_closing_day": 5})
    rules = await AT.closure_rules(CO)
    check("switching it on is read back", rules["enforce_cutoff"] is True
          and rules["closing_day"] == 5)
    await expect("a day in a month whose cut-off has passed",
                 AT._assert_within_cutoff(HR, CO, "2020-01-15"), 409, "closed on")

    AT.can = lambda user, cap: True           # HR, holding ATTENDANCE_LOCK
    await AT._assert_within_cutoff(HR, CO, "2020-01-15")
    check("...but the lock authority may still correct it", True)
    AT.can = original_can

    print("\n" + "=" * 60)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 60)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
