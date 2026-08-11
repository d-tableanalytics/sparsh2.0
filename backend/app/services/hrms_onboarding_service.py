"""HRMS > onboarding, and the moment recruitment becomes an employee.

This phase closes the gap both analysis documents named as the single largest hole in the
source system: "Employee Management -- Not found" (BACKEND_ANALYSIS 2). The source could
hire someone and then had nowhere to put them. Everything from Phase 3 onwards has been
building a pipeline whose last step did not exist; this is that step.

-- An employee is created BEFORE they have a login ---------------------------------------
A new hire is not yet a user of the ERP. Their Employee ID is issued on day one, but their
account may be created days later, or never (a factory hire who never signs in still needs
payroll). HRMS therefore mints the employee record with NO `user_id` at all -- the field is
absent rather than null, because a null value is still indexed and the unique index would
then permit exactly one such row. `hrms_employee_profiles.uniq_user` is sparse for this
reason, and the directory composes such a person from the `identity_snapshot` captured at
onboarding, flagged `pending_user_link`.

HRMS still never writes to `staff` or `learners`. The alternative -- having HRMS create a
`learners` login -- would put an HR module in charge of authentication records it does not
own, and would break the invariant asserted in every phase since Phase 1. When the account
does appear, `POST /hrms/employees/{code}/link` attaches it and the user document becomes
the single source of identity from that moment on.

-- The checklist has two kinds of item ---------------------------------------------------
Nine items are human judgements (assets issued, induction done). Three are claims the system
can verify and therefore owns: `employee_id`, `documents_verified` and `bg_cleared`. Letting
a human tick those by hand would let the checklist assert something the data contradicts --
"background cleared" while the verification sits at Flagged. Those three are driven by the
actions that actually achieve them and are refused as manual edits.

-- Only an accepted offer may be onboarded -----------------------------------------------
Onboarding collects PAN, Aadhaar and bank details. Asking a candidate for those before they
have agreed to join gathers sensitive identity data on somebody who may still say no, so the
gate is `Offer Accepted` and nothing earlier (see ONBOARDABLE_STATUSES).
"""
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AADHAAR_RE, AUDIT_EMPLOYEE_ID_ISSUED, AUDIT_ONBOARD_BG, AUDIT_ONBOARD_CHECKLIST,
    AUDIT_ONBOARD_COMPLETED, AUDIT_ONBOARD_DETAILS, AUDIT_ONBOARD_DOCUMENTS,
    AUDIT_ONBOARD_STARTED, AUDIT_ONBOARD_SUBMITTED, AUDIT_ONBOARD_VERIFIED,
    AUDIT_STAGE_CHANGED, CHECKLIST_KEYS, COLL_CANDIDATES, COLL_OFFERS, COLL_ONBOARDING,
    COLL_REQUISITIONS, ENTITY_CANDIDATE, ENTITY_ONBOARDING,
    IFSC_RE, MAX_ONBOARD_DOCUMENTS, MAX_REFERENCES, ONBOARDABLE_STATUSES, PAN_RE,
    SYSTEM_CHECKLIST_KEYS, AppStatus, BgVerification, Gender, OfferStatus,
    OnboardStatus, PreOnboardStatus, can_transition, is_iso_date, seed_checklist,
)
from app.services import hrms_employee_service as employees
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.services.hrms_notify_service import notify_hrms_role, notify_user
from app.utils.hrms_public_guard import (
    INVALID_LINK, clean_text, decode_upload, new_access_code,
)


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_name(actor: dict) -> str:
    if not actor:
        return "System"
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _progress(checklist: list) -> dict:
    total = len(checklist or [])
    done = sum(1 for item in (checklist or []) if item.get("done"))
    return {"done": done, "total": total,
            "percent": int(round(done * 100 / total)) if total else 0}


async def _get(company_id: str, onb_no: str) -> dict:
    doc = await get_collection(COLL_ONBOARDING).find_one(
        {"onb_no": onb_no, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Onboarding record not found.")
    return doc


def _assert_open(doc: dict) -> None:
    """Refuse edits once onboarding is Completed.

    A completed onboarding is a record of what happened, not a working document. Re-opening
    it to tick a box would rewrite history; the employee record is the live thing from then
    on and is edited through the employee master.
    """
    if doc.get("status") == OnboardStatus.COMPLETED.value:
        raise HTTPException(
            status_code=409,
            detail="This onboarding is complete. Update the employee record instead.")


# ─────────────────────────────────────────────────────────────
# Candidate stage movement
# ─────────────────────────────────────────────────────────────
async def _advance_candidate(actor: Optional[dict], company_id: str, uk: str,
                             target: AppStatus) -> None:
    """Move the candidate, but only along a legal edge.

    Deliberately silent when the edge is illegal: onboarding must not fail because the
    candidate was moved by hand in the meantime. The lifecycle graph is the authority and a
    refused move is simply not made, rather than corrupting the stage or aborting the
    onboarding step the operator actually asked for.
    """
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)}, {"application_status": 1})
    current = (candidate or {}).get("application_status")
    if not current or current == target.value:
        return
    if not can_transition(current, target.value):
        return
    await get_collection(COLL_CANDIDATES).update_one(
        {"uk": uk, "company_id": str(company_id)},
        {"$set": {"application_status": target.value,
                  "updated_at": datetime.now(timezone.utc)}})
    await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                f"{current} -> {target.value}", company_id)


# ─────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────
async def list_onboardings(actor: dict, company_id: str, *, status: str = None,
                           search: str = None) -> list:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if search:
        term = clean_text(search, limit=80)
        if term:
            escaped = re.escape(term)
            query["$or"] = [
                {"candidate_name": {"$regex": escaped, "$options": "i"}},
                {"onb_no": {"$regex": escaped, "$options": "i"}},
                {"employee_id": {"$regex": escaped, "$options": "i"}},
            ]

    rows = await get_collection(COLL_ONBOARDING).find(query).sort("created_at", -1).to_list(500)
    out = []
    for row in rows:
        view = _out(row)
        view["progress"] = _progress(view.get("checklist"))
        # The access code is a credential. It belongs on the detail view (where HR copies the
        # link) and nowhere else -- a list endpoint is the easiest thing to over-share.
        view.pop("access_code", None)
        view.pop("submission", None)
        out.append(view)
    return out


async def get_onboarding(actor: dict, company_id: str, onb_no: str) -> dict:
    doc = _out(await _get(company_id, onb_no))
    doc["progress"] = _progress(doc.get("checklist"))
    doc["can_generate_id"] = _id_blockers(doc) == []
    doc["id_blockers"] = _id_blockers(doc)
    return doc


async def onboardable_candidates(actor: dict, company_id: str) -> list:
    """Candidates who have accepted an offer and do not yet have an onboarding."""
    existing = await get_collection(COLL_ONBOARDING).find(
        {"company_id": str(company_id)}, {"uk": 1}).to_list(2000)
    taken = {row.get("uk") for row in existing}

    rows = await get_collection(COLL_CANDIDATES).find(
        {"company_id": str(company_id),
         "application_status": {"$in": [s.value for s in ONBOARDABLE_STATUSES]}},
        {"uk": 1, "candidate_name": 1, "can_email": 1, "can_contact": 1,
         "request_no": 1, "application_status": 1}).to_list(500)

    return [{"uk": r["uk"], "candidate_name": r.get("candidate_name"),
             "can_email": r.get("can_email"), "can_contact": r.get("can_contact"),
             "request_no": r.get("request_no"),
             "application_status": r.get("application_status")}
            for r in rows if r.get("uk") not in taken]


# ─────────────────────────────────────────────────────────────
# Start
# ─────────────────────────────────────────────────────────────
async def start_onboarding(actor: dict, company_id: str, payload: dict) -> dict:
    uk = clean_text(payload.get("uk"), limit=40)
    if not uk:
        raise HTTPException(status_code=422, detail="Choose a candidate.")

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    # Duplicate check FIRST. Starting an onboarding moves the candidate to Pre-Onboarding,
    # so a second attempt would otherwise fail the stage gate below and report "they have
    # not accepted an offer" -- true of the stage, but not the reason, and actively
    # misleading to whoever is looking at an accepted offer on their screen.
    if await get_collection(COLL_ONBOARDING).find_one(
            {"uk": uk, "company_id": str(company_id)}):
        raise HTTPException(
            status_code=409, detail="This candidate is already being onboarded.")

    stage = candidate.get("application_status")
    if stage not in {s.value for s in ONBOARDABLE_STATUSES}:
        raise HTTPException(
            status_code=409,
            detail="Onboarding can only be started once the candidate has accepted an offer.")

    # Pull terms from the accepted offer, then the requisition. The offer is the more
    # authoritative source -- it is what the candidate actually agreed to.
    offer = await get_collection(COLL_OFFERS).find_one(
        {"uk": uk, "company_id": str(company_id),
         "status": OfferStatus.ACCEPTED.value})
    req = None
    if candidate.get("request_no"):
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": candidate["request_no"], "company_id": str(company_id)})

    joining_date = clean_text(payload.get("joining_date"), limit=10) \
        or (offer or {}).get("joining_date")
    if joining_date and not is_iso_date(joining_date):
        raise HTTPException(
            status_code=422,
            detail="Joining date must be a valid date in YYYY-MM-DD format.")

    year = datetime.now(timezone.utc).year
    onb_no = await next_business_id("onboarding", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "onb_no": onb_no,
        "company_id": str(company_id),
        "uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        "candidate_email": candidate.get("can_email"),
        "candidate_mobile": candidate.get("can_contact"),
        "offer_no": (offer or {}).get("offer_no"),
        "request_no": candidate.get("request_no"),
        "designation": (offer or {}).get("designation") or (req or {}).get("designation_name"),
        "department_id": (req or {}).get("department_id"),
        "designation_id": (req or {}).get("designation_id"),
        "status": OnboardStatus.PRE_ONBOARDING.value,
        "pre_status": PreOnboardStatus.PENDING.value,
        "bg_verification": BgVerification.PENDING.value,
        "bg_note": None,
        "access_code": new_access_code(),
        "joining_date": joining_date,
        "reporting_manager_id": clean_text(payload.get("reporting_manager_id"), limit=40)
        or (req or {}).get("assignee_id"),
        "asset_requirements": None,
        "submission": None,
        "documents": [],
        "checklist": seed_checklist(),
        "employee_id": None,
        "created_at": now,
        "created_by": str(actor.get("_id")) if actor and actor.get("_id") else None,
        "created_by_name": _actor_name(actor),
        "updated_at": now,
    }
    await get_collection(COLL_ONBOARDING).insert_one(dict(doc))

    # Phase 11-R, Item 1: register the pre-onboarding link. Fire-and-forget by contract.
    from app.models.hrms import LinkKind
    from app.services.hrms_link_service import register_link
    await register_link(
        company_id=company_id, kind=LinkKind.ONBOARDING, code=doc["access_code"],
        target_type="onboarding", target_id=onb_no, actor=actor,
        candidate_name=doc.get("candidate_name"), request_no=doc.get("request_no"))

    await _advance_candidate(actor, company_id, uk, AppStatus.PRE_ONBOARDING)
    await audit(actor, AUDIT_ONBOARD_STARTED, ENTITY_ONBOARDING, onb_no,
                doc["candidate_name"], company_id)
    await notify_hrms_role(
        company_id, ["HR"], f"Onboarding started: {doc['candidate_name']}",
        f"{onb_no} is open. Send the pre-onboarding form to collect their documents.",
        link="/hrms/onboarding")

    return await get_onboarding(actor, company_id, onb_no)


# ─────────────────────────────────────────────────────────────
# HR-side edits
# ─────────────────────────────────────────────────────────────
async def update_details(actor: dict, company_id: str, onb_no: str, payload: dict) -> dict:
    doc = await _get(company_id, onb_no)
    _assert_open(doc)

    changes = {}
    if "joining_date" in payload:
        value = clean_text(payload.get("joining_date"), limit=10)
        if value and not is_iso_date(value):
            raise HTTPException(
                status_code=422,
                detail="Joining date must be a valid date in YYYY-MM-DD format.")
        changes["joining_date"] = value or None
    if "reporting_manager_id" in payload:
        changes["reporting_manager_id"] = clean_text(
            payload.get("reporting_manager_id"), limit=40) or None
    if "asset_requirements" in payload:
        changes["asset_requirements"] = clean_text(
            payload.get("asset_requirements"), limit=2000) or None

    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to update.")

    changes["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)}, {"$set": changes})
    await audit(actor, AUDIT_ONBOARD_DETAILS, ENTITY_ONBOARDING, onb_no,
                ", ".join(k for k in changes if k != "updated_at"), company_id)
    return await get_onboarding(actor, company_id, onb_no)


async def update_bg(actor: dict, company_id: str, onb_no: str, payload: dict) -> dict:
    """Record the background-verification outcome.

    Also drives the `bg_cleared` checklist item, in BOTH directions: moving away from Cleared
    un-ticks it. A checklist that only ever moves forwards would keep asserting a clearance
    that has since been withdrawn.
    """
    doc = await _get(company_id, onb_no)
    _assert_open(doc)

    raw = payload.get("bg_verification")
    value = getattr(raw, "value", raw)
    try:
        outcome = BgVerification(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Unknown background-check outcome.")

    now = datetime.now(timezone.utc)
    checklist = _set_item(doc.get("checklist") or [], "bg_cleared",
                          outcome == BgVerification.CLEARED, actor, now)
    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)},
        {"$set": {"bg_verification": outcome.value,
                  "bg_note": clean_text(payload.get("note"), limit=2000),
                  "checklist": checklist, "updated_at": now}})
    await audit(actor, AUDIT_ONBOARD_BG, ENTITY_ONBOARDING, onb_no, outcome.value, company_id)

    if outcome == BgVerification.FLAGGED:
        await notify_hrms_role(
            company_id, ["HR", "MD"],
            f"Background check flagged: {doc.get('candidate_name')}",
            f"{onb_no} was flagged during background verification. "
            "An Employee ID cannot be issued until this is resolved.",
            kind="warning", link="/hrms/onboarding", email=True)

    return await _refresh(actor, company_id, onb_no)


async def verify_documents(actor: dict, company_id: str, onb_no: str) -> dict:
    """Mark the candidate's KYC documents as checked by a human."""
    doc = await _get(company_id, onb_no)
    _assert_open(doc)
    if doc.get("pre_status") != PreOnboardStatus.SUBMITTED.value:
        raise HTTPException(
            status_code=409,
            detail="There is nothing to verify yet — the candidate has not submitted "
                   "their pre-onboarding form.")

    now = datetime.now(timezone.utc)
    checklist = _set_item(doc.get("checklist") or [], "documents_verified", True, actor, now)
    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)},
        {"$set": {"pre_status": PreOnboardStatus.VERIFIED.value,
                  "verified_at": now, "verified_by": _actor_name(actor),
                  "checklist": checklist, "updated_at": now}})
    await audit(actor, AUDIT_ONBOARD_VERIFIED, ENTITY_ONBOARDING, onb_no,
                doc.get("candidate_name"), company_id)
    return await _refresh(actor, company_id, onb_no)


async def add_documents(actor: dict, company_id: str, onb_no: str, payload: dict) -> dict:
    """HR-side KYC upload — for documents handed over in person or by email.

    Separate from the candidate's public submission so HR is never blocked waiting for a
    form the candidate has not filled in.
    """
    doc = await _get(company_id, onb_no)
    _assert_open(doc)

    uploads = payload.get("documents") or []
    if not uploads:
        raise HTTPException(status_code=422, detail="Attach at least one document.")

    existing = doc.get("documents") or []
    stored = await _store_documents(uploads, existing_count=len(existing), source="hr")

    now = datetime.now(timezone.utc)
    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)},
        {"$set": {"updated_at": now}, "$push": {"documents": {"$each": stored}}})
    await audit(actor, AUDIT_ONBOARD_DOCUMENTS, ENTITY_ONBOARDING, onb_no,
                f"{len(stored)} document(s) added", company_id)
    return await _refresh(actor, company_id, onb_no)


# ─────────────────────────────────────────────────────────────
# Checklist
# ─────────────────────────────────────────────────────────────
def _set_item(checklist: list, key: str, done: bool, actor: Optional[dict],
              now: datetime) -> list:
    out = []
    for item in checklist or []:
        item = dict(item)
        if item.get("key") == key:
            item["done"] = bool(done)
            item["done_at"] = now if done else None
            item["done_by"] = _actor_name(actor) if done else None
        out.append(item)
    return out


async def set_checklist(actor: dict, company_id: str, onb_no: str, payload: dict) -> dict:
    doc = await _get(company_id, onb_no)
    _assert_open(doc)

    key = clean_text(payload.get("key"), limit=60)
    if key not in CHECKLIST_KEYS:
        raise HTTPException(status_code=422, detail="Unknown checklist item.")
    if key in SYSTEM_CHECKLIST_KEYS:
        # The system owns these three because it can verify them. A hand-tick would let the
        # checklist assert something the data contradicts.
        raise HTTPException(
            status_code=409,
            detail="This item is updated automatically by the system, not by hand.")

    now = datetime.now(timezone.utc)
    checklist = _set_item(doc.get("checklist") or [], key, bool(payload.get("done")),
                          actor, now)
    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)},
        {"$set": {"checklist": checklist, "updated_at": now}})
    await audit(actor, AUDIT_ONBOARD_CHECKLIST, ENTITY_ONBOARDING, onb_no,
                f"{key} {'done' if payload.get('done') else 'reopened'}", company_id)
    return await _refresh(actor, company_id, onb_no)


# ─────────────────────────────────────────────────────────────
# The handover — minting the employee record
# ─────────────────────────────────────────────────────────────
def _id_blockers(doc: dict) -> list:
    """Everything standing between this onboarding and an Employee ID.

    Returned as a list rather than a bool so the UI can say *why* the button is disabled.
    An unexplained disabled control is the most common source of "the system is broken"
    tickets.
    """
    blockers = []
    if doc.get("employee_id"):
        blockers.append("An Employee ID has already been issued.")
    if doc.get("pre_status") != PreOnboardStatus.VERIFIED.value:
        blockers.append("KYC documents have not been verified.")
    if doc.get("bg_verification") == BgVerification.FLAGGED.value:
        blockers.append("Background verification is flagged.")
    if not doc.get("joining_date"):
        blockers.append("A joining date has not been set.")
    return blockers


async def generate_employee_id(actor: dict, company_id: str, onb_no: str) -> dict:
    """Issue the Employee ID and create the employee record.

    This is the point the pipeline has been heading towards since Phase 3: a candidate stops
    being a candidate. Everything downstream (leave, attendance, payroll, reporting) keys off
    the record created here.
    """
    doc = await _get(company_id, onb_no)
    _assert_open(doc)

    blockers = _id_blockers(doc)
    if blockers:
        raise HTTPException(status_code=409, detail=" ".join(blockers))

    year = datetime.now(timezone.utc).year
    employee_code = await next_business_id("employee", str(company_id), year)
    now = datetime.now(timezone.utc)

    submission = doc.get("submission") or {}
    extra = {field: submission.get(field) for field in (
        "pan", "aadhaar", "date_of_birth", "gender", "address",
        "bank_name", "bank_account", "bank_ifsc",
        "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
    )}

    # Claim the ID on the onboarding FIRST, conditioned on it still being unissued. Two
    # simultaneous clicks then produce one employee, not two: the loser's update matches
    # nothing and it stops before creating a duplicate record.
    claimed = await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id), "employee_id": None},
        {"$set": {"employee_id": employee_code, "employee_created_at": now,
                  "status": OnboardStatus.ONBOARDING.value, "updated_at": now}})
    if getattr(claimed, "modified_count", 0) == 0:
        raise HTTPException(
            status_code=409, detail="An Employee ID has already been issued.")

    try:
        await employees.create_from_onboarding(
            actor, company_id,
            employee_code=employee_code,
            identity={"name": doc.get("candidate_name"),
                      "email": doc.get("candidate_email"),
                      "mobile": doc.get("candidate_mobile")},
            source_uk=doc.get("uk"),
            joined_on=doc.get("joining_date"),
            department_id=doc.get("department_id"),
            designation_id=doc.get("designation_id"),
            extra=extra)
    except Exception:
        # The employee record is the point of the operation. If it could not be written, the
        # claim above is a lie -- release it so the operator can retry rather than leaving an
        # onboarding that believes it produced an employee that does not exist.
        await get_collection(COLL_ONBOARDING).update_one(
            {"onb_no": onb_no, "company_id": str(company_id)},
            {"$set": {"employee_id": None, "employee_created_at": None,
                      "status": OnboardStatus.PRE_ONBOARDING.value, "updated_at": now}})
        raise

    fresh = await _get(company_id, onb_no)
    checklist = _set_item(fresh.get("checklist") or [], "employee_id", True, actor, now)
    await get_collection(COLL_ONBOARDING).update_one(
        {"onb_no": onb_no, "company_id": str(company_id)},
        {"$set": {"checklist": checklist, "updated_at": now}})

    # An Employee ID means the person has joined.
    await _advance_candidate(actor, company_id, doc.get("uk"), AppStatus.JOINED)
    await audit(actor, AUDIT_EMPLOYEE_ID_ISSUED, ENTITY_ONBOARDING, onb_no,
                f"{employee_code} for {doc.get('candidate_name')}", company_id)
    await notify_hrms_role(
        company_id, ["HR", "MD"], f"Employee created: {doc.get('candidate_name')}",
        f"{employee_code} has been issued. They now appear in the employee directory and "
        "can be linked to a login account.",
        kind="success", link="/hrms/employees", email=True)

    return await _refresh(actor, company_id, onb_no)


async def _refresh(actor: dict, company_id: str, onb_no: str) -> dict:
    """Re-read, settle completion, and return the view. Every mutator ends here."""
    doc = await _get(company_id, onb_no)
    checklist = doc.get("checklist") or []

    if (checklist and all(item.get("done") for item in checklist)
            and doc.get("status") != OnboardStatus.COMPLETED.value):
        now = datetime.now(timezone.utc)
        await get_collection(COLL_ONBOARDING).update_one(
            {"onb_no": onb_no, "company_id": str(company_id),
             "status": {"$ne": OnboardStatus.COMPLETED.value}},
            {"$set": {"status": OnboardStatus.COMPLETED.value,
                      "completed_at": now, "updated_at": now}})
        await _advance_candidate(actor, company_id, doc.get("uk"),
                                 AppStatus.EMPLOYEE_CREATED)
        await audit(actor, AUDIT_ONBOARD_COMPLETED, ENTITY_ONBOARDING, onb_no,
                    doc.get("candidate_name"), company_id)
        await notify_hrms_role(
            company_id, ["HR"], f"Onboarding complete: {doc.get('candidate_name')}",
            f"Every step of {onb_no} is done.", kind="success", link="/hrms/onboarding")

    return await get_onboarding(actor, company_id, onb_no)


# ─────────────────────────────────────────────────────────────
# Uploads
# ─────────────────────────────────────────────────────────────
async def _store_documents(uploads: list, *, existing_count: int, source: str) -> list:
    if existing_count + len(uploads) > MAX_ONBOARD_DOCUMENTS:
        raise HTTPException(
            status_code=422,
            detail=f"A maximum of {MAX_ONBOARD_DOCUMENTS} documents can be attached.")

    stored = []
    for i, upload in enumerate(uploads):
        raw, name, mime = decode_upload(upload, label=f"Document {i + 1}")
        if not raw:
            continue
        import io
        from app.services.s3_service import upload_file_to_s3_with_key
        try:
            result = upload_file_to_s3_with_key(io.BytesIO(raw), f"onboard_{name}", mime)
        except Exception as e:
            print(f"[WARN] HRMS onboarding upload failed: {e}")
            raise HTTPException(
                status_code=503,
                detail="Your document could not be uploaded right now. Please try again.")
        stored.append({
            "name": name,
            "key": result.get("key") if isinstance(result, dict) else None,
            "mime_type": mime,
            "source": source,
            "uploaded_at": datetime.now(timezone.utc),
        })
    return stored


# ─────────────────────────────────────────────────────────────
# The public pre-onboarding form
# ─────────────────────────────────────────────────────────────
async def get_public_onboarding(code: str) -> dict:
    """What the new hire sees behind their pre-onboarding link.

    Exposes only what they need to recognise the form as genuinely theirs. No company_id, no
    requisition number, no offer terms, no internal status beyond "already submitted".
    """
    doc = await get_collection(COLL_ONBOARDING).find_one({"access_code": code})
    if not doc:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if doc.get("status") == OnboardStatus.COMPLETED.value:
        raise HTTPException(
            status_code=410,
            detail="This form is closed. Please contact the HR team if you need to update "
                   "your details.")

    return {
        "ok": True,
        "already_submitted": doc.get("pre_status") != PreOnboardStatus.PENDING.value,
        "candidate_name": doc.get("candidate_name"),
        "designation": doc.get("designation"),
        "joining_date": doc.get("joining_date"),
        "submitted_at": doc.get("submitted_at"),
        "max_documents": MAX_ONBOARD_DOCUMENTS,
        "max_references": MAX_REFERENCES,
    }


def _validate_submission(payload: dict) -> dict:
    """Validate the new hire's details SERVER-SIDE.

    The source enforced PAN-or-Aadhaar in the browser only (BACKEND_ANALYSIS 8), so any
    request that skipped the form put an employee into payroll with no identity document at
    all. Everything below runs regardless of what the client did.
    """
    out = {}

    pan = (payload.get("pan") or "").strip().upper()
    aadhaar = (payload.get("aadhaar") or "").strip()
    if not pan and not aadhaar:
        raise HTTPException(
            status_code=422,
            detail="Provide your PAN or your Aadhaar number — at least one is required.")
    if pan:
        if not PAN_RE.match(pan):
            raise HTTPException(status_code=422, detail="PAN is not valid (e.g. ABCDE1234F).")
        out["pan"] = pan
    if aadhaar:
        aadhaar = aadhaar.replace(" ", "")
        if not AADHAAR_RE.match(aadhaar):
            raise HTTPException(status_code=422, detail="Aadhaar must be 12 digits.")
        out["aadhaar"] = aadhaar

    for field, limit in (("passport", 40), ("driving_license", 40)):
        out[field] = clean_text(payload.get(field), limit=limit)

    dob = clean_text(payload.get("date_of_birth"), limit=10)
    if dob:
        if not is_iso_date(dob):
            raise HTTPException(
                status_code=422,
                detail="Date of birth must be a valid date in YYYY-MM-DD format.")
        if dob >= datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            raise HTTPException(status_code=422, detail="Date of birth must be in the past.")
        out["date_of_birth"] = dob

    gender = payload.get("gender")
    gender = getattr(gender, "value", gender)
    if gender:
        try:
            out["gender"] = Gender(gender).value
        except ValueError:
            raise HTTPException(status_code=422, detail="Unknown value for gender.")

    ifsc = (payload.get("bank_ifsc") or "").strip().upper()
    if ifsc:
        if not IFSC_RE.match(ifsc):
            raise HTTPException(
                status_code=422, detail="IFSC code is not valid (e.g. HDFC0001234).")
        out["bank_ifsc"] = ifsc

    account = (payload.get("bank_account") or "").strip()
    if account:
        if not account.isdigit() or not (6 <= len(account) <= 20):
            raise HTTPException(
                status_code=422, detail="Bank account number must be 6-20 digits.")
        out["bank_account"] = account

    for field, limit in (("address", 500), ("bank_name", 120),
                         ("emergency_contact_name", 120),
                         ("emergency_contact_phone", 30),
                         ("emergency_contact_relation", 60),
                         ("asset_requirements", 1000)):
        out[field] = clean_text(payload.get(field), limit=limit)

    references = payload.get("references") or []
    if len(references) > MAX_REFERENCES:
        raise HTTPException(
            status_code=422,
            detail=f"A maximum of {MAX_REFERENCES} references can be provided.")
    out["references"] = [
        {"name": clean_text((r or {}).get("name"), limit=120),
         "relation": clean_text((r or {}).get("relation"), limit=80),
         "phone": clean_text((r or {}).get("phone"), limit=30)}
        for r in references
        if isinstance(r, dict) and clean_text(r.get("name"), limit=120)
    ]
    return out


async def submit_public_onboarding(code: str, payload: dict) -> dict:
    """Record the new hire's pre-onboarding submission."""
    doc = await get_collection(COLL_ONBOARDING).find_one({"access_code": code})
    if not doc:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if doc.get("status") == OnboardStatus.COMPLETED.value:
        raise HTTPException(status_code=410, detail="This form is closed.")
    if doc.get("pre_status") != PreOnboardStatus.PENDING.value:
        # Re-submitting would overwrite details a human has already verified.
        raise HTTPException(
            status_code=409,
            detail="Your details have already been submitted. Contact the HR team if "
                   "something needs to change.")

    details = _validate_submission(payload)
    stored = await _store_documents(payload.get("documents") or [],
                                    existing_count=len(doc.get("documents") or []),
                                    source="candidate")

    now = datetime.now(timezone.utc)
    # Conditioned on Pending so two rapid submits cannot both write.
    result = await get_collection(COLL_ONBOARDING).update_one(
        {"access_code": code, "pre_status": PreOnboardStatus.PENDING.value},
        {"$set": {"submission": details,
                  "pre_status": PreOnboardStatus.SUBMITTED.value,
                  "submitted_at": now,
                  "asset_requirements": details.get("asset_requirements")
                  or doc.get("asset_requirements"),
                  "updated_at": now},
         "$push": {"documents": {"$each": stored}}})
    if getattr(result, "matched_count", 0) == 0:
        raise HTTPException(
            status_code=409, detail="Your details have already been submitted.")

    company_id = doc.get("company_id")
    await audit(None, AUDIT_ONBOARD_SUBMITTED, ENTITY_ONBOARDING, doc["onb_no"],
                doc.get("candidate_name"), company_id)
    await notify_hrms_role(
        company_id, ["HR"], f"Pre-onboarding submitted: {doc.get('candidate_name')}",
        f"{doc['onb_no']} — their details and {len(stored)} document(s) are ready to verify.",
        link="/hrms/onboarding", email=True)
    if doc.get("created_by"):
        await notify_user(
            doc["created_by"], f"Pre-onboarding submitted: {doc.get('candidate_name')}",
            f"{doc['onb_no']} is ready to verify.", link="/hrms/onboarding")

    return {
        "ok": True,
        "message": "Thank you — your details have been received. The HR team will verify "
                   "them and be in touch before your joining date.",
    }
