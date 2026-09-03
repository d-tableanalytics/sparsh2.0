"""HRMS > the internal shortlisting committee (internal recruitment track, SOP §5).

"HR and the Department Head shall jointly finalise the shortlist before the final
interview."

-- Why this needed a record ----------------------------------------------------------------
Until this phase the act existed and the decision did not. HR shortlisted candidates, the HOD
was consulted somewhere off-system, and the pipeline moved. Nothing recorded WHO agreed, on
WHICH candidates, or on what evidence -- so "we jointly finalised the shortlist" was a claim
the module could neither support nor contradict.

That matters most in the case the SOP is actually worried about: a candidate progressed to a
final interview that the department head never agreed to see. With a record, that is a gap
somebody can point at. Without one it is an argument about memory.

-- Two ROLES and two PEOPLE ----------------------------------------------------------------
SOP §5 requires HR and the Department Head. Both must be covered, and by two DIFFERENT
people, for exactly the reason hrms_scorecard_service refuses a managerial scorecard signed
twice by one person: an MD holds every capability on this track, so without the second check
one person could convene, agree with themselves and call it a committee.

Finance is deliberately absent from the capability grant. Finance approves what a role costs;
it never decides who fills it, and this record is entirely about who fills it.

-- What it gates, and how narrowly ---------------------------------------------------------
On the internal track, `Selected` requires a FINALISED committee record naming that
candidate. The gate is deliberately at `Selected` rather than at the final interview: booking
a conversation is cheap and reversible, and blocking it would push scheduling off-system,
which is how a control stops being one. Selection is the commitment.

Bypassed only by an approved `Relaxed Scorecard` exception -- there is no override flag, the
same rule every other gate on this track follows.

-- Internal track only ---------------------------------------------------------------------
A client-track requisition never has one. The client owns the shortlist there, and their
verdict is already recorded as a client-share response.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_SHORTLIST_CONVENED, AUDIT_SHORTLIST_DECIDED, COLL_CANDIDATES,
    COLL_POSITION_SCORECARDS, COLL_REQUISITIONS, COLL_SHORTLIST_REVIEWS,
    ENTITY_SHORTLIST, RETENTION_YEARS, SHORTLIST_COMMITTEE_ROLES, SHORTLIST_MIN_MEMBERS,
    CommitteeDecision, RequisitionTrack, ShortlistOutcome, score_band,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import hrms_role
from app.utils.hrms_public_guard import clean_text

MAX_COMMITTEE_MEMBERS = 10
MAX_SHORTLIST_CANDIDATES = 100


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_name(actor: dict) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _add_years(iso_date: str, years: int) -> str:
    """`iso_date` plus N years, clamped for 29 February. Pure."""
    try:
        y, m, d = (int(p) for p in str(iso_date)[:10].split("-"))
    except (ValueError, TypeError):
        return iso_date
    if m == 2 and d == 29:
        d = 28
    return f"{y + years:04d}-{m:02d}-{d:02d}"


async def _require_internal_requisition(company_id: str, request_no: str) -> dict:
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if not req:
        raise HTTPException(
            status_code=422, detail="That requisition does not exist for this company.")
    track = req.get("requisition_track") or RequisitionTrack.CLIENT.value
    if track != RequisitionTrack.INTERNAL.value:
        raise HTTPException(
            status_code=409,
            detail=(f"{request_no} is a client requisition. The shortlisting committee is a "
                    f"Sparsh Magic control -- on the client track the client decides who "
                    f"they want to see, and their verdict is recorded against the CV."))
    return req


# -------------------------------------------------------------
# Committee composition
# -------------------------------------------------------------
async def _resolve_members(company_id: str, members) -> list:
    """Resolve committee entries to users of this company, with their roles stamped.

    The role is resolved SERVER-SIDE from the user record. A caller cannot declare that
    somebody "counts as HR" any more than they can declare their own capabilities.
    """
    if not isinstance(members, list):
        raise HTTPException(status_code=422, detail="Name the committee members.")
    if len(members) > MAX_COMMITTEE_MEMBERS:
        raise HTTPException(
            status_code=422,
            detail=f"A committee of more than {MAX_COMMITTEE_MEMBERS} is a meeting, not a "
                   f"committee.")

    out, seen = [], set()
    for entry in members:
        entry = dict(entry or {})
        user_id = str(entry.get("user_id") or "").strip()
        if not user_id:
            raise HTTPException(status_code=422, detail="Every member needs a user.")
        if user_id in seen:
            raise HTTPException(
                status_code=422,
                detail="The same person is listed twice on this committee.")
        seen.add(user_id)
        try:
            oid = ObjectId(user_id)
        except (InvalidId, TypeError):
            raise HTTPException(status_code=422, detail="Invalid committee member.")
        person = await get_collection("learners").find_one(
            {"_id": oid, "company_id": str(company_id)})
        if not person:
            raise HTTPException(
                status_code=422,
                detail="Every committee member must be a user of this company.")

        raw_decision = getattr(entry.get("decision"), "value", entry.get("decision"))
        try:
            decision = CommitteeDecision(raw_decision or CommitteeDecision.AGREE.value)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=(f"A member's decision must be one of: "
                        f"{', '.join(d.value for d in CommitteeDecision)}."))

        role = hrms_role(person)
        out.append({
            "user_id": user_id,
            "name": (person.get("full_name") or person.get("email") or "Unknown"),
            # Stamped as it stood. If somebody's governance role changes next quarter the
            # record still says who sat AS WHAT, which is the question an audit asks.
            "role": role.value if role else None,
            "decision": decision.value,
            "remarks": clean_text(entry.get("remarks"), limit=2000),
            # ── SOP §11 conflict of interest ──
            "coi_declared": bool(entry.get("coi_declared")),
            "coi_relationship": clean_text(entry.get("coi_relationship"), limit=200),
            "recused": bool(entry.get("recused")),
        })
    return out


def committee_state(members: list) -> dict:
    """Who is covered, who is missing, and whether that is a committee at all.

    A RECUSED member counts as absent, exactly as they do on an interview panel: somebody
    who stood down over a conflict cannot also be the reason the committee is quorate.

    Returned rather than raised, so a screen can show "still needed: manager" while the
    record is being assembled and only the finalisation is refused.
    """
    active = [m for m in (members or []) if not m.get("recused")]
    covered = {m.get("role") for m in active if m.get("role")}
    people = {str(m.get("user_id")) for m in active if m.get("user_id")}

    outstanding = [r.value for r in SHORTLIST_COMMITTEE_ROLES if r.value not in covered]
    complete = not outstanding and len(people) >= SHORTLIST_MIN_MEMBERS
    if not outstanding and len(people) < SHORTLIST_MIN_MEMBERS:
        outstanding = ["a second, independent member"]
    return {
        "required_roles": [r.value for r in SHORTLIST_COMMITTEE_ROLES],
        "covered_roles": sorted(r for r in covered if r),
        "outstanding_roles": outstanding,
        "member_count": len(people),
        "objections": [m.get("name") for m in active
                       if m.get("decision") == CommitteeDecision.OBJECT.value],
        "complete": complete,
    }


def assert_committee_complete(members: list) -> None:
    """Refuse to FINALISE a shortlist the SOP's committee has not actually formed."""
    state = committee_state(members)
    if state["complete"]:
        return
    raise HTTPException(
        status_code=422,
        detail=(f"A shortlisting committee needs "
                f"{', '.join(state['required_roles'])} — two different people. Still "
                f"needed: {', '.join(state['outstanding_roles'])}."))


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_shortlist_reviews(actor: dict, company_id: str, *, request_no: str = None,
                                 outcome: str = None, uk: str = None,
                                 limit: int = 100) -> dict:
    query = {"company_id": str(company_id)}
    if request_no:
        query["request_no"] = request_no
    if outcome:
        query["outcome"] = outcome
    if uk:
        query["candidate_uks"] = uk
    limit = max(1, min(int(limit or 100), 200))
    rows = await get_collection(COLL_SHORTLIST_REVIEWS).find(query).sort(
        "created_at", -1).to_list(limit)
    out = [{**_out(r), "committee_state": committee_state(r.get("committee_members"))}
           for r in rows]
    return {
        "shortlist_reviews": out,
        "total": len(out),
        # What a governance screen leads with: sittings that were convened and never decided.
        "pending": sum(1 for r in out
                       if r.get("outcome") == ShortlistOutcome.PENDING.value),
    }


async def get_shortlist_review(company_id: str, slr_no: str) -> Optional[dict]:
    doc = await get_collection(COLL_SHORTLIST_REVIEWS).find_one(
        {"slr_no": slr_no, "company_id": str(company_id)})
    if not doc:
        return None
    out = _out(doc)
    out["committee_state"] = committee_state(doc.get("committee_members"))
    return out


# -------------------------------------------------------------
# The gate
# -------------------------------------------------------------
async def assert_shortlist_cleared(company_id: str, candidate: dict, req: dict) -> None:
    """Refuse to select an internal candidate no committee has finalised (SOP §5).

    Silent on the client track and on a candidate with no requisition -- there is no
    committee to have sat, and refusing would strand a walk-in CV nobody attached to a
    vacancy.

    Bypassed only by an approved `Relaxed Scorecard` exception. Progressing somebody the
    committee has not agreed on IS a relaxation of the selection criteria, which is the
    deviation that type names, so it does not get an exception type of its own.
    """
    track = (req or {}).get("requisition_track") or RequisitionTrack.CLIENT.value
    if track != RequisitionTrack.INTERNAL.value:
        return
    request_no = (req or {}).get("request_no")
    uk = (candidate or {}).get("uk")
    if not request_no or not uk:
        return

    finalised = await get_collection(COLL_SHORTLIST_REVIEWS).find_one({
        "company_id": str(company_id),
        "request_no": request_no,
        "outcome": ShortlistOutcome.FINALISED.value,
        "candidate_uks": uk,
    })
    if finalised:
        return

    from app.services.hrms_exception_service import approved_exception_for
    if await approved_exception_for(company_id, "shortlist", request_no, uk):
        return

    raise HTTPException(
        status_code=409,
        detail=(f'{candidate.get("candidate_name") or uk} has not been finalised by the '
                f"shortlisting committee for {request_no}. SOP section 5 asks HR and the "
                f"Department Head to agree the shortlist before the final interview. "
                f"Record the committee's decision, or log an approved Relaxed Scorecard "
                f"exception."))


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def _resolve_candidates(company_id: str, request_no: str, uks) -> list:
    """Check every named candidate exists and is actually on this requisition.

    The same rule the exception log applies to a candidate-scoped waiver, and for the same
    reason: a committee decision that names somebody from another vacancy would lift a gate
    on work it never reviewed.
    """
    uks = [str(u).strip() for u in (uks or []) if str(u or "").strip()]
    if len(uks) > MAX_SHORTLIST_CANDIDATES:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_SHORTLIST_CANDIDATES} candidates per sitting.")

    resolved, seen = [], set()
    for uk in uks:
        if uk in seen:
            continue
        seen.add(uk)
        candidate = await get_collection(COLL_CANDIDATES).find_one(
            {"uk": uk, "company_id": str(company_id)},
            {"uk": 1, "candidate_name": 1, "request_no": 1, "scorecard_score": 1,
             "scorecard_band": 1})
        if not candidate:
            raise HTTPException(status_code=422, detail=f"{uk} is not a candidate here.")
        if candidate.get("request_no") != request_no:
            raise HTTPException(
                status_code=422,
                detail=(f"{uk} is not a candidate on {request_no}. A committee decides on "
                        f"the shortlist for one vacancy."))
        resolved.append(candidate)
    return resolved


async def _retention_years(company_id: str, record_type: str) -> int:
    """This company's retention floor for `record_type` (Phase INT-5)."""
    from app.services.hrms_config_service import retention_years_for
    return await retention_years_for(company_id, record_type)


async def _bands(company_id: str) -> dict:
    """This company's band floors (Phase INT-5)."""
    from app.services.hrms_config_service import score_bands_for
    return await score_bands_for(company_id)


def _decision_guide(candidates: list, bands: dict = None) -> list:
    """The scoring band beside each candidate, so the committee decides on the evidence.

    Read from the candidate's stored scorecard evaluation and re-banded through
    `score_band` rather than copying the stored label. That way a committee sitting after
    the four-band guide landed sees the CURRENT guide, not whichever one happened to be in
    force when somebody was scored. The number is the fact; the band is its reading.
    """
    return [{
        "uk": c.get("uk"),
        "candidate_name": c.get("candidate_name"),
        "weighted_score": c.get("scorecard_score"),
        "decision_guide_band": score_band(c.get("scorecard_score"), bands),
    } for c in candidates]


async def create_shortlist_review(actor: dict, company_id: str, payload: dict) -> dict:
    """Convene a committee sitting. Convening decides nothing until the outcome is set."""
    request_no = clean_text(payload.get("request_no"), limit=40)
    if not request_no:
        raise HTTPException(status_code=422, detail="Choose a requisition.")
    await _require_internal_requisition(company_id, request_no)

    members = await _resolve_members(company_id, payload.get("committee_members"))
    candidates = await _resolve_candidates(company_id, request_no,
                                           payload.get("candidate_uks"))

    raw_outcome = getattr(payload.get("outcome"), "value", payload.get("outcome"))
    try:
        outcome = ShortlistOutcome(raw_outcome or ShortlistOutcome.PENDING.value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(f"Outcome must be one of: "
                    f"{', '.join(o.value for o in ShortlistOutcome)}."))

    # Finalising is the act that lifts the gate, so THAT is what needs a real committee.
    # Convening one and coming back to it later is a normal way to work.
    if outcome is ShortlistOutcome.FINALISED:
        assert_committee_complete(members)
        if not candidates:
            raise HTTPException(
                status_code=422,
                detail="A finalised shortlist with nobody on it is a deferral. Name the "
                       "candidates, or record the outcome as Deferred.")

    now = datetime.now(timezone.utc)
    slr_no = await next_business_id("shortlist", str(company_id), now.year)
    decided_at = now if outcome is not ShortlistOutcome.PENDING else None

    doc = {
        "slr_no": slr_no,
        "company_id": str(company_id),
        "request_no": request_no,
        "candidate_uks": [c["uk"] for c in candidates],
        "committee_members": members,
        "decision_guide": _decision_guide(candidates, await _bands(company_id)),
        "outcome": outcome.value,
        "notes": clean_text(payload.get("notes"), limit=4000),
        "decided_at": decided_at,
        "convened_by": str(actor.get("_id") or ""),
        "convened_by_name": _actor_name(actor),
        # SOP §13. Selection records live with the requisition, so the requisition's own
        # retention floor is the right one. A floor, not a purge date.
        "retention_until": _add_years(
            now.strftime("%Y-%m-%d"),
            await _retention_years(company_id, "requisition")),
        "created_at": now,
    }
    await get_collection(COLL_SHORTLIST_REVIEWS).insert_one(dict(doc))
    await audit(actor, AUDIT_SHORTLIST_CONVENED, ENTITY_SHORTLIST, slr_no,
                f"{len(candidates)} candidate(s) on {request_no}, "
                f"{len(members)} member(s), outcome {outcome.value}", company_id)

    out = _out(doc)
    out["committee_state"] = committee_state(members)
    return out


async def update_shortlist_review(actor: dict, company_id: str, slr_no: str,
                                  payload: dict) -> dict:
    """Record members, candidates or the outcome.

    A DECIDED sitting is frozen. What the committee agreed on the day is the record; a
    second decision is a second sitting, not an edit of the first -- the same rule that
    freezes an approved scorecard, and for the same reason.
    """
    coll = get_collection(COLL_SHORTLIST_REVIEWS)
    current = await coll.find_one({"slr_no": slr_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Shortlist review not found.")
    if current.get("outcome") != ShortlistOutcome.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=(f'{slr_no} was already decided ("{current.get("outcome")}"). Convene a '
                    f"new sitting rather than rewriting what this one agreed."))

    updates = {}
    if payload.get("committee_members") is not None:
        updates["committee_members"] = await _resolve_members(
            company_id, payload["committee_members"])
    if payload.get("candidate_uks") is not None:
        candidates = await _resolve_candidates(
            company_id, current.get("request_no"), payload["candidate_uks"])
        updates["candidate_uks"] = [c["uk"] for c in candidates]
        updates["decision_guide"] = _decision_guide(candidates,
                                                    await _bands(company_id))
    if payload.get("notes") is not None:
        updates["notes"] = clean_text(payload["notes"], limit=4000)

    decided = None
    if payload.get("outcome") is not None:
        raw = getattr(payload["outcome"], "value", payload["outcome"])
        try:
            decided = ShortlistOutcome(raw)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=(f"Outcome must be one of: "
                        f"{', '.join(o.value for o in ShortlistOutcome)}."))

    if decided is ShortlistOutcome.FINALISED:
        members = updates.get("committee_members", current.get("committee_members"))
        uks = updates.get("candidate_uks", current.get("candidate_uks"))
        assert_committee_complete(members)
        if not uks:
            raise HTTPException(
                status_code=422,
                detail="A finalised shortlist with nobody on it is a deferral. Name the "
                       "candidates, or record the outcome as Deferred.")

    if decided is not None:
        updates["outcome"] = decided.value
        if decided is not ShortlistOutcome.PENDING:
            updates["decided_at"] = datetime.now(timezone.utc)
            updates["decided_by"] = str(actor.get("_id") or "")
            updates["decided_by_name"] = _actor_name(actor)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    # Compare-and-swap on the pending state: two members finalising at once must not both
    # land, the same rule the exception log and the requisition chain follow.
    result = await coll.update_one(
        {"slr_no": slr_no, "company_id": str(company_id),
         "outcome": ShortlistOutcome.PENDING.value},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="This sitting was decided by someone else. Reload and try again.")

    await audit(actor, AUDIT_SHORTLIST_DECIDED, ENTITY_SHORTLIST, slr_no,
                (updates.get("outcome") or "updated")
                + f' on {current.get("request_no")}', company_id)
    return await get_shortlist_review(company_id, slr_no)
