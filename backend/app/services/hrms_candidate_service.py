"""Candidate pipeline — postings, applications, screening, assessments, interviews.

A candidate is ONE document. Assessments and interviews are embedded on it, because they are
always read together (the "candidate journey") and are bounded in size — one Mongo read replaces
the reference's four-way join.

`stage` is the single source of truth for where someone stands. The reference spreads this over
several columns that can disagree; here every move goes through `advance_stage`, which refuses
to walk backwards.

Security-relevant behaviours, each fixing a named defect in the reference:
  * assessment access codes are NEVER returned to a list/read endpoint (its GET leaks the code
    for every candidate to any logged-in user);
  * public submissions are state-gated, so a link can't be replayed to overwrite a submission;
  * a posting's public link honours an expiry.
"""
import io
import logging
import re
from datetime import datetime, date, timezone
from typing import Optional

from app.db.mongodb import get_collection
from app.models.hrms import (
    COL_CANDIDATES, COL_POSTINGS, COL_REQUISITIONS, SEQ_CANDIDATE,
    STAGE_APPLIED, STAGE_REJECTED, CANDIDATE_STAGES, CANDIDATE_FORWARD, REJECTION_STAGES,
    POSTING_OPEN, POSTING_STATES,
    ASSESSMENT_SENT, ASSESSMENT_OPENED, ASSESSMENT_SUBMITTED, ASSESSMENT_REVIEWED,
    INTERVIEW_SCHEDULED, INTERVIEW_DONE, INTERVIEW_CANCELLED,
    REQ_APPROVED,
    OFFER_DRAFT, OFFER_SENT, OFFER_ACCEPTED, OFFER_DECLINED, OFFER_WITHDRAWN, OFFER_FINAL,
    ONB_INVITED, ONB_SUBMITTED, ONB_VERIFIED, ONB_CONVERTED,
    APPT_PENDING, APPT_GENERATED, APPT_SENT, APPT_ACKNOWLEDGED,
)
from app.utils.counters import next_code
from app.utils.public_guard import public_token
from app.services.s3_service import upload_file_to_s3_with_key

logger = logging.getLogger(__name__)

RESUME_PREFIX = "hrms/resumes"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def generate_candidate_uk() -> str:
    return await next_code(SEQ_CANDIDATE, "CAN", width=4)


def validate_applicant(payload: dict) -> None:
    """Applicant-facing validation. Messages are written to be read by the applicant."""
    if not (payload.get("full_name") or "").strip():
        raise ValueError("Please enter your name.")
    email = (payload.get("email") or "").strip()
    if not EMAIL_RE.match(email):
        raise ValueError("Please enter a valid email address.")


def store_resume(blob: bytes, extension: str, content_type: str, uk: str) -> str:
    """Put a CV on S3 under the gated prefix. Returns the key, or "" if the upload failed.

    A failed upload must not lose the application — the candidate's details matter more than
    the attachment, and HR can ask for the CV again.
    """
    try:
        name = f"{RESUME_PREFIX}/{uk}{extension}"
        result = upload_file_to_s3_with_key(io.BytesIO(blob), name, content_type)
        return (result or {}).get("key") or ""
    except Exception as e:
        logger.error("Resume upload failed for %s: %s", uk, e)
        return ""


# ─── Postings ───────────────────────────────────────────────────────────────────
async def create_posting(request_no: str, platform: str, notes: str,
                         expires_on: Optional[str], actor: dict) -> dict:
    """Publish an APPROVED requisition to one platform, with its own public code."""
    req = await get_collection(COL_REQUISITIONS).find_one({"request_no": request_no})
    if not req:
        raise ValueError("Requisition not found")
    if req.get("approval_status") != REQ_APPROVED:
        raise ValueError("Only an approved requisition can be posted.")

    now = datetime.now(timezone.utc)
    doc = {
        "request_no": request_no,
        "designation": req.get("designation") or "",
        "department": req.get("department") or "",
        # Inherited from the requisition so a candidate can be attributed to a client without
        # joining back through the requisition on every analytics query.
        "client_company_id": req.get("client_company_id") or "",
        "client_company_name": req.get("client_company_name") or "",
        "platform": (platform or "").strip() or "Careers page",
        "notes": notes or "",
        "status": POSTING_OPEN,
        "expires_on": expires_on,
        # 128 bits from `secrets` — not the reference's 30-40 bits of Math.random().
        "public_code": public_token(),
        "applications": 0,
        "created_by": str(actor.get("_id")),
        "created_by_name": actor.get("full_name") or actor.get("email"),
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COL_POSTINGS).insert_one(doc)
    return doc


def posting_is_live(posting: dict) -> tuple:
    """(accepting, reason). Reason is applicant-facing copy, not an internal message."""
    if not posting:
        return False, "This link is not valid."
    if posting.get("status") != POSTING_OPEN:
        return False, "This role is no longer accepting applications."
    expires = posting.get("expires_on")
    if expires:
        try:
            # A grace day: an application on the closing date itself still counts.
            if date.fromisoformat(str(expires)[:10]) < date.today():
                return False, "Applications for this role have closed."
        except ValueError:
            pass
    return True, ""


def serialize_posting(doc: dict, include_code: bool = True) -> dict:
    out = {
        "id": str(doc.get("_id")),
        "requestNo": doc.get("request_no"),
        "designation": doc.get("designation") or "",
        "department": doc.get("department") or "",
        "clientCompanyId": doc.get("client_company_id") or "",
        "clientCompanyName": doc.get("client_company_name") or "",
        "platform": doc.get("platform") or "",
        "notes": doc.get("notes") or "",
        "status": doc.get("status") or POSTING_OPEN,
        "expiresOn": doc.get("expires_on"),
        "applications": int(doc.get("applications") or 0),
        "createdBy": doc.get("created_by_name") or "",
        "createdAt": doc.get("created_at"),
    }
    if include_code:
        out["publicCode"] = doc.get("public_code")
    return out


def serialize_public_posting(doc: dict) -> dict:
    """What an anonymous visitor may see. Deliberately narrow — no internal ids, no counts,
    no requisition number."""
    return {
        "designation": doc.get("designation") or "",
        "department": doc.get("department") or "",
        "jd": doc.get("_jd") or None,
    }


# ─── Pipeline ───────────────────────────────────────────────────────────────────
def can_advance(current: str, target: str) -> bool:
    """Forward-only, except rejection which is reachable from anywhere.

    Stops a candidate silently moving back to an earlier stage, which would make the funnel
    counts meaningless.

    Both rejection kinds behave identically: reachable from any live stage, terminal once set.
    A client rejection is still a rejection — reopen by re-applying, not by quietly reversing it.
    """
    if target not in CANDIDATE_STAGES:
        return False
    if target in REJECTION_STAGES:
        return current not in REJECTION_STAGES
    if current in REJECTION_STAGES:
        return False        # reopen by re-applying, not by quietly un-rejecting
    if current not in CANDIDATE_FORWARD or target not in CANDIDATE_FORWARD:
        return False
    return CANDIDATE_FORWARD.index(target) > CANDIDATE_FORWARD.index(current)


def journey_entry(from_stage: str, to_stage: str, actor: dict, remarks: str = "") -> dict:
    return {
        "from": from_stage,
        "to": to_stage,
        "actor": str(actor.get("_id")) if actor else "",
        "actor_name": (actor or {}).get("full_name") or (actor or {}).get("email") or "",
        "remarks": remarks or "",
        "at": datetime.now(timezone.utc),
    }


def serialize_candidate(doc: dict, include_codes: bool = False,
                        include_kyc: bool = False) -> dict:
    """Candidate for an internal reader.

    `include_codes` is False everywhere except the one endpoint that deliberately reveals a
    single assessment link to the HR user who just created it. The reference's list endpoint
    returns every candidate's access code to any logged-in user — its audit rates that critical.

    `include_kyc` gates the onboarding block's statutory and bank fields, which is the same
    leak in a different place: the reference serves whole-workforce KYC to any logged-in user.
    """
    assessments = []
    for a in doc.get("assessments", []) or []:
        row = {
            "id": a.get("id"),
            "title": a.get("title") or "",
            "status": a.get("status") or ASSESSMENT_SENT,
            "sentAt": a.get("sent_at"),
            "submittedAt": a.get("submitted_at"),
            "dueOn": a.get("due_on"),
            "score": a.get("score"),
            "passed": a.get("passed"),
            "remarks": a.get("remarks") or "",
            "questions": a.get("questions") or [],
            "answers": a.get("answers") or [],
        }
        if include_codes:
            row["accessCode"] = a.get("access_code")
        assessments.append(row)

    interviews = [
        {
            "id": i.get("id"),
            "roundName": i.get("round_name") or "",
            "scheduledAt": i.get("scheduled_at"),
            "durationMinutes": i.get("duration_minutes"),
            "mode": i.get("mode") or "",
            "location": i.get("location") or "",
            "interviewerIds": i.get("interviewer_ids") or [],
            "interviewerNames": i.get("interviewer_names") or [],
            "status": i.get("status") or INTERVIEW_SCHEDULED,
            "recommendation": i.get("recommendation") or "",
            "score": i.get("score"),
            "strengths": i.get("strengths") or "",
            "concerns": i.get("concerns") or "",
            "remarks": i.get("remarks") or "",
            "evaluatedBy": i.get("evaluated_by_name") or "",
        }
        for i in (doc.get("interviews", []) or [])
    ]

    return {
        "id": str(doc.get("_id")),
        "uk": doc.get("uk"),
        "requestNo": doc.get("request_no") or "",
        "designation": doc.get("designation") or "",
        "department": doc.get("department") or "",
        "clientCompanyId": doc.get("client_company_id") or "",
        "clientCompanyName": doc.get("client_company_name") or "",
        "fullName": doc.get("full_name") or "",
        "email": doc.get("email") or "",
        "phone": doc.get("phone") or "",
        "currentCompany": doc.get("current_company") or "",
        "experienceYears": doc.get("experience_years") or "",
        "currentCtc": doc.get("current_ctc") or "",
        "expectedCtc": doc.get("expected_ctc") or "",
        "noticePeriod": doc.get("notice_period") or "",
        "coverNote": doc.get("cover_note") or "",
        "resumeKey": doc.get("resume_key") or "",
        "source": doc.get("source") or "",
        "platform": doc.get("platform") or "",
        "referredBy": doc.get("referred_by") or "",
        "referralSource": doc.get("referral_source") or "",
        "referralEmployeeCode": doc.get("referral_employee_code") or "",
        "stage": doc.get("stage") or STAGE_APPLIED,
        "rejectionReason": doc.get("rejection_reason") or "",
        "assessments": assessments,
        "interviews": interviews,
        # Offer access codes are never listed, for the same reason as assessment codes.
        "offers": [serialize_offer(o) for o in (doc.get("offers") or [])],
        # Access code withheld here for the same reason as offers and assessments.
        "appointmentLetter": serialize_appointment(doc),
        "onboarding": serialize_onboarding(doc, include_kyc),
        "journey": [
            {"from": j.get("from"), "to": j.get("to"), "actorName": j.get("actor_name") or "",
             "remarks": j.get("remarks") or "", "at": j.get("at")}
            for j in (doc.get("journey") or [])
        ],
        "appliedAt": doc.get("created_at"),
    }


async def find_candidate_by_assessment_code(code: str) -> Optional[dict]:
    """Look a candidate up by one of their assessment codes."""
    if not code:
        return None
    return await get_collection(COL_CANDIDATES).find_one({"assessments.access_code": code})


def find_assessment(doc: dict, code: str) -> Optional[dict]:
    return next((a for a in (doc.get("assessments") or []) if a.get("access_code") == code), None)


# ─── Offer & onboarding (Phase 7) ───────────────────────────────────────────────
async def find_candidate_by_offer_code(code: str) -> Optional[dict]:
    if not code:
        return None
    return await get_collection(COL_CANDIDATES).find_one({"offers.access_code": code})


def find_offer(doc: dict, code: str) -> Optional[dict]:
    return next((o for o in (doc.get("offers") or []) if o.get("access_code") == code), None)


def active_offer(doc: dict) -> Optional[dict]:
    """The offer currently in play — the most recent one not withdrawn."""
    live = [o for o in (doc.get("offers") or []) if o.get("status") != OFFER_WITHDRAWN]
    return live[-1] if live else None


async def find_candidate_by_appointment_code(code: str) -> Optional[dict]:
    if not code:
        return None
    return await get_collection(COL_CANDIDATES).find_one({"appointment_letter.access_code": code})


def appointment_link_state(appt: Optional[dict]) -> tuple:
    """(usable, reason) for the public acknowledgement link.

    Same shape as `offer_link_state` so both public pages report a dead link identically.
    """
    if not appt:
        return False, "This link is not valid."
    if appt.get("status") == APPT_ACKNOWLEDGED:
        return False, "You have already acknowledged this appointment letter."
    if appt.get("status") not in (APPT_SENT, APPT_GENERATED):
        return False, "This appointment letter is not ready yet."
    valid_till = appt.get("valid_till")
    if valid_till:
        try:
            if date.fromisoformat(str(valid_till)[:10]) < date.today():
                return False, "This appointment letter has expired."
        except ValueError:
            pass
    return True, ""


def serialize_appointment(doc: dict, include_code: bool = False) -> Optional[dict]:
    """The appointment letter for an internal reader.

    `include_code` follows the same rule as offers and assessments: the access code is returned
    once, to the HR user who generated it, and never from a list endpoint.
    """
    appt = doc.get("appointment_letter")
    if not appt:
        return None
    out = {
        "status": appt.get("status") or APPT_PENDING,
        "designation": appt.get("designation") or "",
        "department": appt.get("department") or "",
        "annualCtc": appt.get("annual_ctc"),
        "joiningDate": appt.get("joining_date"),
        "location": appt.get("location") or "",
        "reportingTo": appt.get("reporting_to") or "",
        "terms": appt.get("terms") or "",
        "validTill": appt.get("valid_till"),
        "generatedAt": appt.get("generated_at"),
        "sentAt": appt.get("sent_at"),
        "acknowledgedAt": appt.get("acknowledged_at"),
        "acknowledgementNote": appt.get("acknowledgement_note") or "",
        "generatedBy": appt.get("generated_by_name") or "",
    }
    if include_code:
        out["accessCode"] = appt.get("access_code")
    return out


async def find_candidate_by_onboarding_code(code: str) -> Optional[dict]:
    if not code:
        return None
    return await get_collection(COL_CANDIDATES).find_one({"onboarding.access_code": code})


def offer_link_state(offer: Optional[dict]) -> tuple:
    """(usable, reason) for the public offer link. Reason is candidate-facing copy."""
    if not offer:
        return False, "This link is not valid."
    status = offer.get("status")
    if status in OFFER_FINAL:
        # Spent, not broken — the candidate already answered.
        return False, "This offer has already been responded to."
    if status != OFFER_SENT:
        return False, "This offer is not ready yet."
    valid_till = offer.get("valid_till")
    if valid_till:
        try:
            # A grace day, so an acceptance on the closing date itself still counts.
            if date.fromisoformat(str(valid_till)[:10]) < date.today():
                return False, "This offer has expired. Please contact us."
        except ValueError:
            pass
    return True, ""


def serialize_offer(doc: dict, include_code: bool = False) -> dict:
    out = {
        "id": doc.get("id"),
        "designation": doc.get("designation") or "",
        "department": doc.get("department") or "",
        "annualCtc": float(doc.get("annual_ctc") or 0),
        "joiningDate": doc.get("joining_date"),
        "location": doc.get("location") or "",
        "employmentType": doc.get("employment_type") or "Full-time",
        "probationMonths": doc.get("probation_months"),
        "notes": doc.get("notes") or "",
        "validTill": doc.get("valid_till"),
        "status": doc.get("status") or OFFER_DRAFT,
        "sentAt": doc.get("sent_at"),
        "decidedAt": doc.get("decided_at"),
        "candidateNote": doc.get("candidate_note") or "",
    }
    if include_code:
        out["accessCode"] = doc.get("access_code")
    return out


def serialize_onboarding(doc: dict, include_kyc: bool) -> Optional[dict]:
    """Onboarding for an internal reader.

    `include_kyc` gates PAN, Aadhaar, passport, licence, UAN, ESIC and bank details. The
    reference guards its equivalent with "any authenticated user" and returns the whole
    workforce's KYC — its audit rates that critical.
    """
    onb = doc.get("onboarding")
    if not onb:
        return None
    out = {
        "status": onb.get("status") or ONB_INVITED,
        "invitedAt": onb.get("invited_at"),
        "submittedAt": onb.get("submitted_at"),
        "verifiedAt": onb.get("verified_at"),
        "verifiedBy": onb.get("verified_by_name") or "",
        "convertedAt": onb.get("converted_at"),
        "employeeCode": onb.get("employee_code") or "",
        "dueOn": onb.get("due_on"),
        "message": onb.get("message") or "",
        "remarks": onb.get("remarks") or "",
        # Non-sensitive personal details are fine for any recruiter to see.
        "dateOfBirth": onb.get("date_of_birth"),
        "gender": onb.get("gender") or "",
        "personalEmail": onb.get("personal_email") or "",
        "phone": onb.get("phone") or "",
        "address": onb.get("address") or "",
        "emergencyName": onb.get("emergency_name") or "",
        "emergencyRelation": onb.get("emergency_relation") or "",
        "emergencyPhone": onb.get("emergency_phone") or "",
        "kycVisible": include_kyc,
    }
    if include_kyc:
        out.update({
            "pan": onb.get("pan") or "",
            "aadhaar": onb.get("aadhaar") or "",
            "passport": onb.get("passport") or "",
            "drivingLicense": onb.get("driving_license") or "",
            "uan": onb.get("uan") or "",
            "esicNo": onb.get("esic_no") or "",
            "bankName": onb.get("bank_name") or "",
            "bankAccount": onb.get("bank_account") or "",
            "bankIfsc": onb.get("bank_ifsc") or "",
        })
    return out
