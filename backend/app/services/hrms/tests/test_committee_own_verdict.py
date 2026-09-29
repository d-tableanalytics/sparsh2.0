"""Shortlisting committee: each member approves for themselves, and only they see it.

  * convening (through the API) leaves every other member Pending and asks each of them;
  * a member records only their OWN verdict -- nobody sets another member's;
  * nothing is decided while a member has still to answer;
  * the last answer decides the sitting by itself (the same derived outcome as before);
  * only the sitting's members and its convener see it; only the convener changes who sits.

Run:  python -m app.services.hrms.tests.test_committee_own_verdict   (from backend/)
"""
import asyncio
from datetime import datetime, timezone

RESULTS = []


def check(label: str, ok: bool) -> None:
    RESULTS.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")


def section(title: str) -> None:
    print(f"\n-- {title} --")


async def expect_http(label: str, coro, status: int, fragment: str = None) -> None:
    from fastapi import HTTPException
    try:
        await coro
        check(f"{label} -> {status}", False)
    except HTTPException as e:
        ok = e.status_code == status and (not fragment or fragment.lower() in str(e.detail).lower())
        check(f"{label} -> {status}" + (f" ('{fragment}')" if fragment else "")
              + ("" if ok else f"  [got {e.status_code}: {e.detail}]"), ok)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
NOW = datetime.now(timezone.utc)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_HOD, U_OUT = (str(ObjectId()) for _ in range(3))
    D_JUNIOR = ObjectId()
    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "full_name": "Hana HR", "company_id": COMPANY,
         "role": "clientuser", "governance_role": "HR"},
        {"_id": ObjectId(U_HOD), "full_name": "Hari HOD", "company_id": COMPANY,
         "role": "clientuser", "governance_role": "HOD"},
        {"_id": ObjectId(U_OUT), "full_name": "Otto Other", "company_id": COMPANY,
         "role": "clientuser", "governance_role": "HOD"},
    ])
    store = {
        M.COLL_REQUISITIONS: FakeCollection([
            {"request_no": "R-JUN", "company_id": COMPANY, "requisition_track": "internal",
             "designation_id": str(D_JUNIOR), "designation_name": "Ops Executive",
             "approval_status": "Approved", "closing_status": "Open", "created_at": NOW}]),
        M.COLL_DESIGNATIONS: FakeCollection([
            {"_id": D_JUNIOR, "company_id": COMPANY, "designation_name": "Ops Executive",
             "designation_level": "junior"}]),
        M.COLL_CANDIDATES: FakeCollection([
            {"_id": ObjectId(), "uk": "CAN-1", "company_id": COMPANY, "candidate_name": "One",
             "request_no": "R-JUN", "application_status": M.AppStatus.INTERVIEW_SCHEDULED.value},
            {"_id": ObjectId(), "uk": "CAN-2", "company_id": COMPANY, "candidate_name": "Two",
             "request_no": "R-JUN", "application_status": M.AppStatus.INTERVIEW_SCHEDULED.value}]),
        M.COLL_SHORTLIST_REVIEWS: FakeCollection(), M.COLL_EXCEPTIONS: FakeCollection(),
        M.COLL_INTERVIEWS: FakeCollection(), M.COLL_COUNTERS: FakeCollection(),
        M.COLL_AUDIT_LOG: FakeCollection(), "learners": learners, "staff": FakeCollection(),
    }
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_shortlist_service as SL
    import app.services.hrms_candidate_service as CS
    import app.services.hrms_exception_service as EX
    import app.services.hrms_interview_service as IV
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.services.hrms_notify_service as NS
    import app.utils.hrms_access as HACC
    for mod in (SL, CS, EX, IV, AUD, IDS, HACC):
        mod.get_collection = mongo.get_collection

    asked = []

    async def capture(user_id, title, message, **kw):
        asked.append((user_id, title))
    NS.notify_user = capture

    async def silent(*a, **kw):
        return None
    CS.notify_user = silent

    def actor(uid, gov):
        return {"_id": uid, "role": "clientuser", "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": gov, "full_name": gov}
    HR, HOD, OUT = actor(U_HR, "HR"), actor(U_HOD, "HOD"), actor(U_OUT, "HOD")

    def status_of(uk):
        return next(c for c in store[M.COLL_CANDIDATES].docs if c["uk"] == uk)["application_status"]

    try:
        section("Convening asks each member; nobody is pre-approved")
        # HR tries to convene with the HOD already marked as agreeing.
        rec = await SL.create_shortlist_review(HR, COMPANY, {
            "request_no": "R-JUN", "candidate_uks": ["CAN-1"],
            "committee_members": [{"user_id": U_HR, "decision": "Pending"},
                                  {"user_id": U_HOD, "decision": "Agree"}]},
            own_verdicts_only=True)
        hod = next(m for m in rec["committee_members"] if m["user_id"] == U_HOD)
        check("the HOD's verdict cannot be set by HR -- it stays Pending", hod["decision"] == "Pending")
        check("the sitting is Pending", rec["outcome"] == "Pending")
        check("the HOD is asked for their approval",
              any(u == U_HOD and "approval is needed" in t for u, t in asked))
        check("the convener is not notified about their own sitting", all(u != U_HR for u, _ in asked))
        slr = rec["slr_no"]

        section("Only a member gives a verdict, and only their own")
        await expect_http("someone who is not on the committee",
                          SL.record_verdict(OUT, COMPANY, slr, "Agree"), 404)
        await expect_http("Do not approve with no reason",
                          SL.record_verdict(HOD, COMPANY, slr, "Object"), 422, "why")
        await expect_http("PATCHing the other member's verdict (HR sets the HOD to Agree)",
                          SL.update_shortlist_review(HR, COMPANY, slr, {
                              "committee_members": [{"user_id": U_HR, "decision": "Agree"},
                                                    {"user_id": U_HOD, "decision": "Agree"}],
                              "outcome": "Selected"}, own_verdicts_only=True),
                          409, "waiting for")
        await expect_http("a member (not the convener) changing who sits",
                          SL.update_shortlist_review(HOD, COMPANY, slr, {
                              "committee_members": [{"user_id": U_HOD}, {"user_id": U_OUT}]},
                              own_verdicts_only=True), 403, "convened")

        section("Nothing is decided until everyone answers; the last answer decides")
        after_hr = await SL.record_verdict(HR, COMPANY, slr, "Agree")
        check("after HR approves, it is still Pending -- the HOD has not answered",
              after_hr["outcome"] == "Pending" and after_hr["committee_state"]["awaiting"] == ["Hari HOD"])
        check("the candidate has not moved", status_of("CAN-1") == M.AppStatus.INTERVIEW_SCHEDULED.value)
        done = await SL.record_verdict(HOD, COMPANY, slr, "Agree")
        check("the HOD's approval decides it: Selected", done["outcome"] == "Selected")
        check("...and the candidate moves to Selected", status_of("CAN-1") == M.AppStatus.SELECTED.value)
        await expect_http("a verdict on a decided sitting",
                          SL.record_verdict(HR, COMPANY, slr, "Object", "late"), 409, "already decided")

        section("One member not approving rejects")
        rec2 = await SL.create_shortlist_review(HR, COMPANY, {
            "request_no": "R-JUN", "candidate_uks": ["CAN-2"],
            "committee_members": [{"user_id": U_HR}, {"user_id": U_HOD}]}, own_verdicts_only=True)
        await SL.record_verdict(HR, COMPANY, rec2["slr_no"], "Agree")
        no = await SL.record_verdict(HOD, COMPANY, rec2["slr_no"], "Object", "Weak on the core skill")
        check("the HOD does not approve -> Rejected", no["outcome"] == "Rejected")
        hod2 = next(m for m in no["committee_members"] if m["user_id"] == U_HOD)
        check("...with their reason on record", hod2.get("remarks") == "Weak on the core skill")

        section("An old sitting where convening stamped everyone 'Agree'")
        store[M.COLL_CANDIDATES].docs.append(
            {"_id": ObjectId(), "uk": "CAN-3", "company_id": COMPANY, "candidate_name": "Three",
             "request_no": "R-JUN", "application_status": M.AppStatus.INTERVIEW_SCHEDULED.value})
        store[M.COLL_SHORTLIST_REVIEWS].docs.append({
            "slr_no": "SLR-OLD", "company_id": COMPANY, "request_no": "R-JUN",
            "candidate_uks": ["CAN-3"], "outcome": "Pending", "convened_by": U_HR,
            "committee_members": [
                {"user_id": U_HR, "name": "Hana HR", "role": "hr", "decision": "Agree"},
                {"user_id": U_HOD, "name": "Hari HOD", "role": "manager", "decision": "Agree"}]})
        await expect_http("HR recording it with the HOD's stamped 'Agree'",
                          SL.update_shortlist_review(HR, COMPANY, "SLR-OLD", {"outcome": "Selected"},
                                                     own_verdicts_only=True), 409, "Hari HOD")
        old = await SL.record_verdict(HR, COMPANY, "SLR-OLD", "Agree")
        check("HR's own approval does not decide it -- the HOD still has to answer",
              old["outcome"] == "Pending" and old["committee_state"]["awaiting"] == ["Hari HOD"])
        old = await SL.record_verdict(HOD, COMPANY, "SLR-OLD", "Agree")
        check("the HOD's own approval then decides it", old["outcome"] == "Selected")

        section("Only the members and the convener see a sitting")
        mine = await SL.list_shortlist_reviews(HOD, COMPANY, only_mine=True)
        check("a member sees their sittings",
              {r["slr_no"] for r in mine["shortlist_reviews"]} == {slr, rec2["slr_no"], "SLR-OLD"})
        theirs = await SL.list_shortlist_reviews(OUT, COMPANY, only_mine=True)
        check("someone not involved sees none", theirs["shortlist_reviews"] == [])
        doc = await SL.get_shortlist_review(COMPANY, slr)
        check("the record says who is involved", SL._involved(doc, HR) and SL._involved(doc, HOD)
              and not SL._involved(doc, OUT))
    finally:
        mongo.get_collection = original

    passed = sum(RESULTS)
    print(f"\n=== {passed}/{len(RESULTS)} checks passed ===")
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
