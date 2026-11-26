"""Inter-Departmental Feedback (IDF) — core: roles, setup, cycles, the feedback form, calendar
activities with locked completion, monitoring and reminders.

Built to the client's "Inter-Departmental Feedback Management System" requirement document
(docs/hrms/Inter Dep Feedbak Process Development.docx), which takes priority over anything
said earlier. Scoring / RAG / action plans live in idf_analysis.py; Excel, PDF and the MD
email in idf_reports.py.

-- Who does what (document §11 + roles table) ---------------------------------------------
* Department HOD (the rater)  — fills the forms for the departments their department depends
                                 on. Departments come from the master list (HRMS ▸ Departments);
                                 the HOD comes from Team: a member whose Department is that
                                 department and whose Designation is HOD.
* HR / Admin                  — set the parameters and deadlines, start feedback cycles —
                                 choosing, per cycle, which departments are reviewed and which
                                 departments give feedback about each — and see STATUS only.
                                 HR never receives the consolidated report (document §10).
* MD                          — everything: the complete dashboard, all scores, reports,
                                 Excel import/export and action plans.
* Action owner                — their own improvement actions (idf_analysis).
* TPS Coordinator (Sparsh)    — monitors action plans (idf_analysis).

-- Confidentiality --------------------------------------------------------------------------
Individual rater identities never appear in departmental reports: reports and the dashboard
speak in departments ("Sales → HR"), not people. Feedback content is served to the MD only;
HR/Admin get counts and pending lists. The email log records that a report was sent, never
its content.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection

COLL_SETTINGS = "idf_settings"
COLL_CYCLES = "idf_cycles"
COLL_SUBMISSIONS = "idf_submissions"
COLL_AUDIT = "idf_audit"
COLL_LINKS = "idf_links"                  # personal form links emailed to each HOD
LINK_SENT, LINK_OPENED, LINK_SUBMITTED, LINK_CLOSED = "Sent", "Opened", "Submitted", "Closed"
COLL_DEPARTMENTS = "hrms_departments"     # the master department list

EVENT_KIND = "idf_feedback"               # calendar activities created for raters
STAFF_ADMIN_ROLES = {"superadmin", "admin"}
RATING_MIN, RATING_MAX = 1, 5

# Document §3A — the four parameters (configurable per company). `question` is what the HOD
# sees on the form (the requirement document's wording); `report_question` is the wording of the
# client's Compiled Excel sample, used in that Excel so it keeps matching the sample.
DEFAULT_PARAMETERS = [
    {"code": "information", "name": "Information",
     "question": "How clearly and accurately does the department share the information you need?",
     "report_question": "Rate how clearly and accurately Department shares the information you need, when you need it."},
    {"code": "planning", "name": "Planning",
     "question": "Does the department provide timely updates so you can plan your work?",
     "report_question": "Rate how early Department gives you notice or updates so you have time to plan your own work."},
    {"code": "task_closure", "name": "Task Closure",
     "question": "Does the department complete requests within agreed timelines without repeated follow-ups?",
     "report_question": "Rate how consistently Department closes your requests within the agreed timeline, without repeated follow-ups from your side."},
    {"code": "ownership", "name": "Coordination & Ownership",
     "question": "Does the department take ownership of resolving issues without escalation?",
     "report_question": "Rate how much ownership Department takes to resolve issues on its own, without you having to escalate."},
]
_DEFAULT_BY_CODE = {p["code"]: p for p in DEFAULT_PARAMETERS}
RATING_LABELS = {1: "Poor", 2: "Below Average", 3: "Average", 4: "Good", 5: "Excellent"}
DEFAULT_COMMENT_REQUIRED = [1, 2, 5]      # document §3C
DEFAULT_DEADLINE_DAYS = 7
DEFAULT_REMINDER_DAYS_BEFORE = 2

STATUS_SCHEDULED, STATUS_PENDING = "Scheduled", "Pending"
STATUS_OVERDUE, STATUS_COMPLETED = "Overdue", "Completed"
CYCLE_OPEN, CYCLE_COMPLETED, CYCLE_CANCELLED = "Open", "Completed", "Cancelled"

_IST = timezone(timedelta(hours=5, minutes=30))


def today_ist() -> date:
    return datetime.now(timezone.utc).astimezone(_IST).date()


def _oid(value) -> Optional[ObjectId]:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        return None


def _name(u: Optional[dict]) -> str:
    if not u:
        return ""
    return (u.get("full_name") or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            or u.get("email") or "")


def _gov(u: dict) -> str:
    return (u.get("governance_role") or "").strip().upper()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────
# Who is who
# ─────────────────────────────────────────────────────────────
async def user_company_id(user: dict) -> str:
    if user.get("company_id"):
        return str(user["company_id"])
    from app.utils.hrms_access import internal_company_id
    return await internal_company_id() or ""


async def company_people(company_id: str) -> List[dict]:
    from app.utils.hrms_access import tenant_identity_source
    coll, base = await tenant_identity_source(company_id)
    return await get_collection(coll).find({**base, "is_active": {"$ne": False}}).to_list(5000)


async def company_mds(company_id: str) -> List[dict]:
    return [u for u in await company_people(company_id) if _gov(u) == "MD"]


def is_md(user: dict) -> bool:
    return _gov(user) == "MD"


def _is_staff_admin(user: dict) -> bool:
    return (user.get("role") or "").lower() in STAFF_ADMIN_ROLES


def _is_manager_in_company(user: dict) -> bool:
    """HR / Admin of the company (and the MD, who may do everything)."""
    return _gov(user) in {"HR", "MD"} or (user.get("role") or "").lower() == "clientadmin"


async def _company_for(user: dict, company_id: Optional[str]) -> str:
    """A Sparsh Admin names the company; everyone else is pinned to their own."""
    if _is_staff_admin(user) and company_id:
        return str(company_id)
    cid = await user_company_id(user)
    if not cid:
        raise HTTPException(status_code=400, detail="Choose a company.")
    return cid


async def assert_manager(user: dict, company_id: Optional[str]) -> str:
    """HR / Admin / MD of the company, or a Sparsh Admin: setup, cycles and status."""
    cid = await _company_for(user, company_id)
    if _is_staff_admin(user):
        return cid
    if _is_manager_in_company(user) and await user_company_id(user) == cid:
        return cid
    raise HTTPException(status_code=403,
                        detail="Only HR, the company Admin or the MD can manage Inter-Departmental Feedback.")


async def assert_md(user: dict, company_id: Optional[str] = None) -> str:
    """The gate in front of feedback CONTENT, scores and reports: the company MD — and the Sparsh
    Super Admin / Admin, who may open any company's (they name it)."""
    if _is_staff_admin(user):
        if not company_id:
            raise HTTPException(status_code=400, detail="Choose a company.")
        return str(company_id)
    if not is_md(user):
        raise HTTPException(status_code=403,
                            detail="The Inter-Departmental Feedback dashboard and reports are for the MD only.")
    cid = await user_company_id(user)
    if not cid:
        raise HTTPException(status_code=403, detail="The dashboard and reports are for the MD only.")
    return cid


async def audit(company_id: str, user: Optional[dict], action: str, detail: dict) -> None:
    """Document §12 audit trail — what happened, by whom, when. Never feedback content."""
    try:
        await get_collection(COLL_AUDIT).insert_one({
            "company_id": company_id, "action": action, "detail": detail, "at": _now(),
            "by": str((user or {}).get("_id") or "system"), "by_name": _name(user) or "System"})
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Departments (master) and settings
# ─────────────────────────────────────────────────────────────
def is_team_hod(u: dict) -> bool:
    """HOD as defined in Team: the member's Designation is HOD (the role-style dropdown,
    stored in `department`) or their governance role is HOD."""
    return (str(u.get("department") or "").strip().upper() == "HOD") or _gov(u) == "HOD"


async def departments(company_id: str) -> List[dict]:
    """Master departments with their HOD(s) from Team: members whose Department is that
    department and whose Designation is HOD. A head set on the master record is used only
    when Team names nobody."""
    rows = await get_collection(COLL_DEPARTMENTS).find(
        {"company_id": str(company_id), "active": {"$ne": False}}).to_list(500)
    people = await company_people(company_id)
    by_id = {str(u["_id"]): u for u in people}
    team_heads: Dict[str, List[dict]] = {}
    for u in people:
        if u.get("department_id") and is_team_hod(u):
            team_heads.setdefault(str(u["department_id"]), []).append(u)
    out = []
    for d in sorted(rows, key=lambda r: (r.get("name") or "").lower()):
        heads = team_heads.get(str(d["_id"])) or (
            [by_id[str(d["head_user_id"])]] if by_id.get(str(d.get("head_user_id") or "")) else [])
        heads = sorted(heads, key=lambda u: _name(u).lower())
        out.append({"id": str(d["_id"]), "name": d.get("name") or "",
                    "heads": [{"id": str(u["_id"]), "name": _name(u), "email": u.get("email")} for u in heads],
                    # First HOD — the default owner of the department's improvement actions.
                    "head_user_id": str(heads[0]["_id"]) if heads else None,
                    "head_name": _name(heads[0]) if heads else None,
                    "head_email": heads[0].get("email") if heads else None})
    return out


def _clean_parameters(raw) -> List[dict]:
    out, seen = [], set()
    for p in raw or []:
        name = str((p or {}).get("name") or "").strip()
        if not name:
            continue
        code = str((p or {}).get("code") or "").strip() or name.lower().replace(" ", "_").replace("&", "and")
        if code in seen:
            raise HTTPException(status_code=422, detail=f"Two parameters share the code '{code}'.")
        seen.add(code)
        question = str((p or {}).get("question") or "").strip()[:300] or name
        row = {"code": code[:40], "name": name[:60], "question": question}
        # A standard question left as it is keeps the sample's report wording; an edited or new
        # question is used in the Excel as written.
        std = _DEFAULT_BY_CODE.get(code)
        if std and question == std["question"]:
            row["report_question"] = std["report_question"]
        out.append(row)
    return out


async def settings(company_id: str) -> dict:
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)}) or {}
    return {
        # The review mapping is chosen per cycle; the last one pre-fills the next cycle.
        "last_reviews": doc.get("last_reviews") or [],
        "parameters": doc.get("parameters") or [dict(p) for p in DEFAULT_PARAMETERS],
        "deadline_days": int(doc.get("deadline_days") or DEFAULT_DEADLINE_DAYS),
        "reminder_days_before": int(doc.get("reminder_days_before") if doc.get("reminder_days_before") is not None
                                    else DEFAULT_REMINDER_DAYS_BEFORE),
        "comment_required_for": doc.get("comment_required_for") or list(DEFAULT_COMMENT_REQUIRED),
        # The 1–5 scale's labels (configurable); the score stays (average ÷ 5) × 100.
        "rating_labels": doc.get("rating_labels") or [RATING_LABELS[i] for i in range(1, 6)],
        # Setup ▸ Results meeting (time, length, days after results, type, link, venue).
        "meeting": _process().meeting_settings(doc),
    }


def _labels(src: dict) -> Dict[int, str]:
    """{1: 'Poor', …, 5: 'Excellent'} from a cycle's (or settings') stored label list."""
    lst = (src or {}).get("rating_labels") or []
    return {i: (lst[i - 1] if len(lst) >= i and lst[i - 1] else RATING_LABELS[i]) for i in range(1, 6)}


async def get_setup(user: dict, company_id: Optional[str]) -> dict:
    """The rules only: parameters, deadline, reminders, comment rule. HODs come from Team and
    the review mapping is chosen when a cycle is started."""
    cid = await assert_manager(user, company_id)
    st = await settings(cid)
    mds = await company_mds(cid)
    return {
        "company_id": cid,
        "parameters": st["parameters"], "deadline_days": st["deadline_days"],
        "reminder_days_before": st["reminder_days_before"],
        "comment_required_for": st["comment_required_for"],
        "rating_labels": st["rating_labels"],
        "meeting": st["meeting"],
        "has_cycles": bool(await get_collection(COLL_CYCLES).find_one(
            {"company_id": cid, "status": CYCLE_COMPLETED}, {"_id": 1})),
        "md_count": len(mds), "md_names": [_name(u) for u in mds],
    }


async def save_setup(user: dict, company_id: Optional[str], payload: dict) -> dict:
    cid = await assert_manager(user, company_id)
    params = _clean_parameters(payload.get("parameters")) if payload.get("parameters") is not None \
        else (await settings(cid))["parameters"]
    if not params:
        raise HTTPException(status_code=422, detail="Keep at least one feedback parameter.")
    if len(params) > 10:
        raise HTTPException(status_code=422, detail="At most 10 parameters.")
    try:
        deadline_days = int(payload.get("deadline_days") or DEFAULT_DEADLINE_DAYS)
        before = int(payload.get("reminder_days_before") if payload.get("reminder_days_before") is not None
                     else DEFAULT_REMINDER_DAYS_BEFORE)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Deadline and reminder days must be whole numbers.")
    if not 1 <= deadline_days <= 60 or not 0 <= before <= 30:
        raise HTTPException(status_code=422, detail="Deadline 1–60 days; reminder 0–30 days before.")
    req = sorted({int(x) for x in (payload.get("comment_required_for") or DEFAULT_COMMENT_REQUIRED)
                  if str(x).isdigit() and RATING_MIN <= int(x) <= RATING_MAX})
    labels = payload.get("rating_labels")
    if labels is None:
        labels = (await settings(cid))["rating_labels"]
    labels = [str(x or "").strip()[:30] for x in labels] if isinstance(labels, list) else []
    if len(labels) != 5 or not all(labels):
        raise HTTPException(status_code=422, detail="Give a label for each rating 1 to 5.")
    now = _now()
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": cid},
        {"$set": {"company_id": cid, "parameters": params, "rating_labels": labels,
                  "meeting": _process().clean_meeting_settings(payload.get("meeting") or (await settings(cid))["meeting"]),
                  "deadline_days": deadline_days, "reminder_days_before": before,
                  "comment_required_for": req, "updated_at": now, "updated_by": str(user.get("_id") or "")},
         "$setOnInsert": {"created_at": now}}, upsert=True)
    await audit(cid, user, "setup saved", {"parameters": len(params)})
    return await get_setup(user, cid)


# ─────────────────────────────────────────────────────────────
# Access summary (drives the menu)
# ─────────────────────────────────────────────────────────────
async def access(user: dict) -> dict:
    cid = await user_company_id(user)
    uid = str(user.get("_id") or "")
    is_hod = bool(cid and uid and (await _my_dept_ids(user, cid) or await get_collection(COLL_CYCLES).count_documents(
        {"company_id": cid, "status": CYCLE_OPEN, "pairs.rater_user_ids": uid})))
    from app.services.idf_analysis import COLL_ACTIONS
    mine = list(await _my_dept_ids(user, cid)) if cid and uid else []
    has_actions = bool(uid and await get_collection(COLL_ACTIONS).count_documents(
        {"$or": [{"owner_user_id": uid}, {"company_id": cid, "department_id": {"$in": mine}}]}
        if mine else {"owner_user_id": uid}))
    staff_admin = _is_staff_admin(user)
    return {
        "is_hod": is_hod,
        "is_md": is_md(user) and bool(cid),
        "can_manage": staff_admin or (bool(cid) and _is_manager_in_company(user)),
        "has_actions": has_actions,
        "is_coordinator": staff_admin,            # TPS Coordinator (Sparsh): monitors action plans
        "can_raise": bool(cid) or staff_admin,    # the open feedback channel — anyone can raise an issue
        "can_delete": can_delete(user),           # MD, Client Admin, Super Admin
    }


# ─────────────────────────────────────────────────────────────
# Cycles
# ─────────────────────────────────────────────────────────────
def _cycle_out(c: dict) -> dict:
    c = dict(c)
    c["id"] = str(c.pop("_id"))
    return c


async def _get_cycle(company_id: str, cycle_id: str) -> dict:
    oid = _oid(cycle_id)
    c = oid and await get_collection(COLL_CYCLES).find_one({"_id": oid, "company_id": company_id})
    if not c:
        raise HTTPException(status_code=404, detail="Feedback cycle not found.")
    return c


async def _rater_collection(rater_user_id: str) -> str:
    from app.utils.calendar_utils import get_target_collection_name
    return await get_target_collection_name({"assigned_member_ids": [rater_user_id]})


def _clean_reviews(payload: dict, depts: Dict[str, dict]) -> List[dict]:
    """The cycle's review mapping: [{receiver_dept_id, giver_dept_ids: [...]}] — the
    department under review and the departments that give feedback about it."""
    out, seen = [], set()
    for rv in payload.get("reviews") or []:
        r = str((rv or {}).get("receiver_dept_id") or "")
        if r not in depts:
            raise HTTPException(status_code=422, detail="A reviewed department does not exist.")
        if r in seen:
            raise HTTPException(status_code=422, detail=f"{depts[r]['name']} is listed twice — review it once.")
        seen.add(r)
        givers = []
        for g in (rv or {}).get("giver_dept_ids") or []:
            g = str(g)
            if g not in depts:
                raise HTTPException(status_code=422, detail="A rating department does not exist.")
            if g == r:
                raise HTTPException(status_code=422, detail=f"{depts[r]['name']} cannot rate itself.")
            if g not in givers:
                givers.append(g)
        if not givers:
            raise HTTPException(status_code=422,
                                detail=f"Choose at least one department to give feedback about {depts[r]['name']}.")
        out.append({"receiver_dept_id": r, "giver_dept_ids": givers})
    if not out:
        raise HTTPException(status_code=422, detail="Add at least one department to review.")
    return out


async def cycle_options(user: dict, company_id: Optional[str]) -> dict:
    """For the Start-cycle dialog: departments with their HOD(s) from Team, the default
    deadline, and the previous cycle's review mapping to pre-fill."""
    cid = await assert_manager(user, company_id)
    st = await settings(cid)
    depts = await departments(cid)
    valid = {d["id"] for d in depts}
    last = [{"receiver_dept_id": rv["receiver_dept_id"],
             "giver_dept_ids": [g for g in rv["giver_dept_ids"] if g in valid]}
            for rv in st["last_reviews"] if rv.get("receiver_dept_id") in valid]
    return {"departments": [{"id": d["id"], "name": d["name"], "heads": d["heads"]} for d in depts],
            "last_reviews": [rv for rv in last if rv["giver_dept_ids"]],
            "deadline_days": st["deadline_days"]}


def _new_pair(g: dict, r: dict) -> dict:
    """One form of a cycle: department `g` gives feedback about department `r`."""
    return {"giver_dept_id": g["id"], "giver_name": g["name"],
            "receiver_dept_id": r["id"], "receiver_name": r["name"],
            # Every HOD of the giving department may fill it; the first submission counts.
            "raters": g["heads"], "rater_user_ids": [h["id"] for h in g["heads"]],
            "rater_user_id": g["heads"][0]["id"], "rater_name": ", ".join(h["name"] for h in g["heads"]),
            "rater_email": g["heads"][0]["email"], "status": STATUS_PENDING,
            "submitted_at": None, "events": [], "event_id": None, "event_coll": None,
            "last_reminder": None, "overdue_notified": False}


def _event_timing(p: dict, deadline: date) -> dict:
    return {"description": (f"Give {p['giver_name']}'s feedback about {p['receiver_name']} "
                            f"by {deadline.strftime('%d %b %Y')}. It completes automatically "
                            f"once the feedback is submitted."),
            "start": f"{deadline.isoformat()}T10:00:00", "end": f"{deadline.isoformat()}T10:30:00"}


async def _create_events(cid: str, cycle_id: str, pairs: List[dict], deadline: date, now) -> None:
    """One calendar activity per rater and department to rate (document §4A). It cannot be
    completed by hand — see guard_calendar_change and the calendar routes."""
    for p in pairs:
        for rater in p["raters"]:
            coll = await _rater_collection(rater["id"])
            ev = await get_collection(coll).insert_one({
                "kind": EVENT_KIND, "type": "event",
                "title": f"Inter-Departmental Feedback: rate {p['receiver_name']}",
                **_event_timing(p, deadline),
                "user_id": rater["id"], "assigned_member_ids": [rater["id"]],
                # Document §4D: Scheduled when created -> Pending once the HOD opens the form ->
                # Overdue after the deadline -> Completed only on stored submission.
                "company_id": cid, "status": STATUS_SCHEDULED, "idf_status": STATUS_SCHEDULED,
                "idf_cycle_id": cycle_id, "idf_giver_dept_id": p["giver_dept_id"],
                "idf_receiver_dept_id": p["receiver_dept_id"], "created_at": now})
            p["events"].append({"id": str(ev.inserted_id), "coll": coll})
        if p["events"]:
            p["event_id"], p["event_coll"] = p["events"][0]["id"], p["events"][0]["coll"]


async def _create_links(cid: str, cycle_id: str, pairs: List[dict], now) -> None:
    """A personal link per HOD per department to rate — the email carries it (like TPMS form links)."""
    import secrets
    links = [{"token": secrets.token_urlsafe(32), "company_id": cid, "cycle_id": cycle_id,
              "giver_dept_id": p["giver_dept_id"], "receiver_dept_id": p["receiver_dept_id"],
              "rater_user_id": rt["id"], "status": LINK_SENT, "created_at": now,
              "last_sent_at": None, "send_count": 0, "opened_at": None, "submitted_at": None}
             for p in pairs for rt in p["raters"]]
    if links:
        await get_collection(COLL_LINKS).insert_many(links)


async def start_cycle(user: dict, company_id: Optional[str], payload: dict) -> dict:
    """Document §4A: HR/Admin start a cycle, choosing which departments are reviewed and which
    departments give feedback about each. Every rater (the giving department's HOD from Team)
    gets a calendar activity per department to rate, and the initial notification."""
    cid = await assert_manager(user, company_id)
    if await get_collection(COLL_CYCLES).find_one({"company_id": cid, "status": CYCLE_OPEN}, {"_id": 1}):
        raise HTTPException(status_code=409,
                            detail="A feedback cycle is already open. Complete or cancel it before starting a new one.")
    st = await settings(cid)
    depts = {d["id"]: d for d in await departments(cid)}
    reviews = _clean_reviews(payload, depts)
    pairs_cfg = [{"giver_dept_id": g, "receiver_dept_id": rv["receiver_dept_id"]}
                 for rv in reviews for g in rv["giver_dept_ids"]]
    no_head = sorted({depts[p["giver_dept_id"]]["name"] for p in pairs_cfg
                      if not depts[p["giver_dept_id"]]["heads"]})
    if no_head:
        raise HTTPException(status_code=422,
                            detail=(f"No HOD in Team for: {', '.join(no_head)}. In Team, give the HOD that "
                                    f"Department and the HOD designation — the HOD fills the department's forms."))

    period = str(payload.get("period") or today_ist().strftime("%Y-%m"))[:7]
    if len(period) != 7 or period[4] != "-":
        raise HTTPException(status_code=422, detail="Cycle month must be YYYY-MM.")
    # A pulse re-score (Standard Approach: 30 days after a Red result, affected departments only,
    # same questions) may run in a month that also has a regular cycle.
    pulse = str(payload.get("cycle_type") or "") == "pulse"
    pulse_of = str(payload.get("pulse_of") or "") if pulse else ""
    if pulse and not pulse_of:
        raise HTTPException(status_code=422, detail="Say which cycle the pulse re-score follows up.")
    if pulse:
        src = await get_collection(COLL_CYCLES).find_one({"_id": _oid(pulse_of), "company_id": cid})
        if not src or src.get("status") != CYCLE_COMPLETED:
            raise HTTPException(status_code=422, detail="A pulse re-score follows up a completed cycle.")
        done = src.get("completed_at")
        done = done.date() if isinstance(done, datetime) else date.fromisoformat(str(done)[:10]) if done else today_ist()
        opens = done + timedelta(days=30)
        if today_ist() < opens:
            raise HTTPException(status_code=422, detail=(
                f"The pulse re-score opens 30 days after the results, on {opens.strftime('%d %b %Y')}."))
    same = {"company_id": cid, "period": period, "status": {"$ne": CYCLE_CANCELLED},
            "cycle_type": "pulse" if pulse else {"$ne": "pulse"}}
    if await get_collection(COLL_CYCLES).find_one(same, {"_id": 1}):
        raise HTTPException(status_code=409, detail=(f"A pulse re-score for {period} already exists." if pulse
                                                     else f"A feedback cycle for {period} already exists."))
    start = today_ist()
    try:
        deadline = (date.fromisoformat(str(payload["deadline"])[:10]) if payload.get("deadline")
                    else start + timedelta(days=st["deadline_days"]))
    except ValueError:
        raise HTTPException(status_code=422, detail="Deadline must be YYYY-MM-DD.")
    if deadline < start:
        raise HTTPException(status_code=422, detail="The deadline cannot be in the past.")

    now = _now()
    pairs = [_new_pair(depts[p["giver_dept_id"]], depts[p["receiver_dept_id"]]) for p in pairs_cfg]
    doc = {"company_id": cid, "period": period,
           "name": str(payload.get("name") or (f"Pulse re-score {period}" if pulse
                                               else f"Inter-Departmental Feedback {period}")).strip()[:120],
           "cycle_type": "pulse" if pulse else "regular", "pulse_of": pulse_of or None,
           "start_date": start.isoformat(), "deadline": deadline.isoformat(),
           "status": CYCLE_OPEN, "parameters": st["parameters"],
           "comment_required_for": st["comment_required_for"],
           "rating_labels": st["rating_labels"],
           "reminder_days_before": st["reminder_days_before"],
           "pairs": pairs, "source": "form",
           "initiated_by": str(user.get("_id") or ""), "initiated_by_name": _name(user),
           "created_at": now, "completed_at": None, "report_sent_at": None}
    res = await get_collection(COLL_CYCLES).insert_one(doc)
    cycle_id = str(res.inserted_id)

    await _create_events(cid, cycle_id, pairs, deadline, now)
    await get_collection(COLL_CYCLES).update_one({"_id": res.inserted_id}, {"$set": {"pairs": pairs, "reviews": reviews}})
    # Remember the mapping so the next cycle starts pre-filled with it (not a pulse's few pairs).
    if not pulse:
        await get_collection(COLL_SETTINGS).update_one(
            {"company_id": cid}, {"$set": {"company_id": cid, "last_reviews": reviews}}, upsert=True)
    await _create_links(cid, cycle_id, pairs, now)
    await audit(cid, user, "cycle started", {"cycle_id": cycle_id, "period": period, "pairs": len(pairs)})
    await _notify_raters(pairs, deadline, kind="start", cycle_id=cycle_id)
    return _cycle_out(await get_collection(COLL_CYCLES).find_one({"_id": res.inserted_id}))


async def add_reviews(user: dict, company_id: Optional[str], cycle_id: str, payload: dict) -> dict:
    """Add more department feedback to a cycle after it has started. The new forms get their
    calendar activity, email and personal link exactly as at the start; forms already in the
    cycle are untouched. A COMPLETED cycle reopens: when the added forms are in it completes
    again, and the MD gets a fresh report covering every department."""
    cid = await assert_manager(user, company_id)
    c = await _get_cycle(cid, cycle_id)
    if c.get("source") == "import":
        raise HTTPException(status_code=409, detail="An imported cycle cannot take new feedback forms.")
    if c["status"] not in (CYCLE_OPEN, CYCLE_COMPLETED):
        raise HTTPException(status_code=409, detail=f"This cycle is {c['status']}.")
    if c["status"] == CYCLE_COMPLETED and await get_collection(COLL_CYCLES).find_one(
            {"company_id": cid, "status": CYCLE_OPEN, "_id": {"$ne": c["_id"]}}, {"_id": 1}):
        raise HTTPException(status_code=409,
                            detail="Another feedback cycle is open. Complete or cancel it before reopening this one.")
    depts = {d["id"]: d for d in await departments(cid)}
    reviews = _clean_reviews(payload, depts)
    have = {(p["giver_dept_id"], p["receiver_dept_id"]) for p in c.get("pairs") or []}
    new_cfg = [(g, rv["receiver_dept_id"]) for rv in reviews for g in rv["giver_dept_ids"]
               if (g, rv["receiver_dept_id"]) not in have]
    if not new_cfg:
        raise HTTPException(status_code=422,
                            detail="These departments are already in this cycle — tick at least one new department.")
    no_head = sorted({depts[g]["name"] for g, _ in new_cfg if not depts[g]["heads"]})
    if no_head:
        raise HTTPException(status_code=422,
                            detail=(f"No HOD in Team for: {', '.join(no_head)}. In Team, give the HOD that "
                                    f"Department and the HOD designation — the HOD fills the department's forms."))
    try:
        deadline = date.fromisoformat(str(payload.get("deadline") or c["deadline"])[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail="Deadline must be YYYY-MM-DD.")
    if deadline < today_ist():
        raise HTTPException(status_code=422, detail="The deadline has passed — choose a new deadline.")

    now = _now()
    cycle_id = str(c["_id"])
    new_pairs = [_new_pair(depts[g], depts[r]) for g, r in new_cfg]
    await _create_events(cid, cycle_id, new_pairs, deadline, now)
    await _create_links(cid, cycle_id, new_pairs, now)
    pairs = list(c.get("pairs") or [])
    if deadline.isoformat() != c["deadline"]:
        # One deadline for the whole cycle: move the activities still pending.
        for p in pairs:
            if p.get("status") != STATUS_COMPLETED:
                await _set_events(p, _event_timing(p, deadline))
    pairs += new_pairs
    # The cycle's mapping = what it had + what was added.
    merged: Dict[str, List[str]] = {}
    for p in pairs:
        merged.setdefault(p["receiver_dept_id"], [])
        if p["giver_dept_id"] not in merged[p["receiver_dept_id"]]:
            merged[p["receiver_dept_id"]].append(p["giver_dept_id"])
    all_reviews = [{"receiver_dept_id": r, "giver_dept_ids": gs} for r, gs in merged.items()]
    fields = {"pairs": pairs, "reviews": all_reviews, "deadline": deadline.isoformat()}
    reopened = c["status"] == CYCLE_COMPLETED
    if reopened:
        fields.update({"status": CYCLE_OPEN, "completed_at": None, "reopened_at": now,
                       "report_sent_at": None, "previous_report_sent_at": c.get("report_sent_at")})
    await get_collection(COLL_CYCLES).update_one({"_id": c["_id"]}, {"$set": fields})
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": cid}, {"$set": {"company_id": cid, "last_reviews": all_reviews}}, upsert=True)
    await audit(cid, user, "cycle reopened, forms added" if reopened else "forms added to cycle",
                {"cycle_id": cycle_id, "added": len(new_pairs)})
    await _notify_raters(new_pairs, deadline, kind="start", cycle_id=cycle_id)
    out = _cycle_out(await get_collection(COLL_CYCLES).find_one({"_id": c["_id"]}))
    out["added"] = len(new_pairs)
    out["reopened"] = reopened
    return out


def _pair_events(p: dict) -> List[dict]:
    """The calendar activities of one pair — one per HOD of the giving department."""
    if p.get("events"):
        return p["events"]
    return [{"id": p["event_id"], "coll": p["event_coll"]}] if p.get("event_id") and p.get("event_coll") else []


async def _mark_pending(p: dict, uid: str) -> None:
    """The HOD has opened the form: their Scheduled activity for it becomes Pending."""
    for ev in _pair_events(p):
        await get_collection(ev["coll"]).update_one(
            {"_id": _oid(ev["id"]), "user_id": uid, "idf_status": STATUS_SCHEDULED},
            {"$set": {"status": STATUS_PENDING, "idf_status": STATUS_PENDING}})


async def _set_events(p: dict, fields: dict) -> None:
    for ev in _pair_events(p):
        await get_collection(ev["coll"]).update_one({"_id": _oid(ev["id"])}, {"$set": fields})


# ─────────────────────────────────────────────────────────────
# Delete (MD, Client Admin, Super Admin) — permanent, audited
# ─────────────────────────────────────────────────────────────
def can_delete(user: dict) -> bool:
    """Who may permanently delete Inter-Departmental Feedback records: the Super Admin, and a
    company's Client Admin or MD (their own company). HR runs cycles but cannot delete."""
    role = (user.get("role") or "").lower()
    return role == "superadmin" or role == "clientadmin" or is_md(user)


async def assert_can_delete(user: dict, company_id: str) -> str:
    if not can_delete(user):
        raise HTTPException(status_code=403, detail="Only the MD, the Client Admin or the Super Admin can delete.")
    if (user.get("role") or "").lower() != "superadmin" and await user_company_id(user) != str(company_id):
        raise HTTPException(status_code=403, detail="You can delete only your own company's records.")
    return str(company_id)


async def _cycle_footprint(c: dict) -> dict:
    """Everything that belongs to a cycle (and its pulse re-scores)."""
    from app.services.idf_analysis import COLL_ACTIONS
    from app.services.idf_process import COLL_RESPONSES
    ids = [str(c["_id"])]
    pulses = await get_collection(COLL_CYCLES).find({"pulse_of": str(c["_id"])}).to_list(50)
    ids += [str(p["_id"]) for p in pulses]
    events = sum(len(_pair_events(p)) for cyc in [c, *pulses] for p in cyc.get("pairs") or [])
    events += sum(1 for cyc in [c, *pulses] if cyc.get("results_meeting_event_id"))
    async def n(coll):
        return await get_collection(coll).count_documents({"cycle_id": {"$in": ids}})
    return {"cycle_ids": ids, "pulses": pulses, "forms": sum(len(cyc.get("pairs") or []) for cyc in [c, *pulses]),
            "submissions": await n(COLL_SUBMISSIONS), "links": await n(COLL_LINKS),
            "actions": await n(COLL_ACTIONS), "responses": await n(COLL_RESPONSES), "calendar_activities": events}


async def delete_preview(user: dict, company_id: Optional[str], cycle_id: str) -> dict:
    oid = _oid(cycle_id)
    c = oid and await get_collection(COLL_CYCLES).find_one({"_id": oid})
    if not c:
        raise HTTPException(status_code=404, detail="Feedback cycle not found.")
    await assert_can_delete(user, c["company_id"])
    f = await _cycle_footprint(c)
    return {"cycle": {"id": str(c["_id"]), "name": c.get("name"), "period": c.get("period"), "status": c.get("status"),
                      "cycle_type": c.get("cycle_type") or "regular"},
            "forms": f["forms"], "submissions": f["submissions"], "links": f["links"], "actions": f["actions"],
            "responses": f["responses"], "calendar_activities": f["calendar_activities"],
            "pulse_rescores": len(f["pulses"]), "report_sent": bool(c.get("report_sent_at"))}


async def delete_cycle(user: dict, company_id: Optional[str], cycle_id: str, confirm: str) -> dict:
    """Permanently delete a cycle with its forms, submitted feedback, links, calendar activities,
    action plans, "you said, we did" entries and pulse re-scores. Typing DELETE confirms."""
    from app.services.idf_analysis import COLL_ACTIONS
    from app.services.idf_process import COLL_RESPONSES
    if str(confirm or "").strip().upper() != "DELETE":
        raise HTTPException(status_code=422, detail="Type DELETE to confirm.")
    oid = _oid(cycle_id)
    c = oid and await get_collection(COLL_CYCLES).find_one({"_id": oid})
    if not c:
        raise HTTPException(status_code=404, detail="Feedback cycle not found.")
    cid = await assert_can_delete(user, c["company_id"])
    f = await _cycle_footprint(c)
    for cyc in [c, *f["pulses"]]:
        for p in cyc.get("pairs") or []:
            for ev in _pair_events(p):
                await get_collection(ev["coll"]).delete_one({"_id": _oid(ev["id"])})
        if cyc.get("results_meeting_event_id") and cyc.get("results_meeting_coll"):
            await get_collection(cyc["results_meeting_coll"]).delete_one({"_id": _oid(cyc["results_meeting_event_id"])})
    ids = f["cycle_ids"]
    for coll in (COLL_SUBMISSIONS, COLL_LINKS, COLL_ACTIONS, COLL_RESPONSES):
        await get_collection(coll).delete_many({"cycle_id": {"$in": ids}})
    # A deleted pulse re-score no longer stands as the re-score of an older cycle's actions.
    await get_collection(COLL_ACTIONS).update_many(
        {"rescore_cycle_id": {"$in": ids}},
        {"$set": {"rescore_pct": None, "rescore_band": None, "rescore_cycle_id": None}})
    await get_collection(COLL_CYCLES).delete_many({"_id": {"$in": [_oid(i) for i in ids]}})
    await audit(cid, user, "cycle deleted", {"cycle_id": str(c["_id"]), "period": c.get("period"),
                                             "status": c.get("status"), "forms": f["forms"],
                                             "submissions": f["submissions"], "actions": f["actions"]})
    return {"ok": True, "deleted": {k: f[k] for k in ("forms", "submissions", "links", "actions", "responses",
                                                      "calendar_activities")} | {"pulse_rescores": len(f["pulses"])}}


async def cancel_cycle(user: dict, company_id: Optional[str], cycle_id: str) -> dict:
    cid = await assert_manager(user, company_id)
    c = await _get_cycle(cid, cycle_id)
    if c["status"] != CYCLE_OPEN:
        raise HTTPException(status_code=409, detail=f"This cycle is {c['status']}.")
    await get_collection(COLL_CYCLES).update_one({"_id": c["_id"]}, {"$set": {"status": CYCLE_CANCELLED}})
    for p in c.get("pairs") or []:
        if p.get("status") != STATUS_COMPLETED:
            await _set_events(p, {"deleted_at": _now(), "idf_status": "Cancelled"})
    await audit(cid, user, "cycle cancelled", {"cycle_id": cycle_id})
    return {"ok": True}


def _process():
    """The standard-process module (imported lazily: it imports this one)."""
    from app.services import idf_process
    return idf_process


def _pair_status(p: dict, deadline: str) -> str:
    if p.get("status") == STATUS_COMPLETED:
        return STATUS_COMPLETED
    return STATUS_OVERDUE if today_ist().isoformat() > deadline else STATUS_PENDING


async def list_cycles(user: dict, company_id: Optional[str]) -> dict:
    cid = await assert_manager(user, company_id)
    rows = await get_collection(COLL_CYCLES).find({"company_id": cid}).sort("created_at", -1).to_list(200)
    out = []
    for c in rows:
        pairs = c.get("pairs") or []
        done = sum(1 for p in pairs if p.get("status") == STATUS_COMPLETED)
        out.append({"id": str(c["_id"]), "name": c.get("name"), "period": c.get("period"),
                    "start_date": c.get("start_date"), "deadline": c.get("deadline"),
                    "status": c.get("status"), "source": c.get("source"),
                    "total": len(pairs), "completed": done, "cycle_type": c.get("cycle_type") or "regular",
                    "report_sent_at": c.get("report_sent_at"), "results_meeting_date": c.get("results_meeting_date"),
                    # The cycle's mapping, for "Add departments": who already rates whom.
                    "pairs": [{"giver_dept_id": p["giver_dept_id"], "receiver_dept_id": p["receiver_dept_id"]}
                              for p in pairs]})
    st = await settings(cid)
    from app.services import idf_process
    return {"cycles": out, "deadline_days": st["deadline_days"], "company_id": cid,
            "cadence": await idf_process.cadence(cid), "pulse": await idf_process.pulse_suggestion(cid)}


async def cycle_status(user: dict, company_id: Optional[str], cycle_id: str) -> dict:
    """Document §4E — HR/Admin monitoring: counts, department-wise %, the pending list.
    Status only: no ratings, comments or scores."""
    cid = await assert_manager(user, company_id)
    c = await _get_cycle(cid, cycle_id)
    pairs = c.get("pairs") or []
    rows, by_dept = [], {}
    # Link status per form: the furthest any of its HODs got (Submitted > Opened > Sent).
    rank = {LINK_SENT: 1, LINK_OPENED: 2, LINK_SUBMITTED: 3}
    link_state: Dict[tuple, str] = {}
    for ln in await get_collection(COLL_LINKS).find({"cycle_id": str(c["_id"])}).to_list(5000):
        k = (ln["giver_dept_id"], ln["receiver_dept_id"])
        if rank.get(ln.get("status"), 0) > rank.get(link_state.get(k), 0):
            link_state[k] = ln["status"]
    for p in pairs:
        st = _pair_status(p, c["deadline"]) if c["status"] == CYCLE_OPEN else (
            STATUS_COMPLETED if p.get("status") == STATUS_COMPLETED else c["status"])
        rows.append({"giver_name": p["giver_name"], "receiver_name": p["receiver_name"],
                     "rater_name": p.get("rater_name"), "status": st,
                     "link_status": link_state.get((p["giver_dept_id"], p["receiver_dept_id"])),
                     "submitted_at": p.get("submitted_at")})
        d = by_dept.setdefault(p["giver_name"], {"department": p["giver_name"], "total": 0, "completed": 0})
        d["total"] += 1
        d["completed"] += 1 if st == STATUS_COMPLETED else 0
    for d in by_dept.values():
        d["percent"] = round(d["completed"] / d["total"] * 100) if d["total"] else 0
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in (STATUS_COMPLETED, STATUS_PENDING, STATUS_OVERDUE)}
    return {"cycle": {k: c.get(k) for k in ("name", "period", "start_date", "deadline", "status", "report_sent_at")}
            | {"id": str(c["_id"])},
            "responses": await _process().responses_summary(cid, str(c["_id"])),
            "total": len(rows), "completed": counts[STATUS_COMPLETED],
            "pending": counts[STATUS_PENDING], "overdue": counts[STATUS_OVERDUE],
            "departments": sorted(by_dept.values(), key=lambda d: d["department"].lower()),
            "activities": sorted(rows, key=lambda r: (r["status"] == STATUS_COMPLETED, r["giver_name"].lower()))}


# ─────────────────────────────────────────────────────────────
# Form Links (HR / Admin / MD) — every HOD's personal link, like TPMS ▸ Form Links
# ─────────────────────────────────────────────────────────────
def _link_state(ln: dict, pair: Optional[dict], cycle: dict) -> str:
    if (pair or {}).get("status") == STATUS_COMPLETED or ln.get("status") == LINK_SUBMITTED:
        return LINK_SUBMITTED
    if cycle.get("status") != CYCLE_OPEN:
        return LINK_CLOSED
    return ln.get("status") or LINK_SENT


async def list_links(user: dict, company_id: Optional[str], cycle_id: Optional[str] = None) -> dict:
    """Every personal form link of one cycle (the open one by default): who it is for, its
    state and the link itself — to copy, open or resend. Status only, never feedback."""
    cid = await assert_manager(user, company_id)
    cycles = [c for c in await get_collection(COLL_CYCLES).find({"company_id": cid}).sort("created_at", -1).to_list(200)
              if c.get("source") != "import"]
    c = (next((x for x in cycles if str(x["_id"]) == str(cycle_id or "")), None)
         or next((x for x in cycles if x.get("status") == CYCLE_OPEN), None)
         or (cycles[0] if cycles else None))
    out_cycles = [{"id": str(x["_id"]), "name": x.get("name"), "period": x.get("period"), "status": x.get("status")}
                  for x in cycles]
    if not c:
        return {"cycle": None, "cycles": out_cycles, "links": [], "company_id": cid}
    pairs = {(p["giver_dept_id"], p["receiver_dept_id"]): p for p in c.get("pairs") or []}
    base = await _link_base()
    rows = []
    for ln in await get_collection(COLL_LINKS).find({"cycle_id": str(c["_id"])}).to_list(5000):
        p = pairs.get((ln["giver_dept_id"], ln["receiver_dept_id"]))
        if not p:
            continue
        rt = next((r for r in p.get("raters") or [] if r.get("id") == ln["rater_user_id"]),
                  {"name": p.get("rater_name"), "email": p.get("rater_email")})
        rows.append({"id": str(ln["_id"]), "giver_name": p["giver_name"], "receiver_name": p["receiver_name"],
                     "rater_name": rt.get("name"), "rater_email": rt.get("email"),
                     "status": _link_state(ln, p, c),
                     "last_sent_at": ln.get("last_sent_at") or ln.get("created_at"),
                     "send_count": ln.get("send_count") or 0,
                     "opened_at": ln.get("opened_at"),
                     "submitted_at": ln.get("submitted_at") or p.get("submitted_at"),
                     "link_path": f"/idf/f/{ln['token']}",
                     "link": form_url(base, ln["token"]) if base else None})
    order = {LINK_SENT: 0, LINK_OPENED: 1, LINK_CLOSED: 2, LINK_SUBMITTED: 3}
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["receiver_name"].lower(), r["giver_name"].lower()))
    return {"cycle": {"id": str(c["_id"]), "name": c.get("name"), "period": c.get("period"),
                      "deadline": c.get("deadline"), "status": c.get("status")},
            "cycles": out_cycles, "links": rows, "company_id": cid}


async def resend_link(user: dict, company_id: Optional[str], link_id: str) -> dict:
    """Email one HOD their link to one form again (open cycle, not yet submitted)."""
    cid = await assert_manager(user, company_id)
    ln = await get_collection(COLL_LINKS).find_one({"_id": _oid(link_id), "company_id": cid})
    if not ln:
        raise HTTPException(status_code=404, detail="Form link not found.")
    c = await get_collection(COLL_CYCLES).find_one({"_id": _oid(ln["cycle_id"])})
    pair = next((p for p in (c or {}).get("pairs") or []
                 if p["giver_dept_id"] == ln["giver_dept_id"] and p["receiver_dept_id"] == ln["receiver_dept_id"]), None)
    if not c or not pair:
        raise HTTPException(status_code=404, detail="This feedback form no longer exists.")
    state = _link_state(ln, pair, c)
    if state == LINK_SUBMITTED:
        raise HTTPException(status_code=409, detail="This feedback has already been submitted.")
    if state == LINK_CLOSED:
        raise HTTPException(status_code=409, detail=f"This feedback cycle is {c['status']}.")
    sent = await _notify_raters([pair], date.fromisoformat(c["deadline"]), "resend", str(c["_id"]),
                                only_rater=ln["rater_user_id"])
    if not sent:
        raise HTTPException(status_code=422,
                            detail="The email could not be sent — check the HOD's email address and the email settings.")
    await audit(cid, user, "form link resent", {"cycle_id": str(c["_id"]), "from": pair["giver_name"],
                                                "about": pair["receiver_name"]})
    return {"ok": True}


# ─────────────────────────────────────────────────────────────
# Rater: my forms + submit
# ─────────────────────────────────────────────────────────────
async def _my_dept_ids(user: dict, cid: str) -> set:
    """Departments this user heads — from Team (Department + HOD designation)."""
    uid = str(user.get("_id") or "")
    return {d["id"] for d in await departments(cid) if any(h["id"] == uid for h in d["heads"])}


def _is_rater(p: dict, uid: str) -> bool:
    return uid in (p.get("rater_user_ids") or [p.get("rater_user_id")])


async def my_forms(user: dict) -> dict:
    cid = await user_company_id(user)
    uid = str(user.get("_id") or "")
    if not cid:
        return {"cycle": None, "forms": [], "parameters": [], "is_hod": False}
    mine = await _my_dept_ids(user, cid)
    c = await get_collection(COLL_CYCLES).find_one({"company_id": cid, "status": CYCLE_OPEN})
    if not c:
        return {"cycle": None, "forms": [], "parameters": [], "is_hod": bool(mine)}
    # The caller's own personal link to each form (the same one their email carries).
    own = {(ln["giver_dept_id"], ln["receiver_dept_id"]): ln["token"]
           for ln in await get_collection(COLL_LINKS).find(
               {"cycle_id": str(c["_id"]), "rater_user_id": uid}).to_list(500)}
    base = await _link_base()
    forms = []
    for p in c.get("pairs") or []:
        if _is_rater(p, uid) or p["giver_dept_id"] in mine:
            if p.get("status") != STATUS_COMPLETED:
                await _mark_pending(p, uid)
            tok = own.get((p["giver_dept_id"], p["receiver_dept_id"]))
            forms.append({"giver_dept_id": p["giver_dept_id"], "giver_name": p["giver_name"],
                          "receiver_dept_id": p["receiver_dept_id"], "receiver_name": p["receiver_name"],
                          "status": _pair_status(p, c["deadline"]), "submitted_at": p.get("submitted_at"),
                          "link_path": f"/idf/f/{tok}" if tok else None,
                          "link": form_url(base, tok) if tok and base else None})
    forms.sort(key=lambda f: (f["status"] == STATUS_COMPLETED, f["receiver_name"].lower()))
    return {"cycle": {"id": str(c["_id"]), "name": c.get("name"), "period": c.get("period"),
                      "deadline": c.get("deadline")},
            "forms": forms, "parameters": c.get("parameters") or DEFAULT_PARAMETERS,
            "comment_required_for": c.get("comment_required_for") or DEFAULT_COMMENT_REQUIRED,
            "rating_labels": _labels(c), "is_hod": bool(mine) or bool(forms)}


async def open_link(user: dict, token: str) -> dict:
    """The emailed link: opens that HOD's form for that department. Only the HOD it was sent to
    (or another HOD of the same department) may use it; it reports 'submitted' or 'closed'
    instead of a form once the feedback is in or the cycle has ended."""
    ln = await get_collection(COLL_LINKS).find_one({"token": str(token or "")})
    if not ln:
        raise HTTPException(status_code=404, detail="This feedback link is not valid.")
    cid, uid = ln["company_id"], str(user.get("_id") or "")
    staff = _is_staff_admin(user)          # Sparsh Super Admin / Admin: may open any link, to preview it
    if not staff and (await user_company_id(user) != cid or (
            ln["rater_user_id"] != uid and ln["giver_dept_id"] not in await _my_dept_ids(user, cid))):
        raise HTTPException(status_code=403,
                            detail="This feedback link was sent to another HOD. Log in with the account it was emailed to.")
    c = await get_collection(COLL_CYCLES).find_one({"_id": _oid(ln["cycle_id"])})
    pair = next((p for p in (c or {}).get("pairs") or []
                 if p["giver_dept_id"] == ln["giver_dept_id"] and p["receiver_dept_id"] == ln["receiver_dept_id"]), None)
    if not c or not pair:
        raise HTTPException(status_code=404, detail="This feedback form no longer exists.")
    state = ("submitted" if pair.get("status") == STATUS_COMPLETED
             else "closed" if c["status"] != CYCLE_OPEN else "open")
    if staff:
        # A preview: nothing about the HOD's link or calendar activity changes, and no submit.
        state = "preview" if state == "open" else state
    if state == "open":
        await _mark_pending(pair, uid)
    if state == "open" and ln.get("status") == LINK_SENT:
        await get_collection(COLL_LINKS).update_one(
            {"_id": ln["_id"]}, {"$set": {"status": LINK_OPENED, "opened_at": _now()}})
    return {"state": state, "cycle_status": c["status"],
            "cycle": {"id": str(c["_id"]), "name": c.get("name"), "period": c.get("period"), "deadline": c.get("deadline")},
            "form": {"giver_dept_id": pair["giver_dept_id"], "giver_name": pair["giver_name"],
                     "receiver_dept_id": pair["receiver_dept_id"], "receiver_name": pair["receiver_name"],
                     "status": (_pair_status(pair, c.get("deadline") or "9999-12-31")
                                if state in ("open", "preview") else pair.get("status")),
                     "submitted_at": pair.get("submitted_at")},
            "parameters": c.get("parameters") or DEFAULT_PARAMETERS,
            "comment_required_for": c.get("comment_required_for") or DEFAULT_COMMENT_REQUIRED,
            "rating_labels": _labels(c)}


async def submit(user: dict, payload: dict) -> dict:
    """Document §3D: validate, store, then — and only then — complete the calendar activity.
    Not editable afterwards. When the last mandatory feedback is in, the cycle completes and
    the report package goes to the MD (idf_reports)."""
    cid = await user_company_id(user)
    uid = str(user.get("_id") or "")
    c = await get_collection(COLL_CYCLES).find_one({"company_id": cid, "status": CYCLE_OPEN}) if cid else None
    if not c:
        raise HTTPException(status_code=409, detail="There is no open feedback cycle.")
    g, r = str(payload.get("giver_dept_id") or ""), str(payload.get("receiver_dept_id") or "")
    idx = next((i for i, p in enumerate(c.get("pairs") or [])
                if p["giver_dept_id"] == g and p["receiver_dept_id"] == r), None)
    if idx is None:
        raise HTTPException(status_code=422, detail="Your department is not mapped to rate that department.")
    pair = c["pairs"][idx]
    if not _is_rater(pair, uid) and g not in await _my_dept_ids(user, cid):
        raise HTTPException(status_code=403, detail="Only the HOD of the rating department can submit this feedback.")
    if pair.get("status") == STATUS_COMPLETED:
        raise HTTPException(status_code=409,
                            detail=f"Feedback about {pair['receiver_name']} has already been submitted for this cycle.")

    params = c.get("parameters") or DEFAULT_PARAMETERS
    need_comment = set(c.get("comment_required_for") or DEFAULT_COMMENT_REQUIRED)
    raw_r, raw_c = payload.get("ratings") or {}, payload.get("comments") or {}
    ratings, comments = {}, {}
    for p in params:
        v = raw_r.get(p["code"])
        if v in (None, "", "na", "NA"):
            ratings[p["code"]] = None                      # Blank = Not applicable this cycle
        else:
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"{p['name']}: choose 1–5 or Not applicable.")
            if not RATING_MIN <= v <= RATING_MAX:
                raise HTTPException(status_code=422, detail=f"{p['name']}: ratings are 1–5.")
            ratings[p["code"]] = v
        text = str(raw_c.get(p["code"]) or "").strip()[:1000]
        if ratings[p["code"]] in need_comment and not text:
            raise HTTPException(status_code=422,
                                detail=f"{p['name']}: a comment is required for a rating of {ratings[p['code']]}.")
        if text:
            comments[p["code"]] = text
    if all(v is None for v in ratings.values()):
        raise HTTPException(status_code=422, detail="Rate at least one parameter.")
    strength = str(payload.get("strength") or "").strip()[:1000]
    improvement = str(payload.get("improvement") or "").strip()[:1000]
    if not strength or not improvement:
        raise HTTPException(status_code=422,
                            detail="Strength and Improvement are mandatory: one thing they do well, one to improve.")

    now = _now()
    coll = get_collection(COLL_SUBMISSIONS)
    if await coll.find_one({"cycle_id": str(c["_id"]), "giver_dept_id": g, "receiver_dept_id": r}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="This feedback has already been submitted.")
    await coll.insert_one({
        "company_id": cid, "cycle_id": str(c["_id"]), "period": c["period"],
        "giver_dept_id": g, "giver_name": pair["giver_name"],
        "receiver_dept_id": r, "receiver_name": pair["receiver_name"],
        "rater_user_id": uid, "ratings": ratings, "comments": comments,
        "strength": strength, "improvement": improvement, "submitted_at": now, "source": "form"})
    # Stored successfully -> NOW complete the pair and its calendar activity (document §4C).
    await get_collection(COLL_CYCLES).update_one(
        {"_id": c["_id"]}, {"$set": {f"pairs.{idx}.status": STATUS_COMPLETED, f"pairs.{idx}.submitted_at": now}})
    # Every HOD's activity for this pair completes — the department's feedback is in.
    await _set_events(pair, {"status": STATUS_COMPLETED, "idf_status": STATUS_COMPLETED, "completed_at": now})
    for ln in await get_collection(COLL_LINKS).find(
            {"cycle_id": str(c["_id"]), "giver_dept_id": g, "receiver_dept_id": r}).to_list(20):
        await get_collection(COLL_LINKS).update_one(
            {"_id": ln["_id"]}, {"$set": {"status": LINK_SUBMITTED, "submitted_at": now}})
    await audit(cid, user, "feedback submitted", {"cycle_id": str(c["_id"]),
                                                  "from": pair["giver_name"], "about": pair["receiver_name"]})

    fresh = await get_collection(COLL_CYCLES).find_one({"_id": c["_id"]})
    report = None
    if all(p.get("status") == STATUS_COMPLETED for p in fresh.get("pairs") or []):
        report = await complete_cycle(fresh)
    return {"ok": True, "status": STATUS_COMPLETED, "submitted_at": now,
            "cycle_completed": bool(report), "md_emailed": (report or {}).get("md_emailed", 0)}


async def complete_cycle(cycle: dict, send_report: bool = True) -> dict:
    """All mandatory feedback is in: close the cycle, generate the action plan, and send the
    report package to the MD only (document §10B)."""
    from app.services import idf_analysis, idf_reports
    cid = cycle["company_id"]
    await get_collection(COLL_CYCLES).update_one(
        {"_id": cycle["_id"]}, {"$set": {"status": CYCLE_COMPLETED, "completed_at": _now()}})
    cycle = await get_collection(COLL_CYCLES).find_one({"_id": cycle["_id"]})
    from app.services import idf_process
    if cycle.get("cycle_type") == "pulse":
        # A pulse re-score measures recovery: its scores go onto the Red actions it follows up.
        await idf_process.record_pulse_results(cycle, await idf_analysis.analyse(cycle))
    else:
        await idf_analysis.generate_actions(cycle)
        await idf_process.schedule_results_meeting(cycle)
        await idf_process.create_responses(cycle, await idf_analysis.analyse(cycle, with_previous=False))
        cycle = await get_collection(COLL_CYCLES).find_one({"_id": cycle["_id"]})
    sent = await idf_reports.email_md_package(cycle) if send_report else 0
    await audit(cid, None, "cycle completed", {"cycle_id": str(cycle["_id"]), "md_emailed": sent})
    return {"md_emailed": sent}


# ─────────────────────────────────────────────────────────────
# Calendar guard — the activity completes only through submission
# ─────────────────────────────────────────────────────────────
LOCK_MESSAGE = ("This Inter-Departmental Feedback activity completes automatically once the "
                "feedback is submitted. Open Inter-Department Feedback ▸ My Feedback Forms to fill it.")


def is_locked_event(event: dict) -> bool:
    return (event or {}).get("kind") == EVENT_KIND


# ─────────────────────────────────────────────────────────────
# Reminders (daily job) — document §4B
# ─────────────────────────────────────────────────────────────
async def _link_base() -> str:
    """The application's public address (Settings ▸ Application URL), as TPMS form links use."""
    try:
        from app.services.tpms_form_link_service import configured_base_url
        return (await configured_base_url() or "").rstrip("/")
    except Exception:
        return ""


def form_url(base: str, token: str) -> str:
    return f"{base}/idf/f/{token}"


async def _notify_raters(pairs: List[dict], deadline: date, kind: str, cycle_id: Optional[str] = None,
                         only_rater: Optional[str] = None) -> int:
    """One email per HOD, with their own link to each form they still have to fill (the same
    links in the first email and every reminder)."""
    base = await _link_base()
    tokens: Dict[tuple, str] = {}
    if cycle_id:
        for ln in await get_collection(COLL_LINKS).find({"cycle_id": cycle_id}).to_list(5000):
            tokens[(ln["giver_dept_id"], ln["receiver_dept_id"], ln["rater_user_id"])] = ln["token"]
    by_rater: Dict[str, dict] = {}
    for p in pairs:
        if p.get("status") == STATUS_COMPLETED:
            continue
        raters = p.get("raters") or [{"id": p.get("rater_user_id"), "name": p.get("rater_name"),
                                      "email": p.get("rater_email")}]
        for rt in raters:
            if not rt.get("email") or (only_rater and rt.get("id") != only_rater):
                continue
            r = by_rater.setdefault(rt["id"], {"email": rt["email"], "name": rt.get("name"), "items": []})
            tok = tokens.get((p["giver_dept_id"], p["receiver_dept_id"], rt["id"]))
            link = (f' — <a href="{form_url(base, tok)}" style="font-weight:bold">Open feedback form</a>'
                    if tok and base else "")
            r["items"].append(f"<b>{p['receiver_name']}</b> (from {p['giver_name']}){link}")
    # The wording is the Notification Template for each kind (Notification Templates ▸
    # Inter-Departmental Feedback); this code only supplies the values.
    from app.services.idf_process import idf_mail, html_list, _month
    event = {"start": "idf_cycle_started", "resend": "idf_link_resend",
             "before": "idf_due_soon", "overdue": "idf_overdue"}[kind]
    cyc = await get_collection(COLL_CYCLES).find_one({"_id": _oid(cycle_id)}) if cycle_id else None
    cid = (cyc or {}).get("company_id")
    sent = 0
    for uid, r in by_rater.items():
        ctx = {"cycle_month": _month((cyc or {}).get("period")), "deadline": deadline.strftime("%d %b %Y"),
               "form_links": html_list(r["items"])}
        try:
            if await idf_mail({"_id": uid, "email": r["email"], "full_name": r.get("name"), "company_id": cid},
                              event, ctx, cid):
                sent += 1
                if cycle_id:      # "Last sent" on the Form Links page
                    for p in pairs:
                        if p.get("status") == STATUS_COMPLETED:
                            continue
                        await get_collection(COLL_LINKS).update_many(
                            {"cycle_id": cycle_id, "rater_user_id": uid,
                             "giver_dept_id": p["giver_dept_id"], "receiver_dept_id": p["receiver_dept_id"]},
                            {"$set": {"last_sent_at": _now()}, "$inc": {"send_count": 1}})
        except Exception:
            pass
    return sent


async def run_daily_reminders() -> dict:
    """Pre-deadline reminder, daily overdue reminders until submission, and the overdue
    status on the calendar activity. Also overdue action-plan alerts (idf_analysis)."""
    today = today_ist()
    out = {"before": 0, "overdue": 0}
    for c in await get_collection(COLL_CYCLES).find({"status": CYCLE_OPEN}).to_list(500):
        deadline = date.fromisoformat(c["deadline"])
        pairs = c.get("pairs") or []
        pending = [p for p in pairs if p.get("status") != STATUS_COMPLETED]
        if not pending:
            continue
        stamp = today.isoformat()
        if today > deadline:
            todo = [p for p in pending if p.get("last_reminder") != stamp]
            if todo:
                out["overdue"] += await _notify_raters(todo, deadline, "overdue", str(c["_id"]))
            for i, p in enumerate(pairs):
                if p.get("status") == STATUS_COMPLETED:
                    continue
                pairs[i]["last_reminder"], pairs[i]["overdue_notified"] = stamp, True
                pairs[i]["status"] = STATUS_OVERDUE
                await _set_events(p, {"status": STATUS_OVERDUE, "idf_status": STATUS_OVERDUE})
        elif (deadline - today).days <= int(c.get("reminder_days_before") or 0):
            # Per form, so forms added to the cycle later still get their "due soon" reminder.
            before = f"before:{c['deadline']}"
            todo = [p for p in pending if p.get("last_reminder") != before]
            if not todo:
                continue
            out["before"] += await _notify_raters(todo, deadline, "before", str(c["_id"]))
            for i, p in enumerate(pairs):
                if p.get("status") != STATUS_COMPLETED:
                    pairs[i]["last_reminder"] = before
        else:
            continue
        await get_collection(COLL_CYCLES).update_one({"_id": c["_id"]}, {"$set": {"pairs": pairs}})
    # The standard process: "you said, we did" reminders, cycle-due and pulse-due notices to HR.
    from app.services.idf_process import daily as process_daily
    try:
        out.update(await process_daily(today))
    except Exception:
        pass
    # Overdue action plans: the owner (and the MD) are alerted — they update it under Action Plans.
    from app.services.idf_analysis import alert_overdue_actions
    try:
        out["action_alerts"] = await alert_overdue_actions()
    except Exception:
        out["action_alerts"] = 0
    return out
