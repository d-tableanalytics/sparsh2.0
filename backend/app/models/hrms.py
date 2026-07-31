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


class HrmsAccessResponse(BaseModel):
    """What /api/hrms/meta returns — lets the UI render the right nav without guessing at
    role names, exactly as the backend computed it."""
    has_access: bool
    permissions: dict          # {module: {create, read, update, delete}} for the HRMS modules
    is_superadmin: bool
    modules: List[str]         # HRMS permission module names
    employee_code: Optional[str] = None   # set once the caller has an employee record (Phase 1)
