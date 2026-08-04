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
import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

from app.db.mongodb import get_collection
from app.models.tpms import COLL_MAIL_TEMPLATES, TPMS_NOTIFICATIONS_ENABLED

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


async def _resolve_names(ids, collection: str) -> str:
    """Comma-joined display names for a list of user ids from a collection."""
    from bson import ObjectId
    oids = []
    for i in ids or []:
        try:
            oids.append(ObjectId(str(i)))
        except Exception:
            pass
    if not oids:
        return ""
    names = []
    for u in await get_collection(collection).find({"_id": {"$in": oids}}).to_list(200):
        n = (u.get("full_name")
             or " ".join(filter(None, [u.get("first_name"), u.get("last_name")])).strip()
             or u.get("email") or "")
        if n:
            names.append(n)
    return ", ".join(names)


# Spec §11 — a form may set `noCid` to suppress the company parameter on its deep link.
# Keyed by form_type; add an entry to opt a form out.
FORM_NO_CID = {
    # "implementation_feedback": True,
}


def _form_link(event: dict) -> str:
    """In-app deep link for form-scored activities (spec §11 "HOD Form Links").

    Carries CID / EID / MID (Company / Employee / Month) so the form opens already scoped
    instead of dropping the recipient on a blank month — unless the form sets `noCid`, in
    which case the company parameter is omitted. `period` is emitted alongside MID because
    the ERP form components read that name; same value, both spellings, so the link works
    from mail and from the in-app "My Forms" list alike.
    Absolute when FRONTEND_URL is set, else relative. Empty for non-form activities.
    """
    try:
        from app.models.forms import ACTIVITY_FORM_MAP
        forms = ACTIVITY_FORM_MAP.get(event.get("activity") or "")
    except Exception:
        forms = None
    if not forms:
        return ""

    from urllib.parse import urlencode
    form_type = forms[0]
    members = event.get("assigned_member_ids") or []
    params = {
        "CID": "" if FORM_NO_CID.get(form_type) else str(event.get("company_id") or ""),
        "EID": str(members[0]) if members else "",
        "MID": str(event.get("start") or "")[:7],   # YYYY-MM
    }
    params = {k: v for k, v in params.items() if v}
    if params.get("MID"):
        params["period"] = params["MID"]

    path = f"/tpms/forms/{form_type.replace('_', '-')}"
    if params:
        path = f"{path}?{urlencode(params)}"
    base = os.getenv("FRONTEND_URL", "").rstrip("/")
    return (base + path) if base else path


async def build_map(event: dict, extra: Optional[dict] = None) -> Dict[str, str]:
    """Placeholder values available to every template (buildMap_, code.js:1084)."""
    start = str(event.get("start") or "")
    meta = event.get("activity_meta") or {}
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
        # Previously-unfilled placeholders (rendered as literal {{…}} before this fix).
        "Staff_Assigner": await _resolve_names(event.get("coach_ids"), "staff"),
        "Company_Assigners": await _resolve_names(event.get("assigned_member_ids"), "learners"),
        "Session_Type": (str(meta.get("scope") or "").upper() or (event.get("activity") or "")),
        "Form_Link": _form_link(event),
    }
    if extra:
        mapping.update({k: v for k, v in extra.items() if v is not None})
    return mapping


def log_context(event: dict) -> Dict[str, str]:
    """Spec §14 — the delivery log is joined to its activity so the Logs Report can show
    Activity / Company / Date next to the send result. Recorded at write time rather than
    resolved afterwards, because the log has no other route back to the schedule."""
    return {
        "event_id": str(event.get("_id") or ""),
        "activity": event.get("activity") or "",
        "company_id": str(event.get("company_id") or ""),
        "company_name": event.get("company_name") or "",
        "event_date": str(event.get("start") or "")[:10],
    }


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

    def phone_of(u):
        return u.get("mobile") or u.get("phone") or u.get("whatsapp") or ""

    company, staff = [], []
    member_oids = to_oids(event.get("assigned_member_ids"))
    if member_oids:
        for u in await get_collection("learners").find({"_id": {"$in": member_oids}}).to_list(500):
            if u.get("email"):
                company.append({"email": u["email"], "name": name_of(u), "id": str(u["_id"]), "phone": phone_of(u)})
    staff_oids = to_oids(event.get("coach_ids"))
    if staff_oids:
        for u in await get_collection("staff").find({"_id": {"$in": staff_oids}}).to_list(500):
            if u.get("email"):
                staff.append({"email": u["email"], "name": name_of(u), "id": str(u["_id"]), "phone": phone_of(u)})
    return {SIDE_COMPANY: company, SIDE_STAFF: staff}


# ─────────────────────────────────────────────────────────────
# H1 — WhatsApp send layer (Meta templates). Sending is gated by the TPMS switch, so this is
# fully dormant while notifications are off; the resolution/normalisation logic is ready.
# ─────────────────────────────────────────────────────────────
def normalize_phone(raw: str) -> str:
    """Spec §11 — strip non-digits, strip leading zeros, then prefix the country code when
    exactly 10 digits remain. The zero-strip is what makes a locally-dialled "09876543210"
    resolve to the same number as "9876543210"."""
    digits = re.sub(r"\D", "", str(raw or ""))
    digits = digits.lstrip("0")
    if not digits:
        return ""
    if len(digits) == 10:
        digits = "91" + digits
    return digits


# Spec §11 — waGuessField_: when a template variable isn't a known placeholder name, infer
# the intended field from the words in it. Ordered most-specific first, because "event date"
# must match the date rule before the generic "event" one would ever apply.
_WA_GUESS_RULES = [
    (("date", "day", "schedule"), "Event_Date"),
    (("time", "hour"), "Event_Time"),
    (("activity", "task"), "Activity"),
    (("company", "client", "org"), "Company_Name"),
    (("title", "subject", "name of"), "Title"),
    (("status", "state"), "Status"),
    (("department", "dept"), "Departments"),
    (("staff", "om", "smops"), "Staff_Assigner"),
    (("doer", "assigner", "member", "employee"), "Company_Assigners"),
    (("link", "url", "form"), "Form_Link"),
    (("comment", "note", "remark"), "Comment"),
    (("recipient", "to"), "Recipient_Name"),
]


def wa_guess_field(variable: str, mapping: Dict[str, str]) -> str:
    """Best-effort value for an unmapped template variable. Returns "" when nothing fits,
    which leaves the caller's "-" guard in charge (Meta rejects blank params)."""
    needle = str(variable or "").replace("_", " ").lower()
    if not needle:
        return ""
    for words, field in _WA_GUESS_RULES:
        if any(w in needle for w in words):
            value = mapping.get(field)
            if value:
                return str(value)
    return ""


async def get_whatsapp_template(activity: str, event_kind: str, side: str) -> Optional[dict]:
    """Most-specific WhatsApp template wins: exact activity, then '*'. Returns None when no
    row exists — the business's per-event on/off switch ("no template row = skip")."""
    from app.models.tpms import COLL_WHATSAPP_TEMPLATES
    coll = get_collection(COLL_WHATSAPP_TEMPLATES)
    for name in (activity, "*"):
        if not name:
            continue
        doc = await coll.find_one({"activity": name, "side": side,
                                   "event": event_kind, "active": {"$ne": False}})
        if doc:
            return doc
    return None


async def send_whatsapp(event: dict, event_kind: str, side: str) -> dict:
    """Resolve a Meta template, map ordered positional params from build_map, normalise
    phones, and send. No template row → skip (returns skipped=1). Gated by the TPMS switch."""
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"sent": 0, "skipped": 0}
    tpl = await get_whatsapp_template(event.get("activity") or "", event_kind, side)
    if not tpl:
        return {"sent": 0, "skipped": 1}  # no template = intentional skip
    from app.services.notification_service import send_whatsapp_template

    mapping = await build_map(event)
    # Meta requires ORDERED params; the template row stores the variable order. A variable
    # that doesn't name a known field falls back to the heuristic guesser (spec §11) rather
    # than silently sending "-".
    var_keys = tpl.get("variables") or []
    params = [str(mapping.get(k) or wa_guess_field(k, mapping) or "-") for k in var_keys]
    people = await _recipients(event)
    sent = failed = 0
    for person in people.get(side) or []:
        phone = normalize_phone(person.get("phone"))
        if not phone:
            continue
        try:
            await send_whatsapp_template(phone, tpl.get("meta_template_name") or tpl.get("name"),
                                         tpl.get("language") or "en", params,
                                         user_id=person.get("id"), slug=f"tpms_wa_{event_kind}_{side}")
            sent += 1
        except Exception as e:
            failed += 1
            logger.error(f"TPMS WhatsApp to {phone} failed: {e}")
    return {"sent": sent, "failed": failed, "skipped": 0}


async def _dispatch(event: dict, event_kind: str, heading: str,
                    extra: Optional[dict] = None) -> dict:
    """Resolve a template per side, fill it and send. Never raises — a mail failure must
    not roll back the action that triggered it (the source wraps every send too)."""
    # TPMS notifications globally disabled → send nothing (schedule/reschedule/cancel/complete).
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"sent": 0, "failed": 0}
    from app.services.notification_service import send_email_notification

    mapping = await build_map(event, extra)
    people = await _recipients(event)
    activity = event.get("activity") or ""
    sent = failed = 0

    for side in (SIDE_STAFF, SIDE_COMPANY):
        recipients = people.get(side) or []
        if not recipients:
            continue
        tpl = await get_template(activity, event_kind, side)
        # Strictly respect the template's Active/Inactive status. get_template returns None when
        # the template is Inactive OR not configured — in BOTH cases send nothing for this side:
        # no default subject, no _default_body fallback. Only an Active template that has a body
        # is used for delivery.
        if not tpl or not tpl.get("body_html"):
            continue
        subject_tpl = tpl.get("subject") or f"[{heading}] {{{{Title}}}} – {{{{Activity}}}}"
        body_tpl = tpl.get("body_html")

        for person in recipients:
            person_map = {**mapping, "Recipient_Name": person["name"]}
            subject = fill(subject_tpl, person_map)
            html = fill(body_tpl, person_map)
            try:
                await send_email_notification(
                    person["email"], subject, html,
                    user_id=person.get("id"), slug=f"tpms_{event_kind}_{side}",
                    meta=log_context(event),
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


# ─────────────────────────────────────────────────────────────
# Async status mail (spec §11 "Async Mail Queue", §1.4, §5.18)
#
# The source queued the job and fired a one-off trigger ~3 seconds later so updateSchedule
# returned to the UI immediately. The asyncio equivalent is to detach the send onto the
# running loop: the caller returns as soon as the hand-off is accepted, and the sends
# proceed in the background.
#
# §18.14 — if the hand-off cannot be scheduled (no running loop), the mail is sent inline
# straight away rather than lost. Strong references are held until each task finishes,
# otherwise the loop may garbage-collect a send mid-flight.
# ─────────────────────────────────────────────────────────────
_BACKGROUND_SENDS: set = set()


async def _dispatch_detached(event: dict, event_kind: str, heading: str,
                             extra: Optional[dict]) -> None:
    try:
        await _dispatch(event, event_kind, heading, extra)
    except Exception as e:
        logger.error(f"TPMS detached {event_kind} mail failed: {e}")


def _enqueue_status_mail(event: dict, event_kind: str, heading: str,
                         extra: Optional[dict]) -> bool:
    """Hand the send to the event loop. False = could not be scheduled, send inline."""
    if not TPMS_NOTIFICATIONS_ENABLED:
        return False          # nothing to queue; _dispatch will no-op immediately
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False          # no loop (sync context / shutdown) → inline fallback
    task = loop.create_task(_dispatch_detached(event, event_kind, heading, extra))
    _BACKGROUND_SENDS.add(task)
    task.add_done_callback(_BACKGROUND_SENDS.discard)
    return True


async def notify_status(event: dict, status_kind: str, extra: Optional[dict] = None) -> dict:
    """Sent on reschedule / cancel / completion (sendStatusEmails_, code.js:970).

    Detached so the caller — updateSchedule, confirmCompletion, the reschedule decision —
    returns without waiting on delivery to every assigned recipient. Schedule mail is
    deliberately NOT detached: the spec scopes the queue to status-change mail only.
    """
    headings = {EVENT_RESCHEDULE: "Rescheduled", EVENT_CANCEL: "Cancelled",
                EVENT_COMPLETED: "Completed"}
    heading = headings.get(status_kind, "Update")
    if _enqueue_status_mail(event, status_kind, heading, extra):
        return {"queued": 1, "sent": 0, "failed": 0}
    return await _dispatch(event, status_kind, heading, extra)


async def notify_learner_done(event: dict, doer_name: str) -> dict:
    """Staff-only nudge asking them to confirm (markLearnerDone, code.js:3901)."""
    # TPMS notifications globally disabled → no confirm-me nudge.
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"sent": 0}
    from app.services.notification_service import send_email_notification

    people = await _recipients(event)
    mapping = await build_map(event, {"Doer_Name": doer_name})
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


async def notify_reschedule_request(event: dict, requester_name: str, new_date: str) -> dict:
    """H9 — tell internal staff a doer has REQUESTED a reschedule. Staff-side only."""
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"sent": 0}
    from app.services.notification_service import send_email_notification

    people = await _recipients(event)
    mapping = await build_map(event, {"Requested_By": requester_name, "New_Date": new_date})
    subject = fill("[Reschedule Requested] {{Title}} – {{Activity}}", mapping)
    html = (
        '<div style="font-family:Arial,sans-serif;color:#1e293b;font-size:14px">'
        '<h3 style="color:#b45309;margin:0 0 10px">Reschedule requested</h3>'
        f'<p><b>{requester_name}</b> requested to reschedule <b>{mapping["Activity"]}</b> '
        f'({mapping["Company_Name"]}) to <b>{new_date}</b>. Please review and approve or reject.</p>'
        "</div>"
    )
    sent = 0
    for person in people.get(SIDE_STAFF) or []:
        try:
            await send_email_notification(person["email"], subject, html,
                                          user_id=person.get("id"), slug="tpms_reschedule_request")
            sent += 1
        except Exception as e:
            logger.error(f"TPMS reschedule-request mail to {person['email']} failed: {e}")
    return {"sent": sent}


async def notify_reschedule_decision(event: dict, approved: bool, note: str = "") -> dict:
    """H9 — tell the doer(s) their reschedule request was approved/rejected. Company-side only.
    (Approval ALSO sends the standard reschedule status mail to both sides via notify_status.)"""
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"sent": 0}
    from app.services.notification_service import send_email_notification

    people = await _recipients(event)
    mapping = await build_map(event, {"Note": note})
    verdict = "approved" if approved else "rejected"
    color = "#15803d" if approved else "#b91c1c"
    subject = fill(f"[Reschedule {verdict.title()}] {{{{Title}}}} – {{{{Activity}}}}", mapping)
    html = (
        '<div style="font-family:Arial,sans-serif;color:#1e293b;font-size:14px">'
        f'<h3 style="color:{color};margin:0 0 10px">Reschedule {verdict}</h3>'
        f'<p>Your reschedule request for <b>{mapping["Activity"]}</b> ({mapping["Company_Name"]}) '
        f'was <b>{verdict}</b>.{(" Note: " + note) if note else ""}</p>'
        "</div>"
    )
    sent = 0
    for person in people.get(SIDE_COMPANY) or []:
        try:
            await send_email_notification(person["email"], subject, html,
                                          user_id=person.get("id"), slug=f"tpms_reschedule_{verdict}")
            sent += 1
        except Exception as e:
            logger.error(f"TPMS reschedule-decision mail to {person['email']} failed: {e}")
    return {"sent": sent}


async def notify_form_submission(*, form_type: str, title: str, company_id: str, period: str,
                                 respondent_id: str, respondent_name: str,
                                 ratings: Optional[List[dict]] = None) -> dict:
    """H3 — after a review form is submitted: a summary mail to the HOD/MD respondent, plus a
    per-employee scorecard mail to each rated team member (rating forms only). Gated."""
    if not TPMS_NOTIFICATIONS_ENABLED:
        return {"summary_sent": 0, "employee_sent": 0}
    from bson import ObjectId
    from app.services.notification_service import send_email_notification

    def _wrap(heading, inner, color="#4f46e5"):
        return ('<div style="font-family:Arial,sans-serif;color:#1e293b;font-size:14px;max-width:600px;margin:auto">'
                f'<h3 style="color:{color};margin:0 0 10px">{heading}</h3>' + inner + '</div>')

    async def _find(uid):
        try:
            return await get_collection("learners").find_one({"_id": ObjectId(str(uid))})
        except Exception:
            return None

    summary_sent = employee_sent = 0

    # 1) Respondent (HOD/MD) summary.
    respondent = await _find(respondent_id)
    if respondent and respondent.get("email"):
        html = _wrap(f"{title} submitted",
                     f"<p>Your <b>{title}</b> submission for <b>{period}</b> has been received. Thank you.</p>")
        try:
            await send_email_notification(respondent["email"], f"[{title}] Submission received – {period}",
                                          html, user_id=str(respondent["_id"]), slug=f"tpms_form_{form_type}_summary")
            summary_sent += 1
        except Exception as e:
            logger.error(f"TPMS form summary mail failed: {e}")

    # 2) Per-employee scorecards (rating forms only).
    if ratings:
        by_member: Dict[tuple, List[dict]] = {}
        for c in ratings:
            by_member.setdefault((str(c.get("member_id")), c.get("member_name") or ""), []).append(c)
        for (mid, mname), cells in by_member.items():
            member = await _find(mid)
            if not member or not member.get("email"):
                continue
            rows = "".join(
                f'<tr><td style="padding:3px 12px 3px 0;color:#64748b">{c.get("criterion_code")}</td>'
                f'<td style="padding:3px 0"><b>{c.get("rating")}</b>/5</td></tr>' for c in cells)
            html = _wrap(f"Your {title} scorecard – {period}",
                         f'<p>Hello {mname or member.get("full_name","")}, your ratings for <b>{period}</b>:</p>'
                         f'<table style="border-collapse:collapse;font-size:14px">{rows}</table>')
            try:
                await send_email_notification(member["email"], f"[{title}] Your scorecard – {period}",
                                              html, user_id=str(member["_id"]), slug=f"tpms_form_{form_type}_scorecard")
                employee_sent += 1
            except Exception as e:
                logger.error(f"TPMS form scorecard mail failed: {e}")

    return {"summary_sent": summary_sent, "employee_sent": employee_sent}
