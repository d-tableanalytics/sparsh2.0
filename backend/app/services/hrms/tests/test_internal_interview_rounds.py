"""Internal hiring interview design (SOP section 5).

  * Panel interview: HR + Department Head for junior/mid roles; add Management for
    senior/managerial roles.
  * Final interview with Management for managerial and above roles before offer stage.

So on the internal track a junior / mid candidate sits ONE interview (the Panel Interview),
and a senior / managerial candidate sits the Panel Interview and then ONE more (the
Management interview, conducted by the MD). Each is held once. The client track is untouched.

Run:  python -m app.services.hrms.tests.test_internal_interview_rounds   (from backend/)
"""
import asyncio
from datetime import datetime, timedelta, timezone

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
        ok = e.status_code == status
        if ok and fragment:
            ok = fragment.lower() in str(e.detail).lower()
        check(f"{label} -> {status}" + (f" ('{fragment}')" if fragment else "")
              + ("" if ok else f"  [got {e.status_code}: {e.detail}]"), ok)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
NOW = datetime.now(timezone.utc)
SOON = (NOW + timedelta(days=3)).isoformat()


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_HOD, U_MD = (str(ObjectId()) for _ in range(3))
    DESIG_MID, DESIG_MANAGERIAL = ObjectId(), ObjectId()

    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "full_name": "Hana HR", "email": "hr@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "HR"},
        {"_id": ObjectId(U_HOD), "full_name": "Hari HOD", "email": "hod@c1.com",
         "company_id": COMPANY, "role": "clientuser", "governance_role": "HOD"},
        {"_id": ObjectId(U_MD), "full_name": "Meera MD", "email": "md@c1.com",
         "company_id": COMPANY, "role": "clientadmin", "governance_role": "MD"},
    ])
    designations = FakeCollection([
        {"_id": DESIG_MID, "company_id": COMPANY, "name": "Ops Executive",
         "designation_level": "mid"},
        {"_id": DESIG_MANAGERIAL, "company_id": COMPANY, "name": "Ops Manager",
         "designation_level": "managerial"},
    ])
    reqs = FakeCollection([
        {"request_no": "R-MID", "company_id": COMPANY, "requisition_track": "internal",
         "designation_name": "Ops Executive", "designation_id": str(DESIG_MID),
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
        {"request_no": "R-MGR", "company_id": COMPANY, "requisition_track": "internal",
         "designation_name": "Ops Manager", "designation_id": str(DESIG_MANAGERIAL),
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
        {"request_no": "R-CLIENT", "company_id": COMPANY, "requisition_track": "client",
         "designation_name": "Analyst", "designation_id": str(DESIG_MID),
         "approval_status": "Approved", "closing_status": "Open", "created_at": NOW},
    ])
    candidates = FakeCollection([
        {"_id": ObjectId(), "uk": "CAN-MID", "company_id": COMPANY, "candidate_name": "Mid One",
         "request_no": "R-MID", "application_status": M.AppStatus.SHORTLISTED.value},
        {"_id": ObjectId(), "uk": "CAN-MGR", "company_id": COMPANY,
         "candidate_name": "Manager One", "request_no": "R-MGR",
         "application_status": M.AppStatus.SHORTLISTED.value},
        {"_id": ObjectId(), "uk": "CAN-FIR", "company_id": COMPANY,
         "candidate_name": "Routed One", "request_no": "R-MGR",
         "application_status": M.AppStatus.FINAL_INTERVIEW_REQUIRED.value},
        {"_id": ObjectId(), "uk": "CAN-CLI", "company_id": COMPANY,
         "candidate_name": "Client One", "request_no": "R-CLIENT",
         "application_status": M.AppStatus.SHORTLISTED.value},
    ])
    interviews = FakeCollection()
    telephonic = FakeCollection([
        {"tel_no": f"TEL-{n}", "company_id": COMPANY, "uk": c["uk"],
         "request_no": c["request_no"], "outcome": M.TelephonicOutcome.PASSED.value}
        for n, c in enumerate(candidates.docs, start=1)])
    store = {M.COLL_REQUISITIONS: reqs, M.COLL_CANDIDATES: candidates,
             M.COLL_INTERVIEWS: interviews, M.COLL_DESIGNATIONS: designations,
             M.COLL_INTERVIEW_WINDOWS: FakeCollection(), M.COLL_COUNTERS: FakeCollection(),
             M.COLL_TELEPHONIC: telephonic, M.COLL_AUDIT_LOG: FakeCollection(),
             M.COLL_SHORTLIST_REVIEWS: FakeCollection(),
             "learners": learners}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_interview_service as IV
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (IV, AUD, IDS):
        mod.get_collection = mongo.get_collection

    notes = []

    async def note(*a, **kw):
        notes.append(a)
    IV.notify_user = note

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR", "full_name": "Hana HR"}

    def booking(uk, round_name, lead, *members):
        return {"uk": uk, "round": round_name, "mode": "Virtual", "scheduled_at": SOON,
                "duration_min": 45, "interviewer_id": lead,
                "meeting_link": "https://meet.example.com/x",
                "panel": [{"user_id": u} for u in members]}

    def status_of(uk):
        return next(c for c in candidates.docs if c["uk"] == uk)["application_status"]

    PANEL, FINAL = M.InterviewRound.PANEL.value, M.InterviewRound.MD.value
    try:
        section("The rounds each band sits")
        check("junior: one interview -- the Panel Interview",
              M.internal_rounds_for("junior") == [M.InterviewRound.PANEL])
        check("mid: one interview -- the Panel Interview",
              M.internal_rounds_for("mid") == [M.InterviewRound.PANEL])
        check("senior: the Panel Interview, then the Management interview",
              M.internal_rounds_for("senior") == [M.InterviewRound.PANEL, M.InterviewRound.MD])
        check("managerial: the same two",
              M.internal_rounds_for("managerial") == [M.InterviewRound.PANEL, M.InterviewRound.MD])

        section("Junior / mid: ONE interview")
        await expect_http("an old-style HR Round on the internal track",
                          IV.schedule_interview(HR, COMPANY, booking("CAN-MID", "HR Round", U_HR, U_HOD)),
                          422, "Panel Interview")
        await expect_http("a Management interview for a mid role",
                          IV.schedule_interview(HR, COMPANY, booking("CAN-MID", FINAL, U_MD)),
                          422, "one interview only")
        await expect_http("a mid panel with HR only",
                          IV.schedule_interview(HR, COMPANY, booking("CAN-MID", PANEL, U_HR)),
                          422, "still missing")
        mid = await IV.schedule_interview(HR, COMPANY, booking("CAN-MID", PANEL, U_HR, U_HOD))
        check("the Panel Interview with HR + HOD books", mid["round"] == PANEL)
        await expect_http("a second Panel Interview for the same candidate",
                          IV.schedule_interview(HR, COMPANY, booking("CAN-MID", PANEL, U_HR, U_HOD)),
                          409, "held once")
        await interviews.update_one({"interview_no": mid["interview_no"]},
                                    {"$set": {"status": "Cancelled"}})
        again = await IV.schedule_interview(HR, COMPANY, booking("CAN-MID", PANEL, U_HR, U_HOD))
        check("...but a cancelled one may be rebooked", again["interview_no"] != mid["interview_no"])

        section("Senior / managerial: the panel, then the Management interview")
        await expect_http("a managerial panel with HR + HOD only",
                          IV.schedule_interview(HR, COMPANY, booking("CAN-MGR", PANEL, U_HR, U_HOD)),
                          422, "still missing")
        await expect_http("the Management interview before the panel",
                          IV.schedule_interview(HR, COMPANY, booking("CAN-MGR", FINAL, U_MD)),
                          409, "after the Panel Interview")
        mgr = await IV.schedule_interview(
            HR, COMPANY, booking("CAN-MGR", PANEL, U_HR, U_HOD, U_MD))
        check("the managerial panel with HR + HOD + Management books", mgr["round"] == PANEL)

        # Panel PASS on a managerial role -> straight to the Management interview (no committee).
        await interviews.update_one({"interview_no": mgr["interview_no"]},
                                    {"$set": {"status": "Completed", "outcome": "Pass"}})
        await IV._advance_candidate(HR, COMPANY, {**mgr, "outcome": "Pass"}, M.Outcome.PASS)
        check("a panel pass sends a managerial candidate to the Management interview",
              status_of("CAN-MGR") == M.AppStatus.FINAL_INTERVIEW_REQUIRED.value)
        check("...and says so", any("Management interview" in str(n) for n in notes))

        await expect_http("the Management interview led by HR, not the MD",
                          IV.schedule_interview(HR, COMPANY, booking("CAN-MGR", FINAL, U_HR, U_MD)),
                          422, "conducted by the MD")
        final = await IV.schedule_interview(HR, COMPANY, booking("CAN-MGR", FINAL, U_MD))
        check("the Management interview books right after the panel -- no committee needed",
              final["round"] == FINAL)
        check("...and the candidate is now in it (MD Round)",
              status_of("CAN-MGR") == M.AppStatus.MD_ROUND.value)

        # Panel FAIL -> stop: rejected, and no Management interview.
        candidates.docs.append({"_id": ObjectId(), "uk": "CAN-FAIL", "company_id": COMPANY,
                                "candidate_name": "Failed Panel", "request_no": "R-MGR",
                                "application_status": M.AppStatus.INTERVIEW_SCHEDULED.value})
        telephonic.docs.append({"tel_no": "TEL-F", "company_id": COMPANY, "uk": "CAN-FAIL",
                                "request_no": "R-MGR", "outcome": M.TelephonicOutcome.PASSED.value})
        failed = {"interview_no": "INT-F", "company_id": COMPANY, "uk": "CAN-FAIL",
                  "round": PANEL, "request_no": "R-MGR", "status": "Completed", "outcome": "Fail",
                  "candidate_name": "Failed Panel"}
        interviews.docs.append(dict(failed))
        await IV._advance_candidate(HR, COMPANY, failed, M.Outcome.FAIL)
        check("a panel fail rejects the candidate", status_of("CAN-FAIL") == M.AppStatus.REJECTED.value)
        await expect_http("...and no Management interview can follow",
                          IV.schedule_interview(HR, COMPANY, booking("CAN-FAIL", FINAL, U_MD)),
                          409, "")

        await expect_http("a second Management interview",
                          IV.schedule_interview(HR, COMPANY, booking("CAN-MGR", FINAL, U_MD)),
                          409, "held once")

        section("A candidate the committee routed to the final interview can be booked for it")
        interviews.docs.append({"interview_no": "INT-OLD", "company_id": COMPANY, "uk": "CAN-FIR",
                                "round": PANEL, "status": "Completed", "outcome": "Pass"})
        routed = await IV.schedule_interview(HR, COMPANY, booking("CAN-FIR", FINAL, U_MD))
        check("Final Interview Required -> the Management interview books", routed["round"] == FINAL)
        check("...and the candidate moves into it (MD Round)",
              status_of("CAN-FIR") == M.AppStatus.MD_ROUND.value)

        section("A round booked under the old names counts as the panel interview")
        candidates.docs.append({"_id": ObjectId(), "uk": "CAN-OLD", "company_id": COMPANY,
                                "candidate_name": "Old Style", "request_no": "R-MID",
                                "application_status": M.AppStatus.TECHNICAL_ROUND.value})
        telephonic.docs.append({"tel_no": "TEL-OLD", "company_id": COMPANY, "uk": "CAN-OLD",
                                "request_no": "R-MID", "outcome": M.TelephonicOutcome.PASSED.value})
        interviews.docs.append({"interview_no": "INT-LEGACY", "company_id": COMPANY, "uk": "CAN-OLD",
                                "round": "HR Round", "status": "Completed", "outcome": "Pass"})
        await expect_http("a Panel Interview for someone who already passed an old HR Round",
                          IV.schedule_interview(HR, COMPANY, booking("CAN-OLD", PANEL, U_HR, U_HOD)),
                          409, "held once")
        opts = await IV.panel_options(HR, COMPANY, "CAN-OLD")
        check("...and the dialog shows it as already held",
              opts["rounds"][0]["available"] is False and "INT-LEGACY" in opts["rounds"][0]["reason"])

        section("The schedule dialog is told the rounds")
        opts = await IV.panel_options(HR, COMPANY, "CAN-MID")
        check("mid: only the Panel Interview is offered",
              [r["value"] for r in opts["rounds"]] == [PANEL] and not opts["two_interviews"])
        opts = await IV.panel_options(HR, COMPANY, "CAN-MGR", FINAL)
        check("managerial: both rounds are listed", [r["value"] for r in opts["rounds"]] == [PANEL, FINAL])
        check("...the Management interview needs Management only", opts["required_roles"] == ["md"])

        section("The client track is untouched")
        cli = await IV.schedule_interview(HR, COMPANY, booking("CAN-CLI", "HR Round", U_HR))
        check("a client-track HR Round still books, with no panel rule", cli["round"] == "HR Round")
    finally:
        mongo.get_collection = original

    passed = sum(RESULTS)
    print(f"\n=== {passed}/{len(RESULTS)} checks passed ===")
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
