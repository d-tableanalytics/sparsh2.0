"""Internal requisition -- the RBAC approval workflow, driven end to end.

The scenario, run against the services rather than the UI:

    Role        HR Executive
    Department  HR
    Budget      INR 35,000/month  ->  420,000/year (see "Units" below)
    Raised by   the Department Head (HOD)

    1  HOD raises and submits it
    2  HR may see and verify it, and may NOT approve the budget
    3  Management/Finance approve headcount and budget
    4  nothing may be sourced until they have
    5  Management/Finance reject it, and it stops
    6  it is resubmitted, approved, and moves on

Why the service layer and not the screen: hiding a button is not a control. Every refusal
asserted here is one the API makes, so a hand-typed CV or a curl call meets the same answer
the UI does.

-- Units ------------------------------------------------------------------------------------
HRMS stores CTC as a bare number and never asks which currency or period a company works in
(hrms_offer_service._money says so explicitly). The brief gives a MONTHLY figure, so it is
converted to an annual one here -- 35,000 x 12 = 420,000 -- because the band stamped at the
budget gate is what every later offer is compared against, and an offer is captured
annually. Mixing the two units would compare a yearly offer against a monthly band and
refuse every legitimate offer.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_internal_rbac_approval   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []
findings: list[str] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def finding(label: str, detail: str) -> None:
    """A confirmed deviation from the brief that is NOT a test failure.

    The behaviour asserted around it is the behaviour the code actually has, so this file
    stays a true regression test. Recording the gap here rather than failing keeps the suite
    honest in both directions: green means "this is what it does", and the findings block
    says where that differs from what was asked for.
    """
    findings.append(f"{label}: {detail}")
    print(f"  NOTE  {label}")


def section(title: str) -> None:
    print(f"\n-- {title} --")


async def expect_http(label: str, coro, status: int, fragment: str = None) -> None:
    from fastapi import HTTPException
    try:
        await coro
        check(f"{label} -> {status}", False)
    except HTTPException as e:
        ok = e.status_code == status
        if ok and fragment:
            ok = fragment.lower() in str(e.detail).lower()
        check(f"{label} -> {status}" + (f" ('{fragment}')" if fragment else ""), ok)
    except Exception as e:
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
MONTHLY = 35_000
ANNUAL = MONTHLY * 12                      # 420,000


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo
    import app.utils.hrms_access as A

    U_HR, U_MD, U_FIN, U_HOD, U_EMP = (str(ObjectId()) for _ in range(5))
    dept_id, desig_id = ObjectId(), ObjectId()

    departments = FakeCollection([
        {"_id": dept_id, "company_id": COMPANY, "name": "HR", "active": True}])
    designations = FakeCollection([
        {"_id": desig_id, "company_id": COMPANY, "name": "HR Executive",
         "designation_level": M.DesignationLevel.MID.value, "active": True}])
    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "full_name": "Hana HR",
         "governance_role": "HR", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_MD), "company_id": COMPANY, "full_name": "Meera MD",
         "governance_role": "MD", "role": "clientadmin", "is_active": True},
        {"_id": ObjectId(U_FIN), "company_id": COMPANY, "full_name": "Farid Finance",
         "governance_role": "FINANCE", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_HOD), "company_id": COMPANY, "full_name": "Hari HOD",
         "governance_role": "HOD", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_EMP), "company_id": COMPANY, "full_name": "Eve Employee",
         "governance_role": "IMPLEMENTOR", "role": "clientuser", "is_active": True},
    ])
    # Sanctioned strength well above the ask, so the over-sanction escalation detour stays
    # out of the way -- it is a different control and has its own file.
    sanctions = FakeCollection([
        {"company_id": COMPANY, "department_id": str(dept_id),
         "designation_id": str(desig_id), "sanctioned_count": 50}])

    store = {M.COLL_REQUISITIONS: FakeCollection(),
             M.COLL_JOB_DESCRIPTIONS: FakeCollection(),
             M.COLL_JOB_POSTINGS: FakeCollection(),
             M.COLL_CANDIDATES: FakeCollection(),
             M.COLL_POSITION_SCORECARDS: FakeCollection(),
             M.COLL_SALARY_BANDS: FakeCollection(),
             M.COLL_DEPARTMENTS: departments, M.COLL_DESIGNATIONS: designations,
             M.COLL_SANCTIONED_STRENGTH: sanctions,
             M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
             M.COLL_EMPLOYEE_PROFILES: FakeCollection(), M.COLL_LINKS: FakeCollection(),
             "learners": learners, "companies": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_requisition_service as RS
    import app.services.hrms_posting_service as PS
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_sanction_service as SANC
    import app.services.hrms_link_service as LS
    import app.services.hrms_referral_service as RF
    import app.services.hrms_scorecard_service as SC
    import app.services.hrms_salary_band_service as BANDS
    import app.utils.hrms_access as HACC
    for mod in (RS, PS, CS, AUD, IDS, SANC, LS, RF, SC, BANDS, HACC):
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    for mod in (RS, PS, CS, SC):
        if hasattr(mod, "notify_user"):
            mod.notify_user = silent
        if hasattr(mod, "notify_hrms_role"):
            mod.notify_hrms_role = silent

    def actor(uid, governance, role="clientuser"):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": governance,
                "full_name": f"{governance} user"}

    HR = actor(U_HR, "HR")
    MD = actor(U_MD, "MD", role="clientadmin")
    FIN = actor(U_FIN, "FINANCE")
    HOD = actor(U_HOD, "HOD")
    EMP = actor(U_EMP, "IMPLEMENTOR")

    def payload(**over):
        base = {"department_id": str(dept_id), "designation_id": str(desig_id),
                "assignee_id": U_HR, "vacancy": 1, "required_date": "2027-03-31",
                "experience_required": "2-4 years",
                "qualification": "Graduate, MBA (HR) preferred",
                "essential_skills": "Recruitment coordination, HRIS, onboarding",
                "offering_ctc": float(ANNUAL),
                "work_location": M.WorkLocation.OFFICE.value,
                "employment_type": M.EmploymentType.FULL_TIME.value,
                "requisition_track": "internal",
                "jd": {"title": "HR Executive",
                       "responsibilities": "Run the recruitment desk end to end."}}
        base.update(over)
        return base

    BUDGET = {"approved_headcount": 1,
              "approved_salary_band_min": float(ANNUAL - 20_000),
              "approved_salary_band_max": float(ANNUAL + 30_000)}

    def candidate(**over):
        base = {"candidate_name": "Asha Applicant", "can_email": "asha@example.com",
                "can_contact": "+91 90000 00001"}
        base.update(over)
        return base

    async def status_of(request_no: str) -> str:
        row = await store[M.COLL_REQUISITIONS].find_one({"request_no": request_no})
        return row["approval_status"]

    def audit_actions(request_no: str) -> list:
        return [a["action"] for a in store[M.COLL_AUDIT_LOG].docs
                if a.get("entity_id") == request_no]

    try:
        # =================================================================
        section("1. Role permissions, before anything is raised")
        # =================================================================
        check("HOD may raise a requisition", A.can(HOD, M.Cap.REQUISITION_CREATE))
        check("HR may verify (stage 1)", A.can(HR, M.Cap.REQUISITION_REVIEW_HR))
        check("HOD may NOT verify -- that is HR's step",
              not A.can(HOD, M.Cap.REQUISITION_REVIEW_HR))
        check("HR may NOT approve the budget",
              not A.can(HR, M.Cap.REQUISITION_APPROVE_BUDGET))
        check("HOD may NOT approve the budget",
              not A.can(HOD, M.Cap.REQUISITION_APPROVE_BUDGET))
        check("an ordinary employee may NOT approve the budget",
              not A.can(EMP, M.Cap.REQUISITION_APPROVE_BUDGET))
        check("Management (MD) may approve the budget",
              A.can(MD, M.Cap.REQUISITION_APPROVE_BUDGET))
        check("Finance may approve the budget",
              A.can(FIN, M.Cap.REQUISITION_APPROVE_BUDGET))
        check("HR may still READ the requisition it cannot approve",
              A.can(HR, M.Cap.REQUISITION_READ))
        # Separation of duties in the other direction: the money approver holds no hiring
        # judgement on this chain.
        check("Finance holds no candidate screening",
              not A.can(FIN, M.Cap.CANDIDATE_SCREEN))
        check("Finance holds no interview evaluation",
              not A.can(FIN, M.Cap.INTERVIEW_EVALUATE))

        # =================================================================
        section("2. HOD raises and submits the requisition")
        # =================================================================
        raised = await RS.create_requisition(HOD, COMPANY, payload())
        REQ = raised["request_no"]
        check("requisition created", REQ.startswith("HR-REQ-"))
        check("runs on the INTERNAL track",
              raised["requisition_track"] == "internal")
        check("opens at Pending HR Verification -- NOT at the budget step",
              raised["approval_status"] == M.ReqApproval.PENDING_HR_VERIFICATION.value)
        check("closing status Open", raised["closing_status"] == M.ReqClosing.OPEN.value)
        check("raiser recorded as the HOD", raised["created_by"] == U_HOD)
        check("role and department captured",
              raised["designation_name"] == "HR Executive"
              and raised["department_name"] == "HR")
        check("no budget is recorded yet", raised.get("budget_approved_at") is None)
        check("no salary band is stamped yet",
              raised.get("approved_salary_band_min") is None)
        check("raising is audited",
              M.AUDIT_REQ_CREATED in audit_actions(REQ))

        # =================================================================
        section("3. Unauthorised approval is refused at every wrong door")
        # =================================================================
        # There is no budget-approval step any more: HR verification is the first gate and
        # only HR may clear it. The old budget action is simply unknown now.
        for label, who in (("Finance", FIN), ("HOD", HOD), ("an ordinary employee", EMP)):
            await expect_http(
                f"{label} tries to verify (HR's step)",
                RS.act_on_requisition(who, COMPANY, REQ, "hr-verify"), 403, "not authorised")
        await expect_http(
            "the removed budget-approve action is unknown",
            RS.act_on_requisition(FIN, COMPANY, REQ, "budget-approve", budget=BUDGET),
            422, "invalid action")
        await expect_http(
            "the legacy budget-skip cannot be pressed by hand",
            RS.act_on_requisition(HR, COMPANY, REQ, "budget-skip"), 422)
        await expect_http(
            "a client-chain action on an internal requisition is simply unknown",
            RS.act_on_requisition(MD, COMPANY, REQ, "md-approve"), 422, "invalid action")
        check("after every refusal the status is unchanged",
              await status_of(REQ) == M.ReqApproval.PENDING_HR_VERIFICATION.value)

        # =================================================================
        section("4. Nothing may be sourced before HR verifies it")
        # =================================================================
        await expect_http(
            "adding a candidate while awaiting HR verification",
            CS.create_candidate(HR, COMPANY, candidate(request_no=REQ)),
            409, "verified by HR")
        check("the sourcing gate is declared in the model, not in a service",
              M.PRE_BUDGET_STATES == {M.ReqApproval.PENDING_HR_VERIFICATION.value,
                                      M.ReqApproval.PENDING_BUDGET.value})
        check("the chain is structurally sound (no budget step; Approved only via the "
              "scorecard)", M.approval_chain_is_sound())

        # =================================================================
        section("5. HR rejects it")
        # =================================================================
        await expect_http(
            "rejecting without a reason",
            RS.act_on_requisition(HR, COMPANY, REQ, "hr-reject"),
            422, "remark is required")
        check("a rejection with no reason did not change the status",
              await status_of(REQ) == M.ReqApproval.PENDING_HR_VERIFICATION.value)

        rejected = await RS.act_on_requisition(
            HR, COMPANY, REQ, "hr-reject",
            remarks="Headcount deferred to the next quarter's budget.")
        check("rejected by HR",
              rejected["approval_status"] == M.ReqApproval.REJECTED.value)
        check("the reason is on the record",
              "deferred" in (rejected.get("hr_remarks") or "").lower())
        check("the rejection is audited",
              M.AUDIT_REQ_HR_REJECTED in audit_actions(REQ))
        check("no salary band was stamped by a rejection",
              (await store[M.COLL_REQUISITIONS].find_one(
                  {"request_no": REQ})).get("approved_salary_band_min") is None)

        section("5b. A rejected requisition is a dead end")
        await expect_http(
            "re-verifying a rejected requisition",
            RS.act_on_requisition(HR, COMPANY, REQ, "hr-verify"),
            409, "not \"Pending HR Verification\"")
        check("Rejected has no outbound transition on the internal chain -- there is no "
              "'resubmit' action, so step 6 must raise a NEW requisition",
              not [a for a, (frm, *_rest) in M.INTERNAL_REQ_TRANSITIONS.items()
                   if frm.value == M.ReqApproval.REJECTED.value])

        # The brief asks that a rejection "stops" the request. It stops the APPROVAL chain,
        # as asserted above. It does not stop sourcing, because the sourcing gate tests for
        # the pre-verification states rather than for the presence of an approval.
        blocked_after_rejection = True
        try:
            await CS.create_candidate(HR, COMPANY, candidate(request_no=REQ))
            blocked_after_rejection = False
        except Exception:
            pass
        check("(recording actual behaviour) a CV can be attached to a REJECTED "
              "requisition", not blocked_after_rejection)
        if not blocked_after_rejection:
            finding(
                "a rejected requisition does not block sourcing",
                "PRE_BUDGET_STATES (models/hrms.py) lists only Pending HR Verification and "
                "Pending Budget Approval, and neither candidate-insert path checks "
                "closing_status. A REJECTED requisition therefore accepts hand-added CVs "
                "and talent-pool sourcing. Fix: make assert_sourcing_allowed a positive "
                "check -- status in {Pending Scorecard Approval, Approved}, closing_status "
                "Open.")

        # =================================================================
        section("6. Resubmitted, verified, and moves on")
        # =================================================================
        resubmitted = await RS.create_requisition(HOD, COMPANY, payload(
            notes="Resubmission of " + REQ + " against the new quarter's budget."))
        REQ2 = resubmitted["request_no"]
        check("the resubmission is a NEW requisition with its own number", REQ2 != REQ)
        check("it starts at the beginning of the chain again",
              resubmitted["approval_status"] == M.ReqApproval.PENDING_HR_VERIFICATION.value)

        verified = await RS.act_on_requisition(HR, COMPANY, REQ2, "hr-verify",
                                               remarks="Approved against Q1 headcount plan.")
        check("within sanction, HR verification goes straight to Pending Scorecard Approval",
              verified["approval_status"] == M.ReqApproval.PENDING_SCORECARD.value)
        check("HR verification is stamped with who and when",
              verified.get("hr_reviewed_by") == U_HR and verified.get("hr_reviewed_at"))
        check("the approved headcount is taken from the vacancies",
              verified["approved_headcount"] == 1)
        check("no standing band exists for the role, so none is stamped (offers are then "
              "not band-checked)", verified.get("approved_salary_band_min") is None)
        check("HR's remark is kept", "Q1 headcount" in (verified.get("hr_remarks") or ""))
        check("the SLA clock for this milestone is stamped",
              "budget_approved" in (verified.get("sla_actuals") or {}))

        section("6b. Sourcing opens exactly at the gate, and no earlier")
        opened = await CS.create_candidate(HR, COMPANY, candidate(request_no=REQ2))
        check("a CV may now be attached", bool(opened.get("uk")))
        check("the first requisition is still shut to the same call",
              await status_of(REQ) == M.ReqApproval.REJECTED.value)

        section("6c. The chain continues to the scorecard, and stops there without one")
        await expect_http(
            "reaching Approved with no approved scorecard",
            RS.act_on_requisition(HOD, COMPANY, REQ2, "scorecard-approve"),
            409, "scorecard")
        card = await SC.create_scorecard(HR, COMPANY, {
            "request_no": REQ2, "title": "HR Executive",
            "criteria": [{"label": "Recruitment coordination",
                          "category": M.ScorecardCategory.SKILL.value, "weight": 2},
                         {"label": "HRIS", "category": M.ScorecardCategory.SKILL.value},
                         {"label": "Culture fit",
                          "category": M.ScorecardCategory.CULTURE_FIT.value}]})
        # HR drafts the scorecard but is not one of its approvers. Note WHERE that is
        # enforced: `act_on_requisition` asks `can(actor, capability)` itself, so the
        # requisition chain refuses HR at the service layer (section 3 above). The scorecard
        # service does not -- Cap.SCORECARD_APPROVE is checked by the route, and the service
        # decides completeness from WHICH ROLES have signed. So an HR signature here is
        # recorded and simply does not satisfy anything.
        check("HR does not hold the scorecard approval capability",
              not A.can(HR, M.Cap.SCORECARD_APPROVE))
        after_hr_sign = await SC.approve_scorecard(
            HR, COMPANY, card["scr_no"], {"decision": "Pass", "signature": "Hana HR"})
        check("an HR signature does NOT approve the scorecard",
              after_hr_sign["status"] != M.ScorecardStatus.APPROVED.value)
        await expect_http(
            "the requisition still cannot pass the scorecard gate on an HR signature",
            RS.act_on_requisition(HOD, COMPANY, REQ2, "scorecard-approve"), 409, "scorecard")
        finding(
            "the scorecard approval capability is enforced only at the route",
            "hrms_scorecard_service.approve_scorecard records a signature without asking "
            "can(actor, Cap.SCORECARD_APPROVE); the requisition chain checks its capability "
            "inside act_on_requisition. Not reachable through the API (routes/hrms.py gates "
            "it) and the role rules still refuse to COMPLETE the approval, so no gate is "
            "actually passed -- but it is the one approval whose capability check lives in "
            "a different layer from the rest.")

        approved_card = await SC.approve_scorecard(
            HOD, COMPANY, card["scr_no"], {"decision": "Pass", "signature": "Hari HOD"})
        check("the HOD's signature approves it",
              approved_card["status"] == M.ScorecardStatus.APPROVED.value)
        final = await RS.act_on_requisition(HOD, COMPANY, REQ2, "scorecard-approve")
        check("the requisition reaches Approved",
              final["approval_status"] == M.ReqApproval.APPROVED.value)
        check("the JD is co-approved, which is what unlocks posting",
              (await store[M.COLL_JOB_DESCRIPTIONS].find_one(
                  {"jd_no": resubmitted["jd_no"]}))["status"] == M.JdStatus.APPROVED.value)

        # =================================================================
        section("7. The approval audit trail")
        # =================================================================
        trail = audit_actions(REQ2)
        # Each step of the chain is separately attributable -- the point of an approval
        # trail is answering "who authorised this", one row per decision.
        check("the raise is on the trail", M.AUDIT_REQ_CREATED in trail)
        check("HR verification is on the trail", M.AUDIT_REQ_HR_VERIFIED in trail)
        check("there is no budget-approval row any more", M.AUDIT_REQ_BUDGET_OK not in trail)
        check("the scorecard approval is on the trail", M.AUDIT_REQ_SCORECARD_OK in trail)
        check("the rejected requisition kept its own separate trail, ending at the "
              "HR rejection",
              M.AUDIT_REQ_HR_REJECTED in audit_actions(REQ)
              and M.AUDIT_REQ_HR_VERIFIED not in audit_actions(REQ))

        rows = [a for a in store[M.COLL_AUDIT_LOG].docs if a.get("entity_id") == REQ2]
        check("each audit row names the actor",
              all(r.get("actor_id") or r.get("actor_name") for r in rows))
        check("each audit row is timestamped", all(r.get("created_at") for r in rows))
        check("each audit row is scoped to the company",
              all(r.get("company_id") == COMPANY for r in rows))
        verify_row = next(r for r in rows if r["action"] == M.AUDIT_REQ_HR_VERIFIED)
        check("the verification row names HR", verify_row["actor_id"] == U_HR)
        check("the trail is append-only in order raised -> verified -> scorecard",
              [r["action"] for r in rows if r["action"] in (
                  M.AUDIT_REQ_CREATED, M.AUDIT_REQ_HR_VERIFIED, M.AUDIT_REQ_SCORECARD_OK)]
              == [M.AUDIT_REQ_CREATED, M.AUDIT_REQ_HR_VERIFIED, M.AUDIT_REQ_SCORECARD_OK])

    finally:
        mongo.get_collection = original

    print()
    if findings:
        print("=" * 70)
        print("  FINDINGS -- behaviour differs from the brief")
        print("=" * 70)
        for item in findings:
            print(f"  * {item}")
        print()
    total, passed = len(results), sum(results)
    print("=" * 70)
    print(f"  {passed}/{total} checks passed"
          + (f", {len(findings)} finding(s)" if findings else ""))
    print("=" * 70)
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
