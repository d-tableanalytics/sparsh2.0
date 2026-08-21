"""
TPMS ▸ Leadership Score — feedback-giver links and email dispatch.

One unique, unguessable link per (subject × feedback giver), mailed to the giver, opened
at /lf/<token>, submitted once. This mirrors the security model already proven by
`tpms_form_link_service` for the four existing TPMS forms:

  • 32 random bytes from `secrets` — not guessable, not derived from any id.
  • Bound at creation to exactly ONE (cycle, subject, giver). Nothing about the target is
    encoded in the token, so it cannot be edited to reach another leader or another giver.
  • Expires at the end of the cycle's closing month.
  • Single submission: once submitted the row is terminal.

STORAGE ISOLATION
-----------------
Rows live in `tpms_leadership_assignments`, a NEW collection. `tpms_form_assignments` —
which carries the live links for Accountability / Ownership / Culture / Implementation
Feedback — is never read or written here, so the existing Form Mail Logs, resend action
and expiry behaviour are untouched. Only the pure helpers `new_token()` and
`public_link()`-style URL building are conceptually shared; nothing about storage is.

MAIL ISOLATION
--------------
Dispatch calls `notification_service.send_email_notification` directly. It deliberately
does NOT route through `tpms_notify_service`, because that service's form hooks
(`_recipient_form_links`, `notify_form_submission`) are bound to the existing four forms
and to a schedule event, and `notify_form_submission` mails a per-employee scorecard —
which would breach the anonymity this module is required to preserve.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from bson import ObjectId

from app.db.mongodb import get_collection
from app.models.leadership import (
    COLL_LS_ASSIGNMENTS,
    DEFAULT_TEMPLATE_BODY, DEFAULT_TEMPLATE_SUBJECT,
    EMAIL_FAILED, EMAIL_PENDING, EMAIL_SENT,
    LEVEL_LABELS,
    LINK_EXPIRED, LINK_OPENED, LINK_PENDING, LINK_SENT, LINK_SUBMITTED,
    RELATION_LABELS, RESEND_COOLDOWN_HOURS,
    TEMPLATE_ACTIVITY, TEMPLATE_EVENT, TEMPLATE_SIDE,
    cycle_label, cycle_period,
)

logger = logging.getLogger(__name__)

# IST — the zone every TPMS date decision is made in.
IST = timezone(timedelta(hours=5, minutes=30))

# Matches the fallback origin used elsewhere in the backend; FRONTEND_URL overrides it.
LOCAL_FRONTEND_URL = "http://localhost:5173"


def new_token() -> str:
    """A fresh, unguessable link credential."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """What is stored. The raw token is a live credential — anyone holding it can submit
    as that giver for the whole window — so it is kept only in the recipient's mailbox,
    never in the database. A lookup hashes the incoming value and matches on that.

    Plain SHA-256 is right here, not a password KDF: the token is 32 bytes from `secrets`,
    so there is no dictionary to attack and stretching would only slow every form open."""
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def public_link(token: str) -> str:
    """The in-app URL mailed to the giver: /lf/<token>.

    Always absolute. A relative href has no base document in an email, so the mail client
    would resolve it against its own origin and the recipient would land on a dead page.
    """
    base = (os.getenv("FRONTEND_URL") or LOCAL_FRONTEND_URL).rstrip("/")
    return f"{base}/lf/{token}"


def cycle_expiry_utc(cycle: str) -> Optional[datetime]:
    """Last instant of the cycle's closing month in IST, expressed in UTC.

    A cycle spans two months, so its links stay usable for exactly that window — tied to
    the business cycle rather than an arbitrary TTL.
    """
    try:
        period = cycle_period(cycle)
        year, month = int(period[:4]), int(period[5:7])
    except Exception:
        return None
    nxt = datetime(year + (month // 12), (month % 12) + 1, 1, tzinfo=IST)
    return (nxt - timedelta(microseconds=1)).astimezone(timezone.utc)


def cycle_is_expired(cycle: str, now: Optional[datetime] = None) -> bool:
    """Whether the cycle's own window has closed. Independent of any assignment row."""
    exp = cycle_expiry_utc(cycle)
    if not exp:
        return False
    return exp < (now or datetime.now(timezone.utc))


def resend_blocked_until(doc: dict) -> Optional[datetime]:
    """When this invitation becomes eligible for another automatic send, or None if now.

    Keyed on `sent_at`, which is written only on a SUCCESSFUL send. A row that has never
    been mailed, or whose last attempt failed, therefore has no cooldown and goes out
    immediately — a cooldown must never be the reason someone is left without their link.
    """
    if doc.get("email_status") != EMAIL_SENT:
        return None
    sent_at = doc.get("sent_at")
    if not sent_at:
        return None
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    return sent_at + timedelta(hours=RESEND_COOLDOWN_HOURS)


def in_resend_cooldown(doc: dict, now: Optional[datetime] = None) -> bool:
    until = resend_blocked_until(doc)
    return bool(until and until > (now or datetime.now(timezone.utc)))


def is_expired(doc: dict, now: Optional[datetime] = None) -> bool:
    """Past its window and never submitted. A submitted form is finished business and is
    never reported as expired, however long ago its cycle closed."""
    if not doc or doc.get("status") == LINK_SUBMITTED:
        return False
    exp = doc.get("expires_at")
    if not exp:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < (now or datetime.now(timezone.utc))


def effective_status(doc: dict, now: Optional[datetime] = None) -> str:
    """Status as it should be shown. Expiry is DERIVED, not written by a sweep, so a link
    is never briefly reported live after its cycle closed just because no job has run."""
    if is_expired(doc, now):
        return LINK_EXPIRED
    return doc.get("status") or LINK_SENT


def _display_name(user: dict) -> str:
    return (user.get("full_name")
            or " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip()
            or user.get("email") or "")


async def create_assignment(*, company_id: str, company_name: str, cycle: str,
                            subject: dict, giver: dict, relation: str,
                            assigned_by: Optional[dict] = None) -> dict:
    """One giver's link for one subject in one cycle, created idempotently.

    Re-dispatching a cycle must not mint a second link for the same pairing — the giver
    would hold two live URLs for one form and the log would double-count. An existing
    unsubmitted row is reused (expiry refreshed); a submitted one is returned untouched so
    a re-dispatch can never reopen completed feedback.
    """
    col = get_collection(COLL_LS_ASSIGNMENTS)
    key = {
        "company_id": str(company_id),
        "cycle": str(cycle),
        "subject_id": str(subject.get("subject_id")),
        "giver_id": str(giver.get("_id")),
    }
    existing = await col.find_one(key)
    if existing:
        if existing.get("status") != LINK_SUBMITTED:
            await col.update_one(
                {"_id": existing["_id"]},
                {"$set": {"expires_at": cycle_expiry_utc(cycle),
                          "relation": relation,
                          "updated_at": datetime.now(timezone.utc)}},
            )
            existing["relation"] = relation
        return existing

    now = datetime.now(timezone.utc)
    token = new_token()
    doc = {
        **key,
        "period": cycle_period(cycle),
        # The hash only. `_issued_token` carries the raw value back to the caller in
        # memory so this dispatch can mail it; it is never persisted and never returned by
        # an API. A resend mints a fresh token (see rotate_token).
        "token_hash": token_hash(token),
        "relation": relation,
        "company_name": company_name or "",
        # Subject snapshot: the giver's form must still name the leader correctly even if
        # the user record is later renamed.
        "subject_name": subject.get("subject_name") or "",
        "subject_level": subject.get("level") or "",
        "subject_designation": subject.get("designation") or "",
        # Giver snapshot. Held for dispatch, authorization and duplicate prevention only —
        # never serialized to a leader. See leadership_service._public_* helpers.
        "giver_name": _display_name(giver),
        "giver_email": giver.get("email") or "",
        # Snapshotted for the reminder ladder, which mails and messages non-submitters
        # without ever reading a response. Absent on rows created before this field
        # existed — leadership_notify_service falls back to a roster lookup for those.
        "giver_phone": giver.get("mobile") or "",
        "assigned_by_id": str((assigned_by or {}).get("_id") or ""),
        "assigned_by_name": _display_name(assigned_by or {}),
        # Not "sent": nothing has been mailed yet. mark_email_result promotes it.
        "status": LINK_PENDING,
        "email_status": EMAIL_PENDING,
        "email_error": None,
        "sent_at": None,
        "opened_at": None,
        "submitted_at": None,
        "expires_at": cycle_expiry_utc(cycle),
        "created_at": now,
        "updated_at": now,
    }
    await col.insert_one(doc)
    doc["_issued_token"] = token
    return doc


async def remove_assignment(company_id: str, cycle: str, subject_id: str, giver_id: str) -> bool:
    """Drop a panel member who has not yet submitted. A submitted row is kept — removing it
    would silently delete collected feedback."""
    col = get_collection(COLL_LS_ASSIGNMENTS)
    res = await col.delete_one({
        "company_id": str(company_id), "cycle": str(cycle),
        "subject_id": str(subject_id), "giver_id": str(giver_id),
        "status": {"$ne": LINK_SUBMITTED},
    })
    return res.deleted_count > 0


async def resolve_token(token: str) -> Optional[dict]:
    """The assignment a link token refers to, or None when unknown.

    Matches on the HASH. Rows issued before hashing still carry a plaintext `token`, and
    those links are already in people's inboxes, so they are accepted as a second lookup —
    a giver must not be locked out of a form because of when their link was minted. Such a
    row is marked `legacy_token` so the admin screen can show which invitations still hold
    a credential in the database, and rotating one clears it for good.

    Returns expired and submitted rows too: the form page has to tell the giver WHY a link
    no longer works, which it cannot do if a dead token is indistinguishable from a typo.
    """
    if not token:
        return None
    col = get_collection(COLL_LS_ASSIGNMENTS)
    doc = await col.find_one({"token_hash": token_hash(token)})
    if doc:
        return doc
    legacy = await col.find_one({"token": token})
    if legacy:
        legacy["legacy_token"] = True
    return legacy


async def rotate_token(doc: dict) -> str:
    """Issue a fresh credential for an existing invitation and return it, once.

    Resending has to produce a working URL, and the old one cannot be reproduced because
    only its hash was kept. So a resend mints a new token and the previous link stops
    working. That is the safer default for a single-use form — a forwarded or leaked link
    dies the moment the real recipient is chased again — and it is what the resend button
    tells HR it will do.

    Also the repair path for a legacy row: rotating drops the plaintext `token` field, so
    the credential stops existing in the database.
    """
    token = new_token()
    await get_collection(COLL_LS_ASSIGNMENTS).update_one(
        {"_id": doc["_id"]},
        {"$set": {"token_hash": token_hash(token),
                  "updated_at": datetime.now(timezone.utc)},
         "$unset": {"token": "", "link": ""}},
    )
    doc["token_hash"] = token_hash(token)
    doc.pop("token", None)
    doc.pop("link", None)
    doc["_issued_token"] = token
    return token


async def claim_for_submission(doc: dict) -> bool:
    """Atomically take this invitation from open to submitted. True if this caller won it.

    This is what makes a response safe to store with NO rater identity on it. Duplicate
    submission used to be prevented by a unique index over (cycle, subject, giver_id) on
    the RESPONSE — which meant every answer carried the name of the person who gave it,
    permanently, to enforce a rule that belongs on the invitation.

    The filter is the lock: `status` must still be one of the open states, so two
    concurrent submits cannot both match, and only the winner goes on to write a response.
    If writing that response then fails, `release_claim` puts the row back.
    """
    now = datetime.now(timezone.utc)
    res = await get_collection(COLL_LS_ASSIGNMENTS).update_one(
        {"_id": doc["_id"], "status": {"$in": [LINK_PENDING, LINK_SENT, LINK_OPENED]}},
        {"$set": {"status": LINK_SUBMITTED, "submitted_at": now, "updated_at": now},
         # The credential has done its job. Removing it here is what "single use" means:
         # the link is dead in the database, not merely refused by a status check.
         "$unset": {"token_hash": "", "token": "", "link": ""}},
    )
    return res.modified_count == 1


async def release_claim(doc: dict) -> None:
    """Undo a claim whose response could not be written, so the giver can try again."""
    await get_collection(COLL_LS_ASSIGNMENTS).update_one(
        {"_id": doc["_id"], "status": LINK_SUBMITTED},
        {"$set": {"status": LINK_OPENED, "submitted_at": None,
                  "updated_at": datetime.now(timezone.utc)}},
    )


async def mark_opened(doc: dict) -> None:
    """First open moves Pending/Sent → Opened. `opened_at` records the FIRST view.

    Pending is accepted as well as Sent: opening the form is proof the link reached its
    owner, whatever the delivery log believes.
    """
    if doc.get("status") not in (LINK_PENDING, LINK_SENT):
        return
    now = datetime.now(timezone.utc)
    await get_collection(COLL_LS_ASSIGNMENTS).update_one(
        {"_id": doc["_id"], "status": {"$in": [LINK_PENDING, LINK_SENT]}},
        {"$set": {"status": LINK_OPENED, "opened_at": now, "updated_at": now}},
    )


async def mark_email_result(assignment_id, status: str, error: Optional[str] = None) -> None:
    now = datetime.now(timezone.utc)
    oid = assignment_id if isinstance(assignment_id, ObjectId) else ObjectId(str(assignment_id))
    updates = {"email_status": status, "email_error": error, "updated_at": now}
    if status == EMAIL_SENT:
        # `sent_at` is the cooldown's key, so it is written ONLY on a real delivery.
        updates["sent_at"] = now
    col = get_collection(COLL_LS_ASSIGNMENTS)
    await col.update_one({"_id": oid}, {"$set": updates})

    # A real delivery is also what turns a minted link into a Sent one. Done as a separate,
    # FILTERED update so it can only ever move pending -> sent: a resend of a link the giver
    # has already opened or submitted must not drag its status backwards.
    if status == EMAIL_SENT:
        await col.update_one({"_id": oid, "status": LINK_PENDING},
                             {"$set": {"status": LINK_SENT}})


async def get_invite_template() -> Optional[dict]:
    """The stored Leadership invitation template, or None when none has been authored.

    Reads the existing `tpms_mail_templates` collection through the same helper the rest of
    TPMS uses, so an inactive row is ignored and the "*" catch-all still applies — but only
    within the leadership_invite event, which nothing else writes.
    """
    from app.services.tpms_notify_service import get_template
    try:
        return await get_template(TEMPLATE_ACTIVITY, TEMPLATE_EVENT, TEMPLATE_SIDE)
    except Exception as e:
        logger.error("Leadership template lookup failed (%s) — using the default body", e)
        return None


def template_map(doc: dict, link: str = "") -> dict:
    """Placeholder values for ONE assignment.

    `leadership_link` is the URL minted for this send. It is passed in rather than read
    off the row, because the row holds only a hash — the raw credential exists for the
    length of one dispatch and then only in the recipient's mailbox. Because the map is
    rebuilt per assignment, two givers can never receive the same link, which is what
    keeps both single-use submission and anonymity intact.
    """
    expires = doc.get("expires_at")
    return {
        "leadership_link": link or "",
        "giver_name": doc.get("giver_name") or "",
        "subject_name": doc.get("subject_name") or "a colleague",
        "subject_designation": doc.get("subject_designation") or "",
        "level_label": LEVEL_LABELS.get(doc.get("subject_level") or "", doc.get("subject_level") or ""),
        "cycle_label": cycle_label(doc.get("cycle") or ""),
        "company_name": doc.get("company_name") or "",
        "expires_on": expires.strftime("%Y-%m-%d") if hasattr(expires, "strftime") else "",
    }


def _ensure_link_present(html: str, link: str) -> str:
    """Append the link if the rendered body does not already carry it.

    An author who forgets `{{leadership_link}}` would otherwise send an invitation with no
    way to act on it, and the giver has no other route to the form — they are never given a
    token to enter by hand. This is the same guarantee the TPMS schedule mail makes.
    """
    if not link or link in (html or ""):
        return html
    return (html or "") + (
        '<div style="margin-top:18px;padding:14px 16px;border:1px solid #e5e7eb;'
        'border-radius:10px;background:#fafafa;font-family:Arial,sans-serif">'
        '<p style="margin:0 0 8px;font-weight:700;font-size:13px">Your feedback link</p>'
        f'<p style="margin:6px 0"><a href="{link}" style="color:#4f46e5;font-weight:700">'
        'Give your feedback</a></p>'
        '<p style="margin:8px 0 0;font-size:11px;color:#6b7280">'
        'This link is personal to you and can be submitted once.</p></div>'
    )


async def render_invite(doc: dict, template: Optional[dict] = None, link: str = "") -> tuple:
    """(subject, html) for one giver — template if configured, built-in default otherwise.

    Pass `template` when sending a batch so the row is fetched once rather than per
    recipient; the FILLING still happens per recipient, which is what personalises the link.
    """
    tpl = template if template is not None else await get_invite_template()
    mapping = template_map(doc, link)

    from app.services.tpms_notify_service import fill
    subject_tpl = (tpl or {}).get("subject") or DEFAULT_TEMPLATE_SUBJECT
    body_tpl = (tpl or {}).get("body_html") or DEFAULT_TEMPLATE_BODY

    subject = fill(subject_tpl, mapping).strip() or fill(DEFAULT_TEMPLATE_SUBJECT, mapping)
    html = _ensure_link_present(fill(body_tpl, mapping), mapping["leadership_link"])
    return subject, html


async def send_assignment_email(doc: dict, template: Optional[dict] = None) -> dict:
    """Mail one giver their link. Never raises — a failed send is recorded on the row so
    the dispatch screen can show it and offer a resend."""
    email = doc.get("giver_email")
    if not email:
        await mark_email_result(doc["_id"], EMAIL_FAILED, "No email address on file")
        return {"ok": False, "error": "No email address on file"}

    # Every send mints a fresh credential. The previous URL stops working, which is the
    # point: a single-use link that has been forwarded, or is sitting in an old mailbox,
    # dies the moment the real recipient is chased again. A row already submitted never
    # reaches here (dispatch_pending filters it out), so nothing completed is reopened.
    link = doc.get("_issued_token")
    link = public_link(link) if link else public_link(await rotate_token(doc))

    from app.services.notification_service import send_email_notification
    try:
        subject_line, html = await render_invite(doc, template, link)
        # send_email_notification NEVER raises — it returns False. The result must be
        # captured: marking EMAIL_SENT on a failed send both lies to the dispatch screen and
        # (since the cooldown is keyed on `sent_at`) locks the invitation out of retry for
        # RESEND_COOLDOWN_HOURS. A failed send must stay immediately retryable.
        delivered = await send_email_notification(
            email, subject_line, html,
            user_id=doc.get("giver_id"),
            slug="tpms_leadership_feedback_link",
        )
        if not delivered:
            await mark_email_result(doc["_id"], EMAIL_FAILED, "Delivery failed")
            logger.warning("Leadership link mail not delivered to %s", email)
            return {"ok": False, "error": "Delivery failed"}
        await mark_email_result(doc["_id"], EMAIL_SENT, None)
        return {"ok": True, "email": email}
    except Exception as e:
        logger.error("Leadership link mail failed for %s: %s", email, e)
        await mark_email_result(doc["_id"], EMAIL_FAILED, str(e))
        return {"ok": False, "error": str(e)}


async def dispatch_pending(company_id: str, cycle: str,
                           subject_id: Optional[str] = None,
                           skip_subjects: Optional[list] = None) -> dict:
    """Mail every not-yet-submitted link for a cycle (or one subject within it).

    Two things are skipped rather than mailed:
      • already-submitted rows — a re-dispatch must never nag someone who is done;
      • rows mailed successfully within RESEND_COOLDOWN_HOURS — so pressing the button
        twice in a minute does not send the same invitation twice. They are chased again
        on the next dispatch after the cooldown, which is what the button is for.

    Neither skip loses a link: `skipped_recent` is reported back so the caller can say
    exactly how many were held, and a single giver can always be re-mailed immediately
    through the explicit per-assignment resend.

    `skip_subjects` is the third exclusion: leaders whose panel does not yet meet the
    document's 2-per-relation composition. The caller decides who those are (see
    leadership_service.incomplete_panels) — this function only honours the list, so one
    unfinished panel never holds up the leaders who are ready.
    """
    query: dict = {
        "company_id": str(company_id),
        "cycle": str(cycle),
        "status": {"$ne": LINK_SUBMITTED},
    }
    if subject_id:
        query["subject_id"] = str(subject_id)
    elif skip_subjects:
        query["subject_id"] = {"$nin": [str(x) for x in skip_subjects]}

    rows = await get_collection(COLL_LS_ASSIGNMENTS).find(query).to_list(2000)
    now = datetime.now(timezone.utc)
    due = [r for r in rows if not in_resend_cooldown(r, now)]
    skipped_recent = len(rows) - len(due)

    # Fetch the template ONCE for the batch, then fill it separately for every recipient —
    # each mail carries only that giver's own token URL.
    template = await get_invite_template() if due else None
    sent = failed = 0
    for row in due:
        result = await send_assignment_email(row, template)
        if result.get("ok"):
            sent += 1
        else:
            failed += 1

    next_at = None
    if skipped_recent:
        held = [resend_blocked_until(r) for r in rows if in_resend_cooldown(r, now)]
        held = [h for h in held if h]
        next_at = min(held) if held else None

    logger.info(
        "Leadership dispatch [%s/%s]: %d sent, %d failed, %d held by the %dh cooldown "
        "(%d pending total), template=%s",
        company_id, cycle, sent, failed, skipped_recent, RESEND_COOLDOWN_HOURS,
        len(rows), "custom" if template else "default",
    )
    return {
        "sent": sent,
        "failed": failed,
        "total": len(rows),
        "skipped_recent": skipped_recent,
        "cooldown_hours": RESEND_COOLDOWN_HOURS,
        "next_resend_at": next_at,
        "template": "custom" if template else "default",
    }


async def assignments_for_subject(company_id: str, cycle: str, subject_id: str) -> List[dict]:
    return await get_collection(COLL_LS_ASSIGNMENTS).find({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id),
    }).sort("created_at", 1).to_list(200)


def panel_row(doc: dict, now: Optional[datetime] = None) -> dict:
    """One panel member as HR sees them. HR-ONLY — this carries giver identity and must
    never be returned by a leader-facing or manager-facing endpoint."""
    return {
        "id": str(doc.get("_id")),
        "giver_id": doc.get("giver_id"),
        "giver_name": doc.get("giver_name"),
        "giver_email": doc.get("giver_email"),
        "relation": doc.get("relation"),
        "relation_label": RELATION_LABELS.get(doc.get("relation") or "", doc.get("relation") or ""),
        "status": effective_status(doc, now),
        "email_status": doc.get("email_status"),
        "email_error": doc.get("email_error"),
        # No link. Only its hash is stored, so there is nothing to hand back — and a URL
        # on screen is a live credential that could be used to submit as this person.
        # HR who needs one presses Resend, which mints a fresh link and mails it to them.
        "legacy_token": bool(doc.get("token")),
        "sent_at": doc.get("sent_at"),
        "opened_at": doc.get("opened_at"),
        "submitted_at": doc.get("submitted_at"),
    }
