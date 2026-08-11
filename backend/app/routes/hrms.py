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
    ClientIn, ClientResponseIn, ClientUpdate,
    DocumentIn, DocumentStatusIn, DocumentTypeIn, DocumentTypeUpdate, DocumentUpdate,
    LinkRevokeIn, SanctionedStrengthIn, SanctionedStrengthUpdate,
)
from app.services import hrms_analytics_service as analytics
from app.services import hrms_employee_service as employees
from app.services import hrms_masters_service as masters
from app.services import hrms_assessment_service as assessments
from app.services import hrms_candidate_service as candidates
from app.services import hrms_interview_service as interviews
from app.services import hrms_offer_service as offers
from app.services import hrms_onboarding_service as onboarding
from app.services import hrms_posting_service as postings
from app.services import hrms_requisition_service as requisitions
# ── Phase 11-R ──
from app.services import hrms_appointment_service as appointments
from app.services import hrms_client_service as clients
from app.services import hrms_document_service as documents
from app.services import hrms_link_service as links
from app.services import hrms_sanction_service as sanctions
from app.services.hrms_audit_service import read_audit
from app.utils.hrms_access import (
    NO_ACCESS_MESSAGE, can, capabilities_for, ensure_hrms_enabled, hrms_role,
    is_internal_user, scope_company_id,
)


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
    return HrmsHealthResponse(
        enabled=True,
        role=role.value if role else None,
        capabilities=sorted(c.value for c in capabilities_for(current_user)),
        company_id=scope_company_id(current_user),
        is_internal=is_internal_user(current_user),
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
    limit: int = Query(100, ge=1, le=200),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """Requisition list + stat tiles. A plain employee sees only the ones they raised."""
    _require(current_user, Cap.REQUISITION_READ)
    return await requisitions.list_requisitions(
        current_user, _company(current_user, company_id),
        search=search, approval_status=approval_status, closing_status=closing_status,
        department_id=department_id, limit=limit, skip=skip)


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
    """One transition of the approval chain: hr-approve | hr-reject | md-approve | md-reject.

    The per-action capability is enforced inside the service, from the same transition table
    that defines the state machine -- so the gate can never drift from the rule it guards.
    """
    return await requisitions.act_on_requisition(
        current_user, _company(current_user, company_id), request_no,
        body.action, body.remarks, body.salary_change)


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
async def create_postings(
    body: PostingIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Publish an APPROVED job description to one or more platforms -- one posting row per
    platform, each with its own code and its own destination."""
    _require(current_user, Cap.POSTING_WRITE)
    return await postings.create_postings(
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
    limit: int = Query(200, ge=1, le=500),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """The candidate pipeline. Row-scoped: a hiring manager sees only candidates on
    requisitions they raised. Column counts come from the same scoped query as the rows,
    so the board totals always match what the caller can open."""
    _require(current_user, Cap.CANDIDATE_READ)
    return await candidates.list_candidates(
        current_user, _company(current_user, company_id),
        search=search, status=status, request_no=request_no,
        posting_code=posting_code, limit=limit, skip=skip)


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
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Headline KPIs, positions summary, offer outcomes and time-to-hire.

    A hiring manager gets the same shape scoped to their own requisitions — the response
    says so via `scoped_to_own_requisitions`, so the UI can label the numbers honestly
    rather than implying they are company-wide.
    """
    _require(current_user, Cap.ANALYTICS_READ)
    return await analytics.dashboard(
        current_user, _company(current_user, company_id),
        date_from=date_from, date_to=date_to, client_id=client_id)


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
# Item 4 — the client master + client sharing
# ─────────────────────────────────────────────────────────────
@router.get("/clients")
async def list_hrms_clients(
    include_inactive: bool = Query(False),
    search: Optional[str] = Query(None),
    with_stats: bool = Query(False),
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """The client master — who vacancies are being filled FOR.

    NOTE: a client is NOT a tenant. `company_id` remains the only security boundary;
    `client_id` is a reporting dimension inside one tenant (see hrms_client_service).
    """
    _require(current_user, Cap.CLIENT_READ)
    return await clients.list_clients(
        current_user, _company(current_user, company_id),
        include_inactive=include_inactive, search=search, with_stats=with_stats)


@router.post("/clients", status_code=201)
async def create_hrms_client(
    body: ClientIn,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_WRITE)
    return await clients.create_client(
        current_user, _company(current_user, company_id), body.model_dump())


@router.get("/clients/{client_id}")
async def get_hrms_client(
    client_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_READ)
    scoped = _company(current_user, company_id)
    doc = await clients.get_client(scoped, client_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Client not found.")
    doc["summary"] = await clients.client_summary(scoped, client_id)
    return doc


@router.patch("/clients/{client_id}")
async def update_hrms_client(
    client_id: str,
    body: ClientUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    _require(current_user, Cap.CLIENT_WRITE)
    return await clients.update_client(
        current_user, _company(current_user, company_id), client_id,
        body.model_dump(exclude_unset=True))


@router.delete("/clients/{client_id}")
async def delete_hrms_client(
    client_id: str,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Blocked while any requisition names the client — deactivate instead."""
    _require(current_user, Cap.CLIENT_WRITE)
    return await clients.delete_client(
        current_user, _company(current_user, company_id), client_id)


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
