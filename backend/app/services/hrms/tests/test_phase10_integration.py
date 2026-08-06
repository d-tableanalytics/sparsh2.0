"""Phase 10 integration harness -- analytics and reports over HTTP.

Focus: the capability gates, the entity/breakdown allow-lists reaching the router as enums
(so an unknown value is refused by FastAPI before any service code runs), tenant pinning,
export headers, and the read-only promise.

Run:  python -m app.services.hrms.tests.test_phase10_integration   (from backend/)
"""
from __future__ import annotations

from fastapi.testclient import TestClient

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


COMPANY = "C1"
OTHER = "C2"


def main() -> None:
    import main as app_main
    from app.controllers.auth_controller import get_current_user
    from app.utils import hrms_access as A
    import app.routes.hrms as R

    app = app_main.app

    async def fake_enabled(company_id):
        return company_id in (COMPANY, OTHER)

    A.is_hrms_enabled = fake_enabled

    seen = {}

    async def fake_dashboard(actor, company_id, **kw):
        seen["dashboard"] = (company_id, kw)
        return {"kpis": [], "range": {"from": "2026-01-01", "to": "2026-03-01"},
                "positions": {}, "offer_outcomes": {}, "onboarding_states": {},
                "time_to_hire": {}, "scoped_to_own_requisitions": False}

    async def fake_funnel(actor, company_id, **kw):
        seen["funnel"] = (company_id, kw)
        return {"total": 0, "stages": [], "lost": {}, "unranked": 0,
                "range": {"from": "2026-01-01", "to": "2026-03-01"}}

    async def fake_breakdown(actor, company_id, by, **kw):
        seen["breakdown"] = (company_id, by, kw)
        return {"by": by, "rows": [], "total": 0, "label": by, "truncated": False,
                "range": {"from": "2026-01-01", "to": "2026-03-01"}}

    async def fake_report(actor, company_id, entity, **kw):
        seen["report"] = (company_id, entity, kw)
        return {"entity": entity, "columns": [], "rows": [], "total": 0, "page": 1,
                "page_size": 25, "pages": 0, "salary_visible": True,
                "scoped_to_own_requisitions": False,
                "range": {"from": "2026-01-01", "to": "2026-03-01"}}

    async def fake_export(actor, company_id, entity, **kw):
        seen["export"] = (company_id, entity, kw)
        return {"entity": entity,
                "columns": [("uk", "Candidate ID"), ("candidate_name", "Name")],
                "rows": [["CAN-01", "Asha"], ["CAN-02", "Ben"]],
                "total": 9, "returned": 2, "truncated": True,
                "range": ("2026-01-01", "2026-03-01")}

    R.analytics.dashboard = fake_dashboard
    R.analytics.funnel = fake_funnel
    R.analytics.breakdown = fake_breakdown
    R.analytics.report = fake_report
    R.analytics.export_rows = fake_export

    INTERNAL = {"_id": "st", "role": "admin", "_source_collection": "staff"}
    MD = {"_id": "md", "role": "clientadmin", "_source_collection": "learners",
          "company_id": COMPANY}
    HR = {"_id": "hr", "role": "clientuser", "_source_collection": "learners",
          "company_id": COMPANY, "governance_role": "HR"}
    HOD = {"_id": "hod", "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "HOD"}
    EMP = {"_id": "emp", "role": "clientuser", "_source_collection": "learners",
           "company_id": COMPANY, "governance_role": "IMPLEMENTOR"}

    current = {"user": HR}
    app.dependency_overrides[get_current_user] = lambda: current["user"]

    def as_user(u):
        current["user"] = u

    client = TestClient(app)

    try:
        section("Capabilities via /health")
        for label, user in (("HR", HR), ("MD", MD), ("INTERNAL", INTERNAL)):
            as_user(user)
            caps = client.get("/api/hrms/health").json()["capabilities"]
            check(f"{label} has analytics.read, report.read and report.export",
                  all(c in caps for c in
                      ("analytics.read", "report.read", "report.export")))
        as_user(HOD)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("HOD has analytics.read", "analytics.read" in caps)
        check("HOD has report.read", "report.read" in caps)
        check("HOD LACKS report.export", "report.export" not in caps)
        as_user(EMP)
        caps = client.get("/api/hrms/health").json()["capabilities"]
        check("employee has no analytics or report capability",
              not any(c.startswith(("analytics.", "report.")) for c in caps))

        section("Capability gating per endpoint")
        as_user(EMP)
        for path in ("/api/hrms/analytics/dashboard", "/api/hrms/analytics/funnel",
                     "/api/hrms/analytics/breakdown", "/api/hrms/reports/candidates",
                     "/api/hrms/reports/candidates/export"):
            check(f"employee -> {path} 403", client.get(path).status_code == 403)
        as_user(HOD)
        check("HOD -> dashboard 200",
              client.get("/api/hrms/analytics/dashboard").status_code == 200)
        check("HOD -> funnel 200",
              client.get("/api/hrms/analytics/funnel").status_code == 200)
        check("HOD -> report 200",
              client.get("/api/hrms/reports/candidates").status_code == 200)
        check("HOD -> EXPORT 403 -- the whole point of the separate capability",
              client.get("/api/hrms/reports/candidates/export").status_code == 403)
        as_user(HR)
        check("HR -> export 200",
              client.get("/api/hrms/reports/candidates/export").status_code == 200)

        section("Allow-lists are enforced by the ROUTER, before any service code")
        as_user(HR)
        seen.pop("report", None)
        for bad in ("learners", "staff", "hrms_offers", "companies"):
            r = client.get(f"/api/hrms/reports/{bad}")
            check(f"entity '{bad}' refused ({r.status_code})",
                  r.status_code in (404, 422))
        check("no rejected entity reached the service", "report" not in seen)
        seen.pop("breakdown", None)
        for bad in ("salary", "$where", "password", "company_id"):
            check(f"breakdown '{bad}' refused",
                  client.get("/api/hrms/analytics/breakdown",
                             params={"by": bad}).status_code == 422)
        check("no rejected breakdown reached the service", "breakdown" not in seen)
        for good in ("candidates", "requisitions", "interviews", "offers", "onboarding"):
            check(f"entity '{good}' accepted",
                  client.get(f"/api/hrms/reports/{good}").status_code == 200)
        for good in ("source", "department", "designation", "platform"):
            check(f"breakdown '{good}' accepted",
                  client.get("/api/hrms/analytics/breakdown",
                             params={"by": good}).status_code == 200)

        section("Route ordering -- /export must not be read as an entity")
        seen.pop("export", None)
        client.get("/api/hrms/reports/offers/export")
        check("/reports/{entity}/export reaches the exporter",
              seen.get("export", (None, None))[1] == "offers")

        section("Pagination bounds are enforced at the door")
        check("page 0 -> 422", client.get("/api/hrms/reports/candidates",
                                          params={"page": 0}).status_code == 422)
        check("negative page -> 422",
              client.get("/api/hrms/reports/candidates",
                         params={"page": -1}).status_code == 422)
        check("page_size above the cap -> 422",
              client.get("/api/hrms/reports/candidates",
                         params={"page_size": 101}).status_code == 422)
        check("page_size 0 -> 422",
              client.get("/api/hrms/reports/candidates",
                         params={"page_size": 0}).status_code == 422)
        check("page_size at the cap is accepted",
              client.get("/api/hrms/reports/candidates",
                         params={"page_size": 100}).status_code == 200)

        section("Tenant pinning")
        as_user(HR)
        client.get("/api/hrms/analytics/dashboard", params={"company_id": OTHER})
        check("a client cannot retarget the dashboard",
              seen["dashboard"][0] == COMPANY)
        client.get("/api/hrms/analytics/funnel", params={"company_id": OTHER})
        check("...nor the funnel", seen["funnel"][0] == COMPANY)
        client.get("/api/hrms/reports/candidates", params={"company_id": OTHER})
        check("...nor a report", seen["report"][0] == COMPANY)
        client.get("/api/hrms/reports/candidates/export", params={"company_id": OTHER})
        check("...nor an export", seen["export"][0] == COMPANY)
        as_user(INTERNAL)
        client.get("/api/hrms/analytics/dashboard", params={"company_id": OTHER})
        check("internal may target a company", seen["dashboard"][0] == OTHER)
        check("internal without a company -> 400",
              client.get("/api/hrms/analytics/dashboard").status_code == 400)

        section("Query parameters reach the service intact")
        as_user(HR)
        client.get("/api/hrms/reports/candidates",
                   params={"page": 3, "page_size": 10, "search": "asha",
                           "date_from": "2026-01-01", "date_to": "2026-02-01"})
        kw = seen["report"][2]
        check("page forwarded", kw["page"] == 3)
        check("page_size forwarded", kw["page_size"] == 10)
        check("search forwarded", kw["search"] == "asha")
        check("date window forwarded",
              kw["date_from"] == "2026-01-01" and kw["date_to"] == "2026-02-01")

        section("Export response")
        r = client.get("/api/hrms/reports/candidates/export")
        check("defaults to CSV",
              r.headers["content-type"].startswith("text/csv"))
        check("served as an attachment",
              "attachment;" in r.headers["content-disposition"])
        check("filename carries entity and window",
              "hrms_candidates_2026-01-01_to_2026-03-01.csv"
              in r.headers["content-disposition"])
        check("truncation is announced in a header",
              r.headers["x-export-truncated"] == "true")
        check("row counts are announced",
              r.headers["x-export-rows"] == "2" and r.headers["x-export-total"] == "9")
        check("the body is the rendered CSV, BOM included",
              r.content.startswith(b"\xef\xbb\xbf") and b"Candidate ID" in r.content)
        check("the truncation note is inside the file too",
              b"truncated" in r.content.lower())

        rx = client.get("/api/hrms/reports/candidates/export", params={"fmt": "xlsx"})
        check("xlsx is served with the spreadsheet content type",
              "spreadsheetml" in rx.headers["content-type"])
        check("xlsx body is a real zip container", rx.content[:2] == b"PK")
        check("an unknown format -> 422",
              client.get("/api/hrms/reports/candidates/export",
                         params={"fmt": "pdf"}).status_code == 422)

        section("Analytics is READ-ONLY over HTTP")
        for method, path in (("post", "/api/hrms/analytics/dashboard"),
                             ("post", "/api/hrms/reports/candidates"),
                             ("patch", "/api/hrms/analytics/funnel"),
                             ("delete", "/api/hrms/reports/candidates"),
                             ("put", "/api/hrms/analytics/breakdown")):
            check(f"{method.upper()} {path} -> 405",
                  getattr(client, method)(path).status_code == 405)

        section("SWEEP: nothing new is public")
        app.dependency_overrides.pop(get_current_user, None)
        intended_prefixes = ("/api/hrms/public/", "/api/auth/")
        intended_exact = {"/api/assistant/health", "/api/assistant/ready"}
        leaked, checked = [], 0
        for route in app.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set()) or set()
            if "GET" not in methods or "{" in path or not path.startswith("/api/"):
                continue
            if any(path.startswith(p) for p in intended_prefixes) or path in intended_exact:
                continue
            checked += 1
            if client.get(path).status_code not in (401, 403, 404, 405, 422):
                leaked.append(path)
        check(f"swept {checked} authenticated GET routes", checked > 20)
        check("no authenticated route answers without a token", not leaked)
        for path in ("/api/hrms/analytics/dashboard", "/api/hrms/analytics/funnel",
                     "/api/hrms/analytics/breakdown", "/api/hrms/reports/candidates",
                     "/api/hrms/reports/candidates/export"):
            check(f"{path} -> 401 without a token", client.get(path).status_code == 401)

        section("Regression -- earlier phases intact")
        for path in ("/api/hrms/health", "/api/hrms/onboarding", "/api/hrms/offers",
                     "/api/hrms/interviews", "/api/hrms/assessments",
                     "/api/hrms/candidates", "/api/hrms/employees",
                     "/api/hrms/requisitions", "/api/hrms/postings"):
            check(f"{path} -> 401 without a token", client.get(path).status_code == 401)
        for path in ("/api/hrms/public/apply/ZZ-ZZZZZZ",
                     "/api/hrms/public/assess/" + "A" * 22,
                     "/api/hrms/public/offer/" + "A" * 22,
                     "/api/hrms/public/onboard/" + "A" * 22):
            check(f"{path} still anonymous",
                  client.get(path).status_code not in (401, 403))
        check("API root still 200", client.get("/").status_code == 200)
        for path in ("/api/tasks", "/api/users/me", "/api/tpms/activities",
                     "/api/holidays", "/api/reports/overview"):
            check(f"{path} still protected", client.get(path).status_code == 401)
    finally:
        app.dependency_overrides.clear()

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
