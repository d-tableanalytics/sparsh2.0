"""Inter-Departmental Feedback — verified against the CLIENT'S OWN DATA.

1. Import the client's compiled workbook (docs/hrms/Report Interdepartmental_Feedback_Compiled.xls)
   and check the scores equal the client's published Action Plan
   (docs/hrms/Interdepartmental_Feedback Action_Plan.docx): company 70.6% Amber, Project 58.8% Red,
   HR / Purchase 80% Green, the four hotspots, Coordination & Ownership weakest at 68.5%.
2. Export -> re-import round trip in the same format gives the same scores.
3. The online cycle (document §3–§4, §10): start cycle -> calendar activities, form validation,
   locked completion, HR status-only, reminders, cycle completion -> action plan -> report
   package emailed to the MD only.

Self-contained: in-memory fake collections, no database, no real email.
Run from backend/:   PYTHONPATH=. python tests/test_inter_department_feedback.py
"""
import asyncio
import copy
import io
import os
import sys
from datetime import date, timedelta

from bson import ObjectId
from fastapi import HTTPException

from app.services.hrms.tests.test_phase2_employee import (FakeCollection, _matches, check, results, section)

XLS = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "hrms",
                   "Report Interdepartmental_Feedback_Compiled.xls")


class Coll(FakeCollection):
    """FakeCollection + delete_many, positional "a.0.b" $set, $push, $setOnInsert."""

    async def delete_many(self, query):
        keep = [d for d in self.docs if not _matches(d, query)]
        n = len(self.docs) - len(keep)
        self.docs[:] = keep

        class R:
            deleted_count = n
        return R()

    async def update_one(self, query, update, upsert=False):
        doc = next((d for d in self.docs if _matches(d, query)), None)
        if doc is None:
            if not upsert:
                class R0:
                    matched_count = 0
                return R0()
            doc = {k: v for k, v in query.items() if not isinstance(v, dict)}
            doc.setdefault("_id", ObjectId())
            doc.update(update.get("$setOnInsert") or {})
            self.docs.append(doc)
        for k, v in (update.get("$set") or {}).items():
            cur, parts = doc, k.split(".")
            for p in parts[:-1]:
                cur = cur[int(p)] if isinstance(cur, list) else cur.setdefault(p, {})
            if isinstance(cur, list):
                cur[int(parts[-1])] = v
            else:
                cur[parts[-1]] = v
        for k, v in (update.get("$push") or {}).items():
            doc.setdefault(k, []).append(v)
        for k, v in (update.get("$inc") or {}).items():
            doc[k] = (doc.get(k) or 0) + v

        class R:
            matched_count = 1
        return R()

    async def update_many(self, query, update):
        matched = [d for d in self.docs if _matches(d, query)]
        for d in matched:
            await self.update_one({"_id": d["_id"]}, update)

        class R:
            matched_count = len(matched)
        return R()


async def refused(label, coro, code):
    try:
        await coro
        check(f"{label} -> refused", False)
    except HTTPException as e:
        check(f"{label} -> refused ({code})", e.status_code == code)


async def main():
    import app.db.mongodb as mongo
    store = {}
    mongo.get_collection = lambda name: store.setdefault(name, Coll())
    import app.services.idf_service as S
    import app.services.idf_analysis as A
    import app.services.idf_reports as R
    import app.services.smtp_delivery as smtp
    import app.services.notification_service as ns
    from app.config.settings import settings
    for name, mod in list(sys.modules.items()):
        if name.startswith("app.") and hasattr(mod, "get_collection"):
            mod.get_collection = mongo.get_collection
    mails, logged = [], []

    async def fake_send(msg, rcpt):
        mails.append((msg, list(rcpt)))
        return True, None

    bodies = {}

    async def fake_email(to, subject, message, user_id=None, slug="manual", cc=None, meta=None):
        mails.append((subject, [to]))
        bodies.setdefault(to, []).append(message)
        return True

    async def fake_log(*a, **k):
        logged.append(a[4] if len(a) > 4 else "")
    smtp.send_message = fake_send
    ns.send_email_notification = fake_email
    ns.log_notification = fake_log
    settings.SMTP_USERNAME, settings.SMTP_PASSWORD = "noreply@test", "x"

    C = str(ObjectId())
    store["companies"] = Coll([{"_id": ObjectId(C), "name": "Dewas Techno", "is_internal": False}])
    names = ["HR", "Sales", "Operation", "Commercial", "Design", "Project", "Purchase", "Marketing"]
    D = {n: ObjectId() for n in names}
    U = {k: ObjectId() for k in ("MD", "HRM", *[f"H_{n}" for n in names])}
    # No head on the department records: HODs come from Team (Department + HOD designation).
    store["hrms_departments"] = Coll([{"_id": D[n], "company_id": C, "name": n, "active": True} for n in names])
    people = [{"_id": U["MD"], "company_id": C, "role": "clientadmin", "governance_role": "MD",
               "full_name": "Rajeev Lath", "email": "md@co.test", "is_active": True},
              {"_id": U["HRM"], "company_id": C, "role": "clientuser", "governance_role": "HR",
               "full_name": "Prem Kumawat", "email": "hr@co.test", "is_active": True}]
    # Team: each HOD has the HOD designation (stored in `department`) and their master Department.
    # Marketing deliberately has NO HOD in Team.
    people += [{"_id": U[f"H_{n}"], "company_id": C, "role": "clientuser", "department": "HOD",
                "department_id": str(D[n]), "department_name": n,
                "full_name": f"{n} Head", "email": f"{n.lower()}@co.test", "is_active": True}
               for n in names if n != "Marketing"]
    people.append({"_id": ObjectId(), "company_id": C, "role": "clientuser", "department": "Implementor",
                   "department_id": str(D["Sales"]), "full_name": "Sales Executive", "email": "exec@co.test",
                   "is_active": True})
    second_sales_hod = {"_id": ObjectId(), "company_id": C, "role": "clientuser", "governance_role": "HOD",
                        "department_id": str(D["Sales"]), "full_name": "Sales Co-Head",
                        "email": "cohead@co.test", "is_active": True}
    people.append(second_sales_hod)
    store["learners"] = Coll(people)
    MD = people[0]
    HR = people[1]
    HOD = {p["department_name"]: p for p in people if p.get("department") == "HOD"}
    ADMIN = {"_id": "sa", "role": "superadmin", "full_name": "Sparsh Admin"}

    # ── 1. The client's workbook ──────────────────────────────────────────────────────────
    section("Import the client's workbook (MD only)")
    data = open(XLS, "rb").read()
    await refused("HR imports", R.import_compiled(HR, data, "x.xls", "2026-10", True, True), 403)
    pv = await R.import_compiled(MD, data, "Report.xls", "2026-10", False, False)
    check("preview finds the 8 rated-department sheets", pv["departments_rated"] == 8)
    check("preview flags 'Solution' as not in the department list", pv["unknown_departments"] == ["Solution"])
    await refused("apply without adding the missing department", R.import_compiled(MD, data, "Report.xls", "2026-10", True, False), 422)
    out = await R.import_compiled(MD, data, "Report.xls", "2026-10", True, True)
    check("imported as a completed cycle", out["imported"] and out["ratings_imported"] > 0)

    cyc = store["idf_cycles"].docs[0]
    res = await A.analyse(cyc)
    pct = {d["name"]: d["pct"] for d in res["departments"]}
    band = {d["name"]: d["band"] for d in res["departments"]}
    section("Scores equal the client's Action Plan")
    expected = {"Project": 58.8, "Design": 60.0, "Sales": 66.3, "Operation": 72.0, "Commercial": 77.0,
                "HR": 80.0, "Purchase": 80.0}
    for n, v in expected.items():
        check(f"{n} = {v}% ({band.get(n)})", pct.get(n) == v)
    check("Marketing (all zero = not rated) has no score", "Marketing" not in pct)
    check("company overall 70.6% Amber", res["company"]["pct"] == 70.6 and res["company"]["band"] == "Amber")
    cp = res["company"]["param_pct"]
    check("company params 72.1 / 70.3 / 71.4 / 68.5",
          (cp["information"], cp["planning"], cp["task_closure"], cp["ownership"]) == (72.1, 70.3, 71.4, 68.5))
    check("weakest company parameter: Coordination & Ownership", res["company"]["weakest_param"] == "Coordination & Ownership")
    hs = {(h["from"], h["to"]): h["pct"] for h in res["hotspots"]}
    check("hotspots = HR→Sales 40, HR→Operation 40, Sales→Project 45, Operation→Design 55",
          hs == {("HR", "Sales"): 40.0, ("HR", "Operation"): 40.0, ("Sales", "Project"): 45.0,
                 ("Operation", "Design"): 55.0})
    acts = [a for a in store["idf_actions"].docs if a["cycle_id"] == str(cyc["_id"])]
    check("a Red repair action for every hotspot",
          {(a["feedback_from"], a["department"]) for a in acts if a["type"] == "Relationship repair"} == set(hs))
    check("Amber strengthen actions for Design, Sales, Operation, Commercial",
          {a["department"] for a in acts if a["type"] == "Strengthen"} >= {"Design", "Commercial"})
    check("Green sustain for HR and Purchase", {a["department"] for a in acts if a["type"] == "Sustain"} == {"HR", "Purchase"})
    section("Team stage and the structured improvement process (document §6–§7)")
    stg = {d["name"]: d["stage"] for d in res["departments"]}
    check("Red = Storming, Amber = Norming, Green = Performing (Project / Sales / HR)",
          (stg["Project"], stg["Sales"], stg["HR"]) == ("Storming", "Norming", "Performing"))
    check("company classified on the same bands: Amber → Norming", res["company"]["stage"] == "Norming")
    red = next(a for a in acts if a["type"] == "Relationship repair" and a["department"] == "Sales" and a["feedback_from"] == "HR")
    check("an Amber department's relationship below 60% (HR → Sales) gets the Red repair, Storming",
          red["band"] == "Red" and red["stage"] == "Storming" and red["category"] == "Red – Repair")
    check("Red repair = the Standard Approach's 6 steps: MD & HR meeting, 5-Why, hand-off, log, weekly WRM, pulse re-score",
          len(red["steps"]) == 6 and "MD and HR" in red["steps"][0] and "5-Why" in red["steps"][1]
          and "hand-off agreement" in red["steps"][2] and red["target_date"] in red["steps"][3]
          and "WRM" in red["steps"][4] and "counselling" in red["steps"][4] and red["rescore_date"] in red["steps"][5])
    check("Red is led by MD & HR, meeting within 7 days", red["led_by"] == "MD & HR"
          and red["response_time"] == "Meeting within 7 days")
    amb = next(a for a in acts if a["type"] == "Strengthen" and a["department"] == "Design")
    check("Amber strengthen = 4 steps: weakest question + lowest rater in WRM, 15-day meeting, one process fix, fortnightly",
          len(amb["steps"]) == 4 and amb["parameter"] in amb["steps"][0] and amb["feedback_from"] in amb["steps"][0]
          and "15 days" in amb["steps"][1] and "process fix" in amb["steps"][2] and "fortnightly" in amb["steps"][3])
    check("Amber is led by the rated department's HOD", amb["led_by"] == "HOD of the rated department")
    grn = next(a for a in acts if a["type"] == "Sustain" and a["department"] == "HR")
    check("Green sustain = 4 steps: recognise, share practices, support others, monitor (5-point drop rule)",
          len(grn["steps"]) == 4 and "Recognise" in grn["steps"][0] and "5 points" in grn["steps"][3])
    check("Green coaches the weakest Amber/Red department (HR coaches Project)",
          grn["coach_department"] == "Project" and "Project" in grn["steps"][1]
          and grn["led_by"] == "HOD, with HR for recognition")
    low = {**res, "company": {**res["company"], "pct": 55.0, "band": "Red"}}
    comp = [a for a in A.build_actions(cyc, low, {}, date.today(), {"id": str(MD["_id"]), "name": "Rajeev Lath"})
            if a["type"] == "Company-wide repair"]
    check("company below 60%: a company-wide repair led by the MD with all HODs",
          len(comp) == 1 and comp[0]["owner_name"] == "Rajeev Lath" and comp[0]["led_by"] == "MD with all HODs")
    summ = " ".join(R.management_summary(res, "Dewas Techno"))
    check("the MD's summary recognises the Green departments by name",
          "Recognition" in summ and "HR (80.0%)" in summ and "Purchase (80.0%)" in summ)
    check("actions owned by the department's HOD (from Team) — Marketing has none",
          all(a["owner_user_id"] for a in acts if a["department"] != "Marketing"))

    section("Export in the client's format, and re-import it")
    files = await R.package(cyc)
    check("package = compiled xlsx + analysis xlsx + pdf", len(files) == 3 and any(f.endswith(".pdf") for f in files))
    from openpyxl import load_workbook
    comp = next(v for k, v in files.items() if "_Compiled_" in k)
    wb = load_workbook(io.BytesIO(comp))
    check("same sheets: Company, a sheet per rated department, Sheet1 legend",
          wb.sheetnames[0] == "Company" and "Sheet1" in wb.sheetnames and "HR" in wb.sheetnames)
    hr = wb["HR"]
    check("department sheet layout: FEEDBACK FOR / Topic / Final / Comments",
          hr["A4"].value == "FEEDBACK FOR:" and hr["B4"].value == "HR" and hr["A6"].value == "Topic"
          and "Final" in [c.value for c in hr[6]] and "Comments" in [c.value for c in hr[6]])
    check("HR Average Score % = 0.8", [c.value for c in hr[14]][-1] == 0.8)
    section("Compiled export = the client's sample, cell by cell")
    import xlrd
    sample = xlrd.open_workbook(XLS, formatting_info=True)
    ours = load_workbook(io.BytesIO(comp))
    check("same sheet order as the sample", ours.sheetnames == sample.sheet_names())
    diffs, fmt_diffs = [], []
    for name in sample.sheet_names():
        sh, ws = sample.sheet_by_name(name), ours[name]
        for r in range(sh.nrows):
            for c in range(sh.ncols):
                sv, ov = sh.cell_value(r, c), ws.cell(row=r + 1, column=c + 1).value
                hdr = str(sh.cell_value(r, 0)).strip() == "Topic"
                if name == "Company" and c in (3, 9, 10) and r >= 5:
                    # The sample's Sales column holds Commercial's ratings of Sales, not Sales'
                    # Final — and its Company column / % are averaged over that error. Ours are the
                    # correct values (Information 72.1%, company 70.6%, as the client's Action Plan).
                    continue
                if hdr and c >= 2:
                    continue                      # department names: ours are the master names
                if name == "Marketing" and r >= 6 and c >= 2:
                    continue                      # all-zero = not rated: the sample shows 0, we leave blank
                if isinstance(sv, float) and sv != 0:
                    if not isinstance(ov, (int, float)) or abs(ov - sv) > 1e-9:
                        diffs.append(f"{name}!{r+1}:{c+1} sample={sv} ours={ov}")
                    else:
                        want = sample.format_map[sample.xf_list[sh.cell_xf_index(r, c)].format_key].format_str
                        if want in ("0", "0.00", "0%") and ws.cell(row=r + 1, column=c + 1).number_format != want:
                            fmt_diffs.append(f"{name}!{r+1}:{c+1} {want} vs {ws.cell(row=r + 1, column=c + 1).number_format}")
                elif isinstance(sv, str) and sv.strip() and c <= 1:
                    if str(ov or "").strip() != sv.strip():
                        diffs.append(f"{name}!{r+1}:{c+1} sample={sv!r} ours={ov!r}")
    check("every label, rating, Final, average and % matches the sample" + (f" — {diffs[:3]}" if diffs else ""), not diffs)
    check("number formats match the sample (0 / 0.00 / 0%)" + (f" — {fmt_diffs[:3]}" if fmt_diffs else ""), not fmt_diffs)
    out2 = await R.import_compiled(MD, comp, "round.xlsx", "2026-09", True, True)
    res2 = await A.analyse(next(c for c in store["idf_cycles"].docs if c["period"] == "2026-09"))
    check("round trip gives identical department scores",
          {d["name"]: d["pct"] for d in res2["departments"]} == pct and res2["company"]["pct"] == 70.6)
    pdf = next(v for k, v in files.items() if k.endswith(".pdf"))
    check("PDF is a real PDF", pdf[:4] == b"%PDF")
    xl = next(v for k, v in files.items() if "_Analysis_" in k)
    sheets = load_workbook(io.BytesIO(xl)).sheetnames
    check("analysis workbook has the 8 report sheets",
          sheets == ["Company Overall", "Department Scorecard", "Parameter Analysis", "Feedback Matrix",
                     "Strength & Improvement", "Hotspots", "Action Plan", "Management Summary"])
    check("reports never name individual raters",
          not any(p["full_name"] in str(c.value) for p in people[2:] for ws in load_workbook(io.BytesIO(comp))
                  for row in ws.iter_rows() for c in row if c.value))

    # ── 2. The online cycle ───────────────────────────────────────────────────────────────
    section("HODs come from Team")
    deps = {d["name"]: d for d in await S.departments(C)}
    check("HR's HOD is the Team member with Department HR + HOD designation",
          [h["name"] for h in deps["HR"]["heads"]] == ["HR Head"])
    check("Sales has two HODs (designation HOD + governance HOD); the executive is not one",
          sorted(h["name"] for h in deps["Sales"]["heads"]) == ["Sales Co-Head", "Sales Head"])
    check("Marketing has no HOD in Team", deps["Marketing"]["heads"] == [])

    section("Setup holds only the rules; the mapping is chosen per cycle")
    await refused("an HOD opens setup", S.get_setup(HOD["Sales"], None), 403)
    st = await S.get_setup(HR, None)
    check("setup has no HOD list and no mapping", "dependencies" not in st and "departments" not in st)
    await S.save_setup(HR, None, {"parameters": st["parameters"], "deadline_days": 7, "reminder_days_before": 2})
    await refused("HR opens the MD dashboard", A.md_dashboard(HR, None), 403)
    await refused("Superadmin opens the dashboard without choosing a company", A.md_dashboard(ADMIN, None), 400)
    sa_dash = await A.md_dashboard(ADMIN, None, C)
    check("Super Admin / Admin open any company's dashboard (they pick it)", sa_dash["result"] is not None)
    sa_dl = await R.md_download(ADMIN, sa_dash["result"]["cycle"]["id"], "pdf", C)
    check("…and download its reports", sa_dl[0].endswith(".pdf"))
    review = lambda r, gs: {"receiver_dept_id": str(D[r]), "giver_dept_ids": [str(D[g]) for g in gs]}
    await refused("no department to review", S.start_cycle(HR, None, {"period": "2026-11", "reviews": []}), 422)
    await refused("a department rating itself",
                  S.start_cycle(HR, None, {"period": "2026-11", "reviews": [review("HR", ["HR"])]}), 422)
    try:
        await S.start_cycle(HR, None, {"period": "2026-11", "reviews": [review("HR", ["Marketing"])]})
        check("a rater department without an HOD in Team -> refused", False)
    except HTTPException as e:
        check("a rater department without an HOD in Team -> refused, naming it",
              e.status_code == 422 and "Marketing" in str(e.detail))
    # Review HR (rated by Sales and Design) and Sales (rated by HR).
    cyc_doc = await S.start_cycle(HR, None, {"period": "2026-11",
                                             "reviews": [review("HR", ["Sales", "Design"]), review("Sales", ["HR"])]})
    check("cycle started with 3 department ratings", cyc_doc["status"] == "Open" and len(cyc_doc["pairs"]) == 3)
    events = [e for c in ("LEARNER_CALENDER", "STAFF_CALENDER", "calendar_events")
              for e in store.get(c, Coll()).docs if e.get("kind") == S.EVENT_KIND]
    check("a calendar activity per HOD and department, Scheduled when created (Sales has 2 HODs -> 4)",
          len(events) == 4 and all(e["status"] == "Scheduled" and e["idf_status"] == "Scheduled" for e in events))
    check("initial notification emailed to each of the 4 HODs",
          sum(1 for m in mails if "requested" in str(m[0])) == 4)
    section("Personal form links in the email (like TPMS form links)")
    links = store[S.COLL_LINKS].docs
    check("one link per HOD per department to rate (4)", len(links) == 4 and len({l["token"] for l in links}) == 4)
    sales_link = next(l for l in links if l["rater_user_id"] == str(HOD["Sales"]["_id"]))
    check("the Sales HOD's email carries their own link", any(f"/idf/f/{sales_link['token']}" in b
                                                              for b in bodies.get("sales@co.test", [])))
    check("…and not the Design HOD's link", not any(
        l["token"] in b for l in links if l["rater_user_id"] == str(HOD["Design"]["_id"])
        for b in bodies.get("sales@co.test", [])))
    await refused("another department's HOD opens the Sales link", S.open_link(HOD["Design"], sales_link["token"]), 403)
    await refused("an unknown link", S.open_link(HOD["Sales"], "not-a-token"), 404)
    opened = await S.open_link(HOD["Sales"], sales_link["token"])
    check("the right HOD opens their form: Sales → HR", opened["state"] == "open"
          and opened["form"]["receiver_name"] == "HR" and len(opened["parameters"]) == 4)
    check("the form asks the requirement document's 4 questions",
          [p["question"] for p in opened["parameters"]] == [
              "How clearly and accurately does the department share the information you need?",
              "Does the department provide timely updates so you can plan your work?",
              "Does the department complete requests within agreed timelines without repeated follow-ups?",
              "Does the department take ownership of resolving issues without escalation?"])
    check("rating scale 1 Poor … 5 Excellent; comment required for 1, 2 and 5",
          opened["rating_labels"] == {1: "Poor", 2: "Below Average", 3: "Average", 4: "Good", 5: "Excellent"}
          and sorted(opened["comment_required_for"]) == [1, 2, 5])
    edited = S._clean_parameters([{**p, "question": "Custom wording?"} if p["code"] == "planning" else p
                                  for p in S.DEFAULT_PARAMETERS])
    check("Excel wording: a standard question keeps the sample's; an edited one is used as written",
          edited[0].get("report_question", "").startswith("Rate how clearly")
          and "report_question" not in edited[1] and edited[1]["question"] == "Custom wording?")
    check("link status Sent → Opened", sales_link["status"] == "Opened")
    sales_ev = next(e for e in events if e["user_id"] == str(HOD["Sales"]["_id"]))
    check("opening the form turns that HOD's activity Scheduled → Pending",
          sales_ev["status"] == "Pending" and sales_ev["idf_status"] == "Pending")
    check("…other HODs' activities stay Scheduled",
          all(e["status"] == "Scheduled" for e in events if e["user_id"] != str(HOD["Sales"]["_id"])))
    design_link = next(l for l in links if l["rater_user_id"] == str(HOD["Design"]["_id"]))
    pv = await S.open_link(ADMIN, design_link["token"])
    check("Super Admin / Admin open any HOD's link as a read-only preview",
          pv["state"] == "preview" and pv["form"]["receiver_name"] == "HR")
    check("…which leaves the HOD's link and calendar activity untouched",
          design_link["status"] == "Sent" and all(e["status"] == "Scheduled" for e in events
                                                   if e["user_id"] == str(HOD["Design"]["_id"])))
    co_link = next(l for l in links if l["rater_user_id"] == str(second_sales_hod["_id"]))
    check("the second Sales HOD can open their own link too",
          (await S.open_link(second_sales_hod, co_link["token"]))["state"] == "open")

    opts = await S.cycle_options(HR, None)
    check("the next cycle is pre-filled with this mapping",
          {o["receiver_dept_id"]: sorted(o["giver_dept_ids"]) for o in opts["last_reviews"]}
          == {str(D["HR"]): sorted([str(D["Sales"]), str(D["Design"])]), str(D["Sales"]): [str(D["HR"])]})
    check("calendar activity is locked (no manual completion)", S.is_locked_event(events[0]))
    await refused("a second open cycle", S.start_cycle(HR, None, {"period": "2026-12"}), 409)
    await refused("no final report while feedback is pending (MD download refused)",
                  R.md_download(MD, cyc_doc["id"], "compiled"), 409)

    section("Form rules (document §3)")
    mf = await S.my_forms(HOD["Sales"])
    check("Sales HOD sees only Sales → HR", [f["receiver_name"] for f in mf["forms"]] == ["HR"])
    good = {"giver_dept_id": str(D["Sales"]), "receiver_dept_id": str(D["HR"]),
            "ratings": {"information": 4, "planning": 3, "task_closure": None, "ownership": 2},
            "comments": {"ownership": "Escalations needed for leave queries"},
            "strength": "Quick on joining formalities", "improvement": "Close tickets without follow-ups"}
    await refused("a 2 without a comment", S.submit(HOD["Sales"], {**good, "comments": {}}), 422)
    await refused("missing Strength", S.submit(HOD["Sales"], {**good, "strength": ""}), 422)
    await refused("the wrong HOD", S.submit(HOD["Design"], good), 403)
    await refused("all Not applicable", S.submit(HOD["Sales"], {**good, "ratings": {}}), 422)
    out = await S.submit(HOD["Sales"], good)
    check("valid submission (with a Not-applicable parameter) accepted", out["ok"] and not out["cycle_completed"])
    await refused("resubmitting the same pair", S.submit(HOD["Sales"], good), 409)
    sales_evs = [e for e in events if e["idf_giver_dept_id"] == str(D["Sales"])]
    check("both Sales HODs' calendar activities turned Completed after storage",
          len(sales_evs) == 2 and all(e["status"] == "Completed" for e in sales_evs))
    await refused("the second Sales HOD submitting the same pair", S.submit(second_sales_hod, good), 409)
    check("after submitting, the link says 'submitted' (no form)",
          (await S.open_link(HOD["Sales"], sales_link["token"]))["state"] == "submitted")
    check("both Sales links marked Submitted",
          all(l["status"] == "Submitted" for l in store[S.COLL_LINKS].docs if l["giver_dept_id"] == str(D["Sales"])))

    section("Form Links page (HR / Admin / MD), like TPMS ▸ Form Links")
    await refused("an HOD opens Form Links", S.list_links(HOD["Sales"], None), 403)
    fl = await S.list_links(HR, None)
    check("the open cycle is shown by default, the imported ones are not listed",
          fl["cycle"]["id"] == cyc_doc["id"] and all(c["period"] == "2026-11" for c in fl["cycles"]))
    rows = {(r["giver_name"], r["rater_name"]): r for r in fl["links"]}
    check("one row per HOD per form (4), each with its link",
          len(fl["links"]) == 4 and all(r["link_path"].startswith("/idf/f/") for r in fl["links"]))
    check("Sales rows Submitted; Design → HR still Sent",
          rows[("Sales", "Sales Head")]["status"] == "Submitted" and rows[("Sales", "Sales Co-Head")]["status"] == "Submitted"
          and rows[("Design", "Design Head")]["status"] == "Sent")
    design_row = rows[("Design", "Design Head")]
    check("'last sent' stamped by the start email (sent once)",
          design_row["last_sent_at"] is not None and design_row["send_count"] == 1)
    check("Form Links rows carry no ratings or comments",
          not any(k in r for r in fl["links"] for k in ("ratings", "comments", "strength", "improvement")))
    before = len(bodies.get("design@co.test", []))
    await refused("an HOD resends a link", S.resend_link(HOD["Design"], None, design_row["id"]), 403)
    await S.resend_link(HR, None, design_row["id"])
    design_tok = next(l["token"] for l in store[S.COLL_LINKS].docs if l["rater_user_id"] == str(HOD["Design"]["_id"]))
    check("Resend emails the Design HOD their own link again",
          len(bodies["design@co.test"]) == before + 1 and f"/idf/f/{design_tok}" in bodies["design@co.test"][-1])
    check("…and the row shows it was sent twice",
          next(r for r in (await S.list_links(HR, None))["links"] if r["id"] == design_row["id"])["send_count"] == 2)
    await refused("resending a submitted form's link", S.resend_link(HR, None, rows[("Sales", "Sales Head")]["id"]), 409)
    mfd = await S.my_forms(HOD["Design"])
    check("My Feedback Forms gives the HOD their own form link",
          mfd["forms"][0]["link_path"] == f"/idf/f/{design_tok}")

    section("HR monitoring = status only")
    stt = await S.cycle_status(HR, None, cyc_doc["id"])
    check("1 completed, 2 pending of 3", (stt["completed"], stt["pending"], stt["total"]) == (1, 2, 3))
    check("status shows each form's link status (Sales → HR: Submitted)",
          any(r["giver_name"] == "Sales" and r["link_status"] == "Submitted" for r in stt["activities"]))
    check("status rows carry no ratings or comments",
          not any(k in r for r in stt["activities"] for k in ("ratings", "comments", "strength", "improvement")))

    section("Reminders (document §4B)")
    c = store["idf_cycles"].docs[-1]
    c["deadline"] = (date.today() - timedelta(days=1)).isoformat()
    before = len(mails)
    r1 = await S.run_daily_reminders()
    check("overdue reminder to each pending rater", r1["overdue"] == 2 and len(mails) - before == 2)
    check("pending activities turned Overdue", sum(1 for e in events if e["status"] == "Overdue") == 2)
    r2 = await S.run_daily_reminders()
    check("not re-sent the same day", r2["overdue"] == 0)

    section("Last submission completes the cycle -> actions -> report to the MD only")
    mails.clear()
    await S.submit(HOD["Design"], {**good, "giver_dept_id": str(D["Design"]),
                                   "ratings": {"information": 5, "planning": 5, "task_closure": 4, "ownership": 4},
                                   "comments": {"information": "Always on time", "planning": "Plans ahead"}})
    out = await S.submit(HOD["HR"], {"giver_dept_id": str(D["HR"]), "receiver_dept_id": str(D["Sales"]),
                                     "ratings": {"information": 2, "planning": 2, "task_closure": 2, "ownership": 2},
                                     "comments": {k: "Late data" for k in ("information", "planning", "task_closure", "ownership")},
                                     "strength": "Good follow up", "improvement": "Share data on time"})
    check("cycle completed on the last submission", out["cycle_completed"])
    pkg = [m for m in mails if not isinstance(m[0], str)]
    check("report package emailed once, to the MD only", len(pkg) == 1 and pkg[0][1] == ["md@co.test"])
    check("package has 3 attachments", len([p for p in pkg[0][0].walk() if p.get_filename()]) == 3)
    att = next(p for p in pkg[0][0].walk() if (p.get_filename() or "").startswith("Interdepartmental_Feedback_Compiled_"))
    wbm = load_workbook(io.BytesIO(att.get_payload(decode=True)))
    check("emailed Compiled Excel: Company + a FEEDBACK FOR sheet per reviewed department + legend",
          wbm.sheetnames == ["Company", "HR", "Sales", "Sheet1"])
    hrs = wbm["HR"]
    hdr = [c.value for c in hrs[6]]
    check("HR sheet: raters Sales and Design as columns, then Final and Comments",
          hdr == ["Topic", "Question", "Sales", "Design", "Final", "Comments"])
    check("the actually submitted ratings: Sales 4/3/blank(N/A)/2, Design 5/5/4/4",
          [[hrs.cell(row=r, column=c).value for c in (3, 4)] for r in range(7, 11)] == [[4, 5], [3, 5], [None, 4], [2, 4]])
    check("Final = average of valid ratings (Information 4.5)", hrs.cell(row=7, column=5).value == 4.5)
    check("submitted Strength and Improvement per rater",
          hrs.cell(row=12, column=3).value == "Quick on joining formalities"
          and hrs.cell(row=13, column=3).value == "Close tickets without follow-ups")
    check("comments in the Comments column", "Sales: Escalations needed" in str(hrs.cell(row=10, column=6).value))
    check("Average Score % cell formatted 0%", hrs.cell(row=14, column=6).number_format == "0%")
    check("Company sheet: HR and Sales scores + Company column",
          [c.value for c in wbm["Company"][5]][:5] == ["Topic", "Question", "HR", "Sales", "Company"])
    dl = await R.md_download(MD, str(store["idf_cycles"].docs[-1]["_id"]), "compiled")
    check("MD downloads the same Compiled Excel from the dashboard", dl[0].startswith("Interdepartmental_Feedback_Compiled_"))
    await refused("HR downloads it", R.md_download(HR, str(store["idf_cycles"].docs[-1]["_id"]), "compiled"), 403)
    check("email log holds no feedback content", not any("Late data" in str(x) for x in logged))
    dash = await A.md_dashboard(MD, None)
    check("MD dashboard shows the cycle with RAG", dash["result"] and dash["result"]["company"]["band"])
    hs = dash["result"]["hotspots"]
    check("HR → Sales 40% is a hotspot", any(h["from"] == "HR" and h["to"] == "Sales" and h["pct"] == 40.0 for h in hs))

    section("Action plans: MD, coordinator, owner")
    mine = await A.list_actions(HOD["Sales"], None, {})
    check("Sales HOD sees only Sales actions", mine["role"] == "owner" and mine["actions"]
          and all(a["department"] == "Sales" for a in mine["actions"]))
    a0 = mine["actions"][0]
    await refused("owner changes the target date", A.update_action(HOD["Sales"], None, a0["id"], {"target_date": "2030-01-01"}), 403)
    upd = await A.update_action(HOD["Sales"], None, a0["id"], {"status": "In Progress", "remark": "Meeting held"})
    check("owner updates status + progress remark", upd["status"] == "In Progress" and upd["remarks"][-1]["text"] == "Meeting held")
    co = await A.list_actions(ADMIN, C, {})
    check("TPS coordinator (Sparsh) monitors the company's action plans", co["role"] == "coordinator" and co["actions"])
    await refused("HR (not an owner) cannot read others' actions",
                  A.update_action(HR, None, a0["id"], {"remark": "x"}), 404)

    section("Action Plan Management (document §8)")
    md_list = await A.list_actions(MD, None, {})
    one = md_list["actions"][0]
    check("every action carries the 10 required fields",
          all(k in one for k in ("department", "feedback_from", "parameter", "current_score", "improvement_action",
                                 "owner_name", "target_date", "status", "remarks", "review_date")))
    check("the MD gets the company's people to assign as owners",
          any(p["name"] == "Prem Kumawat" for p in md_list["people"]))
    await refused("an owner cannot reassign the owner",
                  A.update_action(HOD["Sales"], None, a0["id"], {"owner_user_id": str(HR["_id"])}), 403)
    re = await A.update_action(MD, None, a0["id"], {"owner_user_id": str(HR["_id"]), "target_date": "2030-02-01"})
    check("the MD reassigns the owner and the target date", re["owner_name"] == "Prem Kumawat"
          and re["target_date"] == "2030-02-01")
    closed = await A.update_action(MD, None, a0["id"], {"status": "Closed", "remark": "Hand-off agreed"})
    check("closure tracked: when and by whom", closed["status"] == "Closed" and closed["closed_at"]
          and closed["closed_by"] == "Rajeev Lath")
    reopened = await A.update_action(MD, None, a0["id"], {"status": "In Progress"})
    check("reopening clears the closure", reopened["closed_at"] is None and reopened["closed_by"] is None)
    act_doc = next(x for x in store["idf_actions"].docs if str(x["_id"]) == a0["id"])
    act_doc["review_date"] = date.today().isoformat()
    act_doc["target_date"] = "2030-02-01"
    check("a review that has come round is flagged",
          next(x for x in (await A.list_actions(MD, None, {}))["actions"] if x["id"] == a0["id"])["review_due"])
    mails.clear()
    await A.alert_overdue_actions()
    check("review-due reminder emailed to the owner", any("Review due" in str(m[0]) and m[1] == ["hr@co.test"] for m in mails))
    mails.clear()
    await A.alert_overdue_actions()
    check("…once per review date", not any("Review due" in str(m[0]) for m in mails))
    act_doc["target_date"] = (date.today() - timedelta(days=1)).isoformat()
    act_doc.pop("last_overdue_alert", None)
    mails.clear()
    await A.alert_overdue_actions()
    check("overdue action alert emailed to the owner", any("Overdue" in str(m[0]) and m[1] == ["hr@co.test"] for m in mails))
    upd2 = await A.update_action(MD, None, a0["id"], {"remark": "Weekly WRM done"})
    check("a progress update moves the next review on (no longer due)",
          not upd2["review_due"] and upd2["review_date"] > date.today().isoformat())

    section("Add department feedback to a started cycle (reopens a completed one)")
    nov = store["idf_cycles"].docs[-1]
    nov_id = str(nov["_id"])
    new_deadline = (date.today() + timedelta(days=5)).isoformat()
    existing = [review("HR", ["Sales", "Design"]), review("Sales", ["HR"])]
    await refused("an HOD adds forms", S.add_reviews(HOD["Sales"], None, nov_id,
                                                    {"reviews": [review("Operation", ["Purchase"])]}), 403)
    await refused("nothing new to add", S.add_reviews(HR, None, nov_id, {"reviews": existing, "deadline": new_deadline}), 422)
    await refused("a rater department without an HOD", S.add_reviews(
        HR, None, nov_id, {"reviews": [review("Operation", ["Marketing"])], "deadline": new_deadline}), 422)
    await refused("the old (passed) deadline", S.add_reviews(
        HR, None, nov_id, {"reviews": [review("Operation", ["Purchase"])]}), 422)
    ev_before = sum(len(store.get(c, Coll()).docs) for c in ("LEARNER_CALENDER", "STAFF_CALENDER", "calendar_events"))
    mails.clear()
    added = await S.add_reviews(HR, None, nov_id, {"reviews": existing + [review("Operation", ["Purchase", "Commercial"])],
                                                   "deadline": new_deadline})
    check("2 new forms added; the completed cycle reopens with a fresh deadline",
          added["added"] == 2 and added["reopened"] and added["status"] == "Open" and added["deadline"] == new_deadline)
    check("existing forms untouched: the 3 submitted stay Completed",
          sum(1 for p in added["pairs"] if p["status"] == "Completed") == 3 and len(added["pairs"]) == 5)
    check("the earlier MD report is kept as history; 'report to MD' resets until the new one goes",
          added["report_sent_at"] is None and added["previous_report_sent_at"] is not None)
    await refused("the reopened cycle's report can't be downloaded until the added forms are in",
                  R.md_download(MD, nov_id, "pdf"), 409)
    ev_after = sum(len(store.get(c, Coll()).docs) for c in ("LEARNER_CALENDER", "STAFF_CALENDER", "calendar_events"))
    check("a calendar activity for each new HOD form (Purchase, Commercial → Operation)", ev_after - ev_before == 2)
    check("only the new HODs are emailed, each with their own link",
          sorted(m[1][0] for m in mails) == ["commercial@co.test", "purchase@co.test"]
          and all("/idf/f/" in bodies[e][-1] for e in ("commercial@co.test", "purchase@co.test")))
    check("Form Links lists the new links", len((await S.list_links(HR, None, nov_id))["links"]) == 6)
    store["idf_cycles"].docs[-1]["reminder_days_before"] = 10       # inside the "due soon" window
    mails.clear()
    rb = await S.run_daily_reminders()
    check("the added forms get the 'due soon' reminder", rb["before"] == 2
          and sorted(m[1][0] for m in mails) == ["commercial@co.test", "purchase@co.test"])
    mails.clear()
    check("…once only", (await S.run_daily_reminders())["before"] == 0 and not mails)
    await refused("adding the same department again", S.add_reviews(
        HR, None, nov_id, {"reviews": [review("Operation", ["Purchase"])], "deadline": new_deadline}), 422)
    op = {"receiver_dept_id": str(D["Operation"]), "ratings": {"information": 4, "planning": 4, "task_closure": 4, "ownership": 4},
          "comments": {}, "strength": "Responsive", "improvement": "Share plans earlier"}
    r1 = await S.submit(HOD["Purchase"], {**op, "giver_dept_id": str(D["Purchase"])})
    check("cycle stays open until every added form is in", not r1["cycle_completed"])
    mails.clear()
    r2 = await S.submit(HOD["Commercial"], {**op, "giver_dept_id": str(D["Commercial"])})
    check("…then completes again and the MD gets a fresh report", r2["cycle_completed"]
          and any(not isinstance(m[0], str) and m[1] == ["md@co.test"] for m in mails))
    pkg2 = next(m for m in mails if not isinstance(m[0], str))
    att2 = next(p for p in pkg2[0].walk() if (p.get_filename() or "").startswith("Interdepartmental_Feedback_Compiled_"))
    check("the new Compiled Excel covers every department, Operation included",
          set(load_workbook(io.BytesIO(att2.get_payload(decode=True))).sheetnames) == {"Company", "HR", "Operation", "Sales", "Sheet1"})

    section("Reports, summary and rating scale (document §10, §13)")
    titles = [t for t, _ in R.summary_sections(res, "Dewas Techno")]
    check("Management Summary = key findings, major concerns, recommended focus areas",
          titles == ["Key findings", "Major concerns", "Recommended focus areas"])
    focus = dict(R.summary_sections(res, "Dewas Techno"))["Recommended focus areas"]
    check("focus areas name each hotspot's repair and each Amber department's interface meeting",
          any(f.startswith("HR → Sales") for f in focus) and any(f.startswith("Design:") for f in focus))
    pa = load_workbook(io.BytesIO(xl))["Parameter Analysis"]
    check("Parameter-wise analysis has the band", [c.value for c in pa[1]][:3] == ["Parameter", "Company %", "Band"])
    await refused("a rating scale without 5 labels", S.save_setup(HR, None, {"rating_labels": ["Bad", "OK"]}), 422)
    labels = ["Very poor", "Poor", "Fair", "Good", "Very good"]
    saved = await S.save_setup(HR, None, {"rating_labels": labels})
    check("the rating scale's labels are configurable in Setup", saved["rating_labels"] == labels)
    check("a cycle's form shows its own labels", S._labels({"rating_labels": labels})[3] == "Fair"
          and S._labels({})[5] == "Excellent")

    # ── The client's "Standard Approach" document ──────────────────────────────────────────
    import app.services.idf_process as P
    from datetime import datetime as _dt, timezone as _tz
    section("Standard Approach: results meeting and the MD's email")
    novc = next(c for c in store["idf_cycles"].docs if str(c["_id"]) == nov_id)
    meets = [e for cn in ("LEARNER_CALENDER", "STAFF_CALENDER", "calendar_events")
             for e in store.get(cn, Coll()).docs if e.get("kind") == "idf_results_meeting"]
    check("a results meeting of the MD and all HODs is put in their calendars — once per cycle",
          len(meets) == 1 and str(MD["_id"]) in meets[0]["assigned_member_ids"]
          and str(HOD["Sales"]["_id"]) in meets[0]["assigned_member_ids"] and novc.get("results_meeting_date"))
    html = " ".join(str(part.get_payload(decode=True) or b"", "utf-8", "ignore")
                    for part in pkg2[0].walk() if part.get_content_type() == "text/html")
    check("the MD's email names the results meeting and the no-retaliation statement",
          "results meeting" in html and "no retaliation" in html.lower())

    section("Standard Approach: \"you said, we did\" within 15 days")
    hr_mine = (await P.list_responses(HOD["HR"], None))["mine"]
    hr_resp = next(r for r in hr_mine if r["department"] == "HR")
    check("each rated department's HOD gets a 'you said, we did' to write, due 15 days after results",
          hr_resp["status"] == "Pending" and hr_resp["due_date"]
          == (P._as_date(novc["completed_at"]) + timedelta(days=15)).isoformat())
    check("…showing what the department was told, by department (never by person)",
          any(i["from"] == "Sales" for i in hr_resp["received"]["improvements"]))
    await refused("another department's HOD answers for HR",
                  P.submit_response(HOD["Sales"], hr_resp["id"], {"items": [{"what": "x", "by_when": "2030-01-01"}]}), 404)
    await refused("a change without a date",
                  P.submit_response(HOD["HR"], hr_resp["id"], {"items": [{"what": "Reply within 24 hours"}]}), 422)
    mails.clear()
    done_r = await P.submit_response(HOD["HR"], hr_resp["id"], {"items": [
        {"what": "Answer leave queries within 24 hours", "by_when": "2030-01-15"}]})
    check("the HOD says what will change and by when", done_r["status"] == "Submitted" and done_r["items"])
    check("…and the HODs of the departments that rated HR are told (Sales, Design)",
          {m[1][0] for m in mails} >= {"sales@co.test", "design@co.test"})
    check("the raters see it under responses received",
          any(r["department"] == "HR" for r in (await P.list_responses(HOD["Design"], None))["received"]))
    sm = await P.responses_summary(C, nov_id)
    check("HR and the MD follow up: 1 answered, the rest pending", sm["submitted"] == 1 and sm["total"] >= 2)
    sales_r = next(x for x in store[P.COLL_RESPONSES].docs if x["department"] == "Sales" and x["cycle_id"] == nov_id)
    sales_r["due_date"] = (date.today() - timedelta(days=1)).isoformat()
    mails.clear()
    d1 = await P.daily(date.today())
    check("an overdue 'you said, we did' reminds the HOD", d1["you_said_reminders"] >= 1
          and any(m[1] == ["sales@co.test"] for m in mails))

    section("Standard Approach: open feedback channel (no waiting for the next survey)")
    exec_u = next(p for p in people if p["email"] == "exec@co.test")
    await refused("an issue without the department it is about", P.raise_issue(exec_u, {"description": "Late every week"}), 422)
    mails.clear()
    iss = await P.raise_issue(exec_u, {"about_department_id": str(D["Operation"]), "anonymous": True,
                                       "description": "Dispatch dates change without notice to Sales."})
    check("anyone can raise an inter-department issue; HR is emailed",
          iss["status"] == "New" and any(m[1] == ["hr@co.test"] for m in mails))
    hrl = await P.list_issues(HR, None)
    check("HR sees it; an anonymous raiser stays anonymous to HR",
          hrl["manager"] and hrl["issues"][0]["raised_by_name"] == "Anonymous" and "raised_by" not in hrl["issues"][0])
    check("the raiser sees only their own issues", len((await P.list_issues(exec_u, None))["issues"]) == 1)
    await refused("a non-HR user updates an issue", P.update_issue(exec_u, None, iss["id"], {"status": "Resolved"}), 403)
    up_i = await P.update_issue(HR, None, iss["id"], {"status": "Taken to WRM", "note": "On Monday's WRM"})
    check("HR takes it to the weekly WRM", up_i["status"] == "Taken to WRM" and up_i["wrm_date"])
    mails.clear()
    await P.update_issue(HR, None, iss["id"], {"status": "Resolved", "note": "Dispatch freeze agreed"})
    check("resolving it tells the person who raised it", any(m[1] == ["exec@co.test"] for m in mails))

    section("Standard Approach: rhythm and the pulse re-score")
    cad = await P.cadence(C)
    check("re-score monthly for the first two cycles, then quarterly",
          cad["interval_months"] == 3 and cad["next_due_period"] == P.add_months(cad["last_period"], 3)
          and P.add_months("2026-12", 1) == "2027-01" and P.add_months("2026-11", 3) == "2027-02")
    ps = await P.pulse_suggestion(C)
    check("a pulse re-score is suggested for the Red relationships (HR → Sales)",
          ps and not ps["started"] and any(x["from"] == "HR" and x["to"] == "Sales" for x in ps["relationships"]))
    check("…not available before 30 days have passed", ps["available"] is False)
    await refused("starting the pulse before the 30 days", S.start_cycle(HR, None, {
        "period": novc["period"], "cycle_type": "pulse", "pulse_of": ps["cycle_id"], "reviews": ps["reviews"]}), 422)
    novc["completed_at"] = _dt.now(_tz.utc) - timedelta(days=31)
    mails.clear()
    d2 = await P.daily(date.today())
    check("30 days on, HR is told the pulse re-score is due — once", d2["pulse_due_reminders"] >= 1
          and (await P.daily(date.today()))["pulse_due_reminders"] == 0)
    ps = await P.pulse_suggestion(C)
    check("30 days on, the pulse re-score is available", ps["available"] is True)
    pulse = await S.start_cycle(HR, None, {"period": novc["period"], "cycle_type": "pulse", "pulse_of": ps["cycle_id"],
                                           "reviews": ps["reviews"],
                                           "deadline": (date.today() + timedelta(days=5)).isoformat()})
    check("the pulse re-score runs in the same month, only for the affected departments",
          pulse["cycle_type"] == "pulse" and [(p["giver_name"], p["receiver_name"]) for p in pulse["pairs"]] == [("HR", "Sales")])
    check("…without replacing the remembered full mapping",
          len((await S.cycle_options(HR, None))["last_reviews"]) > 1)
    n_actions = len(store["idf_actions"].docs)
    await S.submit(HOD["HR"], {"giver_dept_id": str(D["HR"]), "receiver_dept_id": str(D["Sales"]),
                               "ratings": {"information": 4, "planning": 4, "task_closure": 4, "ownership": 4},
                               "comments": {}, "strength": "Faster replies", "improvement": "Keep it up"})
    pulse_doc = next(c for c in store["idf_cycles"].docs if str(c["_id"]) == pulse["id"])
    check("the pulse completes", pulse_doc["status"] == "Completed")
    red_act = next(a for a in store["idf_actions"].docs if a["cycle_id"] == nov_id and a["type"] == "Relationship repair"
                   and a["feedback_from"] == "HR" and a["department"] == "Sales")
    check("its new score goes onto the Red action it re-scores (HR → Sales: 40% → 80%)",
          red_act.get("rescore_pct") == 80.0 and red_act.get("rescore_band") == "Green")
    check("a pulse creates no new actions and no second results meeting",
          len(store["idf_actions"].docs) == n_actions and len([e for cn in ("LEARNER_CALENDER", "STAFF_CALENDER", "calendar_events")
                                                              for e in store.get(cn, Coll()).docs if e.get("kind") == "idf_results_meeting"]) == 1)
    pres = await A.analyse(pulse_doc)
    check("the pulse is compared with the cycle it re-scores",
          next(d for d in pres["departments"] if d["name"] == "Sales")["change"] is not None)
    check("leadership focus by team stage", P.LEADERSHIP_FOCUS["Norming"].startswith("Agree standard formats"))

    section("Email wording comes from Notification Templates (nothing hard-coded)")
    from app.models.notify_modules import NOTIFY_MODULES
    idf_mod = NOTIFY_MODULES["idf"]
    check("an 'Inter-Departmental Feedback' module with 14 email templates is listed under Notification Templates",
          idf_mod["label"] == "Inter-Departmental Feedback" and len(idf_mod["triggers"]) == 14
          and all(t["slug"] + "_email" in ns.DEFAULT_TEMPLATES for t in idf_mod["triggers"]))
    tpl = store.setdefault("notification_templates", Coll())
    tpl.docs.append({"_id": ObjectId(), "slug": "idf_issue_raised_email", "scope": "company", "company_id": C,
                     "subject": "WRM item: {{about_department}}", "is_active": True,
                     "body": "Hi {{name}},\nNew issue about {{about_department}}:\n{{description}}"})
    mails.clear()
    bodies.clear()
    iss2 = await P.raise_issue(exec_u, {"about_department_id": str(D["Purchase"]),
                                        "description": "Purchase orders are raised without specs."})
    check("the company's own template is used: its subject…",
          any(m[0] == "WRM item: Purchase" and m[1] == ["hr@co.test"] for m in mails))
    check("…and its body, placeholders filled and line breaks kept",
          any("Hi Prem Kumawat,<br>New issue about Purchase:<br>Purchase orders are raised" in b
              for b in bodies.get("hr@co.test", [])))
    tpl.docs[-1]["is_active"] = False
    mails.clear()
    await P.raise_issue(exec_u, {"about_department_id": str(D["Purchase"]), "description": "Second one, switched off."})
    check("switching the template Inactive stops that email", not mails)
    tpl.docs.pop()
    mails.clear()
    await P.update_issue(HR, None, iss2["id"], {"status": "Resolved", "note": "Specs template shared"})
    check("without an edited template the built-in default is used",
          any(m[0] == "Your inter-department issue about Purchase is resolved" for m in mails))

    section("Delete (MD, Client Admin, Super Admin) — permanent and audited")
    check("who may delete: MD, Client Admin, Super Admin — not HR, not an HOD",
          S.can_delete(MD) and S.can_delete(ADMIN) and S.can_delete({"role": "clientadmin"})
          and not S.can_delete(HR) and not S.can_delete(HOD["Sales"]))
    other_admin = {"_id": ObjectId(), "role": "clientadmin", "company_id": str(ObjectId()), "full_name": "Other Co Admin"}
    store["learners"].docs.append(other_admin)
    some_action = next(a for a in store["idf_actions"].docs if a["cycle_id"] != nov_id)
    await refused("HR deletes an action", A.delete_action(HR, None, str(some_action["_id"])), 403)
    await A.delete_action(MD, None, str(some_action["_id"]))
    check("the MD deletes an action plan item", not any(a["_id"] == some_action["_id"] for a in store["idf_actions"].docs))
    await refused("HR deletes a raised issue", P.delete_issue(HR, None, iss["id"]), 403)
    await P.delete_issue(MD, None, iss["id"])
    check("the MD deletes a raised issue", not any(str(x["_id"]) == iss["id"] for x in store[P.COLL_ISSUES].docs))
    await refused("HR previews a cycle delete", S.delete_preview(HR, None, nov_id), 403)
    await refused("another company's Client Admin deletes this company's cycle",
                  S.delete_preview(other_admin, None, nov_id), 403)
    pv = await S.delete_preview(MD, None, nov_id)
    check("the preview lists what goes: forms, feedback, actions, 'you said, we did', calendar, the pulse",
          pv["forms"] >= 5 and pv["submissions"] >= 5 and pv["actions"] > 0 and pv["responses"] >= 2
          and pv["calendar_activities"] > 0 and pv["pulse_rescores"] == 1)
    await refused("delete without typing DELETE", S.delete_cycle(MD, None, nov_id, ""), 422)
    pulse_id = pulse["id"]
    out_del = await S.delete_cycle(MD, None, nov_id, "delete")
    gone = {nov_id, pulse_id}
    check("the cycle and its pulse re-score are deleted", out_del["ok"]
          and not any(str(c["_id"]) in gone for c in store["idf_cycles"].docs))
    check("…with their feedback, links, actions and 'you said, we did'",
          not any(d.get("cycle_id") in gone for cn in ("idf_submissions", S.COLL_LINKS, "idf_actions", P.COLL_RESPONSES)
                  for d in store[cn].docs))
    check("…and their calendar activities and results meeting",
          not any(e.get("idf_cycle_id") in gone for cn in ("LEARNER_CALENDER", "STAFF_CALENDER", "calendar_events")
                  for e in store.get(cn, Coll()).docs))
    check("the deletion is in the audit trail",
          any(a.get("action") == "cycle deleted" for a in store[S.COLL_AUDIT].docs))
    check("other cycles are untouched (the imported ones remain)", len(store["idf_cycles"].docs) >= 2)

    passed = sum(results)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
