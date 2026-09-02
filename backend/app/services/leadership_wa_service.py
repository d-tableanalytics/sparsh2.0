"""
Leadership ▸ WhatsApp delivery and its own tracking ledger.

Leadership sends its invitations by WhatsApp and by nothing else. Email is not a fallback
here: a feedback invitation names the leader being rated, so an inbox that is shared,
forwarded or auto-archived is a disclosure risk this module does not accept.

WHY THIS DOES NOT REUSE TPMS TRACKING
-------------------------------------
TPMS keys its templates on (activity, event kind, side) and its delivery log on an activity
id. A Leadership invitation has no activity, no side and no event kind, so it would have to
either invent codes or widen a schema belonging to a different module. Separate collections
also keep a TPMS retention sweep away from records that carry panel identity.

ANONYMITY
---------
This ledger records DELIVERY OF AN INVITATION, never a response. It holds who was invited —
which is precisely what the assignment row already holds — and nothing about what anybody
answered. The two cannot be joined: responses stopped carrying `assignment_ref`, so there
is no path from an answer to a row in here. Reading it is gated on `_require_panel` (HR and
internal staff), the same gate as the panel itself, because knowing who was invited IS
panel information — a clientadmin must not see it.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from bson import ObjectId

from app.db.mongodb import get_collection
from app.models.leadership import (
    COLL_LS_ASSIGNMENTS, COLL_LS_WA_LOG, COLL_LS_WA_TEMPLATES,
    WA_DELIVERED, WA_FAILED, WA_PENDING, WA_READ, WA_SENT, WA_UNREACHABLE,
    WA_TPL_APPROVED, WA_TPL_DRAFT, WA_TPL_EDITABLE, WA_TPL_PENDING, WA_TPL_REJECTED,
    WA_VARIABLE_FIELDS, wa_is_forward,
)

logger = logging.getLogger(__name__)

# The values a template may use, and what fills each one. NAMED rather than numbered on
# purpose: a numbered template has to fix what {{1}} means for everybody, so the moment one
# variable becomes optional the positions shift underneath every other template. With names
# the body says {{company_name}}, any of them can be left out, and reordering the sentence
# cannot silently swap two values.
#
# `link` is MINTED PER INVITATION at send time — a fresh single-use token for one giver and
# one leader — so it can never be typed, pasted or stored. The admin writes {{link}}; the
# backend fills it.
SYSTEM_VARIABLES = {
    # Minted per invitation at send time. There is no field anywhere that accepts a link,
    # and a custom variable may not shadow this name.
    "feedback_link": "their unique feedback form link",
    "giver_name":    "the giver's name",
    # Named `leader_name` for the person writing the template, not `subject_name` as the
    # data model calls it — "subject" is our word for the rated person and means nothing to
    # anyone composing a message. The assignment field it reads is unchanged.
    #
    # Naming the leader in the message tells anyone glancing at that phone who is about to
    # be rated. Offered because it was asked for, but it is the one variable that costs
    # something to use.
    "leader_name":   "the leader they are rating",
    # Filled from the cycle's own collection window — HR's Open/Close dates when they set
    # them, the cycle's calendar months when they did not. The same window the form
    # enforces, so a message can never state a deadline the form disagrees with.
    "opens_at":      "when the feedback window opens",
    "closes_at":     "the last date to give feedback",
}

# Meta's own rule for a named parameter, mirrored so a bad name is refused while it can
# still be typed rather than after a review that takes hours.
VAR_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# What Meta sees in the sample it reviews. It requires an example for every variable, and
# there is exactly one sensible example for each of ours, so they are generated rather than
# asked for — and the sample link is obviously a sample.
SAMPLE_VALUES = {
    "giver_name": "Asha Rao",
    "feedback_link": "https://example.com/f/sample-link",
    "leader_name": "Rahul Mehta",
    "opens_at": "12 Sep 2026, 10:00 AM IST",
    "closes_at": "30 Sep 2026, 6:00 PM IST",
}


def _custom_map(variables) -> Dict[str, str]:
    """[{name, value}] → {name: value}, ignoring anything unnamed."""
    out: Dict[str, str] = {}
    for item in (variables or []):
        name = str((item or {}).get("name") or "").strip()
        if name:
            out[name] = str((item or {}).get("value") or "")
    return out


def validate_variables(body: str, variables) -> List[str]:
    """Everything that would make this template unusable, said before it is saved.

    Meta checks its own rules on review, hours later. These are the ones only WE can check:
    a variable in the body that nothing fills, a custom name shadowing a system one, and a
    declared variable with no value — each of which produces an APPROVED template that
    sends a blank where a word should be.
    """
    errors: List[str] = []
    custom = _custom_map(variables)

    for name in custom:
        if not VAR_NAME_RE.match(name):
            errors.append(f"'{name}' is not a usable variable name — use lowercase letters, "
                          "numbers and underscores, starting with a letter.")
        elif name in SYSTEM_VARIABLES:
            errors.append(f"'{name}' is a system variable and cannot be redefined.")
        elif not custom[name].strip():
            errors.append(f"Give {{{{{name}}}}} a value, or it will send as a blank.")

    used = set(re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", body or ""))
    unknown = sorted(used - set(SYSTEM_VARIABLES) - set(custom))
    if unknown:
        errors.append("Nothing fills " + ", ".join("{{%s}}" % u for u in unknown)
                      + " — add it as a variable, or remove it from the message.")

    unused = sorted(set(custom) - used)
    if unused:
        errors.append("Not used in the message: "
                      + ", ".join("{{%s}}" % u for u in unused) + ".")
    return errors


def authored_doc(name: str, language: str, body: str, variables=None) -> dict:
    """The full Meta template document, from the three things a user actually chooses.

    Everything else is fixed because a feedback invitation has one shape: UTILITY (it is a
    transactional notice, not marketing), numbered variables, no header, no footer, no
    buttons. Asking for those would be asking a question with only one right answer.
    """
    text = str(body or "").strip()
    custom = _custom_map(variables)
    used = body_variables(text, custom)
    return {
        # Stored so a send can fill them: a custom variable is the same words for every
        # recipient, which is exactly why the admin types it once here.
        "variables": [{"name": n, "value": v} for n, v in custom.items()],
        "name": str(name or "").strip().lower(),
        "language": str(language or "en").strip() or "en",
        "category": "UTILITY",
        "variable_style": "named",
        "header_format": "NONE",
        "body": text,
        # One example per variable ACTUALLY used, in the order it first appears — which is
        # exactly what Meta pairs with body_text_named_params.
        "body_examples": [SAMPLE_VALUES.get(v) or custom.get(v) or v for v in used],
        "footer": None,
        "buttons": [],
    }


def body_variables(body: str, custom=None) -> List[str]:
    """The fillable variables this body uses, in first-appearance order.

    Anything nothing can fill is dropped rather than guessed at — validate_variables is what
    reports it, so a typo is a message on screen rather than a template that ships and sends
    a blank.
    """
    known = set(SYSTEM_VARIABLES) | set(custom or {})
    seen, out = set(), []
    for token in re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", body or ""):
        if token in known and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────
# Template — one per company, and never shared
# ─────────────────────────────────────────────────────────────
async def suggest_template_name(company_id: str) -> str:
    """A Meta template name for this company that no other company is using.

    Built from the company's own name so it stays readable on the Meta dashboard, where
    every client's templates sit in one list and "leadership_invitation" tells nobody which
    company it belongs to. Falls back to the id when the name yields nothing usable — an
    ugly name is recoverable, a collision is not.
    """
    slug = ""
    try:
        oid = ObjectId(str(company_id))
    except Exception:
        oid = None
    if oid is not None:
        co = await get_collection("companies").find_one({"_id": oid}, {"name": 1})
        slug = re.sub(r"[^a-z0-9]+", "_", str((co or {}).get("name") or "").lower()).strip("_")
    # Meta allows lowercase, digits and underscores, starting with a letter.
    slug = re.sub(r"^[^a-z]+", "", slug)[:40].strip("_")
    base = f"{slug}_leadership_invite" if slug else "leadership_invite"

    col = get_collection(COLL_LS_WA_TEMPLATES)
    candidate, tail = base, str(company_id)[-6:].lower()
    # Two clients with the same trading name would otherwise collide on the slug alone.
    if await col.find_one({"meta_template_name": candidate,
                           "company_id": {"$ne": str(company_id)}}):
        candidate = f"{base}_{re.sub(r'[^a-z0-9]', '', tail) or 'x'}"
    return candidate[:60]


async def get_template(company_id: Optional[str] = None) -> dict:
    """This company's own template, or the empty built-in shape.

    There is deliberately no fall back to any other row. Every company writes its own
    invitation and gets it approved, so a company that has not written one yet has nothing
    to send — which the screen says plainly — rather than quietly borrowing wording, and a
    Meta template name, belonging to a different client.
    """
    col = get_collection(COLL_LS_WA_TEMPLATES)
    doc = await col.find_one({"company_id": str(company_id)}) if company_id else None

    return {
        "company_id": str(company_id) if company_id else None,
        "meta_template_name": (doc or {}).get("meta_template_name") or "",
        # Offered only when nothing is written yet, so it never overwrites a chosen name.
        "suggested_name": ("" if (doc or {}).get("meta_template_name")
                           else await suggest_template_name(str(company_id))
                           if company_id else ""),
        "language": (doc or {}).get("language") or "en",
        "category": (doc or {}).get("category") or "UTILITY",
        "system_variables": dict(SYSTEM_VARIABLES),
        "variables": (doc or {}).get("variables") or [],
        # Written on insert and reported for completeness. It stopped gating anything when
        # approval became the only gate — a template Meta has approved is one that sends.
        "active": bool((doc or {}).get("active", True)),
        "fields": list(WA_VARIABLE_FIELDS),
        "body": (doc or {}).get("body") or "",
        # Every row belongs to a company now, so having one IS being customised.
        "is_customised": bool(doc),
        # Where the template stands with Meta. DRAFT means it has never been submitted.
        "status": str((doc or {}).get("status") or WA_TPL_DRAFT).upper(),
        "meta_template_id": (doc or {}).get("meta_template_id"),
        "rejected_reason": (doc or {}).get("rejected_reason"),
        "last_submit_error": (doc or {}).get("last_submit_error"),
        "submitted_at": (doc or {}).get("submitted_at"),
        "synced_at": (doc or {}).get("synced_at"),
        # Editable status is not enough: a company that has never written a template
        # is DRAFT by default, and offering Submit there is a button whose only
        # outcome is the 400 that says "save the template first".
        "can_submit": bool((doc or {}).get("meta_template_name"))
                      and bool((doc or {}).get("body"))
                      and str((doc or {}).get("status") or WA_TPL_DRAFT).upper() in WA_TPL_EDITABLE,
        # Nothing can be sent until the client names a template they had approved AND the
        # wiring is switched on. Said plainly, because "no messages arrived" is otherwise a
        # long afternoon.
        # Ready to SEND means Meta has approved it and the wiring is switched on. A name
        # typed in but never approved is exactly the case that used to fail per recipient.
        # Approval IS the gate. A second on/off switch beside it was one more thing to
        # forget, and pressing Send is already the decision to send.
        "is_ready": str((doc or {}).get("status") or "").upper() == WA_TPL_APPROVED
                    and bool((doc or {}).get("meta_template_name")),
        "updated_at": (doc or {}).get("updated_at"),
        "updated_by": (doc or {}).get("updated_by"),
    }


async def save_authored_template(company_id: str, doc: dict, user: dict) -> dict:
    """Store the composer's full definition for one company, as a DRAFT.

    The authored fields (header, body, footer, buttons, variable style, examples) are kept
    exactly as the composer produced them, because that is what Meta validates and renders
    from. Leadership's own wiring — which data field fills each placeholder, and whether the
    template is switched on — lives alongside and is left untouched by an edit here.
    """
    col = get_collection(COLL_LS_WA_TEMPLATES)
    existing = await col.find_one({"company_id": str(company_id)}) or {}

    # A Meta template NAME is global to the WhatsApp Business Account rather than scoped to
    # a company, so two clients choosing the same obvious name are ONE template to Meta.
    # Refused here, while it can still be typed differently. Letting it through would fail
    # at submit with Meta's "Content in this language already exists", and — worse — a
    # later Refresh matches on name, so this company would adopt the other client's
    # approval and send its invitations with their wording.
    #
    # Checked on the name alone, not name + language: to Meta a name is one template that
    # may carry several language versions, so a shared name collides whatever the language.
    # The other company is never identified — that a name is taken is all one client may
    # learn about another.
    name = str(doc.get("name") or "").strip().lower()
    if name:
        clash = await col.find_one({"meta_template_name": name,
                                    "company_id": {"$ne": str(company_id)}})
        if clash:
            raise ValueError(
                f"The template name '{name}' is already used by another company. Meta "
                "template names are shared across the whole WhatsApp Business Account, so "
                "please choose a different one.")

    await col.update_one(
        {"company_id": str(company_id)},
        {"$set": {
            **doc,
            "company_id": str(company_id),
            "meta_template_name": doc.get("name") or "",
            # Any edit returns it to DRAFT: Meta reviews content, so a changed template is
            # no longer the one it approved.
            "status": WA_TPL_DRAFT,
            "rejected_reason": None,
            "last_submit_error": None,
            "updated_by": (user or {}).get("full_name") or (user or {}).get("email"),
            "updated_at": _now(),
        },
         "$setOnInsert": {"created_at": _now(), "active": True}},
        upsert=True,
    )
    saved = await get_template(company_id)
    # The composer identifies what it is editing by `_id`; one template per company means
    # that is simply this company's row.
    row = await col.find_one({"company_id": str(company_id)})
    saved["_id"] = str(row["_id"]) if row else None
    saved["meta_template_id"] = existing.get("meta_template_id")
    return saved


async def submit_template(company_id: str, user: dict) -> dict:
    """Send this company's template to Meta for review.

    Meta assigns it an id and it enters PENDING; approval usually lands within minutes to
    hours and is picked up by `sync_template_status`. A REJECTED template is EDITED rather
    than recreated — it still occupies its name on the WABA, and a second create for the
    same name comes back "Content in this language already exists".
    """
    from app.services.meta_whatsapp_service import (
        MetaTemplateError, create_message_template, edit_message_template, is_configured,
    )

    col = get_collection(COLL_LS_WA_TEMPLATES)
    doc = await col.find_one({"company_id": str(company_id)})
    if not doc:
        raise ValueError("Save the template before submitting it.")
    if not is_configured():
        raise ValueError("WhatsApp template management is not configured on this server.")

    status = str(doc.get("status") or WA_TPL_DRAFT).upper()
    if status not in WA_TPL_EDITABLE:
        raise ValueError(f"This template is already {status} at Meta — nothing to submit.")
    if not str(doc.get("meta_template_name") or "").strip():
        raise ValueError("Give the template a name before submitting it.")
    if not str(doc.get("body") or "").strip():
        raise ValueError("Write the message body before submitting it.")

    # The stored definition IS the Meta document — header, body, footer, buttons and
    # examples, exactly as the composer authored and validated them. Rebuilding a simpler
    # shape here would submit something different from what was reviewed on screen.
    meta_doc = {**doc, "name": doc.get("name") or doc.get("meta_template_name")}

    now = _now()
    existing_id = str(doc.get("meta_template_id") or "").strip()
    try:
        # The category is never sent on an edit. `authored_doc` fixes it at UTILITY for every
        # Leadership template, so there is nothing a re-submission could be changing it to —
        # and once Meta has approved a template it refuses the field outright, which is what
        # made "edit an approved invitation and send it back for review" impossible.
        result = (await edit_message_template(existing_id, meta_doc, include_category=False)
                  if existing_id else await create_message_template(meta_doc))
    except MetaTemplateError as e:
        # The template stays editable — record why so it shows on the row rather than only
        # in a toast that disappears.
        await col.update_one({"_id": doc["_id"]},
                             {"$set": {"last_submit_error": e.message, "updated_at": now}})
        raise ValueError(e.message)
    except Exception as e:                                        # pragma: no cover
        await col.update_one({"_id": doc["_id"]},
                             {"$set": {"last_submit_error": str(e), "updated_at": now}})
        raise ValueError(str(e))

    meta_status = str(result.get("status") or WA_TPL_PENDING).upper()
    await col.update_one({"_id": doc["_id"]}, {"$set": {
        "status": meta_status,
        "meta_template_id": str(result.get("id") or "") or None,
        "rejected_reason": None,
        "last_submit_error": None,
        "submitted_at": now, "synced_at": now, "updated_at": now,
        "submitted_by": (user or {}).get("full_name") or (user or {}).get("email"),
    }})
    logger.info("Leadership template '%s' submitted for company %s — %s",
                meta_doc["name"], company_id, meta_status)
    return await get_template(company_id)


async def sync_template_status(company_id: str) -> dict:
    """Ask Meta where this company's template stands, and mirror the verdict locally.

    Meta reviews asynchronously and does not call us back for templates, so the status only
    moves when somebody asks. Called from the screen's Refresh, which is why it is cheap and
    safe to repeat.
    """
    from app.services.meta_whatsapp_service import fetch_templates, is_configured

    col = get_collection(COLL_LS_WA_TEMPLATES)
    doc = await col.find_one({"company_id": str(company_id)})
    name = str((doc or {}).get("meta_template_name") or "").strip()
    if not doc or not name or not is_configured():
        return await get_template(company_id)

    try:
        rows = await fetch_templates()
    except Exception as e:                                        # pragma: no cover
        # Unreachable Meta is not a verdict. Leaving the stored status alone is what stops
        # a network blink reading as "your approved template disappeared".
        logger.warning("Leadership template sync failed for %s: %s", company_id, e)
        return await get_template(company_id)

    # Bind to the template this company actually submitted. Once Meta has issued an id,
    # that id IS the identity — matching on name alone would let one company pick up
    # another's verdict, because the name lives on the shared Business Account. The name
    # match survives only for a row that has never been submitted, and cross-company name
    # reuse is refused on save, so it can no longer resolve to somebody else's template.
    language = str(doc.get("language") or "en")
    tpl_id = str(doc.get("meta_template_id") or "").strip()
    match = next((r for r in (rows or []) if tpl_id and str(r.get("id") or "") == tpl_id), None)
    if match is None and not tpl_id:
        match = next((r for r in (rows or [])
                      if str(r.get("name") or "") == name
                      and str(r.get("language") or "") == language), None)
    if not match:
        return await get_template(company_id)

    status = str(match.get("status") or "").upper()
    updates = {"status": status, "synced_at": _now(), "updated_at": _now(),
               "meta_template_id": str(match.get("id") or "") or doc.get("meta_template_id")}
    updates["rejected_reason"] = (match.get("rejected_reason")
                                  if status == WA_TPL_REJECTED else None)
    await col.update_one({"_id": doc["_id"]}, {"$set": updates})
    return await get_template(company_id)


async def open_entry(assignment: dict, phone: str, status: str,
                     error: Optional[str] = None) -> str:
    """Record an attempt BEFORE it is made, and return the row id.

    Written first on purpose: a crash between "we decided to send" and "Meta answered"
    otherwise leaves no trace, and the invitation looks as though it was never attempted.
    """
    now = _now()
    doc = {
        "company_id": str(assignment.get("company_id")),
        "cycle": str(assignment.get("cycle")),
        "subject_id": str(assignment.get("subject_id")),
        "subject_name": assignment.get("subject_name"),
        "assignment_id": str(assignment.get("_id")),
        # Panel identity, which this collection is gated to HR for. It is NOT joinable to
        # any response — see the module docstring.
        "giver_id": str(assignment.get("giver_id") or ""),
        "giver_name": assignment.get("giver_name") or "",
        "phone": phone or "",
        "status": status,
        "error": error,
        "message_id": None,
        "attempts": 1,
        "created_at": now,
        "updated_at": now,
        f"{status}_at": now,
    }
    res = await get_collection(COLL_LS_WA_LOG).insert_one(doc)
    return str(res.inserted_id)


async def close_entry(entry_id: str, status: str, message_id: Optional[str] = None,
                      error: Optional[str] = None) -> None:
    """Stamp the outcome of the attempt this row was opened for."""
    updates = {"status": status, "updated_at": _now(), f"{status}_at": _now()}
    if message_id:
        updates["message_id"] = str(message_id)
    if error is not None:
        updates["error"] = error
    await get_collection(COLL_LS_WA_LOG).update_one(
        {"_id": ObjectId(entry_id)}, {"$set": updates})


async def apply_status(message_id: str, status: str,
                       error: Optional[str] = None) -> bool:
    """Move a logged message to `status`, if that is forward progress.

    Meta's delivery callbacks arrive out of order often enough that a late "sent" would
    otherwise drag a message that is already "read" backwards — `wa_is_forward` is what
    stops the ledger going into reverse. Returns whether anything changed.
    """
    if status not in (WA_SENT, WA_DELIVERED, WA_READ, WA_FAILED, WA_UNREACHABLE):
        return False
    col = get_collection(COLL_LS_WA_LOG)
    row = await col.find_one({"message_id": str(message_id)})
    if not row or not wa_is_forward(row.get("status") or WA_PENDING, status):
        return False

    updates = {"status": status, "updated_at": _now(), f"{status}_at": _now()}
    if error is not None:
        updates["error"] = error
    await col.update_one({"_id": row["_id"]}, {"$set": updates})
    return True


async def cycle_tracking(company_id: str, cycle: str) -> dict:
    """Every send attempt for a cycle, newest first, with the counts the screen leads on."""
    rows = await get_collection(COLL_LS_WA_LOG).find({
        "company_id": str(company_id), "cycle": str(cycle),
    }).sort("updated_at", -1).to_list(5000)

    counts = {s: 0 for s in
              (WA_PENDING, WA_SENT, WA_DELIVERED, WA_READ, WA_FAILED, WA_UNREACHABLE)}
    out = []
    for r in rows:
        status = r.get("status") or WA_PENDING
        counts[status] = counts.get(status, 0) + 1
        out.append({
            "id": str(r["_id"]),
            "subject_id": r.get("subject_id"),
            "subject_name": r.get("subject_name"),
            "giver_name": r.get("giver_name"),
            "phone": r.get("phone"),
            "status": status,
            "error": r.get("error"),
            "attempts": r.get("attempts", 1),
            "sent_at": r.get("sent_at"),
            "delivered_at": r.get("delivered_at"),
            "read_at": r.get("read_at"),
            "failed_at": r.get("failed_at") or r.get("unreachable_at"),
            "updated_at": r.get("updated_at"),
        })
    return {"company_id": str(company_id), "cycle": str(cycle),
            "counts": counts, "rows": out, "total": len(out)}


# ─────────────────────────────────────────────────────────────
# Sending
# ─────────────────────────────────────────────────────────────
async def _giver_phone(giver_id: str) -> str:
    """The giver's number, from whichever collection holds them."""
    if not giver_id:
        return ""
    try:
        oid = ObjectId(str(giver_id))
    except Exception:
        return ""
    for coll in ("staff", "learners"):
        doc = await get_collection(coll).find_one({"_id": oid})
        if doc:
            return str(doc.get("mobile") or doc.get("phone") or "").strip()
    return ""


def build_components(template: dict, context: Dict[str, str]) -> List[dict]:
    """The Cloud API `components` array for one send.

    Body parameters only. A survey invitation is a sentence and a link, and Leadership never
    had a way to author a header or button variable — the mapping existed but nothing could
    ever set it, so every send passed an empty list through two extra branches.

    An empty list is valid: a template with no variables at all needs no components.
    """
    custom = _custom_map((template or {}).get("variables"))
    used = body_variables((template or {}).get("body") or "", custom)
    if not used:
        return []
    # Meta addresses a NAMED template's parameters by `parameter_name`, so the order of this
    # list does not matter to it — but building it from the body means a variable the admin
    # removed simply stops being sent, with no positions to keep in step.
    return [{
        "type": "body",
        # A system variable comes from the invitation being sent; a custom one is the fixed
        # words the admin typed. Context wins, so a custom variable can never shadow the link.
        "parameters": [{"type": "text", "parameter_name": v,
                        "text": str(context.get(v, custom.get(v, "")))}
                       for v in used],
    }]




async def _post_template(phone: str, template_name: str, language: str,
                         components: List[dict], params: List[str]) -> dict:
    """Send one approved template and return {ok, message_id, error}.

    Leadership posts to Meta itself rather than calling notification_service.
    send_whatsapp_template, which returns a bare True/False. Delivered and Read arrive
    later as webhooks carrying only Meta's message id, so a sender that discards that id
    makes those two states permanently unreachable — the ledger could never move past
    `sent`. Widening the shared TPMS function's return type would change what every TPMS
    caller stores in its own log, so Leadership keeps its own sender, exactly as it keeps
    its own ledger.
    """
    import requests
    from app.services.notification_service import (
        _normalize_wa_phone, _wa_configured, _wa_endpoint, _wa_headers, log_notification,
    )

    if not _wa_configured():
        return {"ok": False, "error": "WhatsApp Cloud API credentials are not configured"}
    to = _normalize_wa_phone(phone)
    if not to:
        return {"ok": False, "error": f"'{phone}' is not a usable WhatsApp number"}

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language or "en"},
            "components": components,
        },
    }
    log_text = f"[leadership:{template_name}] " + " | ".join(str(p) for p in params)

    try:
        response = requests.post(_wa_endpoint(), json=payload,
                                 headers=_wa_headers(), timeout=20)
    except Exception as e:                                        # pragma: no cover
        logger.error("Leadership WhatsApp post failed for %s: %s", to, e)
        await log_notification(None, to, "whatsapp", "leadership_invite", log_text,
                               "failed", str(e))
        return {"ok": False, "error": str(e)}

    if response.status_code != 200:
        error = f"{response.status_code} - {response.text[:300]}"
        logger.error("Leadership WhatsApp refused for %s: %s", to, error)
        await log_notification(None, to, "whatsapp", "leadership_invite", log_text,
                               "failed", error)
        return {"ok": False, "error": error}

    # Meta answers {"messages":[{"id":"wamid...."}]}. That id is the only handle the later
    # delivered/read webhooks carry, so losing it here would strand the row at `sent`.
    try:
        message_id = (response.json().get("messages") or [{}])[0].get("id")
    except Exception:
        message_id = None
    await log_notification(None, to, "whatsapp", "leadership_invite", log_text, "sent")
    return {"ok": True, "message_id": message_id}


async def send_invitation(assignment: dict, link: str) -> dict:
    """Send one giver their form link over WhatsApp, and log the attempt either way.

    Every exit writes a ledger row, including the ones that never reach Meta. A giver with
    no number on file is `unreachable`, not a silent skip — HR can only fix what the screen
    admits is broken.
    """
    company_id = str(assignment.get("company_id"))
    template = await get_template(company_id)

    phone = await _giver_phone(assignment.get("giver_id"))
    if not phone:
        reason = "No mobile number on this person's record"
        entry = await open_entry(assignment, "", WA_UNREACHABLE, reason)
        return {"ok": False, "status": WA_UNREACHABLE, "entry_id": entry, "error": reason}

    if not template.get("is_ready"):
        reason = ("No approved WhatsApp template is configured for this company"
                  if not template.get("meta_template_name") else
                  "This company's WhatsApp template is switched off")
        entry = await open_entry(assignment, phone, WA_FAILED, reason)
        return {"ok": False, "status": WA_FAILED, "entry_id": entry, "error": reason}

    entry = await open_entry(assignment, phone, WA_PENDING)

    # The window this giver is actually held to. Read from the cycle at SEND time rather
    # than copied onto the assignment when it was created, so an Open or Close date HR
    # edits afterwards is the one the next message states.
    from app.services.leadership_link_service import format_window_dt, message_window
    from app.services.leadership_service import get_cycle
    cyc = await get_cycle(company_id, str(assignment.get("cycle") or "")) or {}
    opens, closes = message_window(cyc)

    context = {
        "giver_name": assignment.get("giver_name") or "there",
        "leader_name": assignment.get("subject_name") or "your colleague",
        "feedback_link": link,
        "opens_at": format_window_dt(opens),
        "closes_at": format_window_dt(closes),
    }

    components = build_components(template, context)
    # The log line shows what was substituted, taken from the components actually sent
    # rather than recomputed — a log that can disagree with the message is worse than none.
    logged = [p.get("text", "") for c in components for p in c.get("parameters", [])]
    result = await _post_template(
        phone,
        template["meta_template_name"],
        template.get("language") or "en",
        components,
        logged,
    )
    if result.get("ok"):
        await close_entry(entry, WA_SENT, message_id=result.get("message_id"))
        return {"ok": True, "status": WA_SENT, "entry_id": entry}

    reason = result.get("error") or "Delivery refused"
    await close_entry(entry, WA_FAILED, error=reason)
    return {"ok": False, "status": WA_FAILED, "entry_id": entry, "error": reason}


async def resend_invitation(assignment_id: str, link_builder) -> dict:
    """Re-send one invitation and count the attempt on its existing ledger rows."""
    doc = await get_collection(COLL_LS_ASSIGNMENTS).find_one({"_id": ObjectId(str(assignment_id))})
    if not doc:
        raise ValueError("This invitation no longer exists")
    await get_collection(COLL_LS_WA_LOG).update_many(
        {"assignment_id": str(assignment_id)}, {"$inc": {"attempts": 1}})
    return await send_invitation(doc, await link_builder(doc))
