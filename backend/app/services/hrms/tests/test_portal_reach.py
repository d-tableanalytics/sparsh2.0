"""Internal hiring > Job Portal Reach.

Run:  python -m app.services.hrms.tests.test_portal_reach   (from backend/)
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


class ViewsCollection(FakeCollection):
    """FakeCollection plus the upsert record_view relies on."""

    async def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in flt.items()):
                for k, v in (update.get("$inc") or {}).items():
                    d[k] = d.get(k, 0) + v
                d.update(update.get("$set") or {})
                return
        if upsert:
            doc = {**flt, **(update.get("$setOnInsert") or {}), **(update.get("$set") or {})}
            for k, v in (update.get("$inc") or {}).items():
                doc[k] = v
            self.docs.append(doc)


async def main() -> None:
    from app.models import hrms as M
    import app.db.mongodb as mongo
    import app.services.hrms_reach_service as R
    import app.services.hrms_analytics_service as A

    now = datetime.now(timezone.utc)
    postings = FakeCollection([
        {"posting_code": "JP1", "company_id": CO, "request_no": "HR-REQ-1", "title": "Accountant"},
        {"posting_code": "JP2", "company_id": CO, "request_no": "HR-REQ-2", "title": "Designer"},
    ])
    views = ViewsCollection()
    cands = FakeCollection([
        {"uk": "C1", "company_id": CO, "posting_code": "JP1", "source_platform": "naukri", "applied_at": now},
        {"uk": "C2", "company_id": CO, "posting_code": "JP1", "source_platform": "naukri", "applied_at": now},
        {"uk": "C3", "company_id": CO, "posting_code": "JP1", "source_platform": "linkedin", "applied_at": now},
        {"uk": "C4", "company_id": CO, "posting_code": "JP2", "source_platform": None, "applied_at": now},
        {"uk": "C5", "company_id": CO, "posting_code": "JP1", "source_platform": "naukri",
         "applied_at": now - timedelta(days=400)},
    ])
    store = {M.COLL_JOB_POSTINGS: postings, M.COLL_POSTING_VIEWS: views, M.COLL_CANDIDATES: cands}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())
    R.get_collection = A.get_collection = mongo.get_collection

    async def scope(actor, company_id):
        return {"company_id": company_id}
    A._scope = scope
    HR = {"_id": "hr", "role": "staff", "_source_collection": "staff", "governance_role": "HR"}
    try:
        section("Recording views")
        for i in range(10):
            await R.record_view("JP1", "naukri", f"10.0.0.{i}", "Chrome")
        await R.record_view("JP1", "naukri", "10.0.0.1", "Chrome")      # refresh, same day
        for i in range(20):
            await R.record_view("JP1", "LinkedIn", f"10.1.0.{i}", "Chrome")
        await R.record_view("JP2", "", "10.2.0.1", "Chrome")
        await R.record_view("JP2", "nokri", "10.2.0.2", "Chrome")        # typo'd link
        await R.record_view("NOPE", "naukri", "10.9.9.9", "Chrome")      # unknown posting
        check("a refresh by the same visitor on the same day is not a second view",
              len([v for v in views.docs if v["platform"] == "naukri"]) == 10)
        check("the refresh is still counted as a hit on the same row",
              next(v for v in views.docs if v["visitor"] == R._visitor("10.0.0.1", "Chrome")
                   and v["platform"] == "naukri")["hits"] == 2)
        check("the label spelling (LinkedIn) is stored as its key", any(v["platform"] == "linkedin" for v in views.docs))
        check("a blank or unknown ?src= is counted as untagged",
              len([v for v in views.docs if v["platform"] == R.UNTAGGED]) == 2)
        check("no raw IP is stored", not any("10.0.0.1" in str(v) for v in views.docs))
        check("an unknown posting records nothing", not any(v["posting_code"] == "NOPE" for v in views.docs))

        section("Report")
        r = await R.reach_analytics(HR, CO)
        by = {x["platform"]: x for x in r["platforms"]}
        check("Naukri: reach 10, 2 applications, 20% conversion",
              (by["naukri"]["reach"], by["naukri"]["applications"], by["naukri"]["conversion_rate"]) == (10, 2, 20.0))
        check("LinkedIn: reach 20, 1 application, 5% conversion",
              (by["linkedin"]["reach"], by["linkedin"]["applications"], by["linkedin"]["conversion_rate"]) == (20, 1, 5.0))
        check("an application from before the window is not counted", r["totals"]["applications"] == 4)
        check("an application without a tracked link lands in Untagged", by[R.UNTAGGED]["applications"] == 1)
        check("the untagged row has no conversion rate", by[R.UNTAGGED]["conversion_rate"] is None)
        check("overall conversion counts tracked links only: 3 of 30 = 10%",
              (r["totals"]["tracked_applications"], r["totals"]["conversion_rate"]) == (3, 10.0))
        check("most reach: LinkedIn", r["most_reach"]["label"] == "LinkedIn")
        check("most applications: Naukri", r["most_applications"]["label"] == "Naukri")
        check("best conversion: Naukri (20%)", r["best_conversion"]["label"] == "Naukri")
        check("sorted by reach", r["platforms"][0]["platform"] == "linkedin")
        check("the posting filter lists both postings with titles",
              {p["posting_code"]: p["title"] for p in r["postings"]} == {"JP1": "Accountant", "JP2": "Designer"})
        one = await R.reach_analytics(HR, CO, posting_code="JP2")
        check("filtering to one posting narrows views and applications",
              one["totals"] == {"views": 2, "reach": 2, "applications": 1,
                                "tracked_applications": 0, "conversion_rate": None})
        check("the weekly trend adds up to the views",
              sum(sum(p["counts"].values()) for p in r["trend"]) == r["totals"]["views"])

        section("Platform keys")
        check("normalise_platform accepts keys and labels, rejects the rest",
              (M.normalise_platform("NAUKRI"), M.normalise_platform("Company Website"),
               M.normalise_platform("nokri"), M.normalise_platform(None)) == ("naukri", "website", None, None))
        check("the public apply model accepts src",
              M.PublicApplicationIn.model_fields.get("src") is not None)
    finally:
        mongo.get_collection = original

    passed = sum(RESULTS)
    print(f"\n=== {passed}/{len(RESULTS)} checks passed ===")
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
