"""
TPMS form links — one unique, secure, per-assignee link per scheduled form.

Replaces the in-app Forms UI. When a form-scored activity is scheduled, every eligible
respondent gets their own row in `tpms_form_assignments` carrying a random token. The token is
the only credential needed to open and submit that one form, so the recipient never logs in.

What makes a token safe to email:
  • 32 random bytes from `secrets` (URL-safe) — not guessable, not derived from any id.
  • Bound at creation to exactly ONE (form_type, period, company, respondent). Nothing about the
    target is encoded in the token, so it cannot be edited to reach another form or user; the
    binding is looked up server-side.
  • Expires at the end of the form's own period (see `period_end_utc`).
  • Single submission: once submitted the row is terminal and further posts are refused.

The rows are also the data source for TPMS ▸ Form Mail Logs, which is why delivery state
(email/WhatsApp status, sent_at) lives on the same document as lifecycle state (opened_at,
submitted_at). One row = one mailed link = one audit line.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId

from app.db.mongodb import get_collection

logger = logging.getLogger(__name__)

ASSIGNMENT_COLLECTION = "tpms_form_assignments"

# ─── Form status (the lifecycle of the LINK, not of the schedule) ───
STATUS_SENT = "sent"           # link generated and mailed, not yet opened
STATUS_OPENED = "opened"       # recipient loaded the form at least once
STATUS_SUBMITTED = "submitted" # answers recorded — terminal
STATUS_EXPIRED = "expired"     # period ended before submission (derived, see `decorate`)

# ─── Delivery status, tracked per channel ───
EMAIL_PENDING = "pending"
EMAIL_SENT = "sent"
EMAIL_FAILED = "failed"
EMAIL_SKIPPED = "skipped"      # no template / notifications off — link exists but was not mailed

# IST, the zone every TPMS date decision is made in.
IST = timezone(timedelta(hours=5, minutes=30))


def period_end_utc(period: str) -> Optional[datetime]:
    """The last instant of `period` ("YYYY-MM") in IST, expressed in UTC.

    A form belongs to a month, so its link stays usable for exactly that month and no longer —
    tying expiry to the business cycle the form already runs on rather than an arbitrary TTL.
    """
    try:
        year, month = int(period[:4]), int(period[5:7])
    except Exception:
        return None
    nxt = datetime(year + (month // 12), (month % 12) + 1, 1, tzinfo=IST)
    return (nxt - timedelta(microseconds=1)).astimezone(timezone.utc)


def new_token() -> str:
    """A fresh, unguessable link credential."""
    return secrets.token_urlsafe(32)


# Where the mailed form link points while running locally. Overridden by the pre-existing
# FRONTEND_URL environment variable — the same one tpms_notify_service has always used — so
# going live is a matter of setting that variable, with no code change here.
#
# It matters that this is ABSOLUTE. A relative href ("/f/<token>") has no base document in an
# email, so the mail client resolves it against its OWN origin — in Gmail the recipient lands on
# https://mail.google.com/f/<token> and sees Google's "Request access" page instead of the form.
# Matches the localhost origin already used elsewhere in the backend (routes/company.py).
LOCAL_FRONTEND_URL = "http://localhost:5173"


def public_link(token: str) -> str:
    """The in-app URL mailed to the recipient: /f/<token>, the assigned-form route.

    Always absolute: FRONTEND_URL when set, otherwise the local development origin.
    """
    base = (os.getenv("FRONTEND_URL") or LOCAL_FRONTEND_URL).rstrip("/")
    return f"{base}/f/{token}"


def _governance_role(user: dict) -> str:
    """A client user's governance role (hod / md). Mirrors forms._user_department so a form's
    audience resolves to the same people here as it does in the Forms API."""
    return (user.get("governance_role") or user.get("department") or "").strip().lower()


def _display_name(user: dict) -> str:
    return (user.get("full_name")
            or " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip()
            or user.get("email") or "")


async def eligible_respondents(company_id: str, form_type: str, assigned_member_ids=None) -> list:
    """Who must fill `form_type` for this company.

    Explicit selection wins: when doers are put on the schedule (`assigned_member_ids`), the form
    goes to EXACTLY those people (that have an email) — it is NEVER fanned out to the whole
    company. This is what stops a single selected doer from mailing every role-holder. Only when
    NO doer is selected do we apply the audience rule — every company user holding the form's
    governance role (HODs for the rating forms, the MD for the feedback checklist).
    Users without an email are dropped: there would be nowhere to send their link.
    """
    from app.models.forms import AUDIENCE_DEPARTMENT, form_audience

    want = AUDIENCE_DEPARTMENT.get(form_audience(form_type))
    if not want or not company_id:
        return []

    learners = get_collection("learners")

    oids = []
    for mid in (assigned_member_ids or []):
        try:
            oids.append(ObjectId(str(mid)))
        except Exception:
            pass
    if oids:
        # Respect the exact people chosen — no role fan-out.
        return [u for u in await learners.find({"_id": {"$in": oids}}).to_list(500) if u.get("email")]

    # No one was selected → the audience rule: every company user holding the form's role.
    return [u for u in await learners.find({"company_id": str(company_id)}).to_list(1000)
            if _governance_role(u) == want and u.get("email")]


async def create_assignment(*, form_type: str, form_title: str, activity: str, period: str,
                            company_id: str, company_name: str, respondent: dict,
                            assigned_by: Optional[dict], event_id: str = "") -> dict:
    """One respondent's link for one form in one period, created idempotently.

    Re-scheduling the same activity must not mint a second link for the same person — the
    recipient would then hold two live URLs for one form and the log would double-count. An
    existing unsubmitted row is reused (and its expiry refreshed); a submitted one is returned
    untouched so a re-schedule can never reopen completed work.
    """
    col = get_collection(ASSIGNMENT_COLLECTION)
    key = {
        "form_type": form_type,
        "period": period,
        "company_id": str(company_id),
        "respondent_id": str(respondent.get("_id")),
    }
    existing = await col.find_one(key)
    if existing:
        if existing.get("status") != STATUS_SUBMITTED:
            await col.update_one(
                {"_id": existing["_id"]},
                {"$set": {"expires_at": period_end_utc(period), "updated_at": datetime.now(timezone.utc)}},
            )
        return existing

    now = datetime.now(timezone.utc)
    token = new_token()
    doc = {
        **key,
        "token": token,
        "link": public_link(token),
        "form_title": form_title,
        "activity": activity,
        "company_name": company_name or "",
        "event_id": str(event_id or ""),
        # Recipient snapshot: the log must stay readable even if the user is later renamed
        # or removed, and the mail needs the address that was actually used.
        "respondent_name": _display_name(respondent),
        "respondent_email": respondent.get("email") or "",
        "respondent_role": _governance_role(respondent),
        "assigned_by_id": str((assigned_by or {}).get("_id") or ""),
        "assigned_by_name": _display_name(assigned_by or {}),
        "status": STATUS_SENT,
        "email_status": EMAIL_PENDING,
        "email_error": None,
        "whatsapp_status": None,
        "sent_at": None,
        "opened_at": None,
        "submitted_at": None,
        "expires_at": period_end_utc(period),
        "created_at": now,
        "updated_at": now,
    }
    await col.insert_one(doc)
    return doc


async def assignments_for_event(event: dict, actor: Optional[dict] = None) -> list:
    """Every assignment a scheduled TPMS event implies — one per (form of the activity ×
    eligible respondent). Empty for activities that are not form-scored, which is what keeps
    this inert for the rest of the TPMS calendar.
    """
    from app.models.forms import ACTIVITY_FORM_MAP, FORM_DEFINITIONS

    forms = ACTIVITY_FORM_MAP.get(event.get("activity") or "")
    if not forms:
        return []

    company_id = str(event.get("company_id") or "")
    period = str(event.get("start") or "")[:7]  # YYYY-MM
    if not company_id or len(period) != 7:
        logger.warning(
            "TPMS form links: '%s' produced none — company_id=%r start=%r (need a company and a "
            "YYYY-MM start date).", event.get("activity"), company_id, event.get("start"),
        )
        return []

    from app.models.forms import AUDIENCE_DEPARTMENT, form_audience

    out = []
    for form_type in forms:
        people = await eligible_respondents(company_id, form_type, event.get("assigned_member_ids"))
        if not people:
            # The commonest reason a scheduled form mail arrives with no link. A form is
            # addressed to a governance ROLE, not to whoever the activity was assigned to:
            # the rating forms go to HODs, the Implementation Feedback checklist to the MD. If
            # the company has nobody carrying that role (or they have no email address) there
            # is no one to issue a link to, and the mail goes out with an empty {{Form_Link}}.
            # Say so explicitly — this used to fail silently, leaving no way to tell why.
            logger.warning(
                "TPMS form links: no recipient for form '%s' (activity '%s', company %s, "
                "period %s). It is addressed to users with governance_role/department '%s'; "
                "none were found with an email address. Set that role on the intended user.",
                form_type, event.get("activity"), company_id, period,
                AUDIENCE_DEPARTMENT.get(form_audience(form_type)),
            )
            continue
        for person in people:
            out.append(await create_assignment(
                form_type=form_type,
                form_title=(FORM_DEFINITIONS.get(form_type) or {}).get("title") or form_type,
                activity=event.get("activity") or "",
                period=period,
                company_id=company_id,
                company_name=event.get("company_name") or "",
                respondent=person,
                assigned_by=actor,
                event_id=str(event.get("_id") or ""),
            ))
    return out


async def mark_email_result(assignment_id, status: str, error: Optional[str] = None) -> None:
    """Record what happened when the link was mailed, for the Form Mail Logs status column."""
    now = datetime.now(timezone.utc)
    updates = {"email_status": status, "email_error": error, "updated_at": now}
    if status == EMAIL_SENT:
        updates["sent_at"] = now
    await get_collection(ASSIGNMENT_COLLECTION).update_one(
        {"_id": assignment_id if isinstance(assignment_id, ObjectId) else ObjectId(str(assignment_id))},
        {"$set": updates},
    )


async def mark_whatsapp_result(assignment_id, status: str) -> None:
    await get_collection(ASSIGNMENT_COLLECTION).update_one(
        {"_id": assignment_id if isinstance(assignment_id, ObjectId) else ObjectId(str(assignment_id))},
        {"$set": {"whatsapp_status": status, "updated_at": datetime.now(timezone.utc)}},
    )


def is_expired(doc: dict, now: Optional[datetime] = None) -> bool:
    """Past its period end and never submitted. A submitted form is finished business and is
    never reported as expired, however long ago its period closed."""
    if not doc or doc.get("status") == STATUS_SUBMITTED:
        return False
    exp = doc.get("expires_at")
    if not exp:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < (now or datetime.now(timezone.utc))


def effective_status(doc: dict, now: Optional[datetime] = None) -> str:
    """Status as it should be shown. Expiry is DERIVED rather than written by a sweep, so a link
    is never briefly reported live after its period closed just because no job has run yet."""
    if is_expired(doc, now):
        return STATUS_EXPIRED
    return doc.get("status") or STATUS_SENT


async def resolve_token(token: str) -> Optional[dict]:
    """The assignment a link token refers to, or None when the token is unknown.

    Returns expired and submitted rows too — the public route needs to tell the recipient WHY a
    link no longer works, which it cannot do if invalid tokens are indistinguishable from
    missing ones.
    """
    if not token:
        return None
    return await get_collection(ASSIGNMENT_COLLECTION).find_one({"token": token})


async def mark_opened(doc: dict) -> None:
    """First open moves Sent → Opened. Later opens only refresh nothing: `opened_at` records the
    FIRST view, which is what the log column means."""
    if doc.get("status") != STATUS_SENT:
        return
    await get_collection(ASSIGNMENT_COLLECTION).update_one(
        {"_id": doc["_id"], "status": STATUS_SENT},
        {"$set": {"status": STATUS_OPENED,
                  "opened_at": datetime.now(timezone.utc),
                  "updated_at": datetime.now(timezone.utc)}},
    )


async def mark_submitted(doc: dict) -> None:
    now = datetime.now(timezone.utc)
    await get_collection(ASSIGNMENT_COLLECTION).update_one(
        {"_id": doc["_id"]},
        {"$set": {"status": STATUS_SUBMITTED, "submitted_at": now, "updated_at": now}},
    )
