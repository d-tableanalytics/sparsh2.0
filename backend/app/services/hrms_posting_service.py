"""HRMS > job postings + public application intake.

Publishes an APPROVED job description to one or more channels, and receives the
applications that come back.

-- One posting row per platform ----------------------------------------------------
Publishing a JD to LinkedIn + Naukri + Career Page creates THREE rows, three codes and
three independently-countable application streams. Each row chooses its own destination:

  auto     -> the built-in public form at /apply/<posting_code>; applications enter the
              pipeline automatically.
  external -> the poster's own URL (a job board listing, a Google Form, ...). Applications
              made there NEVER reach this pipeline -- nothing writes them back. The UI says
              so explicitly rather than implying tracking it cannot do.

-- Application count is computed, never stored -------------------------------------
A stored counter drifts the moment a candidate is deleted, merged or moved. It is derived
from `hrms_candidates` on read, which cannot disagree with reality.
"""
import random
import string
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_APPLICATION, AUDIT_POSTING_CREATED, AUDIT_POSTING_DELETED, AUDIT_POSTING_UPDATED,
    COLL_CANDIDATES, COLL_JOB_DESCRIPTIONS, COLL_JOB_POSTINGS, COLL_REQUISITIONS,
    EMAIL_RE, ENTITY_CANDIDATE_APPLICATION, ENTITY_POSTING, MAX_CERTIFICATES, PHONE_RE,
    POSTING_CODE_RE, AppStatus, ApplyLinkMode, JdStatus, LiveStatus, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.services.hrms_notify_service import notify_hrms_role, notify_user
from app.utils.hrms_public_guard import (
    CLOSED_LINK, INVALID_LINK, clean_text, decode_upload, safe_filename,
)

# Two-letter prefix per platform, so a code hints at its channel without being guessable.
_PLATFORM_PREFIX = {
    "LinkedIn": "LI", "Naukri": "NK", "Indeed": "ID", "Foundit": "FN",
    "Apna": "AP", "Career Page": "CP", "Referral": "RF", "Manual": "MN",
}
_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _mint_code(platform: str) -> str:
    """Generate a posting code.

    `secrets` is used rather than `random` even though a posting code is a public
    identifier, not a secret: the source generated every id and access token with
    `Math.random()` (BACKEND_ANALYSIS Risk #12), and keeping one habit avoids the mistake of
    reaching for the weak generator when the value DOES need to be unguessable -- as the
    Phase 6/8/9 access codes will.
    """
    import secrets
    prefix = _PLATFORM_PREFIX.get(platform, "JB")
    body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    return f"{prefix}-{body}"


async def _unique_code(platform: str, preferred: str = None) -> str:
    """Resolve a posting code, honouring a client-previewed one when it is safe to.

    The UI shows the applicant link WHILE the form is being filled in, so the code the user
    copies must be the code that gets stored. A supplied code is accepted only if it matches
    the public pattern and is unused; otherwise the server mints its own and the client
    re-reads it from the response.
    """
    coll = get_collection(COLL_JOB_POSTINGS)
    if preferred:
        candidate = preferred.strip().upper()
        if POSTING_CODE_RE.match(candidate):
            if not await coll.find_one({"posting_code": candidate}):
                return candidate
    for _ in range(12):
        candidate = _mint_code(platform)
        if not await coll.find_one({"posting_code": candidate}):
            return candidate
    raise HTTPException(
        status_code=500,
        detail="Could not allocate a unique posting code. Please try again.")


async def _application_counts(codes: list) -> dict:
    """Applications per posting code, in one aggregation rather than N queries."""
    if not codes:
        return {}
    rows = await get_collection(COLL_CANDIDATES).aggregate([
        {"$match": {"posting_code": {"$in": codes}}},
        {"$group": {"_id": "$posting_code", "n": {"$sum": 1}}},
    ]).to_list(len(codes) + 10)
    return {r["_id"]: r["n"] for r in rows}


def _effective_status(doc: dict, today: str) -> str:
    """A posting past its expiry reads as Expired without needing a nightly job.

    The source computed expiry at read time too; the alternative is a scheduler this ERP
    does not have. The stored value is left alone so an operator can see what was set.
    """
    expiry = doc.get("expiry_date")
    if (doc.get("live_status") == LiveStatus.LIVE.value and expiry and expiry < today):
        return LiveStatus.EXPIRED.value
    return doc.get("live_status")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# -------------------------------------------------------------
# Authenticated side
# -------------------------------------------------------------
async def list_postings(actor: dict, company_id: str, *, jd_no: str = None,
                        live_status: str = None, search: str = None,
                        limit: int = 100) -> dict:
    query = {"company_id": str(company_id)}
    if jd_no:
        query["jd_no"] = jd_no
    if live_status:
        query["live_status"] = live_status
    if search:
        import re
        safe = re.escape(search.strip())
        query["$or"] = [
            {"posting_code": {"$regex": safe, "$options": "i"}},
            {"title": {"$regex": safe, "$options": "i"}},
            {"platform": {"$regex": safe, "$options": "i"}},
        ]

    limit = max(1, min(int(limit or 100), 200))
    rows = await get_collection(COLL_JOB_POSTINGS).find(query).sort(
        "created_at", -1).limit(limit).to_list(limit)

    counts = await _application_counts([r["posting_code"] for r in rows])
    today = _today()
    out = []
    for r in rows:
        item = _out(r)
        item["live_status"] = _effective_status(r, today)
        item["application_count"] = counts.get(r["posting_code"], 0)
        out.append(item)

    live = sum(1 for r in out if r["live_status"] == LiveStatus.LIVE.value)
    return {
        "postings": out,
        "total": len(out),
        "stats": {
            "live": live,
            "applications": sum(counts.values()),
            "channels": len({r["platform"] for r in out}),
        },
    }


async def create_postings(actor: dict, company_id: str, payload: dict) -> dict:
    """Publish an approved JD to one or more platforms."""
    jd_no = (payload.get("jd_no") or "").strip()
    if not jd_no:
        raise HTTPException(status_code=422, detail="Select a job description to publish.")

    jd = await get_collection(COLL_JOB_DESCRIPTIONS).find_one(
        {"jd_no": jd_no, "company_id": str(company_id)})
    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found.")
    if jd.get("status") != JdStatus.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=(f'Only an approved job description can be published. {jd_no} is '
                    f'"{jd.get("status")}" - it must clear HR review and MD approval first.'))

    links = payload.get("platform_links") or []
    if not links:
        raise HTTPException(status_code=422, detail="Select at least one platform.")

    expiry = payload.get("expiry_date")
    if expiry:
        if not is_iso_date(expiry):
            raise HTTPException(
                status_code=422, detail="Expiry date must be a valid date in YYYY-MM-DD format.")
        if expiry < _today():
            raise HTTPException(status_code=422, detail="Expiry date cannot be in the past.")

    # Validate EVERY link before writing ANY row, so a bad third platform cannot leave the
    # first two published. Without this the operation is partially applied on failure.
    prepared = []
    seen_platforms = set()
    for link in links:
        link = link if isinstance(link, dict) else link.model_dump()
        platform = getattr(link.get("platform"), "value", link.get("platform"))
        mode = getattr(link.get("apply_link_mode"), "value", link.get("apply_link_mode")) \
            or ApplyLinkMode.AUTO.value
        external = (link.get("external_url") or "").strip()

        if platform in seen_platforms:
            raise HTTPException(
                status_code=422, detail=f"{platform} is listed twice.")
        seen_platforms.add(platform)

        if mode == ApplyLinkMode.EXTERNAL.value:
            if not external:
                raise HTTPException(
                    status_code=422,
                    detail=(f"{platform}: enter the application link, or switch it to the "
                            f"generated form."))
            if not external.lower().startswith(("http://", "https://")):
                raise HTTPException(
                    status_code=422,
                    detail=f"{platform}: the application link must start with http:// or https://.")
        else:
            external = None
        prepared.append((platform, mode, external, link.get("code")))

    now = datetime.now(timezone.utc)
    docs = []
    for platform, mode, external, preferred in prepared:
        code = await _unique_code(platform, preferred)
        docs.append({
            "posting_code": code,
            "company_id": str(company_id),
            "jd_no": jd_no,
            "request_no": jd.get("request_no"),
            "title": jd.get("title"),
            "platform": platform,
            "apply_link_mode": mode,
            "external_url": external,
            "live_status": LiveStatus.LIVE.value,
            "expiry_date": expiry or None,
            "notes": clean_text(payload.get("notes")),
            "requires_assessment": bool(payload.get("requires_assessment")),
            "posted_by": str(actor.get("_id") or ""),
            "posting_date": now.strftime("%Y-%m-%d"),
            "created_at": now,
        })

    await get_collection(COLL_JOB_POSTINGS).insert_many([dict(d) for d in docs])

    # Phase 11-R, Item 1: register each AUTO posting's apply link.
    #
    # EXTERNAL postings are deliberately NOT registered. An external listing sends the
    # applicant to a job board or a Google Form; nothing ever writes those applications back
    # into this pipeline (see ApplyLinkMode.EXTERNAL), so there is no open to count and no
    # submission to consume. Registering one would put a row in the Link Manager promising
    # tracking that cannot exist -- the same honesty the posting UI already applies.
    from app.models.hrms import LinkKind
    from app.services.hrms_link_service import register_link
    for d in docs:
        if d["apply_link_mode"] != ApplyLinkMode.AUTO.value:
            continue
        await register_link(
            company_id=company_id, kind=LinkKind.APPLY, code=d["posting_code"],
            target_type="posting", target_id=d["posting_code"], actor=actor,
            candidate_name=None, request_no=d.get("request_no"),
            expires_at=d.get("expiry_date"))

    await audit(actor, AUDIT_POSTING_CREATED, ENTITY_POSTING, jd_no,
                f"{len(docs)} platform(s): {', '.join(d['platform'] for d in docs)}", company_id)
    return {"postings": [_out(d) for d in docs], "created": len(docs)}


async def update_posting(actor: dict, company_id: str, code: str, payload: dict) -> dict:
    coll = get_collection(COLL_JOB_POSTINGS)
    current = await coll.find_one({"posting_code": code, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Posting not found.")

    updates = {}
    if payload.get("live_status") is not None:
        updates["live_status"] = getattr(payload["live_status"], "value", payload["live_status"])
    if payload.get("notes") is not None:
        updates["notes"] = clean_text(payload["notes"])
    if payload.get("requires_assessment") is not None:
        updates["requires_assessment"] = bool(payload["requires_assessment"])
    if payload.get("expiry_date") is not None:
        expiry = payload["expiry_date"]
        if expiry and not is_iso_date(expiry):
            raise HTTPException(status_code=422, detail="Expiry date must be YYYY-MM-DD.")
        updates["expiry_date"] = expiry or None

    mode = payload.get("apply_link_mode")
    if mode is not None:
        mode = getattr(mode, "value", mode)
        updates["apply_link_mode"] = mode
        if mode == ApplyLinkMode.EXTERNAL.value:
            external = (payload.get("external_url") or current.get("external_url") or "").strip()
            if not external.lower().startswith(("http://", "https://")):
                raise HTTPException(
                    status_code=422,
                    detail="An external application link must start with http:// or https://.")
            updates["external_url"] = external
        else:
            updates["external_url"] = None
    elif payload.get("external_url") is not None:
        external = (payload["external_url"] or "").strip()
        if external and not external.lower().startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422,
                detail="An external application link must start with http:// or https://.")
        updates["external_url"] = external or None

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"posting_code": code, "company_id": str(company_id)},
                          {"$set": updates})
    await audit(actor, AUDIT_POSTING_UPDATED, ENTITY_POSTING, code,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)

    doc = await coll.find_one({"posting_code": code})
    item = _out(doc)
    item["application_count"] = (await _application_counts([code])).get(code, 0)
    return item


async def delete_posting(actor: dict, company_id: str, code: str) -> dict:
    """Remove a posting. Applications already received are KEPT.

    Deleting the channel must not delete the people who came through it -- candidates
    outlive the ad, and Phase 5 onward depend on them.
    """
    coll = get_collection(COLL_JOB_POSTINGS)
    current = await coll.find_one({"posting_code": code, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Posting not found.")

    await coll.delete_one({"posting_code": code, "company_id": str(company_id)})
    await audit(actor, AUDIT_POSTING_DELETED, ENTITY_POSTING, code,
                current.get("platform"), company_id)
    return {"deleted": True, "posting_code": code,
            "applications_kept": (await _application_counts([code])).get(code, 0)}


# -------------------------------------------------------------
# Public side (NO authentication -- treat every input as hostile)
# -------------------------------------------------------------
async def get_public_posting(code: str) -> dict:
    """The job ad behind a public link.

    Returns only what a candidate needs to decide whether to apply. Internal fields --
    company_id, requisition number, who posted it, the assessment flag -- are deliberately
    NOT exposed: this response is world-readable.
    """
    posting = await get_collection(COLL_JOB_POSTINGS).find_one({"posting_code": code})
    if not posting:
        raise HTTPException(status_code=404, detail=INVALID_LINK)

    status = _effective_status(posting, _today())
    if status != LiveStatus.LIVE.value:
        # 410 Gone: the link was valid but this position is finished. Distinguishable from a
        # bogus code (404) for the applicant's benefit; neither reveals anything internal.
        raise HTTPException(status_code=410, detail=CLOSED_LINK)

    if posting.get("apply_link_mode") == ApplyLinkMode.EXTERNAL.value:
        return {"ok": True, "external": True, "external_url": posting.get("external_url"),
                "title": posting.get("title"), "platform": posting.get("platform")}

    jd = await get_collection(COLL_JOB_DESCRIPTIONS).find_one({"jd_no": posting.get("jd_no")}) or {}
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": posting.get("request_no")}) or {}

    return {
        "ok": True,
        "external": False,
        "posting_code": posting["posting_code"],
        "title": jd.get("title") or posting.get("title"),
        "platform": posting.get("platform"),
        "posting_date": posting.get("posting_date"),
        "expiry_date": posting.get("expiry_date"),
        "department": req.get("department_name"),
        "designation": req.get("designation_name"),
        "employment_type": jd.get("employment_type"),
        "location": jd.get("location") or req.get("work_location"),
        "experience": jd.get("experience") or req.get("experience_required"),
        "qualifications": jd.get("qualifications") or req.get("qualification"),
        "responsibilities": jd.get("responsibilities"),
        "skills": jd.get("skills") or req.get("essential_skills"),
        "benefits": jd.get("benefits"),
        "ctc": jd.get("ctc"),
        "vacancies": req.get("vacancy"),
    }


async def _store_upload(upload, label: str, prefix: str) -> Optional[dict]:
    """Validate, decode and store one candidate file.

    Returns `{name, key}` -- the S3 KEY, not a URL. Signed URLs expire in an hour, so
    persisting one would leave dead links in every candidate record; the key is permanent
    and a fresh URL is generated on demand.
    """
    if upload is None:
        return None
    raw, name, mime = decode_upload(upload, label=label)
    if not raw:
        return None

    import io
    from app.services.s3_service import upload_file_to_s3_with_key
    try:
        result = upload_file_to_s3_with_key(io.BytesIO(raw), f"{prefix}_{name}", mime)
    except Exception as e:
        print(f"[WARN] HRMS public upload failed ({label}): {e}")
        raise HTTPException(
            status_code=503,
            detail=f"{label} could not be uploaded right now. Please try again.")
    return {"name": name, "key": result.get("key") if isinstance(result, dict) else None,
            "mime_type": mime}


async def submit_application(code: str, payload: dict) -> dict:
    """Receive a public application and create a candidate.

    Every field is untrusted. Validation here is the ONLY validation -- there is no
    authenticated caller to have checked anything first.
    """
    posting = await get_collection(COLL_JOB_POSTINGS).find_one({"posting_code": code})
    if not posting:
        raise HTTPException(status_code=404, detail=INVALID_LINK)
    if _effective_status(posting, _today()) != LiveStatus.LIVE.value:
        raise HTTPException(status_code=410, detail=CLOSED_LINK)
    if posting.get("apply_link_mode") == ApplyLinkMode.EXTERNAL.value:
        raise HTTPException(
            status_code=409,
            detail="Applications for this listing are handled on the original job board.")

    name = clean_text(payload.get("candidate_name"), limit=140)
    email = clean_text(payload.get("can_email"), limit=180)
    phone = clean_text(payload.get("can_contact"), limit=30)

    if not name:
        raise HTTPException(status_code=422, detail="Please enter your full name.")
    if not email or not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Please enter a valid email address.")
    if not phone or not PHONE_RE.match(phone):
        raise HTTPException(status_code=422, detail="Please enter a valid phone number.")
    if not payload.get("declaration"):
        raise HTTPException(
            status_code=422,
            detail="Please confirm that the information provided is accurate.")

    certificates = payload.get("certificates") or []
    if len(certificates) > MAX_CERTIFICATES:
        raise HTTPException(
            status_code=422,
            detail=f"You can attach at most {MAX_CERTIFICATES} certificates.")

    email = email.lower()
    company_id = posting.get("company_id")

    # Phase 11-R, Item 5: the discovery / referral block. Validated BEFORE any upload is
    # stored, so a rejected claim never costs storage -- the same ordering the existing
    # validation already follows.
    #
    # "Where did you find this job" is MANDATORY on the public form, which is the point of
    # Item 1's one-form-per-posting design: the channel comes from the applicant rather
    # than from which of several links they clicked. Enforced here rather than in
    # resolve_referral, because the manual add-candidate path has no applicant to ask.
    if not payload.get("referral_source"):
        raise HTTPException(
            status_code=422, detail="Please tell us where you found this job.")
    from app.services.hrms_referral_service import resolve_referral
    referral = await resolve_referral(payload, company_id)

    # Server-side duplicate detection. The source flagged duplicates in the browser only
    # (BACKEND_ANALYSIS 8), so a re-submission created a second candidate record. Re-applying
    # to the SAME posting is idempotent from the applicant's point of view -- they get the
    # same friendly acknowledgement rather than an error that invites a retry loop.
    existing = await get_collection(COLL_CANDIDATES).find_one({
        "company_id": company_id, "posting_code": code,
        "$or": [{"can_email": email}, {"can_contact": phone}],
    })
    if existing:
        return {"ok": True, "duplicate": True, "reference": existing.get("uk"),
                "message": "You have already applied for this position."}

    # Uploads happen only after validation passes, so a rejected form never costs storage.
    resume = await _store_upload(payload.get("resume"), "Resume", "resume")
    photo = await _store_upload(payload.get("photo"), "Photo", "photo")
    certs = []
    for i, cert in enumerate(certificates):
        stored = await _store_upload(cert, f"Certificate {i + 1}", "cert")
        if stored:
            certs.append(stored)

    year = datetime.now(timezone.utc).year
    uk = await next_business_id("candidate", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "uk": uk,
        "company_id": company_id,
        "posting_code": code,
        "jd_no": posting.get("jd_no"),
        "request_no": posting.get("request_no"),
        "candidate_name": name,
        "can_email": email,
        "can_contact": phone,
        "source": posting.get("platform"),
        "application_status": AppStatus.APPLIED.value,
        # Copied from the posting at apply time so a later change to the posting cannot
        # retroactively alter the rules an existing applicant is judged by.
        "requires_assessment": bool(posting.get("requires_assessment")),
        "current_location": clean_text(payload.get("current_location"), limit=120),
        "total_experience": clean_text(payload.get("total_experience"), limit=60),
        "qualification": clean_text(payload.get("qualification"), limit=180),
        "current_company": clean_text(payload.get("current_company"), limit=140),
        "current_ctc": clean_text(payload.get("current_ctc"), limit=40),
        "expected_ctc": clean_text(payload.get("expected_ctc"), limit=40),
        "notice_period": clean_text(payload.get("notice_period"), limit=60),
        "linkedin": clean_text(payload.get("linkedin"), limit=300),
        "portfolio": clean_text(payload.get("portfolio"), limit=300),
        "cover_note": clean_text(payload.get("cover_note"), limit=4000),
        "resume": resume,
        "photo": photo,
        "certificates": certs,
        "applied_at": now,
        "created_at": now,
    }
    # Applied AFTER the base document so `source` is overridden to "Referral" when the
    # applicant declared one -- a referral that arrived through the LinkedIn ad is a
    # referral, and filing it under LinkedIn would overstate that channel.
    doc.update(referral)
    await get_collection(COLL_CANDIDATES).insert_one(dict(doc))

    await audit(None, AUDIT_APPLICATION, ENTITY_CANDIDATE_APPLICATION, uk,
                f"{name} applied via {posting.get('platform')} ({code})", company_id)

    title = posting.get("title") or "a role"
    await notify_hrms_role(
        company_id, ["HR"], f"New application for {title}",
        f"{name} applied via {posting.get('platform')}.",
        link="/hrms/candidates", email=False)

    # Also tell the requisition's assigned recruiter -- they own this pipeline, and a
    # role-wide notification alone lets everyone assume someone else is handling it.
    req = await get_collection(COLL_REQUISITIONS).find_one(
        {"request_no": posting.get("request_no")}) or {}
    if req.get("assignee_id"):
        await notify_user(req["assignee_id"], f"New application for {title}",
                          f"{name} applied via {posting.get('platform')}.",
                          link="/hrms/candidates")

    # Phase 11-R, Item 5: tell the referring employee their referral landed. In-app only.
    if doc.get("referrer_user_id"):
        from app.services.hrms_referral_service import notify_referrer
        await notify_referrer(
            doc, "Your referral has applied",
            f"{name}, whom you referred, has applied for {title}.")

    return {"ok": True, "duplicate": False, "reference": uk,
            "message": "Your application has been submitted."}
