"""Sanctioned strength, end to end, from raising a requisition to a publishable JD.

test_phase11_sanction proves the sanction ARITHMETIC and the escalation ladder in isolation.
This walks the two journeys a person actually takes, through every gate, and checks the thing
those unit-level suites stop short of: that the chain still ends where it should — requisition
Approved, and its JD approved in the same step, which is what makes the role publishable.

  WITHIN sanction   raise -> HR verify -> budget approve ------------> scorecard gate -> JD
  OVER sanction     raise -> HR verify -> budget approve -> escalate -> scorecard gate -> JD

Also checked: the committed-seat arithmetic across several live requisitions (the double-spend
guard, seen from the outside), that a rejection at either decision point stops the chain and
takes the JD with it, and that the scorecard gate refuses until a scorecard is actually
approved.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_sanction_to_jd_e2e   (from backend/)
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
    except Exception as e:                                   # noqa: BLE001
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

COMPANY = "C1"
FUTURE = (datetime.now(timezone.utc) + timedelta(days=45)).strftime("%Y-%m-%d")


async def main() -> int:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_MD, U_HOD, U_BOSS = (str(ObjectId()) for _ in range(4))
    DEPT, DESIG = str(ObjectId()), str(ObjectId())

    learners = FakeCollection([
        {"_id": ObjectId(U_HR), "company_id": COMPANY, "full_name": "Hana HR",
         "governance_role": "HR", "is_active": True},
        {"_id": ObjectId(U_MD), "company_id": COMPANY, "full_name": "Meera MD",
         "governance_role": "MD", "is_active": True},
        # The raiser reports to a MANAGER, not to the MD. Keeping the two apart is the
        # point: the ladder follows the reporting line, and the MD is appended at the end
        # by rule — so a line that never passes through an MD still reaches one.
        {"_id": ObjectId(U_HOD), "company_id": COMPANY, "full_name": "Hari HOD",
         "governance_role": "HOD", "is_active": True, "reporting_manager": U_BOSS},
        {"_id": ObjectId(U_BOSS), "company_id": COMPANY, "full_name": "Bela Boss",
         "governance_role": "HOD", "is_active": True},
    ])
    departments = FakeCollection([
        {"_id": ObjectId(DEPT), "company_id": COMPANY, "name": "Engineering", "active": True}])
    designations = FakeCollection([
        {"_id": ObjectId(DESIG), "company_id": COMPANY, "name": "Backend Engineer",
         "active": True}])
    # One engineer already on the payroll, so `actual` is a real number rather than zero.
    profiles = FakeCollection([
        {"_id": ObjectId(), "company_id": COMPANY, "department_id": DEPT,
         "designation_id": DESIG, "employment_status": "Active"}])

    store = {
        "learners": learners, "staff": FakeCollection(),
        M.COLL_DEPARTMENTS: departments, M.COLL_DESIGNATIONS: designations,
        M.COLL_EMPLOYEE_PROFILES: profiles,
        M.COLL_SANCTIONED_STRENGTH: FakeCollection(), M.COLL_REQUISITIONS: FakeCollection(),
        M.COLL_JOB_DESCRIPTIONS: FakeCollection(), M.COLL_POSITION_SCORECARDS: FakeCollection(),
        M.COLL_COUNTERS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection(),
    }
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_requisition_service as RS
    import app.services.hrms_sanction_service as SS
    import app.services.hrms_scorecard_service as SC
    import app.services.hrms_employee_service as ES
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    for mod in (RS, SS, SC, ES, AUD, IDS):
        mod.get_collection = mongo.get_collection

    async def quiet(*a, **kw):
        return None

    for mod in (RS, SC):
        mod.notify_user = quiet
        mod.notify_hrms_role = quiet

    def person(uid, gov, name):
        return {"_id": uid, "role": "clientuser", "_source_collection": "learners",
                "company_id": COMPANY, "governance_role": gov, "full_name": name}

    HR, MD = person(U_HR, "HR", "Hana HR"), person(U_MD, "MD", "Meera MD")
    HOD, BOSS = person(U_HOD, "HOD", "Hari HOD"), person(U_BOSS, "MD", "Bela Boss")

    def payload(seats, **over):
        base = {"department_id": DEPT, "designation_id": DESIG, "vacancy": seats,
                "experience_required": "3-5 years", "qualification": "B.Tech",
                "essential_skills": "Python", "required_date": FUTURE,
                "requirement_type": "New", "justification": "Growth",
                "jd_summary": "Builds and runs the backend services.",
                "jd_responsibilities": "Design, build, operate.",
                "jd_requirements": "Python, SQL."}
        base.update(over)
        return base

    BAND = {"approved_headcount": 1, "approved_salary_band_min": 500000,
            "approved_salary_band_max": 700000}

    async def budget(req_no, actor=MD):
        return await RS.act_on_requisition(actor, COMPANY, req_no, "budget-approve",
                                           budget=BAND)

    async def approved_scorecard(req_no, title):
        """A scorecard signed off, which the final gate requires before it will pass."""
        sc = await SC.create_scorecard(HR, COMPANY, {
            "request_no": req_no, "title": title,
            "criteria": [{"label": "Python", "category": "skill", "expected_level": "Strong",
                          "evaluation_criteria": "Live coding", "weight": 3, "max_score": 5}]})
        await SC.approve_scorecard(HOD, COMPANY, sc["scr_no"],
                                   {"decision": "Pass", "signature": "Hari HOD"})
        return sc["scr_no"]

    # =================================================================
    section("Sanctioned strength is set for the position")
    # =================================================================
    saved = await SS.set_sanction(MD, COMPANY, {
        "department_id": DEPT, "designation_id": DESIG, "sanctioned_count": 4,
        "remarks": "Four backend seats agreed."})
    check("the figure is stored", saved["sanctioned_count"] == 4)
    status = await SS.position_status(COMPANY, DEPT, DESIG, requested=0)
    check("actual is COUNTED from the payroll, not stored", status["actual"] == 1)
    check("nothing is committed yet", status["open_requisitions"] == 0)
    check("with 1 of 4 filled, the position is not over sanction",
          status["is_over_sanction"] is False)

    # =================================================================
    section("WITHIN sanction: 1 + 0 committed + 2 requested = 3 of 4")
    # =================================================================
    r1 = await RS.create_requisition(HOD, COMPANY, payload(2))
    req1 = r1["request_no"]
    check("raised, waiting on HR", r1["approval_status"] == M.ReqApproval.PENDING_HR_VERIFICATION.value)
    check("the snapshot says it is inside sanction",
          r1["sanction_snapshot"]["is_over_sanction"] is False)
    check("and records the figures it was judged on",
          (r1["sanction_snapshot"]["sanctioned"], r1["sanction_snapshot"]["actual"],
           r1["sanction_snapshot"]["requested"]) == (4, 1, 2))

    s = await RS.act_on_requisition(HR, COMPANY, req1, "hr-verify")
    check("HR verification moves it to the budget gate",
          s["approval_status"] == M.ReqApproval.PENDING_BUDGET.value)
    s = await budget(req1)
    check("budget approval goes STRAIGHT to the scorecard gate — no escalation",
          s["approval_status"] == M.ReqApproval.PENDING_SCORECARD.value)
    check("no escalation chain was built", not (s.get("escalation_chain") or []))

    jd1 = s.get("jd_no")
    check("a JD was created with the requisition", bool(jd1))
    jd_doc = await store[M.COLL_JOB_DESCRIPTIONS].find_one({"jd_no": jd1, "company_id": COMPANY})
    check("and it is NOT approved yet", jd_doc["status"] != M.JdStatus.APPROVED.value)

    # The gate is only real if it checks the scorecard, so both halves of that are tested:
    # none at all, and one that exists but nobody has signed.
    await expect_http("the final gate with no scorecard at all",
                      RS.act_on_requisition(HOD, COMPANY, req1, "scorecard-approve"),
                      409, "no position scorecard")
    draft = await SC.create_scorecard(HR, COMPANY, {
        "request_no": req1, "title": "Backend Engineer",
        "criteria": [{"label": "Python", "category": "skill", "expected_level": "Strong",
                      "evaluation_criteria": "Live coding", "weight": 3, "max_score": 5}]})
    await expect_http("the final gate with a scorecard nobody has signed",
                      RS.act_on_requisition(HOD, COMPANY, req1, "scorecard-approve"),
                      409, "still waiting on")
    await SC.approve_scorecard(HOD, COMPANY, draft["scr_no"],
                               {"decision": "Pass", "signature": "Hari HOD"})
    s = await RS.act_on_requisition(HOD, COMPANY, req1, "scorecard-approve")
    check("the final gate approves the requisition",
          s["approval_status"] == M.ReqApproval.APPROVED.value)
    jd_doc = await store[M.COLL_JOB_DESCRIPTIONS].find_one({"jd_no": jd1, "company_id": COMPANY})
    check("and its JD is approved in the same step — publishable",
          jd_doc["status"] == M.JdStatus.APPROVED.value)

    # =================================================================
    section("Committed seats: the approved requisition now counts against the figure")
    # =================================================================
    status = await SS.position_status(COMPANY, DEPT, DESIG, requested=0)
    check("its 2 seats are committed", status["open_requisitions"] == 2)
    check("1 filled + 2 committed = 3 of 4, still inside",
          status["is_over_sanction"] is False)
    status = await SS.position_status(COMPANY, DEPT, DESIG, requested=1)
    check("one more seat takes it to exactly 4 — still inside",
          status["is_over_sanction"] is False)
    status = await SS.position_status(COMPANY, DEPT, DESIG, requested=2)
    check("two more would be 5 of 4 — over", status["is_over_sanction"] is True)

    # =================================================================
    section("OVER sanction: 1 + 2 committed + 2 requested = 5 of 4")
    # =================================================================
    r2 = await RS.create_requisition(HOD, COMPANY, payload(2))
    req2 = r2["request_no"]
    check("the snapshot says it is over sanction",
          r2["sanction_snapshot"]["is_over_sanction"] is True)
    check("the committed seats are counted in it",
          r2["sanction_snapshot"]["open_requisitions"] == 2)

    await RS.act_on_requisition(HR, COMPANY, req2, "hr-verify")
    s = await budget(req2)
    check("budget approval routes it to ESCALATION, not to the scorecard gate",
          s["approval_status"] == M.ReqApproval.PENDING_ESCALATION.value)
    chain = s.get("escalation_chain") or []
    check("a chain was built from the raiser's reporting line", len(chain) >= 1)
    check("it starts with the raiser's own manager",
          str((chain[0] or {}).get("user_id")) == U_BOSS)
    # The requirement this exists for: the reporting line here holds no MD at all, and the
    # ladder must still end at one. Manager and MD are different people, deliberately.
    check("the manager is NOT the MD", U_BOSS != U_MD)
    check("the LAST rung is the MD", chain[-1]["role"] == "MD"
          and str(chain[-1]["user_id"]) == U_MD)
    check("and it is there by rule, not by reporting line",
          chain[-1].get("mandatory") is True)

    await expect_http("the scorecard gate cannot be reached around the escalation",
                      RS.act_on_requisition(HOD, COMPANY, req2, "scorecard-approve"),
                      409)

    s = await RS.act_on_requisition(BOSS, COMPANY, req2, "escalate-approve")
    check("the manager's approval advances the ladder but does NOT release it",
          s["approval_status"] == M.ReqApproval.PENDING_ESCALATION.value)
    check("it is now with the MD", int(s.get("escalation_level") or 0) == len(chain))
    await expect_http("a hiring manager cannot clear the MD's rung",
                      RS.act_on_requisition(HOD, COMPANY, req2, "escalate-approve"), 403)
    s = await RS.act_on_requisition(MD, COMPANY, req2, "escalate-approve")
    check("only the MD's approval returns it to the scorecard gate",
          s["approval_status"] == M.ReqApproval.PENDING_SCORECARD.value)

    await approved_scorecard(req2, "Backend Engineer (2)")
    s = await RS.act_on_requisition(HOD, COMPANY, req2, "scorecard-approve")
    check("an over-sanction requisition still finishes the chain once escalated",
          s["approval_status"] == M.ReqApproval.APPROVED.value)
    jd2 = await store[M.COLL_JOB_DESCRIPTIONS].find_one(
        {"jd_no": s.get("jd_no"), "company_id": COMPANY})
    check("its JD is publishable too", jd2["status"] == M.JdStatus.APPROVED.value)

    # =================================================================
    section("Rejection stops the chain, at either decision point")
    # =================================================================
    r3 = await RS.create_requisition(HOD, COMPANY, payload(3))
    req3 = r3["request_no"]
    await RS.act_on_requisition(HR, COMPANY, req3, "hr-verify")
    s = await budget(req3)
    check("3 more seats escalates", s["approval_status"] == M.ReqApproval.PENDING_ESCALATION.value)
    await expect_http("an escalation rejection with no reason",
                      RS.act_on_requisition(BOSS, COMPANY, req3, "escalate-reject"), 422)
    # Rejecting at the FIRST rung closes it: the ladder never reaches the MD, which is the
    # right outcome — the manager has already said no.
    s = await RS.act_on_requisition(BOSS, COMPANY, req3, "escalate-reject",
                                    "Not this quarter.")
    check("rejecting the escalation closes the requisition",
          s["approval_status"] == M.ReqApproval.REJECTED.value)
    jd3 = await store[M.COLL_JOB_DESCRIPTIONS].find_one(
        {"jd_no": s.get("jd_no"), "company_id": COMPANY})
    check("its JD is rejected with it — nothing publishable survives",
          jd3["status"] == M.JdStatus.REJECTED.value)
    status = await SS.position_status(COMPANY, DEPT, DESIG, requested=0)
    check("a rejected requisition commits no seats", status["open_requisitions"] == 4)

    r4 = await RS.create_requisition(HOD, COMPANY, payload(1))
    req4 = r4["request_no"]
    await RS.act_on_requisition(HR, COMPANY, req4, "hr-verify")
    await budget(req4)
    await RS.act_on_requisition(BOSS, COMPANY, req4, "escalate-approve")
    s = await RS.act_on_requisition(MD, COMPANY, req4, "escalate-approve")
    check("both rungs cleared, so it reaches the scorecard gate",
          s["approval_status"] == M.ReqApproval.PENDING_SCORECARD.value)
    await approved_scorecard(req4, "Backend Engineer (4)")
    s = await RS.act_on_requisition(HOD, COMPANY, req4, "scorecard-reject",
                                    "The bar is wrong for this level.")
    check("rejecting at the FINAL gate also closes it",
          s["approval_status"] == M.ReqApproval.REJECTED.value)
    jd4 = await store[M.COLL_JOB_DESCRIPTIONS].find_one(
        {"jd_no": s.get("jd_no"), "company_id": COMPANY})
    check("and its JD is not left publishable", jd4["status"] != M.JdStatus.APPROVED.value)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
