"""
HRMS ▸ authenticated API routes.

Mounted under /api/hrms.

  GET /hrms/health   module status + the caller's resolved role and capability set
  GET /hrms/audit    audit trail (capability-gated; the filterable Phase 15 API builds here)

Router-wide guard: `_hrms_company_gate` refuses a client-side user whose company has HRMS
switched off, on EVERY endpoint — so the module cannot be reached by typing a URL. Internal
staff pass; the data layer (hrms_access.hrms_enabled_company_ids) hides disabled companies
from what they see instead. This mirrors routes/tpms.py exactly.

Phase 1 ships the foundation only. Later phases add their routers/endpoints here.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.controllers.auth_controller import get_current_user
from app.models.hrms import (
    DEFAULT_REPORT_PAGE_SIZE, MAX_REPORT_PAGE_SIZE,
    BreakdownBy, ExportFormat, ReportEntity,
    Cap, DepartmentIn, DepartmentUpdate, DesignationIn, DesignationUpdate,
    EmployeeLinkIn, EmployeeProfileIn, EmployeeProfileUpdate, HrmsHealthResponse,
    OnboardingBgIn, OnboardingChecklistIn, OnboardingDetailsIn, OnboardingDocumentsIn,
    OnboardingIn,
    AssessmentIn, AssessmentReviewIn, CandidateIn, CandidateUpdate,
    InterviewEvaluateIn, InterviewIn, InterviewUpdate,
    OfferIn, OfferRevokeIn, OfferSendIn, OfferUpdate,
    JobDescriptionUpdate, PostingIn, PostingUpdate,
    RequisitionAction, RequisitionClose, RequisitionIn, RequisitionUpdate, ScreenIn,
)
# ── Phase 11-R — recruitment review enhancements ──
from app.models.hrms import (
    AppointmentCancelIn, AppointmentIn, AppointmentSendIn, AppointmentUpdate,
    ClientResponseIn,
    ScorecardApproveIn, ScorecardEvaluateIn, ScorecardIn, ScorecardUpdate,
    ReferenceCheckIn, ReferenceCheckUpdate, OfferApproveIn,
    TelephonicScreeningIn, TelephonicScreeningUpdate, NegotiationRoundIn,
    ConfigUpdateIn, ConfigResetIn, HolidayIn, HolidayImportIn,
    PersonnelFileCloseIn, ProbationConfirmIn, ProbationIn, ProbationUpdate,
    ExceptionDecisionIn, ExceptionIn,
    ClientEngagementIn, ClientEngagementUpdate, EngagementMemberIn,
    DocumentIn, DocumentStatusIn, DocumentTypeIn, DocumentTypeUpdate, DocumentUpdate,
    LinkRevokeIn, SanctionedStrengthIn, SanctionedStrengthUpdate,
)
# -- Phase 12 - the client hiring track --
from app.models.hrms import (
    BackgroundApproveIn, BackgroundCheckIn, BackgroundCheckUpdate,
    InterviewRecordingIn, InterviewReportIn,
    JobRequestAction, JobRequestConvertIn, JobRequestIn, JobRequestUpdate,
    ShareIn, ShareRemarkIn, ShareStatusIn, UploadIn,
)
# ── Phase INT-2 — the remaining Internal Recruitment SOP controls ──
from app.models.hrms import (
    PRINTABLE_DOCUMENTS,
    CommSendIn, CommTemplateUpdate, InterviewWindowIn, InterviewWindowUpdate,
    PolicyApproveIn, PolicyIn, PolicyRevisionIn, PreboardingTouchpointIn, PurgeApproveIn,
    SalaryBandIn, SalaryBandUpdate, ShortlistReviewIn, ShortlistReviewUpdate, TalentPoolIn,
)
from app.services import hrms_analytics_service as analytics
from app.services import hrms_employee_service as employees
from app.services import hrms_masters_service as masters
from app.services import hrms_assessment_service as assessments
from app.services import hrms_candidate_service as candidates
from app.services import hrms_interview_service as interviews
from app.services import hrms_offer_service as offers
from app.services import hrms_exception_service as exceptions
from app.services import hrms_probation_service as probation
from app.services import hrms_reference_service as references
from app.services import hrms_scorecard_service as scorecards
from app.services import hrms_telephonic_service as telephonic
from app.services import hrms_negotiation_service as negotiation
from app.services import hrms_config_service as config_svc
from app.services import hrms_holiday_service as holidays_svc
from app.services import hrms_tracker_service as tracker_svc
from app.services import hrms_sla_service as sla
from app.services import hrms_onboarding_service as onboarding
from app.services import hrms_posting_service as postings
from app.services import hrms_requisition_service as requisitions
# ── Phase 11-R ──
from app.services import hrms_appointment_service as appointments
from app.services import hrms_client_service as clients
from app.services import hrms_document_service as documents
from app.services import hrms_link_service as links
from app.services import hrms_sanction_service as sanctions
# ── Phase INT-2 ──
from app.services import hrms_comm_service as comms
from app.services import hrms_interview_window_service as interview_windows
from app.services import hrms_policy_service as policies
from app.services import hrms_preboarding_service as preboarding
from app.services import hrms_purge_service as purge
from app.services import hrms_record_document_service as record_documents
from app.services import hrms_salary_band_service as salary_bands
from app.services import hrms_shortlist_service as shortlists
from app.services import hrms_survey_service as surveys
# ── Phase 12: the client hiring track ──
from app.services import hrms_background_service as background
from app.services import hrms_interview_media_service as interview_media
from app.services import hrms_job_request_service as job_requests
from app.services import hrms_share_service as shares
from app.services.hrms_audit_service import read_audit
from app.utils.hrms_access import (
    NO_ACCESS_MESSAGE, can, capabilities_for, ensure_hrms_enabled, hrms_role,
    is_internal_user, scope_company_id,
)
from app.utils.hrms_access import is_client_scoped_user, scope_client_ids


async def _hrms_company_gate(current_user: dict = Depends(get_current_user)) -> None:
    """Router-wide guard — see module docstring."""
    await ensure_hrms_enabled(current_user)


router = APIRouter(prefix="/hrms", tags=["HRMS"], dependencies=[Depends(_hrms_company_gate)])


def _require(user: dict, capability: Cap) -> None:
    """Capability gate. Every protected endpoint calls this and nothing else, so there is
    exactly one place a permission decision can be made (and audited)."""
    if not can(user, capability):
        raise HTTPException(status_code=403, detail=NO_ACCESS_MESSAGE)


def _company(user: dict, requested: str = None) -> str:
    """The company this request operates on, with tenant pinning applied.

    A client-side caller is always pinned to their own company -- a `company_id` in the
    query string is ignored, not honoured. An internal caller must name one, because
    "every company at once" is not a meaningful scope for employee data.
    """
    scoped = scope_company_id(user, requested)
    if not scoped:
        raise HTTPException(
            status_code=400,
            detail="Select a company to work with (company_id is required).")
    return scoped


@router.get("/health", response_model=HrmsHealthResponse)
async def hrms_health(current_user: dict = Depends(get_current_user)):
    """Module status for the caller.

    Returns the caller's RESOLVED role and capability list rather than raw role strings,
    so the frontend gates on exactly what the server enforces. The source HRMS derived
    permissions independently on each side and ended up "rendering actions unconditionally
    that the API will 403 for" (FRONTEND_ANALYSIS §5) — this endpoint is what prevents that.

    Reaching this endpoint at all means the company gate passed, so `enabled` is true by
    construction; it is returned explicitly because the client shape should not depend on
    inferring status from an HTTP code.
    """
    role = hrms_role(current_user)
    company_id = scope_company_id(current_user)
    # ── Client scope ──
    # Resolved SERVER-SIDE from the engagement records and handed to the frontend as an
    # answer, never as a question. The frontend renders from it; a client id it later sends
    # back is a filter, and `assert_client_allowed` is what keeps it one.
    allowed_client_ids = await scope_client_ids(current_user, company_id)
    return HrmsHealthResponse(
        enabled=True,
        role=role.value if role else None,
        capabilities=sorted(c.value for c in capabilities_for(current_user)),
        company_id=company_id,
        is_internal=is_internal_user(current_user),
        is_client_user=is_client_scoped_user(current_user),
        allowed_client_ids=allowed_client_ids,
    )


@router.get("/audit")
async def hrms_audit(
    entity: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Read the HRMS audit trail.

    Tenant-scoped: a client-side caller is pinned to their own company regardless of the
    `company_id` query param (see hrms_access.scope_company_id), so a crafted query string
    cannot read another tenant's trail.
    """
    _require(current_user, Cap.AUDIT_READ)

    rows = await read_audit(
        company_id=scope_company_id(current_user, company_id),
        entity=entity,
        entity_id=entity_id,
        actor_id=actor_id,
        limit=limit,
    )
    return {"audit": rows, "count": len(rows)}


@router.get("/companies")
async def hrms_companies(current_user: dict = Depends(get_current_user)):
    """Companies this caller may work with inside HRMS.

    Internal staff need a scope selector, since every employee endpoint requires a company.
    This is HRMS's own list rather than `GET /api/companies` on purpose: that route is gated
    by the Companies module's `companies.read` permission, which a staff admin may not hold,
    and reusing it would couple HRMS's scoping to another module's permission model.

    Client-side users get exactly their own company, so the same UI works for both without
    branching.
    """
    from bson import ObjectId

    from app.db.mongodb import get_collection
    from app.utils.hrms_access import hrms_enabled_company_ids

    if is_internal_user(current_user):
        ids = await hrms_enabled_company_ids()
        oids = []
        for i in ids:
            try:
                oids.append(ObjectId(i))
            except Exception:
                continue
        rows = await get_collection("companies").find(
            {"_id": {"$in": oids}}, {"name": 1}).sort("name", 1).to_list(500)
    else:
        own = str(current_user.get("company_id") or "")
        rows = []
        if own:
            try:
                doc = await get_collection("companies").find_one(
                    {"_id": ObjectId(own)}, {"name": 1})
                if doc:
                    rows = [doc]
            except Exception:
                rows = []

    return {"companies": [{"id": str(r["_id"]), "name": r.get("name")} for r in rows]}


# =============================================================
# Phase 2 - Departments
# =============================================================
@router.get("/departments")
async def list_departments(
    company_id: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DEPARTMENT_READ)
    return {"departments": await masters.list_masters(
        "department", _company(current_user, company_id), include_inactive)}


@router.post("/departments", status_code=201)
async def create_department(
    body: DepartmentIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DEPARTMENT_WRITE)
    return await masters.create_master(
        "department", _company(current_user, company_id), body.model_dump(), current_user)


@router.patch("/departments/{department_id}")
async def update_department(
    department_id: str,
    body: DepartmentUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DEPARTMENT_WRITE)
    return await masters.update_master(
        "department", _company(current_user, company_id), department_id,
        body.model_dump(exclude_unset=True), current_user)


@router.delete("/departments/{department_id}")
async def delete_department(
    department_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DEPARTMENT_WRITE)
    return await masters.delete_master(
        "department", _company(current_user, company_id), department_id, current_user)


# =============================================================
# Phase 2 - Designations
# =============================================================
@router.get("/designations")
async def list_designations(
    company_id: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DESIGNATION_READ)
    return {"designations": await masters.list_masters(
        "designation", _company(current_user, company_id), include_inactive)}


@router.post("/designations", status_code=201)
async def create_designation(
    body: DesignationIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DESIGNATION_WRITE)
    return await masters.create_master(
        "designation", _company(current_user, company_id), body.model_dump(), current_user)


@router.patch("/designations/{designation_id}")
async def update_designation(
    designation_id: str,
    body: DesignationUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DESIGNATION_WRITE)
    return await masters.update_master(
        "designation", _company(current_user, company_id), designation_id,
        body.model_dump(exclude_unset=True), current_user)


@router.delete("/designations/{designation_id}")
async def delete_designation(
    designation_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DESIGNATION_WRITE)
    return await masters.delete_master(
        "designation", _company(current_user, company_id), designation_id, current_user)


@router.get("/masters/suggestions")
async def master_suggestions(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Distinct department/designation values already on this company's users, with counts.

    READ-ONLY against `learners` -- nothing is written there and nothing is auto-created.
    It exists so HR can build a clean master from real data instead of retyping it. See
    hrms_masters_service.suggest_from_directory for why we do not auto-seed.
    """
    _require(current_user, Cap.DEPARTMENT_READ)
    return await masters.suggest_from_directory(_company(current_user, company_id))


# =============================================================
# Phase 2 - Employees
# =============================================================
@router.get("/employees")
async def list_employees(
    company_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None),
    designation_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """The employee directory. Row-scoped: a MANAGER sees only their department and their
    direct reports; salary is omitted entirely without `employee.salary.read`."""
    _require(current_user, Cap.EMPLOYEE_READ)
    return await employees.list_employees(
        current_user, _company(current_user, company_id),
        search=search, department_id=department_id, designation_id=designation_id,
        status=status, include_inactive=include_inactive, limit=limit, skip=skip)


@router.get("/employees/linkable")
async def linkable_users(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Company users without an employee profile yet -- the 'Add employee' picker.
    Declared before /employees/{user_id} so the static path wins."""
    _require(current_user, Cap.EMPLOYEE_WRITE)
    return {"users": await employees.list_linkable_users(
        current_user, _company(current_user, company_id))}


@router.get("/employees/me")
async def my_employee_profile(current_user: dict = Depends(get_current_user)):
    """Your own employee record.

    Reading your own profile is an inherent right, not a capability -- it is deliberately
    not gated by `employee.read`, so it can never be revoked by a permission edit. Your own
    salary is always visible to you.
    """
    return await employees.get_employee(
        current_user, str(current_user.get("_id")), force_salary=True)


@router.post("/employees", status_code=201)
async def create_employee(
    body: EmployeeProfileIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.EMPLOYEE_WRITE)
    return await employees.create_profile(
        current_user, _company(current_user, company_id), body.model_dump(exclude_unset=True))


@router.get("/employees/{user_id}")
async def get_employee(
    user_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    return await employees.get_employee(
        current_user, user_id, company_id=scope_company_id(current_user, company_id))


@router.patch("/employees/{user_id}")
async def update_employee(
    user_id: str,
    body: EmployeeProfileUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.EMPLOYEE_WRITE)
    return await employees.update_profile(
        current_user, user_id, body.model_dump(exclude_unset=True),
        _company(current_user, company_id))


@router.get("/employees/{user_id}/hierarchy")
async def employee_hierarchy(
    user_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Reporting chain upward + direct reports. The upward walk is depth-capped and
    cycle-guarded -- `reporting_manager` has no DB constraint against A->B->A."""
    _require(current_user, Cap.EMPLOYEE_READ)
    return await employees.get_hierarchy(
        current_user, user_id, _company(current_user, company_id))


# =============================================================
# Phase 3 - Requisitions (FMS)
# =============================================================
@router.get("/requisitions")
async def list_requisitions(
    company_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    approval_status: Optional[str] = Query(None),
    closing_status: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None),
    track: Optional[str] = Query(None, description="client | internal"),
    limit: int = Query(100, ge=1, le=200),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """Requisition list + stat tiles. A plain employee sees only the ones they raised.

    `track` filters to one hiring track. Omitting it returns BOTH, which is what every
    caller written before the internal track existed does -- so their behaviour is unchanged.
    """
    _require(current_user, Cap.REQUISITION_READ)
    return await requisitions.list_requisitions(
        current_user, _company(current_user, company_id),
        search=search, approval_status=approval_status, closing_status=closing_status,
        department_id=department_id, track=track, limit=limit, skip=skip)


@router.post("/requisitions", status_code=201)
async def create_requisition(
    body: RequisitionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Raise a requisition together with its job description.

    Open to any HRMS user by design: whoever raises one becomes its hiring manager and
    later co-reviews its candidates' assessments (FRONTEND_ANALYSIS 5).
    """
    _require(current_user, Cap.REQUISITION_CREATE)
    return await requisitions.create_requisition(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/requisitions/{request_no}")
async def get_requisition(
    request_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REQUISITION_READ)
    return await requisitions.get_requisition(
        current_user, _company(current_user, company_id), request_no)


@router.patch("/requisitions/{request_no}")
async def update_requisition(
    request_no: str,
    body: RequisitionUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REQUISITION_WRITE)
    return await requisitions.update_requisition(
        current_user, _company(current_user, company_id), request_no,
        body.model_dump(exclude_unset=True))


@router.delete("/requisitions/{request_no}")
async def delete_requisition(
    request_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REQUISITION_WRITE)
    return await requisitions.delete_requisition(
        current_user, _company(current_user, company_id), request_no)


@router.post("/requisitions/{request_no}/approve")
async def act_on_requisition(
    request_no: str,
    body: RequisitionAction,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One transition of the approval chain.

    Client track:   hr-approve | hr-reject | md-approve | md-reject
                    (+ escalate-approve | escalate-reject when over sanctioned strength)
    Internal track: hr-verify | budget-approve | scorecard-approve, each with its -reject twin
                    (+ the same escalation pair)

    WHICH set applies is a property of the requisition, not of the caller, so an action from
    the other track's chain is rejected as unknown. The per-action capability is enforced
    inside the service from the same transition table that defines the state machine -- so
    the gate can never drift from the rule it guards.
    """
    return await requisitions.act_on_requisition(
        current_user, _company(current_user, company_id), request_no,
        body.action, body.remarks, body.salary_change,
        budget={"approved_headcount": body.approved_headcount,
                "approved_salary_band_min": body.approved_salary_band_min,
                "approved_salary_band_max": body.approved_salary_band_max})


@router.get("/requisitions/{request_no}/sla")
async def requisition_sla(
    request_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Milestone targets against actuals for one requisition (SOP §8).

    Everything except the actual timestamps is computed on read, so a target changed in the
    SOP takes effect immediately and a stored breach flag can never go stale.
    """
    _require(current_user, Cap.REQUISITION_READ)
    scoped = _company(current_user, company_id)
    req = await requisitions.get_requisition(current_user, scoped, request_no)
    if not req:
        raise HTTPException(status_code=404, detail="Requisition not found.")
    return await sla.sla_for(scoped, req)


@router.get("/sla/breaches")
async def sla_breaches(
    notify: bool = Query(False, description="fire escalations for anything newly overdue"),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Open internal requisitions with a milestone that is overdue and still incomplete.

    The dangerous half of breach detection: a milestone recorded late announces itself, but
    one never recorded at all is silent precisely because nothing is happening. Intended to
    be driven by a scheduled job; `notify` is off by default so opening a screen does not
    quietly email people.
    """
    _require(current_user, Cap.ANALYTICS_READ)
    return await sla.sweep_open_breaches(
        current_user, _company(current_user, company_id), notify=notify)


@router.post("/requisitions/{request_no}/close")
async def close_requisition(
    request_no: str,
    body: RequisitionClose,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REQUISITION_CLOSE)
    return await requisitions.close_requisition(
        current_user, _company(current_user, company_id), request_no, body.status)


# =============================================================
# Phase 3 - Job Descriptions
# =============================================================
@router.get("/jd")
async def list_jds(
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """The JD library. JDs are authored with their requisition and approved together, so
    there is deliberately no create endpoint and no independent approve/reject path."""
    _require(current_user, Cap.JD_READ)
    return await requisitions.list_jds(
        current_user, _company(current_user, company_id),
        status=status, search=search, limit=limit)


@router.get("/jd/{jd_no}")
async def get_jd(
    jd_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.JD_READ)
    return await requisitions.get_jd(
        current_user, _company(current_user, company_id), jd_no)


@router.patch("/jd/{jd_no}")
async def update_jd(
    jd_no: str,
    body: JobDescriptionUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.JD_WRITE)
    return await requisitions.update_jd(
        current_user, _company(current_user, company_id), jd_no,
        body.model_dump(exclude_unset=True))


# =============================================================
# Phase 4 - Job Postings (authenticated side)
# =============================================================
@router.get("/postings")
async def list_postings(
    company_id: Optional[str] = Query(None),
    jd_no: Optional[str] = Query(None),
    live_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """Postings + KPI tiles. `application_count` is computed from candidates on every read,
    never stored, so it cannot drift from reality."""
    _require(current_user, Cap.POSTING_READ)
    return await postings.list_postings(
        current_user, _company(current_user, company_id),
        jd_no=jd_no, live_status=live_status, search=search, limit=limit)


@router.post("/postings", status_code=201)
async def create_posting(
    body: PostingIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Publish an APPROVED job description as ONE posting with ONE application link. The
    link is shared wherever the company likes; the form asks the applicant which channel
    they came through, and that answer becomes the candidate's source."""
    _require(current_user, Cap.POSTING_WRITE)
    return await postings.create_posting(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/postings/{code}")
async def update_posting(
    code: str,
    body: PostingUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.POSTING_WRITE)
    return await postings.update_posting(
        current_user, _company(current_user, company_id), code,
        body.model_dump(exclude_unset=True))


@router.delete("/postings/{code}")
async def delete_posting(
    code: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Remove a posting. Applications already received are KEPT -- deleting the channel must
    not delete the people who came through it."""
    _require(current_user, Cap.POSTING_WRITE)
    return await postings.delete_posting(
        current_user, _company(current_user, company_id), code)


# =============================================================
# Phase 5 - Candidates, screening, journey
# =============================================================
@router.get("/candidates")
async def list_candidates(
    company_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    posting_code: Optional[str] = Query(None),
    talent_pool: Optional[bool] = Query(
        None, description="Phase INT-2: only pooled candidates, or only unpooled ones."),
    tags: Optional[str] = Query(
        None, description="Comma-separated talent-pool tags. Matches ANY of them."),
    limit: int = Query(200, ge=1, le=500),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """The candidate pipeline. Row-scoped: a hiring manager sees only candidates on
    requisitions they raised. Column counts come from the same scoped query as the rows,
    so the board totals always match what the caller can open.

    `talent_pool` and `tags` are the Annexure C sourcing filter. The pool is deliberately a
    FILTER on this list rather than a collection of its own, so a pooled candidate keeps the
    same scoping, the same row security and the same retention as every other CV."""
    _require(current_user, Cap.CANDIDATE_READ)
    return await candidates.list_candidates(
        current_user, _company(current_user, company_id),
        search=search, status=status, request_no=request_no,
        posting_code=posting_code, talent_pool=talent_pool, tags=tags,
        limit=limit, skip=skip)


@router.post("/candidates", status_code=201)
async def create_candidate(
    body: CandidateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Add a candidate by hand -- a walk-in, referral or agency CV that never went through
    a public posting."""
    _require(current_user, Cap.CANDIDATE_WRITE)
    return await candidates.create_candidate(
        current_user, _company(current_user, company_id), body.model_dump(exclude_unset=True))


@router.post("/candidates/screen")
async def screen_candidates(
    body: ScreenIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Bulk triage: shortlist / review / hold / duplicate / reject / forward.

    Returns `moved` and `skipped` -- partial success is deliberate, so a batch where a few
    candidates sit at an incompatible stage still moves the rest and says which blocked.

    Declared before /candidates/{uk} so the static path wins.
    """
    _require(current_user, Cap.CANDIDATE_SCREEN)
    return await candidates.screen_candidates(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/candidates/{uk}")
async def get_candidate(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CANDIDATE_READ)
    return await candidates.get_candidate(
        current_user, _company(current_user, company_id), uk)


@router.patch("/candidates/{uk}")
async def update_candidate(
    uk: str,
    body: CandidateUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Edit a candidate, including moving their stage.

    A stage move is validated against the lifecycle graph -- an illegal jump (Applied ->
    Joined, say) is a 409 listing what IS allowed from here, not a silent write.
    """
    _require(current_user, Cap.CANDIDATE_WRITE)
    return await candidates.update_candidate(
        current_user, _company(current_user, company_id), uk,
        body.model_dump(exclude_unset=True))


@router.delete("/candidates/{uk}")
async def delete_candidate(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CANDIDATE_WRITE)
    return await candidates.delete_candidate(
        current_user, _company(current_user, company_id), uk)


@router.get("/candidates/{uk}/journey")
async def candidate_journey(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The candidate's full history, reconstructed from the audit trail.

    This is the only read path over the audit log a normal user reaches, and the reason
    every write since Phase 1 has been audited with a stable action name and entity id.
    """
    _require(current_user, Cap.CANDIDATE_READ)
    return await candidates.get_journey(
        current_user, _company(current_user, company_id), uk)


# =============================================================
# Phase 6 - Assessments (dual review)
# =============================================================
@router.get("/assessments")
async def list_assessments(
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    uk: Optional[str] = Query(None),
    mine: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Assessments + KPI tiles.

    Each row carries `my_slot`, `my_decision` and `awaiting_me`, so the UI knows whether
    THIS caller still owes a decision without re-deriving the dual-review rules client-side.
    `mine=true` narrows to exactly those.
    """
    _require(current_user, Cap.ASSESSMENT_READ)
    return await assessments.list_assessments(
        current_user, _company(current_user, company_id),
        status=status, uk=uk, mine=mine, limit=limit)


@router.get("/assessments/assessable")
async def assessable_candidates(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Candidates who may be sent an assessment -- those whose role REQUIRES one, who are at
    the assessment stage, and who have no open assessment already. Declared before
    /assessments/{no} so the static path wins."""
    _require(current_user, Cap.ASSESSMENT_SEND)
    return {"candidates": await assessments.assessable_candidates(
        current_user, _company(current_user, company_id))}


@router.post("/assessments", status_code=201)
async def send_assessment(
    body: AssessmentIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ASSESSMENT_SEND)
    return await assessments.send_assessment(
        current_user, _company(current_user, company_id), body.model_dump())


@router.post("/assessments/{assessment_no}/review")
async def review_assessment(
    assessment_no: str,
    body: AssessmentReviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record ONE reviewer's Pass/Fail.

    The caller fills the manager slot if they raised the requisition, otherwise the HR slot.
    The candidate advances only when every required slot has passed; either Fail decides it.
    """
    _require(current_user, Cap.ASSESSMENT_REVIEW)
    return await assessments.review_assessment(
        current_user, _company(current_user, company_id), assessment_no, body.model_dump())


# =============================================================
# Phase 7 - Interviews + scorecard evaluation
# =============================================================
@router.get("/interviews")
async def list_interviews(
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    round_name: Optional[str] = Query(None, alias="round"),
    uk: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """The interview feed, sorted for day-grouping.

    Deliberately NOT gated by `interview.read`. Seeing the interview you were booked for is
    an inherent right -- an interviewer who cannot open their own booking cannot do the job,
    and that must not be revocable by a permission edit. The capability WIDENS the list to
    the whole company; without it the service scopes you to your own.

    Each row carries `can_evaluate`, decided server-side, so the UI never offers a button
    the API will refuse.
    """
    return await interviews.list_interviews(
        current_user, _company(current_user, company_id),
        status=status, round_name=round_name, uk=uk, limit=limit)


@router.get("/interviews/schedulable")
async def schedulable_candidates(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Candidates who may be booked.

    Applies the SAME assessment gate the scheduler enforces, so the picker cannot offer
    somebody the API will refuse. Declared before /interviews/{no} so the static path wins.
    """
    _require(current_user, Cap.INTERVIEW_SCHEDULE)
    return {"candidates": await interviews.schedulable_candidates(
        current_user, _company(current_user, company_id))}


@router.post("/interviews", status_code=201)
async def schedule_interview(
    body: InterviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Book an interview.

    Blocked when the candidate's role requires an assessment they have not passed -- a 409
    naming the stage they are actually at.
    """
    _require(current_user, Cap.INTERVIEW_SCHEDULE)
    return await interviews.schedule_interview(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/interviews/{interview_no}")
async def update_interview(
    interview_no: str,
    body: InterviewUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Reschedule, move the venue, or set a status.

    Allowed to a scheduler OR the assigned interviewer. A reschedule bumps the calendar
    sequence so clients treat the new invite as an update, not a second booking.
    """
    return await interviews.update_interview(
        current_user, _company(current_user, company_id), interview_no,
        body.model_dump(exclude_unset=True))


@router.delete("/interviews/{interview_no}")
async def cancel_interview(
    interview_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Cancel an interview. Marked Cancelled, never deleted -- a dropped round is part of
    the hiring record and the candidate journey reads it."""
    return await interviews.cancel_interview(
        current_user, _company(current_user, company_id), interview_no)


@router.post("/interviews/{interview_no}/evaluate")
async def evaluate_interview(
    interview_no: str,
    body: InterviewEvaluateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record the scorecard and advance the candidate.

    Six competencies 0-5, a decision, and a REQUIRED typed signature. An MD round
    additionally requires `interview.decide_md` -- the final call is the MD's, whoever
    conducted the conversation.
    """
    return await interviews.evaluate_interview(
        current_user, _company(current_user, company_id), interview_no, body.model_dump())


@router.get("/interviews/{interview_no}/invite.ics")
async def interview_invite(
    interview_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Download the RFC 5545 invite for an interview.

    Served as a file rather than emailed as an attachment: the shared notification service
    has no attachment channel, and adding one would mean editing a module outside HRMS.
    A link also stays correct after a reschedule, whereas a mailed .ics goes stale.
    See PHASE_7_REPORT for the recommendation to add attachment support later.
    """
    from fastapi.responses import Response
    doc = await interviews._require_visible(
        current_user, _company(current_user, company_id), interview_no)
    body = interviews.invite_for(
        doc, cancelled=doc.get("status") == "Cancelled")
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{interview_no}.ics"'},
    )


# =============================================================
# Phase 8 - Offers
# =============================================================
@router.get("/offers")
async def list_offers(
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    uk: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Offers + KPI tiles.

    `ctc` is OMITTED for a caller without `employee.salary.read` — an offer is a
    compensation document, so it follows the same boundary Phase 2 drew for salary rather
    than inventing a second rule. The response reports `ctc_visible` so the UI knows.
    """
    _require(current_user, Cap.OFFER_READ)
    return await offers.list_offers(
        current_user, _company(current_user, company_id),
        status=status, uk=uk, limit=limit)


@router.get("/offers/offerable")
async def offerable_candidates(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Candidates who may be offered — Selected, and without a live offer already.
    Each carries a suggested CTC (JD → requisition → the candidate's expectation).
    Declared before /offers/{no} so the static path wins."""
    _require(current_user, Cap.OFFER_WRITE)
    return {"candidates": await offers.offerable_candidates(
        current_user, _company(current_user, company_id))}


@router.post("/offers", status_code=201)
async def create_offer(
    body: OfferIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Draft an offer. `send_now` drafts and issues in one action, which additionally
    requires `offer.send`."""
    _require(current_user, Cap.OFFER_WRITE)
    if body.send_now:
        _require(current_user, Cap.OFFER_SEND)
    return await offers.create_offer(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/offers/{offer_no}")
async def update_offer(
    offer_no: str,
    body: OfferUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Edit a DRAFT. Each edit archives the previous body and bumps the version, so what was
    offered at every point stays recoverable. Refused once sent."""
    _require(current_user, Cap.OFFER_WRITE)
    return await offers.update_offer(
        current_user, _company(current_user, company_id), offer_no,
        body.model_dump(exclude_unset=True))


@router.post("/offers/{offer_no}/send")
async def send_offer(
    offer_no: str,
    body: OfferSendIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Issue the offer. Requires an authorised signatory — the letter commits the company
    to a salary and must be attributable."""
    _require(current_user, Cap.OFFER_SEND)
    return await offers.send_offer(
        current_user, _company(current_user, company_id), offer_no, body.model_dump())


@router.post("/offers/{offer_no}/approve")
async def approve_offer(
    offer_no: str,
    body: OfferApproveIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Management's sign-off on an internal offer, mandatory before it can be sent.

    Separate from `offer.send` on purpose: verifying the figure sits inside the approved band
    says the offer is affordable; this says it should go out. Annexure B of the Internal
    Recruitment SOP makes the second one Management/Finance's call, not HR's.
    """
    _require(current_user, Cap.OFFER_APPROVE)
    return await offers.approve_offer(
        current_user, _company(current_user, company_id), offer_no, body.model_dump())


@router.post("/offers/{offer_no}/revoke")
async def revoke_offer(
    offer_no: str,
    body: OfferRevokeIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Withdraw a sent offer before the candidate responds."""
    _require(current_user, Cap.OFFER_SEND)
    return await offers.revoke_offer(
        current_user, _company(current_user, company_id), offer_no, body.model_dump())


@router.delete("/offers/{offer_no}")
async def delete_offer(
    offer_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Delete a DRAFT only. A sent offer is part of the hiring record — revoke it instead."""
    _require(current_user, Cap.OFFER_WRITE)
    return await offers.delete_offer(
        current_user, _company(current_user, company_id), offer_no)


# ─────────────────────────────────────────────────────────────
# Phase 9 — onboarding
# ─────────────────────────────────────────────────────────────
@router.get("/onboarding")
async def list_onboardings(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The onboarding board. The access code is deliberately absent — see the service."""
    _require(current_user, Cap.ONBOARDING_READ)
    return await onboarding.list_onboardings(
        current_user, _company(current_user, company_id), status=status, search=search)


@router.get("/onboarding/onboardable")
async def onboardable_candidates(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Candidates who have accepted an offer and are not yet being onboarded."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.onboardable_candidates(
        current_user, _company(current_user, company_id))


@router.get("/onboarding/{onb_no}")
async def get_onboarding(
    onb_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.ONBOARDING_READ)
    return await onboarding.get_onboarding(
        current_user, _company(current_user, company_id), onb_no)


@router.post("/onboarding", status_code=201)
async def start_onboarding(
    body: OnboardingIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Open an onboarding for a candidate who has accepted their offer. Mints the
    pre-onboarding link the new hire fills in."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.start_onboarding(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/onboarding/{onb_no}")
async def update_onboarding_details(
    onb_no: str,
    body: OnboardingDetailsIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Joining date, reporting manager, asset requirements."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.update_details(
        current_user, _company(current_user, company_id), onb_no,
        body.model_dump(exclude_unset=True))


@router.post("/onboarding/{onb_no}/bg")
async def update_onboarding_bg(
    onb_no: str,
    body: OnboardingBgIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record the background-verification outcome. Drives the `bg_cleared` checklist item in
    both directions — a withdrawn clearance un-ticks it."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.update_bg(
        current_user, _company(current_user, company_id), onb_no, body.model_dump())


@router.post("/onboarding/{onb_no}/verify")
async def verify_onboarding_documents(
    onb_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Confirm a human has checked the KYC documents. Required before an Employee ID."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.verify_documents(
        current_user, _company(current_user, company_id), onb_no)


@router.post("/onboarding/{onb_no}/documents")
async def add_onboarding_documents(
    onb_no: str,
    body: OnboardingDocumentsIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """HR-side KYC upload, for documents handed over in person or by email."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.add_documents(
        current_user, _company(current_user, company_id), onb_no, body.model_dump())


@router.post("/onboarding/{onb_no}/checklist")
async def set_onboarding_checklist(
    onb_no: str,
    body: OnboardingChecklistIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Tick or un-tick a joining-day task. The three system-owned items are refused here."""
    _require(current_user, Cap.ONBOARDING_WRITE)
    return await onboarding.set_checklist(
        current_user, _company(current_user, company_id), onb_no, body.model_dump())


@router.post("/onboarding/{onb_no}/generate-id")
async def generate_employee_id(
    onb_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Issue the Employee ID and create the employee record.

    Its own capability, separate from `onboarding.write`: this is the irreversible step that
    turns a candidate into an employee, and it should be possible to let someone run an
    onboarding without letting them create staff records.
    """
    _require(current_user, Cap.ONBOARDING_GENERATE_ID)
    return await onboarding.generate_employee_id(
        current_user, _company(current_user, company_id), onb_no)


@router.post("/employees/link/{employee_code}")
async def link_employee_user(
    employee_code: str,
    body: EmployeeLinkIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Attach an onboarding-created employee record to a real login account.

    Gated on `employee.write` because it changes who an employee record IS — from that point
    the user document is the single source of identity.
    """
    _require(current_user, Cap.EMPLOYEE_WRITE)
    return await employees.link_user(
        current_user, _company(current_user, company_id), employee_code, body.user_id)


# ─────────────────────────────────────────────────────────────
# Phase 10 — analytics & reports (READ-ONLY)
# ─────────────────────────────────────────────────────────────
@router.get("/analytics/dashboard")
async def analytics_dashboard(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    # Phase 11-R, Item 4: optional client filter. Absent -> the existing company-wide
    # behaviour, unchanged, plus a per-client comparison table in the payload.
    client_id: Optional[str] = Query(None),
    track: Optional[str] = Query(None, description="internal — adds the SOP §10 KPI block"),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Headline KPIs, positions summary, offer outcomes and time-to-hire.

    A hiring manager gets the same shape scoped to their own requisitions — the response
    says so via `scoped_to_own_requisitions`, so the UI can label the numbers honestly
    rather than implying they are company-wide.

    `track=internal` adds `internal_kpis`, the Internal Recruitment SOP's own dashboard.
    Omitting it leaves the payload byte-for-byte what every existing caller receives.
    """
    _require(current_user, Cap.ANALYTICS_READ)
    return await analytics.dashboard(
        current_user, _company(current_user, company_id),
        date_from=date_from, date_to=date_to, client_id=client_id, track=track)


@router.get("/analytics/funnel")
async def analytics_funnel(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The hiring funnel by EFFECTIVE rank, so it can never show more offers than
    interviews. See models/hrms.py STAGE_RANK."""
    _require(current_user, Cap.ANALYTICS_READ)
    return await analytics.funnel(
        current_user, _company(current_user, company_id),
        date_from=date_from, date_to=date_to, client_id=client_id)


@router.get("/analytics/breakdown")
async def analytics_breakdown(
    by: BreakdownBy = Query(BreakdownBy.SOURCE),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Group counts along one allow-listed dimension."""
    _require(current_user, Cap.ANALYTICS_READ)
    return await analytics.breakdown(
        current_user, _company(current_user, company_id), by.value,
        date_from=date_from, date_to=date_to, client_id=client_id)


@router.get("/reports/{entity}")
async def hrms_report(
    entity: ReportEntity,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_REPORT_PAGE_SIZE, ge=1, le=MAX_REPORT_PAGE_SIZE),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One page of a detailed report. `entity` is an enum, not a collection name."""
    _require(current_user, Cap.REPORT_READ)
    return await analytics.report(
        current_user, _company(current_user, company_id), entity.value,
        page=page, page_size=page_size, search=search,
        date_from=date_from, date_to=date_to, client_id=client_id)


@router.get("/reports/{entity}/export")
async def hrms_report_export(
    entity: ReportEntity,
    fmt: ExportFormat = Query(ExportFormat.CSV),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Download a report.

    Its own capability, separate from `report.read`: reading aggregate figures on screen
    and taking a file of personal data off the system are different acts, and a hiring
    manager is deliberately granted the first and not the second.

    Rendered server-side from already-scoped rows. Building the file in the browser would
    mean shipping rows the API had correctly withheld.
    """
    _require(current_user, Cap.REPORT_EXPORT)
    payload = await analytics.export_rows(
        current_user, _company(current_user, company_id), entity.value,
        search=search, date_from=date_from, date_to=date_to, client_id=client_id)

    if fmt == ExportFormat.XLSX:
        body = analytics.render_xlsx(payload)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        body = analytics.render_csv(payload)
        media = "text/csv; charset=utf-8"

    filename = analytics.export_filename(entity.value, fmt.value, payload["range"])
    return StreamingResponse(
        iter([body]),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Truncation is announced in a header AND inside the file, so it cannot be
            # missed by whichever one the recipient looks at.
            "X-Export-Truncated": "true" if payload["truncated"] else "false",
            "X-Export-Rows": str(payload["returned"]),
            "X-Export-Total": str(payload["total"]),
        },
    )


# =============================================================================
# Phase 11-R — recruitment review enhancements
# =============================================================================
# Seven items, appended as one block so the phase's whole API surface is readable in one
# place. Every endpoint follows the existing conventions without exception:
#   * `_require(user, Cap.X)` and nothing else decides permission,
#   * `_company(user, company_id)` pins the tenant (a client-side caller's company_id
#     query param is IGNORED, not honoured),
#   * static paths are declared BEFORE their `{param}` siblings so they win the match.
# No pre-existing route above is modified except by the addition of an OPTIONAL `client_id`
# query parameter on the analytics/report endpoints, which defaults to None and therefore
# leaves their existing behaviour byte-identical.

# ─────────────────────────────────────────────────────────────
# Item 1 — the public-link registry
# ─────────────────────────────────────────────────────────────
@router.get("/links")
async def list_hrms_links(
    kind: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    skip: int = Query(0, ge=0),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Every public link this company has issued, with its open count and live status.

    Status is COMPUTED per row (an expired link reads Expired without a nightly job), so
    the `status` filter is applied after projection — see hrms_link_service.list_links.
    A hiring manager sees links for their own requisitions only.
    """
    _require(current_user, Cap.LINK_READ)
    return await links.list_links(
        current_user, _company(current_user, company_id),
        kind=kind, status=status, search=search,
        date_from=date_from, date_to=date_to, limit=limit, skip=skip)


@router.get("/links/{link_id}")
async def get_hrms_link(
    link_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One link plus its open history (count, first sighting, last sighting)."""
    _require(current_user, Cap.LINK_READ)
    return await links.get_link(current_user, _company(current_user, company_id), link_id)


@router.post("/links/{link_id}/revoke")
async def revoke_hrms_link(
    link_id: str,
    body: LinkRevokeIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Kill a live link. The public handlers refuse it from the next request onward —
    revocation here is ENFORCED by `assert_link_live`, not merely displayed."""
    _require(current_user, Cap.LINK_MANAGE)
    return await links.revoke(
        current_user, _company(current_user, company_id), link_id, body.reason)


@router.post("/links/{link_id}/reissue")
async def reissue_hrms_link(
    link_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Mint a fresh credential for the same record and revoke the old one.

    Delegates to the owning service so the new code is one that service knows about.
    An `apply` link cannot be reissued — its code is printed on published job ads.
    """
    _require(current_user, Cap.LINK_MANAGE)
    return await links.reissue(current_user, _company(current_user, company_id), link_id)


# ─────────────────────────────────────────────────────────────
# Item 2 — documentation
# ─────────────────────────────────────────────────────────────
@router.get("/document-types")
async def list_hrms_document_types(
    include_inactive: bool = Query(False),
    applies_to: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The company's document-type master. Seeds a sensible default set on first read."""
    _require(current_user, Cap.DOCUMENT_READ)
    return {"document_types": await documents.list_document_types(
        _company(current_user, company_id),
        include_inactive=include_inactive, applies_to=applies_to)}


@router.post("/document-types", status_code=201)
async def create_hrms_document_type(
    body: DocumentTypeIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DOCUMENT_WRITE)
    return await documents.create_document_type(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/document-types/{type_id}")
async def update_hrms_document_type(
    type_id: str,
    body: DocumentTypeUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DOCUMENT_WRITE)
    return await documents.update_document_type(
        current_user, _company(current_user, company_id), type_id,
        body.model_dump(exclude_unset=True))


@router.delete("/document-types/{type_id}")
async def delete_hrms_document_type(
    type_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Blocked while any document still references the type — deactivate instead."""
    _require(current_user, Cap.DOCUMENT_WRITE)
    return await documents.delete_document_type(
        current_user, _company(current_user, company_id), type_id)


@router.get("/documents")
async def list_hrms_documents(
    owner_type: Optional[str] = Query(None),
    owner_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    type_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    expiring_soon: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    skip: int = Query(0, ge=0),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The document register. Expiry is computed per row, so the `status` filter runs
    after projection."""
    _require(current_user, Cap.DOCUMENT_READ)
    return await documents.list_documents(
        current_user, _company(current_user, company_id),
        owner_type=owner_type, owner_id=owner_id, status=status, type_id=type_id,
        search=search, expiring_soon=expiring_soon, limit=limit, skip=skip)


@router.get("/documents/checklist")
async def hrms_document_checklist(
    owner_type: str = Query(...),
    owner_id: str = Query(...),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Every applicable type for this person, with its status or `Pending`, plus the
    read-only view over files already attached elsewhere (resume, KYC scans).

    Declared before /documents/{doc_no} so the static path wins.
    """
    _require(current_user, Cap.DOCUMENT_READ)
    return await documents.checklist(
        current_user, _company(current_user, company_id), owner_type, owner_id)


@router.post("/documents", status_code=201)
async def upload_hrms_document(
    body: DocumentIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Upload a document, or a new version of one (supply `doc_no` for a version)."""
    _require(current_user, Cap.DOCUMENT_WRITE)
    return await documents.upload_document(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/documents/{doc_no}")
async def get_hrms_document(
    doc_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.DOCUMENT_READ)
    return await documents.get_document(
        current_user, _company(current_user, company_id), doc_no)


@router.patch("/documents/{doc_no}")
async def update_hrms_document(
    doc_no: str,
    body: DocumentUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Metadata only. The file is immutable — replacing it means adding a version."""
    _require(current_user, Cap.DOCUMENT_WRITE)
    return await documents.update_document(
        current_user, _company(current_user, company_id), doc_no,
        body.model_dump(exclude_unset=True))


@router.post("/documents/{doc_no}/status")
async def set_hrms_document_status(
    doc_no: str,
    body: DocumentStatusIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Verify, reject or move a document to Under Review.

    Its own capability, separate from `document.write`: collecting paperwork and ATTESTING
    to it are different acts, and Sparsh support staff deliberately hold the first and not
    the second — the same boundary that keeps REQUISITION_REVIEW_HR off the INTERNAL list.
    """
    _require(current_user, Cap.DOCUMENT_VERIFY)
    return await documents.set_status(
        current_user, _company(current_user, company_id), doc_no, body.model_dump())


@router.get("/documents/{doc_no}/url")
async def hrms_document_url(
    doc_no: str,
    version: Optional[int] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """A short-lived signed URL, minted per request. Never stored — see the service."""
    _require(current_user, Cap.DOCUMENT_READ)
    return await documents.signed_url(
        current_user, _company(current_user, company_id), doc_no, version)


@router.delete("/documents/{doc_no}")
async def delete_hrms_document(
    doc_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Remove a register row. A VERIFIED document is refused — reject it instead."""
    _require(current_user, Cap.DOCUMENT_WRITE)
    return await documents.delete_document(
        current_user, _company(current_user, company_id), doc_no)


# ─────────────────────────────────────────────────────────────
# Item 3 — appointment letters
# ─────────────────────────────────────────────────────────────
@router.get("/appointments")
async def list_hrms_appointments(
    status: Optional[str] = Query(None),
    uk: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Appointment letters + KPI tiles. `ctc` is omitted without `employee.salary.read`,
    the same boundary Phase 8 draws for offers."""
    _require(current_user, Cap.APPOINTMENT_READ)
    return await appointments.list_appointments(
        current_user, _company(current_user, company_id),
        status=status, uk=uk, search=search, limit=limit)


@router.get("/appointments/eligible")
async def appointable_candidates(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Candidates who have accepted an offer and have no live letter yet.
    Declared before /appointments/{no} so the static path wins."""
    _require(current_user, Cap.APPOINTMENT_READ)
    return {"candidates": await appointments.eligible_candidates(
        current_user, _company(current_user, company_id))}


@router.post("/appointments", status_code=201)
async def create_hrms_appointment(
    body: AppointmentIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Draft an appointment letter, defaulting every term from the accepted offer."""
    _require(current_user, Cap.APPOINTMENT_WRITE)
    return await appointments.create_appointment(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/appointments/{appointment_no}")
async def get_hrms_appointment(
    appointment_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.APPOINTMENT_READ)
    return await appointments.get_appointment(
        current_user, _company(current_user, company_id), appointment_no)


@router.patch("/appointments/{appointment_no}")
async def update_hrms_appointment(
    appointment_no: str,
    body: AppointmentUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Edit a GENERATED letter. Refused once sent — the candidate is reading it."""
    _require(current_user, Cap.APPOINTMENT_WRITE)
    return await appointments.update_appointment(
        current_user, _company(current_user, company_id), appointment_no,
        body.model_dump(exclude_unset=True))


@router.post("/appointments/{appointment_no}/send")
async def send_hrms_appointment(
    appointment_no: str,
    body: AppointmentSendIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Issue the letter.

    Its own capability, separate from `appointment.write`: authoring a letter and COMMITTING
    the company to employing somebody are different acts — exactly the split Phase 8 draws
    between OFFER_WRITE and OFFER_SEND.
    """
    _require(current_user, Cap.APPOINTMENT_SEND)
    return await appointments.send_appointment(
        current_user, _company(current_user, company_id), appointment_no,
        body.model_dump())


@router.post("/appointments/{appointment_no}/cancel")
async def cancel_hrms_appointment(
    appointment_no: str,
    body: AppointmentCancelIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Withdraw a letter and revoke its public link. An ACKNOWLEDGED letter is refused."""
    _require(current_user, Cap.APPOINTMENT_SEND)
    return await appointments.cancel_appointment(
        current_user, _company(current_user, company_id), appointment_no,
        body.model_dump())


# ─────────────────────────────────────────────────────────────
# Item 4 — the client dimension (READ-ONLY) + client sharing
# ─────────────────────────────────────────────────────────────
# Clients are the ERP's existing Companies. There is deliberately no create/update/delete
# here: a second way to enter an organisation is a second list to keep in step, and the
# Companies module already owns that job. Editing a client means editing the company.
@router.get("/clients")
async def list_hrms_clients(
    include_inactive: bool = Query(False),
    search: Optional[str] = Query(None),
    with_stats: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Companies that can be named as the client of a requisition.

    NOTE: a client is NOT a tenant. `company_id` remains the only security boundary;
    `client_id` is a reporting dimension inside one tenant (see hrms_client_service).
    """
    _require(current_user, Cap.CLIENT_READ)
    return await clients.list_clients(
        current_user, _company(current_user, company_id),
        include_inactive=include_inactive, search=search, with_stats=with_stats)


# ─────────────────────────────────────────────────────────────
# Client engagements — the tenant/client relationship
# ─────────────────────────────────────────────────────────────
# `GET /clients` above lists COMPANIES, which is what you pick FROM when opening an
# engagement. These routes list and manage the engagements themselves: which of those
# companies are actually ours to recruit for, and which of our users work on each.
#
# Every one is scoped by `_company()`, so a client-side caller is pinned to their own
# tenant and an engagement belonging to another company is never read, let alone filtered
# out afterwards.
@router.get("/client-engagements")
async def list_client_engagements(
    status: Optional[str] = Query(None),
    include_ended: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The clients this tenant has engaged."""
    _require(current_user, Cap.CLIENT_READ)
    return await clients.list_engagements(
        current_user, _company(current_user, company_id),
        status=status, include_ended=include_ended)


@router.post("/client-engagements", status_code=201)
async def create_client_engagement(
    body: ClientEngagementIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record that this tenant recruits for that company.

    Creates no company and duplicates no company data -- `client_id` stays a
    `companies._id`. What is new is the RELATIONSHIP, which exists nowhere in the ERP.
    """
    _require(current_user, Cap.CLIENT_WRITE)
    return await clients.create_engagement(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/client-engagements/{engagement_id}")
async def get_client_engagement(
    engagement_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_READ)
    doc = await clients.get_engagement(_company(current_user, company_id), engagement_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Engagement not found.")
    return doc


@router.patch("/client-engagements/{engagement_id}")
async def update_client_engagement(
    engagement_id: str,
    body: ClientEngagementUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Suspending or ending an engagement revokes its members' scope immediately."""
    _require(current_user, Cap.CLIENT_WRITE)
    return await clients.update_engagement(
        current_user, _company(current_user, company_id), engagement_id,
        body.model_dump(exclude_unset=True))


@router.get("/client-engagements/{engagement_id}/members")
async def list_client_engagement_members(
    engagement_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_READ)
    return await clients.list_engagement_members(
        _company(current_user, company_id), engagement_id)


@router.post("/client-engagements/{engagement_id}/members", status_code=201)
async def add_client_engagement_member(
    engagement_id: str,
    body: EngagementMemberIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Give one user access to one client's recruitment.

    The user must belong to this same company -- client scope narrows INSIDE the tenant
    boundary and never reaches across it.
    """
    _require(current_user, Cap.CLIENT_WRITE)
    return await clients.add_engagement_member(
        current_user, _company(current_user, company_id), engagement_id, body.user_id)


@router.delete("/client-engagements/{engagement_id}/members/{user_id}")
async def remove_client_engagement_member(
    engagement_id: str,
    user_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_WRITE)
    return await clients.remove_engagement_member(
        current_user, _company(current_user, company_id), engagement_id, user_id)


@router.get("/clients/{client_id}")
async def get_hrms_client(
    client_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_READ)
    scoped = _company(current_user, company_id)
    doc = await clients.get_client(client_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Client not found.")
    # The summary IS tenant-scoped even though the company record is not: it counts this
    # tenant's requisitions and candidates for that client, nobody else's.
    doc["summary"] = await clients.client_summary(scoped, client_id)
    return doc


# ─────────────────────────────────────────────────────────────
# Internal track — position scorecards
# ─────────────────────────────────────────────────────────────
# HR drafts, the hiring manager approves, and for managerial+ roles Management approves too
# (Internal Recruitment SOP, Annexure B). The scorecard IS the bar candidates are measured
# against, so an approved one is frozen and the requisition cannot be approved without it.
@router.get("/scorecards")
async def list_scorecards(
    request_no: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SCORECARD_READ)
    return await scorecards.list_scorecards(
        current_user, _company(current_user, company_id),
        request_no=request_no, status=status, limit=limit)


@router.post("/scorecards", status_code=201)
async def create_scorecard(
    body: ScorecardIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SCORECARD_WRITE)
    return await scorecards.create_scorecard(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/scorecards/{scr_no}")
async def get_scorecard(
    scr_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SCORECARD_READ)
    doc = await scorecards.get_scorecard(_company(current_user, company_id), scr_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Scorecard not found.")
    return doc


@router.patch("/scorecards/{scr_no}")
async def update_scorecard(
    scr_no: str,
    body: ScorecardUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SCORECARD_WRITE)
    return await scorecards.update_scorecard(
        current_user, _company(current_user, company_id), scr_no,
        body.model_dump(exclude_unset=True))


@router.post("/scorecards/{scr_no}/approve")
async def approve_scorecard(
    scr_no: str,
    body: ScorecardApproveIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One approval signature. The scorecard completes when every required role has signed."""
    _require(current_user, Cap.SCORECARD_APPROVE)
    return await scorecards.approve_scorecard(
        current_user, _company(current_user, company_id), scr_no, body.model_dump())


@router.post("/candidates/{uk}/scorecard-evaluate")
async def evaluate_against_scorecard(
    uk: str,
    body: ScorecardEvaluateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Score a candidate against their requisition's scorecard.

    Records the weighted score and its band; deliberately does NOT move the candidate. The
    band is advice for whoever reads it, not an instruction to the pipeline.
    """
    _require(current_user, Cap.CANDIDATE_SCREEN)
    return await scorecards.evaluate_candidate(
        current_user, _company(current_user, company_id), uk, body.model_dump())


# ─────────────────────────────────────────────────────────────
# Internal track — reference checks
# ─────────────────────────────────────────────────────────────
# Mandatory before an internal offer (SOP §6). A candidate may have several referees; the
# offer gate asks whether ANY of them cleared.
@router.get("/reference-checks")
async def list_reference_checks(
    uk: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REFERENCE_READ)
    return await references.list_reference_checks(
        current_user, _company(current_user, company_id),
        uk=uk, request_no=request_no, outcome=outcome, limit=limit)


@router.post("/reference-checks", status_code=201)
async def create_reference_check(
    body: ReferenceCheckIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REFERENCE_WRITE)
    return await references.create_reference_check(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/reference-checks/{ref_no}")
async def get_reference_check(
    ref_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REFERENCE_READ)
    doc = await references.get_reference_check(_company(current_user, company_id), ref_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Reference check not found.")
    return doc


@router.patch("/reference-checks/{ref_no}")
async def update_reference_check(
    ref_no: str,
    body: ReferenceCheckUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REFERENCE_WRITE)
    return await references.update_reference_check(
        current_user, _company(current_user, company_id), ref_no,
        body.model_dump(exclude_unset=True))


# ─────────────────────────────────────────────────────────────
# Per-company configuration (Phase INT-5, spec §42)
# ─────────────────────────────────────────────────────────────
# The rules this company runs by: SLA targets, retention periods, probation duration,
# reminder tiers and score band floors. READ is wide because a target you cannot see is one
# you cannot plan against; WRITE is Management's and Finance's, because Annexure B makes
# them "A" on policy review and these numbers are that policy expressed as data.
#
# No setting here turns a GATE off. The budget gate, the reference check, the scorecard
# approval and the telephonic screen are the controls the SOP is made of; a deviation goes
# through the exception log, where it is attributable.
@router.get("/settings")
async def get_hrms_settings(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SETTINGS_READ)
    return await config_svc.describe(_company(current_user, company_id))


@router.patch("/settings")
async def update_hrms_settings(
    body: ConfigUpdateIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SETTINGS_WRITE)
    return await config_svc.update_config(
        current_user, _company(current_user, company_id),
        body.model_dump(exclude_unset=True, exclude_none=True))


@router.post("/settings/reset")
async def reset_hrms_settings(
    body: ConfigResetIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Follow the module defaults again. Distinct from setting a value that HAPPENS to equal
    the default -- a stored value stays where it was put if the default ever moves."""
    _require(current_user, Cap.SETTINGS_WRITE)
    return await config_svc.reset_config(
        current_user, _company(current_user, company_id), body.keys)


# ─────────────────────────────────────────────────────────────
# The internal requisition tracker (Phase INT-7, Annexure C)
# ─────────────────────────────────────────────────────────────
# "Maintain a shared internal requisition tracker (status, scores, budget approval date)
# visible to HR, Department Head, and Management." One row per internal requisition, every
# stage rolled up, computed entirely server-side.
#
# Gated on `requisition.read` and scoped by the SAME visibility rule the requisition list
# uses, so a user never sees a row here they could not open there. Read-only by
# construction -- see hrms_tracker_service.
@router.get("/internal-requisitions/tracker")
async def internal_requisition_tracker(
    status: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None),
    sla: Optional[str] = Query(None, description="breached | on_track | met | not_started"),
    limit: int = Query(100, ge=1, le=200),
    skip: int = Query(0, ge=0),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.REQUISITION_READ)
    return await tracker_svc.tracker(
        current_user, _company(current_user, company_id),
        status=status, department_id=department_id, sla=sla, limit=limit, skip=skip)


# ─────────────────────────────────────────────────────────────
# The working calendar (Phase INT-6, spec §26)
# ─────────────────────────────────────────────────────────────
# The dates SLA maths skips, for THIS company. Gated on the same capabilities as the rest of
# the rule set: a holiday moves a compliance due date, so it belongs with the numbers it
# moves rather than with the operational screens.
#
# HRMS's own calendar, never the ERP's global `holidays` master -- that collection has no
# company_id, so pointing per-company figures at it would let one admin's edit move every
# entity's due dates. `/import` ADOPTS dates from it as a copy.
@router.get("/holidays")
async def list_hrms_holidays(
    year: Optional[int] = Query(None, ge=1970, le=2200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SETTINGS_READ)
    return await holidays_svc.list_holidays(
        _company(current_user, company_id), year=year)


@router.post("/holidays", status_code=201)
async def add_hrms_holiday(
    body: HolidayIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SETTINGS_WRITE)
    return await holidays_svc.add_holiday(
        current_user, _company(current_user, company_id), body.model_dump())


@router.post("/holidays/import")
async def import_hrms_holidays(
    body: HolidayImportIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Adopt one year of the ERP's global calendar. Safe to run twice — dates already on
    this calendar are reported as skipped rather than refused."""
    _require(current_user, Cap.SETTINGS_WRITE)
    return await holidays_svc.import_from_erp(
        current_user, _company(current_user, company_id), year=body.year)


@router.delete("/holidays/{holiday_date}")
async def remove_hrms_holiday(
    holiday_date: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SETTINGS_WRITE)
    return await holidays_svc.remove_holiday(
        current_user, _company(current_user, company_id), holiday_date)


# ─────────────────────────────────────────────────────────────
# Internal track — salary negotiation (SOP step 9, spec §16)
# ─────────────────────────────────────────────────────────────
# The RECORD of the rounds. The RULE lives on the offer (`assert_within_band`) and does not
# move: recording an above-band round is allowed, issuing an offer at it is not, until the
# budget is re-approved or an Offer Outside Budget exception is approved.
@router.get("/negotiations")
async def list_negotiation_rounds(
    uk: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.NEGOTIATION_READ)
    return await negotiation.list_rounds(
        current_user, _company(current_user, company_id),
        uk=uk, request_no=request_no, limit=limit)


@router.post("/negotiations", status_code=201)
async def record_negotiation_round(
    body: NegotiationRoundIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.NEGOTIATION_WRITE)
    return await negotiation.record_round(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/negotiations/{neg_no}")
async def get_negotiation_round(
    neg_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.NEGOTIATION_READ)
    doc = await negotiation.get_round(_company(current_user, company_id), neg_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Negotiation round not found.")
    return doc


@router.get("/candidates/{uk}/negotiation")
async def candidate_negotiation(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The spec §16 comparison surface: band, latest round, within/above/below, and whether
    an offer at the latest figure would pass the band gate today."""
    _require(current_user, Cap.NEGOTIATION_READ)
    return await negotiation.negotiation_for(
        current_user, _company(current_user, company_id), uk)


# ─────────────────────────────────────────────────────────────
# Internal track — telephonic screening (SOP step 5)
# ─────────────────────────────────────────────────────────────
# The brief call HR makes between CV screening and the panel. `telephonic.write` is HR's
# alone (Annexure B marks HR "R" and everybody else "I"); the HOD reads it because they
# interview off the back of it.
#
# The GATE this feeds lives on interview scheduling, not here -- see
# hrms_telephonic_service.assert_telephonic_cleared.
@router.get("/telephonic-screenings")
async def list_telephonic_screenings(
    uk: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.TELEPHONIC_READ)
    return await telephonic.list_screenings(
        current_user, _company(current_user, company_id),
        uk=uk, request_no=request_no, outcome=outcome, limit=limit)


# Declared BEFORE /telephonic-screenings/{tel_no}, or "screenable" is parsed as a tel_no --
# the same ordering /interviews/schedulable and /offers/offerable rely on.
@router.get("/telephonic-screenings/screenable")
async def screenable_candidates(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.TELEPHONIC_READ)
    return await telephonic.screenable_candidates(
        current_user, _company(current_user, company_id))


@router.post("/telephonic-screenings", status_code=201)
async def create_telephonic_screening(
    body: TelephonicScreeningIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.TELEPHONIC_WRITE)
    return await telephonic.create_screening(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/telephonic-screenings/{tel_no}")
async def get_telephonic_screening(
    tel_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.TELEPHONIC_READ)
    doc = await telephonic.get_screening(_company(current_user, company_id), tel_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Telephonic screening not found.")
    return doc


@router.patch("/telephonic-screenings/{tel_no}")
async def update_telephonic_screening(
    tel_no: str,
    body: TelephonicScreeningUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.TELEPHONIC_WRITE)
    return await telephonic.update_screening(
        current_user, _company(current_user, company_id), tel_no,
        body.model_dump(exclude_unset=True))


# ─────────────────────────────────────────────────────────────
# Internal track — probation and personnel-file closure
# ─────────────────────────────────────────────────────────────
# Probation is an EMPLOYEE event, not a recruitment stage: the candidate lifecycle ends at
# joining. See hrms_probation_service for why no AppStatus was added.
@router.get("/probation")
async def list_probations(
    outcome: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PROBATION_READ)
    return await probation.list_probations(
        current_user, _company(current_user, company_id),
        outcome=outcome, request_no=request_no, limit=limit)


@router.get("/probation/due")
async def due_probations(
    within_days: int = Query(30, ge=0, le=365),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Reviews that are overdue, and those falling due inside the window.

    Split rather than merged: a missed commitment and a diary entry are two different
    conversations, and one date-sorted list leaves the reader to tell them apart.
    """
    _require(current_user, Cap.PROBATION_READ)
    return await probation.due_probations(
        current_user, _company(current_user, company_id), within_days=within_days)


@router.post("/probation", status_code=201)
async def open_probation(
    body: ProbationIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Open a review by hand. Internal-track joiners get one automatically at handover."""
    _require(current_user, Cap.PROBATION_REVIEW)
    return await probation.open_probation(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/probation/{prb_no}")
async def get_probation(
    prb_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PROBATION_READ)
    doc = await probation.get_probation(_company(current_user, company_id), prb_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Probation review not found.")
    return doc


@router.patch("/probation/{prb_no}")
async def update_probation(
    prb_no: str,
    body: ProbationUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PROBATION_REVIEW)
    return await probation.update_probation(
        current_user, _company(current_user, company_id), prb_no,
        body.model_dump(exclude_unset=True))


@router.post("/probation/{prb_no}/confirm")
async def confirm_probation(
    prb_no: str,
    body: ProbationConfirmIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Confirm, extend or end a probation.

    The hiring manager's call (Annexure B: "Probation review & confirmation -- Department
    Head: A/R"). A confirmation closes the internal requisition as Hired, because there is no
    client handover on this track.
    """
    _require(current_user, Cap.PROBATION_CONFIRM)
    return await probation.confirm_probation(
        current_user, _company(current_user, company_id), prb_no, body.model_dump())


@router.post("/personnel-file/close")
async def close_personnel_file(
    body: PersonnelFileCloseIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record that the personnel file has been checked and closed (SOP §7, §9)."""
    _require(current_user, Cap.PERSONNEL_FILE_CLOSE)
    return await probation.close_personnel_file(
        current_user, _company(current_user, company_id), body.model_dump())


# ─────────────────────────────────────────────────────────────
# Internal track — the exception log
# ─────────────────────────────────────────────────────────────
# An APPROVED exception is the only thing that lifts the reference-check and salary-band
# gates. There is deliberately no override flag on either of those endpoints: a boolean in a
# payload records nothing and attributes nothing.
@router.get("/exceptions")
async def list_exceptions(
    request_no: Optional[str] = Query(None),
    uk: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    exception_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.EXCEPTION_READ)
    return await exceptions.list_exceptions(
        current_user, _company(current_user, company_id),
        request_no=request_no, uk=uk, status=status,
        exception_type=exception_type, limit=limit)


@router.post("/exceptions", status_code=201)
async def raise_exception(
    body: ExceptionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Log a deviation for approval. Raising one grants nothing until it is approved."""
    _require(current_user, Cap.EXCEPTION_WRITE)
    return await exceptions.raise_exception(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/exceptions/{exc_no}")
async def get_exception(
    exc_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.EXCEPTION_READ)
    doc = await exceptions.get_exception(_company(current_user, company_id), exc_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Exception not found.")
    return doc


@router.post("/exceptions/{exc_no}/approve")
async def decide_exception(
    exc_no: str,
    body: ExceptionDecisionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Approve or reject. Management/Finance only, and never the person who raised it."""
    _require(current_user, Cap.EXCEPTION_APPROVE)
    return await exceptions.decide_exception(
        current_user, _company(current_user, company_id), exc_no, body.model_dump())


@router.post("/candidates/client-response")
async def record_client_response(
    body: ClientResponseIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record the hiring client's verdict on a shared CV.

    Gated on `candidate.screen` rather than a new capability: this IS a screening decision,
    made by the client and entered on their behalf. A separate capability would let somebody
    hold one without the other for no coherent reason.
    """
    _require(current_user, Cap.CANDIDATE_SCREEN)
    return await candidates.record_client_response(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/analytics/positions")
async def analytics_positions(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The position-wise CV status matrix: one row per requisition, one column per stage.

    Same `_scope`, same SCAN_CAP and the same window validation as every other analytics
    endpoint. Read-only.
    """
    _require(current_user, Cap.ANALYTICS_READ)
    return await analytics.positions(
        current_user, _company(current_user, company_id),
        date_from=date_from, date_to=date_to, client_id=client_id)


# ─────────────────────────────────────────────────────────────
# Item 7 — sanctioned strength
# ─────────────────────────────────────────────────────────────
@router.get("/sanctioned-strength")
async def list_sanctioned_strength(
    department_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Every sanctioned figure, each with its LIVE actual headcount and availability.

    `actual` is counted from employee profiles on every read and never stored — a stored
    figure would be wrong the moment somebody resigned, which is exactly when it is asked.
    """
    _require(current_user, Cap.SANCTION_READ)
    return await sanctions.list_sanctions(
        _company(current_user, company_id), department_id=department_id)


@router.get("/sanctioned-strength/position")
async def sanctioned_position(
    department_id: str = Query(...),
    designation_id: str = Query(...),
    requested: int = Query(0, ge=0),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The live sanctioned/actual/available readout for one position.

    Read by the requisition form on every change, so the raiser is told BEFORE they submit
    that the request will be escalated. Declared before /{sanction_id} so the static path
    wins.
    """
    _require(current_user, Cap.SANCTION_READ)
    return await sanctions.position_status(
        _company(current_user, company_id), department_id, designation_id,
        requested=requested)


@router.post("/sanctioned-strength", status_code=201)
async def set_sanctioned_strength(
    body: SanctionedStrengthIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Create or replace the sanctioned figure for a position (an upsert — one figure per
    position is the rule, enforced by a unique index)."""
    _require(current_user, Cap.SANCTION_WRITE)
    return await sanctions.set_sanction(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/sanctioned-strength/{sanction_id}")
async def update_sanctioned_strength(
    sanction_id: str,
    body: SanctionedStrengthUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SANCTION_WRITE)
    return await sanctions.update_sanction(
        current_user, _company(current_user, company_id), sanction_id,
        body.model_dump(exclude_unset=True))


@router.delete("/sanctioned-strength/{sanction_id}")
async def delete_sanctioned_strength(
    sanction_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Remove a sanctioned figure. The position then has none, which means every future
    requisition for it is routed for escalation — the response says so explicitly."""
    _require(current_user, Cap.SANCTION_WRITE)
    return await sanctions.delete_sanction(
        current_user, _company(current_user, company_id), sanction_id)


# ═════════════════════════════════════════════════════════════
# Phase INT-2 — the remaining Internal Recruitment SOP controls
# ═════════════════════════════════════════════════════════════
# Every endpoint below is additive and internal-track only. None of them changes a status
# code, a payload or a message on any pre-existing route, and none of them is reachable for
# a client-track requisition -- the services refuse one outright rather than half-applying
# a control the client track has no counterpart for.


# ─────────────────────────────────────────────────────────────
# INT-2.1 — the internal shortlisting committee (SOP §5)
# ─────────────────────────────────────────────────────────────
# HR and the Department Head jointly finalise the shortlist. Two roles, two DIFFERENT
# people, and a finalised record is what lifts the gate on `Selected`.
@router.get("/shortlist-reviews")
async def list_shortlist_reviews(
    request_no: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    uk: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SHORTLIST_READ)
    return await shortlists.list_shortlist_reviews(
        current_user, _company(current_user, company_id),
        request_no=request_no, outcome=outcome, uk=uk, limit=limit)


@router.post("/shortlist-reviews", status_code=201)
async def create_shortlist_review(
    body: ShortlistReviewIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Convene a sitting. Convening decides nothing until the outcome is Finalised."""
    _require(current_user, Cap.SHORTLIST_WRITE)
    return await shortlists.create_shortlist_review(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/shortlist-reviews/{slr_no}")
async def get_shortlist_review(
    slr_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SHORTLIST_READ)
    doc = await shortlists.get_shortlist_review(_company(current_user, company_id), slr_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Shortlist review not found.")
    return doc


@router.patch("/shortlist-reviews/{slr_no}")
async def update_shortlist_review(
    slr_no: str,
    body: ShortlistReviewUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Record members, candidates or the outcome. A DECIDED sitting is frozen."""
    _require(current_user, Cap.SHORTLIST_WRITE)
    return await shortlists.update_shortlist_review(
        current_user, _company(current_user, company_id), slr_no,
        body.model_dump(exclude_unset=True))


# ─────────────────────────────────────────────────────────────
# INT-2.1 — batch interview windows (Annexure C)
# ─────────────────────────────────────────────────────────────
# A PREFERENCE, never a rule: scheduling outside a window warns in the response and books
# the interview anyway. `interview.schedule` governs, because a window is a scheduling
# artifact rather than a governance one.
@router.get("/interview-windows")
async def list_interview_windows(
    department_id: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INTERVIEW_READ)
    return await interview_windows.list_windows(
        _company(current_user, company_id),
        department_id=department_id, include_inactive=include_inactive)


@router.post("/interview-windows", status_code=201)
async def create_interview_window(
    body: InterviewWindowIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INTERVIEW_SCHEDULE)
    return await interview_windows.create_window(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/interview-windows/{window_id}")
async def update_interview_window(
    window_id: str,
    body: InterviewWindowUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INTERVIEW_SCHEDULE)
    return await interview_windows.update_window(
        current_user, _company(current_user, company_id), window_id,
        body.model_dump(exclude_unset=True))


@router.delete("/interview-windows/{window_id}")
async def delete_interview_window(
    window_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.INTERVIEW_SCHEDULE)
    return await interview_windows.delete_window(
        current_user, _company(current_user, company_id), window_id)


# ─────────────────────────────────────────────────────────────
# INT-2.3 — pre-boarding engagement (SOP §6)
# ─────────────────────────────────────────────────────────────
# Tracking, not a control. NOTHING is gated on a touchpoint: a candidate with none onboards
# exactly as they always did. What it does is put people on a due list and flag the ones who
# say they are wavering.
@router.get("/preboarding")
async def list_preboarding(
    uk: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.PREBOARDING_READ)
    return await preboarding.list_touchpoints(
        current_user, _company(current_user, company_id),
        uk=uk, request_no=request_no, sentiment=sentiment, limit=limit)


@router.get("/preboarding/due")
async def due_preboarding(
    within_days: int = Query(7, ge=0, le=90),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Accepted candidates nobody has spoken to lately.

    Split into `never_contacted` and `gone_quiet` rather than one sorted list, the same way
    `/probation/due` splits: "we have not started" and "we have let it slip" are two
    different conversations.
    """
    _require(current_user, Cap.PREBOARDING_READ)
    return await preboarding.due_touchpoints(
        current_user, _company(current_user, company_id), within_days=within_days)


@router.post("/preboarding", status_code=201)
async def record_preboarding_touchpoint(
    body: PreboardingTouchpointIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Log one contact. An `At Risk` sentiment notifies the recruiter and the HOD."""
    _require(current_user, Cap.PREBOARDING_WRITE)
    return await preboarding.record_touchpoint(
        current_user, _company(current_user, company_id), body.model_dump())


# ─────────────────────────────────────────────────────────────
# INT-2.5 — the standing salary-band master (Annexure C)
# ─────────────────────────────────────────────────────────────
# A CONVENIENCE, never an authority: the budget gate pre-fills from this table, and the
# offer check still reads the band stamped on the REQUISITION. A master edited in April must
# not retroactively legalise an offer approved in March.
@router.get("/salary-bands")
async def list_salary_bands(
    department_id: Optional[str] = Query(None),
    designation_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SALARY_BAND_READ)
    return await salary_bands.list_salary_bands(
        current_user, _company(current_user, company_id),
        department_id=department_id, designation_id=designation_id,
        status=status, limit=limit)


@router.get("/salary-bands/for-requisition/{request_no}")
async def salary_band_prefill(
    request_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The band the budget gate would pre-fill for this requisition, or null.

    A SUGGESTION in the shape the approval body expects, so the UI can fill the boxes and
    the approver can still change them. Nothing here writes.
    """
    _require(current_user, Cap.SALARY_BAND_READ)
    scoped = _company(current_user, company_id)
    req = await requisitions.get_requisition(current_user, scoped, request_no)
    if not req:
        raise HTTPException(status_code=404, detail="Requisition not found.")
    return {"request_no": request_no,
            "prefill": await salary_bands.prefill_for_requisition(scoped, req)}


@router.post("/salary-bands", status_code=201)
async def create_salary_band(
    body: SalaryBandIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Publish a band. An existing active band for the same position is superseded."""
    _require(current_user, Cap.SALARY_BAND_WRITE)
    return await salary_bands.create_salary_band(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/salary-bands/{band_no}")
async def get_salary_band(
    band_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SALARY_BAND_READ)
    doc = await salary_bands.get_salary_band(_company(current_user, company_id), band_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Salary band not found.")
    return doc


@router.patch("/salary-bands/{band_no}")
async def update_salary_band(
    band_no: str,
    body: SalaryBandUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Edit the descriptive fields or retire a band. The FIGURES are not editable -- publish
    a new band instead, so what was agreed last year still reads as what was agreed."""
    _require(current_user, Cap.SALARY_BAND_WRITE)
    return await salary_bands.update_salary_band(
        current_user, _company(current_user, company_id), band_no,
        body.model_dump(exclude_unset=True))


# ─────────────────────────────────────────────────────────────
# INT-2.6 — the talent pool (Annexure C)
# ─────────────────────────────────────────────────────────────
# Listing is `GET /candidates?talent_pool=true&tags=` -- the pool is a filter on the
# candidate list, not a second collection. These two endpoints manage membership.
@router.post("/candidates/{uk}/talent-pool")
async def set_talent_pool(
    uk: str,
    body: TalentPoolIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Add a candidate to the pool, or take them out.

    Consent is REQUIRED to join and its expiry may not outlive the record's retention
    period. Leaving is unconditional -- consent is a thing somebody may withdraw.
    """
    _require(current_user, Cap.CANDIDATE_WRITE)
    return await candidates.set_talent_pool(
        current_user, _company(current_user, company_id), uk, body.model_dump())


@router.post("/candidates/{uk}/source-to/{request_no}", status_code=201)
async def source_from_talent_pool(
    uk: str,
    request_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Bring a pooled candidate forward onto a NEW requisition.

    Copies the CV into a new candidate record with its own uk and its own retention clock.
    It never re-points the old one: the original application is a record of what somebody
    applied for and when.
    """
    _require(current_user, Cap.CANDIDATE_WRITE)
    return await candidates.create_from_pool(
        current_user, _company(current_user, company_id), uk, request_no)


# ─────────────────────────────────────────────────────────────
# INT-2.7 — candidate communications (Annexure C)
# ─────────────────────────────────────────────────────────────
# Everything goes out through hrms_notify_service. There is no second mail path; what is new
# here is the template and the append-only log.
@router.get("/communications")
async def list_communications(
    uk: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    template_key: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.COMM_READ)
    return await comms.list_log(
        current_user, _company(current_user, company_id),
        uk=uk, request_no=request_no, template_key=template_key, limit=limit)


@router.get("/communications/templates")
async def list_comm_templates(
    include_inactive: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The six message templates plus the two consent statements, seeded on first read.

    The consent wording lives here rather than in code so legal can change it without a
    deploy -- which is exactly why editing a template is its own capability.
    """
    _require(current_user, Cap.COMM_READ)
    return {"templates": await comms.list_templates(
        _company(current_user, company_id), include_inactive=include_inactive)}


@router.patch("/communications/templates/{key}")
async def update_comm_template(
    key: str,
    body: CommTemplateUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.COMM_TEMPLATE_WRITE)
    return await comms.update_template(
        current_user, _company(current_user, company_id), key,
        body.model_dump(exclude_unset=True))


@router.post("/communications/send", status_code=201)
async def send_communication(
    body: CommSendIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Send one templated message by hand.

    The facts -- name, designation, CTC, joining date -- are DERIVED from the record, never
    accepted from the caller. A sender who could type those in could quote a candidate a
    salary the record does not hold.
    """
    _require(current_user, Cap.COMM_WRITE)
    return await comms.send_template(
        current_user, _company(current_user, company_id), body.candidate_uk,
        body.template_key, variables=body.variables)


# ─────────────────────────────────────────────────────────────
# INT-2.8 — new-hire experience surveys (SOP §10)
# ─────────────────────────────────────────────────────────────
# Read is the AGGREGATE only. There is deliberately no endpoint that returns response rows,
# and the aggregation refuses a figure below SURVEY_MIN_RESPONSES -- a satisfaction survey a
# manager can de-anonymise measures nothing.
@router.get("/surveys")
async def list_surveys(
    include_inactive: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SURVEY_READ)
    return {"surveys": await surveys.list_surveys(
        _company(current_user, company_id), include_inactive=include_inactive)}


@router.get("/surveys/results")
async def survey_results(
    kind: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Mean scores. SCORES ONLY -- never rows, and never below the suppression threshold."""
    _require(current_user, Cap.SURVEY_READ)
    scoped = _company(current_user, company_id)
    return {
        "results": await surveys.aggregate(
            scoped, kind=kind, date_from=date_from, date_to=date_to),
        "response_rate": await surveys.issue_rate(scoped),
    }


# ─────────────────────────────────────────────────────────────
# INT-2.9 — the complete internal KPI set (SOP §10)
# ─────────────────────────────────────────────────────────────
@router.get("/analytics/internal-kpis")
async def analytics_internal_kpis(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None),
    designation_id: Optional[str] = Query(None),
    designation_level: Optional[str] = Query(
        None, description="junior | mid | senior | managerial"),
    hr_user_id: Optional[str] = Query(None, description="the assigned HR owner"),
    hod_user_id: Optional[str] = Query(None, description="whoever raised the requisition"),
    status: Optional[str] = Query(None, description="a ReqApproval value"),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """All eight SOP KPIs, computed server-side and role-scoped.

    Already present inside `GET /analytics/dashboard`; exposed on its own so the dashboard's
    track filter can fetch just this block rather than the whole payload. Every ratio carries
    `eligible_n` and, where records were left out, `excluded_n` with the reason -- a joiner
    whose 90-day window has not matured is excluded from the denominator, never counted as
    retained.

    ── Phase INT-8 (spec §29) ── the six filters narrow the requisition set, and every
    figure downstream flows from it -- so a filtered KPI can never mix a filtered numerator
    with an unfiltered denominator. The response echoes `filters` so the UI can say what
    the figures cover.
    """
    _require(current_user, Cap.ANALYTICS_READ)
    return await analytics.internal_kpis(
        current_user, _company(current_user, company_id),
        date_from=date_from, date_to=date_to,
        department_id=department_id, designation_id=designation_id,
        designation_level=designation_level, hr_user_id=hr_user_id,
        hod_user_id=hod_user_id, status=status)


# ─────────────────────────────────────────────────────────────
# INT-2.10 — statutory pre-employment checks (SOP §11)
# ─────────────────────────────────────────────────────────────
@router.get("/probation/{prb_no}/statutory")
async def probation_statutory_state(
    prb_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """What is outstanding before this probation can be CONFIRMED.

    Read-only, and surfaced while the probation is still running rather than sprung at the
    moment somebody tries to confirm -- a control the user meets for the first time when it
    blocks them is a control that reads as a bug.
    """
    _require(current_user, Cap.PROBATION_READ)
    scoped = _company(current_user, company_id)
    review = await probation.get_probation(scoped, prb_no)
    if not review:
        raise HTTPException(status_code=404, detail="Probation review not found.")
    return await probation.statutory_state(scoped, review.get("employee_code"))


# ─────────────────────────────────────────────────────────────
# INT-2.11 — the policy register and its review cycle (SOP §14)
# ─────────────────────────────────────────────────────────────
@router.get("/policies")
async def list_policies(
    include_withdrawn: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.POLICY_READ)
    return await policies.list_policies(
        _company(current_user, company_id), include_withdrawn=include_withdrawn)


@router.get("/policies/due")
async def due_policy_reviews(
    within_days: int = Query(30, ge=0, le=365),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Reviews overdue, and those falling due inside the window."""
    _require(current_user, Cap.POLICY_READ)
    return await policies.due_reviews(
        _company(current_user, company_id), within_days=within_days)


@router.post("/policies", status_code=201)
async def register_policy(
    body: PolicyIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.POLICY_WRITE)
    return await policies.register_policy(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/policies/{policy_key}")
async def get_policy(
    policy_key: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One policy plus its full Modification History (SOP §14's own table)."""
    _require(current_user, Cap.POLICY_READ)
    doc = await policies.get_policy(_company(current_user, company_id), policy_key)
    if not doc:
        raise HTTPException(status_code=404, detail="That policy is not in the register.")
    return doc


@router.post("/policies/{policy_key}/revisions", status_code=201)
async def log_policy_revision(
    policy_key: str,
    body: PolicyRevisionIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Draft an amendment. It does NOT come into force until it is approved."""
    _require(current_user, Cap.POLICY_WRITE)
    return await policies.log_revision(
        current_user, _company(current_user, company_id), policy_key, body.model_dump())


@router.post("/policies/{policy_key}/approve")
async def approve_policy_revision(
    policy_key: str,
    body: PolicyApproveIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Make a revision the version in force. MD only, and signed."""
    _require(current_user, Cap.POLICY_APPROVE)
    return await policies.approve_revision(
        current_user, _company(current_user, company_id), policy_key, body.model_dump())


# ─────────────────────────────────────────────────────────────
# INT-2.12 — the retention purge (SOP §13)
# ─────────────────────────────────────────────────────────────
# Proposals are written by `scripts/hrms_retention_purge.py`, which defaults to a dry run.
# Execution requires an MD's typed signature here -- the same standard probation confirmation
# holds, because both destroy or end something.
@router.get("/purge-batches")
async def list_purge_batches(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.RETENTION_PURGE)
    return await purge.list_batches(
        _company(current_user, company_id), status=status, limit=limit)


@router.get("/purge-batches/{batch_no}")
async def get_purge_batch(
    batch_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The full proposal, INCLUDING the exact ids. A proposal that says "412 candidates"
    and does not say which is not something anybody can meaningfully approve."""
    _require(current_user, Cap.RETENTION_PURGE)
    doc = await purge.get_batch(_company(current_user, company_id), batch_no)
    if not doc:
        raise HTTPException(status_code=404, detail="Purge batch not found.")
    return doc


@router.post("/purge-batches/{batch_no}/approve")
async def approve_purge_batch(
    batch_no: str,
    body: PurgeApproveIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Authorise the purge and carry it out.

    Redacts rather than hard-deletes: the id and the audit spine survive and the PII fields
    are cleared, stamped with the batch number. An audit trail with dangling references
    proves nothing. It is not reversible.
    """
    _require(current_user, Cap.RETENTION_PURGE)
    return await purge.approve_and_execute(
        current_user, _company(current_user, company_id), batch_no, body.model_dump())


# ─────────────────────────────────────────────────────────────
# INT-2.13 — the printable documentation set (SOP §9)
# ─────────────────────────────────────────────────────────────
# ONE endpoint pattern for all five forms, gated by the entity's EXISTING read capability.
# Printing a record is reading it, so a separate `document.generate` capability would create
# a user who may read a probation review but not print it.
@router.get("/records/{entity}/{business_no}/document")
async def generate_record_document(
    entity: str,
    business_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Render one record as a PDF and return a signed URL.

    `entity` is an allow-list key (PRINTABLE_DOCUMENTS), never a collection name -- mapping
    a URL segment onto a collection would let a caller print any collection in the database.
    Every figure on the form is read from the record; nothing is re-entered.
    """
    spec = PRINTABLE_DOCUMENTS.get(entity)
    if not spec:
        raise HTTPException(
            status_code=404,
            detail=(f"There is no printable document for '{entity}'. Available: "
                    f"{', '.join(sorted(PRINTABLE_DOCUMENTS))}."))
    # The capability comes from the TABLE, so a new form cannot be added without deciding
    # who may read it.
    _require(current_user, spec[3])
    return await record_documents.generate(
        current_user, _company(current_user, company_id), entity, business_no)


# =============================================================
# Phase 12 -- the client hiring track
# =============================================================
# Three surfaces, one router. What separates them is not the path but the SCOPE the service
# applies: a Sparsh user sees the tenant's work, a client user sees only the rows their
# engagements grant. That narrowing lives in the services (share / job-request
# `_scope_filter`) rather than here, so no route can forget to apply it.


# -- Client job requests --------------------------------------
@router.get("/job-requests")
async def list_job_requests(
    status: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Sparsh's inbox, or the client's own list -- the service decides which by role."""
    _require(current_user, Cap.JOB_REQUEST_READ)
    return await job_requests.list_job_requests(
        current_user, _company(current_user, company_id),
        status=status, client_id=client_id, limit=limit)


@router.post("/job-requests", status_code=201)
async def create_job_request(
    body: JobRequestIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.JOB_REQUEST_WRITE)
    return await job_requests.create_job_request(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/job-requests/{jbr_no}")
async def get_job_request(
    jbr_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.JOB_REQUEST_READ)
    return await job_requests.get_job_request(
        current_user, _company(current_user, company_id), jbr_no)


@router.patch("/job-requests/{jbr_no}")
async def update_job_request(
    jbr_no: str,
    body: JobRequestUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.JOB_REQUEST_WRITE)
    return await job_requests.update_job_request(
        current_user, _company(current_user, company_id), jbr_no,
        body.model_dump(exclude_unset=True))


@router.post("/job-requests/{jbr_no}/act")
async def act_on_job_request(
    jbr_no: str,
    body: JobRequestAction,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Sparsh's review: review | accept | decline.

    The service re-checks the capability from JOB_REQUEST_TRANSITIONS, so the boundary
    between what a client ASKED FOR and what Sparsh AGREED TO holds even for a caller that
    reached the service some other way.
    """
    _require(current_user, Cap.JOB_REQUEST_REVIEW)
    return await job_requests.act_on_job_request(
        current_user, _company(current_user, company_id), jbr_no,
        body.action, body.remarks)


@router.post("/job-requests/{jbr_no}/withdraw")
async def withdraw_job_request(
    jbr_no: str,
    body: Optional[JobRequestAction] = None,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.JOB_REQUEST_WRITE)
    return await job_requests.withdraw_job_request(
        current_user, _company(current_user, company_id), jbr_no,
        (body.remarks if body else None))


@router.post("/job-requests/{jbr_no}/convert", status_code=201)
async def convert_job_request(
    jbr_no: str,
    body: JobRequestConvertIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """An accepted request becomes a client-track requisition.

    Also demands REQUISITION_CREATE: this call creates one, and holding the review
    capability alone should not become a side door into making requisitions.
    """
    _require(current_user, Cap.JOB_REQUEST_REVIEW)
    _require(current_user, Cap.REQUISITION_CREATE)
    return await job_requests.convert_to_requisition(
        current_user, _company(current_user, company_id), jbr_no, body.model_dump())


# -- CV sharing -----------------------------------------------
@router.get("/shares")
async def list_shares(
    uk: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    request_no: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Sparsh's sharing board, or the client's shared-candidate list."""
    _require(current_user, Cap.SHARE_READ)
    return await shares.list_shares(
        current_user, _company(current_user, company_id),
        uk=uk, client_id=client_id, status=status, request_no=request_no, limit=limit)


@router.post("/shares", status_code=201)
async def share_candidate(
    body: ShareIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Share one CV with one or more clients. Sparsh only -- a client can never share a
    candidate onward, which is why SHARE_WRITE is withheld from the CLIENT role."""
    _require(current_user, Cap.SHARE_WRITE)
    return await shares.share_candidate(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/shares/{share_no}")
async def get_share(
    share_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SHARE_READ)
    return await shares.get_share(
        current_user, _company(current_user, company_id), share_no)


@router.get("/shares/{share_no}/cv")
async def get_share_cv(
    share_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """A short-lived link to the CV on this share, minted per request and audited -- this
    is the moment a client actually reads somebody's personal data."""
    _require(current_user, Cap.SHARE_READ)
    return await shares.resume_url_for_share(
        current_user, _company(current_user, company_id), share_no)


@router.post("/shares/{share_no}/remarks")
async def add_share_remark(
    share_no: str,
    body: ShareRemarkIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """File a remark against a share without moving its status.

    `share.respond` rather than `share.read`: this writes to the record and reaches the
    recruiter, so it is the same class of act as recording a verdict -- a client who may only
    look at a CV should not be able to put words in its history.
    """
    _require(current_user, Cap.SHARE_RESPOND)
    return await shares.add_share_remark(
        current_user, _company(current_user, company_id), share_no, body.model_dump())


# -- The interview record, as a client reads it (brief SS10) ----
#
# Three verbs, one capability. `share.read` is what proves the caller may look at this
# candidate at all; WHAT they may do with each artifact is fixed by the route, not by a
# permission the caller could hold more of:
#
#     GET /shares/{n}/cv                 -> download   (Content-Disposition: attachment)
#     GET /shares/{n}/interview-report   -> view       (rendered in place)
#     GET /shares/{n}/interview-recording-> watch      (streamed; no save affordance)
#
# There is deliberately no download route for the recording. Adding one later would be a
# product decision, not a permissions change -- which is the point of putting the asymmetry
# in the routing table where it is visible.
@router.get("/shares/{share_no}/interview-report")
async def get_share_interview_report(
    share_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """View the interview report for a shared candidate. Audited on every open."""
    _require(current_user, Cap.SHARE_READ)
    return await shares.report_url_for_share(
        current_user, _company(current_user, company_id), share_no)


@router.get("/shares/{share_no}/interview-recording")
async def get_share_interview_recording(
    share_no: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Watch the interview recording for a shared candidate. Audited on every open."""
    _require(current_user, Cap.SHARE_READ)
    return await shares.recording_ref_for_share(
        current_user, _company(current_user, company_id), share_no)


@router.post("/shares/{share_no}/status")
async def set_share_status(
    share_no: str,
    body: ShareStatusIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The client's verdict, or Sparsh recording one they were told by phone.

    Two capabilities reach this, and WHICH statuses each may set is decided by
    SHARE_CLIENT_SETTABLE in the service rather than here -- a client says what they think
    of a CV; only Sparsh records that somebody was hired.
    """
    if not (can(current_user, Cap.SHARE_RESPOND) or can(current_user, Cap.SHARE_WRITE)):
        raise HTTPException(status_code=403, detail=NO_ACCESS_MESSAGE)
    return await shares.set_share_status(
        current_user, _company(current_user, company_id), share_no, body.model_dump())


@router.post("/shares/{share_no}/withdraw")
async def withdraw_share(
    share_no: str,
    body: Optional[ShareStatusIn] = None,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.SHARE_WRITE)
    return await shares.withdraw_share(
        current_user, _company(current_user, company_id), share_no,
        (body.model_dump() if body else None))


@router.get("/candidates/{uk}/shares")
async def shares_for_candidate(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Every client this candidate went to, with each client's own status.

    Sparsh only: the answer names other clients, which is precisely what a client user may
    not see. The service refuses a client-scoped caller outright.
    """
    _require(current_user, Cap.SHARE_READ)
    return await shares.shares_for_candidate(
        current_user, _company(current_user, company_id), uk)


# -- Background verification ----------------------------------
@router.get("/background-checks")
async def list_background_checks(
    uk: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.BACKGROUND_READ)
    return await background.list_checks(
        current_user, _company(current_user, company_id),
        uk=uk, status=status, limit=limit)


@router.get("/background-checks/pending")
async def pending_verifications(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The work queue: candidates at Selected or Offer stage, and where each one's
    verification stands."""
    _require(current_user, Cap.BACKGROUND_READ)
    return await background.pending_verifications(
        current_user, _company(current_user, company_id))


@router.post("/background-checks", status_code=201)
async def record_background_check(
    body: BackgroundCheckIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.BACKGROUND_WRITE)
    return await background.record_check(
        current_user, _company(current_user, company_id), body.model_dump())


@router.patch("/background-checks/{bgv_no}")
async def update_background_check(
    bgv_no: str,
    body: BackgroundCheckUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.BACKGROUND_WRITE)
    return await background.update_check(
        current_user, _company(current_user, company_id), bgv_no,
        body.model_dump(exclude_unset=True))


@router.get("/candidates/{uk}/verification")
async def candidate_verification(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """One candidate's whole verification file, and whether it clears them for an offer."""
    _require(current_user, Cap.BACKGROUND_READ)
    return await background.verification_state(
        _company(current_user, company_id), uk)


@router.post("/candidates/{uk}/verification/decide")
async def decide_verification(
    uk: str,
    body: BackgroundApproveIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """HR's sign-off, and the step that unlocks the offer.

    Takes a typed signature -- the same standard probation confirmation and the retention
    purge hold, because all three either commit the company or end something.
    """
    _require(current_user, Cap.BACKGROUND_APPROVE)
    return await background.decide_verification(
        current_user, _company(current_user, company_id), uk, body.model_dump())


# -- Candidate CV (Phase 12, requirement 1) --------------------
@router.post("/candidates/{uk}/cv")
async def upload_candidate_cv(
    uk: str,
    body: UploadIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Attach or replace a candidate's CV.

    CANDIDATE_WRITE, not DOCUMENT_WRITE: the CV is part of the candidate record rather than
    a filed document, and it is what a share carries to a client.
    """
    _require(current_user, Cap.CANDIDATE_WRITE)
    return await candidates.upload_cv(
        current_user, _company(current_user, company_id), uk, {"resume": body.model_dump()})


@router.get("/candidates/{uk}/cv")
async def get_candidate_cv(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """A short-lived link to the CV, for Sparsh-side readers. Audited on every open.

    A client never reaches this -- they hold no `candidate.read` and use
    GET /shares/{share_no}/cv, which additionally proves the candidate was shared with them.
    """
    _require(current_user, Cap.CANDIDATE_READ)
    return await candidates.cv_url(
        current_user, _company(current_user, company_id), uk)


# -- The interview record, Sparsh side (brief SS10) -------------
#
# INTERVIEW_MEDIA_WRITE rather than INTERVIEW_SCHEDULE or CANDIDATE_WRITE: filing this
# material publishes evidence about a person to an outside company, which is neither
# logistics nor an ordinary edit of a candidate row. See the capability's own note.
@router.post("/candidates/{uk}/interview-report")
async def file_interview_report(
    uk: str,
    body: InterviewReportIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """File the interview report. Replaces any previous one, keeping it in history.

    Live shares of this candidate pick the report up immediately -- the CV usually goes out
    before the interview happens, so a report that only reached future shares would reach
    almost nobody.
    """
    _require(current_user, Cap.INTERVIEW_MEDIA_WRITE)
    return await interview_media.file_report(
        current_user, _company(current_user, company_id), uk, body.model_dump())


@router.post("/candidates/{uk}/interview-recording")
async def file_interview_recording(
    uk: str,
    body: InterviewRecordingIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """File the recording -- an uploaded file OR the meeting platform's link."""
    _require(current_user, Cap.INTERVIEW_MEDIA_WRITE)
    return await interview_media.file_recording(
        current_user, _company(current_user, company_id), uk, body.model_dump())


@router.get("/candidates/{uk}/interview-record")
async def get_interview_record(
    uk: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """What is on file for this candidate. Sparsh side -- a client reads their share."""
    _require(current_user, Cap.CANDIDATE_READ)
    return await interview_media.get_media(
        current_user, _company(current_user, company_id), uk)


@router.get("/candidates/{uk}/interview-record/{kind}/url")
async def get_interview_record_url(
    uk: str,
    kind: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """A short-lived link to the report or the recording, for a Sparsh-side reader.

    `kind` is "report" or "recording". Sparsh is not subject to the client's view-only
    restriction: the material is theirs, and this is the same read their own candidate
    screens already give them of a CV.
    """
    _require(current_user, Cap.CANDIDATE_READ)
    return await interview_media.media_url(
        current_user, _company(current_user, company_id), uk, kind)


@router.delete("/candidates/{uk}/interview-record/{kind}")
async def remove_interview_record(
    uk: str,
    kind: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Unpublish the report or the recording. The stored object is kept, only unlinked --
    a client may already have been shown it, and the audit trail has to keep resolving."""
    _require(current_user, Cap.INTERVIEW_MEDIA_WRITE)
    return await interview_media.remove_media(
        current_user, _company(current_user, company_id), uk, kind)
