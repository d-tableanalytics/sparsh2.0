"""Candidate Source is locked once the candidate's own application recorded it.

HR may fill in a MISSING platform, and may correct one on a candidate HR added by hand.

Run:  python -m app.services.hrms.tests.test_candidate_source_lock   (from backend/)
"""
import asyncio

RESULTS = []


def check(label: str, ok: bool) -> None:
    RESULTS.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

CO = "C-INT"


async def main() -> None:
    from fastapi import HTTPException
    from app.models import hrms as M
    import app.db.mongodb as mongo
    import app.services.hrms_candidate_service as C

    cands = FakeCollection([
        # applied through the link, platform captured -> locked
        {"uk": "C1", "company_id": CO, "posting_code": "JB-1", "source": "Social Media",
         "source_platform": "linkedin", "application_status": "Applied"},
        # applied through the link before the platform was asked -> may be filled in
        {"uk": "C2", "company_id": CO, "posting_code": "JB-1", "source": "Job Portal",
         "source_platform": None, "application_status": "Applied"},
        # added by HR -> HR may correct it
        {"uk": "C3", "company_id": CO, "created_by": "hr", "source": "Manual",
         "source_platform": "naukri", "application_status": "Applied"},
        # online application whose platform HR filled in -> HR may still correct it
        {"uk": "C4", "company_id": CO, "posting_code": "JB-1", "source": "Job Portal",
         "source_platform": "indeed", "source_platform_by": "hr", "application_status": "Applied"},
    ])
    store = {M.COLL_CANDIDATES: cands, M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())
    C.get_collection = mongo.get_collection

    async def visible(actor, company_id, uk):
        return await cands.find_one({"uk": uk})
    C._require_visible = visible
    HR = {"_id": "hr", "role": "staff", "governance_role": "HR"}

    async def attempt(uk, value):
        try:
            await C.update_candidate(HR, CO, uk, {"source_platform": value})
            return 200
        except HTTPException as e:
            return e.status_code

    try:
        check("a platform recorded by the application cannot be changed",
              await attempt("C1", "naukri") == 409)
        check("...nor cleared", await attempt("C1", None) == 409)
        check("the stored value is untouched",
              (await cands.find_one({"uk": "C1"}))["source_platform"] == "linkedin")
        check("re-sending the same value is harmless", await attempt("C1", "linkedin") == 200)
        check("a MISSING platform on an online application can be filled in",
              await attempt("C2", "naukri") == 200
              and (await cands.find_one({"uk": "C2"}))["source_platform"] == "naukri")
        check("...and HR filling it in does not lock it",
              (await cands.find_one({"uk": "C2"})).get("source_platform_by") == "hr"
              and await attempt("C2", "apna") == 200)
        check("a platform HR set on an online application can be corrected",
              await attempt("C4", "shine") == 200)
        check("a candidate HR added can be corrected",
              await attempt("C3", "indeed") == 200
              and (await cands.find_one({"uk": "C3"}))["source_platform"] == "indeed")
    finally:
        mongo.get_collection = original

    passed = sum(RESULTS)
    print(f"\n=== {passed}/{len(RESULTS)} checks passed ===")
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
