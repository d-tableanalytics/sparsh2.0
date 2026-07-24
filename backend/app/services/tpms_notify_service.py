"""
TPMS ▸ notification service.

Port of the Apps Script mail layer (`copy_of calender/code.js`):
  • getTemplate_          (:955)  → get_template()
  • fill_ / buildMap_     (:1082) → fill() / build_map()
  • sendScheduleEmails_   (:1141) → notify_schedule()
  • sendStatusEmails_     (:970)  → notify_status()
  • defaultBody_          (:1090) → _default_body()

Templates come from `tpms_mail_templates`, keyed (activity × side × event) — the shape of
the sheet's `Templates` tab, which carried 11 columns per activity:
    Staff|Company  ×  schedules | reminder | status_reschedule | status_cancel | status_completed
A row with activity "*" is the catch-all. When no template matches, the ported default
body is used, exactly as the source falls back.

Delivery reuses the ERP's existing notification service (SMTP + logging), so TPMS adds no
second mail stack. Every send is logged with a `tpms_*` slug so the Logs Report can
separate TPMS traffic from the rest of the ERP.
"""
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from app.db.mongodb import get_collection
from app.models.tpms import COLL_MAIL_TEMPLATES

logger = logging.getLogger(__name__)

SIDE_STAFF = "staff"
SIDE_COMPANY = "company"

EVENT_SCHEDULE = "schedule"
EVENT_REMINDER = "reminder"
EVENT_RESCHEDULE = "reschedule"
EVENT_CANCEL = "cancel"
EVENT_COMPLETED = "completed"

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def fill(template: str, mapping: Dict[str, str]) -> str:
    """Port of fill_ (code.js:1082). Unknown placeholders are left untouched, which is
    what the source does — a missing value shows as `{{Name}}` rather than blanking."""
    def repl(m):
        key = m.group(1)
        return str(mapping[key]) if key in mapping and mapping[key] is not None else m.group(0)
    return _PLACEHOLDER.sub(repl, str(template or ""))


def build_map(event: dict, extra: Optional[dict] = None) -> Dict[str, str]:
    """Placeholder values available to every template (buildMap_, code.js:1084)."""
    start = str(event.get("start") or "")
    mapping = {
        "Title": event.get("title") or "",
        "Activity": event.get("activity") or "",
        "Company_Name": event.get("company_name") or "",
        "Company_ID": str(event.get("company_id") or ""),
        "Event_Date": start[:10],
        "Event_Time": start[11:16],
        "Status": event.get("tpms_status") or "",
        "Departments": ", ".join(event.get("assigned_departments") or []),
        "Comment": event.get("additional_details") or "",
        "Schedule_ID": str(event.get("_id") or ""),
    }
    if extra:
        mapping.update({k: v for k, v in extra.items() if v is not None})
    return mapping


async def get_template(activity: str, event_kind: str, side: str) -> Optional[dict]:
    """Most specific template wins: exact activity, then the '*' catch-all."""
    coll = get_collection(COLL_MAIL_TEMPLATES)
    for name in (activity, "*"):
        if not name:
            continue
        doc = await coll.find_one({"activity": name, "side": side,
                                   "event": event_kind, "active": {"$ne": False}})
        if doc:
            return doc
    return None


def _row(label: str, value: str) -> str:
    return (f'<tr><td style="padding:3px 12px 3px 0;color:#64748b">{label}</td>'
            f'<td style="padding:3px 0">{value}</td></tr>')


def _default_body(mapping: Dict[str, str], heading: str) -> str:
    """Port of defaultBody_ (code.js:1090)."""
    return (
        '<div style="font-family:Arial,sans-serif;color:#1e293b;font-size:14px">'
        f'<h3 style="margin:0 0 10px">{heading}: {mapping.get("Title", "")}</h3>'
        '<table style="border-collapse:collapse;font-size:14px">'
        + _row("Activity", f'<b>{mapping.get("Activity", "")}</b>')
        + _row("Company", mapping.get("Company_Name", ""))
        + _row("Scheduled", f'{mapping.get("Event_Date", "")} {mapping.get("Event_Time", "")}')
        + (_row("Departments", mapping.get("Departments", "")) if mapping.get("Departments") else "")
        + (_row("Note", mapping.get("Comment", "")) if mapping.get("Comment") else "")
        + "</table></div>"
    )


async def _recipients(event: dict) -> Dict[str, List[dict]]:
    """Company side = the doers. Staff side = the assigned internal users."""
    from bson import ObjectId

    def name_of(u):
        return (u.get("full_name")
                or " ".join(filter(None, [u.get("first_name"), u.get("last_name")])).strip()
                or u.get("email") or "")

    def to_oids(ids):
        out = []
        for i in ids or []:
            try:
                out.append(ObjectId(str(i)))
            except Exception:
                pass
        return out

    company, staff = [], []
    member_oids = to_oids(event.get("assigned_member_ids"))
    if member_oids:
        for u in await get_collection("learners").find({"_id": {"$in": member_oids}}).to_list(500):
            if u.get("email"):
                company.append({"email": u["email"], "name": name_of(u), "id": str(u["_id"])})
    staff_oids = to_oids(event.get("coach_ids"))
    if staff_oids:
        for u in await get_collection("staff").find({"_id": {"$in": staff_oids}}).to_list(500):
            if u.get("email"):
                staff.append({"email": u["email"], "name": name_of(u), "id": str(u["_id"])})
    return {SIDE_COMPANY: company, SIDE_STAFF: staff}


async def _dispatch(event: dict, event_kind: str, heading: str,
                    extra: Optional[dict] = None) -> dict:
    """Resolve a template per side, fill it and send. Never raises — a mail failure must
    not roll back the action that triggered it (the source wraps every send too)."""
    from app.services.notification_service import send_email_notification

    mapping = build_map(event, extra)
    people = await _recipients(event)
    activity = event.get("activity") or ""
    sent = failed = 0

    for side in (SIDE_STAFF, SIDE_COMPANY):
        recipients = people.get(side) or []
        if not recipients:
            continue
        tpl = await get_template(activity, event_kind, side)
        subject_tpl = (tpl or {}).get("subject") or f"[{heading}] {{{{Title}}}} – {{{{Activity}}}}"
        body_tpl = (tpl or {}).get("body_html")

        for person in recipients:
            person_map = {**mapping, "Recipient_Name": person["name"]}
            subject = fill(subject_tpl, person_map)
            html = fill(body_tpl, person_map) if body_tpl else _default_body(person_map, heading)
            try:
                await send_email_notification(
                    person["email"], subject, html,
                    user_id=person.get("id"), slug=f"tpms_{event_kind}_{side}",
                )
                sent += 1
            except Exception as e:
                failed += 1
                logger.error(f"TPMS {event_kind} mail to {person['email']} failed: {e}")

    return {"sent": sent, "failed": failed}


# ─────────────────────────────────────────────────────────────
# Public API — one call per lifecycle transition
# ─────────────────────────────────────────────────────────────
async def notify_schedule(event: dict) -> dict:
    """Sent on save to both sides (sendScheduleEmails_, code.js:1141)."""
    return await _dispatch(event, EVENT_SCHEDULE, "Scheduled")


async def notify_status(event: dict, status_kind: str, extra: Optional[dict] = None) -> dict:
    """Sent on reschedule / cancel / completion (sendStatusEmails_, code.js:970)."""
    headings = {EVENT_RESCHEDULE: "Rescheduled", EVENT_CANCEL: "Cancelled",
                EVENT_COMPLETED: "Completed"}
    return await _dispatch(event, status_kind, headings.get(status_kind, "Update"), extra)


async def notify_learner_done(event: dict, doer_name: str) -> dict:
    """Staff-only nudge asking them to confirm (markLearnerDone, code.js:3901)."""
    from app.services.notification_service import send_email_notification

    people = await _recipients(event)
    mapping = build_map(event, {"Doer_Name": doer_name})
    subject = fill("[Marked Done] {{Title}} – awaiting your confirmation", mapping)
    html = (
        '<div style="font-family:Arial,sans-serif;color:#1e293b;font-size:14px">'
        '<h3 style="color:#15803d;margin:0 0 10px">Activity marked done by doer</h3>'
        f'<p><b>{doer_name}</b> marked <b>{mapping["Activity"]}</b> '
        f'({mapping["Company_Name"]}) as done. Please confirm to finalize completion.</p>'
        "</div>"
    )
    sent = 0
    for person in people.get(SIDE_STAFF) or []:
        try:
            await send_email_notification(person["email"], subject, html,
                                          user_id=person.get("id"), slug="tpms_learner_done")
            sent += 1
        except Exception as e:
            logger.error(f"TPMS learner-done mail to {person['email']} failed: {e}")
    return {"sent": sent}
