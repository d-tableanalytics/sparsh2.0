"""HRMS — shared constants and Phase-0 models.

The HRMS manages Sparsh's OWN workforce. It is internal-staff-only (see
auth_controller.require_hrms_access): there is no per-company toggle and no client-side path
into it, so employee records, payroll and KYC never leave Sparsh.

Collections are namespaced `hrms_*` so nothing collides with the existing LMS/ORM data. That
namespacing is deliberate for one field in particular: the app already uses "attendance" for
LMS SESSION attendance (calendar_events / report_lms_service). Workforce attendance is a
different domain and lives in `hrms_attendance`, reached only under /api/hrms/.

Per-module document models land here as each phase is built. Phase 0 defines the names, the
sequence scopes and the index plan only — no business collections yet.
"""
from pydantic import BaseModel
from typing import List, Optional


# ─── Collections ────────────────────────────────────────────────────────────────
# One place so a typo can't create a stray collection. Referenced by the index-ensure below
# and by every HRMS route.
COL_EMPLOYEES      = "hrms_employees"
COL_EMPLOYEE_EVENTS = "hrms_employee_events"
COL_ORG_MASTERS    = "hrms_org_masters"      # kind = department | designation | location
COL_ATTENDANCE     = "hrms_attendance"       # one doc per (user, date), segments embedded
COL_LEAVES         = "hrms_leaves"
COL_LEAVE_BALANCES = "hrms_leave_balances"
COL_PAYROLL_RUNS   = "hrms_payroll_runs"
COL_PAYSLIPS       = "hrms_payslips"
COL_REQUISITIONS   = "hrms_requisitions"
COL_JDS            = "hrms_jds"
COL_POSTINGS       = "hrms_postings"
COL_CANDIDATES     = "hrms_candidates"       # assessments/interviews/offers/onboarding embedded
COL_EXIT_DOCUMENTS = "hrms_exit_documents"

HRMS_COLLECTIONS = [
    COL_EMPLOYEES, COL_EMPLOYEE_EVENTS, COL_ORG_MASTERS,
    COL_ATTENDANCE, COL_LEAVES, COL_LEAVE_BALANCES,
    COL_PAYROLL_RUNS, COL_PAYSLIPS,
    COL_REQUISITIONS, COL_JDS, COL_POSTINGS, COL_CANDIDATES,
    COL_EXIT_DOCUMENTS,
]

# Reused from the existing app rather than duplicated — see docs/HRMS_REPLICATION_ROADMAP.md §6.
#   holidays        -> the existing Holiday module (routes/holiday.py)
#   notifications   -> existing in-app notifications
#   notification_logs -> covers the reference project's email outbox
#   activity_logs   -> covers the reference project's audit log
#   system settings -> covers the reference project's hrms_settings


# ─── Sequence scopes (see utils/counters.py) ────────────────────────────────────
SEQ_EMPLOYEE    = "hrms_employee"      # EMP-YYYY-NNNN
SEQ_REQUISITION = "hrms_requisition"   # HR-REQ-YYYY-NNN
SEQ_CANDIDATE   = "hrms_candidate"     # CAN-YYYY-NNNN


# ─── Permission modules ─────────────────────────────────────────────────────────
# Mirrors the keys seeded in models/user.py. `attendance`/`payroll` grants govern OTHER
# people's records; a user's own punch and own payslip never require a grant.
PERM_HRMS        = "hrms"
PERM_RECRUITMENT = "recruitment"
PERM_ATTENDANCE  = "attendance"
PERM_PAYROLL     = "payroll"

HRMS_PERMISSION_MODULES = [PERM_HRMS, PERM_RECRUITMENT, PERM_ATTENDANCE, PERM_PAYROLL]


# ─── Org structure master data (Phase 1) ────────────────────────────────────────
# Departments, designations and locations are three near-identical shapes, so they share one
# collection with a `kind` discriminator — the same approach `task_meta` already uses for
# categories and tags. `active=False` retires an entry without deleting history that still
# references it by name.
ORG_KIND_DEPARTMENT  = "department"
ORG_KIND_DESIGNATION = "designation"
ORG_KIND_LOCATION    = "location"
ORG_KINDS = [ORG_KIND_DEPARTMENT, ORG_KIND_DESIGNATION, ORG_KIND_LOCATION]

LOCATION_TYPES = ["Office", "Factory", "Warehouse", "Branch", "Remote"]


class OrgMasterCreate(BaseModel):
    kind: str
    name: str
    code: Optional[str] = ""
    # department: head; designation: parent department + grade; location: type/city/state
    head: Optional[str] = ""
    department: Optional[str] = ""
    grade: Optional[str] = ""
    type: Optional[str] = ""
    city: Optional[str] = ""
    state: Optional[str] = ""
    description: Optional[str] = ""


class OrgMasterUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    head: Optional[str] = None
    department: Optional[str] = None
    grade: Optional[str] = None
    type: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None


# ─── Employee master (Phase 1) ──────────────────────────────────────────────────
EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Contract", "Intern", "Consultant"]
WORK_MODES = ["Office", "Remote", "Hybrid", "Factory"]
EMPLOYEE_STATUSES = [
    "Active", "Probation", "On Notice", "Resigned", "Terminated", "Absconded", "Retired",
]
# Anything past these means the person has left — used by the directory filter and, later, by
# payroll to stop paying an exited employee.
EXITED_STATUSES = ["Resigned", "Terminated", "Absconded", "Retired"]

# Statutory / bank / compensation. Masked or dropped for a reader without personal-data
# permission — the guard is in the serializer, not in the UI (see hrms_employee_service).
SENSITIVE_FIELDS = [
    "pan", "aadhaar", "passport", "driving_license", "uan", "esic_no",
    "bank_name", "bank_account", "bank_ifsc", "ctc_annual",
]


class EmployeeBase(BaseModel):
    # Identity
    full_name: str
    display_name: Optional[str] = ""
    gender: Optional[str] = ""
    date_of_birth: Optional[str] = None          # ISO "YYYY-MM-DD"
    personal_email: Optional[str] = ""
    work_email: Optional[str] = ""
    phone: Optional[str] = ""
    address: Optional[str] = ""
    emergency_name: Optional[str] = ""
    emergency_relation: Optional[str] = ""
    emergency_phone: Optional[str] = ""

    # Position
    designation: Optional[str] = ""
    department: Optional[str] = ""
    location: Optional[str] = ""
    employment_type: Optional[str] = "Full-time"
    grade: Optional[str] = ""
    work_mode: Optional[str] = "Office"
    # The manager's Sparsh user id. Reuses the same `reporting_manager` concept the user
    # profile already carries, so the two hierarchies never disagree.
    reporting_manager: Optional[str] = ""

    # Lifecycle
    status: Optional[str] = "Active"
    date_of_joining: Optional[str] = None
    probation_end_date: Optional[str] = None
    confirmation_date: Optional[str] = None
    exit_date: Optional[str] = None
    exit_reason: Optional[str] = ""

    # Sensitive
    pan: Optional[str] = ""
    aadhaar: Optional[str] = ""
    passport: Optional[str] = ""
    driving_license: Optional[str] = ""
    uan: Optional[str] = ""
    esic_no: Optional[str] = ""
    bank_name: Optional[str] = ""
    bank_account: Optional[str] = ""
    bank_ifsc: Optional[str] = ""
    ctc_annual: Optional[float] = 0

    photo_url: Optional[str] = ""


class EmployeeCreate(EmployeeBase):
    # Optional link to the Sparsh login this employee signs in with (staff._id). Kept optional:
    # a person can be on the payroll before an account is provisioned, and an account can exist
    # without an employee record.
    user_id: Optional[str] = None


class EmployeeUpdate(BaseModel):
    """Every field optional — PATCH semantics. Mirrors EmployeeBase; `employee_code` is never
    editable (it is the immutable business id)."""
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    personal_email: Optional[str] = None
    work_email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    emergency_name: Optional[str] = None
    emergency_relation: Optional[str] = None
    emergency_phone: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    grade: Optional[str] = None
    work_mode: Optional[str] = None
    reporting_manager: Optional[str] = None
    status: Optional[str] = None
    date_of_joining: Optional[str] = None
    probation_end_date: Optional[str] = None
    confirmation_date: Optional[str] = None
    exit_date: Optional[str] = None
    exit_reason: Optional[str] = None
    pan: Optional[str] = None
    aadhaar: Optional[str] = None
    passport: Optional[str] = None
    driving_license: Optional[str] = None
    uan: Optional[str] = None
    esic_no: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    bank_ifsc: Optional[str] = None
    ctc_annual: Optional[float] = None
    photo_url: Optional[str] = None
    user_id: Optional[str] = None


# ─── Employee timeline ──────────────────────────────────────────────────────────
# Every create / edit / status change / transfer / exit appends here, so a profile shows a real
# chronology instead of one mutable row. Distinct from `activity_logs` (which stays the app-wide
# audit trail): this is a product surface the HR team reads, not an admin log.
EVENT_CREATED       = "created"
EVENT_UPDATED       = "updated"
EVENT_STATUS_CHANGE = "status_change"
EVENT_TRANSFER      = "transfer"
EVENT_PROMOTION     = "promotion"
EVENT_CONFIRMATION  = "confirmation"
EVENT_EXIT          = "exit"
EVENT_NOTE          = "note"


class EmployeeEventCreate(BaseModel):
    event_type: str = EVENT_NOTE
    detail: str = ""
    effective_date: Optional[str] = None


# ─── Attendance (Phase 2) ───────────────────────────────────────────────────────
# One document per (user, IST date). Individual in/out taps live in `segments`; the daily
# summary (first in, last out, total minutes) is DERIVED from them on read rather than stored
# alongside — the reference project keeps both and they drift, which is also why its payroll
# silently ignores manual edits.
#
# The day boundary is IST, matching the rest of the app (see reminder_scheduler): a punch at
# 00:30 IST belongs to that IST day, not to the previous UTC one.
PUNCH_SOURCE_SELF   = "self"     # the employee tapped in/out
PUNCH_SOURCE_MANUAL = "manual"   # HR entered it on their behalf

# Settings live in the existing `system_settings` collection under this name, so HRMS reuses
# the app's settings store instead of introducing a second one.
SETTING_ATTENDANCE = "hrms_attendance"


class AttendanceSettings(BaseModel):
    """Attendance policy. Every value is validated on write — the reference project stores
    these as unvalidated strings, and a bad value NaN-poisons its payroll."""
    setting_name: str = SETTING_ATTENDANCE
    # Location is RECORDED on every punch, but only BLOCKS one when this is on. Opt-in, because
    # switching it on retroactively would reject staff who are legitimately off-site.
    geofence_enabled: bool = False
    office_latitude: float = 0.0
    office_longitude: float = 0.0
    office_radius_meters: int = 200
    # Require a selfie at punch time. Off by default; the photo is proof of presence, not identity
    # verification — it is trivially spoofable and should not be treated as more than a deterrent.
    selfie_required: bool = False
    # Standard shift, "HH:MM" local. Read by the attendance view now and by payroll in Phase 4.
    shift_start: str = "09:00"
    shift_end: str = "17:00"
    # Weekly offs as Python weekday numbers (Mon=0 … Sun=6). Default: Sunday.
    weekly_offs: List[int] = [6]


class AttendanceSettingsUpdate(BaseModel):
    geofence_enabled: Optional[bool] = None
    office_latitude: Optional[float] = None
    office_longitude: Optional[float] = None
    office_radius_meters: Optional[int] = None
    selfie_required: Optional[bool] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    weekly_offs: Optional[List[int]] = None


class PunchRequest(BaseModel):
    """A punch in or out. Coordinates and selfie are optional unless policy requires them."""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # data: URI or bare base64. Uploaded to S3 under the gated documents prefix; the raw image
    # is never stored in Mongo.
    selfie: Optional[str] = None


class ManualAttendanceRequest(BaseModel):
    """HR recording attendance on someone's behalf — a missed punch, an off-site day.

    Recorded as a normal segment flagged `source: manual` with the actor's id, so every consumer
    (including payroll) reads it the same way as a self-punch. The reference project writes an
    `is_manual` flag that its payroll never reads, so corrections silently don't count.
    """
    user_id: str
    punch_date: str          # ISO "YYYY-MM-DD" (IST)
    punch_in: str            # "HH:MM"
    punch_out: Optional[str] = None
    note: Optional[str] = ""


# ─── Leave (Phase 3) ────────────────────────────────────────────────────────────
# Leave types are CONFIGURED, not hardcoded. The reference project ships four fixed strings and
# then classifies them by substring match, which silently misses "Sick" and "Earned" — so a
# paid type quietly behaves as unpaid. Here each type carries its own flags and the engine reads
# those, never the name.
SETTING_LEAVE = "hrms_leave"

LEAVE_PENDING  = "Pending"
LEAVE_APPROVED = "Approved"
LEAVE_REJECTED = "Rejected"
LEAVE_CANCELLED = "Cancelled"
LEAVE_STATUSES = [LEAVE_PENDING, LEAVE_APPROVED, LEAVE_REJECTED, LEAVE_CANCELLED]


class LeaveType(BaseModel):
    code: str                       # stable id, referenced by leave records
    name: str
    # Paid types draw down the annual entitlement; unpaid ones don't (and never block on balance).
    paid: bool = True
    annual_quota: float = 0         # days granted per year for a paid type
    allow_half_day: bool = True
    active: bool = True


# Seeded on first read. Deliberately a starting point an admin edits, not a fixed policy.
DEFAULT_LEAVE_TYPES = [
    {"code": "casual",   "name": "Casual Leave",   "paid": True,  "annual_quota": 12, "allow_half_day": True,  "active": True},
    {"code": "sick",     "name": "Sick Leave",     "paid": True,  "annual_quota": 6,  "allow_half_day": True,  "active": True},
    {"code": "earned",   "name": "Earned Leave",   "paid": True,  "annual_quota": 15, "allow_half_day": False, "active": True},
    {"code": "unpaid",   "name": "Unpaid Leave",   "paid": False, "annual_quota": 0,  "allow_half_day": True,  "active": True},
]


class LeaveSettings(BaseModel):
    setting_name: str = SETTING_LEAVE
    types: List[dict] = DEFAULT_LEAVE_TYPES
    # Weekly offs and public holidays are skipped when counting leave days, so a Mon-Fri request
    # over a weekend doesn't consume Saturday and Sunday. Holidays come from the app's EXISTING
    # `holidays` collection rather than a second HRMS calendar.
    exclude_weekly_offs: bool = True
    exclude_holidays: bool = True
    # Block an application that would exceed the annual quota. Off by default so a new
    # deployment with no balances configured doesn't reject everything on day one.
    enforce_balance: bool = False


class LeaveSettingsUpdate(BaseModel):
    types: Optional[List[dict]] = None
    exclude_weekly_offs: Optional[bool] = None
    exclude_holidays: Optional[bool] = None
    enforce_balance: Optional[bool] = None


class LeaveApply(BaseModel):
    leave_type: str                  # LeaveType.code
    start_date: str                  # ISO "YYYY-MM-DD"
    end_date: str
    # A half day only ever applies to a single-date request — half of a five-day range is
    # ambiguous, so the service rejects that combination rather than guessing.
    is_half_day: bool = False
    reason: str


class LeaveDecision(BaseModel):
    status: str                      # Approved | Rejected
    remark: Optional[str] = ""


# ─── Recruitment (Phase 5) ──────────────────────────────────────────────────────
# A hiring requisition walks ONE approval chain:
#     Pending HR Review → Pending MD Approval → Approved | Rejected
# The job description is authored WITH the requisition and co-approved — there is no separate
# JD approval to chase, which is how the reference project ended up with an approve endpoint
# its own UI never calls.
REQ_PENDING_HR = "Pending HR Review"
REQ_PENDING_MD = "Pending MD Approval"
REQ_APPROVED   = "Approved"
REQ_REJECTED   = "Rejected"
REQ_APPROVAL_STATES = [REQ_PENDING_HR, REQ_PENDING_MD, REQ_APPROVED, REQ_REJECTED]

# Legal transitions. Anything not listed is refused, so a requisition can never jump the chain
# or be re-approved after the fact.
REQ_TRANSITIONS = {
    REQ_PENDING_HR: [REQ_PENDING_MD, REQ_REJECTED],
    REQ_PENDING_MD: [REQ_APPROVED, REQ_REJECTED],
    REQ_APPROVED: [],
    REQ_REJECTED: [REQ_PENDING_HR],      # a rejected requisition may be revised and resubmitted
}

# Where the vacancy itself stands, independent of the approval chain.
REQ_OPEN = "Open"
REQ_HIRED = "Hired"
REQ_CLOSED = "Closed"
REQ_HOLD = "Hold"
REQ_CANCELLED = "Cancelled"
REQ_CLOSING_STATES = [REQ_OPEN, REQ_HIRED, REQ_CLOSED, REQ_HOLD, REQ_CANCELLED]

URGENCY_LEVELS = ["High", "Medium", "Low"]


class JobDescription(BaseModel):
    """Authored alongside the requisition and co-approved with it."""
    title: Optional[str] = ""
    responsibilities: Optional[str] = ""
    skills: Optional[str] = ""
    qualifications: Optional[str] = ""
    experience: Optional[str] = ""
    ctc: Optional[str] = ""
    location: Optional[str] = ""
    benefits: Optional[str] = ""
    employment_type: Optional[str] = "Full-time"


class RequisitionCreate(BaseModel):
    department: str
    designation: str
    vacancy: int = 1
    experience_required: Optional[str] = ""
    offering_ctc: Optional[str] = ""
    qualification: Optional[str] = ""
    essential_skills: Optional[str] = ""
    gender_preferred: Optional[str] = "Any"
    work_location: Optional[str] = ""
    urgency_level: Optional[str] = "Medium"
    required_date: Optional[str] = None       # ISO "YYYY-MM-DD"
    assignee: Optional[str] = ""              # who the role reports to / who asked for it
    jd: Optional[JobDescription] = None


class RequisitionUpdate(BaseModel):
    department: Optional[str] = None
    designation: Optional[str] = None
    vacancy: Optional[int] = None
    experience_required: Optional[str] = None
    offering_ctc: Optional[str] = None
    qualification: Optional[str] = None
    essential_skills: Optional[str] = None
    gender_preferred: Optional[str] = None
    work_location: Optional[str] = None
    urgency_level: Optional[str] = None
    required_date: Optional[str] = None
    assignee: Optional[str] = None
    jd: Optional[JobDescription] = None


class RequisitionDecision(BaseModel):
    """One endpoint drives the whole chain: the server decides which step the caller is taking
    from the requisition's current state, so the client can't skip one."""
    action: str                               # advance | reject | resubmit
    remarks: Optional[str] = ""
    salary_change: Optional[str] = ""         # MD may revise the offered CTC while approving


class RequisitionClose(BaseModel):
    closing_status: str                       # Hired | Closed | Hold | Cancelled | Open
    remarks: Optional[str] = ""


# ─── Candidate pipeline (Phase 6) ───────────────────────────────────────────────
# A posting is one JD published to one platform, each with its own public code so applications
# can be attributed to the channel that produced them.
POSTING_OPEN = "Open"
POSTING_PAUSED = "Paused"
POSTING_CLOSED = "Closed"
POSTING_STATES = [POSTING_OPEN, POSTING_PAUSED, POSTING_CLOSED]

# The pipeline. `stage` is the single source of truth for where a candidate stands; the
# reference spreads this across several boolean-ish columns and they disagree.
STAGE_APPLIED     = "Applied"
STAGE_SHORTLISTED = "Shortlisted"
STAGE_ASSESSMENT  = "Assessment"
STAGE_INTERVIEW   = "Interview"
STAGE_OFFER       = "Offer"
STAGE_HIRED       = "Hired"
STAGE_REJECTED    = "Rejected"
CANDIDATE_STAGES = [
    STAGE_APPLIED, STAGE_SHORTLISTED, STAGE_ASSESSMENT,
    STAGE_INTERVIEW, STAGE_OFFER, STAGE_HIRED, STAGE_REJECTED,
]
# Rejection is reachable from anywhere; everything else moves forward only.
CANDIDATE_FORWARD = [
    STAGE_APPLIED, STAGE_SHORTLISTED, STAGE_ASSESSMENT,
    STAGE_INTERVIEW, STAGE_OFFER, STAGE_HIRED,
]

ASSESSMENT_SENT      = "Sent"
ASSESSMENT_OPENED    = "Opened"
ASSESSMENT_SUBMITTED = "Submitted"
ASSESSMENT_REVIEWED  = "Reviewed"

INTERVIEW_SCHEDULED = "Scheduled"
INTERVIEW_DONE      = "Completed"
INTERVIEW_CANCELLED = "Cancelled"


class PostingCreate(BaseModel):
    request_no: str                        # the approved requisition this publishes
    platform: str                          # LinkedIn / Naukri / Referral / Careers page …
    notes: Optional[str] = ""
    expires_on: Optional[str] = None       # ISO date; after this the public link stops accepting


class PostingUpdate(BaseModel):
    platform: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    expires_on: Optional[str] = None


class PublicApplication(BaseModel):
    """What an anonymous applicant sends. Deliberately minimal — every extra field is another
    thing to validate on an unauthenticated endpoint."""
    full_name: str
    email: str
    phone: Optional[str] = ""
    current_company: Optional[str] = ""
    experience_years: Optional[str] = ""
    current_ctc: Optional[str] = ""
    expected_ctc: Optional[str] = ""
    notice_period: Optional[str] = ""
    cover_note: Optional[str] = ""
    resume: Optional[str] = None           # base64; size-capped server-side


class CandidateCreate(BaseModel):
    """HR entering a candidate directly, bypassing the public link."""
    request_no: Optional[str] = ""
    full_name: str
    email: str
    phone: Optional[str] = ""
    current_company: Optional[str] = ""
    experience_years: Optional[str] = ""
    current_ctc: Optional[str] = ""
    expected_ctc: Optional[str] = ""
    notice_period: Optional[str] = ""
    source: Optional[str] = "Direct"


class ScreenDecision(BaseModel):
    """Move one or many candidates along the pipeline in a single call."""
    candidate_ids: List[str]
    stage: str
    remarks: Optional[str] = ""


class AssessmentSend(BaseModel):
    title: str = "Written assessment"
    instructions: Optional[str] = ""
    questions: List[str] = []
    due_on: Optional[str] = None


class AssessmentSubmission(BaseModel):
    answers: List[str] = []
    note: Optional[str] = ""


class AssessmentReview(BaseModel):
    score: Optional[float] = None
    remarks: Optional[str] = ""
    passed: Optional[bool] = None


class InterviewSchedule(BaseModel):
    round_name: str = "Round 1"
    scheduled_at: str                      # ISO datetime
    duration_minutes: int = 45
    mode: Optional[str] = "In person"      # In person / Video / Phone
    location: Optional[str] = ""
    interviewer_ids: List[str] = []        # Sparsh staff ids


class InterviewEvaluation(BaseModel):
    recommendation: str                    # Proceed | Hold | Reject
    score: Optional[float] = None
    strengths: Optional[str] = ""
    concerns: Optional[str] = ""
    remarks: Optional[str] = ""


# ─── Offer & onboarding (Phase 7) ───────────────────────────────────────────────
OFFER_DRAFT    = "Draft"
OFFER_SENT     = "Sent"
OFFER_ACCEPTED = "Accepted"
OFFER_DECLINED = "Declined"
OFFER_WITHDRAWN = "Withdrawn"
OFFER_STATES = [OFFER_DRAFT, OFFER_SENT, OFFER_ACCEPTED, OFFER_DECLINED, OFFER_WITHDRAWN]
# Once the candidate has answered, the public link is spent. Kept as one list so every guard
# uses the same definition of "already decided".
OFFER_FINAL = [OFFER_ACCEPTED, OFFER_DECLINED, OFFER_WITHDRAWN]

ONB_INVITED   = "Invited"
ONB_SUBMITTED = "Submitted"
ONB_VERIFIED  = "Verified"
ONB_CONVERTED = "Converted"
ONB_STATES = [ONB_INVITED, ONB_SUBMITTED, ONB_VERIFIED, ONB_CONVERTED]


class OfferCreate(BaseModel):
    designation: str
    department: Optional[str] = ""
    annual_ctc: float
    joining_date: str                       # ISO "YYYY-MM-DD"
    location: Optional[str] = ""
    employment_type: Optional[str] = "Full-time"
    probation_months: Optional[int] = 6
    notes: Optional[str] = ""
    valid_till: Optional[str] = None         # after this the public link stops accepting


class OfferDecision(BaseModel):
    """What the candidate sends from the public offer link."""
    accept: bool
    note: Optional[str] = ""


class OnboardingInvite(BaseModel):
    """HR opening the KYC form for a candidate who accepted."""
    message: Optional[str] = ""
    due_on: Optional[str] = None


class OnboardingSubmission(BaseModel):
    """KYC the candidate fills in from the public link.

    Bank and statutory identifiers arrive here, which is why the read side is HR-only and why
    a submission is refused once HR has verified it — see the route guards.
    """
    date_of_birth: Optional[str] = None
    gender: Optional[str] = ""
    personal_email: Optional[str] = ""
    phone: Optional[str] = ""
    address: Optional[str] = ""
    emergency_name: Optional[str] = ""
    emergency_relation: Optional[str] = ""
    emergency_phone: Optional[str] = ""
    pan: Optional[str] = ""
    aadhaar: Optional[str] = ""
    passport: Optional[str] = ""
    driving_license: Optional[str] = ""
    uan: Optional[str] = ""
    esic_no: Optional[str] = ""
    bank_name: Optional[str] = ""
    bank_account: Optional[str] = ""
    bank_ifsc: Optional[str] = ""


class OnboardingVerify(BaseModel):
    remarks: Optional[str] = ""


class ConvertToEmployee(BaseModel):
    """Turn a verified onboarding into an employee record.

    `user_id` optionally links the new employee to an existing Sparsh staff login. Provisioning
    accounts is out of scope here — an employee can exist before their login does.
    """
    user_id: Optional[str] = None
    date_of_joining: Optional[str] = None    # defaults to the offer's joining date


# ─── Payroll (Phase 4) ──────────────────────────────────────────────────────────
SETTING_PAYROLL = "hrms_payroll"


class PayrollRunRequest(BaseModel):
    year: int
    month: int                       # 1-12


class PayrollConfigUpdate(BaseModel):
    """Every field optional. Bounds are enforced in the service, because these values feed the
    salary maths directly."""
    salary_base_days: Optional[int] = None
    shift_start: Optional[int] = None
    shift_end: Optional[int] = None
    working_hours_per_day: Optional[int] = None
    late_flat_fine_after: Optional[int] = None
    late_flat_fine_amount: Optional[float] = None
    late_hour_penalty_after: Optional[int] = None
    late_hour_penalty_hours: Optional[float] = None
    ot_eligible_from: Optional[int] = None
    ot_min_minutes: Optional[int] = None
    ot_multiplier: Optional[float] = None
    unauthorized_leave_penalty_days: Optional[float] = None
    paid_leaves_per_year: Optional[float] = None
    max_monthly_leaves_before_sunday_loss: Optional[float] = None
    professional_tax: Optional[float] = None


class HrmsAccessResponse(BaseModel):
    """What /api/hrms/meta returns — lets the UI render the right nav without guessing at
    role names, exactly as the backend computed it."""
    has_access: bool
    permissions: dict          # {module: {create, read, update, delete}} for the HRMS modules
    is_superadmin: bool
    modules: List[str]         # HRMS permission module names
    employee_code: Optional[str] = None   # set once the caller has an employee record (Phase 1)
