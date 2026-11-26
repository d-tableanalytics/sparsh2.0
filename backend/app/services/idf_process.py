"""Inter-Departmental Feedback — the standard process around the scores.

From the client's "Standard Approach: Inter-Departmental Feedback Score" document:
  * Close the loop — within 15 days of results each HOD tells the raters "you said, we did".
  * No waiting for the next survey — anyone can raise an inter-department problem to HR, who
    brings it to the weekly WRM (the open feedback channel).
  * Review — a results meeting of the MD and all HODs (scheduled in their calendars).
  * Re-score — monthly for the first two cycles, then quarterly; Red relationships get a pulse
    re-score after 30 days, only for the affected departments, with the same questions.
  * Leadership focus by team stage; no retaliation.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection

COLL_RESPONSES = "idf_responses"          # "you said, we did" — one per rated department per cycle
COLL_ISSUES = "idf_issues"                # the open feedback channel
ISSUE_STATUSES = ("New", "Taken to WRM", "Resolved")
RESPONSE_DAYS = 15
PULSE_DAYS = 30

NO_RETALIATION = ("No retaliation: honest feedback is thanked, never held against anyone. "
                  "Results are shown by department, never by individual rater.")
LEADERSHIP_FOCUS = {
    "Storming": "Make it safe to speak, fix hand-offs, clarify who owns what.",
    "Norming": "Agree standard formats and reply times; track actions to closure.",
    "Performing": "Recognise, share good practice, raise the bar.",
}
GOOD_FEEDBACK = ("Rate the process, not the person. Be specific: describe the situation and its effect, "
                 "and suggest one change.")


def _month(period: Optional[str]) -> str:
    try:
        return datetime.strptime(f"{period}-01", "%Y-%m-%d").strftime("%B %Y")
    except (TypeError, ValueError):
        return str(period or "")


def _as_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return date.today()


def add_working_days(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def add_months(period: str, months: int) -> str:
    y, m = (int(x) for x in str(period)[:7].split("-"))
    m += months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


async def render_idf_mail(event: str, context: dict, company_id: Optional[str] = None):
    """(subject, html body) from the event's Notification Template — the company's own version,
    else the company-wide one, else the built-in default (services/idf_templates.py). None when
    an admin has switched that email off."""
    from app.services import notification_service as ns
    t = await ns.fetch_template(f"{event}_email", str(company_id) if company_id else None)
    if not t:
        return None
    ctx = {k: ("" if v is None else str(v)) for k, v in (context or {}).items()}
    subject = ns.render_template(t.get("subject") or "Inter-Departmental Feedback", ctx)
    body = ns.render_template(t.get("body") or "", ctx)
    if "<" not in body:                       # a plain-text template keeps its line breaks
        body = body.replace("\n", "<br>")
    return subject, body


async def idf_mail(to_user: dict, event: str, context: dict, company_id: Optional[str] = None) -> bool:
    """Send one Inter-Departmental Feedback email to one person, from its template. The code
    supplies only the values; the wording lives in Notification Templates."""
    from app.services import notification_service as ns
    from app.services.idf_service import _name
    if not ns.NOTIFICATIONS_ENABLED or not (to_user or {}).get("email"):
        return False
    cid = company_id or to_user.get("company_id")
    rendered = await render_idf_mail(event, {"name": _name(to_user) or "there", **(context or {})}, cid)
    if not rendered:
        return False
    try:
        return bool(await ns.send_email_notification(to_user["email"], rendered[0], rendered[1],
                                                     user_id=str(to_user.get("_id") or ""), slug=f"{event}_email"))
    except Exception:
        return False


def html_list(items: List[str]) -> str:
    return "<ul>" + "".join(f"<li style='margin-bottom:6px'>{i}</li>" for i in items) + "</ul>" if items else ""


async def hr_people(cid: str) -> List[dict]:
    """Who runs the survey and the open channel: the company's HR (governance role HR);
    the company Admin when there is no HR."""
    from app.services.idf_service import company_people, _gov
    people = await company_people(cid)
    hr = [u for u in people if _gov(u) == "HR"]
    return hr or [u for u in people if (u.get("role") or "").lower() == "clientadmin"]


# ─────────────────────────────────────────────────────────────
# Results meeting (MD + all HODs) — "Review: results meeting with the MD and all HODs"
# ─────────────────────────────────────────────────────────────
# Setup ▸ Results meeting — the defaults every results meeting is created with.
MEETING_DEFAULTS = {"time": "11:00", "duration": 60, "days_after": 3, "mode": "online", "link": "", "venue": ""}
MEETING_MODES = ("online", "in_person", "both")
IST = timezone(timedelta(hours=5, minutes=30))


def meeting_settings(doc: Optional[dict]) -> dict:
    return {**MEETING_DEFAULTS, **{k: v for k, v in ((doc or {}).get("meeting") or {}).items() if v is not None}}


def clean_meeting_settings(raw: dict) -> dict:
    """Validate Setup ▸ Results meeting."""
    m = {**MEETING_DEFAULTS, **(raw or {})}
    t = str(m.get("time") or "")
    try:
        hh, mm = (int(x) for x in t.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        raise HTTPException(status_code=422, detail="Meeting time must be HH:MM, e.g. 11:00.")
    try:
        duration, days = int(m.get("duration")), int(m.get("days_after"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Meeting length and days must be whole numbers.")
    if not 15 <= duration <= 240 or not 1 <= days <= 15:
        raise HTTPException(status_code=422, detail="Meeting length 15–240 minutes; 1–15 working days after the results.")
    mode = str(m.get("mode") or "online")
    if mode not in MEETING_MODES:
        raise HTTPException(status_code=422, detail="Meeting type must be online, in person or both.")
    link = str(m.get("link") or "").strip()[:500]
    if link and not link.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="The meeting link must start with http:// or https://.")
    return {"time": f"{hh:02d}:{mm:02d}", "duration": duration, "days_after": days, "mode": mode,
            "link": link, "venue": str(m.get("venue") or "").strip()[:200]}


def _slot(day: date, hhmm: str, minutes: int):
    """An India-time slot as the UTC ISO strings the calendar stores."""
    hh, mm = (int(x) for x in hhmm.split(":"))
    start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=IST).astimezone(timezone.utc)
    end = start + timedelta(minutes=minutes)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ist(iso: str) -> datetime:
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(IST)


async def _meeting_event(cycle: dict):
    from app.services.idf_service import _oid
    if not cycle.get("results_meeting_event_id") or not cycle.get("results_meeting_coll"):
        return None, None
    coll = cycle["results_meeting_coll"]
    return await get_collection(coll).find_one({"_id": _oid(cycle["results_meeting_event_id"])}), coll


def _meeting_ctx(cycle: dict, ev: dict, extra: Optional[dict] = None) -> dict:
    s, e = _ist(ev["start"]), _ist(ev["end"])
    link = ev.get("meeting_link") or ""
    return {"cycle_month": _month(cycle.get("period")),
            "meeting_date": s.strftime("%a, %d %b %Y"),
            "meeting_time": f"{s.strftime('%I:%M %p').lstrip('0').lower()} – {e.strftime('%I:%M %p').lstrip('0').lower()} IST",
            "meeting_link": f'<a href="{link}">{link}</a>' if link else "—",
            "venue": ev.get("location") or "—", **(extra or {})}


async def _invitees(cid: str, ev: dict) -> List[dict]:
    from app.services.idf_service import company_people
    ids = set(ev.get("assigned_member_ids") or [])
    return [u for u in await company_people(cid) if str(u["_id"]) in ids]


async def schedule_results_meeting(cycle: dict) -> Optional[str]:
    """Once per cycle: a calendar meeting for the MD and every participating HOD, on the time,
    length, day, link and venue set in Setup ▸ Results meeting. Each invitee is emailed."""
    if cycle.get("results_meeting_event_id") or cycle.get("cycle_type") == "pulse":
        return None
    from app.services.idf_service import company_mds, departments
    from app.utils.calendar_utils import get_target_collection_name
    cid = cycle["company_id"]
    mds = await company_mds(cid)
    in_cycle = {p["giver_dept_id"] for p in cycle.get("pairs") or []} | \
               {p["receiver_dept_id"] for p in cycle.get("pairs") or []}
    members: List[str] = [str(u["_id"]) for u in mds]
    for d in await departments(cid):
        if d["id"] in in_cycle:
            members += [h["id"] for h in d["heads"] if h["id"] not in members]
    if not members:
        return None
    m = meeting_settings(await get_collection("idf_settings").find_one({"company_id": cid}))
    day = add_working_days(_as_date(cycle.get("completed_at") or datetime.now(timezone.utc)), int(m["days_after"]))
    start, end = _slot(day, m["time"], int(m["duration"]))
    coll = await get_target_collection_name({"assigned_member_ids": members})
    month = _month(cycle.get("period"))
    ev_doc = {
        "kind": "idf_results_meeting", "type": "event",
        "title": f"Inter-Departmental Feedback results meeting — {month}",
        "description": (f"Results meeting of the MD and all HODs for the {month} feedback. The MD opens and "
                        f"sets the no-blame tone. {NO_RETALIATION} The bands decide the steps: Red repair, "
                        f"Amber strengthen, Green sustain. Within {RESPONSE_DAYS} days each HOD tells the "
                        f"raters \"you said, we did\"."),
        "start": start, "end": end,
        "meeting_link": m["link"] or None, "location": m["venue"] or None, "meeting_mode": m["mode"],
        "rsvp": {},
        "user_id": members[0], "assigned_member_ids": members, "company_id": cid,
        "status": "schedule", "idf_cycle_id": str(cycle["_id"]), "created_at": datetime.now(timezone.utc),
        "created_by_name": "Inter-Departmental Feedback"}
    ev = await get_collection(coll).insert_one(ev_doc)
    await get_collection("idf_cycles").update_one(
        {"_id": cycle["_id"]}, {"$set": {"results_meeting_event_id": str(ev.inserted_id),
                                         "results_meeting_coll": coll, "results_meeting_date": day.isoformat()}})
    ctx = _meeting_ctx(cycle, ev_doc)
    for u in await _invitees(cid, ev_doc):
        await idf_mail(u, "idf_meeting_invite", ctx, cid)
    return day.isoformat()


def _meeting_out(cycle: dict, ev: dict, people: Dict[str, dict], viewer_id: str = "") -> dict:
    from app.services.idf_service import _name
    rsvp = ev.get("rsvp") or {}
    s, e = _ist(ev["start"]), _ist(ev["end"])
    invitees = [{"id": i, "name": _name(people[i]) if i in people else "—",
                 "response": (rsvp.get(i) or {}).get("response") or "pending",
                 "reason": (rsvp.get(i) or {}).get("reason") or ""}
                for i in ev.get("assigned_member_ids") or []]
    return {"cycle_id": str(cycle["_id"]), "event_id": str(ev["_id"]), "title": ev.get("title"),
            "date": s.date().isoformat(), "time": s.strftime("%H:%M"),
            "duration": int((e - s).total_seconds() // 60),
            "meeting_link": ev.get("meeting_link") or "", "venue": ev.get("location") or "",
            "mode": ev.get("meeting_mode") or "online", "invitees": invitees,
            "attending": sum(1 for x in invitees if x["response"] == "attending"),
            "declined": sum(1 for x in invitees if x["response"] == "declined"),
            "is_invitee": bool(viewer_id) and viewer_id in (ev.get("assigned_member_ids") or []),
            "my_response": (rsvp.get(viewer_id) or {}).get("response") if viewer_id else None,
            "rescheduled_at": ev.get("rescheduled_at")}


async def _cycle_and_event(cid: str, cycle_id: str):
    from app.services.idf_service import _oid
    c = await get_collection("idf_cycles").find_one({"_id": _oid(cycle_id), "company_id": cid})
    if not c:
        raise HTTPException(status_code=404, detail="Feedback cycle not found.")
    ev, coll = await _meeting_event(c)
    if not ev:
        raise HTTPException(status_code=404, detail="This cycle has no results meeting yet — it is booked when the cycle completes.")
    return c, ev, coll


async def get_meeting(user: dict, company_id: Optional[str], cycle_id: str) -> dict:
    """The results meeting of a cycle — for HR / Admin / MD (manage) and for its invitees."""
    from app.services.idf_service import assert_manager, user_company_id, company_people
    uid = str(user.get("_id") or "")
    try:
        cid, manager = await assert_manager(user, company_id), True
    except HTTPException:
        cid, manager = await user_company_id(user), False
    c, ev, _ = await _cycle_and_event(cid, cycle_id)
    if not manager and uid not in (ev.get("assigned_member_ids") or []):
        raise HTTPException(status_code=403, detail="Only the invitees and HR / Admin / MD see this meeting.")
    people = {str(u["_id"]): u for u in await company_people(cid)}
    return {**_meeting_out(c, ev, people, uid), "can_manage": manager}


async def reschedule_meeting(user: dict, company_id: Optional[str], cycle_id: str, payload: dict) -> dict:
    """HR / Client Admin / MD move the results meeting, or change its link or venue. Every invitee
    is emailed and asked to reply again."""
    from app.services.idf_service import assert_manager, company_people, audit
    cid = await assert_manager(user, company_id)
    c, ev, coll = await _cycle_and_event(cid, cycle_id)
    m = clean_meeting_settings({"time": payload.get("time") or _ist(ev["start"]).strftime("%H:%M"),
                                "duration": payload.get("duration") or 60, "days_after": 1,
                                "mode": payload.get("mode") or ev.get("meeting_mode") or "online",
                                "link": payload.get("meeting_link", ev.get("meeting_link") or ""),
                                "venue": payload.get("venue", ev.get("location") or "")})
    try:
        day = date.fromisoformat(str(payload.get("date") or _ist(ev["start"]).date().isoformat())[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail="Choose the meeting date.")
    start, end = _slot(day, m["time"], int(m["duration"]))
    if start < datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"):
        raise HTTPException(status_code=422, detail="Choose a time in the future.")
    moved = start != ev["start"] or end != ev["end"]
    sets = {"start": start, "end": end, "meeting_link": m["link"] or None, "location": m["venue"] or None,
            "meeting_mode": m["mode"], "updated_at": datetime.now(timezone.utc)}
    if moved:
        sets.update({"rsvp": {}, "rescheduled_at": datetime.now(timezone.utc)})   # new time: everyone replies again
    await get_collection(coll).update_one({"_id": ev["_id"]}, {"$set": sets})
    await get_collection("idf_cycles").update_one({"_id": c["_id"]}, {"$set": {"results_meeting_date": day.isoformat()}})
    ev = {**ev, **sets}
    note = str(payload.get("note") or "").strip()[:500]
    ctx = _meeting_ctx(c, ev, {"note": note or ("The meeting has moved." if moved else "The meeting details were updated.")})
    for u in await _invitees(cid, ev):
        await idf_mail(u, "idf_meeting_rescheduled", ctx, cid)
    await audit(cid, user, "results meeting rescheduled" if moved else "results meeting updated",
                {"cycle_id": cycle_id, "start": start})
    people = {str(u["_id"]): u for u in await company_people(cid)}
    return {**_meeting_out(c, ev, people, str(user.get("_id") or "")), "can_manage": True}


async def rsvp_meeting(user: dict, cycle_id: str, payload: dict) -> dict:
    """An invitee answers: attending, or can't attend (with a reason). A decline is sent to the
    organisers (HR / Client Admin and the MD) so they can move the meeting."""
    from app.services.idf_service import user_company_id, company_people, company_mds, _name
    cid = await user_company_id(user)
    uid = str(user.get("_id") or "")
    c, ev, coll = await _cycle_and_event(cid, cycle_id)
    if uid not in (ev.get("assigned_member_ids") or []):
        raise HTTPException(status_code=403, detail="Only the people invited to this meeting can reply.")
    resp = str(payload.get("response") or "")
    if resp not in ("attending", "declined"):
        raise HTTPException(status_code=422, detail="Reply attending or can't attend.")
    reason = str(payload.get("reason") or "").strip()[:300]
    if resp == "declined" and not reason:
        raise HTTPException(status_code=422, detail="Say briefly why you can't attend, so the organiser can find a better time.")
    entry = {"response": resp, "reason": reason, "name": _name(user), "at": datetime.now(timezone.utc)}
    await get_collection(coll).update_one({"_id": ev["_id"]}, {"$set": {f"rsvp.{uid}": entry}})
    ev = {**ev, "rsvp": {**(ev.get("rsvp") or {}), uid: entry}}
    if resp == "declined":
        organisers = {str(u["_id"]): u for u in [*(await hr_people(cid)), *(await company_mds(cid))]}
        organisers.pop(uid, None)
        ctx = _meeting_ctx(c, ev, {"person": _name(user), "reason": reason})
        for u in organisers.values():
            await idf_mail(u, "idf_meeting_declined", ctx, cid)
    people = {str(u["_id"]): u for u in await company_people(cid)}
    return _meeting_out(c, ev, people, uid)


# ─────────────────────────────────────────────────────────────
# "You said, we did" — close the loop within 15 days of results
# ─────────────────────────────────────────────────────────────
async def create_responses(cycle: dict, result: dict) -> int:
    """One per rated department: its HOD tells the raters what will change and by when."""
    if cycle.get("cycle_type") == "pulse":
        return 0
    from app.services.idf_service import departments, company_people
    cid, cycle_id = cycle["company_id"], str(cycle["_id"])
    heads = {d["id"]: d["heads"] for d in await departments(cid)}
    coll = get_collection(COLL_RESPONSES)
    due = (_as_date(cycle.get("completed_at") or datetime.now(timezone.utc)) + timedelta(days=RESPONSE_DAYS)).isoformat()
    people = {str(u["_id"]): u for u in await company_people(cid)}
    made = 0
    for d in result["departments"]:
        if d["pct"] is None or await coll.find_one({"cycle_id": cycle_id, "department_id": d["id"]}, {"_id": 1}):
            continue
        rater_ids = sorted({r["from_id"] for r in result["relationships"] if r["to_id"] == d["id"]})
        owners = [h["id"] for h in heads.get(d["id"], [])]
        await coll.insert_one({
            "company_id": cid, "cycle_id": cycle_id, "period": cycle.get("period"),
            "department_id": d["id"], "department": d["name"], "pct": d["pct"], "band": d["band"],
            "owner_user_ids": owners, "rater_dept_ids": rater_ids,
            "raters": sorted({r["from"] for r in result["relationships"] if r["to_id"] == d["id"]}),
            # What the department was told — by department, never by person.
            "received": {"strengths": d["strengths"], "improvements": d["improvements"]},
            "due_date": due, "status": "Pending", "items": [], "note": "",
            "created_at": datetime.now(timezone.utc)})
        made += 1
        for uid in owners:
            await idf_mail(people.get(uid), "idf_you_said_request", {
                "department": d["name"], "score": f"{d['pct']}%", "band": d["band"],
                "cycle_month": _month(cycle.get("period")), "due_date": due}, cid)
    return made


def _resp_out(r: dict, show_received: bool) -> dict:
    out = {k: v for k, v in r.items() if k not in ("_id", "received") or (k == "received" and show_received)}
    out["id"] = str(r["_id"])
    out["overdue"] = r.get("status") != "Submitted" and str(r.get("due_date") or "9999") < date.today().isoformat()
    return out


async def list_responses(user: dict, company_id: Optional[str]) -> dict:
    """HOD: their departments' responses to write, and the responses sent to them as a rater.
    HR / Admin / MD / Sparsh Admin: every department's, to follow up."""
    from app.services.idf_service import user_company_id, assert_manager, _my_dept_ids, is_md
    coll = get_collection(COLL_RESPONSES)
    try:
        cid = await assert_manager(user, company_id)
        manager = True
    except HTTPException:
        cid, manager = await user_company_id(user), False
    if not cid:
        return {"mine": [], "received": [], "all": [], "manager": False}
    mine_ids = await _my_dept_ids(user, cid)
    rows = await coll.find({"company_id": cid}).sort("created_at", -1).to_list(2000)
    return {
        "mine": [_resp_out(r, True) for r in rows if r["department_id"] in mine_ids],
        "received": [_resp_out(r, False) for r in rows
                     if r.get("status") == "Submitted" and set(r.get("rater_dept_ids") or []) & mine_ids],
        "all": [_resp_out(r, is_md(user)) for r in rows] if manager else [],
        "manager": manager,
    }


async def submit_response(user: dict, response_id: str, payload: dict) -> dict:
    from app.services.idf_service import _oid, _my_dept_ids, user_company_id, departments, company_people, _name, audit
    coll = get_collection(COLL_RESPONSES)
    oid = _oid(response_id)
    r = oid and await coll.find_one({"_id": oid})
    if not r or r["company_id"] != await user_company_id(user) or \
            r["department_id"] not in await _my_dept_ids(user, r["company_id"]):
        raise HTTPException(status_code=404, detail="Only the department's HOD can answer for it.")
    items = []
    for it in payload.get("items") or []:
        what = str((it or {}).get("what") or "").strip()[:500]
        by = str((it or {}).get("by_when") or "").strip()[:10]
        if what or by:
            if not what or not by:
                raise HTTPException(status_code=422, detail="Each change needs what will change and by when.")
            try:
                date.fromisoformat(by)
            except ValueError:
                raise HTTPException(status_code=422, detail="'By when' must be a date.")
            items.append({"what": what, "by_when": by})
    if not items:
        raise HTTPException(status_code=422, detail="Add at least one change: what will change and by when.")
    now = datetime.now(timezone.utc)
    first = r.get("status") != "Submitted"
    await coll.update_one({"_id": oid}, {"$set": {
        "items": items, "note": str(payload.get("note") or "").strip()[:1000], "status": "Submitted",
        "submitted_at": r.get("submitted_at") or now, "updated_at": now, "submitted_by": _name(user)}})
    # Tell the raters — the HODs of the departments that gave the feedback.
    heads = {d["id"]: d["heads"] for d in await departments(r["company_id"])}
    people = {str(u["_id"]): u for u in await company_people(r["company_id"])}
    lst = "".join(f"<li>{i['what']} — by <b>{i['by_when']}</b></li>" for i in items)
    sent = set()
    for did in r.get("rater_dept_ids") or []:
        for h in heads.get(did, []):
            if h["id"] in sent:
                continue
            sent.add(h["id"])
            await idf_mail(people.get(h["id"]), "idf_you_said_shared", {
                "department": r["department"], "cycle_month": _month(r.get("period")),
                "changes": f"<ul>{lst}</ul>", "note": str(payload.get("note") or "").strip()}, r["company_id"])
    await audit(r["company_id"], user, "you said, we did " + ("submitted" if first else "updated"),
                {"response_id": response_id, "department": r["department"]})
    return _resp_out(await coll.find_one({"_id": oid}), True)


async def responses_summary(cid: str, cycle_id: str) -> dict:
    rows = await get_collection(COLL_RESPONSES).find({"company_id": cid, "cycle_id": cycle_id}).to_list(500)
    today = date.today().isoformat()
    return {"total": len(rows), "submitted": sum(1 for r in rows if r.get("status") == "Submitted"),
            "overdue": sum(1 for r in rows if r.get("status") != "Submitted" and str(r.get("due_date")) < today),
            "pending": [r["department"] for r in rows if r.get("status") != "Submitted"]}


# ─────────────────────────────────────────────────────────────
# Open feedback channel — "no waiting for the next survey"
# ─────────────────────────────────────────────────────────────
def _issue_out(i: dict, manager: bool) -> dict:
    out = {k: v for k, v in i.items() if k not in ("_id", "raised_by")}
    out["id"] = str(i["_id"])
    if manager and i.get("anonymous"):
        out["raised_by_name"] = "Anonymous"
    return out


async def _issue_role(user: dict, company_id: Optional[str]):
    from app.services.idf_service import assert_manager, user_company_id
    try:
        return await assert_manager(user, company_id), True
    except HTTPException:
        return await user_company_id(user), False


async def list_issues(user: dict, company_id: Optional[str]) -> dict:
    """HR / Admin / MD / Sparsh Admin: every issue, to bring to the weekly WRM. Anyone else:
    the issues they raised."""
    from app.services.idf_service import departments
    cid, manager = await _issue_role(user, company_id)
    if not cid:
        return {"issues": [], "departments": [], "manager": False}
    q = {"company_id": cid} if manager else {"company_id": cid, "raised_by": str(user.get("_id") or "")}
    rows = await get_collection(COLL_ISSUES).find(q).sort("created_at", -1).to_list(1000)
    return {"issues": [_issue_out(i, manager) for i in rows], "manager": manager,
            "departments": [{"id": d["id"], "name": d["name"]} for d in await departments(cid)]}


async def raise_issue(user: dict, payload: dict) -> dict:
    from app.services.idf_service import user_company_id, departments, _name, audit
    cid = await user_company_id(user)
    if not cid:
        raise HTTPException(status_code=403, detail="Raise an issue from your company account.")
    depts = {d["id"]: d for d in await departments(cid)}
    about = str(payload.get("about_department_id") or "")
    if about not in depts:
        raise HTTPException(status_code=422, detail="Choose the department the issue is about.")
    text = str(payload.get("description") or "").strip()
    if len(text) < 10:
        raise HTTPException(status_code=422, detail="Describe the issue: the situation and its effect (a sentence or two).")
    anonymous = bool(payload.get("anonymous"))
    mine = str(user.get("department_id") or "")
    doc = {"company_id": cid, "raised_by": str(user.get("_id") or ""), "raised_by_name": _name(user),
           "anonymous": anonymous,
           "from_department": depts[mine]["name"] if mine in depts else (user.get("department_name") or None),
           "about_department_id": about, "about_department": depts[about]["name"],
           "description": text[:2000], "suggestion": str(payload.get("suggestion") or "").strip()[:1000],
           "status": "New", "notes": [], "created_at": datetime.now(timezone.utc)}
    res = await get_collection(COLL_ISSUES).insert_one(doc)
    who = "Someone (anonymous)" if anonymous else doc["raised_by_name"]
    for hr in await hr_people(cid):
        await idf_mail(hr, "idf_issue_raised", {
            "raised_by": who, "about_department": doc["about_department"],
            "description": doc["description"], "suggestion": doc["suggestion"] or "—"}, cid)
    await audit(cid, None if anonymous else user, "issue raised", {"about": doc["about_department"]})
    doc["_id"] = res.inserted_id
    return _issue_out(doc, False)


async def update_issue(user: dict, company_id: Optional[str], issue_id: str, payload: dict) -> dict:
    from app.services.idf_service import _oid, _name, audit, company_people
    cid, manager = await _issue_role(user, company_id)
    if not manager:
        raise HTTPException(status_code=403, detail="Only HR (or the Admin / MD) handles raised issues.")
    oid = _oid(issue_id)
    i = oid and await get_collection(COLL_ISSUES).find_one({"_id": oid, "company_id": cid})
    if not i:
        raise HTTPException(status_code=404, detail="Issue not found.")
    was = i.get("status")
    sets = {"updated_at": datetime.now(timezone.utc)}
    status = payload.get("status")
    if status is not None:
        if status not in ISSUE_STATUSES:
            raise HTTPException(status_code=422, detail="Status must be New, Taken to WRM or Resolved.")
        sets["status"] = status
        if status == "Taken to WRM":
            sets["wrm_date"] = str(payload.get("wrm_date") or date.today().isoformat())[:10]
        if status == "Resolved":
            sets["resolved_at"] = datetime.now(timezone.utc)
    ops = {"$set": sets}
    note = str(payload.get("note") or "").strip()[:1000]
    if note:
        ops["$push"] = {"notes": {"text": note, "by": _name(user), "at": datetime.now(timezone.utc),
                                  "status": sets.get("status", i.get("status"))}}
    await get_collection(COLL_ISSUES).update_one({"_id": oid}, ops)
    if status == "Resolved" and was != "Resolved":
        raiser = next((u for u in await company_people(cid) if str(u["_id"]) == i.get("raised_by")), None)
        await idf_mail(raiser, "idf_issue_resolved", {
            "about_department": i["about_department"], "note": f"HR's note: {note}" if note else ""}, cid)
    await audit(cid, user, "issue updated", {"issue_id": issue_id, "status": sets.get("status")})
    return _issue_out(await get_collection(COLL_ISSUES).find_one({"_id": oid}), True)


async def delete_issue(user: dict, company_id: Optional[str], issue_id: str) -> dict:
    """MD, Client Admin or Super Admin: remove a raised issue (e.g. a duplicate or a test)."""
    from app.services.idf_service import _oid, assert_can_delete, audit
    oid = _oid(issue_id)
    i = oid and await get_collection(COLL_ISSUES).find_one({"_id": oid})
    if not i:
        raise HTTPException(status_code=404, detail="Issue not found.")
    cid = await assert_can_delete(user, i["company_id"])
    await get_collection(COLL_ISSUES).delete_one({"_id": oid})
    await audit(cid, user, "issue deleted", {"issue_id": issue_id, "about": i.get("about_department")})
    return {"ok": True}


async def issues_summary(cid: str) -> dict:
    rows = await get_collection(COLL_ISSUES).find({"company_id": cid}).to_list(2000)
    return {"open": sum(1 for i in rows if i.get("status") != "Resolved"),
            "new": sum(1 for i in rows if i.get("status") == "New"),
            "resolved": sum(1 for i in rows if i.get("status") == "Resolved")}


# ─────────────────────────────────────────────────────────────
# Cycle rhythm and the pulse re-score
# ─────────────────────────────────────────────────────────────
async def cadence(cid: str) -> dict:
    """Re-score monthly for the first two cycles, then quarterly (same questions)."""
    rows = [c for c in await get_collection("idf_cycles").find({"company_id": cid}).to_list(500)
            if c.get("status") != "Cancelled" and c.get("cycle_type") != "pulse"]
    rule = "Monthly for the first two cycles, then quarterly — keep the questions unchanged."
    if not rows:
        return {"cycles_so_far": 0, "next_due_period": None, "interval_months": 1, "rule": rule}
    last = max(c["period"] for c in rows if c.get("period"))
    interval = 1 if len(rows) < 2 else 3
    return {"cycles_so_far": len(rows), "last_period": last, "interval_months": interval,
            "next_due_period": add_months(last, interval), "rule": rule}


async def pulse_suggestion(cid: str) -> Optional[dict]:
    """The latest completed cycle's relationships below 60%: re-score them 30 days on."""
    from app.services.idf_analysis import analyse
    rows = await get_collection("idf_cycles").find(
        {"company_id": cid, "status": "Completed"}).sort("period", -1).to_list(20)
    src = next((c for c in rows if c.get("cycle_type") != "pulse" and c.get("source") != "import"), None)
    if not src:
        return None
    res = await analyse(src, with_previous=False)
    if not res["hotspots"]:
        return None
    by: Dict[str, List[str]] = {}
    for h in res["hotspots"]:
        by.setdefault(h["to_id"], [])
        if h["from_id"] not in by[h["to_id"]]:
            by[h["to_id"]].append(h["from_id"])
    started = await get_collection("idf_cycles").find_one(
        {"company_id": cid, "pulse_of": str(src["_id"]), "status": {"$ne": "Cancelled"}}, {"_id": 1})
    due = _as_date(src.get("completed_at") or datetime.now(timezone.utc)) + timedelta(days=PULSE_DAYS)
    return {"cycle_id": str(src["_id"]), "period": src.get("period"), "due_date": due.isoformat(),
            # The pulse opens 30 days after the results — not before (Standard Approach).
            "available": due <= date.today(), "started": bool(started),
            "reviews": [{"receiver_dept_id": r, "giver_dept_ids": g} for r, g in by.items()],
            "relationships": [{"from": h["from"], "to": h["to"], "pct": h["pct"]} for h in res["hotspots"]]}


async def record_pulse_results(cycle: dict, result: dict) -> int:
    """A completed pulse re-score writes each re-scored relationship's new score onto the Red
    actions it was re-scoring (and the department's, where the whole department was Red)."""
    src_id = cycle.get("pulse_of")
    if not src_id:
        return 0
    rel = {(r["from"], r["to"]): r for r in result["relationships"]}
    dep = {d["name"]: d for d in result["departments"]}
    n = 0
    for a in await get_collection("idf_actions").find({"cycle_id": src_id, "band": "Red"}).to_list(500):
        hit = rel.get((a.get("feedback_from"), a.get("department"))) or dep.get(a.get("department"))
        if hit and hit.get("pct") is not None:
            await get_collection("idf_actions").update_one({"_id": a["_id"]}, {"$set": {
                "rescore_pct": hit["pct"], "rescore_band": hit.get("band"),
                "rescore_cycle_id": str(cycle["_id"]), "rescored_at": datetime.now(timezone.utc)}})
            n += 1
    return n


# ─────────────────────────────────────────────────────────────
# Daily job (from idf_service.run_daily_reminders)
# ─────────────────────────────────────────────────────────────
async def daily(today: date) -> dict:
    from app.services.idf_service import company_people
    out = {"you_said_reminders": 0, "cycle_due_reminders": 0, "pulse_due_reminders": 0}
    # "You said, we did" overdue — remind the HOD every 3 days.
    for r in await get_collection(COLL_RESPONSES).find(
            {"status": {"$ne": "Submitted"}, "due_date": {"$lt": today.isoformat()}}).to_list(2000):
        last = r.get("last_alert")
        if last and (today - date.fromisoformat(last)).days < 3:
            continue
        people = {str(u["_id"]): u for u in await company_people(r["company_id"])}
        for uid in r.get("owner_user_ids") or []:
            if await idf_mail(people.get(uid), "idf_you_said_overdue", {
                    "department": r["department"], "due_date": r["due_date"]}, r["company_id"]):
                out["you_said_reminders"] += 1
        await get_collection(COLL_RESPONSES).update_one({"_id": r["_id"]}, {"$set": {"last_alert": today.isoformat()}})

    for cid in await get_collection("idf_cycles").distinct("company_id"):
        if await get_collection("idf_cycles").find_one({"company_id": cid, "status": "Open"}, {"_id": 1}):
            continue
        st = await get_collection("idf_settings").find_one({"company_id": cid}) or {}
        hr = await hr_people(cid)
        # Next cycle due (monthly ×2, then quarterly) — tell HR once per due month.
        cad = await cadence(cid)
        due = cad.get("next_due_period")
        if due and due <= today.strftime("%Y-%m") and st.get("cadence_notified") != due:
            for u in hr:
                if await idf_mail(u, "idf_cycle_due", {"cycle_month": _month(due), "rule": cad["rule"]}, cid):
                    out["cycle_due_reminders"] += 1
            await get_collection("idf_settings").update_one(
                {"company_id": cid}, {"$set": {"company_id": cid, "cadence_notified": due}}, upsert=True)
        # Pulse re-score due 30 days after a cycle with Red relationships — tell HR once.
        pulse = await pulse_suggestion(cid)
        if pulse and not pulse["started"] and pulse["due_date"] <= today.isoformat() \
                and st.get("pulse_notified") != pulse["cycle_id"]:
            rels = "".join(f"<li>{x['from']} → {x['to']} ({x['pct']}%)</li>" for x in pulse["relationships"])
            for u in hr:
                if await idf_mail(u, "idf_pulse_due", {"cycle_month": _month(pulse["period"]),
                                                        "relationships": f"<ul>{rels}</ul>"}, cid):
                    out["pulse_due_reminders"] += 1
            await get_collection("idf_settings").update_one(
                {"company_id": cid}, {"$set": {"company_id": cid, "pulse_notified": pulse["cycle_id"]}}, upsert=True)
    return out
