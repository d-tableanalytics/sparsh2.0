"""
TPMS ▸ escalation services.

⚠ THE APPS SCRIPT RUNS **TWO** INDEPENDENT ESCALATION ENGINES ON DIFFERENT TIMELINES.
Both are ported here because both run in production today, and the instruction is to
replicate the source exactly. They do not agree with each other:

  Engine A — runEscalationLadder (code.js:3755, daily 07:00) — the one that EMAILS.
      D+1  [Pending Action] → owners + HODs + HRs, cc SMOps      esc_stage 1
      D+2  [CRITICAL]       → MDs (fallback HOD+HR), cc SMOps    esc_stage 2
      D+3  [LAPSED]         → everyone; status becomes Lapsed    esc_stage 3

  Engine B — syncAutoFeed (code.js:2714, daily 06:00) — writes ROWS, sends NOTHING.
      overdue ≥1d  → open an Action_Item (follow-up tracker)
      overdue ≥5d  → open an Escalation, level HOD@5 / HR@7 / MD@10
      completed    → close the action, resolve the escalation

Net effect (unchanged from the source): an activity is force-lapsed on day 3 by Engine A,
while the Escalations table Engine B feeds doesn't open a row until day 5. The Escalation
Dashboard therefore shows a different progression from the one recipients experience.
A third ladder (T−2/T/T+2/T+4/T+5/T+7/T+10) is displayed in the UI as "system logic" and
is not implemented in the source — it is not implemented here either.

Both engines are idempotent and keyed by event id, so re-running is safe.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.db.mongodb import get_collection
from app.models.tpms import (
    AUTO_ACTION_MIN_DAYS, AUTO_ESCALATION_MIN_DAYS,
    COLL_ACTION_ITEMS, COLL_ESCALATIONS,
    LADDER_CRITICAL_DAYS, LADDER_LAPSE_DAYS, LADDER_PENDING_DAYS,
    STATUS_CANCELLED, STATUS_COMPLETED, STATUS_LAPSED, STATUS_SCHEDULED,
    TPMS_EVENT_KIND, erp_status_for, escalation_level,
)
from app.services.tpms_schedule_service import CAL_COLLECTIONS, update_tracker_status

logger = logging.getLogger(__name__)

# Statuses the sweeps skip entirely (code.js:3775 / 2751).
SKIP_STATUSES = {STATUS_COMPLETED, STATUS_CANCELLED, STATUS_LAPSED}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _days_between(a: str, b: str) -> int:
    try:
        return (datetime.fromisoformat(str(b)[:10]) - datetime.fromisoformat(str(a)[:10])).days
    except Exception:
        return 0


async def _open_tpms_events() -> List[tuple]:
    """Every TPMS activity across the calendar collections, as (doc, collection)."""
    out = []
    for coll in CAL_COLLECTIONS:
        for doc in await get_collection(coll).find({"kind": TPMS_EVENT_KIND}).to_list(5000):
            out.append((doc, coll))
    return out


# ─────────────────────────────────────────────────────────────
# Recipient resolution — port of escalationRecipients_ (code.js:3713)
#
# DEVIATION, documented: the sheet carried per-employee HOD_Email / HR_Email / MD_Email
# columns. ERP users have no such columns, so we resolve by DEPARTMENT within the
# company. This is precisely the Apps Script's own company-wide fallback path
# (code.js:3727-3733), which is what actually fires in their data — most of those
# columns are blank.
# ─────────────────────────────────────────────────────────────
async def escalation_recipients(event: dict) -> Dict[str, List[str]]:
    company_id = str(event.get("company_id") or "")
    member_ids = {str(m) for m in (event.get("assigned_member_ids") or [])}
    staff_ids = {str(s) for s in (event.get("coach_ids") or [])}

    owners, hods, hrs, mds, smops = [], [], [], [], []
    if company_id:
        users = await get_collection("learners").find(
            {"company_id": company_id, "is_active": {"$ne": False}}
        ).to_list(1000)
        for u in users:
            email = (u.get("email") or "").strip()
            if not email:
                continue
            dept = (u.get("department") or "").strip().lower()
            if str(u["_id"]) in member_ids:
                owners.append(email)
            if dept == "hod":
                hods.append(email)
            elif dept == "hr":
                hrs.append(email)
            elif dept == "md":
                mds.append(email)

    if staff_ids:
        from bson import ObjectId
        oids = []
        for s in staff_ids:
            try:
                oids.append(ObjectId(s))
            except Exception:
                pass
        if oids:
            for u in await get_collection("staff").find({"_id": {"$in": oids}}).to_list(200):
                if (u.get("email") or "").strip():
                    smops.append(u["email"].strip())

    dedupe = lambda xs: list(dict.fromkeys(x for x in xs if x))
    return {"owners": dedupe(owners), "hods": dedupe(hods), "hrs": dedupe(hrs),
            "mds": dedupe(mds), "smops": dedupe(smops)}


def _esc_body(event: dict, label: str, note: str) -> str:
    """Port of escBody_ (code.js:3740)."""
    start = str(event.get("start") or "")
    return (
        f'<div style="font-family:Arial,sans-serif;color:#1e293b">'
        f'<h3 style="color:#b91c1c">{label}: {event.get("title") or ""}</h3>'
        f"<p>{note}</p>"
        f'<table style="border-collapse:collapse;font-size:14px">'
        f'<tr><td style="padding:3px 10px;color:#64748b">Activity</td>'
        f'<td style="padding:3px 10px"><b>{event.get("activity") or ""}</b></td></tr>'
        f'<tr><td style="padding:3px 10px;color:#64748b">Company</td>'
        f'<td style="padding:3px 10px">{event.get("company_name") or ""}</td></tr>'
        f'<tr><td style="padding:3px 10px;color:#64748b">Scheduled</td>'
        f'<td style="padding:3px 10px">{start[:10]} {start[11:16]}</td></tr>'
        f"</table></div>"
    )


async def _send(recipients: List[str], subject: str, html: str, slug: str) -> int:
    from app.services.notification_service import send_email_notification
    sent = 0
    for email in recipients:
        try:
            await send_email_notification(email, subject, html, slug=slug)
            sent += 1
        except Exception as e:
            logger.error(f"TPMS escalation mail to {email} failed: {e}")
    return sent


# ─────────────────────────────────────────────────────────────
# ENGINE A — runEscalationLadder (code.js:3755). Daily ~07:00.
# ─────────────────────────────────────────────────────────────
async def run_escalation_ladder() -> dict:
    """D+1 pending → D+2 critical → D+3 Lapsed. Calendar days; weekends counted.

    Skips rows where the doer has already marked done — waiting on staff confirmation
    is not "overdue" (code.js:3776).
    """
    today = _today()
    pending = critical = lapsed = 0

    for event, coll in await _open_tpms_events():
        status = event.get("tpms_status") or STATUS_SCHEDULED
        if status in SKIP_STATUSES:
            continue
        if event.get("learner_done"):
            continue
        event_day = str(event.get("start") or "")[:10]
        if not event_day or event_day >= today:
            continue

        overdue = _days_between(event_day, today)
        stage = int(event.get("esc_stage") or 0)
        recipients = await escalation_recipients(event)
        title = event.get("title") or ""
        activity = event.get("activity") or ""
        updates: dict = {}

        if overdue >= LADDER_PENDING_DAYS and stage < 1:
            to = recipients["owners"] + recipients["hods"] + recipients["hrs"]
            if to:
                await _send(
                    list(dict.fromkeys(to)),
                    f"[Pending Action] {title} – {activity} not updated",
                    _esc_body(event, "Pending Action Escalation",
                              f"This activity was scheduled on {event_day} and has not been "
                              "marked complete. Please update its status today."),
                    "tpms_escalation_pending",
                )
            updates["esc_stage"] = stage = 1
            pending += 1

        if overdue >= LADDER_CRITICAL_DAYS and stage < 2:
            to = recipients["mds"] or (recipients["hods"] + recipients["hrs"])
            if to:
                await _send(
                    list(dict.fromkeys(to)),
                    f"[CRITICAL] {title} – {activity} overdue",
                    _esc_body(event, "Critical Escalation",
                              f"This activity (scheduled {event_day}) is still not completed "
                              "after 2 days. Immediate attention required before it lapses."),
                    "tpms_escalation_critical",
                )
            updates["esc_stage"] = stage = 2
            critical += 1

        if overdue >= LADDER_LAPSE_DAYS and stage < 3:
            to = (recipients["owners"] + recipients["hods"]
                  + recipients["hrs"] + recipients["mds"])
            if to:
                await _send(
                    list(dict.fromkeys(to)),
                    f"[LAPSED] {title} – {activity}",
                    _esc_body(event, "Activity Lapsed",
                              f"This activity (scheduled {event_day}) was not completed within "
                              "the allowed window and has been automatically marked LAPSED."),
                    "tpms_escalation_lapsed",
                )
            updates.update({
                "esc_stage": 3,
                "tpms_status": STATUS_LAPSED,
                "status": erp_status_for(STATUS_LAPSED),
            })
            lapsed += 1
            await update_tracker_status(str(event["_id"]), STATUS_LAPSED)

        if updates:
            updates["updated_at"] = datetime.utcnow()
            await get_collection(coll).update_one({"_id": event["_id"]}, {"$set": updates})

    msg = f"TPMS escalation ladder: {pending} pending, {critical} critical, {lapsed} lapsed [{today}]"
    logger.info(msg)
    return {"pending": pending, "critical": critical, "lapsed": lapsed, "date": today}


# ─────────────────────────────────────────────────────────────
# ENGINE B — syncAutoFeed (code.js:2714). Daily ~06:00.
# Writes Action_Items + Escalations. Sends no mail. Idempotent by event id.
# ─────────────────────────────────────────────────────────────
async def sync_auto_feed() -> dict:
    today = _today()
    now = datetime.utcnow()
    actions_created = actions_closed = esc_created = esc_resolved = 0

    companies: Dict[str, dict] = {}
    for c in await get_collection("companies").find({}).to_list(1000):
        companies[str(c["_id"])] = c

    for event, _coll in await _open_tpms_events():
        event_id = str(event["_id"])
        company_id = str(event.get("company_id") or "")
        company = companies.get(company_id) or {}
        company_name = event.get("company_name") or company.get("name") or company_id
        om = company.get("owner") or ""
        status = event.get("tpms_status") or STATUS_SCHEDULED
        event_day = str(event.get("start") or "")[:10]
        activity = event.get("activity") or ""
        overdue = _days_between(event_day, today) if event_day else 0

        # ── Closed activities: close the follow-up, resolve the escalation ──
        if status in (STATUS_COMPLETED, STATUS_CANCELLED):
            res = await get_collection(COLL_ACTION_ITEMS).update_one(
                {"event_id": event_id, "status": {"$ne": "Closed"}},
                {"$set": {"status": "Closed", "closed_at": now}},
            )
            actions_closed += res.modified_count

            completed_day = event.get("completed_at")
            completed_day = (completed_day.date().isoformat()
                             if isinstance(completed_day, datetime) else today)
            res = await get_collection(COLL_ESCALATIONS).update_one(
                {"event_id": event_id, "status": {"$ne": "Resolved"}},
                {"$set": {
                    "status": "Resolved",
                    "actual_date": completed_day,
                    "resolution_date": completed_day,
                    "resolution_method": "Auto: activity completed",
                    "resolved_by": om or "System",
                }},
            )
            esc_resolved += res.modified_count
            continue

        # ── Action item at overdue ≥ 1 day ──
        if overdue >= AUTO_ACTION_MIN_DAYS:
            existing = await get_collection(COLL_ACTION_ITEMS).find_one({"event_id": event_id})
            if existing:
                await get_collection(COLL_ACTION_ITEMS).update_one(
                    {"_id": existing["_id"]}, {"$set": {"delay_days": overdue}}
                )
            else:
                members = event.get("assigned_member_ids") or []
                owner_id = str(members[0]) if members else None
                owner_name, owner_email = None, None
                if owner_id:
                    from app.utils.calendar_utils import find_user_by_id
                    u = await find_user_by_id(owner_id)
                    if u:
                        owner_name = (u.get("full_name")
                                      or " ".join(filter(None, [u.get("first_name"), u.get("last_name")])).strip()
                                      or u.get("email"))
                        owner_email = u.get("email")
                await get_collection(COLL_ACTION_ITEMS).insert_one({
                    "event_id": event_id,
                    "company_id": company_id,
                    "company_name": company_name,
                    "activity": activity,
                    "action": f"Follow up: {activity or event.get('title') or ''}",
                    "owner_id": owner_id,
                    "owner_name": owner_name,
                    "owner_email": owner_email,
                    "target_date": event_day,
                    "status": "Pending",
                    "delay_days": overdue,
                    "created_at": now,
                })
                actions_created += 1

        # ── Escalation at overdue ≥ 5 days ──
        if overdue >= AUTO_ESCALATION_MIN_DAYS:
            level = escalation_level(overdue)
            existing = await get_collection(COLL_ESCALATIONS).find_one({"event_id": event_id})
            if existing:
                await get_collection(COLL_ESCALATIONS).update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"escalated_to": level["to"], "level": level["level"],
                              "last_reminder": today}},
                )
            else:
                await get_collection(COLL_ESCALATIONS).insert_one({
                    "event_id": event_id,
                    "company_id": company_id,
                    "company_name": company_name,
                    "om": om,
                    "activity": activity,
                    "target_date": event_day,
                    "status": "Active",
                    "level": level["level"],
                    "escalated_to": level["to"],
                    "escalation_date": today,
                    "last_reminder": today,
                    "recommended_action": (
                        f"Auto: {activity or 'activity'} overdue {overdue} days — "
                        f"escalate to {level['to']}"
                    ),
                })
                esc_created += 1

    logger.info(
        f"TPMS auto-feed: actions +{actions_created}/closed {actions_closed}, "
        f"escalations +{esc_created}/resolved {esc_resolved}"
    )
    return {"actions_created": actions_created, "actions_closed": actions_closed,
            "escalations_created": esc_created, "escalations_resolved": esc_resolved}
