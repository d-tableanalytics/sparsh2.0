"""Post-review Gap 3 -- the payroll policy screen stops bypassing its own governance.

Checklist rows P1-072, P1-117 (partial), P1-120.

`PUT /hrms/payroll/policy` wrote straight into `hrms_settings.payroll_policy`. The rules
that decide whether a run needs a checker, what rounds to the rupee and when inputs close
went live the moment one person clicked Save: no version, no effective date, no second pair
of eyes, and an audit row naming the KEYS that moved without the values -- "net_rounding,
input_cutoff_day" tells a reader which settings changed and refuses to tell them what to.

Meanwhile PAY_POLICY versions were resolvable, effective-dated and scopeable, and NO SCREEN
could create one. The feature existed and was unreachable; the screen that should have used
it went round it.

Saving now drafts a version and raises a §27 change request. The flat settings dict stays
the fallback base every version lays over, so a company holding no versions resolves
exactly what it resolved before -- section 1 is that check, and it is the one that matters
for deployment.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_gap3_payroll_policy_governance   (from backend/)
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
MAKER = {"_id": "pay-1", "role": "superadmin", "governance_role": "HR",
         "full_name": "Dummy Payroll Maker"}
APPROVER = {"_id": "fin-1", "role": "superadmin", "governance_role": "MD",
            "full_name": "Dummy Finance"}


async def main() -> int:
    from bson import ObjectId

    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_audit_service as AU
    import app.services.hrms_config_change_service as CC
    import app.services.hrms_config_dependency_service as DEP
    import app.services.hrms_payroll_service as PR
    import app.services.hrms_policy_version_service as PV
    import app.services.hrms_shift_service as SH

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AU, CC, DEP, PR, PV, SH):
        mod.get_collection = getter

    counter = {"n": 0}

    async def fake_id(kind, company, year):
        counter["n"] += 1
        return f"CFG-{counter['n']:04d}"
    CC.next_business_id = fake_id

    # The flat settings a company already has. Everything resolves over this.
    store[M.COLL_SETTINGS] = FakeCollection([
        {"company_id": CO, "payroll_policy": {"input_cutoff_day": 25, "net_rounding": "None",
                                              "variance_threshold_percent": 10.0}}])
    store[M.COLL_EMPLOYEE_PROFILES] = FakeCollection([
        {"company_id": CO, "employee_code": "E1", "user_id": str(ObjectId()),
         "employment_status": "Active", "grade": "M2"}])

    # ── 1. Saving drafts; it does not change what the runs read ───────────────────────
    section("1. Save drafts a version and a request, and changes nothing live")

    before = await PR.get_payroll_policy(CO)
    check("the policy in force starts at the flat settings",
          before["input_cutoff_day"] == 25 and before["net_rounding"] == "None", before)

    saved = await PR.save_payroll_policy(MAKER, CO, {
        "input_cutoff_day": 5, "net_rounding": "Nearest",
        "effective_from": "2026-12-01", "change_reason": "Finance moved the input cut-off"})
    check("a PAY_POLICY draft version was created",
          saved["pending_version"]["version_no"] == 1
          and saved["pending_version"]["status"] == "Draft", saved.get("pending_version"))
    check("...and a change request raised against it",
          saved["pending_request"]["entity_code"] == "PAY_POLICY"
          and saved["pending_request"]["version_no"] == 1
          and saved["pending_request"]["status"] == "Draft", saved.get("pending_request"))
    check("the request carries the reason and the effective date (FRD 27, 30)",
          saved["pending_request"]["reason"] == "Finance moved the input cut-off"
          and saved["pending_request"]["effective_from"] == "2026-12-01",
          saved["pending_request"])

    live = await PR.get_payroll_policy(CO)
    check("the policy IN FORCE has not moved -- a Draft is not live",
          live["input_cutoff_day"] == 25 and live["net_rounding"] == "None", live)
    check("the flat settings dict was not written either",
          store[M.COLL_SETTINGS].docs[0]["payroll_policy"]["input_cutoff_day"] == 25,
          store[M.COLL_SETTINGS].docs[0]["payroll_policy"])
    check("the response reports the policy in force, not the one hoped for",
          saved["input_cutoff_day"] == 25, saved["input_cutoff_day"])

    # The POLICY_DEFINITION is provisioned on the way through: without it save_draft 404s,
    # and nothing else in the product creates it for PAY_POLICY.
    check("the PAY_POLICY definition was provisioned rather than 404ing",
          any(d.get("code") == "PAY_POLICY" and d.get("module") == "payroll"
              for d in store[M.COLL_POLICY_DEFINITIONS].docs),
          store[M.COLL_POLICY_DEFINITIONS].docs)

    # ── 2. The audit row carries the values, not just the key names ───────────────────
    section("2. The audit row carries old and new values (FRD 30)")

    rows = await AU.read_audit(company_id=CO, entity=M.ENTITY_PAYROLL_RUN)
    row = next((r for r in rows if r["action"] == M.AUDIT_PAYROLL_POLICY_SAVED), None)
    check("the policy save was audited", row is not None, [r["action"] for r in rows])
    by_field = {c["field"]: c for c in (row or {}).get("changes") or []}
    check("old and new are recorded for the cut-off",
          by_field["input_cutoff_day"]["old"] == 25
          and by_field["input_cutoff_day"]["new"] == 5, by_field.get("input_cutoff_day"))
    check("...and for the rounding rule",
          by_field["net_rounding"]["old"] == "None"
          and by_field["net_rounding"]["new"] == "Nearest", by_field.get("net_rounding"))
    check("a key submitted but UNCHANGED is not reported as a change",
          "variance_threshold_percent" not in by_field, sorted(by_field))
    check("the detail sentence names the values too, for a reader of the trail",
          "input_cutoff_day 25 -> 5" in (row or {}).get("detail", ""), (row or {}).get("detail"))

    # ── 3. A reason is not optional ───────────────────────────────────────────────────
    section("3. A governed change cannot be raised without its reason")

    await expect("saving with no business reason",
                 PR.save_payroll_policy(MAKER, CO, {"input_cutoff_day": 7}),
                 422, "say why")
    check("...and no stray draft was left behind",
          len(store[M.COLL_POLICY_VERSIONS].docs) == 1,
          len(store[M.COLL_POLICY_VERSIONS].docs))

    # ── 4. Activation is what makes it live, and only through the flow ────────────────
    section("4. Approval then activation -- the request flow is the only way live")

    req_no = saved["pending_request"]["request_no"]
    await expect("activating a change nobody has approved",
                 CC.activate(APPROVER, CO, req_no), 409, "only an approved change")

    await CC.analyse_impact(MAKER, CO, req_no)
    await CC.submit(MAKER, CO, req_no)
    await expect("the drafter approving their own change",
                 CC.decide(MAKER, CO, req_no, {"action": "approve"}),
                 403, "someone else's to give")
    await CC.decide(APPROVER, CO, req_no, {"action": "approve", "comments": "Agreed"})
    activated = await CC.activate(APPROVER, CO, req_no)
    check("activation records the old and new definition (FRD 30)",
          activated["definition_change"]["new"]["input_cutoff_day"] == 5,
          activated.get("definition_change"))

    # Effective 2026-12-01, so it governs December and nothing before it.
    december = await PR.get_payroll_policy(CO, on_date="2026-12-31")
    check("from the effective date the run reads the new cut-off and rounding",
          december["input_cutoff_day"] == 5
          and december["net_rounding"] == "Nearest", december)
    closed = await PR.get_payroll_policy(CO, on_date="2026-11-30")
    check("a CLOSED period still reads the old version (FRD 21, 30)",
          closed["input_cutoff_day"] == 25 and closed["net_rounding"] == "None", closed)
    check("...and keys the version never mentioned still come from the base",
          december["variance_threshold_percent"] == 10.0
          and december["require_attendance_lock"] is True, december)

    # ── 5. A closed period's RUN keeps the version it used ────────────────────────────
    section("5. A run in a closed period is calculated on the old policy")

    store[M.COLL_SALARY_COMPONENTS] = FakeCollection([
        {"company_id": CO, "code": "BASIC", "name": "Basic", "component_type": "Earning",
         "active": True}])
    store[M.COLL_SALARY_STRUCTURES] = FakeCollection([
        {"company_id": CO, "employee_code": "E1", "effective_from": "2026-01-01",
         "components": [{"code": "BASIC", "amount": 30000.40}]}])
    store[M.COLL_ATTENDANCE] = FakeCollection([
        {"company_id": CO, "employee_code": "E1", "work_date": f"2026-11-{d:02d}",
         "status": "Present", "payable_day": 1.0, "lop_fraction": 0.0}
        for d in range(1, 31)])
    store[M.COLL_ATTENDANCE_LOCKS] = FakeCollection([
        {"company_id": CO, "period": "2026-11", "status": "Locked"},
        {"company_id": CO, "period": "2026-12", "status": "Locked"}])
    store[M.COLL_PAYROLL_RUNS] = FakeCollection([
        {"_id": ObjectId(), "company_id": CO, "period": "2026-11", "status": "Draft"}])
    store[M.COLL_PAYROLL_RECORDS] = FakeCollection()

    await PR.calculate_payroll(MAKER, CO, "2026-11")
    nov = store[M.COLL_PAYROLL_RECORDS].docs[0]
    check("November's net is NOT rounded -- its policy said None",
          nov["net_pay"] == 30000.4, nov["net_pay"])

    store[M.COLL_PAYROLL_RUNS].docs.append(
        {"_id": ObjectId(), "company_id": CO, "period": "2026-12", "status": "Draft"})
    store[M.COLL_ATTENDANCE].docs.extend([
        {"company_id": CO, "employee_code": "E1", "work_date": f"2026-12-{d:02d}",
         "status": "Present", "payable_day": 1.0, "lop_fraction": 0.0}
        for d in range(1, 32)])
    await PR.calculate_payroll(MAKER, CO, "2026-12")
    dec = next(r for r in store[M.COLL_PAYROLL_RECORDS].docs if r["period"] == "2026-12")
    check("December's IS rounded -- the activated version reached it",
          dec["net_pay"] == 30000.0, dec["net_pay"])

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
