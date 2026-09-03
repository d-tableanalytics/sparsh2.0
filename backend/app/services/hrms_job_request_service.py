"""Client job requests — what a client asks for, before it becomes work Sparsh has agreed to.

    client raises a request -> Sparsh reviews -> Sparsh accepts -> converts to a requisition

-- Why this is not just a requisition raised by a client -------------------------------------
A requisition is Sparsh's own record of work it has taken on, and it carries Sparsh's
approval chain (HR verification, budget, scorecard). Letting a client write straight into
that chain would put an outside party inside our governance and give their request a status
in our pipeline before anybody here had agreed to it.

So a request is a separate, smaller record with its own short lifecycle. Sparsh reviews it,
and CONVERSION is the moment the ask becomes a commitment: the requisition is created then,
by Sparsh, with our department and designation masters filled in -- the two things a client
could not supply and should not choose.

Declining is a first-class outcome for the same reason. Not every request is one we take.

-- What the client may do --------------------------------------------------------------------
Raise one, edit it while it is still being looked at, and withdraw it. Nothing else: they
cannot review, accept, decline or convert their own request, and they cannot see anybody
else's. The scope is resolved from their engagements, never from the request body.

House convention: services validate, gate and audit; routes only check the capability.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_JOB_REQUEST_CONVERTED, AUDIT_JOB_REQUEST_RAISED, AUDIT_JOB_REQUEST_REVIEWED,
    COLL_JOB_REQUESTS, JOB_REQUEST_CLIENT_EDITABLE, JOB_REQUEST_TRANSITIONS,
    JobRequestStatus, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can, is_client_scoped_user, scope_client_ids

ENTITY_JOB_REQUEST = "client job request"

MAX_POSITIONS = 500


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


def _out(doc: dict) -> dict:
    if not doc:
        return {}
    out = dict(doc)
    out.pop("_id", None)
    return out


def _oid(value: str, label: str) -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=422, detail=f"Invalid {label}.")


async def _scope_filter(actor: dict, company_id: str) -> dict:
    """Restrict a client-scoped caller to their own requests.

    `$in` even when the scope is empty, so a client with no live engagement matches nothing
    rather than everything -- the same fail-closed rule the share service follows.
    """
    if not is_client_scoped_user(actor):
        return {}
    allowed = await scope_client_ids(actor, company_id)
    return {"client_id": {"$in": list(allowed or [])}}


async def _resolve_client(actor: dict, company_id: str, requested: Optional[str]) -> tuple:
    """Which client this request belongs to, and its name.

    For a CLIENT user the answer comes from their engagements and a requested id is
    IGNORED, not honoured -- that is what stops a crafted body raising a request against
    somebody else's account. Sparsh staff must name one, because they act for many.
    """
    if is_client_scoped_user(actor):
        allowed = await scope_client_ids(actor, company_id)
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail="Your account is not linked to a client yet. Contact your Sparsh "
                       "contact and they will set it up.")
        if len(allowed) > 1 and requested and str(requested) in set(allowed):
            client_id = str(requested)          # they belong to several; honour the choice
        else:
            client_id = allowed[0]
    else:
        client_id = str(requested or "").strip()
        if not client_id:
            raise HTTPException(status_code=422, detail="Name the client this is for.")

    client = await get_collection("companies").find_one({"_id": _oid(client_id, "client")})
    if not client:
        raise HTTPException(status_code=422, detail="No such client.")
    return client_id, client.get("name")


def _validate(payload: dict, *, partial: bool) -> dict:
    out = {}
    for field, limit, required in (("job_title", 160, True),
                                   ("required_skills", 4000, True),
                                   ("experience", 120, False),
                                   ("location", 160, False),
                                   ("job_description", 8000, False),
                                   ("other_requirements", 4000, False)):
        if field in payload:
            value = _clean(payload[field], limit)
            if required and not value and not partial:
                label = field.replace("_", " ").capitalize()
                raise HTTPException(status_code=422, detail=f"{label} is required.")
            out[field] = value
        elif required and not partial:
            label = field.replace("_", " ").capitalize()
            raise HTTPException(status_code=422, detail=f"{label} is required.")

    if "positions" in payload and payload["positions"] is not None:
        try:
            positions = int(payload["positions"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=422,
                                detail="Number of positions must be a whole number.")
        if positions < 1:
            raise HTTPException(status_code=422, detail="Ask for at least one position.")
        if positions > MAX_POSITIONS:
            raise HTTPException(status_code=422,
                                detail="That number of positions is implausibly large.")
        out["positions"] = positions

    lo, hi = None, None
    for field in ("budget_min", "budget_max"):
        if field in payload:
            if payload[field] is None:
                out[field] = None
                continue
            try:
                amount = float(payload[field])
            except (TypeError, ValueError):
                raise HTTPException(status_code=422,
                                    detail="The budget must be a number.")
            if amount < 0:
                raise HTTPException(status_code=422,
                                    detail="The budget cannot be negative.")
            out[field] = amount
    lo, hi = out.get("budget_min"), out.get("budget_max")
    if lo is not None and hi is not None and lo > hi:
        raise HTTPException(
            status_code=422,
            detail="The minimum of the budget cannot exceed its maximum.")

    if "target_date" in payload:
        value = _clean(payload["target_date"], 10)
        if value and not is_iso_date(value):
            raise HTTPException(
                status_code=422,
                detail="The target date must be a valid YYYY-MM-DD date.")
        out["target_date"] = value
    return out


# ─────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────
async def list_job_requests(actor: dict, company_id: str, *, status: str = None,
                            client_id: str = None, limit: int = 200) -> dict:
    """Sparsh's inbox, and the client's own list. One query, two scopes."""
    query = {"company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    if status:
        if status not in {s.value for s in JobRequestStatus}:
            raise HTTPException(
                status_code=422,
                detail=(f"Status must be one of: "
                        f"{', '.join(s.value for s in JobRequestStatus)}."))
        query["status"] = status
    if client_id and not is_client_scoped_user(actor):
        query["client_id"] = str(client_id)

    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_JOB_REQUESTS).find(query).sort(
        "created_at", -1).limit(limit).to_list(limit)
    return {"job_requests": [_out(r) for r in rows], "total": len(rows)}


async def get_job_request(actor: dict, company_id: str, jbr_no: str) -> dict:
    query = {"jbr_no": jbr_no, "company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    doc = await get_collection(COLL_JOB_REQUESTS).find_one(query)
    if not doc:
        # 404 rather than 403 out of scope: a client should not learn that another client's
        # request exists.
        raise HTTPException(status_code=404, detail="Job request not found.")
    return _out(doc)


# ─────────────────────────────────────────────────────────────
# Writes
# ─────────────────────────────────────────────────────────────
async def create_job_request(actor: dict, company_id: str, payload: dict) -> dict:
    """Raise a job request. Both a client and Sparsh staff can, the latter on their behalf."""
    clean = _validate(payload, partial=False)
    client_id, client_name = await _resolve_client(
        actor, company_id, payload.get("client_id"))

    now = datetime.now(timezone.utc)
    jbr_no = await next_business_id("job_request", str(company_id), now.year)
    doc = {
        "jbr_no": jbr_no,
        "company_id": str(company_id),
        "client_id": client_id,
        "client_name": client_name,
        "status": JobRequestStatus.SUBMITTED.value,
        "raised_by": str((actor or {}).get("_id") or ""),
        "raised_by_name": _actor_name(actor),
        # Whether the client typed this themselves or Sparsh did it for them. Worth keeping:
        # "the client asked for this" and "we wrote down what they asked for" are different
        # claims, and only one of them is the client's own words.
        "raised_by_client": is_client_scoped_user(actor),
        "reviewed_by": None, "reviewed_by_name": None, "reviewed_at": None,
        "decision_remarks": None,
        "request_no": None,                     # filled at conversion
        "created_at": now,
        "updated_at": now,
        **{"positions": 1, **clean},
    }
    await get_collection(COLL_JOB_REQUESTS).insert_one(dict(doc))
    await audit(actor, AUDIT_JOB_REQUEST_RAISED, ENTITY_JOB_REQUEST, jbr_no,
                f"{clean.get('job_title')} x{doc['positions']} for {client_name}",
                company_id)
    await _notify_sparsh(company_id, doc)
    return _out(doc)


async def _notify_sparsh(company_id: str, doc: dict) -> None:
    """A request nobody was told about is a request nobody works."""
    try:
        from app.services.hrms_notify_service import notify_hrms_role
        await notify_hrms_role(
            company_id, ["HR"],
            f"New job request from {doc.get('client_name')}",
            f"{doc.get('client_name')} asked for {doc.get('positions')} x "
            f"{doc.get('job_title')}. It is waiting for review.",
            kind="info", link="/hrms/job-requests", email=True)
    except Exception as e:
        print(f"[WARN] HRMS job-request notification failed: {e}")


async def update_job_request(actor: dict, company_id: str, jbr_no: str,
                             payload: dict) -> dict:
    """Edit a request. A client may only edit their own, and only while it is still open."""
    current = await get_job_request(actor, company_id, jbr_no)

    if is_client_scoped_user(actor) \
            and current["status"] not in JOB_REQUEST_CLIENT_EDITABLE:
        raise HTTPException(
            status_code=409,
            detail=(f'This request is "{current["status"]}" and can no longer be edited. '
                    f"Raise a new one, or talk to your Sparsh contact."))
    if current["status"] in (JobRequestStatus.ACCEPTED.value,
                             JobRequestStatus.DECLINED.value):
        raise HTTPException(
            status_code=409,
            detail=(f'A "{current["status"]}" request is a decision on the record and '
                    f"cannot be edited."))

    clean = _validate(payload, partial=True)
    if not clean:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    clean["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_JOB_REQUESTS).update_one(
        {"jbr_no": jbr_no, "company_id": str(company_id)}, {"$set": clean})
    await audit(actor, AUDIT_JOB_REQUEST_RAISED, ENTITY_JOB_REQUEST, jbr_no,
                f"updated: {', '.join(sorted(k for k in clean if k != 'updated_at'))}",
                company_id)
    return await get_job_request(actor, company_id, jbr_no)


async def act_on_job_request(actor: dict, company_id: str, jbr_no: str,
                             action: str, remarks: str = None) -> dict:
    """Sparsh's review: pick it up, accept it, or decline it.

    Table-driven from JOB_REQUEST_TRANSITIONS for the same reason the requisition chain is:
    the legal moves and the capability each needs are data somebody can read.
    """
    if action not in JOB_REQUEST_TRANSITIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Action must be one of: {', '.join(JOB_REQUEST_TRANSITIONS)}.")
    required_status, next_status, capability, remark_required = \
        JOB_REQUEST_TRANSITIONS[action]

    # Checked HERE as well as at the route, deliberately: this is the boundary between what
    # a client asked for and what Sparsh agreed to, and it should not be possible to cross
    # it from any future caller that skipped the route.
    if not can(actor, capability):
        raise HTTPException(
            status_code=403,
            detail="Only the recruitment team can review a job request.")

    current = await get_job_request(actor, company_id, jbr_no)
    if current["status"] != required_status.value:
        raise HTTPException(
            status_code=409,
            detail=(f'{jbr_no} is "{current["status"]}", not "{required_status.value}".'))

    remarks = _clean(remarks, 2000)
    if remark_required and not remarks:
        raise HTTPException(
            status_code=422,
            detail="Say why the request is being declined. The client is owed a reason.")

    now = datetime.now(timezone.utc)
    result = await get_collection(COLL_JOB_REQUESTS).update_one(
        {"jbr_no": jbr_no, "company_id": str(company_id),
         "status": required_status.value},
        {"$set": {"status": next_status.value,
                  "reviewed_by": str((actor or {}).get("_id") or ""),
                  "reviewed_by_name": _actor_name(actor),
                  "reviewed_at": now,
                  "decision_remarks": remarks or current.get("decision_remarks"),
                  "updated_at": now}})
    if not (result.modified_count or 0):
        raise HTTPException(
            status_code=409,
            detail="Somebody else moved this request. Reload and try again.")

    await audit(actor, AUDIT_JOB_REQUEST_REVIEWED, ENTITY_JOB_REQUEST, jbr_no,
                f'{current["status"]} -> {next_status.value}'
                + (f": {remarks}" if remarks else ""), company_id)
    await _notify_client(company_id, current, next_status, remarks)
    return await get_job_request(actor, company_id, jbr_no)


async def _notify_client(company_id: str, request: dict, status: JobRequestStatus,
                         remarks: str) -> None:
    """Tell the client what happened to their request. Declining silently is the failure
    mode this exists to prevent."""
    if status is JobRequestStatus.UNDER_REVIEW:
        return                              # picking it up is not news
    try:
        from app.models.hrms import COLL_CLIENT_ENGAGEMENTS, ENGAGEMENT_GRANTS_SCOPE
        from app.services.hrms_notify_service import notify_users
        rows = await get_collection(COLL_CLIENT_ENGAGEMENTS).find(
            {"company_id": str(company_id), "client_id": request.get("client_id"),
             "status": {"$in": sorted(ENGAGEMENT_GRANTS_SCOPE)}},
            {"member_user_ids": 1}).to_list(50)
        members = sorted({m for r in rows for m in (r.get("member_user_ids") or [])})
        if not members:
            return
        if status is JobRequestStatus.ACCEPTED:
            await notify_users(
                members, f"Your job request was accepted: {request.get('job_title')}",
                "We have started work on this requirement and will share CVs shortly.",
                kind="success", link="/hrms/my-job-requests", email=True)
        else:
            await notify_users(
                members, f"Your job request was declined: {request.get('job_title')}",
                remarks or "Please contact your Sparsh representative.",
                kind="warning", link="/hrms/my-job-requests", email=True)
    except Exception as e:
        print(f"[WARN] HRMS job-request client notification failed: {e}")


async def withdraw_job_request(actor: dict, company_id: str, jbr_no: str,
                               remarks: str = None) -> dict:
    """The client changing their mind. Allowed while the request is still open."""
    current = await get_job_request(actor, company_id, jbr_no)
    if current["status"] not in JOB_REQUEST_CLIENT_EDITABLE:
        raise HTTPException(
            status_code=409,
            detail=f'A "{current["status"]}" request can no longer be withdrawn.')
    now = datetime.now(timezone.utc)
    await get_collection(COLL_JOB_REQUESTS).update_one(
        {"jbr_no": jbr_no, "company_id": str(company_id)},
        {"$set": {"status": JobRequestStatus.WITHDRAWN.value,
                  "decision_remarks": _clean(remarks, 2000),
                  "updated_at": now}})
    await audit(actor, AUDIT_JOB_REQUEST_REVIEWED, ENTITY_JOB_REQUEST, jbr_no,
                "withdrawn by the client", company_id)
    return await get_job_request(actor, company_id, jbr_no)


async def convert_to_requisition(actor: dict, company_id: str, jbr_no: str,
                                 payload: dict) -> dict:
    """Turn an accepted request into a client-track requisition.

    This is where the client's ask becomes Sparsh's work. The masters the client could not
    supply -- which department and designation this maps to in OUR structure, and who runs
    it -- are supplied here, and from this point the requisition follows the client track's
    ordinary approval chain.

    One requisition per request: converting twice would have two requisitions chasing the
    same vacancies and double the sanctioned-headcount arithmetic.
    """
    if not can(actor, JOB_REQUEST_TRANSITIONS["accept"][2]):
        raise HTTPException(
            status_code=403,
            detail="Only the recruitment team can convert a job request.")

    current = await get_job_request(actor, company_id, jbr_no)
    if current["status"] != JobRequestStatus.ACCEPTED.value:
        raise HTTPException(
            status_code=409,
            detail=(f'Only an accepted request can be converted. {jbr_no} is '
                    f'"{current["status"]}".'))
    if current.get("request_no"):
        raise HTTPException(
            status_code=409,
            detail=(f"{jbr_no} was already converted into {current['request_no']}."))

    from app.services.hrms_requisition_service import create_requisition
    requisition = await create_requisition(actor, company_id, {
        "department_id": payload.get("department_id"),
        "designation_id": payload.get("designation_id"),
        "assignee_id": payload.get("assignee_id"),
        "required_date": payload.get("required_date") or current.get("target_date"),
        "vacancy": int(payload.get("vacancy") or current.get("positions") or 1),
        "experience_required": current.get("experience") or "As discussed",
        "qualification": current.get("job_description") or "As discussed",
        "essential_skills": current.get("required_skills"),
        "offering_ctc": payload.get("offering_ctc") or current.get("budget_max"),
        # The client's free-text location goes on the JD, not the requisition: a
        # requisition's `work_location` is an enum (Office / Remote / Hybrid / Factory) and
        # "Pune - Kharadi" is not one of its members. Passing it here would be silently
        # dropped by the validator, which is worse than not passing it.
        # The client dimension the requisition already understands, and the track that
        # carries it. This is an agency placement, not Sparsh's own vacancy.
        "requisition_track": "client",
        "client_id": current.get("client_id"),
        "jd": {
            "title": current.get("job_title"),
            "responsibilities": current.get("job_description")
            or current.get("other_requirements")
            or f"As set out in job request {jbr_no}.",
            "skills": current.get("required_skills"),
            "experience": current.get("experience"),
            "location": current.get("location"),
        },
    })

    now = datetime.now(timezone.utc)
    await get_collection(COLL_JOB_REQUESTS).update_one(
        {"jbr_no": jbr_no, "company_id": str(company_id)},
        {"$set": {"request_no": requisition["request_no"], "converted_at": now,
                  "converted_by": str((actor or {}).get("_id") or ""),
                  "updated_at": now}})
    await audit(actor, AUDIT_JOB_REQUEST_CONVERTED, ENTITY_JOB_REQUEST, jbr_no,
                f"converted to {requisition['request_no']}", company_id)
    return {"ok": True, "jbr_no": jbr_no,
            "request_no": requisition["request_no"], "requisition": requisition}
