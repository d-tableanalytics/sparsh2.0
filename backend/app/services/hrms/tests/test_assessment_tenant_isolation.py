"""Two companies, one assessment number: reviewing one must never touch the other.

`assessment_no` is unique only within a company — every tenant counts ASM-2026-001 from one.
review_assessment used to read the document back by number alone after recording a decision,
so with two ASM-2026-001s it could pick up the OTHER company's already-decided assessment,
judge it "resolved", and resolve that one instead: rewriting its status and timestamp, moving
a candidate looked up by the other record's uk inside the caller's company, and telling the
other record's manager. The caller's own assessment was left at Completed with both Passes on
it, and its candidate could not be put forward for interview.

This rebuilds that exact collision and checks both sides.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_assessment_tenant_isolation   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

ACME, OTHER = "C-ACME", "C-OTHER"
NO = "ASM-2026-001"          # the same number in both companies — the whole point


async def main() -> int:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_HR, U_MGR, U_OTHER_MGR = (str(ObjectId()) for _ in range(3))
    EARLIER = datetime(2026, 8, 11, 7, 30, tzinfo=timezone.utc)

    assessments = FakeCollection([
        # The OTHER company's ASM-2026-001, decided and resolved weeks ago. Listed FIRST so an
        # unscoped read by number alone finds it before ACME's — the order that broke it.
        {"_id": ObjectId(), "assessment_no": NO, "company_id": OTHER, "uk": "CAN-001",
         "candidate_name": "Other Person", "status": M.AssessmentStatus.REVIEWED.value,
         "outcome": "Pass", "resolved_at": EARLIER, "manager_id": U_OTHER_MGR,
         "hr_decision": "Pass", "manager_decision": "Pass", "max_score": 100},
        # ACME's ASM-2026-001: submitted, nobody has decided yet.
        {"_id": ObjectId(), "assessment_no": NO, "company_id": ACME, "uk": "CAN-005",
         "candidate_name": "Bhumika", "status": M.AssessmentStatus.COMPLETED.value,
         "manager_id": U_MGR, "hr_decision": None, "manager_decision": None,
         "max_score": 100},
    ])
    candidates = FakeCollection([
        {"_id": ObjectId(), "uk": "CAN-005", "company_id": ACME, "candidate_name": "Bhumika",
         "application_status": M.AppStatus.ASSESSMENT_COMPLETED.value},
        # An unrelated ACME candidate that happens to share the OTHER record's uk. The old
        # code looked the candidate up by the wrong document's uk in the caller's company.
        {"_id": ObjectId(), "uk": "CAN-001", "company_id": ACME, "candidate_name": "Bystander",
         "application_status": M.AppStatus.ASSESSMENT_COMPLETED.value},
    ])

    store = {M.COLL_ASSESSMENTS: assessments, M.COLL_CANDIDATES: candidates,
             M.COLL_AUDIT_LOG: FakeCollection(), M.COLL_REQUISITIONS: FakeCollection()}
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_assessment_service as AS
    import app.services.hrms_audit_service as AUD
    for mod in (AS, AUD):
        mod.get_collection = mongo.get_collection

    told = []

    async def fake_user(uid, title, msg, **kw):
        told.append(str(uid))

    async def fake_role(*a, **kw):
        return None

    AS.notify_user = fake_user
    AS.notify_hrms_role = fake_role

    HR = {"_id": U_HR, "role": "clientuser", "_source_collection": "learners",
          "company_id": ACME, "governance_role": "HR", "full_name": "Hana HR"}
    MGR = {"_id": U_MGR, "role": "clientuser", "_source_collection": "learners",
           "company_id": ACME, "governance_role": "HOD", "full_name": "Hari HOD"}

    def acme():
        return next(d for d in assessments.docs if d["company_id"] == ACME)

    def other():
        return next(d for d in assessments.docs if d["company_id"] == OTHER)

    def cand(uk):
        return next(d for d in candidates.docs if d["uk"] == uk)

    # =================================================================
    section("HR decides first — nothing resolves yet")
    # =================================================================
    await AS.review_assessment(HR, ACME, NO, {"decision": "Pass", "score": 70})
    check("ACME's HR slot is recorded", acme()["hr_decision"] == "Pass")
    check("ACME's assessment is NOT resolved on one signature",
          acme()["status"] == M.AssessmentStatus.COMPLETED.value)
    check("the hiring manager is chased", U_MGR in told)

    # =================================================================
    section("The manager decides — ACME's assessment resolves, and only ACME's")
    # =================================================================
    told.clear()
    out = await AS.review_assessment(MGR, ACME, NO, {"decision": "Pass"})
    check("ACME's assessment is Reviewed", acme()["status"] == M.AssessmentStatus.REVIEWED.value)
    check("with the right outcome", acme().get("outcome") == "Pass")
    check("and a resolution time", acme().get("resolved_at") is not None)
    check("the response is ACME's document, not the other company's",
          out.get("company_id") == ACME and out.get("candidate_name") == "Bhumika")

    check("ACME's candidate moves to Assessment Passed — so an interview can be scheduled",
          cand("CAN-005")["application_status"] == M.AppStatus.ASSESSMENT_PASSED.value)
    check("the unrelated ACME candidate sharing the other record's uk is untouched",
          cand("CAN-001")["application_status"] == M.AppStatus.ASSESSMENT_COMPLETED.value)

    check("the other company's resolution time is NOT rewritten",
          other()["resolved_at"] == EARLIER)
    check("its status and outcome are exactly as they were",
          other()["status"] == M.AssessmentStatus.REVIEWED.value
          and other()["outcome"] == "Pass")
    check("the other company's manager is NOT notified", U_OTHER_MGR not in told)

    # =================================================================
    section("_resolve refuses a document from another company outright")
    # =================================================================
    from fastapi import HTTPException
    try:
        await AS._resolve(HR, ACME, dict(other()))
        check("resolving another tenant's document is refused", False)
    except HTTPException as e:
        check("resolving another tenant's document is refused", e.status_code == 409)
    check("and it changed nothing", other()["resolved_at"] == EARLIER)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
