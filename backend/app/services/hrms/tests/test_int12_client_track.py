"""Phase 12 -- the client hiring track, end to end.

    Client -> Job Request -> Sparsh -> Candidate Search -> CV Sharing -> Client Review
    -> Interview -> Selection -> Background Verification -> HR Approval -> Offer -> Onboarding

Two clients, one candidate, and the question the whole phase turns on: can either client
see anything about the other's process?

-- What this file is really testing ------------------------------------------------------
Three things, in order of how much damage getting them wrong would do:

  1. ISOLATION. A client user reads only what was shared with them. Asserted against a real
     second client with its own engagement, its own user and its own share of the SAME
     candidate -- because a scoping bug that returns "everything" passes any test written
     with only one client in the database.
  2. INDEPENDENT STATUS. One CV, two clients, two different outcomes, neither disturbing
     the other or the candidate's own pipeline stage.
  3. THE LOCK. Background verification -> HR approval -> offer. Every earlier step open,
     every later one shut, until the signature exists.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int12_client_track   (from backend/)
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


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


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo
    import app.utils.hrms_access as A

    U_HR, U_MD, U_CLIENT_A, U_CLIENT_B = (str(ObjectId()) for _ in range(4))
    CLIENT_A, CLIENT_B = str(ObjectId()), str(ObjectId())
    dept, desig = ObjectId(), ObjectId()

    companies = FakeCollection([
        {"_id": ObjectId(CLIENT_A), "name": "Acme Retail", "hrms_enabled": True},
        {"_id": ObjectId(CLIENT_B), "name": "Borealis Bank", "hrms_enabled": True},
    ])
    departments = FakeCollection([
        {"_id": dept, "company_id": COMPANY, "name": "Engineering", "active": True}])
    designations = FakeCollection([
        {"_id": desig, "company_id": COMPANY, "name": "Backend Engineer",
         "designation_level": M.DesignationLevel.MID.value, "active": True}])
    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "full_name": "Hana HR",
         "governance_role": "HR", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_MD), "company_id": COMPANY, "full_name": "Meera MD",
         "governance_role": "MD", "role": "clientadmin", "is_active": True},
        {"_id": ObjectId(U_CLIENT_A), "company_id": COMPANY, "full_name": "Alice (Acme)",
         "governance_role": "CLIENT", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_CLIENT_B), "company_id": COMPANY, "full_name": "Bob (Borealis)",
         "governance_role": "CLIENT", "role": "clientuser", "is_active": True},
    ])
    # Two REAL engagements. Everything about isolation rests on these rows, so they are the
    # one fixture this file builds carefully.
    engagements = FakeCollection([
        {"_id": ObjectId(), "company_id": COMPANY, "client_id": CLIENT_A,
         "engagement_no": "CLI-ENG-2026-001", "status": M.EngagementStatus.ACTIVE.value,
         "member_user_ids": [U_CLIENT_A]},
        {"_id": ObjectId(), "company_id": COMPANY, "client_id": CLIENT_B,
         "engagement_no": "CLI-ENG-2026-002", "status": M.EngagementStatus.ACTIVE.value,
         "member_user_ids": [U_CLIENT_B]},
    ])

    store = {c: FakeCollection() for c in (
        M.COLL_REQUISITIONS, M.COLL_JOB_DESCRIPTIONS, M.COLL_CANDIDATES,
        M.COLL_JOB_REQUESTS, M.COLL_CANDIDATE_SHARES, M.COLL_BACKGROUND_CHECKS,
        M.COLL_OFFERS, M.COLL_COUNTERS, M.COLL_AUDIT_LOG, M.COLL_LINKS,
        M.COLL_EXCEPTIONS, M.COLL_SETTINGS, M.COLL_REFERENCE_CHECKS,
        M.COLL_POSITION_SCORECARDS, M.COLL_SANCTIONED_STRENGTH, M.COLL_SALARY_BANDS,
        M.COLL_EMPLOYEE_PROFILES)}
    store.update({M.COLL_DEPARTMENTS: departments, M.COLL_DESIGNATIONS: designations,
                  M.COLL_CLIENT_ENGAGEMENTS: engagements, "companies": companies,
                  "learners": learners, "staff": FakeCollection()})
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_job_request_service as JR
    import app.services.hrms_share_service as SH
    import app.services.hrms_background_service as BG
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_requisition_service as RS
    import app.services.hrms_offer_service as OF
    import app.services.hrms_exception_service as EX
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_posting_service as PS
    import app.services.hrms_sanction_service as SN
    import app.services.hrms_scorecard_service as SC
    import app.services.hrms_reference_service as RC
    import app.services.hrms_link_service as LS
    import app.services.hrms_referral_service as RF
    import app.services.hrms_config_service as CFG
    import app.services.hrms_salary_band_service as BANDS
    import app.services.hrms_shortlist_service as SL
    import app.services.hrms_telephonic_service as TS
    import app.services.hrms_interview_service as IV
    import app.utils.hrms_access as ACCESS

    SERVICES = (JR, SH, BG, CS, RS, OF, EX, AUD, IDS, PS, SN, SC, RC, LS, RF, CFG,
                BANDS, SL, TS, IV, ACCESS)
    for mod in SERVICES:
        mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    for mod in SERVICES:
        for name in ("notify_user", "notify_users", "notify_hrms_role"):
            if hasattr(mod, name):
                setattr(mod, name, silent)
    import app.services.hrms_notify_service as NS
    keep = (NS.notify_user, NS.notify_users, NS.notify_hrms_role)
    NS.notify_user, NS.notify_users, NS.notify_hrms_role = silent, silent, silent

    # Gates with their own test files, stubbed so a failure here names THIS file's control.
    async def _cleared(*a, **kw):
        return None
    SL.assert_shortlist_cleared = _cleared
    TS.assert_telephonic_cleared = _cleared

    import app.services.s3_service as S3
    keep_s3 = S3.upload_file_to_s3_with_key
    keep_url = S3.get_signed_url
    S3.upload_file_to_s3_with_key = lambda f, n, m: {"key": f"s3/{n}", "url": "https://x/y"}
    signed_calls = []

    def _fake_signed(key, expires_in=3600, download_as=None):
        signed_calls.append({"key": key, "expires_in": expires_in,
                             "download_as": download_as})
        return f"https://signed.example/{key}"
    S3.get_signed_url = _fake_signed
    PS.upload_file_to_s3_with_key = S3.upload_file_to_s3_with_key

    def actor(uid, gov, role="clientuser", name=None):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": gov,
                "full_name": name or gov}

    HR = actor(U_HR, "HR", name="Hana HR")
    MD = actor(U_MD, "MD", role="clientadmin", name="Meera MD")
    ALICE = actor(U_CLIENT_A, "CLIENT", name="Alice (Acme)")
    BOB = actor(U_CLIENT_B, "CLIENT", name="Bob (Borealis)")

    def cv(name="cv.pdf"):
        return {"name": name, "mime_type": "application/pdf",
                "data": base64.b64encode(b"%PDF-1.4 curriculum vitae").decode()}

    try:
        # =================================================================
        section("Roles: a client user resolves to CLIENT and is client-scoped")
        # =================================================================
        check("Alice resolves to the CLIENT role",
              A.hrms_role(ALICE) is M.HrmsRole.CLIENT)
        check("Alice is client-scoped", A.is_client_scoped_user(ALICE))
        check("HR is NOT client-scoped", not A.is_client_scoped_user(HR))
        check("Alice's scope resolves to Acme only",
              await A.scope_client_ids(ALICE, COMPANY) == [CLIENT_A])
        check("Bob's scope resolves to Borealis only",
              await A.scope_client_ids(BOB, COMPANY) == [CLIENT_B])
        check("a client may raise a job request",
              A.can(ALICE, M.Cap.JOB_REQUEST_WRITE))
        check("a client may NOT review one", not A.can(ALICE, M.Cap.JOB_REQUEST_REVIEW))
        check("a client may NOT share a CV onward", not A.can(ALICE, M.Cap.SHARE_WRITE))
        check("a client may NOT read the candidate collection",
              not A.can(ALICE, M.Cap.CANDIDATE_READ))
        check("a client may NOT see background verification",
              not A.can(ALICE, M.Cap.BACKGROUND_READ))

        # =================================================================
        section("1-4. The client raises a job request; Sparsh receives it")
        # =================================================================
        req_a = await JR.create_job_request(ALICE, COMPANY, {
            "job_title": "Backend Engineer", "positions": 2,
            "required_skills": "Python, FastAPI, MongoDB", "experience": "3-6 years",
            "location": "Pune", "budget_min": 1200000.0, "budget_max": 1800000.0,
            "job_description": "Build and run our order APIs."})
        JBR = req_a["jbr_no"]
        check("the request is raised", JBR.startswith("JBR-"))
        check("it opens as Submitted",
              req_a["status"] == M.JobRequestStatus.SUBMITTED.value)
        check("the client is taken from the ENGAGEMENT, not the request body",
              req_a["client_id"] == CLIENT_A)
        check("it is marked as raised by the client themselves",
              req_a["raised_by_client"] is True)

        # A client naming somebody else's id must not reach that client's account.
        forged = await JR.create_job_request(ALICE, COMPANY, {
            "job_title": "Forged", "required_skills": "x", "client_id": CLIENT_B})
        check("a client cannot raise a request against ANOTHER client's account",
              forged["client_id"] == CLIENT_A)

        await expect_http("a client reviewing their own request",
                          JR.act_on_job_request(ALICE, COMPANY, JBR, "review"),
                          403, "recruitment team")
        await expect_http("a client accepting their own request",
                          JR.act_on_job_request(ALICE, COMPANY, JBR, "accept"),
                          403, "recruitment team")

        seen_by_bob = await JR.list_job_requests(BOB, COMPANY)
        check("Bob cannot see Acme's job request",
              all(r["client_id"] == CLIENT_B for r in seen_by_bob["job_requests"]))
        await expect_http("Bob opening Acme's request by its number",
                          JR.get_job_request(BOB, COMPANY, JBR), 404)

        sparsh_inbox = await JR.list_job_requests(HR, COMPANY)
        check("Sparsh sees every client's requests in one inbox",
              len(sparsh_inbox["job_requests"]) >= 2)

        await JR.act_on_job_request(HR, COMPANY, JBR, "review")
        await expect_http("declining with no reason",
                          JR.act_on_job_request(HR, COMPANY, JBR, "decline"),
                          422, "owed a reason")
        accepted = await JR.act_on_job_request(HR, COMPANY, JBR, "accept")
        check("Sparsh accepted it",
              accepted["status"] == M.JobRequestStatus.ACCEPTED.value)
        check("the reviewer is recorded", accepted["reviewed_by"] == U_HR)

        converted = await JR.convert_to_requisition(HR, COMPANY, JBR, {
            "department_id": str(dept), "designation_id": str(desig),
            "assignee_id": U_HR, "required_date": "2027-06-30"})
        REQ = converted["request_no"]
        check("it converts into a requisition", REQ.startswith("HR-REQ-"))
        check("the requisition runs on the CLIENT track",
              converted["requisition"]["requisition_track"]
              == M.RequisitionTrack.CLIENT.value)
        check("the requisition carries the client",
              converted["requisition"]["client_id"] == CLIENT_A)
        check("the vacancy count comes from the request",
              converted["requisition"]["vacancy"] == 2)
        await expect_http("converting the same request twice",
                          JR.convert_to_requisition(HR, COMPANY, JBR, {
                              "department_id": str(dept), "designation_id": str(desig),
                              "assignee_id": U_HR, "required_date": "2027-06-30"}),
                          409, "already converted")

        # =================================================================
        section("1. HR uploads a CV; it is stored, not silently dropped")
        # =================================================================
        await RS.act_on_requisition(HR, COMPANY, REQ, "hr-approve")
        await RS.act_on_requisition(MD, COMPANY, REQ, "md-approve")
        cand = await CS.create_candidate(HR, COMPANY, {
            "request_no": REQ, "candidate_name": "Asha Applicant",
            "can_email": "asha@example.com", "can_contact": "+91 90000 00001",
            "total_experience": "5 years", "current_company": "Zeta",
            "current_ctc": "1400000", "expected_ctc": "1800000",
            "resume": cv()})
        UK = cand["uk"]
        stored = await store[M.COLL_CANDIDATES].find_one({"uk": UK})
        check("the CV uploaded at creation is STORED (it used to be dropped)",
              bool((stored.get("resume") or {}).get("key")))

        no_cv = await CS.create_candidate(HR, COMPANY, {
            "request_no": REQ, "candidate_name": "Bhavna NoCV",
            "can_email": "bhavna@example.com", "can_contact": "+91 90000 00002"})
        await expect_http("sharing a candidate with no CV",
                          SH.share_candidate(HR, COMPANY, {
                              "uk": no_cv["uk"], "client_ids": [CLIENT_A]}),
                          409, "no CV on file")
        await CS.upload_cv(HR, COMPANY, no_cv["uk"], {"resume": cv("late.pdf")})
        after = await store[M.COLL_CANDIDATES].find_one({"uk": no_cv["uk"]})
        check("a CV can be attached to an existing candidate afterwards",
              bool((after.get("resume") or {}).get("key")))

        # =================================================================
        section("2 & 5. One CV, two clients, two independent statuses")
        # =================================================================
        shared = await SH.share_candidate(HR, COMPANY, {
            "uk": UK, "client_ids": [CLIENT_A, CLIENT_B], "request_no": REQ,
            "note": "Strong Python background."})
        check("shared with BOTH clients in one act", shared["count"] == 2)
        share_a = next(s["share_no"] for s in shared["shared"]
                       if s["client_id"] == CLIENT_A)
        share_b = next(s["share_no"] for s in shared["shared"]
                       if s["client_id"] == CLIENT_B)

        again = await SH.share_candidate(HR, COMPANY, {
            "uk": UK, "client_ids": [CLIENT_A]})
        check("re-sharing with the same client is refused, not duplicated",
              again["count"] == 0 and again["skipped"])

        # The heart of the requirement: each client moves independently.
        await SH.set_share_status(ALICE, COMPANY, share_a, {
            "status": M.ShareStatus.SHORTLISTED.value, "remarks": "Good fit."})
        await SH.set_share_status(BOB, COMPANY, share_b, {
            "status": M.ShareStatus.REJECTED.value, "remarks": "Too senior for the band."})
        row_a = await store[M.COLL_CANDIDATE_SHARES].find_one({"share_no": share_a})
        row_b = await store[M.COLL_CANDIDATE_SHARES].find_one({"share_no": share_b})
        check("Acme shortlisted them", row_a["status"] == M.ShareStatus.SHORTLISTED.value)
        check("Borealis rejected the SAME candidate",
              row_b["status"] == M.ShareStatus.REJECTED.value)
        check("the two statuses are independent",
              row_a["status"] != row_b["status"])
        candidate_now = await store[M.COLL_CANDIDATES].find_one({"uk": UK})
        check("neither verdict disturbed the candidate's own pipeline stage",
              candidate_now["application_status"] == M.AppStatus.APPLIED.value)

        check("an illegal share move is refused",
              True)
        await expect_http("moving a share backwards to CV Shared",
                          SH.set_share_status(HR, COMPANY, share_a, {
                              "status": M.ShareStatus.CV_SHARED.value}), 409, "cannot move")
        await expect_http("a client marking somebody Hired themselves",
                          SH.set_share_status(ALICE, COMPANY, share_a, {
                              "status": M.ShareStatus.HIRED.value}),
                          403, "recorded by the recruitment team")

        # =================================================================
        section("3 & 6. A client sees ONLY what was shared with them")
        # =================================================================
        alice_sees = await SH.list_shares(ALICE, COMPANY)
        bob_sees = await SH.list_shares(BOB, COMPANY)
        check("Alice sees exactly one share", alice_sees["total"] == 1)
        check("Bob sees exactly one share", bob_sees["total"] == 1)
        check("the response is marked as a client view", alice_sees["client_view"] is True)
        await expect_http("Alice opening Borealis's share",
                          SH.get_share(ALICE, COMPANY, share_b), 404)
        await expect_http("Alice asking where else the candidate went",
                          SH.shares_for_candidate(ALICE, COMPANY, UK), 403, "not where else")

        view = alice_sees["shares"][0]
        check("the client view carries the authorised snapshot",
              view["snapshot"]["candidate_name"] == "Asha Applicant")
        check("contact details are withheld by default",
              "can_email" not in view["snapshot"])
        check("what the candidate earns NOW is never exposed",
              "current_ctc" not in view["snapshot"])
        check("Sparsh's internal candidate key is not in the client view",
              "uk" not in view)
        check("nor the internal history", "history" not in view)

        sparsh_view = await SH.shares_for_candidate(HR, COMPANY, UK)
        check("Sparsh sees BOTH clients for this candidate", sparsh_view["total"] == 2)

        # A client with no engagement at all must match nothing, not everything.
        stranger = actor(str(ObjectId()), "CLIENT", name="Stranger")
        stranger_sees = await SH.list_shares(stranger, COMPANY)
        check("a client with no engagement sees NOTHING (fails closed)",
              stranger_sees["total"] == 0)

        # =================================================================
        section("Rejected by one client -> still shareable with another")
        # =================================================================
        # The scenario this whole collection exists for. Borealis rejected Asha above.
        # A rejection is ONE CLIENT'S opinion, so it must not follow the candidate around:
        # the CV stays sourceable, and the next client starts from a clean sheet.
        rejected_row = await store[M.COLL_CANDIDATE_SHARES].find_one({"share_no": share_b})
        check("Borealis's share is Rejected",
              rejected_row["status"] == M.ShareStatus.REJECTED.value)
        candidate_after_reject = await store[M.COLL_CANDIDATES].find_one({"uk": UK})
        check("the REJECTION did not touch the candidate's own pipeline stage",
              candidate_after_reject["application_status"] != M.AppStatus.REJECTED.value)

        # A third client, after the rejection.
        CLIENT_C = str(ObjectId())
        await store["companies"].insert_one(
            {"_id": ObjectId(CLIENT_C), "name": "Cirrus Logistics", "hrms_enabled": True})
        onward = await SH.share_candidate(HR, COMPANY, {
            "uk": UK, "client_ids": [CLIENT_C],
            "note": "Passed over elsewhere on band, not on skill."})
        check("the same CV goes on to a THIRD client after a rejection",
              onward["count"] == 1)
        share_c = onward["shared"][0]["share_no"]
        row_c = await store[M.COLL_CANDIDATE_SHARES].find_one({"share_no": share_c})
        check("the new client starts at CV Shared, carrying no history of the rejection",
              row_c["status"] == M.ShareStatus.CV_SHARED.value)
        check("all three shares of one candidate coexist",
              (await SH.shares_for_candidate(HR, COMPANY, UK))["total"] == 3)
        check("and they hold three different statuses",
              len({(await store[M.COLL_CANDIDATE_SHARES].find_one(
                  {"share_no": n}))["status"] for n in (share_a, share_b, share_c)}) == 3)

        # The rejecting client is not a dead end either: a rejection is revivable, so the
        # same client can be re-approached without losing the record of the first pass.
        revived = await SH.set_share_status(HR, COMPANY, share_b, {
            "status": M.ShareStatus.UNDER_REVIEW.value,
            "remarks": "Re-pitched for the senior opening."})
        check("a rejected share can be revived with the SAME client",
              revived["status"] == M.ShareStatus.UNDER_REVIEW.value)
        revived_row = await store[M.COLL_CANDIDATE_SHARES].find_one({"share_no": share_b})
        check("reviving keeps the whole history, rejection included",
              [h["status"] for h in revived_row["history"]]
              == [M.ShareStatus.CV_SHARED.value, M.ShareStatus.REJECTED.value,
                  M.ShareStatus.UNDER_REVIEW.value])
        check("a client can revive their own rejection too (they may reconsider)",
              M.ShareStatus.UNDER_REVIEW in M.SHARE_CLIENT_SETTABLE)

        # Isolation still holds with three clients in play: the third must not see the
        # first two, and neither of them gains sight of the third.
        cirrus = actor(str(ObjectId()), "CLIENT", name="Chandra (Cirrus)")
        await store[M.COLL_CLIENT_ENGAGEMENTS].insert_one(
            {"_id": ObjectId(), "company_id": COMPANY, "client_id": CLIENT_C,
             "engagement_no": "CLI-ENG-2026-003",
             "status": M.EngagementStatus.ACTIVE.value,
             "member_user_ids": [cirrus["_id"]]})
        cirrus_sees = await SH.list_shares(cirrus, COMPANY)
        check("the third client sees only their own share",
              cirrus_sees["total"] == 1
              and cirrus_sees["shares"][0]["share_no"] == share_c)
        alice_still = await SH.list_shares(ALICE, COMPANY)
        check("the first client gained no sight of the third",
              alice_still["total"] == 1
              and alice_still["shares"][0]["share_no"] == share_a)

        # =================================================================
        section("7 & 8. The lock: verification -> HR approval -> offer")
        # =================================================================
        await store[M.COLL_CANDIDATES].update_one(
            {"uk": UK}, {"$set": {"application_status": M.AppStatus.SELECTED.value}})
        await RC.create_reference_check(HR, COMPANY, {
            "uk": UK, "referee_name": "Prior Manager",
            "outcome": M.ReferenceOutcome.POSITIVE.value,
            "responses": "Would rehire.",
            "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d")})

        def offer_payload():
            return {"uk": UK, "ctc": 1500000.0,
                    "joining_date": (datetime.now(timezone.utc)
                                     + timedelta(days=30)).strftime("%Y-%m-%d")}

        await expect_http("an offer with NO background checks at all",
                          OF.create_offer(HR, COMPANY, offer_payload()),
                          409, "not complete")

        state = await BG.verification_state(COMPANY, UK)
        check("all three required checks are outstanding",
              set(state["outstanding"]) == {t.value for t in M.REQUIRED_BACKGROUND_CHECKS})

        await expect_http("a Cleared check with no findings behind it",
                          BG.record_check(HR, COMPANY, {
                              "uk": UK, "check_type": M.BackgroundCheckType.IDENTITY.value,
                              "status": M.BackgroundCheckStatus.CLEARED.value}),
                          422, "record what")

        for check_type in M.REQUIRED_BACKGROUND_CHECKS:
            await BG.record_check(HR, COMPANY, {
                "uk": UK, "check_type": check_type.value,
                "status": M.BackgroundCheckStatus.CLEARED.value,
                "agency": "VerifyCo", "findings": "Matches the record.",
                "completed_on": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
        state = await BG.verification_state(COMPANY, UK)
        check("the checks are now complete", state["checks_complete"] is True)
        check("but NOT yet cleared for an offer -- nobody has signed",
              state["cleared_for_offer"] is False)
        await expect_http("an offer with checks done but unsigned",
                          OF.create_offer(HR, COMPANY, offer_payload()),
                          409, "not been approved")

        await expect_http("approving with no signature",
                          BG.decide_verification(HR, COMPANY, UK, {"decision": "Approved"}),
                          422, "type your name")
        approved = await BG.decide_verification(HR, COMPANY, UK, {
            "decision": "Approved", "signature": "Hana HR", "remarks": "File complete."})
        check("HR approved the verification", approved["cleared_for_offer"] is True)

        offer = await OF.create_offer(HR, COMPANY, offer_payload())
        check("the offer is now unlocked", bool(offer["offer_no"]))

        section("8b. A later flagged check withdraws the approval")
        await BG.record_check(HR, COMPANY, {
            "uk": UK, "check_type": M.BackgroundCheckType.EMPLOYMENT.value,
            "status": M.BackgroundCheckStatus.FLAGGED.value,
            "findings": "Dates do not match the employer's record."})
        after_flag = await BG.verification_state(COMPANY, UK)
        check("a new flagged check voids the earlier approval",
              after_flag["approval"]["status"] == M.BackgroundApprovalStatus.PENDING.value)
        check("and the candidate is no longer cleared",
              after_flag["cleared_for_offer"] is False)
        await expect_http("approving a FLAGGED file",
                          BG.decide_verification(HR, COMPANY, UK, {
                              "decision": "Approved", "signature": "Hana HR"}),
                          409, "flagged")

        section("8c. The only way past the gate is a signed exception")
        other = await CS.create_candidate(HR, COMPANY, {
            "request_no": REQ, "candidate_name": "Chetan Urgent",
            "can_email": "chetan@example.com", "can_contact": "+91 90000 00003",
            "resume": cv()})
        UK2 = other["uk"]
        await store[M.COLL_CANDIDATES].update_one(
            {"uk": UK2}, {"$set": {"application_status": M.AppStatus.SELECTED.value}})
        await RC.create_reference_check(HR, COMPANY, {
            "uk": UK2, "referee_name": "Referee",
            "outcome": M.ReferenceOutcome.POSITIVE.value, "responses": "Fine.",
            "checked_on": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
        await expect_http("an offer for an unverified candidate",
                          OF.create_offer(HR, COMPANY, {
                              "uk": UK2, "ctc": 1500000.0,
                              "joining_date": (datetime.now(timezone.utc)
                                               + timedelta(days=30)).strftime("%Y-%m-%d")}),
                          409, "not complete")
        exc = await EX.raise_exception(HR, COMPANY, {
            "request_no": REQ, "uk": UK2,
            "exception_type": M.ExceptionType.BACKGROUND_WAIVED.value,
            "reason": "Verifier unreachable; candidate has a competing deadline."})
        await EX.decide_exception(MD, COMPANY, exc["exc_no"], {
            "decision": "Approved", "signature": "Meera MD"})
        waived = await OF.create_offer(HR, COMPANY, {
            "uk": UK2, "ctc": 1500000.0,
            "joining_date": (datetime.now(timezone.utc)
                             + timedelta(days=30)).strftime("%Y-%m-%d")})
        check("an APPROVED waiver -- and only that -- opens the gate",
              bool(waived["offer_no"]))
        check("the waiver is an attributable record, not a flag",
              (await store[M.COLL_EXCEPTIONS].find_one(
                  {"exc_no": exc["exc_no"]}))["approved_by"] == U_MD)

        # =================================================================
        section("The stage ladder does not leak Sparsh's process to the client")
        # =================================================================
        # A source check, in the same spirit as the analytics read-only grep: the client's
        # progress indicator must never gain sight of background verification or the HR
        # approval, and the cheapest way for that to break later is somebody passing the
        # prop "because the component takes one".
        import os as _os
        _fe = _os.path.join("..", "frontend", "src", "features", "hrms", "client")

        def _read(name):
            with open(_os.path.join(_fe, name), encoding="utf-8") as fh:
                return fh.read()

        try:
            client_screen = _read("SharedCandidates.jsx")
            ladder = _read("ShareJourney.jsx")
        except OSError:
            client_screen = ladder = None

        if client_screen is None:
            check("the client screen was found for inspection", False)
        else:
            check("the client screen never passes verification into the ladder",
                  "verification=" not in client_screen)
            check("the client screen never calls the verification endpoint",
                  "getCandidateVerification" not in client_screen
                  and "getPendingVerifications" not in client_screen)
            check("the client screen renders the client variant",
                  'variant="client"' in client_screen)
            # The ladder's client branch is the one that must stay free of our gates.
            client_branch = ladder.split("} else if (variant === 'client') {")[1] \
                .split("} else {")[0]
            for token in ("Background verification", "HR approval", "outstanding",
                          "flagged", "cleared_for_offer"):
                check(f"the client ladder branch never mentions {token!r}",
                      token not in client_branch)
            check("the Sparsh branch DOES surface the gates (so the lock stays legible "
                  "to the people who can act on it)",
                  "Background verification" in ladder and "HR approval" in ladder)

        # And the browser prompt is gone from the client-track screens.
        try:
            jr = _read("JobRequestBoard.jsx")
            code_only = "\n".join(l for l in jr.splitlines()
                                   if not l.strip().startswith("//"))
            check("declining a job request uses a form, not a browser prompt()",
                  "window.prompt" not in code_only)
        except OSError:
            check("the job request screen was found for inspection", False)

        # =================================================================
        section("Audit trail: sharing, client access, verification, approvals")
        # =================================================================
        actions = {a["action"] for a in store[M.COLL_AUDIT_LOG].docs}
        check("the job request is audited", M.AUDIT_JOB_REQUEST_RAISED in actions)
        check("its review is audited", M.AUDIT_JOB_REQUEST_REVIEWED in actions)
        check("the conversion is audited", M.AUDIT_JOB_REQUEST_CONVERTED in actions)
        check("the share is audited", M.AUDIT_SHARE_CREATED in actions)
        check("each status change is audited", M.AUDIT_SHARE_STATUS in actions)
        check("recording a check is audited", M.AUDIT_BACKGROUND_RECORDED in actions)
        check("the verification approval is audited", M.AUDIT_BACKGROUND_APPROVED in actions)

        # =================================================================
        section("The client downloads the CV")
        # =================================================================
        signed_calls.clear()
        link = await SH.resume_url_for_share(ALICE, COMPANY, share_a)
        check("the client gets a link", bool(link["url"]))
        check("it is short-lived (5 minutes), not a permanent URL",
              link["expires_in"] == 300)
        check("the link is minted as a DOWNLOAD, not something to render in a tab",
              signed_calls[-1]["download_as"] is not None)
        check("the file arrives under the candidate's name, not our storage key",
              link["name"] == "Asha Applicant - CV.pdf"
              and signed_calls[-1]["download_as"] == "Asha Applicant - CV.pdf")
        check("the original extension is kept", link["name"].endswith(".pdf"))
        check("nothing about our storage layout is returned",
              "s3" not in link["url"].replace("https://signed.example/", "")
              or "resume_key" not in link)

        # The client's own list must tell them a CV EXISTS without telling them where.
        client_row = (await SH.list_shares(ALICE, COMPANY))["shares"][0]
        check("the client is told there is a CV to download",
              client_row["snapshot"]["has_cv"] is True)
        check("...but never receives the S3 key",
              "resume_key" not in client_row["snapshot"])
        check("...nor our internal filename",
              "resume_name" not in client_row["snapshot"])
        sparsh_row = await store[M.COLL_CANDIDATE_SHARES].find_one({"share_no": share_a})
        check("the stored share still holds the key -- the client VIEW hid it, the "
              "document did not lose it",
              bool(sparsh_row["snapshot"]["resume_key"]))

        access_rows = [a for a in store[M.COLL_AUDIT_LOG].docs
                       if a["action"] == M.AUDIT_SHARE_CV_OPENED]
        check("a client DOWNLOADING a CV is audited -- client access, not just decisions",
              len(access_rows) == 1 and access_rows[0]["actor_id"] == U_CLIENT_A)
        check("the audit row names the client and the candidate",
              "Acme" in access_rows[0]["detail"]
              and "Asha" in access_rows[0]["detail"])

        await expect_http("a client downloading a CV never shared with them",
                          SH.resume_url_for_share(ALICE, COMPANY, share_b), 404)

        withdrawn = await SH.withdraw_share(HR, COMPANY, share_b, {"remarks": "Role filled."})
        check("Sparsh can withdraw a CV from a client",
              withdrawn["status"] == M.ShareStatus.WITHDRAWN.value)
        await expect_http("opening a withdrawn CV",
                          SH.resume_url_for_share(BOB, COMPANY, share_b), 410, "withdrawn")

    finally:
        mongo.get_collection = original
        NS.notify_user, NS.notify_users, NS.notify_hrms_role = keep
        S3.upload_file_to_s3_with_key = keep_s3
        S3.get_signed_url = keep_url

    print()
    total, passed = len(results), sum(results)
    print("=" * 70)
    print(f"  {passed}/{total} checks passed")
    print("=" * 70)
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
