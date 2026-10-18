"""Phase 1 FRD §23/§26/§28 -- the versioned-policy spine.

  1. Versions: a draft is not resolvable; activation supersedes rather than deletes;
     the lifecycle refuses to run backwards (FRD §21, §26, §27).
  2. Effective dating: a future version does not affect today, and a closed date keeps the
     version that was in force then (FRD §23, §30).
  3. The documented priority rule (FRD §26): specificity, then priority, then effective
     date, then version number -- and the answer is the same every time.
  4. Fallback: a company with no versions behaves exactly as it did before this existed.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_policy_spine   (from backend/)
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
    import app.services.hrms_policy_version_service as PV

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    # The service binds get_collection at import, so the module's own name is what matters.
    PV.get_collection = getter

    async def no_audit(*a, **k):
        return None
    PV.audit = no_audit

    # ── 1. Definitions and the version lifecycle ────────────────────────────────────
    section("1. Version lifecycle (FRD §21, §26, §27)")

    await PV.save_definition(HR, CO, {
        "code": "att_lop", "name": "LOP rule", "module": "attendance"})
    defs = await PV.list_definitions(CO, "attendance")
    check("a definition is created once, upper-cased",
          len(defs) == 1 and defs[0]["code"] == "ATT_LOP")

    await expect("a version for an unknown policy", PV.save_draft(HR, CO, {
        "policy_code": "NOPE", "effective_from": "2026-01-01", "rules": {}}), 404, "no policy")

    v1 = await PV.save_draft(HR, CO, {
        "policy_code": "ATT_LOP", "effective_from": "2026-01-01",
        "rules": {"half_day_fraction": 0.5}, "change_reason": "Baseline"})
    check("a new version starts at 1 and as Draft",
          v1["version_no"] == 1 and v1["status"] == "Draft")
    check("a Draft is NOT resolvable -- nothing calculates against an unapproved rule",
          await PV.resolve(CO, "ATT_LOP", {}, "2026-06-01") is None)

    await expect("Draft cannot jump straight to Active",
                 PV.set_status(HR, CO, "ATT_LOP", 1, "Active"), 409, "cannot become")
    await PV.set_status(HR, CO, "ATT_LOP", 1, "Pending Approval")
    await PV.set_status(APPROVER, CO, "ATT_LOP", 1, "Approved")
    await PV.set_status(APPROVER, CO, "ATT_LOP", 1, "Active")
    got = await PV.resolve(CO, "ATT_LOP", {}, "2026-06-01")
    check("once Active it resolves, carrying its own provenance",
          got and got["version_no"] == 1 and got["rules"]["half_day_fraction"] == 0.5
          and got["specificity"] == 0)

    await expect("an approved version cannot be edited",
                 PV.save_draft(HR, CO, {"policy_code": "ATT_LOP", "version_no": 1,
                                        "effective_from": "2026-01-01", "rules": {}}),
                 409, "cannot be edited")

    # ── 2. Effective dating ─────────────────────────────────────────────────────────
    section("2. Effective dating (FRD §23, §30)")

    v2 = await PV.save_draft(HR, CO, {
        "policy_code": "ATT_LOP", "effective_from": "2026-07-01",
        "rules": {"half_day_fraction": 0.25}, "change_reason": "Softer half day"})
    await PV.set_status(HR, CO, "ATT_LOP", 2, "Pending Approval")
    await PV.set_status(APPROVER, CO, "ATT_LOP", 2, "Approved")
    check("an approved future version does not touch today",
          (await PV.resolve(CO, "ATT_LOP", {}, "2026-06-30"))["version_no"] == 1)
    check("...but it is already the answer on and after its date",
          (await PV.resolve(CO, "ATT_LOP", {}, "2026-07-01"))["version_no"] == 2)

    await PV.set_status(APPROVER, CO, "ATT_LOP", 2, "Active")
    rows = {r["version_no"]: r for r in await PV.list_versions(CO, "ATT_LOP")}
    check("activating v2 SUPERSEDES v1 rather than deleting it",
          rows[1]["status"] == "Superseded" and rows[1]["superseded_by"] == 2)
    check("a closed period still resolves to the version that was in force then",
          (await PV.resolve(CO, "ATT_LOP", {}, "2026-03-15"))["version_no"] == 1)
    check("the superseded version keeps the rules it was used with",
          (await PV.resolve(CO, "ATT_LOP", {}, "2026-03-15"))["rules"]["half_day_fraction"] == 0.5)

    # ── 3. The documented priority rule ─────────────────────────────────────────────
    section("3. Documented priority rule (FRD §26)")

    await PV.save_definition(HR, CO, {"code": "att_grace", "name": "Grace",
                                      "module": "attendance"})
    # Three versions, all in force on the same date, scoped differently.
    for n, (mins, scope, priority) in enumerate([
        (5,  {},                                              0),   # v1 company default
        (10, {"locations": ["Pune"]},                         0),   # v2 one dimension
        (15, {"locations": ["Pune"], "grades": ["M3"]},       0),   # v3 two dimensions
    ], start=1):
        await PV.save_draft(HR, CO, {"policy_code": "ATT_GRACE",
                                     "effective_from": "2026-01-01",
                                     "rules": {"daily_grace_minutes": mins}})
        await PV.set_status(HR, CO, "ATT_GRACE", n, "Pending Approval")
        await PV.set_status(APPROVER, CO, "ATT_GRACE", n, "Approved")
        if scope:
            await PV.assign_scope(HR, CO, {"policy_code": "ATT_GRACE", "version_no": n,
                                           "scope": scope, "priority": priority})

    mumbai = {"work_location": "Mumbai", "grade": "M1"}
    pune_m1 = {"work_location": "Pune", "grade": "M1"}
    pune_m3 = {"work_location": "Pune", "grade": "M3"}

    check("nobody matched by a scope falls to the company default",
          (await PV.resolve(CO, "ATT_GRACE", mumbai, "2026-06-01"))["rules"]
          ["daily_grace_minutes"] == 5)
    check("one matching dimension beats the company default",
          (await PV.resolve(CO, "ATT_GRACE", pune_m1, "2026-06-01"))["rules"]
          ["daily_grace_minutes"] == 10)
    check("two matching dimensions beat one",
          (await PV.resolve(CO, "ATT_GRACE", pune_m3, "2026-06-01"))["rules"]
          ["daily_grace_minutes"] == 15)
    check("the winner reports HOW specific it was",
          (await PV.resolve(CO, "ATT_GRACE", pune_m3, "2026-06-01"))["specificity"] == 2)

    # Equal specificity in DIFFERENT dimensions -- the administrator's priority decides.
    await PV.save_draft(HR, CO, {"policy_code": "ATT_GRACE", "effective_from": "2026-01-01",
                                 "rules": {"daily_grace_minutes": 20}})
    await PV.set_status(HR, CO, "ATT_GRACE", 4, "Pending Approval")
    await PV.set_status(APPROVER, CO, "ATT_GRACE", 4, "Approved")
    await PV.assign_scope(HR, CO, {"policy_code": "ATT_GRACE", "version_no": 4,
                                   "scope": {"grades": ["M1"]}, "priority": 5})
    check("two equally specific rules: the higher priority wins",
          (await PV.resolve(CO, "ATT_GRACE", pune_m1, "2026-06-01"))["rules"]
          ["daily_grace_minutes"] == 20)
    first = await PV.resolve(CO, "ATT_GRACE", pune_m1, "2026-06-01")
    again = await PV.resolve(CO, "ATT_GRACE", pune_m1, "2026-06-01")
    check("the same question gives the same answer -- payroll stays reproducible",
          first["version_no"] == again["version_no"])

    await expect("an unknown scope dimension is refused", PV.assign_scope(HR, CO, {
        "policy_code": "ATT_GRACE", "version_no": 4,
        "scope": {"favourite_colour": ["blue"]}}), 422, "scope dimension")

    # ── 4. Activation and scope ─────────────────────────────────────────────────────
    section("4. Activation displaces only the same population (FRD §26)")

    await PV.save_definition(HR, CO, {"code": "att_late", "name": "Late",
                                      "module": "attendance"})
    # v1: the company-wide rule. v2: a Pune-only rule. Both must be able to be live.
    await PV.save_draft(HR, CO, {"policy_code": "ATT_LATE", "effective_from": "2026-01-01",
                                 "rules": {"late_after": 10}})
    await PV.set_status(HR, CO, "ATT_LATE", 1, "Pending Approval")
    await PV.set_status(APPROVER, CO, "ATT_LATE", 1, "Approved")
    await PV.set_status(APPROVER, CO, "ATT_LATE", 1, "Active")

    await PV.save_draft(HR, CO, {"policy_code": "ATT_LATE", "effective_from": "2026-01-01",
                                 "rules": {"late_after": 20}})
    await PV.set_status(HR, CO, "ATT_LATE", 2, "Pending Approval")
    await PV.set_status(APPROVER, CO, "ATT_LATE", 2, "Approved")
    await PV.assign_scope(HR, CO, {"policy_code": "ATT_LATE", "version_no": 2,
                                   "scope": {"locations": ["Pune"]}})
    await PV.set_status(APPROVER, CO, "ATT_LATE", 2, "Active")

    late = {r["version_no"]: r for r in await PV.list_versions(CO, "ATT_LATE")}
    check("activating a Pune-only rule does NOT switch off the company default",
          late[1]["status"] == "Active" and late[2]["status"] == "Active")
    check("...Mumbai still gets the company rule",
          (await PV.resolve(CO, "ATT_LATE", {"work_location": "Mumbai"},
                            "2026-06-01"))["rules"]["late_after"] == 10)
    check("...and Pune gets its own",
          (await PV.resolve(CO, "ATT_LATE", {"work_location": "Pune"},
                            "2026-06-01"))["rules"]["late_after"] == 20)

    # A revision of the COMPANY-WIDE rule does displace the old company-wide one.
    await PV.save_draft(HR, CO, {"policy_code": "ATT_LATE", "effective_from": "2026-02-01",
                                 "rules": {"late_after": 12}})
    await PV.set_status(HR, CO, "ATT_LATE", 3, "Pending Approval")
    await PV.set_status(APPROVER, CO, "ATT_LATE", 3, "Approved")
    await PV.set_status(APPROVER, CO, "ATT_LATE", 3, "Active")
    late = {r["version_no"]: r for r in await PV.list_versions(CO, "ATT_LATE")}
    check("a new company-wide rule DOES supersede the old company-wide one",
          late[1]["status"] == "Superseded" and late[1]["superseded_by"] == 3)
    check("...while the Pune rule is left alone", late[2]["status"] == "Active")
    check("Pune is still on its own rule after the default was revised",
          (await PV.resolve(CO, "ATT_LATE", {"work_location": "Pune"},
                            "2026-06-01"))["rules"]["late_after"] == 20)

    # ── 5. Fallback: an unconfigured company is untouched ───────────────────────────
    section("5. Unconfigured companies are unchanged (deployment safety)")

    check("no policy at all -> resolve() is None, not an error",
          await PV.resolve(CO, "ATT_NOTHING", {}, "2026-06-01") is None)
    existing = {"daily_grace_minutes": 7, "half_day_threshold_minutes": 240}
    check("resolve_rules() hands back the caller's own settings untouched",
          await PV.resolve_rules(CO, "ATT_NOTHING", {}, "2026-06-01",
                                 default=existing) == existing)
    merged = await PV.resolve_rules(CO, "ATT_GRACE", pune_m1, "2026-06-01", default=existing)
    check("a configured policy overlays the default without dropping its other keys",
          merged["daily_grace_minutes"] == 20 and merged["half_day_threshold_minutes"] == 240)

    print("\n" + "=" * 60)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 60)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
