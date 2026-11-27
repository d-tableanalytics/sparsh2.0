"""Inter-Departmental Feedback — meetings of the ACTION PLANS (Red repair, Amber interface).

The action plan says which meeting is needed (Red: a facilitated meeting within 7 days, led by the
MD & HR; Amber: a 30-minute interface meeting within 15 days with the lowest-rating department).
"Schedule meeting" on an action books it: a pre-filled proposal (title, invitees, a date inside the
window, the Setup link / venue) that the owner, HR or the MD adjusts and saves. The meeting goes into
the invitees' calendars with an email; invitees reply; it can be rescheduled; and the owner is
reminded when the deadline nears with no meeting booked. Results meeting: see idf_process.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection

EVENT_KIND = "idf_action_meeting"
BANDS = ("Red", "Amber")
DURATION = {"Red": 60, "Amber": 30}
WINDOW_DAYS = {"Red": 7, "Amber": 15}


async def _action_access(user: dict, company_id: Optional[str], action_id: str):
    """(action, cid, can_manage). Managers: the action's owner / its department's HODs, the MD,
    HR / Client Admin, the Sparsh Admin. Anyone else may only view (if invited)."""
    from app.services.idf_service import _oid, assert_manager, user_company_id, _is_staff_admin
    from app.services.idf_analysis import COLL_ACTIONS, _actions_scope
    oid = _oid(action_id)
    a = oid and await get_collection(COLL_ACTIONS).find_one({"_id": oid})
    if not a:
        raise HTTPException(status_code=404, detail="Action not found.")
    cid = a["company_id"]
    if not _is_staff_admin(user) and await user_company_id(user) != cid:
        raise HTTPException(status_code=404, detail="Action not found.")
    manage = False
    try:
        await assert_manager(user, cid)
        manage = True
    except HTTPException:
        try:
            q, _role = await _actions_scope(user, cid)
            q = {**q, "_id": oid}
            manage = bool(await get_collection(COLL_ACTIONS).find_one(q, {"_id": 1}))
        except HTTPException:
            manage = False
    return a, cid, manage


async def _event(a: dict):
    from app.services.idf_service import _oid
    m = a.get("meeting") or {}
    if not m.get("event_id") or not m.get("coll"):
        return None, None
    return await get_collection(m["coll"]).find_one({"_id": _oid(m["event_id"])}), m["coll"]


async def _proposal(a: dict, cid: str) -> dict:
    """Who should meet, and when — from the band rules (who leads, the lowest rater)."""
    from app.services.idf_service import departments, company_mds, _name
    from app.services.idf_process import hr_people, meeting_settings, _as_date, add_working_days
    heads = {d["name"]: d for d in await departments(cid)}
    by_id = {d["id"]: d for d in heads.values()}
    ids: List[str] = []

    def add(people):
        for p in people:
            pid = str(p.get("id") or p.get("_id"))
            if pid and pid not in ids:
                ids.append(pid)
    band = a.get("band")
    company = a.get("type") == "Company-wide repair"
    if company:          # company below 60%: the MD leads a repair session with ALL HODs (HR facilitates)
        add(await company_mds(cid))
        for d in heads.values():
            add(d["heads"])
        add(await hr_people(cid))
    else:
        add((by_id.get(a.get("department_id")) or {}).get("heads") or [])     # the rated department
        add((heads.get(a.get("feedback_from") or "") or {}).get("heads") or [])  # the lowest rater
        if band == "Red":                                                     # Red is led by the MD & HR
            add(await company_mds(cid))
            add(await hr_people(cid))
    st = meeting_settings(await get_collection("idf_settings").find_one({"company_id": cid}))
    created = _as_date(a.get("created_at") or datetime.now(timezone.utc))
    default_day = max(add_working_days(created, 2), add_working_days(date.today(), 1))
    target = str(a.get("target_date") or "")
    if target and default_day.isoformat() > target:
        default_day = date.fromisoformat(target) if date.fromisoformat(target) > date.today() else default_day
    kind = "Repair meeting" if band == "Red" else "Interface meeting"
    title = ("Company-wide repair session — MD with all HODs" if company
             else f"{kind}: {a.get('feedback_from')} → {a.get('department')}" if a.get("feedback_from")
             else f"{kind}: {a.get('department')}")
    return {"title": title, "date": default_day.isoformat(), "time": st["time"],
            "duration": DURATION.get(band, 60), "meeting_link": st["link"], "venue": st["venue"],
            "invitee_ids": ids, "deadline": target, "window_days": WINDOW_DAYS.get(band)}


def _out(a: dict, ev: dict, people: Dict[str, dict], viewer: str) -> dict:
    from app.services.idf_service import _name
    from app.services.idf_process import _ist
    rsvp = ev.get("rsvp") or {}
    s, e = _ist(ev["start"]), _ist(ev["end"])
    inv = [{"id": i, "name": _name(people[i]) if i in people else "—",
            "response": (rsvp.get(i) or {}).get("response") or "pending",
            "reason": (rsvp.get(i) or {}).get("reason") or ""} for i in ev.get("assigned_member_ids") or []]
    return {"booked": True, "action_id": str(a["_id"]), "title": ev.get("title"),
            "date": s.date().isoformat(), "time": s.strftime("%H:%M"), "duration": int((e - s).total_seconds() // 60),
            "meeting_link": ev.get("meeting_link") or "", "venue": ev.get("location") or "",
            "invitees": inv, "is_invitee": viewer in (ev.get("assigned_member_ids") or []),
            "my_response": (rsvp.get(viewer) or {}).get("response"),
            "attending": sum(1 for x in inv if x["response"] == "attending"),
            "declined": sum(1 for x in inv if x["response"] == "declined")}


def _ctx(a: dict, ev: dict, extra: Optional[dict] = None) -> dict:
    from app.services.idf_process import _ist
    s, e = _ist(ev["start"]), _ist(ev["end"])
    link = ev.get("meeting_link") or ""
    return {"meeting_title": ev.get("title"), "department": a.get("department"),
            "feedback_from": a.get("feedback_from") or "—", "action_type": a.get("type"), "band": a.get("band"),
            "meeting_date": s.strftime("%a, %d %b %Y"),
            "meeting_time": f"{s.strftime('%I:%M %p').lstrip('0').lower()} – {e.strftime('%I:%M %p').lstrip('0').lower()} IST",
            "meeting_link": f'<a href="{link}">{link}</a>' if link else "—", "venue": ev.get("location") or "—",
            "target_date": a.get("target_date") or "—", **(extra or {})}


async def meeting_options(user: dict, company_id: Optional[str]) -> dict:
    """For the Calendar's "Schedule Action Plan Meeting": the open Red / Amber / company-wide
    actions this user may book a meeting for — HR / Client Admin / MD / Sparsh Admin: all of the
    company's; an HOD: their own department's."""
    from app.services.idf_service import assert_manager, user_company_id
    from app.services.idf_analysis import COLL_ACTIONS, _actions_scope
    try:
        cid = await assert_manager(user, company_id)
        q = {"company_id": cid}
    except HTTPException:
        cid = await user_company_id(user)
        if not cid:
            return {"actions": []}
        q, _role = await _actions_scope(user, cid)
    q = {**q, "band": {"$in": list(BANDS)}, "status": {"$ne": "Closed"}}
    rows = await get_collection(COLL_ACTIONS).find(q).sort([("target_date", 1)]).to_list(500)
    return {"actions": [{"id": str(a["_id"]), "department": a.get("department"), "type": a.get("type"),
                         "band": a.get("band"), "feedback_from": a.get("feedback_from"), "period": a.get("period"),
                         "target_date": a.get("target_date"), "owner_name": a.get("owner_name"),
                         "booked": bool((a.get("meeting") or {}).get("event_id")),
                         "meeting_start": (a.get("meeting") or {}).get("start")} for a in rows]}


async def get_action_meeting(user: dict, company_id: Optional[str], action_id: str) -> dict:
    """The action's meeting if booked; else (for those who may book it) the proposal."""
    from app.services.idf_service import company_people
    a, cid, manage = await _action_access(user, company_id, action_id)
    ev, _ = await _event(a)
    uid = str(user.get("_id") or "")
    people = {str(u["_id"]): u for u in await company_people(cid)}
    if ev:
        if not manage and uid not in (ev.get("assigned_member_ids") or []):
            raise HTTPException(status_code=403, detail="Only the invitees and the action's managers see this meeting.")
        from app.services.idf_service import _name
        out = {**_out(a, ev, people, uid), "can_manage": manage}
        if manage:      # who can be invited when it is rescheduled
            out["people"] = sorted(({"id": str(u["_id"]), "name": _name(u)} for u in people.values()),
                                   key=lambda x: (x["name"] or "").lower())
        return out
    if a.get("band") not in BANDS:
        return {"booked": False, "needed": False, "can_manage": manage}
    if not manage:
        return {"booked": False, "needed": True, "can_manage": False}
    from app.services.idf_service import _name
    p = await _proposal(a, cid)
    return {"booked": False, "needed": True, "can_manage": True, "proposal": p,
            "people": sorted(({"id": str(u["_id"]), "name": _name(u)} for u in people.values()),
                             key=lambda x: (x["name"] or "").lower())}


async def schedule_action_meeting(user: dict, company_id: Optional[str], action_id: str, payload: dict) -> dict:
    """Book (or reschedule) the action's meeting. Every invitee is emailed."""
    from app.services.idf_service import company_people, audit
    from app.services.idf_process import clean_meeting_settings, _slot, idf_mail
    from app.services.idf_analysis import COLL_ACTIONS
    from app.utils.calendar_utils import get_target_collection_name
    a, cid, manage = await _action_access(user, company_id, action_id)
    if not manage:
        raise HTTPException(status_code=403, detail="Only the action's owner, HR / Client Admin or the MD can schedule its meeting.")
    if a.get("band") not in BANDS:
        raise HTTPException(status_code=422, detail="Only Red and Amber actions need a meeting.")
    m = clean_meeting_settings({"time": payload.get("time"), "duration": payload.get("duration"), "days_after": 1,
                                "mode": payload.get("mode") or "online",
                                "link": payload.get("meeting_link") or "", "venue": payload.get("venue") or ""})
    try:
        day = date.fromisoformat(str(payload.get("date") or "")[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail="Choose the meeting date.")
    start, end = _slot(day, m["time"], int(m["duration"]))
    if start < datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"):
        raise HTTPException(status_code=422, detail="Choose a time in the future.")
    people = {str(u["_id"]): u for u in await company_people(cid)}
    invitees = [str(i) for i in payload.get("invitee_ids") or [] if str(i) in people]
    if len(invitees) < 2:
        raise HTTPException(status_code=422, detail="Invite at least two people from the company.")
    title = (str(payload.get("title") or "").strip() or (await _proposal(a, cid))["title"])[:150]
    ev, coll = await _event(a)
    now = datetime.now(timezone.utc)
    note = str(payload.get("note") or "").strip()[:500]
    if ev:                                                   # reschedule / update
        moved = start != ev["start"] or end != ev["end"]
        sets = {"title": title, "start": start, "end": end, "meeting_link": m["link"] or None,
                "location": m["venue"] or None, "assigned_member_ids": invitees, "updated_at": now}
        if moved:
            sets["rsvp"] = {}
        await get_collection(coll).update_one({"_id": ev["_id"]}, {"$set": sets})
        ev = {**ev, **sets}
        event_slug = "idf_action_meeting_rescheduled"
        extra = {"note": note or ("The meeting has moved." if moved else "The meeting details were updated.")}
    else:                                                    # book it
        coll = await get_target_collection_name({"assigned_member_ids": invitees})
        ev = {"kind": EVENT_KIND, "type": "event", "title": title,
              "description": (f"{a.get('type')} for {a.get('department')}"
                              + (f" (feedback from {a.get('feedback_from')})" if a.get("feedback_from") else "")
                              + f" — Inter-Departmental Feedback action plan. Target {a.get('target_date')}."),
              "start": start, "end": end, "meeting_link": m["link"] or None, "location": m["venue"] or None,
              "rsvp": {}, "user_id": str(user.get("_id") or invitees[0]), "assigned_member_ids": invitees,
              "company_id": cid, "status": "schedule", "idf_action_id": str(a["_id"]),
              "idf_cycle_id": a.get("cycle_id"), "created_at": now, "created_by_name": "Inter-Departmental Feedback"}
        res = await get_collection(coll).insert_one(ev)
        ev["_id"] = res.inserted_id
        event_slug, extra = "idf_action_meeting_invite", {"note": note}
    await get_collection(COLL_ACTIONS).update_one({"_id": a["_id"]}, {"$set": {
        "meeting": {"event_id": str(ev["_id"]), "coll": coll, "start": start, "end": end}, "touched": True}})
    ctx = _ctx(a, ev, extra)
    for i in invitees:
        await idf_mail(people[i], event_slug, ctx, cid)
    await audit(cid, user, "action meeting " + ("updated" if event_slug.endswith("rescheduled") else "scheduled"),
                {"action_id": action_id, "start": start})
    return {**_out(a, ev, people, str(user.get("_id") or "")), "can_manage": True}


async def rsvp_action_meeting(user: dict, action_id: str, payload: dict) -> dict:
    from app.services.idf_service import company_people, _name, user_company_id
    from app.services.idf_process import idf_mail
    a, cid, _manage = await _action_access(user, None, action_id)
    ev, coll = await _event(a)
    uid = str(user.get("_id") or "")
    if not ev:
        raise HTTPException(status_code=404, detail="No meeting is booked for this action yet.")
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
    people = {str(u["_id"]): u for u in await company_people(cid)}
    if resp == "declined":
        # Tell whoever booked it and the action's owner.
        to = {str(ev.get("user_id") or ""), str(a.get("owner_user_id") or "")} - {uid, ""}
        for t in to:
            if t in people:
                await idf_mail(people[t], "idf_action_meeting_declined",
                               _ctx(a, ev, {"person": _name(user), "reason": reason}), cid)
    return _out(a, ev, people, uid)


async def alert_meetings_not_booked(today: date) -> int:
    """Daily: a Red / Amber action whose deadline is 2 days away (or passed) and still has no meeting
    — its owner is reminded once."""
    from app.services.idf_service import company_people
    from app.services.idf_process import idf_mail
    from app.services.idf_analysis import COLL_ACTIONS
    soon = (today + timedelta(days=2)).isoformat()
    sent = 0
    rows = await get_collection(COLL_ACTIONS).find(
        {"band": {"$in": list(BANDS)}, "status": {"$ne": "Closed"}, "target_date": {"$lte": soon},
         "owner_user_id": {"$ne": None}}).to_list(2000)
    cache: Dict[str, dict] = {}
    for a in rows:
        if (a.get("meeting") or {}).get("event_id") or a.get("meeting_alert_sent"):
            continue
        cid = a["company_id"]
        if cid not in cache:
            cache[cid] = {str(u["_id"]): u for u in await company_people(cid)}
        owner = cache[cid].get(str(a["owner_user_id"]))
        if owner and await idf_mail(owner, "idf_action_meeting_due", {
                "department": a.get("department"), "feedback_from": a.get("feedback_from") or "—",
                "action_type": a.get("type"), "band": a.get("band"), "target_date": a.get("target_date")}, cid):
            sent += 1
        await get_collection(COLL_ACTIONS).update_one({"_id": a["_id"]}, {"$set": {"meeting_alert_sent": today.isoformat()}})
    return sent


async def delete_meeting_of(a: dict) -> None:
    """When an action (or its cycle) is deleted, its calendar meeting goes too."""
    from app.services.idf_service import _oid
    m = a.get("meeting") or {}
    if m.get("event_id") and m.get("coll"):
        await get_collection(m["coll"]).delete_one({"_id": _oid(m["event_id"])})
