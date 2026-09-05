"""The client hiring brief -- the interview record, the isolation holes, and the offer bug.

Covers the work the brief asked for that Phase 12 did not already carry, and the three
defects found while implementing it. Each section names the paragraph of the brief it
answers, so a failure here says which promise broke.

  SS10  the interview report and the recording: filed once, published to live shares,
        and read by a client through three routes with three different verbs --
        CV downloads, report views, recording only watches.
  SS12  which actions a client is offered depends on where the share actually is, and the
        answer comes from the server rather than from a list restated in JavaScript.
  SS13  creating and sending an offer in one action. `OfferIn` declared no `signature`
        field, so Pydantic dropped the one the operator typed and EVERY create-and-send
        was refused with "An authorised signature is required to send an offer".
  SS16  two isolation holes the CLIENT role's own capabilities opened:
          - `requisition.read` returned every requisition in the tenant, including the
            ones raised for other clients;
          - `client.read` returned every company on the books, i.e. the list of who else
            Sparsh recruits for.
        Both are asserted against a REAL second client with its own engagement, because a
        scoping bug that returns "everything" passes any test written with one client.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_hiring_brief   (from backend/)
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone

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

    U_HR, U_ALICE, U_BOB = (str(ObjectId()) for _ in range(3))
    CLIENT_A, CLIENT_B = str(ObjectId()), str(ObjectId())
    dept, desig = ObjectId(), ObjectId()

    companies = FakeCollection([
        {"_id": ObjectId(CLIENT_A), "name": "Acme Retail", "hrms_enabled": True,
         "is_active": True},
        {"_id": ObjectId(CLIENT_B), "name": "Borealis Bank", "hrms_enabled": True,
         "is_active": True},
    ])
    departments = FakeCollection([
        {"_id": dept, "company_id": COMPANY, "name": "Engineering", "active": True}])
    designations = FakeCollection([
        {"_id": desig, "company_id": COMPANY, "name": "Backend Engineer",
         "designation_level": M.DesignationLevel.MID.value, "active": True}])
    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "full_name": "Hana HR",
         "governance_role": "HR", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_ALICE), "company_id": COMPANY, "full_name": "Alice (Acme)",
         "governance_role": "CLIENT", "role": "clientuser", "is_active": True},
        {"_id": ObjectId(U_BOB), "company_id": COMPANY, "full_name": "Bob (Borealis)",
         "governance_role": "CLIENT", "role": "clientuser", "is_active": True},
    ])
    engagements = FakeCollection([
        {"_id": ObjectId(), "company_id": COMPANY, "client_id": CLIENT_A,
         "engagement_no": "CLI-ENG-2026-001", "status": M.EngagementStatus.ACTIVE.value,
         "member_user_ids": [U_ALICE]},
        {"_id": ObjectId(), "company_id": COMPANY, "client_id": CLIENT_B,
         "engagement_no": "CLI-ENG-2026-002", "status": M.EngagementStatus.ACTIVE.value,
         "member_user_ids": [U_BOB]},
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

    import app.services.hrms_share_service as SH
    import app.services.hrms_interview_media_service as IM
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_requisition_service as RS
    import app.services.hrms_client_service as CL
    import app.services.hrms_offer_service as OF
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_posting_service as PS
    import app.services.hrms_sanction_service as SN
    import app.services.hrms_shortlist_service as SL
    import app.services.hrms_telephonic_service as TS
    import app.services.hrms_reference_service as RC
    import app.services.hrms_config_service as CFG
    import app.services.hrms_salary_band_service as BANDS
    import app.utils.hrms_access as ACCESS

    SERVICES = (SH, IM, CS, RS, CL, OF, AUD, IDS, PS, SN, SL, TS, RC, CFG, BANDS, ACCESS)
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
    RC.assert_references_cleared = _cleared
    OF.assert_within_band = _cleared
    # The background-verification gate is real, correct and covered by
    # test_int12_client_track. Stubbed here so the SS13 section fails on the SIGNATURE if it
    # fails at all -- an offer refused for a missing check would look like the bug this file
    # is asserting is gone.
    #
    # Patched on the OWNING module, not on the offer service: create_offer imports it inside
    # the function body (`from app.services.hrms_background_service import ...`), so the name
    # is resolved fresh on every call and an attribute set on the importer is never consulted.
    import app.services.hrms_background_service as BG
    keep_bg = BG.assert_background_cleared
    BG.assert_background_cleared = _cleared

    import app.services.s3_service as S3
    keep_s3 = S3.upload_file_to_s3_with_key
    keep_url = S3.get_signed_url
    S3.upload_file_to_s3_with_key = lambda f, n, m: {"key": f"s3/{n}", "url": "https://x/y"}
    signed = []

    def _fake_signed(key, expires_in=3600, download_as=None):
        signed.append({"key": key, "expires_in": expires_in, "download_as": download_as})
        return f"https://signed.example/{key}"
    S3.get_signed_url = _fake_signed
    PS.upload_file_to_s3_with_key = S3.upload_file_to_s3_with_key
    IM.get_collection = mongo.get_collection

    def actor(uid, gov, role="clientuser", name=None):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": gov,
                "full_name": name or gov}

    HR = actor(U_HR, "HR", name="Hana HR")
    ALICE = actor(U_ALICE, "CLIENT", name="Alice (Acme)")
    BOB = actor(U_BOB, "CLIENT", name="Bob (Borealis)")

    def upload(name, mime, blob):
        return {"name": name, "mime_type": mime,
                "data": base64.b64encode(blob).decode()}

    try:
        # =================================================================
        section("SS16 -- requisitions: a client sees THEIR requisition, not the tenant's")
        # =================================================================
        # Two requisitions, one per client, plus one with no client at all (Sparsh's own
        # internal hiring). A client must see exactly one of the three.
        now = datetime.now(timezone.utc)
        for label, client_id in (("acme", CLIENT_A), ("borealis", CLIENT_B), ("own", None)):
            await store[M.COLL_REQUISITIONS].insert_one({
                "_id": ObjectId(), "request_no": f"REQ-{label}", "company_id": COMPANY,
                "client_id": client_id, "designation_name": "Backend Engineer",
                "designation_id": str(desig), "department_id": str(dept),
                "approval_status": M.ReqApproval.APPROVED.value,
                "closing_status": M.ReqClosing.OPEN.value,
                "created_by": U_HR, "created_at": now, "vacancy": 1})

        hr_list = await RS.list_requisitions(HR, COMPANY)
        check("Sparsh HR sees all three requisitions", hr_list["total"] == 3)

        alice_list = await RS.list_requisitions(ALICE, COMPANY)
        alice_nos = {r["request_no"] for r in alice_list["requisitions"]}
        check("Alice sees exactly one requisition", alice_list["total"] == 1)
        check("and it is Acme's", alice_nos == {"REQ-acme"})
        check("Borealis's requisition is not in Alice's list", "REQ-borealis" not in alice_nos)
        check("Sparsh's own requisition is not in Alice's list", "REQ-own" not in alice_nos)
        check("the stat tiles agree with the list Alice actually got",
              alice_list["stats"]["total"] == 1)

        bob_list = await RS.list_requisitions(BOB, COMPANY)
        check("Bob sees exactly his own",
              {r["request_no"] for r in bob_list["requisitions"]} == {"REQ-borealis"})

        await expect_http("Alice opening Borealis's requisition by its number directly",
                          RS.get_requisition(ALICE, COMPANY, "REQ-borealis"), 404)

        # =================================================================
        section("SS16 -- the client list is not a directory of who else Sparsh works for")
        # =================================================================
        all_clients = await CL.list_clients(HR, COMPANY)
        check("Sparsh HR sees both client companies", all_clients["total"] == 2)

        alice_clients = await CL.list_clients(ALICE, COMPANY)
        names = {c["name"] for c in alice_clients["clients"]}
        check("Alice sees exactly one client company", alice_clients["total"] == 1)
        check("and it is her own", names == {"Acme Retail"})
        check("she never learns Borealis is a client", "Borealis Bank" not in names)

        # An unmapped client user -- scope resolves to [] -- must match NOTHING rather than
        # degrading to "no filter". This is the way this control would break.
        STRANGER = actor(str(ObjectId()), "CLIENT", name="Nobody")
        check("an unmapped client user's scope is empty, not absent",
              await A.scope_client_ids(STRANGER, COMPANY) == [])
        stranger_clients = await CL.list_clients(STRANGER, COMPANY)
        check("an unmapped client user sees NO companies", stranger_clients["total"] == 0)
        stranger_reqs = await RS.list_requisitions(STRANGER, COMPANY)
        check("an unmapped client user sees NO requisitions", stranger_reqs["total"] == 0)

        # =================================================================
        section("SS10 -- Sparsh files the interview record against the candidate")
        # =================================================================
        candidate = await CS.create_candidate(HR, COMPANY, {
            "candidate_name": "Priya Nair", "can_email": "priya@example.com",
            "can_contact": "9876543210", "request_no": "REQ-acme",
            "total_experience": "5 years", "qualification": "B.Tech",
            "resume": upload("cv.pdf", "application/pdf", b"%PDF-1.4 cv")})
        uk = candidate["uk"]

        empty = await IM.get_media(HR, COMPANY, uk)
        check("a candidate starts with no interview record",
              empty["report"] is None and empty["recording"] is None)

        await expect_http("filing a report with no file attached",
                          IM.file_report(HR, COMPANY, uk, {"summary": "x"}), 422)

        filed = await IM.file_report(HR, COMPANY, uk, {
            "file": upload("panel.pdf", "application/pdf", b"%PDF-1.4 panel notes"),
            "summary": "Strong on system design; light on delivery pace."})
        check("the report is filed", filed["ok"] and filed["kind"] == "report")
        check("and the API response never carries the S3 key",
              "key" not in filed["report"])
        check("the summary is stored with it",
              filed["report"]["summary"].startswith("Strong on system design"))

        # A recording is a file OR a link -- never both, never neither.
        await expect_http("filing a recording with neither a file nor a link",
                          IM.file_recording(HR, COMPANY, uk, {}), 422)
        await expect_http(
            "filing a recording with BOTH",
            IM.file_recording(HR, COMPANY, uk, {
                "file": upload("r.mp4", "video/mp4", b"\x00mp4"),
                "url": "https://zoom.example/rec/1"}), 422, "not both")
        await expect_http(
            "a recording 'link' that is not a link",
            IM.file_recording(HR, COMPANY, uk,
                              {"url": "javascript:alert(1)"}), 422)
        await expect_http(
            "a PDF offered as a recording",
            IM.file_recording(HR, COMPANY, uk, {
                "file": upload("x.pdf", "application/pdf", b"%PDF")}), 415)

        rec = await IM.file_recording(HR, COMPANY, uk, {
            "file": upload("panel.mp4", "video/mp4", b"\x00\x00\x00 ftypisom"),
            "title": "Technical round", "duration_min": 47})
        check("the recording is filed", rec["ok"] and rec["recording"]["source"] == "file")
        check("its duration is kept", rec["recording"]["duration_min"] == 47)

        # The wider recording allow-list must NOT have leaked into the public one -- an
        # anonymous applicant posting to a job link must still be unable to upload video.
        check("the public upload allow-list still refuses video",
              "video/mp4" not in M.ALLOWED_UPLOAD_MIME)
        check("the recording allow-list accepts it", "video/mp4" in M.ALLOWED_RECORDING_MIME)

        # =================================================================
        section("SS10 -- a share carries the record, and refreshes when it is filed LATE")
        # =================================================================
        # The ordering that matters: this CV goes to Borealis BEFORE anything else is filed,
        # and to Acme after. Both must end up able to see the record.
        shared_b = await SH.share_candidate(HR, COMPANY, {
            "uk": uk, "client_ids": [CLIENT_B], "note": "Have a look."})
        share_b = shared_b["shared"][0]["share_no"]

        await IM.file_report(HR, COMPANY, uk, {
            "file": upload("panel2.pdf", "application/pdf", b"%PDF-1.4 v2"),
            "summary": "Second panel: recommended."})

        shared_a = await SH.share_candidate(HR, COMPANY, {
            "uk": uk, "client_ids": [CLIENT_A], "note": "Strong match for your role."})
        share_a = shared_a["shared"][0]["share_no"]

        view_b = await SH.get_share(BOB, COMPANY, share_b)
        check("a share made BEFORE the report was filed still shows it",
              view_b["snapshot"]["has_interview_report"] is True)
        view_a = await SH.get_share(ALICE, COMPANY, share_a)
        check("a share made after it does too",
              view_a["snapshot"]["has_interview_report"] is True)
        check("and both show the recording",
              view_a["snapshot"]["has_interview_recording"] is True
              and view_b["snapshot"]["has_interview_recording"] is True)
        check("the client reads the summary without opening the file",
              view_a["snapshot"]["interview_report_summary"].startswith("Second panel"))

        # The client view is an allow-list, and the storage layout is not part of it.
        leaked = [k for k in view_a["snapshot"]
                  if k.endswith("_key") or k == "interview_recording_url"]
        check("no S3 key or raw recording URL reaches the client", leaked == [])
        check("the internal candidate key is stripped too", "uk" not in view_a)

        # =================================================================
        section("SS10 -- three artifacts, three verbs")
        # =================================================================
        signed.clear()
        cv_link = await SH.resume_url_for_share(ALICE, COMPANY, share_a)
        check("the CV is served as a DOWNLOAD",
              signed[-1]["download_as"] is not None)
        check("and named for the candidate, not for our storage key",
              cv_link["name"].startswith("Priya Nair"))

        report_link = await SH.report_url_for_share(ALICE, COMPANY, share_a)
        check("the report is served to VIEW, with no attachment disposition",
              signed[-1]["download_as"] is None)
        check("and says so to the UI", report_link["downloadable"] is False)

        watch = await SH.recording_ref_for_share(ALICE, COMPANY, share_a)
        check("the recording is served to WATCH, with no attachment disposition",
              signed[-1]["download_as"] is None)
        check("and says so to the UI", watch["downloadable"] is False)
        check("the lease is short", watch["expires_in"] == IM.MEDIA_LEASE_SECONDS)
        check("there is no download route for the recording anywhere in the service",
              not hasattr(SH, "recording_download_for_share"))

        # Every client read of this material is attributed.
        trail = await store[M.COLL_AUDIT_LOG].find({"entity_id": share_a}).to_list(100)
        actions = {r.get("action") for r in trail}
        check("opening the report is audited", M.AUDIT_SHARE_REPORT_OPENED in actions)
        check("watching the recording is audited", M.AUDIT_SHARE_RECORDING_OPENED in actions)

        # A link recording opens on the platform that hosts it, and is never leased.
        await IM.file_recording(HR, COMPANY, uk, {"url": "https://zoom.example/rec/9",
                                                  "title": "Round 2"})
        linked = await SH.recording_ref_for_share(ALICE, COMPANY, share_a)
        check("a linked recording is returned as a link", linked["source"] == "link")
        check("with no expiry of ours to promise", linked["expires_in"] is None)

        # =================================================================
        section("SS16 -- one client's reads never reach the other's share")
        # =================================================================
        await expect_http("Bob opening Acme's share of the same candidate",
                          SH.get_share(BOB, COMPANY, share_a), 404)
        await expect_http("Bob opening Acme's interview report",
                          SH.report_url_for_share(BOB, COMPANY, share_a), 404)
        await expect_http("Bob watching Acme's recording",
                          SH.recording_ref_for_share(BOB, COMPANY, share_a), 404)
        await expect_http("a client asking where else this CV went",
                          SH.shares_for_candidate(ALICE, COMPANY, uk), 403)
        alice_shares = await SH.list_shares(ALICE, COMPANY)
        check("Alice's own list holds exactly her one share",
              [s["share_no"] for s in alice_shares["shares"]] == [share_a])
        check("and never names Borealis",
              all("Borealis" not in str(s) for s in alice_shares["shares"]))

        # =================================================================
        section("SS12 -- the actions offered follow the share's actual state")
        # =================================================================
        fresh = await SH.get_share(ALICE, COMPANY, share_a)
        check("from CV Shared a client may review, shortlist or reject",
              set(fresh["allowed_statuses"])
              == {"Under Review", "Shortlisted", "Rejected"})
        check("and is never offered Hired, which is Sparsh's to record",
              "Hired" not in fresh["allowed_statuses"])

        await SH.set_share_status(ALICE, COMPANY, share_a, {"status": "Shortlisted"})
        after = await SH.get_share(ALICE, COMPANY, share_a)
        check("once shortlisted, Approve becomes available",
              "Selected" in after["allowed_statuses"])

        await SH.set_share_status(ALICE, COMPANY, share_a,
                                  {"status": "Rejected", "remarks": "Notice too long."})
        rejected = await SH.get_share(ALICE, COMPANY, share_a)
        check("a rejected candidate stops offering Approve",
              "Selected" not in rejected["allowed_statuses"])
        check("but may still be revived to Under Review",
              rejected["allowed_statuses"] == ["Under Review"])

        # SS12's "Add Remark" and "Send Back to Sparsh": neither is a verdict.
        remarked = await SH.add_share_remark(
            ALICE, COMPANY, share_a,
            {"remarks": "Could we recheck their notice period?", "needs_attention": True})
        check("a send-back does NOT move the status",
              remarked["status"] == M.ShareStatus.REJECTED.value)
        # Read the raw row rather than the client view: `kind` is an internal marker and the
        # client view has no reason to carry it, so asserting on the view would only prove
        # that it is absent there.
        raw = await store[M.COLL_CANDIDATE_SHARES].find_one({"share_no": share_a})
        kinds = [h.get("kind") for h in raw["history"]]
        check("and is recorded as a send-back", "sent_back" in kinds)
        await expect_http("an empty remark",
                          SH.add_share_remark(ALICE, COMPANY, share_a, {"remarks": "  "}),
                          422)

        # =================================================================
        section("SS9 -- a rejected candidate can go to another client")
        # =================================================================
        onward = await SH.share_candidate(HR, COMPANY, {
            "uk": uk, "client_ids": [CLIENT_B], "note": "Reconsider?"})
        check("Sparsh may re-share; Borealis already had a live share",
              onward["skipped"] and onward["skipped"][0]["client_id"] == CLIENT_B)
        journey = await SH.shares_for_candidate(HR, COMPANY, uk)
        check("Sparsh sees the candidate's full sharing history", journey["total"] == 2)
        check("including which clients and what each decided",
              {s["client_name"] for s in journey["shares"]}
              == {"Acme Retail", "Borealis Bank"})

        # =================================================================
        section("SS13 -- create-and-send an offer no longer loses the signature")
        # =================================================================
        check("OfferIn declares a signature field",
              "signature" in M.OfferIn.model_fields)
        # The bug, precisely: the route hands the service `body.model_dump()`, and an
        # undeclared key never survives that. Asserted on the MODEL because that is where it
        # was lost, not in the service that correctly refused what it was given.
        dumped = M.OfferIn(uk=uk, ctc=1500000.0, joining_date="2026-11-02",
                           send_now=True, signature="Hana HR").model_dump()
        check("and carries it through model_dump, which is what the route sends",
              dumped["signature"] == "Hana HR")
        check("a draft-only offer still needs no signature",
              M.OfferIn(uk=uk, ctc=1.0, joining_date="2026-11-02"
                        ).model_dump()["signature"] is None)

        # And end to end, against the service that raised the error the brief reported.
        await store[M.COLL_CANDIDATES].update_one(
            {"uk": uk}, {"$set": {"application_status": M.AppStatus.SELECTED.value}})
        await expect_http(
            "create-and-send with NO signature is still refused",
            OF.create_offer(HR, COMPANY, {"uk": uk, "ctc": 1500000.0,
                                          "joining_date": "2026-11-02", "send_now": True}),
            422, "authorised signature")
        check("and no orphan draft was left behind",
              await store[M.COLL_OFFERS].count_documents({"company_id": COMPANY}) == 0)

        offer = await OF.create_offer(HR, COMPANY, {
            "uk": uk, "ctc": 1500000.0, "joining_date": "2026-11-02",
            "send_now": True, "signature": "Hana HR"})
        check("create-and-send WITH a signature succeeds",
              offer["status"] == M.OfferStatus.SENT.value)
        check("and the letter is attributable", offer["signature"] == "Hana HR")

        # =================================================================
        section("SS15 -- the capability itself, and who holds it")
        # =================================================================
        check("Sparsh HR may file an interview record",
              A.can(HR, M.Cap.INTERVIEW_MEDIA_WRITE))
        check("a client may NOT", not A.can(ALICE, M.Cap.INTERVIEW_MEDIA_WRITE))
        check("a client still cannot read the candidate collection",
              not A.can(ALICE, M.Cap.CANDIDATE_READ))
        check("nor share a CV onward to anybody",
              not A.can(ALICE, M.Cap.SHARE_WRITE))
        for role in (M.HrmsRole.MANAGER, M.HrmsRole.EMPLOYEE, M.HrmsRole.FINANCE):
            check(f"{role.value} does not hold it",
                  M.Cap.INTERVIEW_MEDIA_WRITE not in M.ROLE_CAPABILITIES[role])

        # =================================================================
        section("SS10 -- unpublishing pulls the material back from live shares")
        # =================================================================
        await IM.remove_media(HR, COMPANY, uk, "report")
        gone = await SH.get_share(ALICE, COMPANY, share_a)
        check("removing the report clears it from a live share",
              gone["snapshot"]["has_interview_report"] is False)
        await expect_http("and the client can no longer open it",
                          SH.report_url_for_share(ALICE, COMPANY, share_a), 404)
        await expect_http("removing something that is not filed",
                          IM.remove_media(HR, COMPANY, uk, "report"), 404)
        await expect_http("removing an unknown kind",
                          IM.remove_media(HR, COMPANY, uk, "transcript"), 422)

        withdrawn = await SH.withdraw_share(HR, COMPANY, share_a, {"remarks": "Filled."})
        check("Sparsh can withdraw the share", withdrawn["status"] == "Withdrawn")
        await expect_http("a withdrawn share serves no recording",
                          SH.recording_ref_for_share(ALICE, COMPANY, share_a), 410)
        await expect_http("and takes no remarks",
                          SH.add_share_remark(ALICE, COMPANY, share_a,
                                              {"remarks": "hello"}), 410)

    finally:
        mongo.get_collection = original
        NS.notify_user, NS.notify_users, NS.notify_hrms_role = keep
        S3.upload_file_to_s3_with_key = keep_s3
        S3.get_signed_url = keep_url
        BG.assert_background_cleared = keep_bg

    print()
    total, passed = len(results), sum(results)
    print("=" * 70)
    print(f"  {passed}/{total} checks passed")
    print("=" * 70)
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
