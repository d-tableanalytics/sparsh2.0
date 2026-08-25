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
    ScreenAction, allowed_next_statuses, can_transition, is_iso_date,
)
from app.models.hrms import (
    AUDIT_CLIENT_RESPONSE, AUDIT_CLIENT_SHARED, CLIENT_RESPONSE_STATUS, ClientShareStatus,
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


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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
                          posting_code: str = None, talent_pool: bool = None,
                          tags: str = None, limit: int = 200,
                          skip: int = 0) -> dict:
    query = {"company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    if status:
        query["application_status"] = status
    if request_no:
        query["request_no"] = request_no
    if posting_code:
        query["posting_code"] = posting_code
    # ── Phase INT-2 (Annexure C) ── sourcing against a new requisition. The pool is a FILTER
    # on the candidate list rather than a collection of its own: a pooled candidate is still
    # a candidate, with the same scoping, the same row security and the same retention.
    if talent_pool is not None:
        query["talent_pool"] = bool(talent_pool)
    if tags:
        # Lower-cased to match how they are STORED. Both ends normalise, so a search for
        # "Python" finds a CV tagged "python" -- which is the only behaviour a recruiter
        # typing into a box would expect.
        wanted = [t.strip().lower() for t in str(tags).split(",") if t.strip()]
        if wanted:
            # ANY of the tags, not all: a recruiter looking for "python, django" wants
            # everybody who matches either, and narrowing to the intersection would hide
            # most of the pool behind a search that looks broader than it is.
            query["talent_pool_tags"] = {"$in": wanted}
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
        # ── Internal track ── putting a CV against a requisition IS sourcing, so the same
        # budget gate applies here as to publishing a posting (SOP §11). Enforced server-side
        # rather than by hiding a button: a walk-in CV entered by hand is exactly the route
        # that would otherwise slip past an unfunded requisition.
        from app.services.hrms_requisition_service import assert_sourcing_allowed
        assert_sourcing_allowed(req)

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
    # SOP §13: the disposal floor is stamped WHEN THE RECORD IS CREATED, not when somebody
    # later remembers. The purge proposes nothing for a row with no `retention_until`
    # (deliberately -- an absent date means nobody computed one), so a CV that never gets
    # this stamp is a CV kept forever.
    doc["retention_until"] = candidate_retention_until(
        doc, await _retention_map(company_id))
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

    # Phase 11-R, Item 5: the SAME referral resolver the public form uses. A referral HR
    # types onto a walk-in CV is validated and stored identically to a self-declared one,
    # so the referral reporting counts one kind of thing.
    # `source_from_applicant=False`: there is no applicant to ask here. HR chose the source
    # from the CV in front of them and that choice stands -- but a declared referral still
    # files as one, exactly as it does on the public form.
    from app.services.hrms_referral_service import resolve_referral
    doc.update(await resolve_referral(payload, company_id, source_from_applicant=False))

    await get_collection(COLL_CANDIDATES).insert_one(dict(doc))
    await audit(actor, AUDIT_CANDIDATE_ADDED, ENTITY_CANDIDATE, uk,
                f"{name} added manually", company_id)

    if doc.get("referrer_user_id"):
        from app.services.hrms_referral_service import notify_referrer
        await notify_referrer(
            doc, "Your referral was added",
            f"{name}, whom you referred, has been added to the hiring pipeline.")

    return await get_candidate(actor, company_id, uk)


# ─────────────────────────────────────────────────────────────
# Phase INT-2 — the two gates on `Selected` (SOP §5)
# ─────────────────────────────────────────────────────────────
async def assert_selectable(actor: Optional[dict], company_id: str,
                            candidate: dict) -> None:
    """Refuse to select an internal candidate the SOP's two §5 controls have not cleared.

    ONE function, called from every path that can reach `Selected`: the hand-set stage move
    here, the interview pass-chain, and offer creation. Three copies of a gate is one gate
    and two bugs waiting to drift out of step -- the same reasoning that keeps
    `assert_sourcing_allowed` in a single place.

    Both checks return immediately on a client requisition, so the agency track is
    untouched: a client-track candidate reaches Selected exactly as they always did.
    """
    request_no = (candidate or {}).get("request_no")
    if not request_no:
        return
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if not req:
        return

    # The shortlisting committee (SOP §5): HR and the HOD agreed this person goes forward.
    from app.services.hrms_shortlist_service import assert_shortlist_cleared
    await assert_shortlist_cleared(company_id, candidate, req)
    # The mandatory Management final round for managerial+ roles (SOP §5).
    from app.services.hrms_interview_service import assert_final_round_complete
    await assert_final_round_complete(company_id, candidate, req)


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
            # ── Phase INT-2 ── the two gates on `Selected` (SOP §5). Applied HERE as well
            # as on the offer, because this is the hand-set path: without it, typing
            # "Selected" onto a candidate would route around both controls and the offer
            # gate would find a status it had no reason to doubt.
            #
            # Both are silent on the client track, and both are checked BEFORE anything is
            # written so a refusal cannot leave a half-moved candidate behind.
            if target == AppStatus.SELECTED.value:
                await assert_selectable(actor, company_id, current)
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
        # Phase 11-R, Item 5: the referrer hears about the two milestones that matter to
        # them -- selection and joining -- and nothing else.
        from app.services.hrms_referral_service import notify_referral_milestone
        await notify_referral_milestone(current, stage_to)
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


# ─────────────────────────────────────────────────────────────
# Phase INT-2 — the talent pool (Annexure C) and record retention (SOP §13)
# ─────────────────────────────────────────────────────────────
def _add_years(iso_date: str, years: int) -> str:
    """`iso_date` plus N years, clamped for 29 February. Pure."""
    try:
        y, m, d = (int(p) for p in str(iso_date)[:10].split("-"))
    except (ValueError, TypeError):
        return iso_date
    if m == 2 and d == 29:
        d = 28
    return f"{y + years:04d}-{m:02d}-{d:02d}"


async def _retention_map(company_id: str) -> dict:
    """This company's retention table (INT-5 overlay over RETENTION_YEARS).

    Never raises: a settings row that cannot be read must not stop a CV being saved, and the
    module defaults are the correct answer when there are no overrides. Returning None here
    instead would leave `candidate_retention_until` to fall back on its own default, which
    is the same table -- but silently, and this is a rule worth failing loudly about only in
    the logs.
    """
    try:
        from app.services.hrms_config_service import config_for
        return (await config_for(company_id))["retention_years"]
    except Exception as e:
        from app.models.hrms import RETENTION_YEARS
        print(f"[WARN] HRMS retention config unavailable for {company_id}: {e}")
        return RETENTION_YEARS


def candidate_retention_until(candidate: dict, years_map: dict = None) -> Optional[str]:
    """The date this CV may be considered for disposal (SOP §13). Pure.

    A FLOOR, not a purge date -- nothing in this function deletes anything, and the purge
    job asks a human before it acts on the answer.

    Two figures, because the SOP gives two. A candidate who JOINED is kept for three years
    from joining and then lives on in the personnel file; everybody else is kept for one
    year from their application. The distinction matters here more than anywhere else in the
    module, because it is the ceiling the talent pool's consent may not exceed.
    """
    from app.models.hrms import RETENTION_YEARS
    years_map = RETENTION_YEARS if years_map is None else years_map
    status = (candidate or {}).get("application_status")
    selected = status in (AppStatus.JOINED.value, AppStatus.EMPLOYEE_CREATED.value)
    anchor = (candidate.get("joined_at") if selected else None) \
        or candidate.get("applied_at") or candidate.get("created_at")
    if hasattr(anchor, "strftime"):
        anchor = anchor.strftime("%Y-%m-%d")
    if not anchor:
        return None
    years = years_map["candidate_selected" if selected else "candidate_unselected"]
    return _add_years(str(anchor)[:10], years)


async def set_talent_pool(actor: dict, company_id: str, uk: str, payload: dict) -> dict:
    """Add a candidate to the talent pool, or take them out of it.

    -- Consent is the whole control ---------------------------------------------------
    A candidate enters the pool ONLY with explicit consent. Keeping a CV to consider for a
    future role is a different act from keeping it to process one application, and only the
    candidate can agree to the second. There is deliberately no path that opts somebody in
    because a recruiter found their profile useful.

    -- Consent may not outlive retention ---------------------------------------------
    `consent_expires_at` is capped at the candidate's `retention_until`. Retaining a CV past
    its retention period BECAUSE it is "in the pool" is exactly the compliance failure SOP
    §11 and §13 exist to prevent: the pool would become a way of quietly making a one-year
    record permanent. A caller asking for longer is refused rather than silently clamped --
    a promise the module cannot keep should be visible at the moment it is made.
    """
    from app.models.hrms import (
        AUDIT_TALENT_POOL_ADDED, AUDIT_TALENT_POOL_REMOVED, MAX_TALENT_POOL_TAGS,
    )
    current = await _require_visible(actor, company_id, uk)
    now = datetime.now(timezone.utc)
    joining = bool(payload.get("talent_pool", True))

    if not joining:
        # Leaving is unconditional and immediate. Consent is a thing somebody may withdraw,
        # and asking them to justify it would be the wrong shape entirely.
        await get_collection(COLL_CANDIDATES).update_one(
            {"uk": uk, "company_id": str(company_id)},
            {"$set": {"talent_pool": False, "talent_pool_tags": [],
                      "talent_pool_removed_at": now, "updated_at": now}})
        await audit(actor, AUDIT_TALENT_POOL_REMOVED, ENTITY_CANDIDATE, uk,
                    clean_text(payload.get("remarks"), limit=500) or "removed on request",
                    company_id)
        return await get_candidate(actor, company_id, uk)

    # Consent recorded on the application form counts; so does consent given later and
    # recorded here. What does not count is its absence.
    consented = bool(payload.get("consent_to_retain")) or bool(
        current.get("consent_to_retain"))
    if not consented:
        raise HTTPException(
            status_code=422,
            detail=(f'{current.get("candidate_name")} has not consented to their CV being '
                    f"kept for future roles. The talent pool needs explicit consent -- "
                    f"keeping a CV to consider later is a different thing from keeping it "
                    f"to process one application."))

    from app.services.hrms_config_service import config_for
    retention_until = candidate_retention_until(
        current, (await config_for(company_id))["retention_years"])
    expires = payload.get("consent_expires_at") or retention_until
    if expires and not is_iso_date(expires):
        raise HTTPException(
            status_code=422,
            detail="The consent expiry must be a valid YYYY-MM-DD date.")
    if expires and retention_until and expires > retention_until:
        raise HTTPException(
            status_code=422,
            detail=(f"Consent cannot outlive the retention period. This record may be kept "
                    f"until {retention_until}; being in the talent pool does not extend "
                    f"that. Ask again nearer the time if you want to keep the CV longer."))

    tags = [t for t in
            (clean_text(tag, limit=40) for tag in (payload.get("talent_pool_tags") or []))
            if t]
    if len(tags) > MAX_TALENT_POOL_TAGS:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_TALENT_POOL_TAGS} tags. Tags are for finding people, "
                   f"not for describing them exhaustively.")

    updates = {
        "talent_pool": True,
        "talent_pool_added_at": current.get("talent_pool_added_at") or now,
        "consent_to_retain": True,
        "consent_expires_at": expires,
        # Stamped now so the purge proposal can read one field rather than re-deriving the
        # rule per row. It is still a FLOOR: nothing deletes on this date by itself.
        "retention_until": retention_until,
        "updated_at": now,
    }
    # Tags are written only when the caller SENT some. A call that renews consent or fixes
    # an expiry date must not silently wipe the tags somebody spent time adding -- an
    # unconditional write here would make every partial update destructive.
    if payload.get("talent_pool_tags") is not None:
        # Stored LOWER-CASED, and de-duplicated by that. Tags exist to find people, and
        # Mongo's `$in` is case-sensitive -- so preserving whatever capitalisation somebody
        # happened to type would mean "Python" and "python" were two tags and a search for
        # one silently missed the other. Both ends normalise; see `list_candidates`.
        updates["talent_pool_tags"] = sorted({t.lower() for t in tags})
    await get_collection(COLL_CANDIDATES).update_one(
        {"uk": uk, "company_id": str(company_id)}, {"$set": updates})
    await audit(actor, AUDIT_TALENT_POOL_ADDED, ENTITY_CANDIDATE, uk,
                f'tags: {", ".join(updates.get("talent_pool_tags") or []) or "unchanged"}; '
                f"consent to {expires or 'unspecified'}", company_id)
    return await get_candidate(actor, company_id, uk)


async def create_from_pool(actor: dict, company_id: str, uk: str,
                           request_no: str) -> dict:
    """Bring a pooled candidate forward onto a NEW requisition.

    Copies the CV forward into a NEW candidate record. It deliberately does not re-point the
    old one, for two reasons that both matter:

      * the original application is a record of what somebody applied for and when, and
        moving it to a different vacancy would falsify that; and
      * every downstream record -- screening, interviews, the audit trail -- hangs off the
        candidate. Re-pointing would drag one requisition's history onto another's.

    The new record starts at `Applied` with its own uk, its own applied_at and its own
    retention clock. What is carried over is the CV and the contact details; nothing about
    how the previous process went, because that was a judgement about a different role.
    """
    source = await _require_visible(actor, company_id, uk)
    if not source.get("talent_pool"):
        raise HTTPException(
            status_code=409,
            detail=(f'{source.get("candidate_name")} is not in the talent pool. Only a '
                    f"candidate who consented to being kept for future roles can be "
                    f"brought forward."))

    expires = source.get("consent_expires_at")
    if expires and str(expires) < _today():
        raise HTTPException(
            status_code=409,
            detail=(f'{source.get("candidate_name")}\'s consent to be kept expired on '
                    f"{expires}. Ask them again before putting them forward."))

    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": request_no, "company_id": str(company_id)})
    if not req:
        raise HTTPException(
            status_code=422, detail="That requisition does not exist for this company.")
    # The budget gate applies to a pooled candidate exactly as it does to a fresh one:
    # sourcing is sourcing, whichever drawer the CV came out of.
    from app.services.hrms_requisition_service import assert_sourcing_allowed
    assert_sourcing_allowed(req)

    existing = await get_collection(COLL_CANDIDATES).find_one({
        "company_id": str(company_id), "request_no": request_no,
        "$or": [{"can_email": source.get("can_email")},
                {"can_contact": source.get("can_contact")}]})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(f'{source.get("candidate_name")} is already a candidate on '
                    f'{request_no} ({existing.get("uk")}).'))

    now = datetime.now(timezone.utc)
    new_uk = await next_business_id("candidate", str(company_id), now.year)
    doc = {
        "uk": new_uk,
        "company_id": str(company_id),
        "request_no": request_no,
        "jd_no": req.get("jd_no"),
        "posting_code": None,
        "candidate_name": source.get("candidate_name"),
        "can_email": source.get("can_email"),
        "can_contact": source.get("can_contact"),
        # The channel is the pool itself, stated plainly rather than inheriting the source
        # the person originally came through -- they did not answer an advert this time.
        "source": "Talent Pool",
        "sourced_from_uk": uk,
        "application_status": AppStatus.APPLIED.value,
        "requires_assessment": False,
        "current_location": source.get("current_location"),
        "total_experience": source.get("total_experience"),
        "qualification": source.get("qualification"),
        "current_company": source.get("current_company"),
        "current_ctc": source.get("current_ctc"),
        "expected_ctc": source.get("expected_ctc"),
        "notice_period": source.get("notice_period"),
        "linkedin": source.get("linkedin"),
        "resume": source.get("resume"),
        # The acknowledgements travel with the CV: they were given about this company's
        # handling of this person's data, not about one vacancy.
        "eeo_ack": source.get("eeo_ack"),
        "data_use_ack": source.get("data_use_ack"),
        "consent_to_retain": source.get("consent_to_retain"),
        "consent_expires_at": expires,
        "applied_at": now,
        "created_at": now,
        "created_by": str(actor.get("_id") or ""),
    }
    from app.services.hrms_config_service import config_for
    doc["retention_until"] = candidate_retention_until(
        doc, (await config_for(company_id))["retention_years"])
    await get_collection(COLL_CANDIDATES).insert_one(dict(doc))
    await audit(actor, AUDIT_CANDIDATE_ADDED, ENTITY_CANDIDATE, new_uk,
                f"brought forward from the talent pool ({uk}) onto {request_no}",
                company_id)
    return _out(doc)


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

        # Phase 11-R, Item 4: sharing a CV also OPENS a client-share record. The stage says
        # where the candidate is; the sub-document holds who it went to and what came back.
        # Written in the same update as the stage move, so the two can never disagree.
        if action is ScreenAction.SHARE_WITH_CLIENT:
            updates["client_share"] = {
                "shared_at": now,
                "shared_by": str(actor.get("_id") or ""),
                "shared_by_name": _actor_name(actor),
                "client_contact": clean_text(payload.get("client_contact"), limit=140),
                "status": ClientShareStatus.PENDING.value,
                "responded_at": None,
                "remarks": remarks,
            }
            # Denormalised alongside it so REPORT_ENTITIES and the breakdowns can read a
            # flat field -- reports project a fixed column list and cannot dig into a
            # sub-document.
            updates["client_share_status"] = ClientShareStatus.PENDING.value

        await coll.update_one(query, {"$set": updates})
        moved.append({"uk": uk, "status": target_status})

        # ── Internal track ── SOP §8 milestone 3: "shortlist ready for HOD review".
        # The FIRST shortlisting on a requisition is the moment a shortlist exists; every
        # later one adds to a list that is already ready, so `stamp_if_internal` records
        # only the first.
        if action is ScreenAction.SHORTLIST and doc.get("request_no"):
            from app.services.hrms_sla_service import stamp_if_internal
            await stamp_if_internal(actor, company_id, doc["request_no"],
                                    "shortlist_ready", when=now)

        await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                    f"{current_status} -> {target_status}", company_id)
        await audit(actor, AUDIT_SCREENED, ENTITY_CANDIDATE, uk,
                    f"{action.value}" + (f": {remarks}" if remarks else ""), company_id)

        # ── Phase INT-2 (Annexure C) ── communicate rejections. The SOP promises every
        # applicant a closure message and nothing sent one.
        #
        # Fired on `reject` specifically, and on no other screening action: this action
        # already REQUIRES remarks, which means the decision has been thought about and
        # written down. It is fire-and-forget -- a candidate must still be rejected if the
        # email cannot go out, and a batch of fifty must not half-fail on the tenth.
        if action is ScreenAction.REJECT:
            from app.services.hrms_comm_service import fire_event
            await fire_event(actor, company_id, uk, "screening_rejected")
        if action is ScreenAction.SHARE_WITH_CLIENT:
            # Its own audit action, so "we sent this CV out" is findable in the journey
            # without reading the prose of a generic screening line.
            await audit(actor, AUDIT_CLIENT_SHARED, ENTITY_CANDIDATE, uk,
                        clean_text(payload.get("client_contact"), limit=140)
                        or "shared with the client", company_id)

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
# Client sharing (Phase 11-R, Item 4)
# -------------------------------------------------------------
# The write path for client verdicts lives HERE, in the service that already owns screening,
# rather than in hrms_analytics_service. Analytics is read-only by contract and putting a
# write in it -- even a small one -- would end that guarantee for every future reader.
async def record_client_response(actor: dict, company_id: str, payload: dict) -> dict:
    """Record the hiring client's verdict on a CV that was shared with them.

    Recorded BY an HRMS user on the client's behalf: there is deliberately no public client
    portal in this phase. Building one would mean a second unauthenticated surface with its
    own credentials, rate limits and threat model, which is far more than the review asked
    for.

    The verdict drives the candidate's stage through CLIENT_RESPONSE_STATUS -- a lookup
    table, not a branch -- and FORWARD_TRANSITIONS still decides legality, so a verdict can
    never move somebody somewhere the lifecycle forbids.
    """
    uk = (payload.get("uk") or "").strip()
    if not uk:
        raise HTTPException(status_code=422, detail="Select a candidate.")

    current = await _require_visible(actor, company_id, uk)
    share = current.get("client_share") or {}
    if not share.get("shared_at"):
        raise HTTPException(
            status_code=409,
            detail=(f"{current.get('candidate_name')}'s CV has not been shared with a "
                    f"client, so there is no verdict to record."))

    raw = getattr(payload.get("status"), "value", payload.get("status"))
    try:
        verdict = ClientShareStatus(raw)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Verdict must be one of: "
                   f"{', '.join(s.value for s in ClientShareStatus)}.")

    remarks = clean_text(payload.get("remarks"), limit=2000)
    if verdict is ClientShareStatus.REJECTED and not remarks:
        # Same rule a rejection carries everywhere else in this module: a refusal the
        # recruiter cannot explain to the candidate is not usable feedback.
        raise HTTPException(
            status_code=422, detail="Record the client's reason for rejecting.")

    now = datetime.now(timezone.utc)
    responded_at = payload.get("responded_at") or now
    updates = {
        "client_share.status": verdict.value,
        "client_share.responded_at": responded_at,
        "client_share.remarks": remarks,
        "client_share.recorded_by": str(actor.get("_id") or ""),
        "client_share_status": verdict.value,
        "updated_at": now,
    }

    # The stage move, if this verdict implies one and the graph permits it.
    target = CLIENT_RESPONSE_STATUS.get(verdict)
    stage_from = current.get("application_status")
    stage_to = None
    if target is not None and can_transition(stage_from, target.value):
        updates["application_status"] = target.value
        stage_to = target.value

    await get_collection(COLL_CANDIDATES).update_one(
        {"uk": uk, "company_id": str(company_id)}, {"$set": updates})

    await audit(actor, AUDIT_CLIENT_RESPONSE, ENTITY_CANDIDATE, uk,
                f"client verdict: {verdict.value}" + (f" — {remarks}" if remarks else ""),
                company_id)
    if stage_to:
        await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                    f"{stage_from} -> {stage_to}", company_id)

    # Tell whoever shared it. They are waiting on this answer and nobody watches a record
    # they were not told changed -- the gap Phase 3 closed for requisitions.
    if share.get("shared_by"):
        await notify_user(
            share["shared_by"],
            f"Client verdict: {current.get('candidate_name')} — {verdict.value}",
            f"The client responded on {uk}." + (f" Note: {remarks}" if remarks else ""),
            kind="success" if verdict is ClientShareStatus.SHORTLISTED else "info",
            link="/hrms/candidates")

    return await get_candidate(actor, company_id, uk)


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
            # ── Phase 11-R ── the referral and client-share context the journey screen
            # renders alongside the timeline. Read with `.get`, so a candidate created
            # before this phase simply reports nulls rather than breaking the view.
            "is_referral": bool(candidate.get("is_referral")),
            "referred_by": candidate.get("referred_by"),
            "referral_source": candidate.get("referral_source"),
            "referrer_name": candidate.get("referrer_name"),
            "referrer_employee_code": candidate.get("referrer_employee_code"),
            "referral_relation": candidate.get("referral_relation"),
            "client_share": candidate.get("client_share"),
        },
        "rail": rail,
        "reached": reached,
        # A terminal stage means the rail stops here -- the UI shows why rather than
        # implying more steps are coming.
        "terminal": not allowed_next_statuses(status),
        "events": events,
    }
