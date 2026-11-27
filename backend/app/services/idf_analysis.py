"""Inter-Departmental Feedback — scoring, RAG classification, hotspots, action plans.

Document §5–§8 (Inter Dep Feedbak Process Development.docx). The arithmetic reproduces the
client's worked example (Interdepartmental_Feedback Action_Plan.docx):

  * Percentage = (average rating ÷ 5) × 100; blank / Not-applicable (and 0) are excluded.
  * Relationship (rater → rated): average of that rater's valid ratings  (HR → Sales 2,2,2,2 = 40%).
  * Department, per parameter: average of every rater's valid rating for that parameter.
  * Department overall: average of ALL valid ratings it received   (Sales 3.3125 = 66.3%).
  * Company, per parameter: average of the departments' parameter scores (Information 72.1%).
  * Company overall: average of the departments' overall scores     (70.6%).

RAG: Red < 60, Amber 60–79.9, Green ≥ 80. Any relationship below 60% triggers the Red repair
process for that relationship even when the department is Amber; a drop of 5+ points against
the previous cycle triggers the Amber process.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from bson import ObjectId
from fastapi import HTTPException

from app.db.mongodb import get_collection

COLL_ACTIONS = "idf_actions"
RED, AMBER, GREEN = "Red", "Amber", "Green"
ACTION_STATUSES = ("Open", "In Progress", "Closed")

RED_STEPS = ("Repair: facilitated meeting within 7 days; 5-Why root cause analysis; identify process, "
             "information-flow and ownership gaps; written hand-off agreement between the departments; "
             "track weekly in WRM; re-score after 30 days.")
AMBER_STEPS = ("Strengthen: 30-minute interface meeting within 15 days with the lowest-rating department; "
               "agree one improvement action with an owner and target date; track fortnightly and share "
               "progress with the departments concerned.")
GREEN_STEPS = ("Sustain: recognise the department; capture and share its successful practices; identify "
               "where it can support other departments; keep monitoring the trend.")
DROP_STEPS = "Score dropped 5+ points since the last cycle — " + AMBER_STEPS

# Document §6: band -> category, team stage and required action.
STAGE = {RED: "Storming", AMBER: "Norming", GREEN: "Performing"}
CATEGORY = {RED: "Red – Repair", AMBER: "Amber – Strengthen", GREEN: "Green – Sustain"}


def stage(band_: Optional[str]) -> Optional[str]:
    return STAGE.get(band_)


# Standard Approach document: who leads each band and how fast.
LED_BY = {RED: "MD & HR", AMBER: "HOD of the rated department", GREEN: "HOD, with HR for recognition"}
RESPONSE_TIME = {RED: "Meeting within 7 days", AMBER: "Meeting within 15 days", GREEN: "At the next review"}
# Amber step 3: "agree one process fix".
PROCESS_FIXES = ("Hand-off checklist", "Standard request format", "ERP alert", "Fixed reply time", "Other")


def _steps(kind_band: str, *, dept=None, weakest=None, lowest=None, target=None, rescore=None, drop=False,
           coach=None, company=False) -> list:
    """The improvement process as numbered steps (client documents: the requirement §7 and the
    Standard Approach), filled in with this action's facts."""
    if company:
        return [f"The MD leads a company-wide repair session with all HODs within 7 days (target {target}).",
                f"Agree the company-wide theme{' — ' + weakest if weakest else ''} and the hand-offs to fix first.",
                "Every Red relationship follows its own repair steps; review all of them weekly in WRM.",
                f"Pulse re-score after 30 days (on {rescore}) using the same questions."]
    if kind_band == RED:
        return [f"Acknowledge quickly: within 7 days the MD and HR hold a facilitated meeting of {dept or 'the rated department'} "
                f"and its lowest raters{' (' + lowest + ')' if lowest else ''}. The rated team listens first and asks "
                f"questions — no defending, no blame.",
                f"Find the root cause of the weakest question{' (' + weakest + ')' if weakest else ''} with a 5-Why. "
                f"Check process, information flow and ownership before people.",
                "Write a hand-off agreement between the departments: what information is needed, in what format, "
                "by when, and who owns each step.",
                f"Log the actions in this Action Plan with owner, target date (target {target}) and status.",
                "Review weekly in WRM until the score recovers. The HOD gets one-to-one counselling on leading the change.",
                f"Pulse re-score after 30 days (on {rescore}), only for the affected departments, using the same questions."]
    if kind_band == AMBER:
        return ([("A drop of 5 points or more since the last cycle triggered these Amber steps.")] if drop else []) + [
                f"In the next WRM the HOD picks the weakest question ({weakest or '—'}) and the lowest-rating "
                f"department ({lowest or '—'}), and sets one action, owner and target date (target {target}).",
                f"Within 15 days, hold a 30-minute interface meeting with {lowest or 'the lowest-rating department(s)'} "
                f"to hear what gets in the way.",
                "Agree one process fix: a hand-off checklist, a standard request format, an ERP alert or a fixed reply time.",
                "Track status fortnightly; share progress with the raters."]
    return ["Recognise openly: a WOW card, a mention in the HOD meeting, thanks from the raters (HR supports the recognition).",
            f"Capture what works (routines, formats, reply habits) and let the HOD coach "
            f"{coach + ' (Amber/Red)' if coach else 'one Amber or Red department'}.",
            "Still act on its own improvement comments and on any rater relationship below 60%.",
            "Watch the trend: a drop of 5 points or more triggers the Amber steps."]


def band(pct: Optional[float]) -> Optional[str]:
    if pct is None:
        return None
    return RED if pct < 60 else AMBER if pct < 80 else GREEN


def _pct(avg: Optional[float]) -> Optional[float]:
    """Percentage to one decimal, rounding halves UP as Excel does (66.25 -> 66.3), so the
    figures match the client's own reports. Python's round() would give 66.2."""
    if avg is None:
        return None
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(round(avg / 5 * 100, 9))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _mean(vals) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _valid(v) -> Optional[float]:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if 1 <= v <= 5 else None


async def submissions_for(cycle: dict) -> List[dict]:
    return await get_collection("idf_submissions").find({"cycle_id": str(cycle["_id"])}).to_list(5000)


def compute(cycle: dict, subs: List[dict], previous: Optional[dict] = None) -> dict:
    """The full analysis of one cycle. `previous` is the prior cycle's compute() result."""
    params = cycle.get("parameters") or []
    codes = [p["code"] for p in params]
    pname = {p["code"]: p["name"] for p in params}

    rels, by_dept = [], {}
    for s in subs:
        vals = {c: _valid((s.get("ratings") or {}).get(c)) for c in codes}
        rel_avg = _mean(vals.values())
        weakest = min((c for c in codes if vals[c] is not None), key=lambda c: vals[c], default=None)
        rels.append({"from": s["giver_name"], "from_id": s["giver_dept_id"],
                     "to": s["receiver_name"], "to_id": s["receiver_dept_id"],
                     "ratings": vals, "avg": rel_avg, "pct": _pct(rel_avg), "band": band(_pct(rel_avg)),
                     "weakest": pname.get(weakest) if weakest else None})
        d = by_dept.setdefault(s["receiver_dept_id"], {"id": s["receiver_dept_id"], "name": s["receiver_name"],
                                                       "per_param": {c: [] for c in codes}, "all": [],
                                                       "raters": [], "strengths": [], "improvements": [],
                                                       "comments": []})
        for c in codes:
            if vals[c] is not None:
                d["per_param"][c].append(vals[c])
                d["all"].append(vals[c])
        d["raters"].append({"from": s["giver_name"], "avg": rel_avg, "pct": _pct(rel_avg)})
        if s.get("strength"):
            d["strengths"].append({"from": s["giver_name"], "text": s["strength"]})
        if s.get("improvement"):
            d["improvements"].append({"from": s["giver_name"], "text": s["improvement"]})
        for c, t in (s.get("comments") or {}).items():
            d["comments"].append({"from": s["giver_name"], "parameter": pname.get(c, c), "text": t})

    # Free-text comments from an imported Excel (its "Comments" column is not tied to a rater).
    for note in cycle.get("imported_notes") or []:
        d = by_dept.get(note.get("receiver_dept_id"))
        if d and note.get("text"):
            d["comments"].append({"from": "Imported comment", "parameter": pname.get(note.get("parameter"),
                                                                                   (note.get("parameter") or "").title()),
                                  "text": note["text"]})

    prev_pct = {d["id"]: d["pct"] for d in (previous or {}).get("departments", [])}
    depts = []
    for d in by_dept.values():
        param_avg = {c: _mean(d["per_param"][c]) for c in codes}
        overall = _mean(d["all"])
        pct = _pct(overall)
        scored = [c for c in codes if param_avg[c] is not None]
        weakest = min(scored, key=lambda c: param_avg[c], default=None)
        lowest_rater = min((r for r in d["raters"] if r["avg"] is not None), key=lambda r: r["avg"], default=None)
        change = round(pct - prev_pct[d["id"]], 1) if pct is not None and prev_pct.get(d["id"]) is not None else None
        depts.append({"id": d["id"], "name": d["name"],
                      "param_avg": param_avg, "param_pct": {c: _pct(v) for c, v in param_avg.items()},
                      "avg": overall, "pct": pct, "band": band(pct), "stage": stage(band(pct)),
                      "weakest_param": pname.get(weakest) if weakest else None,
                      "weakest_param_pct": _pct(param_avg[weakest]) if weakest else None,
                      "lowest_rater": lowest_rater["from"] if lowest_rater else None,
                      "lowest_rater_pct": lowest_rater["pct"] if lowest_rater else None,
                      "previous_pct": prev_pct.get(d["id"]), "change": change,
                      "dropped": change is not None and change <= -5,
                      "raters": d["raters"], "strengths": d["strengths"],
                      "improvements": d["improvements"], "comments": d["comments"]})
    depts.sort(key=lambda d: (-(d["pct"] if d["pct"] is not None else -1), d["name"].lower()))

    scored = [d for d in depts if d["pct"] is not None]
    company_param = {c: _mean([d["param_avg"][c] for d in scored]) for c in codes}
    company_avg = _mean([d["avg"] for d in scored])
    company_pct = _pct(company_avg)
    weakest_c = min((c for c in codes if company_param[c] is not None), key=lambda c: company_param[c], default=None)
    hotspots = sorted([r for r in rels if r["pct"] is not None and r["pct"] < 60], key=lambda r: r["pct"])
    pairs = cycle.get("pairs") or []
    done = sum(1 for p in pairs if p.get("status") == "Completed")
    return {
        "cycle": {"id": str(cycle["_id"]), "name": cycle.get("name"), "period": cycle.get("period"),
                  "status": cycle.get("status"), "deadline": cycle.get("deadline"),
                  "completed_at": cycle.get("completed_at"), "source": cycle.get("source")},
        "parameters": params,
        "company": {"avg": company_avg, "pct": company_pct, "band": band(company_pct),
                    "stage": stage(band(company_pct)),
                    "param_avg": company_param, "param_pct": {c: _pct(v) for c, v in company_param.items()},
                    "previous_pct": (previous or {}).get("company", {}).get("pct"),
                    "weakest_param": pname.get(weakest_c) if weakest_c else None,
                    "weakest_param_pct": _pct(company_param[weakest_c]) if weakest_c else None},
        "departments": depts,
        "highest": scored[0]["name"] if scored else None,
        "lowest": scored[-1]["name"] if scored else None,
        "relationships": sorted(rels, key=lambda r: (r["to"].lower(), r["from"].lower())),
        "hotspots": hotspots,
        "completion": {"total": len(pairs), "completed": done,
                       "percent": round(done / len(pairs) * 100) if pairs else (100 if subs else 0)},
    }


async def _previous_cycle(cycle: dict) -> Optional[dict]:
    """A pulse re-score is compared with the cycle it re-scores; a regular cycle with the last
    regular one (a pulse covers only a few departments, so it is not a baseline)."""
    if cycle.get("cycle_type") == "pulse" and cycle.get("pulse_of"):
        from bson import ObjectId as _O
        try:
            return await get_collection("idf_cycles").find_one({"_id": _O(cycle["pulse_of"])})
        except Exception:
            return None
    rows = await get_collection("idf_cycles").find(
        {"company_id": cycle["company_id"], "status": "Completed", "period": {"$lt": cycle.get("period") or ""}}
    ).sort("period", -1).to_list(50)
    rows = [c for c in rows if c.get("cycle_type") != "pulse"]
    return rows[0] if rows else None


async def analyse(cycle: dict, with_previous: bool = True) -> dict:
    prev = await _previous_cycle(cycle) if with_previous else None
    prev_result = compute(prev, await submissions_for(prev)) if prev else None
    return compute(cycle, await submissions_for(cycle), prev_result)


# ─────────────────────────────────────────────────────────────
# Action plans (document §7–§8)
# ─────────────────────────────────────────────────────────────
async def generate_actions(cycle: dict) -> int:
    """Create the cycle's action plan from its scores. Idempotent: re-running for a cycle
    replaces only the actions the system generated and nobody has touched yet."""
    from app.services.idf_service import departments as master_departments, company_mds, _name
    res = await analyse(cycle)
    heads = {d["id"]: d for d in await master_departments(cycle["company_id"])}
    done_at = cycle.get("completed_at") or datetime.now(timezone.utc)
    base = (done_at if isinstance(done_at, datetime) else datetime.now(timezone.utc)).date()
    mds = await company_mds(cycle["company_id"])
    md = {"id": str(mds[0]["_id"]), "name": _name(mds[0])} if mds else None
    coll = get_collection(COLL_ACTIONS)
    await coll.delete_many({"cycle_id": str(cycle["_id"]), "auto": True, "touched": {"$ne": True}})
    # Actions someone has already worked on are kept (above) — never generate a second copy of
    # one of them when the cycle completes again (e.g. after departments were added).
    kept = {_action_key(a) for a in await coll.find({"cycle_id": str(cycle["_id"])}).to_list(1000)}
    docs = [d for d in build_actions(cycle, res, heads, base, md) if _action_key(d) not in kept]
    if docs:
        await coll.insert_many(docs)
    return len(docs)


def _action_key(a: dict) -> tuple:
    """Which improvement item an action is: its type, the department and who gave the feedback."""
    return (a.get("type"), a.get("department_id"), a.get("department"), a.get("feedback_from"))


def build_actions(cycle: dict, res: dict, heads: dict, base: date, md: Optional[dict] = None) -> List[dict]:
    """The action plan for one cycle's results (pure — tested directly)."""
    def make(dept_id, dept_name, from_name, parameter, score, band_, kind, summary, days, review_days,
             drop=False, coach=None, company=False):
        head = heads.get(dept_id) or {}
        target = (base + timedelta(days=days)).isoformat()
        rescore = (base + timedelta(days=30)).isoformat() if band_ == RED else None
        owner_id, owner_name = (md["id"], md["name"]) if company and md else (head.get("head_user_id"), head.get("head_name"))
        return {"stage": stage(band_), "category": CATEGORY.get(band_),
                "led_by": "MD with all HODs" if company else LED_BY.get(band_),
                "response_time": RESPONSE_TIME.get(band_),
                "steps": _steps(band_, dept=dept_name, weakest=parameter, lowest=from_name, target=target,
                                rescore=rescore, drop=drop, coach=coach, company=company),
                "process_fix": None, "coach_department": coach,
                "company_id": cycle["company_id"], "cycle_id": str(cycle["_id"]), "period": cycle.get("period"),
                "department_id": dept_id, "department": dept_name, "feedback_from": from_name,
                "parameter": parameter, "current_score": score, "band": band_, "type": kind,
                "improvement_action": summary,
                "owner_user_id": owner_id, "owner_name": owner_name,
                "target_date": target,
                "review_date": (base + timedelta(days=review_days)).isoformat(),
                "review_every_days": review_days,
                "rescore_date": rescore,
                "status": "Open", "remarks": [], "auto": True, "touched": False,
                "created_at": datetime.now(timezone.utc)}

    docs = []
    c = res["company"]
    if c.get("band") == RED:        # company below 60%: the MD leads a company-wide repair with all HODs
        docs.append(make(None, "Company", None, c.get("weakest_param"), c["pct"], RED, "Company-wide repair",
                         "Company below 60%: the MD leads a company-wide repair session with all HODs.", 7, 7,
                         company=True))
    for h in res["hotspots"]:                              # every relationship below 60% → Red repair
        docs.append(make(h["to_id"], h["to"], h["from"], h["weakest"], h["pct"], RED,
                         "Relationship repair", RED_STEPS, 7, 7))
    hot_depts = {h["to_id"] for h in res["hotspots"]}
    scored = [d for d in res["departments"] if d["pct"] is not None]
    # Green departments coach the weakest Amber/Red ones (one each, round-robin).
    weak = sorted((d for d in scored if d["band"] in (RED, AMBER)), key=lambda d: d["pct"])
    greens = sorted((d for d in scored if d["band"] == GREEN), key=lambda d: -d["pct"])
    coach_of = {g["id"]: weak[i % len(weak)]["name"] for i, g in enumerate(greens)} if weak else {}
    for d in scored:
        if d["band"] == RED and d["id"] not in hot_depts:
            docs.append(make(d["id"], d["name"], d["lowest_rater"], d["weakest_param"], d["pct"], RED,
                             "Department repair", RED_STEPS, 7, 7))
        elif d["band"] == AMBER:
            docs.append(make(d["id"], d["name"], d["lowest_rater"], d["weakest_param"], d["pct"], AMBER,
                             "Strengthen", AMBER_STEPS, 15, 14))
        elif d["band"] == GREEN:
            if d["dropped"]:
                docs.append(make(d["id"], d["name"], d["lowest_rater"], d["weakest_param"], d["pct"], AMBER,
                                 "Strengthen (score drop)", DROP_STEPS, 15, 14, drop=True))
            docs.append(make(d["id"], d["name"], None, None, d["pct"], GREEN, "Sustain", GREEN_STEPS, 30, 30,
                             coach=coach_of.get(d["id"])))
    return docs


def _action_out(a: dict) -> dict:
    a = dict(a)
    a["id"] = str(a.pop("_id"))
    a["overdue"] = a.get("status") != "Closed" and bool(a.get("target_date")) and \
        a["target_date"] < date.today().isoformat()
    # The weekly / fortnightly review has come round and no update has been given since.
    a["review_due"] = a.get("status") != "Closed" and bool(a.get("review_date")) and \
        a["review_date"] <= date.today().isoformat()
    return a


async def _actions_scope(user: dict, company_id: Optional[str]) -> tuple:
    """MD → everything in their company; TPS Coordinator (Sparsh Admin) → a company they pick;
    anyone else → only the actions they own."""
    from app.services.idf_service import is_md, user_company_id, _is_staff_admin
    if _is_staff_admin(user):
        if not company_id:
            raise HTTPException(status_code=400, detail="Choose a company.")
        return {"company_id": str(company_id)}, "coordinator"
    cid = await user_company_id(user)
    if is_md(user) and cid:
        return {"company_id": cid}, "md"
    # The named owner, and every HOD (from Team) of the department the action is for.
    from app.services.idf_service import _my_dept_ids
    uid = str(user.get("_id") or "")
    mine = list(await _my_dept_ids(user, cid)) if cid else []
    return ({"$or": [{"owner_user_id": uid}, {"company_id": cid, "department_id": {"$in": mine}}]}
            if mine else {"owner_user_id": uid}), "owner"


async def list_actions(user: dict, company_id: Optional[str], filters: dict) -> dict:
    q, role = await _actions_scope(user, company_id)
    for k in ("cycle_id", "status", "band"):
        if filters.get(k):
            q[k] = str(filters[k])
    rows = await get_collection(COLL_ACTIONS).find(q).sort([("period", -1), ("band", 1)]).to_list(2000)
    out = [_action_out(a) for a in rows]
    summary = {"open": sum(1 for a in out if a["status"] != "Closed"),
               "overdue": sum(1 for a in out if a["overdue"]),
               "review_due": sum(1 for a in out if a["review_due"]),
               "closed": sum(1 for a in out if a["status"] == "Closed")}
    people = []
    if role == "md":          # who the MD can make an action owner
        from app.services.idf_service import company_people, _name
        people = sorted(({"id": str(u["_id"]), "name": _name(u)} for u in await company_people(q["company_id"])),
                        key=lambda p: (p["name"] or "").lower())
    # An HOD also sees — read-only, without scores — the plans for the departments their own
    # department RATED, so a rater (e.g. Sales rating IT) can follow what its feedback led to.
    from_us = []
    if role == "owner":
        from app.services.idf_service import user_company_id, _my_dept_ids
        cid = await user_company_id(user)
        mine = await _my_dept_ids(user, cid) if cid else set()
        if mine:
            own_ids = {a["id"] for a in out}
            rated: Dict[str, set] = {}
            for c in await get_collection("idf_cycles").find({"company_id": cid}).to_list(500):
                got = {p["receiver_dept_id"] for p in c.get("pairs") or [] if p["giver_dept_id"] in mine}
                if got:
                    rated[str(c["_id"])] = got
            for a in await get_collection(COLL_ACTIONS).find(
                    {"company_id": cid, "cycle_id": {"$in": list(rated)}}).sort([("period", -1), ("band", 1)]).to_list(2000):
                if a.get("department_id") in rated.get(a["cycle_id"], set()) and str(a["_id"]) not in own_ids:
                    o = _action_out(a)
                    for k in ("current_score", "rescore_pct", "remarks"):       # scores stay with the MD
                        o.pop(k, None)
                    o["read_only"] = True
                    from_us.append(o)
    return {"actions": out, "summary": summary, "role": role, "people": people, "from_our_feedback": from_us}


async def update_action(user: dict, company_id: Optional[str], action_id: str, payload: dict) -> dict:
    from app.services.idf_service import _oid, audit, _name
    q, role = await _actions_scope(user, company_id)
    oid = _oid(action_id)
    a = oid and await get_collection(COLL_ACTIONS).find_one({"_id": oid, **q})
    if not a:
        raise HTTPException(status_code=404, detail="Action not found.")
    updates: dict = {"touched": True, "updated_at": datetime.now(timezone.utc)}
    if payload.get("status") is not None:
        if payload["status"] not in ACTION_STATUSES:
            raise HTTPException(status_code=422, detail="Status must be Open, In Progress or Closed.")
        updates["status"] = payload["status"]
        if payload["status"] == "Closed" and a.get("status") != "Closed":
            updates["closed_at"] = datetime.now(timezone.utc)
            updates["closed_by"] = _name(user)
        elif payload["status"] != "Closed" and a.get("status") == "Closed":
            updates["closed_at"], updates["closed_by"] = None, None      # reopened
    if payload.get("process_fix") is not None:          # Amber: the one process fix agreed
        fix = str(payload["process_fix"] or "").strip()
        if fix and fix not in PROCESS_FIXES:
            raise HTTPException(status_code=422, detail="Choose a process fix from the list.")
        updates["process_fix"] = fix or None
    note = str(payload.get("remark") or "").strip()[:1000]
    if role == "md":   # the MD can reshape the plan itself
        for f in ("improvement_action", "target_date", "review_date"):
            if payload.get(f) is not None:
                updates[f] = str(payload[f]).strip()[:1000]
        if payload.get("owner_user_id") is not None:
            from app.utils.hrms_access import tenant_member
            owner = str(payload["owner_user_id"] or "") or None
            if owner:
                u = await tenant_member(a["company_id"], owner, {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1})
                if not u:
                    raise HTTPException(status_code=422, detail="That person is not in this company.")
                updates["owner_name"] = _name(u)
            updates["owner_user_id"] = owner
    elif any(payload.get(f) is not None for f in ("improvement_action", "target_date", "owner_user_id")):
        raise HTTPException(status_code=403, detail="Only the MD can change the action, owner or target date.")
    if note or payload.get("status"):
        # Each update advances the next review by the action's cadence (weekly / fortnightly).
        every = int(a.get("review_every_days") or 14)
        updates.setdefault("review_date", (date.today() + timedelta(days=every)).isoformat())
    ops = {"$set": updates}
    if note:
        ops["$push"] = {"remarks": {"text": note, "by": _name(user), "at": datetime.now(timezone.utc),
                                    "status": updates.get("status", a.get("status"))}}
    await get_collection(COLL_ACTIONS).update_one({"_id": oid}, ops)
    await audit(a["company_id"], user, "action updated", {"action_id": action_id, "status": updates.get("status")})
    return _action_out(await get_collection(COLL_ACTIONS).find_one({"_id": oid}))


async def delete_action(user: dict, company_id: Optional[str], action_id: str) -> dict:
    """MD, Client Admin or Super Admin: remove an action plan item that no longer applies."""
    from app.services.idf_service import _oid, assert_can_delete, audit
    oid = _oid(action_id)
    a = oid and await get_collection(COLL_ACTIONS).find_one({"_id": oid})
    if not a:
        raise HTTPException(status_code=404, detail="Action not found.")
    cid = await assert_can_delete(user, a["company_id"])
    from app.services.idf_meetings import delete_meeting_of
    await delete_meeting_of(a)
    await get_collection(COLL_ACTIONS).delete_one({"_id": oid})
    await audit(cid, user, "action deleted", {"action_id": action_id, "department": a.get("department"),
                                              "type": a.get("type")})
    return {"ok": True}


async def alert_overdue_actions() -> int:
    """Daily: email owners of overdue actions — at most every 3 days per action."""
    from app.services.idf_service import company_people
    today = date.today()
    sent = 0
    rows = await get_collection(COLL_ACTIONS).find(
        {"status": {"$ne": "Closed"}, "target_date": {"$lt": today.isoformat()},
         "owner_user_id": {"$ne": None}}).to_list(2000)
    people_cache: Dict[str, dict] = {}
    for a in rows:
        last = a.get("last_overdue_alert")
        if last and (today - date.fromisoformat(last)).days < 3:
            continue
        cid = a["company_id"]
        if cid not in people_cache:
            people_cache[cid] = {str(u["_id"]): u for u in await company_people(cid)}
        owner = people_cache[cid].get(str(a["owner_user_id"]))
        if not owner or not owner.get("email"):
            continue
        from app.services.idf_process import idf_mail      # wording: Notification Templates
        if await idf_mail(owner, "idf_action_overdue", {
                "department": a["department"], "action_type": a.get("type"),
                "target_date": a["target_date"], "status": a.get("status")}, cid):
            sent += 1
        await get_collection(COLL_ACTIONS).update_one({"_id": a["_id"]},
                                                      {"$set": {"last_overdue_alert": today.isoformat()}})
    from app.services.idf_meetings import alert_meetings_not_booked
    return sent + await _alert_reviews_due(today) + await alert_meetings_not_booked(today)


async def _alert_reviews_due(today: date) -> int:
    """Weekly (Red) / fortnightly (Amber) review: when an action's review date comes round, its
    owner is asked once for a progress update. Updating it moves the review date on."""
    from app.services.idf_service import company_people
    sent = 0
    rows = await get_collection(COLL_ACTIONS).find(
        {"status": {"$ne": "Closed"}, "review_date": {"$lte": today.isoformat()},
         "owner_user_id": {"$ne": None}}).to_list(2000)
    people_cache: Dict[str, dict] = {}
    for a in rows:
        if a.get("last_review_alert") == a["review_date"]:
            continue                                   # already asked for this review
        cid = a["company_id"]
        if cid not in people_cache:
            people_cache[cid] = {str(u["_id"]): u for u in await company_people(cid)}
        owner = people_cache[cid].get(str(a["owner_user_id"]))
        if owner and owner.get("email"):
            from app.services.idf_process import idf_mail  # wording: Notification Templates
            every = "weekly" if int(a.get("review_every_days") or 14) <= 7 else "fortnightly"
            if await idf_mail(owner, "idf_action_review_due", {
                    "department": a["department"], "action_type": a.get("type"),
                    "review_cadence": every, "review_date": a["review_date"]}, cid):
                sent += 1
        await get_collection(COLL_ACTIONS).update_one({"_id": a["_id"]},
                                                      {"$set": {"last_review_alert": a["review_date"]}})
    return sent


# ─────────────────────────────────────────────────────────────
# MD dashboard (document §9)
# ─────────────────────────────────────────────────────────────
async def md_dashboard(user: dict, cycle_id: Optional[str], company_id: Optional[str] = None) -> dict:
    from app.services.idf_service import assert_md, _oid
    cid = await assert_md(user, company_id)
    cycles = await get_collection("idf_cycles").find(
        {"company_id": cid, "status": {"$ne": "Cancelled"}}).sort("period", -1).to_list(100)
    if not cycles:
        return {"cycles": [], "result": None, "trend": [], "actions": {"open": 0, "overdue": 0, "closed": 0}}
    chosen = next((c for c in cycles if str(c["_id"]) == str(cycle_id)), None) if cycle_id else None
    chosen = chosen or next((c for c in cycles if c["status"] == "Completed"), cycles[0])
    result = await analyse(chosen)
    # Department-wise trend across the last 6 completed cycles (oldest → newest).
    trend = []
    for c in sorted([c for c in cycles if c["status"] == "Completed" and c.get("cycle_type") != "pulse"],
                    key=lambda c: c["period"])[-6:]:
        r = compute(c, await submissions_for(c))
        trend.append({"period": c["period"], "company_pct": r["company"]["pct"],
                      "departments": {d["name"]: d["pct"] for d in r["departments"]}})
    acts = (await list_actions(user, cid, {"cycle_id": str(chosen["_id"])}))["summary"]
    from app.services import idf_process as P
    stage_ = (result.get("company") or {}).get("stage")
    return {"cycles": [{"id": str(c["_id"]), "name": c.get("name"), "period": c.get("period"),
                        "status": c.get("status"), "source": c.get("source"),
                        "report_sent_at": c.get("report_sent_at")} for c in cycles],
            "result": result, "trend": trend, "actions": acts,
            "leadership_focus": P.LEADERSHIP_FOCUS.get(stage_), "no_retaliation": P.NO_RETALIATION,
            "responses": await P.responses_summary(cid, str(chosen["_id"])),
            "issues": await P.issues_summary(cid),
            "results_meeting_date": chosen.get("results_meeting_date"),
            "pulse": await P.pulse_suggestion(cid)}
