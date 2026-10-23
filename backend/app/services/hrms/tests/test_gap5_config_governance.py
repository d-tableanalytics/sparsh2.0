"""Post-review Gap 5 -- closing the two doors around the configuration change flow.

Checklist row P1-117.

DOOR ONE. `POST /config/policies/{code}/versions/{v}/status` let a config.approve holder
walk a version Draft -> Pending -> Approved -> Active through one endpoint. No impact
analysis, no simulation, no change request -- and nothing stopping the person who drafted a
rule from approving it themselves, since the version's own status carries no notion of who
asked for it. §27 lists seven stages between wanting a rule changed and the rule being
live, and a second path to Active made the other six decorative. It was also the path the
Policy Designer's own Approve and Activate buttons used, so the bypass was the normal way.

Approved and Active are now the flow's to set. What stays direct is everything that makes
no rule real: Draft -> Pending to hand it over, Pending -> Draft to take it back, and
Retire with a reason. None of those can change what the resolver returns for anybody.

DOOR TWO. Field definitions saved straight to live. A custom field decides what is
mandatory on an employee record, what is masked, what validates and what leaves the company
in an export, and "make blood group mandatory" or "unmask the PAN" took effect the moment
one person clicked Save. `field_definition` is now a governed entity type with a handler --
off by default, because a field change cannot move money and companies add fields
constantly during onboarding, so `governed_config_types` is the switch a company that wants
the control turns on.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_gap5_config_governance   (from backend/)
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
from app.services.hrms.tests.governance_helper import activate_policy_version  # noqa: E402

CO = "C1"
DRAFTER = {"_id": "cfg-1", "role": "superadmin", "governance_role": "HR",
           "full_name": "Dummy Config Drafter"}
APPROVER = {"_id": "cfg-2", "role": "superadmin", "governance_role": "MD",
            "full_name": "Dummy Config Approver"}


async def main() -> int:
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_audit_service as AU
    import app.services.hrms_config_change_service as CC
    import app.services.hrms_config_dependency_service as DEP
    import app.services.hrms_employee_master_service as EM
    import app.services.hrms_policy_version_service as PV

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (AU, CC, DEP, EM, PV):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    for mod in (CC, EM, PV):
        mod.audit = no_audit

    # ── 0. What is governed, and what cannot be un-governed ──────────────────────────
    section("0. The governed-types registry and its floor")

    check("policy versions and salary components are governed out of the box",
          await CC.governed_types(CO) == {"policy_version", "salary_component"},
          await CC.governed_types(CO))
    check("field definitions are NOT, so onboarding is not a queue",
          not await CC.is_governed(CO, M.CONFIG_ENTITY_FIELD_DEFINITION))
    check("every known type has a handler -- a governed type with none would 422 "
          "every save of it",
          set(M.CONFIG_ENTITY_TYPES) == set(CC.ENTITY_HANDLERS),
          set(M.CONFIG_ENTITY_TYPES) ^ set(CC.ENTITY_HANDLERS))

    await expect("naming a type nothing handles",
                 CC.set_governed_types(APPROVER, CO, ["policy_version", "pay_slip_colour"]),
                 422, "unknown configuration type")
    # Un-governing the pay-deciding types is what somebody wanting to bypass the flow
    # would try first, so the service adds them back whatever is posted.
    relaxed = await CC.set_governed_types(APPROVER, CO, [])
    check("an empty list cannot switch governance off for pay-deciding types",
          relaxed["governed_config_types"] == ["policy_version", "salary_component"],
          relaxed)

    # ── 1. The direct status endpoint ───────────────────────────────────────────────
    section("1. Approved and Active are the flow's to set")

    await PV.save_definition(DRAFTER, CO, {"code": M.POLICY_ATT_DAY, "name": "Daily rules",
                                           "module": "attendance"})
    await PV.save_draft(DRAFTER, CO, {
        "policy_code": M.POLICY_ATT_DAY, "effective_from": "2026-01-01",
        "rules": {"half_day_fraction": 0.25}, "change_reason": "Softer half day"})

    handed = await PV.set_status(DRAFTER, CO, M.POLICY_ATT_DAY, 1, "Pending Approval")
    check("handing a draft to an approver is still a direct call -- it makes no rule real",
          handed["status"] == "Pending Approval", handed["status"])
    taken = await PV.set_status(DRAFTER, CO, M.POLICY_ATT_DAY, 1, "Draft")
    check("...and so is taking it back", taken["status"] == "Draft", taken["status"])

    await PV.set_status(DRAFTER, CO, M.POLICY_ATT_DAY, 1, "Pending Approval")
    await expect("approving a governed version directly",
                 PV.set_status(APPROVER, CO, M.POLICY_ATT_DAY, 1, "Approved"),
                 409, "change request")
    check("the version is still Pending -- the refusal wrote nothing",
          (await PV.list_versions(CO, M.POLICY_ATT_DAY))[0]["status"] == "Pending Approval")
    check("...and nothing resolves against it yet",
          await PV.resolve(CO, M.POLICY_ATT_DAY, {}, "2026-06-01") is None)

    # ── 2. The flow's own activation still works, and only with two people ──────────
    section("2. The flow is the only way through, and needs two people")

    from app.models.hrms import CONFIG_ENTITY_POLICY_VERSION

    async def fake_id(kind, company, year):
        fake_id.n = getattr(fake_id, "n", 0) + 1
        return f"CFG-{fake_id.n:04d}"
    CC.next_business_id = fake_id

    req = await CC.create_request(DRAFTER, CO, {
        "entity_type": CONFIG_ENTITY_POLICY_VERSION, "entity_code": M.POLICY_ATT_DAY,
        "version_no": 1, "reason": "Client asked for a quarter-day half day"})
    await expect("submitting before the impact analysis has run",
                 CC.submit(DRAFTER, CO, req["request_no"]),
                 409, "run the impact analysis")
    await CC.analyse_impact(DRAFTER, CO, req["request_no"])
    await CC.submit(DRAFTER, CO, req["request_no"])
    await expect("the drafter approving their own change",
                 CC.decide(DRAFTER, CO, req["request_no"], {"action": "approve"}),
                 403, "someone else's to give")
    await CC.decide(APPROVER, CO, req["request_no"],
                    {"action": "approve", "comments": "Agreed"})
    await CC.activate(APPROVER, CO, req["request_no"])
    live = await PV.resolve(CO, M.POLICY_ATT_DAY, {}, "2026-06-01")
    check("the activated version is live and resolvable",
          live and live["version_no"] == 1
          and live["rules"]["half_day_fraction"] == 0.25, live)

    # Retiring is still direct: it stops a rule being used and breaks nothing that used it.
    await PV.save_draft(DRAFTER, CO, {
        "policy_code": M.POLICY_ATT_DAY, "effective_from": "2027-01-01", "rules": {}})
    await expect("retiring with no reason", PV.set_status(
        DRAFTER, CO, M.POLICY_ATT_DAY, 2, "Retired"), 422, "say why")
    retired = await PV.set_status(DRAFTER, CO, M.POLICY_ATT_DAY, 2, "Retired",
                                  "Drafted in error")
    check("retiring with a reason stays a direct call",
          retired["status"] == "Retired", retired["status"])

    # ── 3. Field definitions, ungoverned: unchanged behaviour ───────────────────────
    section("3. Ungoverned field definitions behave exactly as before")

    await EM.save_field_definition(DRAFTER, CO, {
        "module": "employee", "code": "blood_group", "label": "Blood Group",
        "data_type": "Text"})
    activated = await EM.set_field_status(DRAFTER, CO, "employee", "blood_group",
                                          {"status": "Active"})
    check("a field is drafted and activated in one step when ungoverned",
          activated["status"] == "Active", activated["status"])
    edited = await EM.save_field_definition(DRAFTER, CO, {
        "module": "employee", "code": "blood_group", "label": "Blood group",
        "data_type": "Text", "sensitive": True, "mandatory": False})
    check("...and an edit to a live field applies immediately",
          edited["sensitive"] is True and edited.get("pending_definition") is None, edited)

    # ── 4. Field definitions, governed: not live until approved and activated ───────
    section("4. A governed field change is not live until activated")

    turned_on = await CC.set_governed_types(
        APPROVER, CO, ["policy_version", "salary_component", "field_definition"])
    check("the toggle adds field definitions to the governed set",
          "field_definition" in turned_on["governed_config_types"], turned_on)

    await expect("a governed field change with no business reason",
                 EM.save_field_definition(DRAFTER, CO, {
                     "module": "employee", "code": "blood_group", "label": "Blood group",
                     "data_type": "Text", "sensitive": False}),
                 422, "say why")

    # The change worth governing: unmask a sensitive field AND make it mandatory. One
    # makes medical data readable to anyone who can see the record, the other fails
    # validation on every record that has no value.
    staged = await EM.save_field_definition(DRAFTER, CO, {
        "module": "employee", "code": "blood_group", "label": "Blood group",
        "data_type": "Text", "sensitive": False, "mandatory": True,
        "change_reason": "Ops want it visible and compulsory"})
    check("the change is STAGED, not applied",
          staged["pending_definition"] == {"sensitive": False, "mandatory": True},
          staged.get("pending_definition"))
    check("the live definition is untouched -- it masks and validates as before",
          staged["sensitive"] is True and staged["mandatory"] is False,
          {"sensitive": staged.get("sensitive"), "mandatory": staged.get("mandatory")})
    check("...and the field names the request holding it up",
          staged["pending_request_no"] is not None, staged.get("pending_request_no"))

    field_req = staged["pending_request_no"]
    impact = (await CC.analyse_impact(DRAFTER, CO, field_req))["impact"]
    check("the impact analysis warns that the field stops being masked",
          any("masked" in w for w in impact["warnings"]), impact["warnings"])
    check("...and that it becomes mandatory, which is what fails existing records",
          any("MANDATORY" in w for w in impact["warnings"]), impact["warnings"])

    await CC.submit(DRAFTER, CO, field_req)
    await expect("the drafter approving their own field change",
                 CC.decide(DRAFTER, CO, field_req, {"action": "approve"}),
                 403, "someone else's to give")
    await CC.decide(APPROVER, CO, field_req, {"action": "approve", "comments": "Fine"})

    still = (await EM.list_field_definitions(CO, "employee"))[0]
    check("APPROVED is still not live -- activation is a separate stage (FRD 27)",
          still["sensitive"] is True and still["mandatory"] is False, still)

    done = await CC.activate(APPROVER, CO, field_req)
    applied = (await EM.list_field_definitions(CO, "employee"))[0]
    check("activation applies the staged definition",
          applied["sensitive"] is False and applied["mandatory"] is True, applied)
    check("...and clears the staging, so the field is not stuck pending",
          applied.get("pending_definition") is None
          and applied.get("pending_request_no") is None, applied)
    check("the request records the old and new definition (FRD 30)",
          done["definition_change"]["old"]["sensitive"] is True
          and done["definition_change"]["new"]["sensitive"] is False,
          done.get("definition_change"))
    check("the field's own history carries the change and the request that carried it",
          applied["history"][-1]["via"] == field_req
          and applied["history"][-1]["new"]["sensitive"] is False,
          applied["history"][-1])

    # ── 5. Direct activation of a governed field ────────────────────────────────────
    section("5. A governed field cannot be activated directly either")

    await EM.save_field_definition(DRAFTER, CO, {
        "module": "employee", "code": "shirt_size", "label": "Shirt Size",
        "data_type": "Text"})
    await expect("activating a governed Draft field directly",
                 EM.set_field_status(DRAFTER, CO, "employee", "shirt_size",
                                     {"status": "Active"}),
                 409, "change request")
    draft = next(f for f in await EM.list_field_definitions(CO, "employee")
                 if f["code"] == "shirt_size")
    check("it is still a Draft, so nothing collects it yet",
          draft["status"] == "Draft", draft["status"])
    # A DRAFT field has never been live, so editing it needs no approver -- the same
    # reasoning the component lifecycle uses.
    tweaked = await EM.save_field_definition(DRAFTER, CO, {
        "module": "employee", "code": "shirt_size", "label": "T-shirt size",
        "data_type": "Text"})
    check("a Draft field is still edited freely, even when the type is governed",
          tweaked["label"] == "T-shirt size"
          and tweaked.get("pending_definition") is None, tweaked)

    # Retiring stays direct: a field that should not be collected any more should not
    # have to wait for an approver.
    retired_field = await EM.set_field_status(DRAFTER, CO, "employee", "blood_group",
                                              {"status": "Retired", "reason": "No longer collected"})
    check("retiring a governed field stays a direct call",
          retired_field["status"] == "Retired", retired_field["status"])

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
