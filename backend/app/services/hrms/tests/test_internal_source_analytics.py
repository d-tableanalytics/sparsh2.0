"""Internal hiring > Source Analytics: Job Portal -> Applied -> Shortlisted -> Connected ->
Interviewed -> Selected -> Hired.

Run:  python -m app.services.hrms.tests.test_internal_source_analytics   (from backend/)
"""
import asyncio
from datetime import datetime, timedelta, timezone

RESULTS = []


def check(label: str, ok: bool) -> None:
    RESULTS.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")


def section(title: str) -> None:
    print(f"\n-- {title} --")


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

CO = "C-INT"
T0 = datetime.now(timezone.utc) - timedelta(days=20)


def cand(uk, status, *, platform=None, source="Job Portal", dept="Finance", pos="Accountant",
         req="HR-REQ-1", **extra):
    return {"uk": uk, "company_id": CO, "source": source, "source_platform": platform,
            "application_status": status, "applied_at": T0, "request_no": req,
            "department_name": dept, "applied_position": pos, **extra}


async def main() -> None:
    from app.models import hrms as M
    import app.db.mongodb as mongo
    import app.services.hrms_analytics_service as A

    S = M.AppStatus
    cands = [
        # Naukri: 5 applied
        cand("N1", S.EMPLOYEE_CREATED.value, platform="naukri", joined_at=T0 + timedelta(days=15)),
        cand("N2", S.SELECTED.value, platform="naukri"),
        cand("N3", S.TELEPHONIC_REJECTED.value, platform="naukri"),     # spoke, then rejected
        cand("N4", S.SHORTLISTED.value, platform="naukri"),             # phone: No Answer
        cand("N5", S.APPLIED.value, platform="naukri"),
        # LinkedIn: 3 applied, one interviewed and rejected
        cand("L1", S.REJECTED.value, platform="linkedin", dept="Design", pos="Designer", req="HR-REQ-2"),
        cand("L2", S.INTERVIEW_SCHEDULED.value, platform="linkedin", dept="Design", pos="Designer", req="HR-REQ-2"),
        cand("L3", S.APPLIED.value, platform="linkedin", dept="Design", pos="Designer", req="HR-REQ-2"),
        # Legacy rows with no platform: Company Website maps; plain "Job Portal" cannot
        cand("W1", S.APPLIED.value, source="Company Website"),
        cand("X1", S.APPLIED.value, source="Job Portal"),
        cand("R1", S.APPLIED.value, source="Walk-in", is_referral=True),
        # outside the window
        {**cand("OLD", S.APPLIED.value, platform="naukri"), "applied_at": T0 - timedelta(days=400)},
    ]
    phone = [
        {"uk": "N2", "company_id": CO, "outcome": M.TelephonicOutcome.PASSED.value},
        {"uk": "N3", "company_id": CO, "outcome": M.TelephonicOutcome.REJECTED.value},
        {"uk": "N4", "company_id": CO, "outcome": M.TelephonicOutcome.NO_ANSWER.value},
        {"uk": "L2", "company_id": CO, "outcome": M.TelephonicOutcome.PASSED.value},
    ]
    interviews = [
        {"uk": "N2", "company_id": CO, "status": M.InterviewStatus.COMPLETED.value, "outcome": "Pass"},
        {"uk": "L1", "company_id": CO, "status": M.InterviewStatus.COMPLETED.value, "outcome": "Fail"},
        {"uk": "L2", "company_id": CO, "status": M.InterviewStatus.SCHEDULED.value},   # not yet held
    ]
    store = {M.COLL_CANDIDATES: FakeCollection(cands), M.COLL_TELEPHONIC: FakeCollection(phone),
             M.COLL_INTERVIEWS: FakeCollection(interviews), M.COLL_OFFERS: FakeCollection(),
             M.COLL_ASSESSMENTS: FakeCollection(), M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())
    A.get_collection = mongo.get_collection

    async def scope(actor, company_id):
        return {"company_id": company_id}
    A._scope = scope
    HR = {"_id": "hr", "role": "staff", "_source_collection": "staff", "governance_role": "HR"}
    try:
        r = await A.source_analytics(HR, CO)
        by = {x["platform"]: x for x in r["sources"]}

        section("Attribution")
        check("a candidate from before the window is not counted", r["totals"]["applied"] == 11)
        check("legacy 'Company Website' source is attributed to Company Website", by["website"]["applied"] == 1)
        check("a declared referral is attributed to Referral", by["referral"]["applied"] == 1)
        check("legacy plain 'Job Portal' is Not specified, not a guessed portal",
              r["not_specified"] == 1 and by["unspecified"]["source"] == "Not specified")
        check("Apna is a platform", M.normalise_platform("apna") == "apna")

        section("Funnel per portal")
        n = by["naukri"]
        check("Naukri: applied 5 -> shortlisted 4 -> connected 3 -> interviewed 2 -> selected 2 -> hired 1",
              tuple(n[k] for k in A.SRC_STAGES) == (5, 4, 3, 2, 2, 1))
        check("'No Answer' on the phone is not Connected (N4 shortlisted only)", n["connected"] == 3)
        check("a phone screen that ended in rejection IS Connected (N3)", n["connected"] >= 1)
        li = by["linkedin"]
        check("LinkedIn: an interview held and failed counts as Interviewed; a scheduled one does not",
              li["interviewed"] == 1)
        check("LinkedIn: the candidate interviewed counts as Connected and Shortlisted though now Rejected",
              (li["shortlisted"], li["connected"]) == (2, 2))
        check("every row narrows stage by stage",
              all(all(x[a] >= x[b] for a, b in zip(A.SRC_STAGES, A.SRC_STAGES[1:])) for x in r["sources"]))
        check("rates are of applied: Naukri hire rate 20%", n["hire_rate"] == 20.0)

        section("Which platform leads")
        L = r["leaders"]
        check("most candidates: Naukri", L["applied"]["source"] == "Naukri")
        check("most interviews: Naukri (2)", L["interviewed"] == {"source": "Naukri", "count": 2, "applied": 5})
        check("most hires: Naukri", L["hired"]["source"] == "Naukri")

        section("Filters")
        f = await A.source_analytics(HR, CO, department="Design")
        check("department narrows to LinkedIn's three", f["totals"]["applied"] == 3
              and [x["platform"] for x in f["sources"]] == ["linkedin"])
        f = await A.source_analytics(HR, CO, request_no="HR-REQ-2")
        check("requisition filter", f["totals"]["applied"] == 3)
        f = await A.source_analytics(HR, CO, position="Accountant")
        check("position filter", f["totals"]["applied"] == 8)
        f = await A.source_analytics(HR, CO, platform="naukri")
        check("source filter", [x["platform"] for x in f["sources"]] == ["naukri"])
        check("filter choices still list every department", f["options"]["departments"] == ["Design", "Finance"])
        check("filter choices include Apna and Not specified",
              {"apna", "unspecified"} <= {p["key"] for p in f["options"]["platforms"]})

        section("Trend")
        check("the trend adds up to the applications",
              sum(sum(p["counts"].values()) for p in r["trend"]["points"]) == r["totals"]["applied"])

        section("Attribution rule at creation")
        P = M.platform_for_candidate
        check("an explicit platform wins", P("Naukri", "Social Media") == "naukri")
        check("a referral beats the channel", P(None, "Job Portal", True) == "referral")
        check("Walk-in becomes Other", P(None, "Walk-in") == "other")
        check("the public form accepts platform", M.PublicApplicationIn.model_fields.get("platform") is not None)
        check("manual add accepts source_platform", M.CandidateIn.model_fields.get("source_platform") is not None)
        check("HR can correct the platform later", M.CandidateUpdate.model_fields.get("source_platform") is not None)
    finally:
        mongo.get_collection = original

    passed = sum(RESULTS)
    print(f"\n=== {passed}/{len(RESULTS)} checks passed ===")
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
