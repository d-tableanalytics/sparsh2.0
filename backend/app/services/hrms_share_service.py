"""CV sharing — one candidate, many clients, one status each.

-- The problem this collection exists to solve -----------------------------------------------
A candidate has ONE `application_status`. That is Sparsh's pipeline stage and it is correct
as it stands: it says where WE are with somebody. It cannot also say where five different
clients are with them, and the requirement is explicitly that it must -- the same CV goes to
several clients and each runs their own process at their own pace.

So a share is a RECORD, not a field. `hrms_candidate_shares` holds one row per (candidate,
client) with its own status, its own history and its own audit trail. The two never compete:

    candidate.application_status  ->  where SPARSH is with this person
    share.status                  ->  where THIS CLIENT is with this person

-- The security boundary -------------------------------------------------------------------
This module is the first to be read by users who are not part of the tenant. A client user
must see the candidates shared with them and NOTHING else, and "nothing else" has to hold
against a crafted request, not merely against the UI.

Three rules make that true, and all three live here rather than in a route:

  1. A client's scope is resolved from their ENGAGEMENTS, never from the request. Nothing a
     caller sends can widen it -- `scope_client_ids` reads the engagement records and fails
     closed to [] on any error.
  2. A client-scoped read is filtered by that scope with `$in`, including when it is empty.
     An empty scope matches nothing; it never degrades to "no filter".
  3. A client never reads the candidate collection. They read the SHARE, which carries the
     snapshot Sparsh authorised. Adding a field to a candidate can therefore never
     retroactively expose it to a client who was sent a CV last month.

Rule 3 is the one worth defending: it would have been less code to project the candidate
document and hide some keys. But then every future field is exposed by default and safe only
if somebody remembers to add it to a deny-list, and that is the wrong way round for data
belonging to a person who did not consent to this client seeing it.

House convention: services validate, gate and audit; routes only check the capability.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_SHARE_CREATED, AUDIT_SHARE_CV_OPENED, AUDIT_SHARE_STATUS,
    AUDIT_SHARE_RECORDING_OPENED, AUDIT_SHARE_REPORT_OPENED, AUDIT_SHARE_WITHDRAWN,
    COLL_CANDIDATE_SHARES, COLL_CANDIDATES, COLL_REQUISITIONS, ENTITY_CANDIDATE,
    SHARE_CLIENT_SETTABLE, SHARE_TRANSITIONS, ShareStatus, share_can_transition,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import (
    hrms_role, is_client_scoped_user, scope_client_ids,
)

ENTITY_SHARE = "candidate share"

# A single share action may not fan out further than this. Not a performance limit -- it is
# what stops one mis-click mailing a person's CV to every client on the books.
MAX_CLIENTS_PER_SHARE = 25


def _clean(value, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _actor_name(actor: dict) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _oid(value: str, label: str) -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=422, detail=f"Invalid {label}.")


# ─────────────────────────────────────────────────────────────
# The authorised snapshot
# ─────────────────────────────────────────────────────────────
# What a client sees. An ALLOW-list, built field by field, for the reason in the module
# docstring: a deny-list exposes every field added later by default.
#
# `include_contact` is off unless Sparsh switches it on for that share, because a client
# holding the candidate's email can approach them directly.
def build_snapshot(candidate: dict, *, include_contact: bool = False) -> dict:
    """The candidate as this client is permitted to see them."""
    snapshot = {
        "candidate_name": candidate.get("candidate_name"),
        "total_experience": candidate.get("total_experience"),
        "qualification": candidate.get("qualification"),
        "current_company": candidate.get("current_company"),
        "current_location": candidate.get("current_location"),
        "notice_period": candidate.get("notice_period"),
        "expected_ctc": candidate.get("expected_ctc"),
        "cover_note": candidate.get("cover_note"),
        "linkedin": candidate.get("linkedin"),
        "portfolio": candidate.get("portfolio"),
        # The CV itself: the stored S3 key, never a URL. A signed URL expires, so persisting
        # one would leave a dead link on the share; the client asks for a fresh one and that
        # request is separately authorised.
        "resume_key": (candidate.get("resume") or {}).get("key"),
        "resume_name": (candidate.get("resume") or {}).get("name"),
    }
    # ── The interview record (brief §10) ──
    # Pointers only, on the same rule as the CV above: a key, never a URL. What a client may
    # DO with each differs and is enforced at the read routes, not here -- the report is
    # viewable, the recording is watchable, and neither is downloadable.
    #
    # These keys are also the one part of a snapshot that is refreshed after the fact, by
    # hrms_interview_media_service._refresh_shares. The reason is the real ordering of the
    # process: the CV goes out first and the interview happens afterwards, so a snapshot
    # frozen at share time would carry an interview record for almost nobody. That refresh
    # writes exactly these keys and nothing else -- see the note above it.
    from app.services.hrms_interview_media_service import interview_snapshot
    snapshot.update(interview_snapshot(candidate))
    if include_contact:
        snapshot["can_email"] = candidate.get("can_email")
        snapshot["can_contact"] = candidate.get("can_contact")
    # Deliberately absent whatever the flag says: `current_ctc` (what somebody is paid now
    # is leverage in a negotiation we are running), the internal `uk`, screening notes,
    # interview scores, references and every consent flag. None of it is the client's.
    return snapshot


def _out(doc: dict) -> dict:
    if not doc:
        return {}
    out = dict(doc)
    out.pop("_id", None)
    return out


def _client_view(doc: dict) -> dict:
    """A share as its CLIENT sees it: the snapshot, the status, and nothing internal.

    `uk` is stripped on purpose. It is Sparsh's candidate key, it appears in our URLs, and
    a client holding it could try it against endpoints their capability set does not cover.
    They address a share by `share_no`, which is theirs.
    """
    out = _out(doc)
    for internal in ("uk", "shared_by", "shared_by_name", "request_no", "history",
                     "company_id", "include_contact"):
        out.pop(internal, None)

    # The snapshot is copied before editing: it is the STORED document, and popping a key
    # out of it here would delete the CV pointer from the share itself on the next write.
    snapshot = dict(out.get("snapshot") or {})
    # A client needs to know whether there is a CV to download, not where it lives. The S3
    # key is our storage layout and their download goes through `resume_url_for_share`,
    # which re-checks that this candidate was shared with them.
    snapshot["has_cv"] = bool(snapshot.pop("resume_key", None))
    snapshot.pop("resume_name", None)

    # The interview record, reduced the same way and for the same reason. The client learns
    # THAT there is a report and a recording; every open goes back through a route that
    # re-proves this candidate was shared with them, and is audited.
    #
    # `interview_recording_url` is stripped even though it is not an S3 key: handing over a
    # permanent Zoom link would be handing over an artifact that outlives the share, survives
    # a withdrawal, and can be forwarded to anyone. They get a lease, on request, or nothing.
    snapshot["has_interview_report"] = bool(snapshot.pop("interview_report_key", None))
    snapshot.pop("interview_report_name", None)
    # Both popped unconditionally before the `or`: written as `pop(a) or pop(b)` the second
    # pop never runs when the first returns a key, and the raw recording URL stays in the
    # payload -- exactly the leak this line exists to prevent.
    rec_key = snapshot.pop("interview_recording_key", None)
    rec_url = snapshot.pop("interview_recording_url", None)
    snapshot["has_interview_recording"] = bool(rec_key or rec_url)
    out["snapshot"] = snapshot

    # What this client may do NEXT, computed from the graph rather than restated in JS.
    #
    # Brief §12 asks that the buttons depend on the candidate's current status -- "once a
    # candidate has already been rejected, the UI should not continue showing actions that
    # are no longer applicable". Sending the answer means the UI cannot drift from the
    # server's rules, and a status the client could not set never appears as a button that
    # 403s or 409s when pressed.
    #
    # The intersection is the whole rule: reachable from here (SHARE_TRANSITIONS) AND theirs
    # to set (SHARE_CLIENT_SETTABLE). Withdrawn and Hired are terminal for them either way.
    try:
        onward = SHARE_TRANSITIONS.get(ShareStatus(doc.get("status")), set())
    except ValueError:
        onward = set()
    out["allowed_statuses"] = sorted(s.value for s in onward & SHARE_CLIENT_SETTABLE)
    return out


# ─────────────────────────────────────────────────────────────
# Scoping — the security boundary
# ─────────────────────────────────────────────────────────────
async def _scope_filter(actor: dict, company_id: str) -> dict:
    """The Mongo filter fragment restricting this caller to what they may see.

    Returns `{}` for a Sparsh-side user (they see the tenant's shares) and a client filter
    for a client-scoped one. An empty scope produces `{"client_id": {"$in": []}}`, which
    matches nothing -- never `{}`, which would match everything. That distinction is the
    single most likely way this control gets broken later, so it is spelled out rather than
    left to a truthiness check.
    """
    if not is_client_scoped_user(actor):
        return {}
    allowed = await scope_client_ids(actor, company_id)
    return {"client_id": {"$in": list(allowed or [])}}


async def _require_visible(actor: dict, company_id: str, share_no: str) -> dict:
    """Load one share the caller is entitled to, or 404.

    404 rather than 403 when it exists but is out of scope: telling a client that a share
    exists but is not theirs confirms that Sparsh sent that candidate to a competitor, which
    is precisely the fact the scoping is there to keep.
    """
    query = {"share_no": share_no, "company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    doc = await get_collection(COLL_CANDIDATE_SHARES).find_one(query)
    if not doc:
        raise HTTPException(status_code=404, detail="Share not found.")
    return doc


# ─────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────
async def list_shares(actor: dict, company_id: str, *, uk: str = None,
                      client_id: str = None, status: str = None,
                      request_no: str = None, limit: int = 200) -> dict:
    """Shares this caller may see. The same function serves Sparsh's board and the client
    portal; what differs is the scope filter, not the code path."""
    query = {"company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))

    if uk:
        query["uk"] = uk
    if request_no:
        query["request_no"] = request_no
    if status:
        if status not in {s.value for s in ShareStatus}:
            raise HTTPException(
                status_code=422,
                detail=f"Status must be one of: {', '.join(s.value for s in ShareStatus)}.")
        query["status"] = status
    if client_id:
        # A requested client id NARROWS what the caller already had; it can never widen it.
        # For a client-scoped user the `$in` above still applies, so asking for somebody
        # else's client id returns nothing rather than somebody else's data.
        query["client_id"] = str(client_id) if "client_id" not in query else {
            "$in": [c for c in query["client_id"]["$in"] if c == str(client_id)]}

    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_CANDIDATE_SHARES).find(query).sort(
        "shared_at", -1).limit(limit).to_list(limit)

    client_side = is_client_scoped_user(actor)
    return {"shares": [(_client_view(r) if client_side else _out(r)) for r in rows],
            "total": len(rows), "client_view": client_side}


async def get_share(actor: dict, company_id: str, share_no: str) -> dict:
    doc = await _require_visible(actor, company_id, share_no)
    return _client_view(doc) if is_client_scoped_user(actor) else _out(doc)


async def shares_for_candidate(actor: dict, company_id: str, uk: str) -> dict:
    """Every client this candidate went to, with each client's own status.

    Sparsh-side only: the answer names other clients, which is exactly what a client user
    may not see. A client asking this gets their own single row through `list_shares`.
    """
    if is_client_scoped_user(actor):
        raise HTTPException(
            status_code=403,
            detail="You can see the candidates shared with you, not where else they went.")
    rows = await get_collection(COLL_CANDIDATE_SHARES).find(
        {"company_id": str(company_id), "uk": uk}).sort("shared_at", -1).to_list(200)
    return {"uk": uk, "shares": [_out(r) for r in rows], "total": len(rows)}


# ─────────────────────────────────────────────────────────────
# Sharing
# ─────────────────────────────────────────────────────────────
async def share_candidate(actor: dict, company_id: str, payload: dict) -> dict:
    """Share one candidate with one or more clients.

    Partial success by design, in the same shape the bulk screener uses: one client failing
    (already has this CV, is not an active client) must not lose the other four. The caller
    gets back what happened to each.
    """
    uk = _clean(payload.get("uk"), 40)
    if not uk:
        raise HTTPException(status_code=422, detail="Select a candidate.")

    client_ids = payload.get("client_ids") or []
    if not isinstance(client_ids, list) or not client_ids:
        raise HTTPException(status_code=422, detail="Name at least one client.")
    # De-duplicated first: the same client twice in one request is a UI slip, not two shares.
    client_ids = list(dict.fromkeys(str(c).strip() for c in client_ids if str(c).strip()))
    if len(client_ids) > MAX_CLIENTS_PER_SHARE:
        raise HTTPException(
            status_code=422,
            detail=f"A CV can be sent to at most {MAX_CLIENTS_PER_SHARE} clients at once.")

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    if not (candidate.get("resume") or {}).get("key"):
        # The whole act is "send this client the CV". Without one there is nothing to send,
        # and a share that carries no document is a promise the client cannot act on.
        raise HTTPException(
            status_code=409,
            detail=(f"{candidate.get('candidate_name')} has no CV on file. Upload one "
                    f"before sharing them with a client."))

    include_contact = bool(payload.get("include_contact"))
    note = _clean(payload.get("note"), 2000)
    request_no = _clean(payload.get("request_no"), 40) or candidate.get("request_no")
    snapshot = build_snapshot(candidate, include_contact=include_contact)
    now = datetime.now(timezone.utc)
    actor_id = str((actor or {}).get("_id") or "")

    companies = get_collection("companies")
    shares = get_collection(COLL_CANDIDATE_SHARES)
    created, skipped = [], []

    for client_id in client_ids:
        client = await companies.find_one({"_id": _oid(client_id, "client")})
        if not client:
            skipped.append({"client_id": client_id, "reason": "No such client."})
            continue

        existing = await shares.find_one(
            {"company_id": str(company_id), "uk": uk, "client_id": client_id})
        if existing and existing.get("status") != ShareStatus.WITHDRAWN.value:
            skipped.append({"client_id": client_id,
                            "client_name": client.get("name"),
                            "reason": f"Already shared ({existing.get('status')})."})
            continue

        if existing:
            # Re-sharing after a withdrawal REUSES the row, so the unique index holds and
            # the client keeps one record with its whole history rather than gaining a
            # second that disagrees with the first.
            await shares.update_one(
                {"_id": existing["_id"]},
                {"$set": {"status": ShareStatus.CV_SHARED.value, "snapshot": snapshot,
                          "include_contact": include_contact, "note": note,
                          "shared_at": now, "shared_by": actor_id,
                          "shared_by_name": _actor_name(actor), "responded_at": None,
                          "updated_at": now},
                 "$push": {"history": {"status": ShareStatus.CV_SHARED.value,
                                       "at": now, "by": actor_id,
                                       "by_name": _actor_name(actor),
                                       "remarks": "Re-shared after withdrawal."}}})
            created.append({"share_no": existing["share_no"], "client_id": client_id,
                            "client_name": client.get("name"), "reshared": True})
            await audit(actor, AUDIT_SHARE_CREATED, ENTITY_SHARE, existing["share_no"],
                        f"{candidate.get('candidate_name')} re-shared with "
                        f"{client.get('name')}", company_id)
            continue

        share_no = await next_business_id("share", str(company_id), now.year)
        doc = {
            "share_no": share_no,
            "company_id": str(company_id),
            "uk": uk,
            "candidate_name": candidate.get("candidate_name"),
            "client_id": client_id,
            "client_name": client.get("name"),
            "request_no": request_no,
            "status": ShareStatus.CV_SHARED.value,
            "snapshot": snapshot,
            "include_contact": include_contact,
            "note": note,
            "shared_at": now,
            "shared_by": actor_id,
            "shared_by_name": _actor_name(actor),
            "responded_at": None,
            "history": [{"status": ShareStatus.CV_SHARED.value, "at": now,
                         "by": actor_id, "by_name": _actor_name(actor), "remarks": note}],
            "created_at": now,
            "updated_at": now,
        }
        try:
            await shares.insert_one(dict(doc))
        except DuplicateKeyError:
            # The unique index is the authority, not the read above: two operators sharing
            # the same CV with the same client at once both find nothing and both insert.
            skipped.append({"client_id": client_id, "client_name": client.get("name"),
                            "reason": "Already shared."})
            continue

        created.append({"share_no": share_no, "client_id": client_id,
                        "client_name": client.get("name"), "reshared": False})
        await audit(actor, AUDIT_SHARE_CREATED, ENTITY_SHARE, share_no,
                    f"{candidate.get('candidate_name')} shared with {client.get('name')}",
                    company_id)

    if created:
        # One row against the CANDIDATE too, so their journey shows the share without
        # having to join the two collections.
        await audit(actor, AUDIT_SHARE_CREATED, ENTITY_CANDIDATE, uk,
                    f"shared with {len(created)} client(s)", company_id)
        await _notify_clients(company_id, created, candidate)

    return {"ok": True, "shared": created, "skipped": skipped,
            "count": len(created)}


async def _notify_clients(company_id: str, created: list, candidate: dict) -> None:
    """Tell each client's users that a CV is waiting.

    Late import and best-effort, the pattern every other service here follows: a
    notification that cannot be sent must never lose a share that was already written.
    """
    try:
        from app.models.hrms import COLL_CLIENT_ENGAGEMENTS, ENGAGEMENT_GRANTS_SCOPE
        from app.services.hrms_notify_service import notify_users
        for item in created:
            rows = await get_collection(COLL_CLIENT_ENGAGEMENTS).find(
                {"company_id": str(company_id), "client_id": item["client_id"],
                 "status": {"$in": sorted(ENGAGEMENT_GRANTS_SCOPE)}},
                {"member_user_ids": 1}).to_list(50)
            members = sorted({m for r in rows for m in (r.get("member_user_ids") or [])})
            if members:
                await notify_users(
                    members, "A candidate has been shared with you",
                    f"{candidate.get('candidate_name')} is ready for your review.",
                    link="/hrms/shared-candidates", email=True)
    except Exception as e:
        print(f"[WARN] HRMS share notification failed: {e}")


# ─────────────────────────────────────────────────────────────
# Status
# ─────────────────────────────────────────────────────────────
async def set_share_status(actor: dict, company_id: str, share_no: str,
                           payload: dict) -> dict:
    """Move one share along its own lifecycle.

    Two callers, one path. A client records their verdict; Sparsh records what a client told
    them by phone, and additionally the commercial outcomes a client may not assert. The
    difference is enforced by SHARE_CLIENT_SETTABLE, not by two functions that could drift.
    """
    current = await _require_visible(actor, company_id, share_no)

    raw = getattr(payload.get("status"), "value", payload.get("status"))
    try:
        target = ShareStatus(raw)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Status must be one of: {', '.join(s.value for s in ShareStatus)}.")

    # Permission BEFORE reachability. When a client asks for a status that is both
    # unreachable and not theirs to set, "that one is ours to record" is the useful answer;
    # "you cannot get there from here" would send them looking for a route that does not
    # exist for them at any point.
    if is_client_scoped_user(actor) and target not in SHARE_CLIENT_SETTABLE:
        raise HTTPException(
            status_code=403,
            detail=(f'"{target.value}" is recorded by the recruitment team, not by you. '
                    f"Tell us and we will update it."))

    if current["status"] == target.value:
        raise HTTPException(status_code=409,
                            detail=f"This share is already \"{target.value}\".")
    if not share_can_transition(current["status"], target):
        onward = sorted(s.value for s in
                        SHARE_TRANSITIONS[ShareStatus(current["status"])])
        raise HTTPException(
            status_code=409,
            detail=(f'A share cannot move from "{current["status"]}" to "{target.value}". '
                    + (f'From here it can go to: {", ".join(onward)}.' if onward
                       else "This is a final state.")))

    now = datetime.now(timezone.utc)
    remarks = _clean(payload.get("remarks"), 2000)
    entry = {"status": target.value, "at": now, "by": str((actor or {}).get("_id") or ""),
             "by_name": _actor_name(actor), "remarks": remarks}

    # Conditioned on the status it was read at, so two people moving one share at once
    # cannot both win and leave a history that records an impossible order.
    result = await get_collection(COLL_CANDIDATE_SHARES).update_one(
        {"share_no": share_no, "company_id": str(company_id),
         "status": current["status"]},
        {"$set": {"status": target.value, "responded_at": now, "updated_at": now},
         "$push": {"history": entry}})
    if not (result.modified_count or 0):
        raise HTTPException(
            status_code=409,
            detail="Somebody else updated this share. Reload and try again.")

    await audit(actor, AUDIT_SHARE_STATUS, ENTITY_SHARE, share_no,
                f'{current["status"]} -> {target.value}'
                + (f" ({remarks})" if remarks else ""), company_id)
    await _notify_sparsh_of_verdict(actor, company_id, current, target, remarks)

    fresh = await get_collection(COLL_CANDIDATE_SHARES).find_one(
        {"share_no": share_no, "company_id": str(company_id)})
    return _client_view(fresh) if is_client_scoped_user(actor) else _out(fresh)


async def _notify_sparsh_of_verdict(actor: dict, company_id: str, share: dict,
                                    target: ShareStatus, remarks: str) -> None:
    """A client's verdict is only useful if the recruiter hears about it."""
    if not is_client_scoped_user(actor):
        return                                   # Sparsh recorded it; they already know
    try:
        from app.services.hrms_notify_service import notify_hrms_role
        await notify_hrms_role(
            company_id, ["HR"],
            f"{share.get('client_name')}: {share.get('candidate_name')} is "
            f"{target.value}",
            (remarks or f"The client moved this candidate to {target.value}."),
            kind="info", link="/hrms/cv-sharing", email=True)
    except Exception as e:
        print(f"[WARN] HRMS verdict notification failed: {e}")


async def withdraw_share(actor: dict, company_id: str, share_no: str,
                         payload: dict = None) -> dict:
    """Pull a CV back from a client. Sparsh only -- a client declines, they do not withdraw.

    The row is kept, not deleted: that this client saw this CV is a fact about a person's
    data, and the audit trail requirement covers client ACCESS, not only client decisions.
    """
    if is_client_scoped_user(actor):
        raise HTTPException(
            status_code=403,
            detail="Only the recruitment team can withdraw a CV. Reject it instead.")
    current = await _require_visible(actor, company_id, share_no)
    if current["status"] == ShareStatus.WITHDRAWN.value:
        raise HTTPException(status_code=409, detail="This CV was already withdrawn.")
    if current["status"] == ShareStatus.HIRED.value:
        raise HTTPException(
            status_code=409,
            detail="This candidate was hired through this client. A completed placement "
                   "cannot be withdrawn.")

    now = datetime.now(timezone.utc)
    reason = _clean((payload or {}).get("remarks"), 2000)
    await get_collection(COLL_CANDIDATE_SHARES).update_one(
        {"share_no": share_no, "company_id": str(company_id)},
        {"$set": {"status": ShareStatus.WITHDRAWN.value, "updated_at": now},
         "$push": {"history": {"status": ShareStatus.WITHDRAWN.value, "at": now,
                               "by": str((actor or {}).get("_id") or ""),
                               "by_name": _actor_name(actor), "remarks": reason}}})
    await audit(actor, AUDIT_SHARE_WITHDRAWN, ENTITY_SHARE, share_no,
                f"withdrawn from {current.get('client_name')}"
                + (f": {reason}" if reason else ""), company_id)
    return await get_share(actor, company_id, share_no)


async def resume_url_for_share(actor: dict, company_id: str, share_no: str) -> dict:
    """A short-lived link to the CV on one share.

    Minted per request and audited, because this is the moment a client actually READS
    somebody's personal data and requirement 8 asks for a trail of client access. The
    document service's own URL route cannot serve this: it is keyed on a document number a
    client has no capability to read.
    """
    share = await _require_visible(actor, company_id, share_no)
    key = (share.get("snapshot") or {}).get("resume_key")
    if not key:
        raise HTTPException(status_code=404, detail="No CV is attached to this share.")
    if share.get("status") == ShareStatus.WITHDRAWN.value:
        raise HTTPException(
            status_code=410, detail="This CV has been withdrawn and is no longer available.")

    # The name the file arrives under. Built from the CANDIDATE, not from the stored
    # object: the S3 key carries an internal prefix (`cv_CAN-001_...`) that means nothing to
    # a client and quietly discloses our candidate numbering. A client who downloads four
    # CVs should end up with four recognisable files.
    stored_name = (share.get("snapshot") or {}).get("resume_name") or "cv.pdf"
    extension = ("." + stored_name.rsplit(".", 1)[-1]) if "." in stored_name else ".pdf"
    person = (share.get("candidate_name") or "candidate").strip()
    # Anything a filesystem or a Content-Disposition header would argue with.
    safe_person = "".join(c for c in person if c.isalnum() or c in " -_").strip() or "candidate"
    download_name = f"{safe_person} - CV{extension}"

    from app.services.s3_service import get_signed_url
    url = get_signed_url(key, expires_in=300, download_as=download_name)
    if not url:
        raise HTTPException(
            status_code=503, detail="The CV could not be opened right now. Please try again.")
    await audit(actor, AUDIT_SHARE_CV_OPENED, ENTITY_SHARE, share_no,
                f"{share.get('client_name')} downloaded {share.get('candidate_name')}'s CV",
                company_id)
    return {"url": url, "expires_in": 300, "name": download_name}


# ─────────────────────────────────────────────────────────────
# The interview record, as a client reads it
# ─────────────────────────────────────────────────────────────
# Three routes, three different permissions, and the difference between them is the point of
# brief §10:
#
#     resume_url_for_share      -> DOWNLOAD. `download_as` set, so it saves to disk.
#     report_url_for_share      -> VIEW.     No disposition; the browser renders it.
#     recording_ref_for_share   -> WATCH.    No disposition, short lease, no download in UI.
#
# Each re-proves the share through `_require_visible` rather than trusting that the caller
# got a share number from a list we gave them. A share number in a URL is not authorisation.
async def _require_openable(actor: dict, company_id: str, share_no: str) -> dict:
    """One visible share that is still live.

    A withdrawn share is refused with 410 rather than 404: the client saw this person, the
    row still exists, and "gone" is both the truthful answer and a different thing from "no
    such candidate".
    """
    share = await _require_visible(actor, company_id, share_no)
    if share.get("status") == ShareStatus.WITHDRAWN.value:
        raise HTTPException(
            status_code=410,
            detail="This candidate has been withdrawn and is no longer available.")
    return share


async def report_url_for_share(actor: dict, company_id: str, share_no: str) -> dict:
    """A short-lived link to the interview report, to READ.

    Deliberately without `download_as`. A client asked to review somebody, not to build a
    file of them -- the CV is the one artifact they were promised a copy of.
    """
    share = await _require_openable(actor, company_id, share_no)
    key = (share.get("snapshot") or {}).get("interview_report_key")
    if not key:
        raise HTTPException(
            status_code=404,
            detail="No interview report has been shared for this candidate yet.")

    from app.services.hrms_interview_media_service import MEDIA_LEASE_SECONDS
    from app.services.s3_service import get_signed_url
    url = get_signed_url(key, expires_in=MEDIA_LEASE_SECONDS)
    if not url:
        raise HTTPException(
            status_code=503,
            detail="The interview report could not be opened right now. Please try again.")

    await audit(actor, AUDIT_SHARE_REPORT_OPENED, ENTITY_SHARE, share_no,
                f"{share.get('client_name')} opened {share.get('candidate_name')}'s "
                f"interview report", company_id)
    return {"url": url, "expires_in": MEDIA_LEASE_SECONDS, "downloadable": False,
            "summary": (share.get("snapshot") or {}).get("interview_report_summary")}


async def recording_ref_for_share(actor: dict, company_id: str, share_no: str) -> dict:
    """A reference the client's player can WATCH the interview through.

    Two shapes, because a recording arrives two ways:

        source "file" -> a leased S3 URL the <video> element streams from.
        source "link" -> the meeting platform's own link, opened in a new tab.

    On the honest limit of "no download": see the module docstring of
    hrms_interview_media_service. This route sets no attachment disposition and the client UI
    offers no save control, and a `link` recording is governed by the platform that hosts it
    rather than by us. `downloadable: False` tells the UI what to render; it is not a claim
    that the bytes are unreachable to somebody determined to keep them.
    """
    share = await _require_openable(actor, company_id, share_no)
    snapshot = share.get("snapshot") or {}
    key = snapshot.get("interview_recording_key")
    link = snapshot.get("interview_recording_url")
    if not key and not link:
        raise HTTPException(
            status_code=404,
            detail="No interview recording has been shared for this candidate yet.")

    from app.services.hrms_interview_media_service import MEDIA_LEASE_SECONDS
    common = {
        "downloadable": False,
        "title": snapshot.get("interview_recording_title"),
        "duration_min": snapshot.get("interview_recording_duration_min"),
    }

    # Audited BEFORE the URL is minted, so a trail exists even if the storage layer then
    # fails. The question the audit answers is "who asked to watch this", and they did.
    await audit(actor, AUDIT_SHARE_RECORDING_OPENED, ENTITY_SHARE, share_no,
                f"{share.get('client_name')} watched {share.get('candidate_name')}'s "
                f"interview recording", company_id)

    if link:
        return {**common, "source": "link", "url": link, "expires_in": None}

    from app.services.s3_service import get_signed_url
    url = get_signed_url(key, expires_in=MEDIA_LEASE_SECONDS)
    if not url:
        raise HTTPException(
            status_code=503,
            detail="The recording could not be opened right now. Please try again.")
    return {**common, "source": "file", "url": url, "expires_in": MEDIA_LEASE_SECONDS}


async def add_share_remark(actor: dict, company_id: str, share_no: str,
                           payload: dict) -> dict:
    """Record a remark against a share WITHOUT moving its status.

    Two things in the brief need this and neither is a verdict (§12): "Add Remark", and
    "Send Back to Sparsh" -- a client saying "we like them but need X clarified", which is
    not an approval, not a rejection, and not a reason to invent a status nobody else in the
    lifecycle graph understands.

    `needs_attention` is what separates the two. A plain remark is filed; a send-back is
    filed AND notifies the recruiter, because the client is waiting on an answer. The stored
    entry is the same shape `set_share_status` pushes, so one history renders both.
    """
    share = await _require_openable(actor, company_id, share_no)

    remarks = _clean(payload.get("remarks"), 2000)
    if not remarks:
        raise HTTPException(status_code=422, detail="Write a remark before sending it.")
    needs_attention = bool(payload.get("needs_attention"))

    now = datetime.now(timezone.utc)
    entry = {
        # The status is unchanged, and the entry says so rather than omitting it: a history
        # row with no status would render as a gap in every timeline that reads this list.
        "status": share.get("status"),
        "at": now,
        "by": str((actor or {}).get("_id") or ""),
        "by_name": _actor_name(actor),
        "remarks": remarks,
        "kind": "sent_back" if needs_attention else "remark",
    }
    await get_collection(COLL_CANDIDATE_SHARES).update_one(
        {"share_no": share_no, "company_id": str(company_id)},
        {"$set": {"updated_at": now}, "$push": {"history": entry}})

    await audit(actor, AUDIT_SHARE_STATUS, ENTITY_SHARE, share_no,
                f"{'sent back' if needs_attention else 'remark'}: {remarks}", company_id)

    if needs_attention and is_client_scoped_user(actor):
        try:
            from app.services.hrms_notify_service import notify_hrms_role
            await notify_hrms_role(
                company_id, ["HR"],
                f"{share.get('client_name')} sent back {share.get('candidate_name')}",
                remarks, kind="warning", link="/hrms/cv-sharing", email=True)
        except Exception as e:
            # Best effort, the pattern every notification here follows: a message that could
            # not be sent must never lose a remark that was already written.
            print(f"[WARN] HRMS send-back notification failed: {e}")

    fresh = await get_collection(COLL_CANDIDATE_SHARES).find_one(
        {"share_no": share_no, "company_id": str(company_id)})
    return _client_view(fresh) if is_client_scoped_user(actor) else _out(fresh)
