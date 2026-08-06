"""
HRMS > PUBLIC routes (NO AUTHENTICATION).

Mounted under /api/hrms/public.

  GET  /hrms/public/apply/{code}     the job ad behind a shared application link
  POST /hrms/public/apply/{code}     submit an application
  GET  /hrms/public/assess/{code}    a candidate's assessment
  POST /hrms/public/assess/{code}    submit an assessment
  GET  /hrms/public/offer/{code}     a candidate's offer letter
  POST /hrms/public/offer/{code}     accept or decline
  GET  /hrms/public/onboard/{code}   a new hire's pre-onboarding form
  POST /hrms/public/onboard/{code}   submit joining details and KYC documents

*** READ THIS BEFORE ADDING AN ENDPOINT HERE ***

This is the only router in the ERP reachable with no token, by anyone on the internet. It
accepts files and personal data. Everything else in the app can assume an authenticated,
tenant-scoped caller; nothing here can.

Rules for this file, all enforced by tests in test_phase4_public_security.py:

1. NO `Depends(get_current_user)`, and NO router-level company gate. Adding either would
   break the public flow; forgetting the rest of this list would break security.
2. The URL code is the ONLY credential. It is pattern-validated (`validate_posting_code`)
   before it reaches a query, so a crafted value cannot arrive at Mongo as an operator
   document -- NoSQL operator injection is structurally impossible, not merely unlikely.
3. Every endpoint is rate limited BEFORE it does any work, on two independent axes: per
   client IP, and per posting code. The second exists because the first is defeatable with
   a proxy pool.
4. Errors are deliberately vague and identical for "not found", "malformed" and "wrong
   tenant", so the endpoint cannot be used as an existence oracle. This mirrors how
   /auth/forgot-password answers identically for known and unknown emails.
5. Responses expose ONLY what a candidate needs. No company_id, no requisition number, no
   internal flags, no other applicant's data.
6. This router is NOT gated by `hrms_enabled`. A posting code is only ever issued by an
   enabled company, and checking the toggle here would let an applicant infer a client's
   subscription state from a shared link.
"""
from fastapi import APIRouter, Request

from app.models.hrms import (
    PublicApplicationIn, PublicAssessmentIn, PublicOfferResponseIn, PublicOnboardIn,
)
from app.services import hrms_assessment_service as assessments
from app.services import hrms_offer_service as offers
from app.services import hrms_onboarding_service as onboarding
from app.services import hrms_posting_service as postings
from app.utils.hrms_public_guard import (
    client_ip, enforce_rate_limit, validate_access_code, validate_posting_code,
)

router = APIRouter(prefix="/hrms/public", tags=["HRMS Public"])


@router.get("/apply/{code}")
async def public_job_ad(code: str, request: Request):
    """The job ad behind a public application link.

    Rate limited generously -- browsing an ad is cheap, and a shared office or campus IP
    should not be locked out for reading a job posting.
    """
    code = validate_posting_code(code)
    await enforce_rate_limit("view", client_ip(request))
    return await postings.get_public_posting(code)


@router.post("/apply/{code}")
async def public_apply(code: str, body: PublicApplicationIn, request: Request):
    """Submit an application.

    The expensive endpoint: it creates a record and stores files. Limited per IP (5/hour)
    AND per posting code (200/hour), so neither a single abusive client nor a distributed
    flood against one popular ad can fill the database.
    """
    code = validate_posting_code(code)
    ip = client_ip(request)
    await enforce_rate_limit("apply", ip)
    await enforce_rate_limit("apply-posting", code)
    return await postings.submit_application(code, body.model_dump())


@router.get("/assess/{code}")
async def public_assessment(code: str, request: Request):
    """The assessment behind a candidate's link.

    The code here is a 128-bit access token, not a short public identifier like a posting
    code -- it is the ONLY thing protecting one candidate's submission, so it is validated
    against its own pattern and never normalised (case-folding would throw away entropy).

    Viewing marks the assessment Opened on first sight, which is how HR distinguishes
    "never looked at it" from "opened it and went quiet".
    """
    code = validate_access_code(code)
    await enforce_rate_limit("assess-view", client_ip(request))
    return await assessments.get_public_assessment(code)


@router.post("/assess/{code}")
async def public_assessment_submit(code: str, body: PublicAssessmentIn, request: Request):
    """Submit an assessment. Accepts a written response, attachments, or both."""
    code = validate_access_code(code)
    await enforce_rate_limit("assess-submit", client_ip(request))
    return await assessments.submit_public_assessment(code, body.model_dump())


@router.get("/offer/{code}")
async def public_offer(code: str, request: Request):
    """The offer letter behind a candidate's link.

    A DRAFT is invisible here -- it has not been issued, so as far as the world is concerned
    it does not exist, and it returns the same opaque 404 as an unknown code.
    """
    code = validate_access_code(code)
    await enforce_rate_limit("offer-view", client_ip(request))
    return await offers.get_public_offer(code)


@router.post("/offer/{code}")
async def public_offer_respond(code: str, body: PublicOfferResponseIn, request: Request):
    """Accept or decline. Accepting requires a typed signature; declining does not."""
    code = validate_access_code(code)
    await enforce_rate_limit("offer-respond", client_ip(request))
    return await offers.respond_to_offer(code, body.model_dump())


@router.get("/onboard/{code}")
async def public_onboarding(code: str, request: Request):
    """The pre-onboarding form behind a new hire's link.

    Returns only enough for them to recognise the form as theirs -- their name, the role and
    the joining date. Never the offer terms, the requisition, or any internal status beyond
    "you have already submitted this".
    """
    code = validate_access_code(code)
    await enforce_rate_limit("onboard-view", client_ip(request))
    return await onboarding.get_public_onboarding(code)


@router.post("/onboard/{code}")
async def public_onboarding_submit(code: str, body: PublicOnboardIn, request: Request):
    """Submit joining details and KYC documents.

    PAN-or-Aadhaar is enforced HERE, server-side. The source checked it in the browser only
    (BACKEND_ANALYSIS 8), so any request that skipped the form put an employee into payroll
    with no identity document at all.
    """
    code = validate_access_code(code)
    await enforce_rate_limit("onboard-submit", client_ip(request))
    return await onboarding.submit_public_onboarding(code, body.model_dump())
