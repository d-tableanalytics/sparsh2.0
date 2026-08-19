"""HRMS > the exception log (internal recruitment track).

SOP §12: "Any deviation from this policy -- extended TAT, relaxed scorecard criteria, offer
outside approved budget, waiver of reference check -- must be recorded, with a reason and an
approver."

-- Why an APPROVED RECORD rather than an override flag ------------------------------------
Every gate on this track can be bypassed. That is not a weakness; a control with no escape
hatch gets worked around outside the system, where nobody can see it. What matters is that
the escape hatch leaves a trail somebody signed.

So the gates do not accept `force: true`, `override: true` or any other boolean on the
request body. They ask this module whether an APPROVED exception of the right type exists for
that requisition. A boolean in a payload records nothing, attributes nothing, and can be sent
by anyone who can read the API docs. An approved exception has a type, a reason, a raiser, an
approver and a timestamp.

-- The raiser is never the approver ---------------------------------------------------------
Annexure B: exception approval is "A" for Management/Finance, with HR and the Department Head
merely "C" (consulted). So whoever asks for the deviation is not the person who grants it --
and because an MD holds BOTH capabilities, that has to be enforced rather than assumed. One
person raising and approving their own exception is not an approval; it is a note to self
with extra steps.

-- Scope: a waiver is as narrow as it was written -------------------------------------------
An exception carrying a `uk` lifts its gate for that candidate only. One without lifts it for
everybody on the requisition, which is what "we are waiving reference checks for this bulk
intake" means. Broad covers narrow; narrow never silently widens.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_EXCEPTION_DECIDED, AUDIT_EXCEPTION_RAISED, COLL_CANDIDATES, COLL_EXCEPTIONS,
    COLL_REQUISITIONS, ENTITY_EXCEPTION, EXCEPTION_UNBLOCKS, ExceptionStatus,
    ExceptionType, RequisitionTrack,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_public_guard import clean_text


async def approved_exception_for(company_id: str, gate: str, request_no: str,
                                 uk: str = None) -> Optional[dict]:
    """The approved exception that lifts `gate` for this requisition, or None.

    `gate` is a key of EXCEPTION_UNBLOCKS ("reference_check", "salary_band", ...), NOT a raw
    exception type -- so a caller cannot accidentally ask whether "any exception at all"
    exists. Each gate names the one deviation that lifts it.

    A CANDIDATE-SPECIFIC exception (one carrying `uk`) lifts the gate only for that
    candidate. A requisition-wide one (no `uk`) lifts it for everybody on that requisition,
    which is what "we are waiving reference checks for this bulk intake" means. The reverse
    is deliberately not true: an exception raised for one candidate must never quietly cover
    the next.
    """
    exception_type = EXCEPTION_UNBLOCKS.get(gate)
    if not exception_type or not request_no:
        return None

    query = {
        "company_id": str(company_id),
        "request_no": request_no,
        "exception_type": exception_type,
        "status": ExceptionStatus.APPROVED.value,
    }
    # Requisition-wide first: it is the broader permission, and finding it avoids a second
    # read in the common "waived for this intake" case.
    wide = await get_collection(COLL_EXCEPTIONS).find_one({**query, "uk": None})
    if wide:
        return _out(wide)
    if not uk:
        return None
    narrow = await get_collection(COLL_EXCEPTIONS).find_one({**query, "uk": uk})
    return _out(narrow) if narrow else None


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


# Which gate each exception type lifts, derived from EXCEPTION_UNBLOCKS rather than written
# out again. One table, read in both directions.
GATE_FOR_TYPE = {value: gate for gate, value in EXCEPTION_UNBLOCKS.items()}


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_exceptions(actor: dict, company_id: str, *, request_no: str = None,
                          uk: str = None, status: str = None,
                          exception_type: str = None, limit: int = 100) -> dict:
    query = {"company_id": str(company_id)}
    if request_no:
        query["request_no"] = request_no
    if uk:
        query["uk"] = uk
    if status:
        query["status"] = status
    if exception_type:
        query["exception_type"] = exception_type
    limit = max(1, min(int(limit or 100), 200))
    rows = await get_collection(COLL_EXCEPTIONS).find(query).sort(
        "created_at", -1).to_list(limit)
    out = [_out(r) for r in rows]
    return {
        "exceptions": out,
        "total": len(out),
        # The count a governance screen actually leads with: what is waiting on somebody.
        "pending": sum(1 for r in out if r.get("status") == ExceptionStatus.PENDING.value),
    }


async def get_exception(company_id: str, exc_no: str) -> Optional[dict]:
    doc = await get_collection(COLL_EXCEPTIONS).find_one(
        {"exc_no": exc_no, "company_id": str(company_id)})
    return _out(doc) if doc else None


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def raise_exception(actor: dict, company_id: str, payload: dict) -> dict:
    """Log a deviation for approval. Raising one grants nothing until it is approved."""
    request_no = clean_text(payload.get("request_no"), limit=40)
    if not request_no:
        raise HTTPException(status_code=422, detail="Choose a requisition.")

    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if not req:
        raise HTTPException(
            status_code=422, detail="That requisition does not exist for this company.")
    track = req.get("requisition_track") or RequisitionTrack.CLIENT.value
    if track != RequisitionTrack.INTERNAL.value:
        raise HTTPException(
            status_code=409,
            detail=(f"{request_no} is a client requisition. The exception log records "
                    f"deviations from Sparsh Magic's own recruitment policy; the client "
                    f"track has no gates for one to lift."))

    raw_type = getattr(payload.get("exception_type"), "value", payload.get("exception_type"))
    try:
        exception_type = ExceptionType(raw_type)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(f"Type must be one of: "
                    f"{', '.join(t.value for t in ExceptionType)}."))

    reason = clean_text(payload.get("reason"), limit=4000)
    if not reason:
        raise HTTPException(
            status_code=422,
            detail=("Say why the deviation is needed. An exception with no reason is the "
                    "thing this log exists to prevent."))

    uk = clean_text(payload.get("uk"), limit=40) or None
    if uk:
        candidate = await get_collection(COLL_CANDIDATES).find_one(
            {"uk": uk, "company_id": str(company_id)})
        if not candidate:
            raise HTTPException(status_code=422, detail="That candidate does not exist.")
        if candidate.get("request_no") != request_no:
            raise HTTPException(
                status_code=422,
                detail=(f"{uk} is not a candidate on {request_no}. An exception must name "
                        f"the requisition the candidate is actually against, or the waiver "
                        f"would lift a gate on work it was never reviewed for."))

    # A second PENDING request for the same waiver is noise, and approving one of two
    # identical rows leaves the other stranded forever.
    duplicate = await get_collection(COLL_EXCEPTIONS).find_one({
        "company_id": str(company_id), "request_no": request_no, "uk": uk,
        "exception_type": exception_type.value,
        "status": ExceptionStatus.PENDING.value})
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=(f'{duplicate.get("exc_no")} already requests "{exception_type.value}" '
                    f"for this scope and is still awaiting a decision."))

    year = datetime.now(timezone.utc).year
    exc_no = await next_business_id("exception", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "exc_no": exc_no,
        "company_id": str(company_id),
        "request_no": request_no,
        "uk": uk,
        "candidate_name": None,
        "exception_type": exception_type.value,
        # Named on the record so a reader does not have to know EXCEPTION_UNBLOCKS to see
        # what this would actually let through. None for "Other", which lifts nothing.
        "gate": GATE_FOR_TYPE.get(exception_type.value),
        "reason": reason,
        "linked_entity": clean_text(payload.get("linked_entity"), limit=60),
        "status": ExceptionStatus.PENDING.value,
        "raised_by": str(actor.get("_id") or ""),
        "raised_by_name": actor.get("full_name") or actor.get("email"),
        "raised_at": now,
        "approved_by": None,
        "approved_by_name": None,
        "approved_at": None,
        "decision_remarks": None,
        "created_at": now,
    }
    if uk:
        candidate = await get_collection(COLL_CANDIDATES).find_one(
            {"uk": uk, "company_id": str(company_id)}, {"candidate_name": 1})
        doc["candidate_name"] = (candidate or {}).get("candidate_name")

    await get_collection(COLL_EXCEPTIONS).insert_one(dict(doc))
    await audit(actor, AUDIT_EXCEPTION_RAISED, ENTITY_EXCEPTION, exc_no,
                f'{exception_type.value} on {request_no}'
                + (f" for {uk}" if uk else " (all candidates)"), company_id)
    return _out(doc)


async def decide_exception(actor: dict, company_id: str, exc_no: str,
                           payload: dict) -> dict:
    """Approve or reject an exception. Only an approval lifts anything."""
    coll = get_collection(COLL_EXCEPTIONS)
    current = await coll.find_one({"exc_no": exc_no, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Exception not found.")
    if current.get("status") != ExceptionStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=(f'{exc_no} was already {current.get("status", "decided").lower()}. '
                    f"Raise a new exception if the situation has changed."))

    actor_id = str(actor.get("_id") or "")
    # Annexure B puts HR and the Department Head at "C" and Management at "A" -- the asker is
    # never the granter. Enforced rather than assumed, because an MD holds both capabilities
    # and would otherwise be able to wave through their own request.
    if actor_id and actor_id == str(current.get("raised_by") or ""):
        raise HTTPException(
            status_code=409,
            detail=("You raised this exception, so you cannot approve it. A deviation is "
                    "granted by somebody other than the person who asked for it."))

    signature = clean_text(payload.get("signature"), limit=140)
    if not signature:
        raise HTTPException(
            status_code=422,
            detail="Type your name to sign this decision. It sets aside a control.")

    raw = getattr(payload.get("decision"), "value", payload.get("decision"))
    try:
        decision = ExceptionStatus(raw)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="Decision must be Approved or Rejected.")
    if decision is ExceptionStatus.PENDING:
        raise HTTPException(
            status_code=422,
            detail="Pending is the starting state, not a decision. Approve it or reject it.")

    remarks = clean_text(payload.get("remarks"), limit=2000)
    if decision is ExceptionStatus.REJECTED and not remarks:
        raise HTTPException(
            status_code=422,
            detail="Say why the exception is refused, so the raiser knows what to do next.")

    now = datetime.now(timezone.utc)
    updates = {
        "status": decision.value,
        "approved_by": actor_id,
        "approved_by_name": actor.get("full_name") or actor.get("email"),
        "approved_at": now,
        "signature": signature,
        "decision_remarks": remarks,
        "updated_at": now,
    }
    # Compare-and-swap on the pending state: two approvers clicking at once must not both
    # land, the same rule the requisition chain follows.
    result = await coll.update_one(
        {"exc_no": exc_no, "company_id": str(company_id),
         "status": ExceptionStatus.PENDING.value},
        {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="This exception was decided by someone else. Reload and try again.")

    await audit(actor, AUDIT_EXCEPTION_DECIDED, ENTITY_EXCEPTION, exc_no,
                f'{decision.value}: {remarks or "no remarks"}', company_id)
    return await get_exception(company_id, exc_no)
