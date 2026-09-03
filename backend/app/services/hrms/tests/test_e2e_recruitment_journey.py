"""End-to-end recruitment scenario -- one company, one hiring season, six candidates.

Every other harness in this directory verifies ONE phase against fixtures hand-placed at
the stage that phase begins. This one starts from an empty database and drives the whole
module through the real services, in order, with realistic data:

    requisition + JD -> HR review -> MD approval -> posting (one link)
    -> six public applications, each naming its own channel
    -> screening (shortlist / reject / hold / duplicate)
    -> assessment (issue -> candidate submits -> two reviewers -> pass or fail)
    -> interviews (HR -> Technical -> MD, pass and fail paths)
    -> selection -> offer (accepted and declined)
    -> appointment letter -> acknowledgement
    -> onboarding -> KYC -> background check -> checklist -> Employee ID

It exists to catch what per-phase tests structurally cannot: a stage that writes a field
the NEXT stage reads differently, a status the graph allows but no service produces, or a
figure that only reconciles when every step ran for real. Wherever a rule is enforced it is
also probed from the wrong side -- interviewing before the assessment passed, offering to
somebody not Selected, onboarding before acceptance, issuing an Employee ID with KYC
unverified.

The cast:
  Hana Shirke     HR             -- runs the pipeline
  Mira Bhatt      MD             -- approves requisitions, takes the final round
  Rajat Menon     HOD / raiser   -- hiring manager, co-reviews assessments
  Priya Nair      employee       -- refers a candidate

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_e2e_recruitment_journey   (from backend/)
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
    except Exception as e:  # noqa: BLE001
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "NWA"
NOW = datetime.now(timezone.utc)
IN_2_DAYS = (NOW + timedelta(days=2)).strftime("%Y-%m-%d")
IN_45_DAYS = (NOW + timedelta(days=45)).strftime("%Y-%m-%d")
IN_60_DAYS = (NOW + timedelta(days=60)).strftime("%Y-%m-%d")


def at(days: int, hour: int = 10) -> str:
    """An ISO timestamp `days` from now -- interviews must be in the future."""
    return (NOW + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0).isoformat()


async def main() -> None:  # noqa: C901 -- a linear scenario reads better in one piece
    from bson import ObjectId

    from app.models import hrms as M

    # ── Phase 12 ── the background-verification gate now stands in front of every offer,
    # on both tracks. This file measures a different control, so the gate is stubbed here
    # exactly as the shortlist and telephonic gates are elsewhere -- each has its own test
    # file (test_int12_client_track), and a failure here should name THIS file's control
    # rather than a precondition it never set up.
    import app.services.hrms_background_service as _BGV

    async def _bg_cleared(*_a, **_kw):
        return None
    _BGV.assert_background_cleared = _bg_cleared
    import app.db.mongodb as mongo

    S = M.AppStatus

    U_HR, U_MD, U_HOD, U_PRIYA = (str(ObjectId()) for _ in range(4))
    DEPT_ANALYTICS, DESIG_ANALYST = str(ObjectId()), str(ObjectId())
    DEPT_DESIGN, DESIG_DESIGNER = str(ObjectId()), str(ObjectId())

    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "full_name": "Hana Shirke", "email": "hana@northwind.in",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "HR",
         "is_active": True},
        {"_id": ObjectId(U_MD), "full_name": "Mira Bhatt", "email": "mira@northwind.in",
         "company_id": COMPANY, "role": "clientadmin", "is_active": True},
        {"_id": ObjectId(U_HOD), "full_name": "Rajat Menon", "email": "rajat@northwind.in",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "HOD",
         "is_active": True},
        {"_id": ObjectId(U_PRIYA), "full_name": "Priya Nair", "email": "priya@northwind.in",
         "company_id": COMPANY, "role": "clientuser", "is_active": True},
    ])
    departments = FakeCollection([
        {"_id": ObjectId(DEPT_ANALYTICS), "company_id": COMPANY, "name": "Analytics",
         "active": True},
        {"_id": ObjectId(DEPT_DESIGN), "company_id": COMPANY, "name": "Design",
         "active": True},
    ])
    designations = FakeCollection([
        {"_id": ObjectId(DESIG_ANALYST), "company_id": COMPANY, "name": "Senior Data Analyst",
         "active": True},
        {"_id": ObjectId(DESIG_DESIGNER), "company_id": COMPANY, "name": "UX Designer",
         "active": True},
    ])
    profiles = FakeCollection([
        # Priya is on the payroll, which is what makes her employee code resolvable when a
        # candidate names her as their referrer.
        {"_id": ObjectId(), "company_id": COMPANY, "employee_code": "EMP-2025-014",
         "employee_name": "Priya Nair", "user_id": U_PRIYA, "status": "Active"},
    ])

    store = {
        M.COLL_REQUISITIONS: FakeCollection(), M.COLL_JOB_DESCRIPTIONS: FakeCollection(),
        M.COLL_JOB_POSTINGS: FakeCollection(), M.COLL_CANDIDATES: FakeCollection(),
        M.COLL_ASSESSMENTS: FakeCollection(), M.COLL_INTERVIEWS: FakeCollection(),
        M.COLL_OFFERS: FakeCollection(), M.COLL_APPOINTMENTS: FakeCollection(),
        M.COLL_ONBOARDING: FakeCollection(), M.COLL_EMPLOYEE_PROFILES: profiles,
        M.COLL_DEPARTMENTS: departments, M.COLL_DESIGNATIONS: designations,
        M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
        M.COLL_LINKS: FakeCollection(), M.COLL_DOCUMENTS: FakeCollection(),
        M.COLL_DOCUMENT_TYPES: FakeCollection(),
        M.COLL_PUBLIC_RATELIMIT: FakeCollection(),
        M.COLL_SANCTIONED_STRENGTH: FakeCollection(),
        "learners": learners, "staff": FakeCollection(),
    }
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    candidates = store[M.COLL_CANDIDATES]
    audit_log = store[M.COLL_AUDIT_LOG]
    links = store[M.COLL_LINKS]
    documents = store[M.COLL_DOCUMENTS]

    import app.services.hrms_requisition_service as RS
    import app.services.hrms_posting_service as PS
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_assessment_service as ASM
    import app.services.hrms_interview_service as IV
    import app.services.hrms_offer_service as OF
    import app.services.hrms_appointment_service as AP
    import app.services.hrms_onboarding_service as OB
    import app.services.hrms_employee_service as ES
    import app.services.hrms_referral_service as RF
    import app.services.hrms_link_service as LS
    import app.services.hrms_document_service as DS
    import app.services.hrms_sanction_service as SN
    import app.services.hrms_analytics_service as AN
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_public_guard as G

    SERVICES = (RS, PS, CS, ASM, IV, OF, AP, OB, ES, RF, LS, DS, SN, AN, AUD, IDS, G)
    for mod in SERVICES:
        mod.get_collection = mongo.get_collection

    # Notifications are recorded, not sent. Every service that can notify is stubbed, so a
    # missing notification is a visible gap rather than a silent one.
    sent = []

    async def fake_notify_user(uid, title, msg, **kw):
        sent.append(("user", str(uid), title))

    async def fake_notify_role(cid, roles, title, msg, **kw):
        sent.append(("role", tuple(roles), title))

    for mod in (RS, PS, CS, ASM, IV, OF, AP, OB, RF):
        if hasattr(mod, "notify_user"):
            mod.notify_user = fake_notify_user
        if hasattr(mod, "notify_hrms_role"):
            mod.notify_hrms_role = fake_notify_role
    # Patched at the SOURCE as well: several services import notify_user inside the function
    # body (to break an import cycle), so a module-attribute stub alone would miss them --
    # and hrms_referral_service swallows notification errors, which would turn a missing
    # referrer notification into a silent pass.
    import app.services.hrms_notify_service as NS
    original_notify = (NS.notify_user, NS.notify_hrms_role)
    NS.notify_user, NS.notify_hrms_role = fake_notify_user, fake_notify_role

    uploaded = []

    def fake_s3(stream, filename, mime):
        uploaded.append(filename)
        return {"key": f"s3/{filename}", "url": "https://signed.example/x"}

    import app.services.s3_service as S3
    original_s3 = S3.upload_file_to_s3_with_key
    S3.upload_file_to_s3_with_key = fake_s3

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana Shirke"}
    MD = {"_id": U_MD, "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY, "full_name": "Mira Bhatt"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD", "full_name": "Rajat Menon"}

    def resume(name="resume.pdf"):
        # "%PDF-1.4 …" base64 -- decode_upload sniffs the magic bytes, so a placeholder
        # string would be rejected as a disguised file.
        import base64
        return {"name": name, "mime_type": "application/pdf",
                "data": base64.b64encode(b"%PDF-1.4 curriculum vitae").decode()}

    async def status_of(uk):
        return (await candidates.find_one({"uk": uk}))["application_status"]

    try:
        # =================================================================
        section("1. Requisition + JD -- raised by the hiring manager")
        # =================================================================
        req = await RS.create_requisition(HOD, COMPANY, {
            "department_id": DEPT_ANALYTICS, "designation_id": DESIG_ANALYST,
            "assignee_id": U_HR, "vacancy": 2, "required_date": IN_60_DAYS,
            "experience_required": "4-7 years", "qualification": "B.Tech / MSc Statistics",
            "essential_skills": "SQL, Python, dbt, stakeholder communication",
            "employment_type": "Full-time", "work_location": "Pune (hybrid)",
            "urgency_level": "High", "offering_ctc": 1800000,
            "notes": "Backfill plus one net-new seat for the retail analytics pod.",
            "jd": {
                "title": "Senior Data Analyst",
                "responsibilities": ("Own the retail reporting layer end to end: model the "
                                     "warehouse tables, ship dbt transformations, and partner "
                                     "with category managers on weekly trading reviews."),
                "skills": "Advanced SQL, Python (pandas), dbt, Looker",
                "qualifications": "B.Tech or MSc in Statistics, Maths or Computer Science",
                "experience": "4-7 years in product or retail analytics",
                "location": "Pune (hybrid, 3 days on site)",
                "ctc": "16-20 LPA",
                "benefits": "Health cover for family, annual learning budget, ESOPs",
                "employment_type": "Full-time",
            },
        })
        REQ = req["request_no"]
        JD = req["jd_no"]
        check("requisition raised with a business id", REQ.startswith("HR-REQ-"))
        check("its JD is created in the same call", JD.startswith("JD-"))
        check("requisition starts at Pending HR Review",
              req["approval_status"] == M.ReqApproval.PENDING_HR.value)
        check("the raiser is recorded as the hiring manager",
              req["created_by"] == U_HOD and req["created_by_name"] == "Rajat Menon")
        check("department and designation are resolved from the masters, not free text",
              req["department_name"] == "Analytics"
              and req["designation_name"] == "Senior Data Analyst")
        check("the requisition opens with vacancy 2 and is Open",
              req["vacancy"] == 2 and req["closing_status"] == M.ReqClosing.OPEN.value)

        jd_doc = await RS.get_jd(HR, COMPANY, JD)
        check("the JD carries the drafted content",
              "retail reporting layer" in jd_doc["responsibilities"])
        check("the JD is Pending Approval, not usable yet",
              jd_doc["status"] == M.JdStatus.PENDING_APPROVAL.value)

        section("1b. A requisition cannot skip its own rules")
        await expect_http("a requisition with no JD content", RS.create_requisition(
            HOD, COMPANY, {"department_id": DEPT_DESIGN, "designation_id": DESIG_DESIGNER,
                           "assignee_id": U_HR, "required_date": IN_60_DAYS,
                           "experience_required": "2 years", "qualification": "Any",
                           "essential_skills": "Figma", "jd": {}}), 422, "Job Description")
        await expect_http("vacancy of zero", RS.create_requisition(
            HOD, COMPANY, {"department_id": DEPT_ANALYTICS, "designation_id": DESIG_ANALYST,
                           "assignee_id": U_HR, "vacancy": 0, "required_date": IN_60_DAYS,
                           "experience_required": "4 years", "qualification": "B.Tech",
                           "essential_skills": "SQL",
                           "jd": {"responsibilities": "x"}}), 422, "at least 1")
        await expect_http("an unknown department", RS.create_requisition(
            HOD, COMPANY, {"department_id": str(ObjectId()), "designation_id": DESIG_ANALYST,
                           "assignee_id": U_HR, "required_date": IN_60_DAYS,
                           "experience_required": "4 years", "qualification": "B.Tech",
                           "essential_skills": "SQL",
                           "jd": {"responsibilities": "x"}}), 422, "Department")

        # =================================================================
        section("2. Approval chain -- HR review, then MD")
        # =================================================================
        await expect_http("publishing before approval", PS.create_posting(
            HR, COMPANY, {"jd_no": JD}), 409, "approved job description")
        await expect_http("the MD approving before HR has reviewed", RS.act_on_requisition(
            MD, COMPANY, REQ, "md-approve"), 409)
        await expect_http("HR rejecting with no reason", RS.act_on_requisition(
            HR, COMPANY, REQ, "hr-reject"), 422)
        await expect_http("an invented approval action", RS.act_on_requisition(
            HR, COMPANY, REQ, "rubber-stamp"), 422, "Invalid action")

        after_hr = await RS.act_on_requisition(
            HR, COMPANY, REQ, "hr-approve",
            remarks="Headcount confirmed against the FY plan. Band and CTC look right.")
        check("HR review moves it to Pending MD Approval",
              after_hr["approval_status"] == M.ReqApproval.PENDING_MD.value)
        check("HR's remarks are kept on the record",
              "Headcount confirmed" in (after_hr["hr_remarks"] or ""))
        check("an in-sanction requisition never enters the escalation detour",
              after_hr.get("escalation_chain") == [])

        approved = await RS.act_on_requisition(
            MD, COMPANY, REQ, "md-approve",
            remarks="Approved. Fill both seats this quarter.", salary_change=1900000)
        check("MD approval closes the chain",
              approved["approval_status"] == M.ReqApproval.APPROVED.value)
        check("the MD's revised CTC is recorded",
              approved["offering_ctc"] == 1900000 and approved["salary_change"] == 1900000)
        jd_doc = await RS.get_jd(HR, COMPANY, JD)
        check("the JD is co-approved with its requisition -- no second workflow",
              jd_doc["status"] == M.JdStatus.APPROVED.value)
        check("the approval was audited",
              any(a["entity_id"] == REQ and a["action"] == M.AUDIT_REQ_MD_APPROVED
                  for a in audit_log.docs))
        check("the raiser was told their requisition cleared",
              any(s[0] == "user" and s[1] == U_HOD for s in sent))

        # =================================================================
        section("3. Publishing -- ONE posting, ONE link")
        # =================================================================
        published = await PS.create_posting(HR, COMPANY, {
            "jd_no": JD, "requires_assessment": True, "expiry_date": IN_45_DAYS,
            "notes": "Share on LinkedIn, Naukri and the alumni WhatsApp group."})
        POST = published["posting"]["posting_code"]
        check("publishing creates exactly one posting", published["created"] == 1)
        check("the code matches the public pattern",
              M.POSTING_CODE_RE.match(POST) is not None)
        check("the posting carries no platform -- the applicant supplies the channel",
              "platform" not in published["posting"])
        check("the posting is Live with the assessment flag set",
              published["posting"]["live_status"] == M.LiveStatus.LIVE.value
              and published["posting"]["requires_assessment"] is True)
        check("its apply link is registered in the link register",
              any(l["target_id"] == POST and l["kind"] == M.LinkKind.APPLY.value
                  for l in links.docs))
        await expect_http("publishing the same JD twice", PS.create_posting(
            HR, COMPANY, {"jd_no": JD}), 409, "already published")

        ad = await PS.get_public_posting(POST)
        check("the public ad shows the role and its requisition context",
              ad["title"] == "Senior Data Analyst" and ad["vacancies"] == 2
              and ad["department"] == "Analytics")
        for leak in ("company_id", "jd_no", "request_no", "requires_assessment", "notes"):
            check(f"the world-readable ad does not leak {leak}", leak not in ad)

        # =================================================================
        section("4. Six applications, each naming its own channel")
        # =================================================================
        def application(name, email, phone, source, **over):
            base = {
                "candidate_name": name, "can_email": email, "can_contact": phone,
                "declaration": True, "referral_source": source,
                "current_location": "Pune", "notice_period": "60 days",
                "qualification": "B.Tech, Computer Science",
                "total_experience": "5 years", "current_company": "Zeta Retail",
                "current_ctc": "1450000", "expected_ctc": "1850000",
                "linkedin": f"https://linkedin.com/in/{email.split('@')[0]}",
                "cover_note": "I have shipped dbt models for a retail warehouse before.",
                "resume": resume(), "certificates": [],
            }
            base.update(over)
            return base

        ananya = await PS.submit_application(POST, application(
            "Ananya Iyer", "Ananya.Iyer@example.com", "+91 98200 11223", "Job Portal",
            total_experience="6 years", current_company="Flipkart"))
        rohan = await PS.submit_application(POST, application(
            "Rohan Deshmukh", "rohan.d@example.com", "+91 98200 11224", "Social Media",
            total_experience="1 year", qualification="BA Economics",
            cover_note="Looking to switch into analytics."))
        meera = await PS.submit_application(POST, application(
            "Meera Krishnan", "meera.k@example.com", "+91 98200 11225", "Employee",
            is_referral=True, referred_by="Priya Nair",
            referrer_employee_code="emp-2025-014", referral_relation="Former colleague"))
        sana = await PS.submit_application(POST, application(
            "Sana Qureshi", "sana.q@example.com", "+91 98200 11226", "Consultant / Agency",
            total_experience="7 years", current_company="Tata Digital"))
        kabir = await PS.submit_application(POST, application(
            "Kabir Shah", "kabir.shah@example.com", "+91 98200 11227", "Job Portal",
            total_experience="4 years"))

        A, R, ME, SA, K = (r["reference"] for r in (ananya, rohan, meera, sana, kabir))
        check("five applications accepted with candidate ids",
              all(uk.startswith("CAN-") for uk in (A, R, ME, SA, K))
              and len({A, R, ME, SA, K}) == 5)

        dup = await PS.submit_application(POST, application(
            "Ananya Iyer", "ananya.iyer@example.com", "+91 98200 11223", "Job Portal"))
        check("a re-submission is idempotent, not a second record",
              dup["duplicate"] is True and dup["reference"] == A)
        check("only five candidate rows exist", len(candidates.docs) == 5)

        ananya_doc = await candidates.find_one({"uk": A})
        check("email is normalised to lowercase",
              ananya_doc["can_email"] == "ananya.iyer@example.com")
        check("the resume is stored as an S3 key, not an expiring URL",
              ananya_doc["resume"]["key"].startswith("s3/")
              and "url" not in ananya_doc["resume"])
        opening_stages = [await status_of(uk) for uk in (A, R, ME, SA, K)]
        check("every applicant lands at Applied",
              opening_stages == [S.APPLIED.value] * 5)
        check("the posting's assessment flag is copied onto each applicant",
              ananya_doc["requires_assessment"] is True)
        check("the requisition and JD are linked through from the posting",
              ananya_doc["request_no"] == REQ and ananya_doc["jd_no"] == JD)

        section("4b. Source comes from the applicant, not the link")
        check("Ananya's source is the channel she named",
              ananya_doc["source"] == "Job Portal")
        rohan_doc = await candidates.find_one({"uk": R})
        check("Rohan came through social media and is filed there",
              rohan_doc["source"] == "Social Media")
        meera_doc = await candidates.find_one({"uk": ME})
        check("Meera's referral is filed under Referral, not the channel",
              meera_doc["source"] == M.REFERRAL_SOURCE_LABEL
              and meera_doc["referral_source"] == "Employee")
        check("the referrer was resolved server-side from the code alone",
              meera_doc["referrer_name"] == "Priya Nair"
              and meera_doc["referrer_employee_code"] == "EMP-2025-014"
              and meera_doc["referrer_user_id"] == U_PRIYA)
        check("Priya was told her referral applied",
              any(s[0] == "user" and s[1] == U_PRIYA for s in sent))

        section("4c. The public form refuses what it should")
        await expect_http("no channel named", PS.submit_application(
            POST, application("No Source", "ns@example.com", "9820011230", None)),
            422, "where you found this job")
        await expect_http("a made-up channel", PS.submit_application(
            POST, application("Bad Source", "bs@example.com", "9820011231", "Telepathy")),
            422, "valid referral source")
        await expect_http("an employee referral naming an unknown colleague",
                          PS.submit_application(POST, application(
                              "Ghost Ref", "gr@example.com", "9820011232", "Employee",
                              is_referral=True, referred_by="Nobody",
                              referrer_employee_code="EMP-2025-999")),
                          422, "could not verify")
        await expect_http("a malformed email", PS.submit_application(
            POST, application("Bad Mail", "not-an-email", "9820011233", "Job Portal")),
            422, "valid email")
        await expect_http("the declaration left unticked", PS.submit_application(
            POST, application("No Tick", "nt@example.com", "9820011234", "Job Portal",
                              declaration=False)), 422, "accurate")

        # A walk-in CV, typed in by HR rather than applied for. Same pipeline from here on.
        walkin = await CS.create_candidate(HR, COMPANY, {
            "candidate_name": "Vikram Rao", "can_email": "vikram.rao@example.com",
            "can_contact": "+91 98200 11228", "request_no": REQ, "source": "Walk-in",
            "total_experience": "5 years", "qualification": "MSc Statistics",
            "expected_ctc": "1750000", "notice_period": "Immediate"})
        V = walkin["uk"]
        check("HR can add a walk-in candidate onto the same requisition",
              walkin["source"] == "Walk-in" and walkin["request_no"] == REQ)
        check("a manually added candidate inherits the posting's assessment requirement",
              walkin["requires_assessment"] is True)

        # =================================================================
        section("5. HR screening")
        # =================================================================
        await expect_http("rejecting without a reason", CS.screen_candidates(
            HR, COMPANY, {"uks": [R], "action": "reject"}), 422, "reason is required")
        await expect_http("screening nobody", CS.screen_candidates(
            HR, COMPANY, {"uks": [], "action": "shortlist"}), 422, "at least one")
        await expect_http("an invented action", CS.screen_candidates(
            HR, COMPANY, {"uks": [A], "action": "promote"}), 422, "Invalid action")

        reviewed = await CS.screen_candidates(HR, COMPANY, {
            "uks": [A, ME, SA, K, V], "action": "review",
            "remarks": "First pass on the retail analytics shortlist."})
        check("a batch of five moves to Under Review", len(reviewed["moved"]) == 5)

        shortlisted = await CS.screen_candidates(HR, COMPANY, {
            "uks": [A, ME, SA, V], "action": "shortlist",
            "remarks": "Strong SQL and warehouse modelling evidence."})
        check("four are shortlisted", len(shortlisted["moved"]) == 4)
        # This role requires an assessment, and the flag was copied onto each applicant when
        # they applied. Shortlisting therefore resolves to Assessment Pending rather than
        # Shortlisted -- the point of copying the flag at apply time.
        check("shortlisting an assessment role lands on Assessment Pending",
              await status_of(A) == S.ASSESSMENT_PENDING.value)
        check("...and the Shortlisted hop is still recorded, so the history stays legal",
              any(a["entity_id"] == A and a["action"] == M.AUDIT_STAGE_CHANGED
                  and f"-> {S.SHORTLISTED.value}" in (a.get("detail") or "")
                  for a in audit_log.docs))

        held = await CS.screen_candidates(HR, COMPANY, {
            "uks": [K], "action": "hold", "remarks": "Waiting on his notice-period answer."})
        check("Kabir is parked On Hold", len(held["moved"]) == 1
              and await status_of(K) == S.ON_HOLD.value)

        rejected = await CS.screen_candidates(HR, COMPANY, {
            "uks": [R], "action": "reject",
            "remarks": "One year of experience against a 4-7 year brief."})
        check("Rohan is rejected with the reason recorded",
              len(rejected["moved"]) == 1 and await status_of(R) == S.REJECTED.value)
        rohan_doc = await candidates.find_one({"uk": R})
        check("the rejection reason is stored on the candidate",
              "One year of experience" in (rohan_doc.get("screening_remarks") or ""))

        # A sweep over one candidate who can move and one who is already there: the batch is
        # partially applied and reports why, rather than failing wholesale and leaving the
        # recruiter to work out which row blocked it.
        mixed = await CS.screen_candidates(HR, COMPANY, {
            "uks": [K, A], "action": "shortlist", "remarks": "Second sweep."})
        check("a batch is partially applied, not failed wholesale",
              len(mixed["moved"]) == 1 and mixed["moved"][0]["uk"] == K
              and len(mixed["skipped"]) == 1 and mixed["skipped"][0]["uk"] == A)
        check("the skip explains itself rather than reporting a generic failure",
              "already" in mixed["skipped"][0]["reason"])
        await CS.screen_candidates(HR, COMPANY, {
            "uks": [K], "action": "hold", "remarks": "Still waiting on his notice period."})

        # A rejection is reversible by design -- the graph carries a REJECTED -> UNDER_REVIEW
        # edge because recruiters do reconsider. Verified here and then undone, so the run
        # ends with Rohan rejected as intended.
        revived = await CS.screen_candidates(HR, COMPANY, {
            "uks": [R], "action": "review", "remarks": "Reconsidering after a referral."})
        check("a rejected candidate can be revived to Under Review",
              len(revived["moved"]) == 1 and await status_of(R) == S.UNDER_REVIEW.value)
        await CS.screen_candidates(HR, COMPANY, {
            "uks": [R], "action": "reject",
            "remarks": "Confirmed: one year against a 4-7 year brief."})
        check("...and rejected again", await status_of(R) == S.REJECTED.value)

        journey = await CS.get_journey(HR, COMPANY, A)
        check("the candidate journey replays the screening trail from the audit log",
              len(journey["events"]) >= 3)
        check("the journey rail knows how far the candidate has come",
              journey["reached"] >= 0 and journey["terminal"] is False)

        # =================================================================
        section("6. Assessment -- the gate this role turns on")
        # =================================================================
        await expect_http("interviewing before the assessment is passed",
                          IV.schedule_interview(HR, COMPANY, {
                              "uk": A, "round": "HR Round", "scheduled_at": at(3),
                              "mode": "Virtual", "interviewer_id": U_HR,
                              "meeting_link": "https://meet.northwind.in/early"}),
                          409, "requires an assessment")

        asm_a = await ASM.send_assessment(HR, COMPANY, {
            "uk": A, "title": "Retail SQL + modelling case",
            "instructions": "Model the attached order feed and answer the five questions.",
            "max_score": 50, "due_date": IN_2_DAYS,
            "link": "https://forms.northwind.in/analyst-case"})
        asm_m = await ASM.send_assessment(HR, COMPANY, {
            "uk": ME, "title": "Retail SQL + modelling case", "max_score": 50,
            "due_date": IN_2_DAYS})
        asm_s = await ASM.send_assessment(HR, COMPANY, {
            "uk": SA, "title": "Retail SQL + modelling case", "max_score": 50})
        asm_v = await ASM.send_assessment(HR, COMPANY, {
            "uk": V, "title": "Retail SQL + modelling case", "max_score": 50})
        check("assessments are issued with business ids",
              all(a["assessment_no"].startswith("ASM-")
                  for a in (asm_a, asm_m, asm_s, asm_v)))
        check("the candidate moves to Assessment Pending",
              await status_of(A) == S.ASSESSMENT_PENDING.value)
        check("the hiring manager is set as the second reviewer",
              asm_a["manager_id"] == U_HOD)
        await expect_http("a second open assessment for the same candidate",
                          ASM.send_assessment(HR, COMPANY, {"uk": A, "title": "Again"}),
                          409, "already has an open assessment")
        await expect_http("an assessment for a rejected candidate",
                          ASM.send_assessment(HR, COMPANY, {"uk": R, "title": "Case"}),
                          409, "assessment stage")

        code_a = (await store[M.COLL_ASSESSMENTS].find_one(
            {"assessment_no": asm_a["assessment_no"]}))["access_code"]
        public = await ASM.get_public_assessment(code_a)
        check("the candidate's page shows the brief without internal fields",
              public["title"] == "Retail SQL + modelling case"
              and "company_id" not in public and "hr_decision" not in public)
        check("opening the link marks it Opened",
              (await store[M.COLL_ASSESSMENTS].find_one(
                  {"assessment_no": asm_a["assessment_no"]}))["status"]
              == M.AssessmentStatus.OPENED.value)

        await expect_http("an empty submission", ASM.submit_public_assessment(
            code_a, {"response": "", "attachments": []}), 422, "attach at least one")
        submitted = await ASM.submit_public_assessment(code_a, {
            "response": ("Star schema with a daily grain fact and three conformed "
                         "dimensions; window functions for the basket questions."),
            "attachments": [resume("case-answers.pdf")]})
        check("the submission is accepted", submitted["ok"] is True)
        check("the candidate is now Assessment Completed",
              await status_of(A) == S.ASSESSMENT_COMPLETED.value)
        await expect_http("submitting twice", ASM.submit_public_assessment(
            code_a, {"response": "again"}), 409, "already submitted")

        await expect_http("reviewing before submission", ASM.review_assessment(
            HR, COMPANY, asm_m["assessment_no"], {"decision": "Pass"}),
            409, "not been submitted")

        first = await ASM.review_assessment(HR, COMPANY, asm_a["assessment_no"], {
            "decision": "Pass", "score": 43,
            "remarks": "Clean modelling, good grain discipline."})
        check("one reviewer alone does not resolve it",
              first["hr_decision"] == M.Decision.PASS.value
              and first.get("outcome") is None
              and first["lifecycle"] == "Submitted")
        check("the candidate is held at Assessment Completed until both agree",
              await status_of(A) == S.ASSESSMENT_COMPLETED.value)
        await expect_http("the same reviewer deciding twice", ASM.review_assessment(
            HR, COMPANY, asm_a["assessment_no"], {"decision": "Fail"}),
            409, "already been recorded")

        resolved = await ASM.review_assessment(HOD, COMPANY, asm_a["assessment_no"], {
            "decision": "Pass", "remarks": "Would hire on this alone."})
        check("both reviewers agreeing resolves it to Pass",
              resolved.get("outcome") == M.Decision.PASS.value
              and resolved["status"] == M.AssessmentStatus.REVIEWED.value
              and resolved["lifecycle"] == "Passed")
        check("Ananya is now Assessment Passed",
              await status_of(A) == S.ASSESSMENT_PASSED.value)
        check("the score is kept with its recommendation",
              resolved["score"] == 43 and resolved.get("recommendation"))

        # Meera fails: one Fail decides it, whichever slot casts it.
        code_m = (await store[M.COLL_ASSESSMENTS].find_one(
            {"assessment_no": asm_m["assessment_no"]}))["access_code"]
        await ASM.get_public_assessment(code_m)
        await ASM.submit_public_assessment(code_m, {"response": "Answers attached inline."})
        await ASM.review_assessment(HR, COMPANY, asm_m["assessment_no"], {
            "decision": "Pass", "score": 31})
        meera_asm = await ASM.review_assessment(HOD, COMPANY, asm_m["assessment_no"], {
            "decision": "Fail", "remarks": "Joins were wrong on the returns question."})
        check("a single Fail decides the outcome",
              meera_asm.get("outcome") == M.Decision.FAIL.value
              and meera_asm["lifecycle"] == "Failed")
        check("Meera is Assessment Failed", await status_of(ME) == S.ASSESSMENT_FAILED.value)
        await expect_http("interviewing a candidate who failed the assessment",
                          IV.schedule_interview(HR, COMPANY, {
                              "uk": ME, "round": "HR Round", "scheduled_at": at(3),
                              "mode": "Virtual", "interviewer_id": U_HR,
                              "meeting_link": "https://meet.northwind.in/meera"}),
                          409, "Assessment Passed")

        # Sana and Vikram pass, so the later stages have more than one live candidate.
        for asm_no, uk in ((asm_s["assessment_no"], SA), (asm_v["assessment_no"], V)):
            code = (await store[M.COLL_ASSESSMENTS].find_one(
                {"assessment_no": asm_no}))["access_code"]
            await ASM.get_public_assessment(code)
            await ASM.submit_public_assessment(code, {"response": "Submitted."})
            await ASM.review_assessment(HR, COMPANY, asm_no, {"decision": "Pass", "score": 38})
            await ASM.review_assessment(HOD, COMPANY, asm_no, {"decision": "Pass"})
        check("Sana and Vikram also clear the gate",
              await status_of(SA) == S.ASSESSMENT_PASSED.value
              and await status_of(V) == S.ASSESSMENT_PASSED.value)

        # =================================================================
        section("7. Interviews -- HR, Technical, MD")
        # =================================================================
        await expect_http("an interview in the past", IV.schedule_interview(
            HR, COMPANY, {"uk": A, "round": "HR Round", "scheduled_at": at(-2),
                          "interviewer_id": U_HR}), 422, "in the past")
        await expect_http("a virtual interview with no meeting link", IV.schedule_interview(
            HR, COMPANY, {"uk": A, "round": "HR Round", "scheduled_at": at(3),
                          "mode": "Virtual", "interviewer_id": U_HR,
                          "meeting_link": ""}), 422, "link")
        await expect_http("an offline interview with no venue", IV.schedule_interview(
            HR, COMPANY, {"uk": A, "round": "HR Round", "scheduled_at": at(3),
                          "mode": "Offline", "interviewer_id": U_HR,
                          "location": ""}), 422, "location")
        await expect_http("an invented round", IV.schedule_interview(
            HR, COMPANY, {"uk": A, "round": "Coffee Chat", "scheduled_at": at(3),
                          "mode": "Virtual", "interviewer_id": U_HR,
                          "meeting_link": "https://meet.northwind.in/x"}), 422, "Round must be")

        # Scores are the six declared competencies, 0-5 each -- one declaration shared by the
        # form, the average and this test, so they cannot drift apart.
        def scorecard(outcome, signature, technical, communication, problem_solving,
                      behavior, confidence, team_fit, remarks=None):
            return {"outcome": outcome, "signature": signature, "technical": technical,
                    "communication": communication, "problem_solving": problem_solving,
                    "behavior": behavior, "confidence": confidence, "team_fit": team_fit,
                    "remarks": remarks}

        iv_hr = await IV.schedule_interview(HR, COMPANY, {
            "uk": A, "round": "HR Round", "scheduled_at": at(3), "duration_min": 45,
            "mode": "Virtual", "meeting_link": "https://meet.northwind.in/ananya-hr",
            "interviewer_id": U_HR})
        check("the HR round is scheduled", iv_hr["interview_no"].startswith("INT-"))
        check("the interviewer is resolved from the company's own users",
              iv_hr["interviewer_name"] == "Hana Shirke")
        check("the candidate reads Interview Scheduled",
              await status_of(A) == S.INTERVIEW_SCHEDULED.value)
        check("a calendar invite is generated for the slot",
              "BEGIN:VCALENDAR" in IV.invite_for(
                  await store[M.COLL_INTERVIEWS].find_one(
                      {"interview_no": iv_hr["interview_no"]})))

        await expect_http("scoring outside the 0-5 scale", IV.evaluate_interview(
            HR, COMPANY, iv_hr["interview_no"],
            scorecard("Pass", "Hana Shirke", 4, 9, 4, 4, 4, 4)), 422, "between")
        await expect_http("an unsigned evaluation", IV.evaluate_interview(
            HR, COMPANY, iv_hr["interview_no"],
            scorecard("Pass", "", 4, 4, 4, 4, 4, 4)), 422, "sign")

        ev_hr = await IV.evaluate_interview(HR, COMPANY, iv_hr["interview_no"], scorecard(
            "Pass", "Hana Shirke", 4, 5, 4, 5, 4, 5,
            "Articulate, asks good questions about the trading calendar."))
        check("the scorecard averages the six competencies",
              ev_hr["average_score"] == 4.5)
        check("the evaluation is attributed and the interview Completed",
              ev_hr["eval_by_name"] == "Hana Shirke"
              and ev_hr["status"] == M.InterviewStatus.COMPLETED.value)
        check("passing the HR round advances the stage",
              await status_of(A) == S.TECHNICAL_ROUND.value)
        await expect_http("evaluating the same interview twice", IV.evaluate_interview(
            HR, COMPANY, iv_hr["interview_no"],
            scorecard("Fail", "Hana Shirke", 1, 1, 1, 1, 1, 1)),
            409, "already been evaluated")

        iv_tech = await IV.schedule_interview(HOD, COMPANY, {
            "uk": A, "round": "Technical", "scheduled_at": at(5), "duration_min": 60,
            "mode": "Virtual", "meeting_link": "https://meet.northwind.in/ananya-tech",
            "interviewer_id": U_HOD})
        await IV.evaluate_interview(HOD, COMPANY, iv_tech["interview_no"], scorecard(
            "Pass", "Rajat Menon", 5, 4, 5, 4, 4, 5,
            "Modelled the incremental load correctly and unprompted."))
        check("passing the technical round routes to the MD round",
              await status_of(A) == S.MD_ROUND.value)

        iv_md = await IV.schedule_interview(HR, COMPANY, {
            "uk": A, "round": "MD Round", "scheduled_at": at(7), "duration_min": 30,
            "mode": "Offline", "location": "Northwind HQ, Baner, Pune",
            "interviewer_id": U_MD})
        await expect_http("HR recording the MD's decision", IV.evaluate_interview(
            HR, COMPANY, iv_md["interview_no"],
            scorecard("Pass", "Hana Shirke", 4, 4, 4, 4, 4, 4)), 403, "Only the MD")
        await IV.evaluate_interview(MD, COMPANY, iv_md["interview_no"], scorecard(
            "Pass", "Mira Bhatt", 5, 5, 5, 4, 5, 4, "Clear thinker. Make the offer."))
        check("clearing the MD round selects the candidate",
              await status_of(A) == S.SELECTED.value)

        # Vikram fails the technical round -- the rejection path through interviews.
        iv_v = await IV.schedule_interview(HOD, COMPANY, {
            "uk": V, "round": "Technical", "scheduled_at": at(4), "duration_min": 60,
            "mode": "Virtual", "meeting_link": "https://meet.northwind.in/vikram-tech",
            "interviewer_id": U_HOD})
        await IV.evaluate_interview(HOD, COMPANY, iv_v["interview_no"], scorecard(
            "Fail", "Rajat Menon", 2, 3, 2, 3, 3, 3,
            "Could not reason about slowly changing dimensions."))
        check("a failed round rejects the candidate", await status_of(V) == S.REJECTED.value)

        # A cancelled slot, then a real one -- Sana's HR round is moved once.
        iv_cancel = await IV.schedule_interview(HR, COMPANY, {
            "uk": SA, "round": "HR Round", "scheduled_at": at(2),
            "mode": "Virtual", "meeting_link": "https://meet.northwind.in/sana-old",
            "interviewer_id": U_HR})
        cancelled = await IV.cancel_interview(HR, COMPANY, iv_cancel["interview_no"])
        stored_cancel = await store[M.COLL_INTERVIEWS].find_one(
            {"interview_no": iv_cancel["interview_no"]})
        check("an interview is cancelled, not deleted -- the booking stays on the record",
              cancelled["cancelled"] is True
              and stored_cancel["status"] == M.InterviewStatus.CANCELLED.value)
        await expect_http("evaluating a cancelled interview", IV.evaluate_interview(
            HR, COMPANY, iv_cancel["interview_no"],
            scorecard("Pass", "Hana Shirke", 4, 4, 4, 4, 4, 4)), 409, "cancelled")

        # Sana is selected too, and will decline her offer.
        iv_s = await IV.schedule_interview(HR, COMPANY, {
            "uk": SA, "round": "HR Round", "scheduled_at": at(4),
            "mode": "Virtual", "meeting_link": "https://meet.northwind.in/sana-hr",
            "interviewer_id": U_HR})
        await IV.evaluate_interview(HR, COMPANY, iv_s["interview_no"], scorecard(
            "Pass", "Hana Shirke", 4, 5, 4, 4, 4, 4))
        iv_s2 = await IV.schedule_interview(HOD, COMPANY, {
            "uk": SA, "round": "Technical", "scheduled_at": at(6),
            "mode": "Virtual", "meeting_link": "https://meet.northwind.in/sana-tech",
            "interviewer_id": U_HOD})
        await IV.evaluate_interview(HOD, COMPANY, iv_s2["interview_no"], scorecard(
            "Pass", "Rajat Menon", 4, 4, 4, 4, 4, 4))
        iv_s3 = await IV.schedule_interview(HR, COMPANY, {
            "uk": SA, "round": "MD Round", "scheduled_at": at(8),
            "mode": "Virtual", "meeting_link": "https://meet.northwind.in/sana-md",
            "interviewer_id": U_MD})
        await IV.evaluate_interview(MD, COMPANY, iv_s3["interview_no"], scorecard(
            "Pass", "Mira Bhatt", 4, 4, 5, 4, 4, 4))
        check("Sana is selected as the second hire", await status_of(SA) == S.SELECTED.value)

        # =================================================================
        section("8. Offers -- one accepted, one declined")
        # =================================================================
        await expect_http("an offer for somebody not Selected", OF.create_offer(
            HR, COMPANY, {"uk": K, "ctc": 1500000, "joining_date": IN_45_DAYS}),
            409, "Selected")
        await expect_http("an offer with a joining date in the past", OF.create_offer(
            HR, COMPANY, {"uk": A, "ctc": 1900000, "joining_date": "2020-01-01"}), 422)
        await expect_http("a negative CTC", OF.create_offer(
            HR, COMPANY, {"uk": A, "ctc": -5, "joining_date": IN_45_DAYS}), 422)

        offer_a = await OF.create_offer(HR, COMPANY, {
            "uk": A, "ctc": 1900000, "joining_date": IN_45_DAYS,
            "designation": "Senior Data Analyst", "company_name": "Northwind Analytics",
            "content": "We are delighted to offer you the role of Senior Data Analyst."})
        check("the offer is drafted", offer_a["status"] == M.OfferStatus.DRAFT.value
              and offer_a["offer_no"].startswith("OFR-"))
        check("a draft does not move the candidate yet",
              await status_of(A) == S.SELECTED.value)
        await expect_http("a second live offer for the same candidate", OF.create_offer(
            HR, COMPANY, {"uk": A, "ctc": 2000000, "joining_date": IN_45_DAYS}),
            409, "already has a live offer")
        await expect_http("sending an offer unsigned", OF.send_offer(
            HR, COMPANY, offer_a["offer_no"], {}), 422, "signatory")

        sent_offer = await OF.send_offer(HR, COMPANY, offer_a["offer_no"],
                                         {"signature": "Mira Bhatt, Managing Director"})
        check("sending moves the offer to Sent",
              sent_offer["status"] == M.OfferStatus.SENT.value)
        check("...and the candidate to Offer Generated",
              await status_of(A) == S.OFFER_GENERATED.value)

        code_offer = (await store[M.COLL_OFFERS].find_one(
            {"offer_no": offer_a["offer_no"]}))["access_code"]
        public_offer = await OF.get_public_offer(code_offer)
        check("the candidate's offer page shows the terms",
              public_offer["ctc"] == 1900000
              and public_offer["designation"] == "Senior Data Analyst")
        await expect_http("accepting without signing", OF.respond_to_offer(
            code_offer, {"action": "accept"}), 422, "full name")
        accepted = await OF.respond_to_offer(code_offer, {
            "action": "accept", "signature": "Ananya Iyer",
            "note": "Delighted. I can start on the agreed date."})
        check("the acceptance is recorded", accepted["status"] == M.OfferStatus.ACCEPTED.value)
        check("the candidate is Offer Accepted", await status_of(A) == S.OFFER_ACCEPTED.value)
        await expect_http("responding twice", OF.respond_to_offer(
            code_offer, {"action": "decline"}), 409, "already responded")

        offer_s = await OF.create_offer(HR, COMPANY, {
            "uk": SA, "ctc": 1850000, "joining_date": IN_45_DAYS,
            "designation": "Senior Data Analyst", "send_now": True,
            "signature": "Mira Bhatt, Managing Director"})
        check("create-and-send issues in one step",
              offer_s["status"] == M.OfferStatus.SENT.value)
        code_offer_s = (await store[M.COLL_OFFERS].find_one(
            {"offer_no": offer_s["offer_no"]}))["access_code"]
        declined = await OF.respond_to_offer(code_offer_s, {
            "action": "decline", "note": "I have accepted a counter-offer. Thank you."})
        check("a decline needs no signature",
              declined["status"] == M.OfferStatus.DECLINED.value)
        check("the candidate reads Offer Declined",
              await status_of(SA) == S.OFFER_DECLINED.value)

        # =================================================================
        section("9. Appointment letter")
        # =================================================================
        await expect_http("a letter for somebody who has not accepted", AP.create_appointment(
            HR, COMPANY, {"uk": SA}), 409, "accepted their offer")

        appt = await AP.create_appointment(HR, COMPANY, {"uk": A})
        check("the letter is drafted from the ACCEPTED offer, not retyped",
              appt["ctc"] == 1900000 and appt["joining_date"] == IN_45_DAYS
              and appt["designation"] == "Senior Data Analyst")
        check("it starts Generated", appt["status"] == M.AppointmentStatus.GENERATED.value)
        await expect_http("a second letter for the same candidate", AP.create_appointment(
            HR, COMPANY, {"uk": A}), 409, "already has an appointment letter")
        await expect_http("sending it unsigned", AP.send_appointment(
            HR, COMPANY, appt["appointment_no"], {}), 422, "signatory")

        sent_appt = await AP.send_appointment(HR, COMPANY, appt["appointment_no"], {
            "signature": "Mira Bhatt, Managing Director"})
        check("the letter goes out", sent_appt["status"] == M.AppointmentStatus.SENT.value)
        check("the candidate reads Appointment Letter Sent",
              await status_of(A) == S.APPOINTMENT_LETTER_SENT.value)
        letter_docs = [d for d in documents.docs
                       if d["owner_type"] == "candidate" and d["owner_id"] == A]
        check("the letter is filed as a document on the candidate",
              len(letter_docs) == 1
              and letter_docs[0]["type_name"] == "Appointment Letter"
              and letter_docs[0]["reference"] == appt["appointment_no"])
        check("its public link is registered",
              any(l["kind"] == M.LinkKind.APPOINTMENT.value for l in links.docs))

        code_appt = (await store[M.COLL_APPOINTMENTS].find_one(
            {"appointment_no": appt["appointment_no"]}))["access_code"]
        await expect_http("acknowledging without signing", AP.acknowledge_appointment(
            code_appt, {}), 422, "full name")
        ack = await AP.acknowledge_appointment(code_appt, {
            "signature": "Ananya Iyer", "note": "Acknowledged with thanks."})
        check("the acknowledgement is recorded",
              ack["status"] == M.AppointmentStatus.ACKNOWLEDGED.value)
        await expect_http("acknowledging twice", AP.acknowledge_appointment(
            code_appt, {"signature": "Ananya Iyer"}), 409, "already acknowledged")
        filed = [d for d in documents.docs
                 if d["owner_type"] == "candidate" and d["owner_id"] == A]
        check("acknowledging updates the filed document rather than filing a second copy",
              len(filed) == 1 and filed[0]["status"] == M.DocumentStatus.VERIFIED.value)

        # =================================================================
        section("10. Onboarding -- KYC, background check, Employee ID")
        # =================================================================
        await expect_http("onboarding somebody who declined", OB.start_onboarding(
            HR, COMPANY, {"uk": SA}), 409, "accepted an offer")

        onb = await OB.start_onboarding(HR, COMPANY, {"uk": A})
        ONB = onb["onb_no"]
        check("onboarding starts with a business id", ONB.startswith("ONB-"))
        check("the candidate moves to Pre-Onboarding",
              await status_of(A) == S.PRE_ONBOARDING.value)
        check("the joining date carries over from the offer",
              onb["joining_date"] == IN_45_DAYS)
        check("a checklist is seeded", len(onb["checklist"]) > 0)
        await expect_http("onboarding the same person twice", OB.start_onboarding(
            HR, COMPANY, {"uk": A}), 409, "already being onboarded")

        code_onb = (await store[M.COLL_ONBOARDING].find_one(
            {"onb_no": ONB}))["access_code"]
        public_onb = await OB.get_public_onboarding(code_onb)
        check("the pre-onboarding form opens for the new joiner",
              public_onb["candidate_name"] == "Ananya Iyer")

        def kyc(**over):
            base = {
                "pan": "abcde1234f", "aadhaar": "4321 8765 2109",
                "date_of_birth": "1996-02-11", "gender": "Female",
                "address": "14 Baner Road, Pune 411045",
                "bank_name": "HDFC Bank", "bank_account": "50100234567890",
                "bank_ifsc": "hdfc0000123",
                "emergency_contact_name": "Lakshmi Iyer",
                "emergency_contact_phone": "9820099887",
                "emergency_contact_relation": "Mother",
                "references": [{"name": "Dr R Subramanian", "relation": "Manager at Flipkart",
                                "phone": "9811122233"}],
                "documents": [resume("pan-card.pdf"), resume("aadhaar.pdf")],
            }
            base.update(over)
            return base

        await expect_http("a submission with neither PAN nor Aadhaar",
                          OB.submit_public_onboarding(code_onb, kyc(pan="", aadhaar="")),
                          422)
        await expect_http("a malformed PAN", OB.submit_public_onboarding(
            code_onb, kyc(pan="ABC123")), 422)
        await expect_http("a malformed IFSC", OB.submit_public_onboarding(
            code_onb, kyc(bank_ifsc="XX-1")), 422)

        filled = await OB.submit_public_onboarding(code_onb, kyc())
        check("the joiner's details are accepted", filled["ok"] is True)
        fresh = await OB.get_onboarding(HR, COMPANY, ONB)
        check("the form lands as Submitted, awaiting HR verification",
              fresh["pre_status"] == M.PreOnboardStatus.SUBMITTED.value)
        check("the PAN is normalised to upper case",
              fresh["submission"]["pan"] == "ABCDE1234F")
        check("both KYC documents are stored", len(fresh["documents"]) == 2)

        blocked = await OB.get_onboarding(HR, COMPANY, ONB)
        check("an Employee ID is blocked, and the screen is told why",
              len(blocked["id_blockers"]) > 0
              and any("verified" in b.lower() for b in blocked["id_blockers"]))
        await expect_http("issuing an Employee ID with KYC unverified",
                          OB.generate_employee_id(HR, COMPANY, ONB), 409, "verified")

        await OB.update_bg(HR, COMPANY, ONB, {
            "bg_verification": M.BgVerification.FLAGGED.value,
            "bg_remarks": "Employment dates at the previous firm need confirming."})
        flagged = await OB.get_onboarding(HR, COMPANY, ONB)
        check("a flagged background check blocks the ID",
              any("flagged" in b.lower() for b in flagged["id_blockers"]))

        verified = await OB.verify_documents(HR, COMPANY, ONB)
        check("HR verifying the documents moves it to Verified",
              verified["pre_status"] == M.PreOnboardStatus.VERIFIED.value)
        await expect_http("issuing an ID while the background check is flagged",
                          OB.generate_employee_id(HR, COMPANY, ONB), 409, "flagged")

        cleared = await OB.update_bg(HR, COMPANY, ONB, {
            "bg_verification": M.BgVerification.CLEARED.value,
            "bg_remarks": "Dates confirmed with the previous employer."})
        check("clearing the background check ticks its checklist item",
              any(i["key"] == "bg_cleared" and i["done"] for i in cleared["checklist"]))
        await expect_http("hand-ticking a system-owned checklist item", OB.set_checklist(
            HR, COMPANY, ONB, {"key": "bg_cleared", "done": False}),
            409, "automatically")

        await expect_http("an invented checklist item", OB.set_checklist(
            HR, COMPANY, ONB, {"key": "free_lunch", "done": True}), 422, "Unknown checklist")
        for key in ("offer_signed", "email_created", "system_access", "asset_issued",
                    "workspace", "induction"):
            await OB.set_checklist(HR, COMPANY, ONB, {"key": key, "done": True})
        progressed = await OB.get_onboarding(HR, COMPANY, ONB)
        check("the checklist progress is computed from the items, not stored",
              progressed["progress"]["done"] == 8
              and progressed["progress"]["total"] == len(M.CHECKLIST_KEYS))
        check("nothing blocks the Employee ID now", progressed["id_blockers"] == [])

        handover = await OB.generate_employee_id(HR, COMPANY, ONB)
        EMP = handover["employee_id"]
        check("an Employee ID is issued", EMP.startswith("EMP-"))
        check("the onboarding moves to Onboarding",
              handover["status"] == M.OnboardStatus.ONBOARDING.value)
        check("issuing the ID means the person has joined",
              await status_of(A) == S.JOINED.value)
        check("the employee_id checklist item is ticked by the system, not by hand",
              any(i["key"] == "employee_id" and i["done"] for i in handover["checklist"]))

        employee = await store[M.COLL_EMPLOYEE_PROFILES].find_one({"employee_code": EMP})
        check("the employee master row carries the joiner's identity",
              employee["identity_snapshot"]["name"] == "Ananya Iyer"
              and employee["identity_snapshot"]["email"] == "ananya.iyer@example.com")
        check("...and the KYC captured on the pre-onboarding form",
              employee["pan"] == "ABCDE1234F"
              and employee["bank_ifsc"] == "HDFC0000123"
              and employee["date_of_birth"] == "1996-02-11")
        check("the new employee has NO login attached -- an account is linked later",
              "user_id" not in employee)
        check("the employee is traceable back to the candidate they were",
              employee["source_uk"] == A)
        check("they join on the date the offer agreed",
              employee["joined_on"] == IN_45_DAYS)
        await expect_http("issuing a second Employee ID for the same onboarding",
                          OB.generate_employee_id(HR, COMPANY, ONB), 409, "already")

        # The joining-day items finish off the checklist, which is what completes the
        # onboarding and turns the candidate into an Employee Created record.
        for key in ("policy_ack", "bank_payroll", "buddy_assigned"):
            await OB.set_checklist(HR, COMPANY, ONB, {"key": key, "done": True})
        finished = await OB.get_onboarding(HR, COMPANY, ONB)
        check("a fully-ticked checklist completes the onboarding by itself",
              finished["status"] == M.OnboardStatus.COMPLETED.value
              and finished["progress"]["done"] == finished["progress"]["total"])
        check("the candidate ends as an Employee Created record",
              await status_of(A) == S.EMPLOYEE_CREATED.value)
        await expect_http("editing a completed onboarding", OB.set_checklist(
            HR, COMPANY, ONB, {"key": "induction", "done": False}), 409)

        # =================================================================
        section("11. The pipeline as a whole")
        # =================================================================
        rows = {c["uk"]: c["application_status"] for c in candidates.docs}
        check("Ananya finished as an employee", rows[A] == S.EMPLOYEE_CREATED.value)
        check("Sana declined her offer", rows[SA] == S.OFFER_DECLINED.value)
        check("Meera stopped at the assessment", rows[ME] == S.ASSESSMENT_FAILED.value)
        check("Vikram was rejected at interview", rows[V] == S.REJECTED.value)
        check("Rohan was rejected at screening", rows[R] == S.REJECTED.value)
        check("Kabir is still On Hold", rows[K] == S.ON_HOLD.value)

        listed = await PS.list_postings(HR, COMPANY)
        posting_row = next(p for p in listed["postings"] if p["posting_code"] == POST)
        check("the posting counts the five real applications",
              posting_row["application_count"] == 5)
        check("...computed from candidates, never stored on the posting",
              "application_count" not in await store[M.COLL_JOB_POSTINGS].find_one(
                  {"posting_code": POST}))

        by_source = await AN.breakdown(HR, COMPANY, "source")
        tally = {r["name"]: r["count"] for r in by_source["rows"]}
        check("the source breakdown reads back what applicants said",
              tally == {"Job Portal": 2, "Social Media": 1, "Referral": 1,
                        "Consultant / Agency": 1, "Walk-in": 1})
        check("shares sum to 100", abs(sum(r["share"] for r in by_source["rows"]) - 100) < 1.5)
        by_referral = await AN.breakdown(HR, COMPANY, "referral_source")
        check("the referral dimension still records the channel behind a referral",
              {r["name"] for r in by_referral["rows"]} >= {"Employee", "Job Portal"})

        funnel = await AN.funnel(HR, COMPANY)
        stages = {s["key"]: s["count"] for s in funnel["stages"]}
        check("the funnel counts every applicant at the top",
              funnel["total"] == 6 and stages["applied"] == 6)
        check("the funnel never increases from stage to stage",
              [s["count"] for s in funnel["stages"]]
              == sorted((s["count"] for s in funnel["stages"]), reverse=True))
        check("four candidates reached the assessment", stages["assessment"] == 4)
        check("two were selected and offered",
              stages["selected"] == 2 and stages["offered"] == 2)
        check("one accepted and one was hired",
              stages["accepted"] == 1 and stages["hired"] == 1)
        check("the losses are accounted for, not just dropped",
              funnel["lost"] == {"rejected": 2, "on_hold": 1, "declined": 1, "duplicate": 0})
        check("no candidate is unrankable", funnel["unranked"] == 0)

        journey = await CS.get_journey(HR, COMPANY, A)
        titles = [e["title"] for e in journey["events"]]
        check("every milestone that has its own event is on the journey",
              {M.AUDIT_APPLICATION, M.AUDIT_SCREENED, M.AUDIT_ASSESSMENT_SENT,
               M.AUDIT_ASSESSMENT_SUBMITTED, M.AUDIT_ASSESSMENT_RESOLVED,
               M.AUDIT_INTERVIEW_SCHEDULED, M.AUDIT_OFFER_CREATED, M.AUDIT_OFFER_SENT,
               M.AUDIT_OFFER_ACCEPTED, M.AUDIT_APPOINTMENT_SENT,
               M.AUDIT_APPOINTMENT_ACK} <= set(titles))
        check("all three interviews are on the journey",
              titles.count(M.AUDIT_INTERVIEW_SCHEDULED) == 3)
        # Onboarding audits against the ONBOARDING entity, so its milestones reach the
        # candidate's journey as stage changes rather than as duplicate rows. The chain is
        # what matters: every hop from Applied to Employee Created is present, in order,
        # with no gap -- which is what makes the journey a reconstruction rather than a
        # summary.
        hops = [e["detail"] for e in journey["events"]
                if e["title"] == M.AUDIT_STAGE_CHANGED and "->" in (e["detail"] or "")]
        arrivals = [h.split("->")[-1].strip() for h in hops]
        departures = [h.split("->")[0].strip() for h in hops]
        check("the stage chain is unbroken from Applied to Employee Created",
              departures[0] == S.APPLIED.value
              and arrivals[-1] == S.EMPLOYEE_CREATED.value
              and departures[1:] == arrivals[:-1])
        check("it passes through every gate this role imposes",
              {S.ASSESSMENT_PASSED.value, S.MD_ROUND.value, S.SELECTED.value,
               S.OFFER_ACCEPTED.value, S.APPOINTMENT_LETTER_SENT.value,
               S.PRE_ONBOARDING.value, S.JOINED.value} <= set(arrivals))
        check("the rail reports a finished journey",
              journey["candidate"]["status"] == S.EMPLOYEE_CREATED.value
              and journey["terminal"] is True)

        check("every stage wrote an audit trail",
              {M.AUDIT_REQ_MD_APPROVED, M.AUDIT_POSTING_CREATED, M.AUDIT_APPLICATION,
               M.AUDIT_OFFER_SENT, M.AUDIT_OFFER_ACCEPTED}
              <= {a["action"] for a in audit_log.docs})
        check("the audit trail is scoped to this company",
              all(a["company_id"] == COMPANY for a in audit_log.docs))
        check("every candidate-facing link is in the register",
              {M.LinkKind.APPLY.value, M.LinkKind.ASSESSMENT.value,
               M.LinkKind.OFFER.value, M.LinkKind.APPOINTMENT.value,
               M.LinkKind.ONBOARDING.value} <= {l["kind"] for l in links.docs})

        section("12. Closing the requisition")
        closed = await RS.close_requisition(
            HR, COMPANY, REQ, M.ReqClosing.CLOSED.value)
        check("the requisition can be closed once hiring is done",
              closed["closing_status"] == M.ReqClosing.CLOSED.value)

        # =================================================================
        section("13. The CLIENT TRACK IS UNCHANGED by the internal-track phases")
        # =================================================================
        # Everything above this line is a client-track journey, and it just ran end to end
        # with no shortlisting committee, no interview panel, no reference check, no budget
        # gate, no statutory check and no salary band. That is the assertion -- but a
        # passing walkthrough is easy to misread as "nothing was broken this time", so the
        # guarantee is also asserted STRUCTURALLY, from the tables the gates read.
        #
        # Phase INT-2 added five new controls. Every one of them is keyed on
        # `requisition_track == internal`; if a future change dropped that condition, the
        # journey above would start failing and these checks say WHY in one line.
        req = await store[M.COLL_REQUISITIONS].find_one({"request_no": REQ})
        check("the requisition this journey ran on carries no internal track",
              req.get("requisition_track") in (None, M.RequisitionTrack.CLIENT.value))
        check("and `track_of` reads that absence as the client track",
              RS.track_of(req) is M.RequisitionTrack.CLIENT)

        # The five INT-2 gates, each asked directly about this requisition.
        candidate_row = await candidates.find_one({"request_no": REQ})
        from app.services.hrms_shortlist_service import assert_shortlist_cleared
        from app.services.hrms_interview_service import assert_final_round_complete
        await assert_shortlist_cleared(COMPANY, candidate_row, req)
        check("the shortlisting committee gate is silent on a client requisition", True)
        await assert_final_round_complete(COMPANY, candidate_row, req)
        check("the mandatory Management final round is silent too", True)

        from app.services.hrms_offer_service import assert_within_band
        await assert_within_band(COMPANY, 999_999_999, candidate_row, req)
        check("the salary-band gate does not apply, at any figure", True)

        # Phase INT-4's gate, asked the same way.
        from app.services.hrms_telephonic_service import assert_telephonic_cleared
        await assert_telephonic_cleared(COMPANY, candidate_row, req)
        check("the telephonic gate is silent on a client requisition -- this journey "
              "interviewed without a phone screen and was never asked for one", True)

        from app.services.hrms_requisition_service import assert_sourcing_allowed
        assert_sourcing_allowed(req)
        check("the budget gate does not block sourcing", True)

        # The client chain's own transition table is untouched, which is what makes
        # "the agency track is unchanged" a fact rather than a hope.
        check("MD approval is still the only road to Approved on the client chain",
              M.md_approval_is_mandatory())
        check("the client transition table still has exactly its five actions",
              set(M.REQ_TRANSITIONS) == {"hr-approve", "hr-reject", "md-approve",
                                          "md-reject", "escalate-approve",
                                          "escalate-reject"})
        check("and the two tracks still read from SEPARATE tables",
              M.TRACK_TRANSITIONS[M.RequisitionTrack.CLIENT][0] is M.REQ_TRANSITIONS
              and M.TRACK_TRANSITIONS[M.RequisitionTrack.INTERNAL][0]
              is M.INTERNAL_REQ_TRANSITIONS)

        # The candidate lifecycle itself is shared between the tracks, so a new status or a
        # new edge would change the client track's meaning. Neither happened.
        check("the client-track onboarding still shows exactly its twelve checklist items",
              len(M.seed_checklist()) == 12
              and len(M.seed_checklist(M.RequisitionTrack.CLIENT.value)) == 12)
        # Phase INT-4 DID add two statuses (Telephonic Passed / Rejected), so the old
        # "nothing was added" count is now a lie. What the count was really standing in for
        # is that the CLIENT TRACK's own path is unchanged -- so that is asserted directly,
        # which is both true and harder to satisfy by accident.
        check("the lifecycle has the 26 statuses these phases account for",
              len(list(M.AppStatus)) == 26)
        check("every status is ranked and column-mapped, so nothing new can be counted in a "
              "total while belonging to no funnel stage or board column",
              all(st in M.STAGE_RANK for st in M.AppStatus)
              and sum(len(ss) for _k, _l, ss in M.PIPELINE_COLUMNS) == len(list(M.AppStatus)))
        check("the client track's own Shortlisted -> Interview edge is untouched -- the new "
              "stage was ADDED beside it, never substituted for it",
              M.can_transition(M.AppStatus.SHORTLISTED, M.AppStatus.INTERVIEW_SCHEDULED))
        check("and this journey's candidate reached Employee Created without ever holding a "
              "telephonic status",
              candidate_row.get("application_status")
              not in {M.AppStatus.TELEPHONIC_PASSED.value,
                      M.AppStatus.TELEPHONIC_REJECTED.value})
        check("and every one still ranks, so the funnel credits all of them",
              all(M.stage_rank(s) > 0 for s in M.AppStatus))

    finally:
        mongo.get_collection = original
        S3.upload_file_to_s3_with_key = original_s3
        NS.notify_user, NS.notify_hrms_role = original_notify
        for mod in SERVICES:
            mod.get_collection = original

    total = len(results)
    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{total} checks passed ===")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
