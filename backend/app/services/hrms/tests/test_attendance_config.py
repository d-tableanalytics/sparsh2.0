"""FRD 23 -- the two rule parameters Attendance Configuration added.

Attendance Configuration presents 23's categories as seven tabs over the three ATT_*
policy records. Two of those tabs had a field with nowhere to store it, and this pins both:

  1. Early Going -- `min_hours` set by an ATT_DAY POLICY (scoped, effective-dated), not
     only by the shift or the company timing. The engine already read `min_hours` off the
     merged policy; what was missing was the policy's right to set it, so the risk this
     covers is the MERGE, not the arithmetic.
  2. Monthly Cut-off -- `lock_cap` as the configurable lock authority, mirroring the
     payroll matrix's own `lock_cap`. The important check is the allowlist guard: a
     capability outside ATTENDANCE_LOCK_ALLOWED_CAPS must fall back to HR, because a typo
     in configuration that WIDENED who can close a month would be a hole wearing a scope.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_attendance_config   (from backend/)
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


async def expect(label, coro, status):
    from fastapi import HTTPException
    try:
        await coro
    except HTTPException as e:
        return check(f"{label} -> {status}", e.status_code == status, e.detail)
    return check(f"{label} -> {status} (no error raised)", False)


from app.services.hrms.tests.test_payroll_live_findings import FakeCollection  # noqa: E402
from app.services.hrms.tests.governance_helper import activate_policy_version  # noqa: E402

CO = "C1"
HR = {"_id": "hr-1", "role": "admin", "full_name": "Dummy HR"}
MD = {"_id": "md-1", "role": "admin", "full_name": "Dummy MD"}


async def main() -> int:
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_attendance_rules_service as AR
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_config_change_service as CC
    import app.services.hrms_policy_version_service as PV
    import app.services.hrms_shift_service as SH
    import app.routes.hrms as R

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AR, AT, CC, PV, SH):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    PV.audit = no_audit
    CC.audit = no_audit

    store.setdefault(M.COLL_SETTINGS, FakeCollection()).docs.append({
        "company_id": CO, "shift_policy": {**M.DEFAULT_SHIFT_POLICY}})
    store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection()).docs.extend([
        {"company_id": CO, "employee_code": "E1", "user_id": "u1",
         "work_location": "Pune", "level": "L2", "employee_category": "Staff"},
        {"company_id": CO, "employee_code": "E2", "user_id": "u2",
         "work_location": "Mumbai", "level": "L1", "employee_category": "Staff"},
    ])

    # ── 1. min_hours is reachable from an ATT_DAY policy ────────────────────────────
    section("1. Early Going: min_hours set by the POLICY (new)")

    check("min_hours is declared on ATT_DAY",
          "min_hours" in M.ATTENDANCE_POLICY_RULES[M.POLICY_ATT_DAY])

    # 09:30-18:30 with a 7h30m day: above the 4h half-day threshold, so Present today.
    before = await AR.compute_day(CO, "E1", "2026-03-10", "09:30", "17:00")
    check("unconfigured: a 7h30 day is Present", before["status"] == "Present", before)

    await PV.save_definition(HR, CO, {"code": M.POLICY_ATT_DAY, "name": "Day",
                                      "module": "attendance"})
    await PV.save_draft(HR, CO, {"policy_code": M.POLICY_ATT_DAY,
                                 "effective_from": "2026-03-01",
                                 "rules": {"min_hours": 8}})
    # Scoped to Pune + level L2 -- the §23 applicability dimensions the screen now leads with.
    await PV.assign_scope(HR, CO, {"policy_code": M.POLICY_ATT_DAY, "version_no": 1,
                                   "scope": {"locations": ["Pune"], "levels": ["L2"]}})
    await activate_policy_version(CC, HR, MD, CO, M.POLICY_ATT_DAY, 1)

    after = await AR.compute_day(CO, "E1", "2026-03-10", "09:30", "17:00")
    check("policy min_hours=8 cuts the same day to Half Day",
          after["status"] == "Half Day", after)
    check("...and says WHY, on the min_hours basis",
          after.get("half_day_basis") == "min_hours"
          and "minimum hours" in (after.get("half_day_reason") or ""), after)
    check("...and records which version judged it",
          after.get("day_policy_version") == 1, after)

    out_of_scope = await AR.compute_day(CO, "E2", "2026-03-10", "09:30", "17:00")
    check("the Mumbai / L1 employee is outside the scope and unaffected",
          out_of_scope["status"] == "Present", out_of_scope)

    stale = await AR.compute_day(CO, "E1", "2026-02-10", "09:30", "17:00")
    check("a day BEFORE the effective date is untouched",
          stale["status"] == "Present", stale)

    # ── 2. lock_cap as the configurable lock authority ──────────────────────────────
    section("2. Monthly Cut-off: lock authority (new)")

    check("lock_cap is declared on ATT_CLOSURE",
          "lock_cap" in M.ATTENDANCE_POLICY_RULES[M.POLICY_ATT_CLOSURE])
    check("the allowlist does not include a read-only capability",
          M.Cap.ATTENDANCE_CLOSURE_READ.value not in M.ATTENDANCE_LOCK_ALLOWED_CAPS)

    held: set[str] = set()
    R.can = lambda user, cap: cap.value in held

    held = {"attendance.lock"}
    await R._require_attendance_lock_cap(HR, CO)
    check("unconfigured: attendance.lock is the authority", True)

    held = {"payroll.approve"}
    await expect("unconfigured: payroll.approve alone cannot lock",
                 R._require_attendance_lock_cap(HR, CO), 403)

    # Configure Finance as the authority.
    await PV.save_definition(HR, CO, {"code": M.POLICY_ATT_CLOSURE, "name": "Closure",
                                      "module": "attendance"})
    await PV.save_draft(HR, CO, {"policy_code": M.POLICY_ATT_CLOSURE,
                                 "effective_from": "2026-01-01",
                                 "rules": {"lock_cap": "payroll.approve"}})
    await activate_policy_version(CC, HR, MD, CO, M.POLICY_ATT_CLOSURE, 1)

    held = {"payroll.approve"}
    await R._require_attendance_lock_cap(HR, CO)
    check("configured: payroll.approve now locks the month", True)

    held = {"attendance.lock"}
    await expect("...and plain HR no longer can -- authority MOVED, not widened",
                 R._require_attendance_lock_cap(HR, CO), 403)

    # The allowlist guard: a typo must fall back, not open the gate.
    await PV.save_draft(HR, CO, {"policy_code": M.POLICY_ATT_CLOSURE,
                                 "effective_from": "2026-01-01",
                                 "rules": {"lock_cap": "attendance.mark"}})
    await activate_policy_version(CC, HR, MD, CO, M.POLICY_ATT_CLOSURE, 2)

    held = {"attendance.mark"}
    await expect("an off-allowlist capability is NOT honoured",
                 R._require_attendance_lock_cap(HR, CO), 403)
    held = {"attendance.lock"}
    await R._require_attendance_lock_cap(HR, CO)
    check("...it falls back to HR instead", True)

    print("\n" + "=" * 60)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 60)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
