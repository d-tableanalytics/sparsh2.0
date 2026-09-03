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
    AUDIT_SHARE_WITHDRAWN,
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
    out["snapshot"] = snapshot
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
