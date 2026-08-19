"""Phase 11-R Item 4 verification harness -- the client dimension + client-wise analytics.

Covers: clients read from the ERP's Companies section (there is no HRMS client master),
client sharing as a screening action, the client verdict and the stage moves it drives, the
analytics client filter (which NARROWS and never widens), the CV metrics, the CV funnel, the
per-client comparison and the position-wise matrix.

Two properties matter most here.

  1. `client_id` is a REPORTING dimension, not a tenant boundary. `company_id` remains the
     only security scope, and a client filter composed with a manager's row scope must
     intersect rather than replace it.
  2. There is exactly ONE record per organisation. A client is a company, so HRMS reads
     Companies and never writes it -- asserted below by the absence of the write functions,
     not merely by not calling them.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase11_clients   (from backend/)
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

COMPANY = "C1"
OTHER = "C2"
NOW = datetime.now(timezone.utc)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    S = M.AppStatus
    U_HR, U_HOD = str(ObjectId()), str(ObjectId())

    def cand(uk, status, request_no, **extra):
        d = {"_id": ObjectId(), "uk": uk, "company_id": COMPANY,
             "candidate_name": f"Cand {uk}", "application_status": status,
             "request_no": request_no, "applied_at": NOW - timedelta(days=3)}
        d.update(extra)
        return d

    candidates = FakeCollection([
        cand("CAN-001", S.SHORTLISTED.value, "HR-REQ-2026-001"),
        cand("CAN-002", S.SHORTLISTED.value, "HR-REQ-2026-001"),
        cand("CAN-003", S.SELECTED.value, "HR-REQ-2026-002"),
        cand("CAN-004", S.JOINED.value, "HR-REQ-2026-002"),
        cand("CAN-005", S.REJECTED.value, "HR-REQ-2026-001"),
        cand("CAN-006", S.APPLIED.value, "HR-REQ-2026-003"),
    ])
    # Clients are companies. These are ERP company documents, not an HRMS-owned list --
    # the field names are the Companies module's own (`is_active`, `company_type`, ...).
    ACME, GLOBEX = ObjectId(), ObjectId()
    ACME_ID, GLOBEX_ID = str(ACME), str(GLOBEX)
    companies = FakeCollection([
        {"_id": ACME, "name": "Acme Manufacturing", "company_type": "Manufacturing",
         "email": "r.iyer@acme.com", "contact": "+91 98765 43210", "city": "Pune",
         "state": "MH", "is_active": True, "status": "active"},
        {"_id": GLOBEX, "name": "Globex", "is_active": False, "status": "inactive"},
    ])
    reqs = FakeCollection()
    counters = FakeCollection()
    audit_log = FakeCollection()

    store = {M.COLL_CANDIDATES: candidates, "companies": companies,
             M.COLL_REQUISITIONS: reqs, M.COLL_COUNTERS: counters,
             M.COLL_AUDIT_LOG: audit_log, M.COLL_ASSESSMENTS: FakeCollection(),
             M.COLL_INTERVIEWS: FakeCollection(), M.COLL_OFFERS: FakeCollection(),
             M.COLL_ONBOARDING: FakeCollection(), M.COLL_JOB_POSTINGS: FakeCollection(),
             "learners": FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_service as CS
    import app.services.hrms_candidate_service as CANS
    import app.services.hrms_analytics_service as AN
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (CS, CANS, AN, AUD, IDS):
        mod.get_collection = mongo.get_collection

    sent = []

    async def fake_notify_user(uid, title, msg, **kw):
        sent.append(("user", str(uid), title))
    CANS.notify_user = fake_notify_user

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}
    HOD = {"_id": U_HOD, "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD", "full_name": "Hari HOD"}

    try:
        # =================================================================
        section("Clients ARE the ERP's companies")
        # =================================================================
        for gone in ("create_client", "update_client", "delete_client"):
            check(f"there is no {gone} -- HRMS never writes a company",
                  not hasattr(CS, gone))
        check("there is no hrms_clients collection constant",
              not hasattr(M, "COLL_CLIENTS"))

        listing = await CS.list_clients(HR, COMPANY)
        names = {c["name"] for c in listing["clients"]}
        check("active companies are offered as clients", names == {"Acme Manufacturing"})
        check("an inactive company is withheld by default", "Globex" not in names)

        with_inactive = await CS.list_clients(HR, COMPANY, include_inactive=True)
        check("include_inactive returns it",
              {"Acme Manufacturing", "Globex"}
              == {c["name"] for c in with_inactive["clients"]})

        acme = next(c for c in listing["clients"] if c["name"] == "Acme Manufacturing")
        check("client_id IS the company id", acme["client_id"] == ACME_ID)
        check("no second id is minted for a company",
              not acme["client_id"].startswith("CLI-"))
        check("the company's contact details ride along, unduplicated",
              acme["contact_email"] == "r.iyer@acme.com"
              and acme["contact_phone"] == "+91 98765 43210")
        check("its industry is the company type, not a new field",
              acme["industry"] == "Manufacturing")
        check("only display fields are exposed, never the whole company document",
              set(acme) == {"client_id", "name", "industry", "domain", "contact_email",
                            "contact_phone", "location", "active", "status"})

        found = await CS.list_clients(HR, COMPANY, search="acme")
        check("clients can be searched by name", found["total"] == 1)

        check("an unknown client does not resolve",
              await CS.get_client(str(ObjectId())) is None)
        check("a malformed id answers 'no such client' rather than raising",
              await CS.get_client("not-an-object-id") is None)
        await expect_http("requiring a non-existent client",
                          CS.require_client(str(ObjectId())), 422, "does not exist")
        await expect_http("requiring an INACTIVE company",
                          CS.require_client(GLOBEX_ID), 422, "inactive")
        check("requiring an active company resolves it",
              (await CS.require_client(ACME_ID))["name"] == "Acme Manufacturing")

        # =================================================================
        section("Requisitions name a client")
        # =================================================================
        await reqs.insert_one({
            "request_no": "HR-REQ-2026-001", "company_id": COMPANY, "created_by": U_HOD,
            "client_id": ACME_ID, "client_name": "Acme Manufacturing",
            "designation_name": "Analyst", "department_name": "Ops", "vacancy": 2,
            "closing_status": M.ReqClosing.OPEN.value,
            "approval_status": M.ReqApproval.APPROVED.value, "created_at": NOW})
        await reqs.insert_one({
            "request_no": "HR-REQ-2026-002", "company_id": COMPANY, "created_by": U_HR,
            "client_id": ACME_ID, "client_name": "Acme Manufacturing",
            "designation_name": "Engineer", "vacancy": 1,
            "closing_status": M.ReqClosing.OPEN.value,
            "approval_status": M.ReqApproval.APPROVED.value, "created_at": NOW})
        await reqs.insert_one({
            "request_no": "HR-REQ-2026-003", "company_id": COMPANY, "created_by": U_HR,
            "designation_name": "In-house role", "vacancy": 1,
            "closing_status": M.ReqClosing.OPEN.value,
            "approval_status": M.ReqApproval.APPROVED.value, "created_at": NOW})

        stats = await CS.list_clients(HR, COMPANY, with_stats=True)
        acme_row = next(c for c in stats["clients"] if c["client_id"] == ACME_ID)
        check("a client carries this tenant's requisition count",
              acme_row["requisition_count"] == 2)
        check("and how many of them are still open", acme_row["open_requisitions"] == 2)

        # A rename in Companies must show through WITHOUT a sync step -- that is the whole
        # argument for not keeping a second copy of the name.
        await companies.update_one({"_id": ACME}, {"$set": {"name": "Acme Mfg Ltd"}})
        renamed = await AN.positions(HR, COMPANY)
        check("a rename in Companies shows through on the next read, with no sync step",
              all(r["client_name"] == "Acme Mfg Ltd" for r in renamed["rows"]
                  if r.get("request_no") in ("HR-REQ-2026-001", "HR-REQ-2026-002")))
        check("the stale denormalised name on the requisition is NOT what was shown",
              all(r.get("client_name") == "Acme Manufacturing" for r in reqs.docs
                  if r.get("client_id") == ACME_ID))

        summary = await CS.client_summary(COMPANY, ACME_ID)
        check("the client summary counts its requisitions", summary["requisitions"] == 2)
        check("it counts their vacancies", summary["vacancies"] == 3)
        # CAN-001/002/005 on REQ-001 and CAN-003/004 on REQ-002 -- five in total.
        check("it counts their candidates", summary["candidates"] == 5)

        # =================================================================
        section("Sharing a CV with the client")
        # =================================================================
        check("share_with_client is a distinct screening action",
              M.ScreenAction.SHARE_WITH_CLIENT in M.SCREEN_ACTIONS)
        check("it is NOT the same as forward (which assigns an internal owner)",
              M.SCREEN_ACTIONS[M.ScreenAction.FORWARD][0] is None
              and M.SCREEN_ACTIONS[M.ScreenAction.SHARE_WITH_CLIENT][0]
              is S.SHARED_WITH_CLIENT)

        shared = await CANS.screen_candidates(HR, COMPANY, {
            "uks": ["CAN-001", "CAN-002"], "action": "share_with_client",
            "client_contact": "R Iyer", "remarks": "two strong CVs"})
        check("both candidates moved", shared["moved_count"] == 2)
        row = await candidates.find_one({"uk": "CAN-001"})
        check("the stage is Shared with Client",
              row["application_status"] == S.SHARED_WITH_CLIENT.value)
        check("a client-share record is opened",
              row["client_share"]["status"] == M.ClientShareStatus.PENDING.value)
        check("who it went to is recorded",
              row["client_share"]["client_contact"] == "R Iyer")
        check("the flat field is denormalised for reports",
              row["client_share_status"] == M.ClientShareStatus.PENDING.value)
        check("sharing has its own audit action",
              any(a["action"] == M.AUDIT_CLIENT_SHARED for a in audit_log.docs))

        # =================================================================
        section("The client's verdict")
        # =================================================================
        await expect_http("a verdict on a CV that was never shared",
                          CANS.record_client_response(HR, COMPANY,
                                                      {"uk": "CAN-003",
                                                       "status": "Shortlisted"}),
                          409, "not been shared")
        await expect_http("rejecting with no reason",
                          CANS.record_client_response(HR, COMPANY,
                                                      {"uk": "CAN-001",
                                                       "status": "Rejected"}),
                          422, "reason")
        await expect_http("an unknown verdict",
                          CANS.record_client_response(HR, COMPANY,
                                                      {"uk": "CAN-001", "status": "Maybe"}),
                          422)

        ok = await CANS.record_client_response(
            HR, COMPANY, {"uk": "CAN-001", "status": "Shortlisted",
                          "remarks": "keen to interview"})
        check("a shortlist verdict moves the candidate",
              ok["application_status"] == S.CLIENT_SHORTLISTED.value)
        check("the verdict is stored on the share record",
              ok["client_share"]["status"] == M.ClientShareStatus.SHORTLISTED.value)
        check("the verdict is audited",
              any(a["action"] == M.AUDIT_CLIENT_RESPONSE for a in audit_log.docs))
        check("whoever shared it is notified",
              any(kind == "user" for kind, _who, _t in sent))

        no = await CANS.record_client_response(
            HR, COMPANY, {"uk": "CAN-002", "status": "Rejected", "remarks": "not enough SQL"})
        check("a rejection verdict moves the candidate",
              no["application_status"] == S.CLIENT_REJECTED.value)

        # =================================================================
        section("Lifecycle wiring")
        # =================================================================
        check("Shortlisted -> Shared with Client is legal",
              M.can_transition(S.SHORTLISTED, S.SHARED_WITH_CLIENT))
        check("the pipeline can proceed WITHOUT a verdict (a silent client cannot strand "
              "a candidate)",
              M.can_transition(S.SHARED_WITH_CLIENT, S.INTERVIEW_SCHEDULED))
        check("a client rejection is revivable, like an internal one",
              M.can_transition(S.CLIENT_REJECTED, S.UNDER_REVIEW))
        check("the client band ranks WITH shortlisting, not above it",
              M.STAGE_RANK[S.SHARED_WITH_CLIENT]
              == M.STAGE_RANK[S.CLIENT_SHORTLISTED]
              == M.STAGE_RANK[S.SHORTLISTED] == 2)
        check("a client rejection ranks where it entered",
              M.STAGE_RANK[S.CLIENT_REJECTED] == 2)
        for status in (S.SHARED_WITH_CLIENT, S.CLIENT_SHORTLISTED, S.CLIENT_REJECTED):
            check(f"{status.value} appears in exactly one pipeline column",
                  sum(1 for _k, _l, ss in M.PIPELINE_COLUMNS if status in ss) == 1)
        check("the funnel stays monotonic",
              all(a[2] < b[2] for a, b in zip(M.FUNNEL_STAGES, M.FUNNEL_STAGES[1:])))

        # =================================================================
        section("Analytics: the client filter NARROWS, never widens")
        # =================================================================
        unfiltered = await AN._scope(HR, COMPANY)
        check("with no client, HR's scope is the whole company",
              unfiltered == {"company_id": COMPANY})

        scoped = await AN._scope(HR, COMPANY, acme["client_id"])
        check("a client filter restricts to that client's requisitions",
              set(scoped["request_no"]["$in"]) == {"HR-REQ-2026-001", "HR-REQ-2026-002"})
        check("company_id is STILL the tenant boundary", scoped["company_id"] == COMPANY)

        mgr_scope = await AN._scope(HOD, COMPANY)
        check("a manager alone is narrowed to their own requisitions",
              mgr_scope["request_no"]["$in"] == ["HR-REQ-2026-001"])

        mgr_client = await AN._scope(HOD, COMPANY, acme["client_id"])
        check("manager + client filter INTERSECT (the filter cannot widen their view)",
              mgr_client["request_no"]["$in"] == ["HR-REQ-2026-001"])

        empty = await AN._scope(HR, COMPANY, str(ObjectId()))
        check("an unknown client matches NOTHING (fails closed)",
              empty["request_no"]["$in"] == [])

        # =================================================================
        section("CV metrics")
        # =================================================================
        dash = await AN.dashboard(HR, COMPANY)
        cv = dash["cv_metrics"]
        keys = {k["key"] for k in dash["kpis"]}
        for wanted in ("cvs_reviewed", "cvs_shortlisted", "cvs_selected", "cvs_rejected",
                       "shared_with_client", "client_shortlisted", "client_rejected",
                       "joinings"):
            check(f"the '{wanted}' tile exists", wanted in keys)
        check("every KPI still deep-links", all(k.get("link") for k in dash["kpis"]))

        check("shared counts the CVs actually sent out", cv["shared_with_client"] == 2)
        check("the client's shortlist is counted", cv["client_shortlisted"] == 1)
        check("the client's rejections are counted", cv["client_rejected"] == 1)
        check("joinings count Joined and Employee Created", cv["joinings"] == 1)
        check("rejected counts client rejections too",
              cv["rejected"] >= 2)      # CAN-005 internal + CAN-002 client
        check("reviewed uses EFFECTIVE rank, so a Selected candidate still counts",
              cv["reviewed"] >= 5)
        check("the shortlist rate is measured against ANSWERED CVs only",
              dash["client_metrics"]["shortlist_rate"] == 50.0)

        # CAN-006 is at Applied and nothing else has happened to it. "Reviewed" must not
        # count it -- STAGE_RANK puts Applied and Under Review in the same band, so the
        # obvious `rank >= rank(Under Review)` test made this figure equal the total.
        check("a CV still at Applied is NOT counted as reviewed",
              cv["reviewed"] == cv["total"] - 1)
        check("what is left in the inbox is stated outright",
              cv["awaiting_review"] == 1
              and cv["reviewed"] + cv["awaiting_review"] == cv["total"])
        check("shortlisted is the INTERNAL selection, ahead of client sharing",
              cv["shortlisted"] >= cv["shared_with_client"])
        check("selected is the FINAL selection, so it cannot exceed shortlisted",
              cv["selected"] <= cv["shortlisted"])

        # ── The CV funnel ──
        funnel_keys = [s["key"] for s in dash["cv_funnel"]]
        check("the funnel runs review -> selection -> sharing -> verdict -> joining",
              funnel_keys == ["total", "reviewed", "shortlisted", "shared_with_client",
                              "client_shortlisted", "selected", "joinings"])
        check("every funnel stage reports the same number as its KPI",
              all(s["value"] == cv[s["key"]] for s in dash["cv_funnel"]))
        check("the first stage is 100% of itself",
              dash["cv_funnel"][0]["of_total"] == 100.0)
        check("of_previous is null where a stage out-counts the one above it, never >100%",
              all(s["of_previous"] is None or s["of_previous"] <= 100.0
                  for s in dash["cv_funnel"]))

        # =================================================================
        section("Per-client comparison and the position matrix")
        # =================================================================
        check("the comparison appears only in the all-clients view",
              dash["client_comparison"] is not None)
        one_client = await AN.dashboard(HR, COMPANY, client_id=acme["client_id"])
        check("selecting a client suppresses the comparison",
              one_client["client_comparison"] is None)
        check("the selected client is echoed back",
              one_client["client_id"] == acme["client_id"])

        rows = {r["client_name"]: r for r in dash["client_comparison"]}
        check("the client has a row", "Acme Mfg Ltd" in rows)
        check("requisitions with NO client are grouped, not dropped",
              "In-house / no client" in rows)
        check("the client's candidate total is right", rows["Acme Mfg Ltd"]["total"] == 5)

        pos = await AN.positions(HR, COMPANY)
        check("one row per requisition", pos["total"] == 3)
        check("columns come from AppStatus itself, so a new stage cannot go missing",
              pos["statuses"] == [s.value for s in M.AppStatus])
        analyst = next(r for r in pos["rows"] if r["request_no"] == "HR-REQ-2026-001")
        check("counts are per requisition", analyst["totals"]["candidates"] == 3)
        check("the client travels with the row", analyst["client_name"] == "Acme Mfg Ltd")
        check("the vacancy is shown", analyst["vacancy"] == 2)

        pos_client = await AN.positions(HR, COMPANY, client_id=acme["client_id"])
        check("the matrix honours the client filter", pos_client["total"] == 2)

        # =================================================================
        section("Breakdowns and reports")
        # =================================================================
        check("client_status is an allow-listed breakdown",
              "client_status" in M.BREAKDOWN_FIELDS)
        check("client is an allow-listed breakdown", "client" in M.BREAKDOWN_FIELDS)
        check("the BreakdownBy enum matches its allow-list exactly",
              {b.value for b in M.BreakdownBy} == set(M.BREAKDOWN_FIELDS))
        await expect_http("an unknown breakdown dimension",
                          AN.breakdown(HR, COMPANY, "salary"), 422, "unknown breakdown")

        verdicts = await AN.breakdown(HR, COMPANY, "client_status")
        check("client verdicts can be grouped", verdicts["total"] >= 1)

        cols = [c for c, _l in M.REPORT_ENTITIES["requisitions"]["columns"]]
        check("the requisition report carries the client", "client_name" in cols)
        cand_cols = [c for c, _l in M.REPORT_ENTITIES["candidates"]["columns"]]
        check("the candidate report carries the client verdict",
              "client_share_status" in cand_cols)

        # =================================================================
        section("Analytics is still READ-ONLY")
        # =================================================================
        import inspect
        source = inspect.getsource(AN)
        for forbidden in ("insert_one(", "insert_many(", "update_one(", "update_many(",
                          "delete_one(", "delete_many("):
            check(f"hrms_analytics_service contains no {forbidden.rstrip('(')}",
                  forbidden not in source)

        # =================================================================
        section("Capabilities")
        # =================================================================
        from app.utils.hrms_access import can
        check("HR reads clients", can(HR, M.Cap.CLIENT_READ))
        check("a manager reads clients", can(HOD, M.Cap.CLIENT_READ))
        # `client.write` was reintroduced by the multi-client foundation, but with a
        # DIFFERENT meaning: it manages ENGAGEMENTS (this tenant recruits for that company,
        # and these of our users work on it), never the company record.
        #
        # The invariant this line has always been about is unchanged and is asserted where
        # it actually lives -- in the absence of create/update/delete_client above. A
        # capability name proves nothing on its own; the missing write functions do.
        check("client.write manages engagements, and still never edits a company",
              hasattr(M.Cap, "CLIENT_WRITE")
              and not any(hasattr(CS, fn) for fn in
                          ("create_client", "update_client", "delete_client")))
        check("and only Management or internal support hold it -- not HR",
              M.Cap.CLIENT_WRITE in M.ROLE_CAPABILITIES[M.HrmsRole.MD]
              and M.Cap.CLIENT_WRITE not in M.ROLE_CAPABILITIES[M.HrmsRole.HR])
        check("recording a client verdict IS screening, not a new capability",
              can(HR, M.Cap.CANDIDATE_SCREEN))

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
