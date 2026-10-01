"""Internal hiring > Job Portal Reach.

How much reach each job portal / platform generates for Sparsh Magic's own postings.

HR shares a posting through one TRACKED link per platform -- the same apply link with
`?src=naukri`, `?src=linkedin`, ... When somebody opens it, the public job-ad handler calls
`record_view`; when they apply, the application keeps the platform (`source_platform`). The
report then answers, per platform: how many people reached the job page, how many applied,
and the conversion between the two.

What "reach" means, honestly: people who OPENED our job page from that platform. Views of
the ad on the portal itself (a Naukri impression) never reach this server, so they are not
counted -- the page says so.

Privacy: a visitor is a salted hash of IP + browser, never the IP itself, and only one row
is kept per visitor per posting per platform per day (a refresh is not a second view).
"""
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config.settings import settings
from app.db.mongodb import get_collection
from app.models.hrms import (
    COLL_CANDIDATES, COLL_JOB_POSTINGS, COLL_POSTING_VIEWS, JOB_PLATFORM_LABEL, JOB_PLATFORMS,
    normalise_platform,
)

SCAN_CAP = 50000
UNTAGGED = "untagged"
UNTAGGED_LABEL = "Untagged link"
# A conversion rate from a handful of visitors is noise; below this it is not "the best".
MIN_REACH_FOR_BEST = 5


def _visitor(ip: str, user_agent: str) -> str:
    raw = f"{settings.SECRET_KEY}|reach|{ip or ''}|{(user_agent or '')[:300]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


async def record_view(code: str, src: Optional[str], ip: str, user_agent: str) -> None:
    """Count one visit to a posting's job page, per platform. Never raises: tracking must
    never cost an applicant the page."""
    try:
        posting = await get_collection(COLL_JOB_POSTINGS).find_one(
            {"posting_code": code}, {"company_id": 1, "request_no": 1})
        if not posting:
            return
        now = datetime.now(timezone.utc)
        platform = normalise_platform(src) or UNTAGGED
        await get_collection(COLL_POSTING_VIEWS).update_one(
            {"posting_code": code, "platform": platform,
             "visitor": _visitor(ip, user_agent), "day": now.strftime("%Y-%m-%d")},
            {"$setOnInsert": {"company_id": str(posting.get("company_id")),
                              "request_no": posting.get("request_no"), "first_at": now},
             "$set": {"last_at": now}, "$inc": {"hits": 1}},
            upsert=True)
    except Exception:  # noqa: BLE001 -- best effort by design
        return


def _label(platform: str) -> str:
    return UNTAGGED_LABEL if platform == UNTAGGED else JOB_PLATFORM_LABEL.get(platform, platform)


def _week(day: str):
    d = datetime.strptime(day, "%Y-%m-%d").date()
    return d - timedelta(days=d.weekday())


async def reach_analytics(actor: dict, company_id: str, *, date_from: str = None,
                          date_to: str = None, posting_code: str = None) -> dict:
    from app.services.hrms_analytics_service import _scope, _window, parse_range
    from app.utils.hrms_access import hrms_role
    from app.models.hrms import HrmsRole

    start, end = parse_range(date_from, date_to)
    scope = await _scope(actor, company_id)
    d0, d1 = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    vq = {**scope, "day": {"$gte": d0, "$lte": d1}}
    cq = {**scope, **_window("applied_at", start, end), "posting_code": {"$nin": [None, ""]}}
    if posting_code:
        vq["posting_code"] = cq["posting_code"] = posting_code
    views = await get_collection(COLL_POSTING_VIEWS).find(
        vq, {"platform": 1, "visitor": 1, "day": 1, "posting_code": 1}).to_list(SCAN_CAP)
    cands = await get_collection(COLL_CANDIDATES).find(
        cq, {"source_platform": 1, "posting_code": 1}).to_list(SCAN_CAP)

    rows = {}

    def row(p):
        return rows.setdefault(p, {"platform": p, "label": _label(p), "views": 0,
                                   "_visitors": set(), "applications": 0})

    weeks = {}
    w, last = _week(d0), _week(d1)
    while w <= last:
        weeks[w] = {}
        w += timedelta(days=7)
    for v in views:
        r = row(v.get("platform") or UNTAGGED)
        r["views"] += 1
        r["_visitors"].add(v.get("visitor"))
        bucket = weeks.setdefault(_week(v["day"]), {})
        bucket[r["label"]] = bucket.get(r["label"], 0) + 1
    for c in cands:
        row(normalise_platform(c.get("source_platform")) or UNTAGGED)["applications"] += 1

    order = {p: i for i, (p, _) in enumerate(JOB_PLATFORMS)}
    out = []
    for r in rows.values():
        reach = len(r.pop("_visitors"))
        # No rate for the untagged row: its applications include everything from before
        # tracked links existed, so dividing them by today's plain-link visits means nothing.
        out.append({**r, "reach": reach,
                    "conversion_rate": (round(100 * r["applications"] / reach, 1)
                                        if reach and r["platform"] != UNTAGGED else None)})
    out.sort(key=lambda x: (-x["reach"], -x["applications"], order.get(x["platform"], 99)))

    tagged = [x for x in out if x["platform"] != UNTAGGED]
    most_reach = max(tagged, key=lambda x: x["reach"], default=None)
    most_apps = max(tagged, key=lambda x: x["applications"], default=None)
    rated = [x for x in tagged if x["reach"] >= MIN_REACH_FOR_BEST and x["conversion_rate"]]
    best = max(rated, key=lambda x: (x["conversion_rate"], x["reach"]), default=None)

    codes = sorted({v["posting_code"] for v in views} | {c["posting_code"] for c in cands})
    titles = {p["posting_code"]: p.get("title") for p in await get_collection(COLL_JOB_POSTINGS).find(
        {"posting_code": {"$in": codes}}, {"posting_code": 1, "title": 1}).to_list(len(codes) or 1)}

    totals = {"views": sum(x["views"] for x in out), "reach": sum(x["reach"] for x in out),
              "applications": sum(x["applications"] for x in out)}
    # Overall conversion is tracked traffic only -- the same reason as the untagged row.
    t_reach = sum(x["reach"] for x in tagged)
    t_apps = sum(x["applications"] for x in tagged)
    totals["tracked_applications"] = t_apps
    totals["conversion_rate"] = round(100 * t_apps / t_reach, 1) if t_reach else None
    return {
        "range": {"from": d0, "to": d1},
        "scoped_to_own_requisitions": hrms_role(actor) == HrmsRole.MANAGER,
        "platforms": out, "totals": totals,
        "most_reach": most_reach and {"label": most_reach["label"], "reach": most_reach["reach"]},
        "most_applications": most_apps and most_apps["applications"] and {
            "label": most_apps["label"], "applications": most_apps["applications"]} or None,
        "best_conversion": best and {"label": best["label"], "conversion_rate": best["conversion_rate"],
                                     "applications": best["applications"], "reach": best["reach"]},
        "min_reach_for_best": MIN_REACH_FOR_BEST,
        "postings": [{"posting_code": c, "title": titles.get(c)} for c in codes],
        "trend": [{"label": k.strftime("%d %b"), "counts": weeks[k]} for k in sorted(weeks)],
        "platform_catalogue": [{"key": k, "label": lbl} for k, lbl in JOB_PLATFORMS],
    }
