"""HRMS > candidate pipeline, screening and journey.

The working surface for everyone who applied through Phase 4, plus the manual additions
(walk-ins, referrals, agency CVs) that never touch a public form.

-- One status field, and a real state machine ---------------------------------------
The source carried BOTH a modern `application_status` and legacy numbered step columns
(`status_6`, `status_10`, ...), kept loosely in sync by different modules -- two sources of
truth for the same fact (BACKEND_ANALYSIS Risk #7). Here there is exactly one field.

More importantly, the source validated NO transitions: any status could be assigned to any
other, so a candidate could jump Applied -> Joined and skip assessment, interviews, offer
and onboarding entirely. Every later phase then had to defend against states that cannot
legitimately exist. Here every move is checked against FORWARD_TRANSITIONS and an illegal
one is a 409, not silent corruption.

-- Row scoping ----------------------------------------------------------------------
  HR / MD / ADMIN     every candidate in the company
  INTERNAL            every candidate (support), but cannot screen -- screening is a
                      hiring decision, and those belong to the client (same boundary the
                      approval chain draws in Phase 3)
  MANAGER (HOD)       only candidates on requisitions THEY raised
  EMPLOYEE            403 -- no candidate access at all
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_ASSIGNED, AUDIT_CANDIDATE_ADDED, AUDIT_CANDIDATE_DELETED, AUDIT_CANDIDATE_UPDATED,
    AUDIT_SCREENED, AUDIT_STAGE_CHANGED, COLL_AUDIT_LOG, COLL_CANDIDATES, COLL_REQUISITIONS,
    EMAIL_RE, ENTITY_CANDIDATE, JOURNEY_KINDS, JOURNEY_RAIL, JOURNEY_STATUS_KINDS,
    MAX_BULK_SCREEN, PHONE_RE, PIPELINE_COLUMNS, SCREEN_ACTIONS, AppStatus, Cap, HrmsRole,
    ScreenAction, allowed_next_statuses, can_transition,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.services.hrms_notify_service import notify_user
from app.utils.hrms_access import can, hrms_role
from app.utils.hrms_public_guard import clean_text


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_name(actor: dict) -> str:
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


# -------------------------------------------------------------
# Scoping
# -------------------------------------------------------------
async def _scope_filter(actor: dict, company_id: str) -> dict:
    """Extra query clause limiting which candidates `actor` may see.

    A hiring manager sees the pipeline for requisitions they raised and nothing else. If
    they have raised none, the filter matches nothing rather than everything -- a scoping
    gap must fail closed.
    """
    if hrms_role(actor) != HrmsRole.MANAGER:
        return {}
    rows = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id), "created_by": str(actor.get("_id") or "")},
        {"request_no": 1}).to_list(2000)
    return {"request_no": {"$in": [r["request_no"] for r in rows]}}


async def _require_visible(actor: dict, company_id: str, uk: str) -> dict:
    """Fetch a candidate the actor is allowed to see, or 404.

    404 rather than 403 for an out-of-scope row: a 403 would confirm the record exists.
    """
    query = {"uk": uk, "company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    doc = await get_collection(COLL_CANDIDATES).find_one(query)
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    return doc


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_candidates(actor: dict, company_id: str, *, search: str = None,
                          status: str = None, request_no: str = None,
                          posting_code: str = None, limit: int = 200,
                          skip: int = 0) -> dict:
    query = {"company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    if status:
        query["application_status"] = status
    if request_no:
        query["request_no"] = request_no
    if posting_code:
        query["posting_code"] = posting_code
    if search:
        import re
        safe = re.escape(search.strip())
        query["$and"] = [{"$or": [
            {"candidate_name": {"$regex": safe, "$options": "i"}},
            {"uk": {"$regex": safe, "$options": "i"}},
            {"can_email": {"$regex": safe, "$options": "i"}},
            {"can_contact": {"$regex": safe, "$options": "i"}},
        ]}]

    coll = get_collection(COLL_CANDIDATES)
    total = await coll.count_documents(query)
    limit = max(1, min(int(limit or 200), 500))
    rows = await coll.find(query).sort("created_at", -1).skip(
        max(0, int(skip or 0))).limit(limit).to_list(limit)

    candidates = [_out(r) for r in rows]
    flag_duplicates(candidates)

    # Column counts come from the same scoped query as the rows, so the board totals can
    # never disagree with what the user can actually open.
    base = {k: v for k, v in query.items() if k not in ("application_status",)}
    columns = []
    for key, label, statuses in PIPELINE_COLUMNS:
        values = [s.value for s in statuses]
        columns.append({
            "key": key, "label": label, "statuses": values,
            "count": await coll.count_documents({**base, "application_status": {"$in": values}}),
        })

    return {"candidates": candidates, "total": total, "limit": limit, "skip": skip,
            "columns": columns}


def normalise_phone(value: str) -> str:
    """Reduce a phone number to a comparable key.

    Strips formatting, then keeps the LAST 10 digits when there are at least that many.
    '+91 98765 43210', '098765 43210' and '9876543210' are one person in India, and this
    module is India-specific throughout (PAN, Aadhaar, IFSC, UAN, PF/ESI, IST, rupees), so
    matching on the subscriber number is the behaviour that actually catches duplicates.

    Shorter strings are compared whole, so a 6-digit extension is never truncated into a
    false match with another.
    """
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def flag_duplicates(candidates: list) -> None:
    """Mark candidates sharing a normalised email or phone with another in the same result.

    Advisory only -- it flags, it never merges or blocks. Two people can legitimately share
    a household phone, and an automatic merge would destroy a real application.
    """
    seen_email, seen_phone = {}, {}
    for c in candidates:
        email = (c.get("can_email") or "").strip().lower()
        phone = normalise_phone(c.get("can_contact"))
        if email:
            seen_email.setdefault(email, []).append(c)
        if phone:
            seen_phone.setdefault(phone, []).append(c)
    for group in list(seen_email.values()) + list(seen_phone.values()):
        if len(group) > 1:
            for c in group:
                c["duplicate_flag"] = True


async def get_candidate(actor: dict, company_id: str, uk: str) -> dict:
    doc = await _require_visible(actor, company_id, uk)
    out = _out(doc)
    out["allowed_next"] = sorted(s.value for s in allowed_next_statuses(
        out.get("application_status") or AppStatus.APPLIED.value))
    return out


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def create_candidate(actor: dict, company_id: str, payload: dict) -> dict:
    """Add a candidate by hand (walk-in, referral, agency CV)."""
    name = clean_text(payload.get("candidate_name"), limit=140)
    if not name:
        raise HTTPException(status_code=422, detail="Candidate name is required.")

    email = clean_text(payload.get("can_email"), limit=180)
    phone = clean_text(payload.get("can_contact"), limit=30)
    if email:
        email = email.lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if phone and not PHONE_RE.match(phone):
        raise HTTPException(status_code=422, detail="Enter a valid phone number.")
    if not email and not phone:
        raise HTTPException(
            status_code=422,
            detail="Provide at least an email address or a phone number.")

    request_no = payload.get("request_no")
    req = None
    if request_no:
        req = await get_collection(COLL_REQUISITIONS).find_one(
            {"request_no": request_no, "company_id": str(company_id)})
        if not req:
            raise HTTPException(
                status_code=422, detail="That requisition does not exist for this company.")

    year = datetime.now(timezone.utc).year
    uk = await next_business_id("candidate", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "uk": uk,
        "company_id": str(company_id),
        "candidate_name": name,
        "can_email": email,
        "can_contact": phone,
        "source": clean_text(payload.get("source"), limit=60) or "Manual",
        "request_no": request_no,
        "jd_no": (req or {}).get("jd_no"),
        "application_status": AppStatus.APPLIED.value,
        # A manually-added candidate inherits the requisition's assessment requirement, so
        # they are gated identically to someone who applied through a posting.
        "requires_assessment": False,
        "created_by": str(actor.get("_id") or ""),
        "created_at": now,
        "applied_at": now,
    }
    for field, limit in (("current_location", 120), ("total_experience", 60),
                         ("qualification", 180), ("current_company", 140),
                         ("current_ctc", 40), ("expected_ctc", 40),
                         ("notice_period", 60), ("linkedin", 300), ("cover_note", 4000)):
        doc[field] = clean_text(payload.get(field), limit=limit)

    if request_no:
        posting = await get_collection("hrms_job_postings").find_one(
            {"request_no": request_no, "company_id": str(company_id)})
        if posting:
            doc["requires_assessment"] = bool(posting.get("requires_assessment"))

    await get_collection(COLL_CANDIDATES).insert_one(dict(doc))
    await audit(actor, AUDIT_CANDIDATE_ADDED, ENTITY_CANDIDATE, uk,
                f"{name} added manually", company_id)
    return await get_candidate(actor, company_id, uk)


async def update_candidate(actor: dict, company_id: str, uk: str, payload: dict) -> dict:
    """Edit a candidate, including moving their stage.

    A stage move is validated against the lifecycle graph. Everything else is plain field
    editing.
    """
    current = await _require_visible(actor, company_id, uk)
    updates = {}

    for field, limit in (("candidate_name", 140), ("current_location", 120),
                         ("total_experience", 60), ("qualification", 180),
                         ("current_company", 140), ("current_ctc", 40),
                         ("expected_ctc", 40), ("notice_period", 60),
                         ("linkedin", 300), ("cover_note", 4000), ("remarks", 2000)):
        if field in payload:
            updates[field] = clean_text(payload[field], limit=limit)

    if "can_email" in payload:
        email = clean_text(payload["can_email"], limit=180)
        if email:
            email = email.lower()
            if not EMAIL_RE.match(email):
                raise HTTPException(status_code=422, detail="Enter a valid email address.")
        updates["can_email"] = email
    if "can_contact" in payload:
        phone = clean_text(payload["can_contact"], limit=30)
        if phone and not PHONE_RE.match(phone):
            raise HTTPException(status_code=422, detail="Enter a valid phone number.")
        updates["can_contact"] = phone

    if payload.get("assigned_recruiter_id") is not None:
        recruiter_id = payload["assigned_recruiter_id"]
        if recruiter_id:
            from bson import ObjectId
            from bson.errors import InvalidId
            try:
                oid = ObjectId(str(recruiter_id))
            except (InvalidId, TypeError):
                raise HTTPException(status_code=422, detail="Invalid recruiter.")
            person = await get_collection("learners").find_one(
                {"_id": oid, "company_id": str(company_id)},
                {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1})
            if not person:
                raise HTTPException(
                    status_code=422, detail="The recruiter must be a user of this company.")
            updates["assigned_recruiter_id"] = str(recruiter_id)
            updates["assigned_recruiter_name"] = (
                person.get("full_name")
                or f"{person.get('first_name') or ''} {person.get('last_name') or ''}".strip()
                or person.get("email"))
        else:
            updates["assigned_recruiter_id"] = None
            updates["assigned_recruiter_name"] = None

    # -- The stage move --
    stage_from = stage_to = None
    if payload.get("application_status") is not None:
        target = getattr(payload["application_status"], "value", payload["application_status"])
        current_status = current.get("application_status") or AppStatus.APPLIED.value
        if target != current_status:
            if not can_transition(current_status, target):
                legal = sorted(s.value for s in allowed_next_statuses(current_status))
                raise HTTPException(
                    status_code=409,
                    detail=(f'A candidate at "{current_status}" cannot move to "{target}". '
                            f'Allowed from here: {", ".join(legal) or "nothing - this stage is final"}.'))
            updates["application_status"] = target
            stage_from, stage_to = current_status, target

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_CANDIDATES).update_one(
        {"uk": uk, "company_id": str(company_id)}, {"$set": updates})

    if stage_to:
        # A dedicated audit line -- the journey timeline is reconstructed from these, so a
        # stage move must be distinguishable from an ordinary field edit.
        await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                    f"{stage_from} -> {stage_to}", company_id)
    other = sorted(k for k in updates if k not in ("updated_at", "application_status"))
    if other:
        await audit(actor, AUDIT_CANDIDATE_UPDATED, ENTITY_CANDIDATE, uk,
                    ", ".join(other), company_id)
    if updates.get("assigned_recruiter_id"):
        await notify_user(
            updates["assigned_recruiter_id"],
            f"You were assigned {current.get('candidate_name')}",
            f"{_actor_name(actor)} assigned you this candidate ({uk}).",
            link="/hrms/candidates")
        await audit(actor, AUDIT_ASSIGNED, ENTITY_CANDIDATE, uk,
                    updates.get("assigned_recruiter_name"), company_id)

    return await get_candidate(actor, company_id, uk)


async def delete_candidate(actor: dict, company_id: str, uk: str) -> dict:
    current = await _require_visible(actor, company_id, uk)
    if current.get("application_status") in (
            AppStatus.OFFER_ACCEPTED.value, AppStatus.PRE_ONBOARDING.value,
            AppStatus.JOINED.value, AppStatus.EMPLOYEE_CREATED.value):
        raise HTTPException(
            status_code=409,
            detail=("This candidate has an accepted offer or has joined - their record is "
                    "part of the hiring history. Mark them Rejected instead of deleting."))
    await get_collection(COLL_CANDIDATES).delete_one(
        {"uk": uk, "company_id": str(company_id)})
    await audit(actor, AUDIT_CANDIDATE_DELETED, ENTITY_CANDIDATE, uk,
                current.get("candidate_name"), company_id)
    return {"deleted": True, "uk": uk}


# -------------------------------------------------------------
# Screening
# -------------------------------------------------------------
async def screen_candidates(actor: dict, company_id: str, payload: dict) -> dict:
    """Apply one screening action to a batch of candidates.

    Partial success is deliberate: a batch of 50 where 3 are at an incompatible stage should
    move the 47 and report the 3, not fail wholesale and leave the recruiter to work out
    which ones blocked it.
    """
    uks = [u for u in (payload.get("uks") or []) if u]
    if not uks:
        raise HTTPException(status_code=422, detail="Select at least one candidate.")
    if len(uks) > MAX_BULK_SCREEN:
        raise HTTPException(
            status_code=422,
            detail=f"You can screen at most {MAX_BULK_SCREEN} candidates at once.")

    raw_action = getattr(payload.get("action"), "value", payload.get("action"))
    try:
        action = ScreenAction(raw_action)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid action. Expected one of: {', '.join(a.value for a in ScreenAction)}.")

    target, remark_required, recipient_required = SCREEN_ACTIONS[action]
    remarks = clean_text(payload.get("remarks"), limit=2000)
    if remark_required and not remarks:
        raise HTTPException(
            status_code=422, detail="A reason is required when rejecting a candidate.")

    recipient = None
    if recipient_required:
        recipient_id = payload.get("forward_to_id")
        if not recipient_id:
            raise HTTPException(status_code=422, detail="Choose who to forward to.")
        from bson import ObjectId
        from bson.errors import InvalidId
        try:
            oid = ObjectId(str(recipient_id))
        except (InvalidId, TypeError):
            raise HTTPException(status_code=422, detail="Invalid recipient.")
        recipient = await get_collection("learners").find_one(
            {"_id": oid, "company_id": str(company_id)},
            {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1})
        if not recipient:
            raise HTTPException(
                status_code=422, detail="You can only forward to a user of your own company.")

    coll = get_collection(COLL_CANDIDATES)
    scope = await _scope_filter(actor, company_id)
    now = datetime.now(timezone.utc)
    moved, skipped = [], []

    for uk in uks:
        query = {"uk": uk, "company_id": str(company_id), **scope}
        doc = await coll.find_one(query)
        if not doc:
            skipped.append({"uk": uk, "reason": "not found"})
            continue

        current_status = doc.get("application_status") or AppStatus.APPLIED.value
        updates = {"updated_at": now}

        if action is ScreenAction.FORWARD:
            # Forwarding is an assignment, not a stage move -- the candidate stays exactly
            # where they are and simply gains an owner.
            name = (recipient.get("full_name")
                    or f"{recipient.get('first_name') or ''} {recipient.get('last_name') or ''}".strip()
                    or recipient.get("email"))
            updates["assigned_recruiter_id"] = str(recipient["_id"])
            updates["assigned_recruiter_name"] = name
            await coll.update_one(query, {"$set": updates})
            moved.append({"uk": uk, "status": current_status, "assigned_to": name})
            await audit(actor, AUDIT_SCREENED, ENTITY_CANDIDATE, uk,
                        f"forwarded to {name}", company_id)
            continue

        # `shortlist` resolves by the role's assessment requirement -- the whole reason the
        # flag was copied onto the candidate at apply time (Phase 4).
        if action is ScreenAction.SHORTLIST:
            resolved = (AppStatus.ASSESSMENT_PENDING if doc.get("requires_assessment")
                        else AppStatus.SHORTLISTED)
            # From Applied/Under Review the legal first step is Shortlisted; only once there
            # can the assessment edge be taken. Do it in one hop when the graph allows, and
            # in two when it does not, so the recorded history stays legal.
            if resolved is AppStatus.ASSESSMENT_PENDING and not can_transition(
                    current_status, AppStatus.ASSESSMENT_PENDING.value):
                if can_transition(current_status, AppStatus.SHORTLISTED.value):
                    await coll.update_one(query, {"$set": {
                        "application_status": AppStatus.SHORTLISTED.value, "updated_at": now}})
                    await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                                f"{current_status} -> {AppStatus.SHORTLISTED.value}", company_id)
                    current_status = AppStatus.SHORTLISTED.value
            target_status = resolved.value
        else:
            target_status = target.value

        if current_status == target_status:
            skipped.append({"uk": uk, "reason": f"already {target_status}"})
            continue
        if not can_transition(current_status, target_status):
            skipped.append({
                "uk": uk,
                "reason": f'cannot move from "{current_status}" to "{target_status}"'})
            continue

        updates["application_status"] = target_status
        if remarks:
            updates["screening_remarks"] = remarks
        await coll.update_one(query, {"$set": updates})
        moved.append({"uk": uk, "status": target_status})
        await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                    f"{current_status} -> {target_status}", company_id)
        await audit(actor, AUDIT_SCREENED, ENTITY_CANDIDATE, uk,
                    f"{action.value}" + (f": {remarks}" if remarks else ""), company_id)

    if action is ScreenAction.FORWARD and moved and recipient:
        await notify_user(
            str(recipient["_id"]),
            f"{len(moved)} candidate(s) forwarded to you",
            f"{_actor_name(actor)} forwarded {len(moved)} candidate(s) for your review."
            + (f" Note: {remarks}" if remarks else ""),
            link="/hrms/candidates")

    return {"moved": moved, "skipped": skipped,
            "moved_count": len(moved), "skipped_count": len(skipped)}


# -------------------------------------------------------------
# Journey
# -------------------------------------------------------------
async def get_journey(actor: dict, company_id: str, uk: str) -> dict:
    """Reconstruct a candidate's full history from the audit trail.

    This is the ONLY read path over the audit log that a normal user reaches, and it is why
    every write since Phase 1 has been audited with a stable action name and entity id.
    """
    candidate = await _require_visible(actor, company_id, uk)
    status = candidate.get("application_status") or AppStatus.APPLIED.value

    rows = await get_collection(COLL_AUDIT_LOG).find(
        {"entity": ENTITY_CANDIDATE, "entity_id": uk}).sort("created_at", 1).to_list(500)

    events = []
    for r in rows:
        action = r.get("action") or ""
        detail = r.get("detail") or ""
        kind = JOURNEY_KINDS.get(action, "info")
        # A stage change is coloured by the stage it ARRIVED at, not by the action name --
        # "stage changed" alone tells a reader nothing.
        if action == AUDIT_STAGE_CHANGED and "->" in detail:
            arrived = detail.split("->")[-1].strip()
            try:
                kind = JOURNEY_STATUS_KINDS.get(AppStatus(arrived), kind)
            except ValueError:
                pass
        events.append({
            "at": r.get("created_at"),
            "title": action,
            "detail": detail or None,
            "actor": r.get("actor_name"),
            "kind": kind,
        })

    # If nothing was audited (legacy data, or an import), synthesise a start anchor so the
    # timeline is never blank for a candidate who demonstrably exists.
    if not events:
        events.append({
            "at": candidate.get("applied_at") or candidate.get("created_at"),
            "title": "Applied", "detail": candidate.get("source"),
            "actor": None, "kind": "applied",
        })

    reached, rail = -1, []
    for i, (label, statuses) in enumerate(JOURNEY_RAIL):
        try:
            is_here = AppStatus(status) in statuses
        except ValueError:
            is_here = False
        if is_here:
            reached = i
        rail.append({"label": label, "current": is_here})
    for i, step in enumerate(rail):
        step["reached"] = i <= reached

    return {
        "candidate": {
            "uk": candidate["uk"],
            "name": candidate.get("candidate_name"),
            "status": status,
            "source": candidate.get("source"),
            "request_no": candidate.get("request_no"),
            "applied_at": candidate.get("applied_at") or candidate.get("created_at"),
        },
        "rail": rail,
        "reached": reached,
        # A terminal stage means the rail stops here -- the UI shows why rather than
        # implying more steps are coming.
        "terminal": not allowed_next_statuses(status),
        "events": events,
    }
