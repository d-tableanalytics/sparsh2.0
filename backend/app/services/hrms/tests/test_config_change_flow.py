"""Phase 1 FRD §27/§30 -- the configuration change approval flow.

  1. The stages are ordered: a change cannot reach an approver without an impact analysis,
     and cannot reach live configuration without an approval (FRD §27).
  2. The requester is never the approver (FRD §30 "separate").
  3. Impact analysis answers what the approver needs: how many employees, and whether the
     change is retroactive (FRD §26, §27).
  4. Activation is the ONLY writer, and it records the old/new definition (FRD §30).
  5. A rejected or returned change does not reach configuration at all.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_config_change_flow   (from backend/)
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
    import app.services.hrms_config_change_service as CC
    import app.services.hrms_id_service as ID
    import app.services.hrms_policy_version_service as PV

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (CC, ID, PV):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    CC.audit = no_audit
    PV.audit = no_audit

    # Two employees, so "how many people does this reach" has a real answer.
    store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection()).docs.extend([
        {"company_id": CO, "employee_code": "E1", "work_location": "Pune", "grade": "M3"},
        {"company_id": CO, "employee_code": "E2", "work_location": "Mumbai", "grade": "M1"},
    ])

    await PV.save_definition(HR, CO, {"code": "att_grace", "name": "Grace",
                                      "module": "attendance"})

    # ── 1. The stages are ordered ───────────────────────────────────────────────────
    section("1. The §27 stages are ordered, not optional")

    await PV.save_draft(HR, CO, {"policy_code": "ATT_GRACE", "effective_from": "2099-01-01",
                                 "rules": {"daily_grace_minutes": 15}})

    await expect("a change with no business reason", CC.create_request(HR, CO, {
        "entity_type": "policy_version", "entity_code": "ATT_GRACE", "version_no": 1}),
        422, "why")
    await expect("a change against a version that does not exist", CC.create_request(
        HR, CO, {"entity_code": "ATT_GRACE", "version_no": 99, "reason": "x"}),
        404, "no version")
    await expect("a change to an ungoverned kind of config", CC.create_request(HR, CO, {
        "entity_type": "favourite_colour", "entity_code": "X", "version_no": 1,
        "reason": "x"}), 422, "governed")

    req = await CC.create_request(HR, CO, {
        "entity_code": "ATT_GRACE", "version_no": 1,
        "title": "Grace 5 -> 15 minutes",
        "reason": "Traffic on the Pune route; agreed with the plant head."})
    no = req["request_no"]
    check("a request is numbered and starts as Draft",
          no.startswith("CFG-") and req["status"] == "Draft")

    await expect("submitting before the impact analysis", CC.submit(HR, CO, no),
                 409, "impact analysis")
    await expect("activating something never approved", CC.activate(APPROVER, CO, no),
                 409, "only an approved change")
    check("the policy version is still Draft -- nothing reached configuration",
          (await PV.list_versions(CO, "ATT_GRACE"))[0]["status"] == "Draft")

    # ── 2. Impact analysis ──────────────────────────────────────────────────────────
    section("2. Impact analysis answers what the approver needs (§26, §27)")

    analysed = await CC.analyse_impact(HR, CO, no)
    impact = analysed["impact"]
    check("an unscoped version reaches everybody",
          impact["employees_affected"] == 2 and impact["total_employees"] == 2)
    check("a future-dated change is not flagged retroactive",
          impact["retroactive"] is False and not impact["warnings"])
    check("the request moves to Impact Analysed", analysed["status"] == "Impact Analysed")

    # A scoped version reaches fewer people, and a back-dated one is a warning.
    await PV.save_draft(HR, CO, {"policy_code": "ATT_GRACE", "effective_from": "2020-01-01",
                                 "rules": {"daily_grace_minutes": 20}})
    await PV.assign_scope(HR, CO, {"policy_code": "ATT_GRACE", "version_no": 2,
                                   "scope": {"locations": ["Pune"]}})
    back = await CC.create_request(HR, CO, {
        "entity_code": "ATT_GRACE", "version_no": 2, "reason": "Back-dated correction"})
    back_impact = (await CC.analyse_impact(HR, CO, back["request_no"]))["impact"]
    check("a Pune-only change reaches only the Pune employee",
          back_impact["employees_affected"] == 1)
    check("a back-dated change is flagged retroactive, with a warning (§26)",
          back_impact["retroactive"] is True
          and "not recalculated automatically" in back_impact["warnings"][0].lower())

    # ── 3. Approval is somebody else's ──────────────────────────────────────────────
    section("3. The requester is never the approver (§30)")

    await CC.record_simulation(HR, CO, no, {"sampled": 2, "changed": 2})
    submitted = await CC.submit(HR, CO, no)
    check("once submitted it is Pending Approval", submitted["status"] == "Pending Approval")
    await expect("the requester approving their own change",
                 CC.decide(HR, CO, no, {"action": "approve"}), 403, "someone else")
    await expect("a return with no comment",
                 CC.decide(APPROVER, CO, no, {"action": "return"}), 422, "why")

    returned = await CC.decide(APPROVER, CO, no,
                               {"action": "return", "comments": "Show me March too."})
    check("a returned change goes back to the drafter", returned["status"] == "Returned")
    check("the policy version STILL has not moved",
          (await PV.list_versions(CO, "ATT_GRACE"))[-1]["status"] == "Draft")

    # ── 4. Activation is the only writer ────────────────────────────────────────────
    section("4. Activation is the only route to live configuration (§27, §30)")

    await CC.submit(HR, CO, no)                      # a Returned request may go back up
    approved = await CC.decide(APPROVER, CO, no, {"action": "approve", "comments": "Fine."})
    check("approved, but configuration is untouched until activation",
          approved["status"] == "Approved"
          and (await PV.list_versions(CO, "ATT_GRACE"))[-1]["status"] == "Draft")

    activated = await CC.activate(APPROVER, CO, no)
    check("activation moves the request to Active", activated["status"] == "Active")
    versions = {v["version_no"]: v for v in await PV.list_versions(CO, "ATT_GRACE")}
    check("...and the policy version is now Active", versions[1]["status"] == "Active")
    check("the resolver now returns the new rule",
          (await PV.resolve(CO, "ATT_GRACE", {}, "2099-06-01"))
          ["rules"]["daily_grace_minutes"] == 15)

    definition = activated.get("definition_change") or {}
    check("the old and new definitions are recorded (§30)",
          definition.get("new") == {"daily_grace_minutes": 15}
          and definition.get("new_version") == 1)

    full = await CC.get_request(CO, no)
    decisions = [a["decision"] for a in full["approvals"]]
    check("every decision is kept, not just the last one",
          decisions == ["Returned", "Approved"])
    check("the trail names the requester, the approver and the reason",
          full["requested_by_name"] == "Dummy HR"
          and full["approvals"][-1]["approver_name"] == "Dummy Finance"
          and "plant head" in full["reason"])

    await expect("an activated change cannot be withdrawn",
                 CC.withdraw(HR, CO, no, "changed my mind"), 409, "cannot be withdrawn")

    # ── 5. A rejected change never lands ────────────────────────────────────────────
    section("5. A rejected change never reaches configuration")

    rno = back["request_no"]
    await CC.submit(HR, CO, rno)
    rejected = await CC.decide(APPROVER, CO, rno,
                               {"action": "reject", "comments": "Not back-dating this."})
    check("rejected", rejected["status"] == "Rejected")
    await expect("a rejected change cannot be activated", CC.activate(APPROVER, CO, rno),
                 409, "only an approved change")
    check("its policy version is still Draft",
          {v["version_no"]: v for v in await PV.list_versions(CO, "ATT_GRACE")}[2]["status"]
          == "Draft")

    inbox = await CC.list_requests(CO, status="Pending Approval")
    check("the approval inbox is empty once everything is decided", inbox == [])

    print("\n" + "=" * 60)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 60)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
