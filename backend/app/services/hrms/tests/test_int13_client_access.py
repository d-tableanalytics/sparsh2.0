"""Two reported errors, fixed and pinned.

-- 1. "Client HR cannot access HRMS" -------------------------------------------------------
A user of a CLIENT organisation was refused at the door. Their own company has HRMS switched
off -- correctly, because they do not run a hiring pipeline; Sparsh runs one FOR them -- and
`ensure_hrms_enabled` looked at nothing else before raising 403.

On the live database that is 265 of 276 users, including eight whose governance_role is HR.

The fix admits them through their ENGAGEMENT, into the tenant that actually runs HRMS. The
trap it has to close in the same change: `hrms_role` maps governance_role "HR" to
HrmsRole.HR, so admitting a client's HR without touching identity would have handed them
Sparsh's entire HR capability set. A stamped participant is a CLIENT whatever their title.

-- 2. "An authorised signature is required to send an offer" --------------------------------
On the internal track, create-and-send is impossible in principle -- Management's approval
happens between the two steps. But the signature check ran FIRST, so the user was told to
supply a signature, and supplying one changed nothing because the next check refused the
shape of the request outright. The order is now: impossible before incomplete.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_int13_client_access   (from backend/)
"""
from __future__ import annotations

import asyncio
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

TENANT = "SPARSH"          # People to Process — the company that runs HRMS
CLIENT_CO = "CLIENTCO"     # a client organisation — HRMS is OFF for them


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    from app.models import hrms as M

    # ── Phase 12 ── the background-verification gate now stands in front of every offer,
    # on both tracks. This file measures a different control, so the gate is stubbed here
    # exactly as the shortlist and telephonic gates are elsewhere.
    import app.services.hrms_background_service as _BGV

    async def _bg_cleared(*_a, **_kw):
        return None
    _BGV.assert_background_cleared = _bg_cleared

    U_CLIENT_HR = str(ObjectId())      # "HR" at the client company
    U_CLIENT_MD = str(ObjectId())      # clientadmin at the client company
    U_STRANGER = str(ObjectId())       # same company, no engagement
    U_SPARSH_HR = str(ObjectId())
    CLIENT_ORG = str(ObjectId())
    dept, desig = ObjectId(), ObjectId()

    companies = FakeCollection([
        {"_id": ObjectId(CLIENT_ORG), "name": "Client Org", "hrms_enabled": None},
    ])
    # The tenant is keyed by its own id in `companies`; the fake store looks it up by _id.
    TENANT_OID = ObjectId()
    await companies.insert_one(
        {"_id": TENANT_OID, "name": "People to Process", "hrms_enabled": True})
    TENANT_ID = str(TENANT_OID)

    learners = FakeCollection([
        # These users belong to the CLIENT company, not the tenant. That is the whole point.
        {"_id": ObjectId(U_CLIENT_HR), "company_id": CLIENT_ORG, "role": "clientuser",
         "governance_role": "HR", "full_name": "Client HR", "is_active": True},
        {"_id": ObjectId(U_CLIENT_MD), "company_id": CLIENT_ORG, "role": "clientadmin",
         "governance_role": "MD", "full_name": "Client MD", "is_active": True},
        {"_id": ObjectId(U_STRANGER), "company_id": CLIENT_ORG, "role": "clientuser",
         "governance_role": "HR", "full_name": "Unengaged HR", "is_active": True},
        {"_id": ObjectId(U_SPARSH_HR), "company_id": TENANT_ID, "role": "clientuser",
         "governance_role": "HR", "full_name": "Sparsh HR", "is_active": True},
    ])
    engagements = FakeCollection([
        {"_id": ObjectId(), "company_id": TENANT_ID, "client_id": CLIENT_ORG,
         "engagement_no": "CLI-ENG-1", "status": M.EngagementStatus.ACTIVE.value,
         "member_user_ids": [U_CLIENT_HR, U_CLIENT_MD]},
    ])

    store = {c: FakeCollection() for c in (
        M.COLL_REQUISITIONS, M.COLL_JOB_DESCRIPTIONS, M.COLL_CANDIDATES,
        M.COLL_JOB_REQUESTS, M.COLL_CANDIDATE_SHARES, M.COLL_OFFERS, M.COLL_COUNTERS,
        M.COLL_AUDIT_LOG, M.COLL_LINKS, M.COLL_SANCTIONED_STRENGTH,
        M.COLL_POSITION_SCORECARDS, M.COLL_REFERENCE_CHECKS, M.COLL_SALARY_BANDS,
        M.COLL_SETTINGS, M.COLL_EXCEPTIONS)}
    store.update({M.COLL_DEPARTMENTS: FakeCollection([
        {"_id": dept, "company_id": TENANT_ID, "name": "Engineering", "active": True}]),
        M.COLL_DESIGNATIONS: FakeCollection([
            {"_id": desig, "company_id": TENANT_ID, "name": "Developer",
             "designation_level": M.DesignationLevel.MID.value, "active": True}]),
        M.COLL_CLIENT_ENGAGEMENTS: engagements, "companies": companies,
        "learners": learners, "staff": FakeCollection()})
    keep_get = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.utils.hrms_access as A
    import app.services.hrms_share_service as SH
    import app.services.hrms_job_request_service as JR
    import app.services.hrms_requisition_service as RS
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_offer_service as OF
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_sanction_service as SN
    import app.services.hrms_scorecard_service as SC
    import app.services.hrms_reference_service as RC
    import app.services.hrms_link_service as LS
    import app.services.hrms_referral_service as RF
    import app.services.hrms_config_service as CFG
    import app.services.hrms_salary_band_service as BANDS
    import app.services.hrms_shortlist_service as SL
    import app.services.hrms_telephonic_service as TS

    SERVICES = (A, SH, JR, RS, CS, OF, AUD, IDS, SN, SC, RC, LS, RF, CFG, BANDS, SL, TS)
    for mod in SERVICES:
        if hasattr(mod, "get_collection"):
            mod.get_collection = mongo.get_collection

    async def silent(*a, **kw):
        return None
    for mod in SERVICES:
        for n in ("notify_user", "notify_users", "notify_hrms_role"):
            if hasattr(mod, n):
                setattr(mod, n, silent)
    import app.services.hrms_notify_service as NS
    keep_notify = (NS.notify_user, NS.notify_users, NS.notify_hrms_role)
    NS.notify_user, NS.notify_users, NS.notify_hrms_role = silent, silent, silent

    async def cleared(*a, **kw):
        return None
    SL.assert_shortlist_cleared = cleared
    TS.assert_telephonic_cleared = cleared

    import app.services.s3_service as S3
    keep_s3 = S3.upload_file_to_s3_with_key
    S3.upload_file_to_s3_with_key = lambda f, n, m: {"key": f"s3/{n}", "url": "u"}

    def fresh(uid, role, governance):
        """A user dict exactly as the auth layer hands it over -- unstamped."""
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": CLIENT_ORG if uid != U_SPARSH_HR else TENANT_ID,
                "governance_role": governance,
                "full_name": governance}

    TODAY = datetime.now(timezone.utc)

    try:
        # =================================================================
        section("1. Before the gate runs, a client user is nobody")
        # =================================================================
        client_hr = fresh(U_CLIENT_HR, "clientuser", "HR")
        check("un-stamped, a client's HR still reads as HrmsRole.HR -- which is exactly "
              "why the gate must stamp before anything asks",
              A.hrms_role(client_hr) is M.HrmsRole.HR)

        # =================================================================
        section("2. The entry gate admits an engaged client user")
        # =================================================================
        client_hr = fresh(U_CLIENT_HR, "clientuser", "HR")
        await A.ensure_hrms_enabled(client_hr)
        check("a client HR is no longer refused at the door", True)
        check("they are stamped with the TENANT that runs HRMS",
              client_hr.get(A.CLIENT_TENANT_FIELD) == TENANT_ID)
        check("and they resolve to CLIENT, not HR -- their title is their own company's",
              A.hrms_role(client_hr) is M.HrmsRole.CLIENT)
        check("so they are client-scoped", A.is_client_scoped_user(client_hr))

        client_md = fresh(U_CLIENT_MD, "clientadmin", "MD")
        await A.ensure_hrms_enabled(client_md)
        check("a client's OWNER (clientadmin) also resolves to CLIENT, not MD",
              A.hrms_role(client_md) is M.HrmsRole.CLIENT)

        # =================================================================
        section("3. The escalation this fix had to avoid")
        # =================================================================
        for cap in (M.Cap.CANDIDATE_READ, M.Cap.CANDIDATE_SCREEN, M.Cap.OFFER_WRITE,
                    M.Cap.OFFER_SEND, M.Cap.BACKGROUND_APPROVE, M.Cap.SHARE_WRITE,
                    M.Cap.JOB_REQUEST_REVIEW, M.Cap.EMPLOYEE_READ,
                    M.Cap.REQUISITION_REVIEW_HR, M.Cap.ANALYTICS_READ):
            check(f"a client HR does NOT hold {cap.value}", not A.can(client_hr, cap))
        check("they DO hold the four things a client comes here to do",
              all(A.can(client_hr, c) for c in (M.Cap.JOB_REQUEST_READ,
                                                M.Cap.JOB_REQUEST_WRITE,
                                                M.Cap.SHARE_READ, M.Cap.SHARE_RESPOND)))

        # =================================================================
        section("4. Still refused: a client user with no live engagement")
        # =================================================================
        stranger = fresh(U_STRANGER, "clientuser", "HR")
        await expect_http("an unengaged client user",
                          A.ensure_hrms_enabled(stranger), 403, "not enabled")
        check("and they carry no stamp", not stranger.get(A.CLIENT_TENANT_FIELD))

        section("4b. A lapsed engagement grants nothing")
        await store[M.COLL_CLIENT_ENGAGEMENTS].update_one(
            {"engagement_no": "CLI-ENG-1"},
            {"$set": {"status": M.EngagementStatus.ENDED.value}})
        lapsed = fresh(U_CLIENT_HR, "clientuser", "HR")
        await expect_http("a client user whose engagement ended",
                          A.ensure_hrms_enabled(lapsed), 403, "not enabled")
        await store[M.COLL_CLIENT_ENGAGEMENTS].update_one(
            {"engagement_no": "CLI-ENG-1"},
            {"$set": {"status": M.EngagementStatus.ACTIVE.value}})

        section("4c. A forged stamp is discarded before it is read")
        forged = fresh(U_STRANGER, "clientuser", "HR")
        forged[A.CLIENT_TENANT_FIELD] = TENANT_ID          # as if injected
        await expect_http("a self-awarded tenant",
                          A.ensure_hrms_enabled(forged), 403, "not enabled")
        check("the forged stamp was cleared, not honoured",
              not forged.get(A.CLIENT_TENANT_FIELD))

        # =================================================================
        section("5. A Sparsh-side user is untouched by any of this")
        # =================================================================
        sparsh_hr = fresh(U_SPARSH_HR, "clientuser", "HR")
        await A.ensure_hrms_enabled(sparsh_hr)
        check("no stamp -- their own company runs HRMS",
              not sparsh_hr.get(A.CLIENT_TENANT_FIELD))
        check("they are still HR", A.hrms_role(sparsh_hr) is M.HrmsRole.HR)
        check("and still hold HR's capabilities",
              A.can(sparsh_hr, M.Cap.CANDIDATE_SCREEN)
              and A.can(sparsh_hr, M.Cap.OFFER_SEND))

        # =================================================================
        section("6. Scoping: the tenant's data, their own rows")
        # =================================================================
        check("a stamped user's company resolves to the TENANT, not their own company",
              A.scope_company_id(client_hr) == TENANT_ID)
        check("a requested company id is still ignored",
              A.scope_company_id(client_hr, "SOMEWHERE-ELSE") == TENANT_ID)
        check("their client scope is their own organisation",
              await A.scope_client_ids(client_hr, TENANT_ID) == [CLIENT_ORG])

        jr = await JR.create_job_request(client_hr, TENANT_ID, {
            "job_title": "Software Developer", "positions": 2,
            "required_skills": "React, Node.js"})
        check("a client HR can raise a job request -- the reported blocker, now working",
              jr["jbr_no"].startswith("JBR-") and jr["client_id"] == CLIENT_ORG)
        check("Sparsh receives it",
              (await JR.list_job_requests(
                  fresh(U_SPARSH_HR, "clientuser", "HR"), TENANT_ID))["total"] == 1)

        # =================================================================
        section("7. The offer error: impossible is reported before incomplete")
        # =================================================================
        sparsh = fresh(U_SPARSH_HR, "clientuser", "HR")
        await A.ensure_hrms_enabled(sparsh)
        md = {"_id": str(ObjectId()), "role": "clientadmin",
              "_source_collection": "learners", "company_id": TENANT_ID,
              "full_name": "Sparsh MD"}
        await store["learners"].insert_one(
            {"_id": ObjectId(md["_id"]), "company_id": TENANT_ID, "role": "clientadmin",
             "full_name": "Sparsh MD", "is_active": True})

        async def make_candidate(track):
            req = await RS.create_requisition(sparsh, TENANT_ID, {
                "department_id": str(dept), "designation_id": str(desig),
                "assignee_id": U_SPARSH_HR, "vacancy": 1, "required_date": "2027-06-30",
                "experience_required": "2-4 years", "qualification": "B.E.",
                "essential_skills": "Python", "offering_ctc": 800000.0,
                "requisition_track": track,
                "jd": {"title": "Developer", "responsibilities": "Build."}})
            rn = req["request_no"]
            if track == "internal":
                await RS.act_on_requisition(sparsh, TENANT_ID, rn, "hr-verify")
                await RS.act_on_requisition(md, TENANT_ID, rn, "budget-approve", budget={
                    "approved_headcount": 1, "approved_salary_band_min": 700000.0,
                    "approved_salary_band_max": 900000.0})
                card = await SC.create_scorecard(sparsh, TENANT_ID, {
                    "request_no": rn, "criteria": [{"label": "Core"}]})
                await SC.approve_scorecard(md, TENANT_ID, card["scr_no"],
                                           {"decision": "Pass", "signature": "MD"})
                await RS.act_on_requisition(md, TENANT_ID, rn, "scorecard-approve")
            else:
                await RS.act_on_requisition(sparsh, TENANT_ID, rn, "hr-approve")
                await RS.act_on_requisition(md, TENANT_ID, rn, "md-approve")
            cand = await CS.create_candidate(sparsh, TENANT_ID, {
                "request_no": rn, "candidate_name": f"{track} candidate",
                "can_email": f"{track}@example.com", "can_contact": "+91 90000 00000"})
            await store[M.COLL_CANDIDATES].update_one(
                {"uk": cand["uk"]},
                {"$set": {"application_status": M.AppStatus.SELECTED.value}})
            await RC.create_reference_check(sparsh, TENANT_ID, {
                "uk": cand["uk"], "referee_name": "Ref", "responses": "Fine.",
                "outcome": M.ReferenceOutcome.POSITIVE.value,
                "checked_on": TODAY.strftime("%Y-%m-%d")})
            return cand["uk"]

        joining = (TODAY + timedelta(days=45)).strftime("%Y-%m-%d")
        internal_uk = await make_candidate("internal")

        # THE REPORTED BUG: this used to answer "an authorised signature is required",
        # sending the user to type one that would not have helped.
        await expect_http(
            "internal track, create-and-send with NO signature",
            OF.create_offer(sparsh, TENANT_ID, {
                "uk": internal_uk, "ctc": 800000.0, "joining_date": joining,
                "send_now": True}),
            409, "cannot be created and sent in one step")
        await expect_http(
            "internal track, create-and-send WITH a signature (same answer, as it must be)",
            OF.create_offer(sparsh, TENANT_ID, {
                "uk": internal_uk, "ctc": 800000.0, "joining_date": joining,
                "send_now": True, "signature": "Sparsh HR"}),
            409, "cannot be created and sent in one step")
        drafted = await OF.create_offer(sparsh, TENANT_ID, {
            "uk": internal_uk, "ctc": 800000.0, "joining_date": joining})
        check("...and saving it as a draft works, which is what the message now says to do",
              drafted["status"] == M.OfferStatus.DRAFT.value)

        section("7b. On the CLIENT track the signature message still applies, and helps")
        client_uk = await make_candidate("client")
        await expect_http(
            "client track, create-and-send with no signature",
            OF.create_offer(sparsh, TENANT_ID, {
                "uk": client_uk, "ctc": 800000.0, "joining_date": joining,
                "send_now": True}),
            422, "type the authorised signatory")
        sent = await OF.create_offer(sparsh, TENANT_ID, {
            "uk": client_uk, "ctc": 800000.0, "joining_date": joining,
            "send_now": True, "signature": "Sparsh HR"})
        check("with a signature it sends", sent["status"] == M.OfferStatus.SENT.value)
        check("no orphan draft was left by either refusal",
              len(await store[M.COLL_OFFERS].find(
                  {"uk": client_uk}).to_list(10)) == 1)

    finally:
        mongo.get_collection = keep_get
        NS.notify_user, NS.notify_users, NS.notify_hrms_role = keep_notify
        S3.upload_file_to_s3_with_key = keep_s3

    print()
    total, passed = len(results), sum(results)
    print("=" * 70)
    print(f"  {passed}/{total} checks passed")
    print("=" * 70)
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
