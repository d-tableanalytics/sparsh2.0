"""
HRMS ▸ domain models, collection registry and capability map.

Single source of truth for:
  • every `hrms_*` collection name the module will use (namespace registry),
  • the indexes provisioned at startup (`HRMS_INDEXES` — consumed by db/mongodb.py),
  • the role translation from the ERP's identity model to HRMS roles,
  • the capability registry + default role matrix that EVERY authorization decision
    resolves through (see utils/hrms_access.py).

Mirrors the structure of app/models/tpms.py so the module reads like the rest of the ERP.

── Two deliberate departures from the source HRMS spec ──────────────────────────
1. **Identity is keyed on `user_id` (ObjectId), never on a name string.** The source
   joined every HR-ops table on `users.name`, so renaming a user silently orphaned
   their leave history, balances and permission grants (BACKEND_ANALYSIS §4.4, Risk #4).
   Keying on the immutable `_id` removes that entire class of bug by construction.
2. **One authorization mechanism.** The source had four overlapping ones with three
   different "admin" role sets (BACKEND_ANALYSIS Risk #13). Here there is exactly one:
   `can(user, capability)` in utils/hrms_access.py, resolving through the registry below.

── Phase discipline ─────────────────────────────────────────────────────────────
Collection *names* are all declared up front — they are a namespace map and prevent
later collisions. But `HRMS_INDEXES` grows ONE PHASE AT A TIME: a collection is only
provisioned once the phase that owns it lands, so every DB change stays reviewable.
Capabilities follow the same rule (see CAPABILITIES).
"""
from enum import Enum
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
# Collections — full namespace map (provisioning is phased, see HRMS_INDEXES)
# ─────────────────────────────────────────────────────────────
# Phase 1 — foundation
COLL_AUDIT_LOG        = "hrms_audit_log"
COLL_COUNTERS         = "hrms_counters"

# Phase 2 — employee master
COLL_EMPLOYEE_PROFILES = "hrms_employee_profiles"
COLL_DEPARTMENTS       = "hrms_departments"
COLL_DESIGNATIONS      = "hrms_designations"

# Phase 3-9 — recruitment
COLL_REQUISITIONS     = "hrms_requisitions"
COLL_JOB_DESCRIPTIONS = "hrms_job_descriptions"
COLL_JOB_POSTINGS     = "hrms_job_postings"
COLL_CANDIDATES       = "hrms_candidates"
COLL_ASSESSMENTS      = "hrms_assessments"
COLL_INTERVIEWS       = "hrms_interviews"
COLL_OFFERS           = "hrms_offers"
COLL_ONBOARDING       = "hrms_onboarding"
COLL_PUBLIC_RATELIMIT = "hrms_public_rate_limit"

# Phase 11-R — recruitment review enhancements
COLL_LINKS               = "hrms_links"
COLL_DOCUMENTS           = "hrms_documents"
COLL_DOCUMENT_TYPES      = "hrms_document_types"
COLL_APPOINTMENTS        = "hrms_appointments"
COLL_CLIENTS             = "hrms_clients"
COLL_SANCTIONED_STRENGTH = "hrms_sanctioned_strength"

# Phase 11-14 — settings, HR operations, payroll
COLL_SETTINGS         = "hrms_settings"
COLL_PERMISSIONS      = "hrms_permissions"
COLL_LEAVES           = "hrms_leaves"
COLL_LEAVE_BALANCES   = "hrms_leave_balances"
COLL_HOLIDAYS         = "hrms_holidays"
COLL_ATTENDANCE       = "hrms_attendance"
COLL_PUNCH_SEGMENTS   = "hrms_punch_segments"
COLL_ATTENDANCE_CORRECTIONS = "hrms_attendance_corrections"
COLL_PAYROLL_RUNS     = "hrms_payroll_runs"
COLL_PAYROLL_RECORDS  = "hrms_payroll_records"


# ─────────────────────────────────────────────────────────────
# Index registry — provisioned idempotently at startup by db/mongodb.py
# Format: (collection, keys, options)  — identical shape to TPMS_INDEXES.
# ─────────────────────────────────────────────────────────────
HRMS_INDEXES = [
    # ── Phase 1 ──
    # Audit reads are always "what happened to this entity" or "what happened in this
    # company lately"; both are indexed so the Phase 5 candidate journey and the Phase 15
    # audit API never collection-scan.
    (COLL_AUDIT_LOG, [("entity", 1), ("entity_id", 1)],      {"name": "by_entity"}),
    (COLL_AUDIT_LOG, [("company_id", 1), ("created_at", -1)], {"name": "by_company_recent"}),
    (COLL_AUDIT_LOG, [("actor_id", 1), ("created_at", -1)],   {"name": "by_actor_recent"}),
    # Counters are fetched by _id only (the sequence key) — no secondary index needed.
    # Declared here so the collection is created at startup rather than on first write.
    (COLL_COUNTERS,  [("scope", 1)],                          {"name": "by_scope"}),

    # ── Phase 2: employee master ──
    # One profile per user, enforced at the DB level: a profile EXTENDS the identity in
    # staff/learners, it is never a second copy of it.
    # SPARSE, deliberately: Phase 9 creates an employee record at onboarding, BEFORE the
    # person has a login. Those rows omit  entirely (not null -- a null value is
    # still indexed), so any number of them can coexist while a linked profile stays unique.
    (COLL_EMPLOYEE_PROFILES, [("user_id", 1)],                {"unique": True, "sparse": True,
                                                               "name": "uniq_user"}),
    (COLL_EMPLOYEE_PROFILES, [("company_id", 1), ("employment_status", 1)],
                                                              {"name": "by_company_status"}),
    # Sparse: a profile may exist before a code is minted, but codes never collide.
    (COLL_EMPLOYEE_PROFILES, [("company_id", 1), ("employee_code", 1)],
                                                              {"unique": True, "sparse": True,
                                                               "name": "uniq_company_code"}),
    (COLL_EMPLOYEE_PROFILES, [("company_id", 1), ("department_id", 1)],
                                                              {"name": "by_company_department"}),
    (COLL_DEPARTMENTS,  [("company_id", 1), ("name", 1)],     {"unique": True, "name": "uniq_company_name"}),
    (COLL_DESIGNATIONS, [("company_id", 1), ("name", 1)],     {"unique": True, "name": "uniq_company_name"}),

    # ── Phase 3: requisitions + job descriptions ──
    (COLL_REQUISITIONS, [("request_no", 1)],                  {"unique": True, "name": "uniq_request_no"}),
    (COLL_REQUISITIONS, [("company_id", 1), ("approval_status", 1)],
                                                              {"name": "by_company_approval"}),
    (COLL_REQUISITIONS, [("company_id", 1), ("closing_status", 1)],
                                                              {"name": "by_company_closing"}),
    (COLL_REQUISITIONS, [("company_id", 1), ("created_by", 1)],
                                                              {"name": "by_company_creator"}),
    (COLL_REQUISITIONS, [("company_id", 1), ("department_id", 1)],
                                                              {"name": "by_company_department"}),
    (COLL_JOB_DESCRIPTIONS, [("jd_no", 1)],                   {"unique": True, "name": "uniq_jd_no"}),
    (COLL_JOB_DESCRIPTIONS, [("request_no", 1)],              {"name": "by_request"}),
    (COLL_JOB_DESCRIPTIONS, [("company_id", 1), ("status", 1)],
                                                              {"name": "by_company_status"}),

    # ── Phase 4: job postings + public application intake ──
    (COLL_JOB_POSTINGS, [("posting_code", 1)],                {"unique": True, "name": "uniq_posting_code"}),
    (COLL_JOB_POSTINGS, [("jd_no", 1)],                       {"name": "by_jd"}),
    (COLL_JOB_POSTINGS, [("company_id", 1), ("live_status", 1)],
                                                              {"name": "by_company_live"}),
    (COLL_JOB_POSTINGS, [("request_no", 1)],                  {"name": "by_request"}),
    (COLL_CANDIDATES,   [("uk", 1)],                          {"unique": True, "name": "uniq_uk"}),
    (COLL_CANDIDATES,   [("company_id", 1), ("application_status", 1)],
                                                              {"name": "by_company_status"}),
    (COLL_CANDIDATES,   [("posting_code", 1)],                {"name": "by_posting"}),
    (COLL_CANDIDATES,   [("request_no", 1)],                  {"name": "by_request"}),
    # Duplicate detection runs on every public application, so both must be indexed.
    (COLL_CANDIDATES,   [("company_id", 1), ("can_email", 1)], {"name": "by_company_email"}),
    (COLL_CANDIDATES,   [("company_id", 1), ("can_contact", 1)], {"name": "by_company_phone"}),
    # Mongo's TTL monitor sweeps roughly every 60s; that is cleanup only. Expiry is enforced
    # arithmetically in the limiter, so a late sweep can never widen the window.
    (COLL_PUBLIC_RATELIMIT, [("expires_at", 1)],              {"expireAfterSeconds": 0,
                                                               "name": "ttl_expires"}),

    # ── Phase 6: assessments ──
    (COLL_ASSESSMENTS, [("assessment_no", 1)],                {"unique": True, "name": "uniq_assessment_no"}),
    # The access code is the ONLY credential protecting a candidate's submission, so it is
    # both unique and indexed -- every public request looks up by it.
    (COLL_ASSESSMENTS, [("access_code", 1)],                  {"unique": True, "name": "uniq_access_code"}),
    (COLL_ASSESSMENTS, [("uk", 1)],                           {"name": "by_candidate"}),
    (COLL_ASSESSMENTS, [("company_id", 1), ("status", 1)],    {"name": "by_company_status"}),
    (COLL_ASSESSMENTS, [("request_no", 1)],                   {"name": "by_request"}),

    # ── Phase 7: interviews ──
    (COLL_INTERVIEWS, [("interview_no", 1)],                  {"unique": True, "name": "uniq_interview_no"}),
    (COLL_INTERVIEWS, [("uk", 1)],                            {"name": "by_candidate"}),
    (COLL_INTERVIEWS, [("company_id", 1), ("status", 1)],     {"name": "by_company_status"}),
    # The board groups by day, so the feed always sorts on this.
    (COLL_INTERVIEWS, [("company_id", 1), ("scheduled_at", 1)],
                                                              {"name": "by_company_when"}),
    # An interviewer's own list is the default view for non-privileged users.
    (COLL_INTERVIEWS, [("interviewer_id", 1)],                {"name": "by_interviewer"}),

    # ── Phase 8: offers ──
    (COLL_OFFERS, [("offer_no", 1)],                          {"unique": True, "name": "uniq_offer_no"}),
    # The access code is the candidate's only credential; every public request looks it up.
    (COLL_OFFERS, [("access_code", 1)],                       {"unique": True, "name": "uniq_access_code"}),
    (COLL_OFFERS, [("uk", 1)],                                {"name": "by_candidate"}),
    (COLL_OFFERS, [("company_id", 1), ("status", 1)],         {"name": "by_company_status"}),
    (COLL_OFFERS, [("request_no", 1)],                        {"name": "by_request"}),

    # ── Phase 9: onboarding ──
    (COLL_ONBOARDING, [("onb_no", 1)],                        {"unique": True, "name": "uniq_onb_no"}),
    (COLL_ONBOARDING, [("access_code", 1)],                   {"unique": True, "name": "uniq_access_code"}),
    (COLL_ONBOARDING, [("uk", 1)],                            {"unique": True, "name": "uniq_candidate"}),
    (COLL_ONBOARDING, [("company_id", 1), ("status", 1)],     {"name": "by_company_status"}),
    # Sparse: the id is minted partway through, so most rows have none yet.
    (COLL_ONBOARDING, [("employee_id", 1)],                   {"unique": True, "sparse": True,
                                                               "name": "uniq_employee_id"}),

    # -- Phase 10: date-ranged analytics ------------------------------------------
    # Every dashboard query is `company_id` + a date window. Without these the planner can
    # only use the company_id prefix of an existing (company_id, status) index and then
    # filters by date in memory, which degrades as history accumulates.
    (COLL_CANDIDATES,   [("company_id", 1), ("applied_at", -1)], {"name": "by_company_applied"}),
    (COLL_OFFERS,       [("company_id", 1), ("created_at", -1)], {"name": "by_company_created"}),
    (COLL_ONBOARDING,   [("company_id", 1), ("created_at", -1)], {"name": "by_company_created"}),
    (COLL_REQUISITIONS, [("company_id", 1), ("created_at", -1)], {"name": "by_company_created"}),

    # ── Phase 11-R: link registry, documents, appointments, clients, sanction ──
    # The registry is looked up by CODE on every public request (the revocation guard), so
    # that index is unique and is the hot one. The rest serve the Link Manager's filters.
    (COLL_LINKS, [("code", 1)],                               {"unique": True, "name": "uniq_code"}),
    (COLL_LINKS, [("link_id", 1)],                            {"unique": True, "name": "uniq_link_id"}),
    (COLL_LINKS, [("company_id", 1), ("kind", 1), ("status", 1)],
                                                              {"name": "by_company_kind_status"}),
    (COLL_LINKS, [("company_id", 1), ("created_at", -1)],     {"name": "by_company_created"}),
    (COLL_LINKS, [("target_id", 1)],                          {"name": "by_target"}),
    (COLL_LINKS, [("request_no", 1)],                         {"name": "by_request"}),

    (COLL_DOCUMENTS, [("doc_no", 1)],                         {"unique": True, "name": "uniq_doc_no"}),
    (COLL_DOCUMENTS, [("company_id", 1), ("owner_type", 1), ("owner_id", 1)],
                                                              {"name": "by_owner"}),
    (COLL_DOCUMENTS, [("company_id", 1), ("status", 1)],      {"name": "by_company_status"}),
    # Drives the expiring-soon filter, which is a range scan on this field.
    (COLL_DOCUMENTS, [("company_id", 1), ("expiry_date", 1)], {"name": "by_company_expiry"}),
    (COLL_DOCUMENTS, [("request_no", 1)],                     {"name": "by_request"}),
    (COLL_DOCUMENT_TYPES, [("company_id", 1), ("name", 1)],   {"unique": True,
                                                               "name": "uniq_company_name"}),

    # One appointment letter per candidate, enforced at the DB level: the letter confirms
    # joining terms, and two of them for one person is a contradiction, not a workflow.
    (COLL_APPOINTMENTS, [("appointment_no", 1)],              {"unique": True,
                                                               "name": "uniq_appointment_no"}),
    (COLL_APPOINTMENTS, [("access_code", 1)],                 {"unique": True,
                                                               "name": "uniq_access_code"}),
    (COLL_APPOINTMENTS, [("uk", 1)],                          {"unique": True,
                                                               "name": "uniq_candidate"}),
    (COLL_APPOINTMENTS, [("company_id", 1), ("status", 1)],   {"name": "by_company_status"}),
    (COLL_APPOINTMENTS, [("request_no", 1)],                  {"name": "by_request"}),

    (COLL_CLIENTS, [("client_id", 1)],                        {"unique": True,
                                                               "name": "uniq_client_id"}),
    (COLL_CLIENTS, [("company_id", 1), ("name", 1)],          {"unique": True,
                                                               "name": "uniq_company_name"}),
    (COLL_CLIENTS, [("company_id", 1), ("active", 1)],        {"name": "by_company_active"}),

    # One sanctioned figure per position per company — the uniqueness IS the rule.
    (COLL_SANCTIONED_STRENGTH,
     [("company_id", 1), ("department_id", 1), ("designation_id", 1)],
     {"unique": True, "name": "uniq_company_position"}),
    # ── Later phases append their indexes here, one phase at a time. ──
]


# ─────────────────────────────────────────────────────────────
# Roles — translation from the ERP identity model to HRMS roles
# ─────────────────────────────────────────────────────────────
# The ERP has two user collections and two role axes:
#   • `staff`    → role: superadmin | admin | coach | staff        (Sparsh internal)
#   • `learners` → role: clientadmin | clientuser                  (client-side)
#                  + governance_role: MD | HR | HOD | IMPLEMENTOR   (the client ladder,
#                    already used by auth_controller.client_rank)
#
# HRMS is a CLIENT-COMPANY module: a client's HR team hires and pays their own staff,
# scoped by company_id. Sparsh internal staff get cross-company admin/support visibility.
# This mirrors TPMS/ORM/Delegation exactly.
class HrmsRole(str, Enum):
    ADMIN    = "admin"      # Sparsh superadmin — full HRMS owner, cross-company
    INTERNAL = "internal"   # Sparsh admin/coach/staff — cross-company operator + support
    MD       = "md"         # client MD / clientadmin — final approver within their company
    HR       = "hr"         # client HR — the recruitment + HR-ops operator
    MANAGER  = "manager"    # client HOD — hiring manager; raises reqs, co-reviews assessments
    EMPLOYEE = "employee"   # client implementor / plain user — self-service only


# Which ERP roles map into the two internal HRMS roles.
INTERNAL_OWNER_ROLES = {"superadmin"}
INTERNAL_STAFF_ROLES = {"admin", "coach", "staff"}
CLIENT_ROLES         = {"clientadmin", "clientuser"}

# Client governance ladder → HRMS role. `clientadmin` is the company's top authority and
# maps to MD independently of governance_role (auth_controller.client_rank does the same).
GOVERNANCE_TO_HRMS = {
    "MD":          HrmsRole.MD,
    "HR":          HrmsRole.HR,
    "HOD":         HrmsRole.MANAGER,
    "IMPLEMENTOR": HrmsRole.EMPLOYEE,
}

# Roles permitted to switch the HRMS module on/off for a company. Matches the TPMS
# toggle rule (utils/tpms_access.TOGGLE_ROLES) — Admin / Super Admin only.
TOGGLE_ROLES = {"superadmin", "admin"}


# ─────────────────────────────────────────────────────────────
# Capabilities — the ONE authorization vocabulary
# ─────────────────────────────────────────────────────────────
# Format: "<domain>.<action>". Every gate in every phase resolves through
# utils/hrms_access.can(user, capability) — never an ad-hoc role check.
#
# Phase discipline: each phase registers the capabilities it actually enforces.
# Phase 11 builds the admin console over whatever is registered by then.
class Cap(str, Enum):
    # ── Phase 1 ──
    MODULE_ACCESS = "module.access"   # may open HRMS at all
    MODULE_ADMIN  = "module.admin"    # may administer HRMS configuration
    AUDIT_READ    = "audit.read"      # may read the audit trail

    # ── Phase 2: employee master ──
    EMPLOYEE_READ         = "employee.read"          # browse the directory (row-scoped by role)
    EMPLOYEE_WRITE        = "employee.write"         # create / edit employee profiles
    EMPLOYEE_SALARY_READ  = "employee.salary.read"   # SEE pay figures
    EMPLOYEE_SALARY_WRITE = "employee.salary.write"  # SET pay figures
    DEPARTMENT_READ       = "department.read"
    DEPARTMENT_WRITE      = "department.write"
    DESIGNATION_READ      = "designation.read"
    DESIGNATION_WRITE     = "designation.write"

    # ── Phase 3: requisitions + job descriptions ──
    REQUISITION_READ       = "requisition.read"
    REQUISITION_CREATE     = "requisition.create"      # raise one — deliberately open to all
    REQUISITION_WRITE      = "requisition.write"       # edit / delete
    REQUISITION_REVIEW_HR  = "requisition.review_hr"   # stage 1: forward to MD, or reject
    REQUISITION_APPROVE_MD = "requisition.approve_md"  # stage 2: final approval
    REQUISITION_CLOSE      = "requisition.close"       # set Hired/Closed/Hold/Cancel
    JD_READ                = "jd.read"
    JD_WRITE               = "jd.write"

    # ── Phase 4: job postings ──
    POSTING_READ  = "posting.read"
    POSTING_WRITE = "posting.write"    # publish / pause / close / delete

    # ── Phase 5: candidates + screening ──
    CANDIDATE_READ   = "candidate.read"
    CANDIDATE_WRITE  = "candidate.write"    # add / edit / delete a candidate record
    CANDIDATE_SCREEN = "candidate.screen"   # shortlist / hold / reject / forward

    # ── Phase 6: assessments ──
    ASSESSMENT_READ   = "assessment.read"
    ASSESSMENT_SEND   = "assessment.send"     # operational: issue an assessment
    ASSESSMENT_REVIEW = "assessment.review"   # a DECISION: Pass / Fail

    # ── Phase 7: interviews ──
    INTERVIEW_READ      = "interview.read"       # widens the list beyond your own
    INTERVIEW_SCHEDULE  = "interview.schedule"   # operational: book / reschedule / cancel
    INTERVIEW_EVALUATE  = "interview.evaluate"   # a DECISION: the scorecard
    INTERVIEW_DECIDE_MD = "interview.decide_md"  # the FINAL call, MD only

    # ── Phase 8: offers ──
    OFFER_READ  = "offer.read"
    OFFER_WRITE = "offer.write"   # draft / edit / delete a draft
    OFFER_SEND  = "offer.send"    # the COMMITMENT: issue or revoke a live offer

    # ── Phase 9: onboarding ──
    ONBOARDING_READ        = "onboarding.read"
    ONBOARDING_WRITE       = "onboarding.write"        # start, checklist, BG, KYC, details
    ONBOARDING_GENERATE_ID = "onboarding.generate_id"  # mints the EMPLOYEE RECORD

    # ── Phase 10: analytics & reports (READ-ONLY) ──
    ANALYTICS_READ = "analytics.read"   # dashboard, funnel, breakdowns
    REPORT_READ    = "report.read"      # the detailed tabbed tables
    REPORT_EXPORT  = "report.export"    # taking data OUT of the system

    # ── Phase 11-R: recruitment review enhancements ──
    # Item 1 — the public-link registry.
    LINK_READ   = "link.read"     # see every issued link and its open history
    LINK_MANAGE = "link.manage"   # revoke / reissue — killing a live credential
    # Item 2 — documentation.
    DOCUMENT_READ   = "document.read"
    DOCUMENT_WRITE  = "document.write"   # upload, version, edit metadata, delete
    DOCUMENT_VERIFY = "document.verify"  # a DECISION: Verified / Rejected
    # Item 3 — appointment letters. Mirrors the offer capabilities exactly: read, author,
    # and a separate COMMITMENT capability for issuing one.
    APPOINTMENT_READ  = "appointment.read"
    APPOINTMENT_WRITE = "appointment.write"
    APPOINTMENT_SEND  = "appointment.send"
    # Item 4 — the client master (recruitment-agency model; see PHASE_11R_REPORT §Decisions).
    CLIENT_READ  = "client.read"
    CLIENT_WRITE = "client.write"
    # Item 7 — sanctioned strength + the escalation ladder.
    SANCTION_READ  = "sanction.read"
    SANCTION_WRITE = "sanction.write"
    REQUISITION_ESCALATE = "requisition.escalate"   # act on an over-sanction escalation step
    # ── Later phases append their capabilities here. ──


# Default capability set per HRMS role. Phase 11 layers per-user grants on top of this;
# until then this matrix IS the permission model.
#
# ADMIN is deliberately absent — it is granted everything implicitly in `can()`, so a new
# capability can never accidentally lock the owner out (the source had exactly this bug
# class, BACKEND_ANALYSIS Risk #13).
#
# On INTERNAL and salary: Sparsh staff administer HRMS for their clients, but they are
# deliberately NOT granted employee.salary.* — a client's pay data is not support-staff
# business. (Superadmin still sees everything via the implicit-ADMIN rule; that is the
# system owner, and it is a conscious, documented exception.)
#
# On the two approval capabilities: REVIEW_HR and APPROVE_MD are held by DIFFERENT roles on
# purpose. A two-stage approval where one person can perform both stages is not a control.
# HR forwards; MD approves. (superadmin still holds both via the implicit-ADMIN rule, which
# is the documented break-glass path — see PHASE_3_REPORT Finding #1.)
ROLE_CAPABILITIES: Dict[HrmsRole, Set[Cap]] = {
    HrmsRole.INTERNAL: {
        Cap.MODULE_ACCESS, Cap.MODULE_ADMIN, Cap.AUDIT_READ,
        Cap.EMPLOYEE_READ, Cap.EMPLOYEE_WRITE,
        Cap.DEPARTMENT_READ, Cap.DEPARTMENT_WRITE,
        Cap.DESIGNATION_READ, Cap.DESIGNATION_WRITE,
        # Sparsh staff support and observe the hiring pipeline, but the approval chain is
        # the client's own governance decision — hence no REVIEW_HR / APPROVE_MD here.
        Cap.REQUISITION_READ, Cap.REQUISITION_CREATE, Cap.REQUISITION_WRITE,
        Cap.REQUISITION_CLOSE, Cap.JD_READ, Cap.JD_WRITE,
        Cap.POSTING_READ, Cap.POSTING_WRITE,
        Cap.CANDIDATE_READ, Cap.CANDIDATE_WRITE,
        Cap.ASSESSMENT_READ, Cap.ASSESSMENT_SEND,
        Cap.INTERVIEW_READ, Cap.INTERVIEW_SCHEDULE,
        Cap.OFFER_READ,
        Cap.ONBOARDING_READ, Cap.ONBOARDING_WRITE, Cap.ONBOARDING_GENERATE_ID,
        # Sparsh staff support clients, which means answering "how is hiring going".
        # Read-only, and every figure is company-scoped -- see hrms_analytics_service.
        Cap.ANALYTICS_READ, Cap.REPORT_READ, Cap.REPORT_EXPORT,
        # ── Phase 11-R ──
        # Support routinely means "the candidate says the link does not work", so operating
        # the link registry is squarely support work.
        Cap.LINK_READ, Cap.LINK_MANAGE,
        # Collecting documents is operational; VERIFYING one is the client's own governance
        # act, the same boundary that keeps REQUISITION_REVIEW_HR off this list.
        Cap.DOCUMENT_READ, Cap.DOCUMENT_WRITE,
        # Read only, for the same reason OFFER_SEND is withheld: issuing an appointment
        # letter commits the client to employing somebody.
        Cap.APPOINTMENT_READ,
        Cap.CLIENT_READ, Cap.CLIENT_WRITE,
        Cap.SANCTION_READ,
    },
    HrmsRole.MD: {
        Cap.MODULE_ACCESS, Cap.MODULE_ADMIN, Cap.AUDIT_READ,
        Cap.EMPLOYEE_READ, Cap.EMPLOYEE_WRITE,
        Cap.EMPLOYEE_SALARY_READ, Cap.EMPLOYEE_SALARY_WRITE,
        Cap.DEPARTMENT_READ, Cap.DEPARTMENT_WRITE,
        Cap.DESIGNATION_READ, Cap.DESIGNATION_WRITE,
        Cap.REQUISITION_READ, Cap.REQUISITION_CREATE, Cap.REQUISITION_WRITE,
        Cap.REQUISITION_APPROVE_MD, Cap.REQUISITION_CLOSE,
        Cap.JD_READ, Cap.JD_WRITE,
        Cap.POSTING_READ, Cap.POSTING_WRITE,
        Cap.CANDIDATE_READ, Cap.CANDIDATE_WRITE, Cap.CANDIDATE_SCREEN,
        Cap.ASSESSMENT_READ, Cap.ASSESSMENT_SEND, Cap.ASSESSMENT_REVIEW,
        Cap.INTERVIEW_READ, Cap.INTERVIEW_SCHEDULE, Cap.INTERVIEW_EVALUATE,
        Cap.INTERVIEW_DECIDE_MD,
        Cap.OFFER_READ, Cap.OFFER_WRITE, Cap.OFFER_SEND,
        Cap.ONBOARDING_READ, Cap.ONBOARDING_WRITE, Cap.ONBOARDING_GENERATE_ID,
        Cap.ANALYTICS_READ, Cap.REPORT_READ, Cap.REPORT_EXPORT,
        # ── Phase 11-R ──
        Cap.LINK_READ, Cap.LINK_MANAGE,
        Cap.DOCUMENT_READ, Cap.DOCUMENT_WRITE, Cap.DOCUMENT_VERIFY,
        Cap.APPOINTMENT_READ, Cap.APPOINTMENT_WRITE, Cap.APPOINTMENT_SEND,
        Cap.CLIENT_READ, Cap.CLIENT_WRITE,
        Cap.SANCTION_READ, Cap.SANCTION_WRITE,
        # MD holds the escalation capability as well as the final approval: an escalation
        # ladder that stalls because its top rung cannot act is not a control, it is a trap.
        Cap.REQUISITION_ESCALATE,
    },
    HrmsRole.HR: {
        Cap.MODULE_ACCESS, Cap.AUDIT_READ,
        Cap.EMPLOYEE_READ, Cap.EMPLOYEE_WRITE,
        Cap.EMPLOYEE_SALARY_READ, Cap.EMPLOYEE_SALARY_WRITE,
        Cap.DEPARTMENT_READ, Cap.DEPARTMENT_WRITE,
        Cap.DESIGNATION_READ, Cap.DESIGNATION_WRITE,
        Cap.REQUISITION_READ, Cap.REQUISITION_CREATE, Cap.REQUISITION_WRITE,
        Cap.REQUISITION_REVIEW_HR, Cap.REQUISITION_CLOSE,
        Cap.JD_READ, Cap.JD_WRITE,
        Cap.POSTING_READ, Cap.POSTING_WRITE,
        Cap.CANDIDATE_READ, Cap.CANDIDATE_WRITE, Cap.CANDIDATE_SCREEN,
        Cap.ASSESSMENT_READ, Cap.ASSESSMENT_SEND, Cap.ASSESSMENT_REVIEW,
        Cap.INTERVIEW_READ, Cap.INTERVIEW_SCHEDULE, Cap.INTERVIEW_EVALUATE,
        Cap.OFFER_READ, Cap.OFFER_WRITE, Cap.OFFER_SEND,
        Cap.ONBOARDING_READ, Cap.ONBOARDING_WRITE, Cap.ONBOARDING_GENERATE_ID,
        Cap.ANALYTICS_READ, Cap.REPORT_READ, Cap.REPORT_EXPORT,
        # ── Phase 11-R ──
        Cap.LINK_READ, Cap.LINK_MANAGE,
        Cap.DOCUMENT_READ, Cap.DOCUMENT_WRITE, Cap.DOCUMENT_VERIFY,
        Cap.APPOINTMENT_READ, Cap.APPOINTMENT_WRITE, Cap.APPOINTMENT_SEND,
        Cap.CLIENT_READ, Cap.CLIENT_WRITE,
        Cap.SANCTION_READ, Cap.SANCTION_WRITE,
        # Deliberately NO REQUISITION_ESCALATE: the escalation ladder is the reporting
        # hierarchy above the raiser, and HR reviewing then also escalating would collapse
        # two stages into one person -- the same separation the HR/MD split already draws.
    },
    # A hiring manager reads their own corner of the directory (enforced by row scoping in
    # hrms_employee_service, not by this set) and never sees pay. They RAISE requisitions --
    # that is the documented design intent: whoever raises one becomes its hiring manager.
    HrmsRole.MANAGER: {
        Cap.MODULE_ACCESS,
        Cap.EMPLOYEE_READ,
        Cap.DEPARTMENT_READ, Cap.DESIGNATION_READ,
        Cap.REQUISITION_READ, Cap.REQUISITION_CREATE, Cap.JD_READ,
        Cap.POSTING_READ,
        Cap.CANDIDATE_READ,
        Cap.ASSESSMENT_READ, Cap.ASSESSMENT_REVIEW,
        Cap.INTERVIEW_READ, Cap.INTERVIEW_EVALUATE,
        Cap.OFFER_READ,
        Cap.ONBOARDING_READ,
        # A hiring manager sees analytics for THEIR OWN requisitions only -- the same row
        # scoping the candidate list applies, enforced in the service rather than here.
        # Deliberately NO export: aggregate figures on screen are one thing, a downloadable
        # file of every candidate is another.
        Cap.ANALYTICS_READ, Cap.REPORT_READ,
        # ── Phase 11-R ──
        # Read only, and row-scoped to their own requisitions in the services (same
        # narrowing the candidate list applies), never enforced by this set alone.
        Cap.LINK_READ,
        Cap.DOCUMENT_READ,
        Cap.APPOINTMENT_READ,
        Cap.CLIENT_READ,
        Cap.SANCTION_READ,
        # A hiring manager IS the reporting line an over-sanction requisition escalates
        # through -- this is the capability that lets them clear their rung.
        Cap.REQUISITION_ESCALATE,
    },
    # Self-service, plus the deliberate exception that ANY employee may raise a hiring
    # requisition (FRONTEND_ANALYSIS §5: "anyone may raise a hiring requisition"). Reading
    # your OWN profile is not a capability -- it is an inherent right handled in the route,
    # so it can never be revoked by a permission edit.
    HrmsRole.EMPLOYEE: {
        Cap.MODULE_ACCESS,
        Cap.REQUISITION_READ, Cap.REQUISITION_CREATE, Cap.JD_READ,
        Cap.INTERVIEW_EVALUATE,
    },
}


# ─────────────────────────────────────────────────────────────
# Audit actions
# ─────────────────────────────────────────────────────────────
AUDIT_MODULE_ENABLED  = "hrms module enabled"
AUDIT_MODULE_DISABLED = "hrms module disabled"

# Entity names used in the audit log. Kept as constants so the Phase 5 candidate journey
# and the Phase 15 audit API filter on a closed vocabulary rather than free strings.
ENTITY_COMPANY     = "company"
ENTITY_REQUISITION = "requisition"
ENTITY_CANDIDATE   = "candidate"
ENTITY_EMPLOYEE    = "employee"
ENTITY_LEAVE       = "leave"
ENTITY_PAYROLL     = "payroll"
ENTITY_SETTING     = "setting"


# ─────────────────────────────────────────────────────────────
# Business-ID formats
# ─────────────────────────────────────────────────────────────
# The source generated these by scanning existing rows for the max suffix, which races
# under concurrency (BACKEND_ANALYSIS Risk #12). We use an atomic counter instead —
# see services/hrms_id_service.py. These are the format templates only (pure, no I/O).
ID_FORMATS = {
    "requisition": ("HR-REQ", True,  3),   # HR-REQ-2026-001   (prefix, year-scoped, pad)
    "jd":          ("JD",     True,  3),   # JD-2026-001
    "interview":   ("INT",    True,  3),   # INT-2026-001
    "offer":       ("OFR",    True,  3),   # OFR-2026-001
    "onboarding":  ("ONB",    True,  3),   # ONB-2026-001
    "assessment":  ("ASM",    True,  3),   # ASM-2026-001
    "employee":    ("EMP",    True,  3),   # EMP-2026-001
    "candidate":   ("CAN",    False, 3),   # CAN-001          (not year-scoped)
    # ── Phase 11-R ──
    "link":        ("LNK",    True,  3),   # LNK-2026-001
    "document":    ("DOC",    True,  3),   # DOC-2026-001
    "appointment": ("APT",    True,  3),   # APT-2026-001
    "client":      ("CLI",    False, 3),   # CLI-001          (a client outlives a year)
}


def format_business_id(kind: str, seq: int, year: Optional[int] = None) -> str:
    """Render a business id from its sequence number. Pure — no DB, no clock.

    The caller supplies `year` (and the atomic sequence) so this stays testable and
    free of hidden time dependencies, matching the payroll engine's discipline.
    """
    if kind not in ID_FORMATS:
        raise ValueError(f"Unknown business id kind: {kind}")
    prefix, year_scoped, pad = ID_FORMATS[kind]
    if year_scoped:
        if year is None:
            raise ValueError(f"Business id kind '{kind}' is year-scoped; `year` is required")
        return f"{prefix}-{year}-{str(seq).zfill(pad)}"
    return f"{prefix}-{str(seq).zfill(pad)}"


def counter_key(kind: str, company_id: str, year: Optional[int] = None) -> str:
    """The `_id` of the atomic counter document backing a business-id sequence.

    Scoped per company so two companies never share a sequence — a client must not be
    able to infer another client's hiring volume from gaps in their own numbering.
    """
    if kind not in ID_FORMATS:
        raise ValueError(f"Unknown business id kind: {kind}")
    _, year_scoped, _ = ID_FORMATS[kind]
    if year_scoped:
        if year is None:
            raise ValueError(f"Business id kind '{kind}' is year-scoped; `year` is required")
        return f"{company_id}:{kind}:{year}"
    return f"{company_id}:{kind}"


# ─────────────────────────────────────────────────────────────
# API models
# ─────────────────────────────────────────────────────────────
class HrmsHealthResponse(BaseModel):
    """GET /hrms/health — what the client needs to render the module shell.

    Returning the caller's resolved role + capability list here means the frontend
    never re-derives permissions from raw role strings, which is how the source ended
    up rendering buttons the API then refused (FRONTEND_ANALYSIS §5).
    """
    module: str = "hrms"
    enabled: bool
    role: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    company_id: Optional[str] = None
    is_internal: bool = False


class AuditEntry(BaseModel):
    """One row of the HRMS audit trail."""
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    action: str
    entity: str
    entity_id: Optional[str] = None
    detail: Optional[str] = None
    company_id: Optional[str] = None


# =============================================================
# Phase 2 - Employee master, departments, designations
# =============================================================

# ── Enumerations ──
class EmploymentStatus(str, Enum):
    ACTIVE     = "Active"
    ON_NOTICE  = "On Notice"
    RESIGNED   = "Resigned"
    TERMINATED = "Terminated"
    ON_LEAVE   = "On Long Leave"


class EmploymentType(str, Enum):
    FULL_TIME = "Full-time"
    PART_TIME = "Part-time"
    CONTRACT  = "Contract"
    INTERN    = "Intern"
    CONSULTANT = "Consultant"


class Gender(str, Enum):
    MALE   = "Male"
    FEMALE = "Female"
    OTHER  = "Other"


# Statuses that mean "still on the payroll". Phase 14 payroll runs over exactly this set,
# which is why it lives here rather than being re-derived per caller.
PAYABLE_STATUSES = {EmploymentStatus.ACTIVE, EmploymentStatus.ON_NOTICE, EmploymentStatus.ON_LEAVE}

AUDIT_EMPLOYEE_CREATED   = "employee profile created"
AUDIT_EMPLOYEE_UPDATED   = "employee profile updated"
AUDIT_SALARY_CHANGED     = "employee salary changed"
AUDIT_DEPARTMENT_CREATED = "department created"
AUDIT_DEPARTMENT_UPDATED = "department updated"
AUDIT_DEPARTMENT_DELETED = "department deleted"
AUDIT_DESIGNATION_CREATED = "designation created"
AUDIT_DESIGNATION_UPDATED = "designation updated"
AUDIT_DESIGNATION_DELETED = "designation deleted"

ENTITY_DEPARTMENT  = "department"
ENTITY_DESIGNATION = "designation"


# ── Field formats ──
# Validated server-side. The source HRMS checked identity documents in the browser only
# (BACKEND_ANALYSIS §8: "PAN-or-Aadhaar ... not enforced server-side"), so malformed PII
# reached the database. These patterns close that gap for every write path.
import re as _re

PAN_RE     = _re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
AADHAAR_RE = _re.compile(r"^\d{12}$")
IFSC_RE    = _re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
UAN_RE     = _re.compile(r"^\d{12}$")
DATE_RE    = _re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_iso_date(value: str) -> bool:
    """True for a well-formed, real 'YYYY-MM-DD' date.

    Dates are handled as plain strings throughout HRMS (matching the ERP's holiday_date /
    joining_date convention) and are compared lexically, which is correct for ISO dates and
    immune to server-timezone drift.
    """
    if not value or not DATE_RE.match(value):
        return False
    try:
        from datetime import date
        y, m, d = (int(p) for p in value.split("-"))
        date(y, m, d)          # rejects 2026-02-30 and friends
        return True
    except (ValueError, TypeError):
        return False


# ── API models ──
class DepartmentIn(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    head_user_id: Optional[str] = None
    active: bool = True


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    head_user_id: Optional[str] = None
    active: Optional[bool] = None


class DesignationIn(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    level: Optional[int] = None          # optional grade/band, ascending seniority
    active: bool = True


class DesignationUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    level: Optional[int] = None
    active: Optional[bool] = None


class EmployeeProfileIn(BaseModel):
    """Create an employee profile for an EXISTING user.

    `user_id` is the join key to staff/learners. There is deliberately no name/email here:
    identity lives in the user collections and is never duplicated, so a rename can never
    desynchronise the two (BACKEND_ANALYSIS Risk #4).
    """
    user_id: str
    employee_code: Optional[str] = None          # auto-minted when omitted
    department_id: Optional[str] = None
    designation_id: Optional[str] = None
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    gender: Optional[Gender] = None
    date_of_birth: Optional[str] = None          # YYYY-MM-DD
    joined_on: Optional[str] = None              # YYYY-MM-DD
    resigned_on: Optional[str] = None            # YYYY-MM-DD
    base_salary: Optional[float] = None          # monthly; gated by employee.salary.*
    # Statutory
    pan: Optional[str] = None
    aadhaar: Optional[str] = None
    uan: Optional[str] = None
    pf_number: Optional[str] = None
    esi_number: Optional[str] = None
    # Bank
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    bank_ifsc: Optional[str] = None
    # Personal
    blood_group: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None


class EmployeeProfileUpdate(BaseModel):
    """Every field optional. `user_id` is intentionally absent — a profile can never be
    re-pointed at a different person; delete and recreate instead."""
    employee_code: Optional[str] = None
    department_id: Optional[str] = None
    designation_id: Optional[str] = None
    employment_status: Optional[EmploymentStatus] = None
    employment_type: Optional[EmploymentType] = None
    gender: Optional[Gender] = None
    date_of_birth: Optional[str] = None
    joined_on: Optional[str] = None
    resigned_on: Optional[str] = None
    base_salary: Optional[float] = None
    pan: Optional[str] = None
    aadhaar: Optional[str] = None
    uan: Optional[str] = None
    pf_number: Optional[str] = None
    esi_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    bank_ifsc: Optional[str] = None
    blood_group: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None


# =============================================================
# Phase 3 - Requisitions (FMS) + Job Descriptions
# =============================================================

class ReqApproval(str, Enum):
    """The 4-state approval machine. A requisition and its JD move through ONE unified
    chain -- the source's separate JD approval was removed and the JD is co-approved at the
    MD stage (BACKEND_ANALYSIS 6.7)."""
    PENDING_HR = "Pending HR Review"
    # Phase 11-R, Item 7: an OVER-SANCTION requisition is routed through the raiser's
    # reporting line before it reaches the MD. An in-sanction requisition never enters this
    # state, so the existing three-step chain is completely unchanged for it.
    PENDING_ESCALATION = "Pending Escalation"
    PENDING_MD = "Pending MD Approval"
    APPROVED   = "Approved"
    REJECTED   = "Rejected"


class ReqClosing(str, Enum):
    OPEN   = "Open"
    HIRED  = "Hired"
    CLOSED = "Closed"
    HOLD   = "Hold"
    CANCEL = "Cancel"


class JdStatus(str, Enum):
    DRAFT            = "Draft"
    PENDING_APPROVAL = "Pending Approval"
    APPROVED         = "Approved"
    REJECTED         = "Rejected"


class Urgency(str, Enum):
    HIGH   = "High"
    MEDIUM = "Medium"
    LOW    = "Low"


class WorkLocation(str, Enum):
    OFFICE  = "Office"
    FACTORY = "Factory"
    REMOTE  = "Remote"
    HYBRID  = "Hybrid"


class GenderPreference(str, Enum):
    ANY    = "Any"
    MALE   = "Male"
    FEMALE = "Female"


# -- The state machine, declared as data -----------------------------------------
# Encoding transitions as a table rather than a chain of ifs means the guard, the tests and
# the documentation all read from one source. An action absent from this table simply
# cannot happen, and adding a stage later is a data change rather than new control flow.
#   action -> (required_status, resulting_status, capability, remark_required)
REQ_TRANSITIONS = {
    "hr-approve": (ReqApproval.PENDING_HR, ReqApproval.PENDING_MD,
                   Cap.REQUISITION_REVIEW_HR, False),
    "hr-reject":  (ReqApproval.PENDING_HR, ReqApproval.REJECTED,
                   Cap.REQUISITION_REVIEW_HR, True),
    "md-approve": (ReqApproval.PENDING_MD, ReqApproval.APPROVED,
                   Cap.REQUISITION_APPROVE_MD, False),
    "md-reject":  (ReqApproval.PENDING_MD, ReqApproval.REJECTED,
                   Cap.REQUISITION_APPROVE_MD, True),
    # ── Phase 11-R, Item 7 ── the over-sanction escalation ladder.
    # `escalate-approve` results in PENDING_MD, which is the status reached once the WHOLE
    # ladder is exhausted; while rungs remain the service holds the requisition at
    # PENDING_ESCALATION and advances the level (see hrms_requisition_service).
    "escalate-approve": (ReqApproval.PENDING_ESCALATION, ReqApproval.PENDING_MD,
                         Cap.REQUISITION_ESCALATE, False),
    "escalate-reject":  (ReqApproval.PENDING_ESCALATION, ReqApproval.REJECTED,
                         Cap.REQUISITION_ESCALATE, True),
}

REQ_ACTIONS = tuple(REQ_TRANSITIONS.keys())

# Where `hr-approve` lands when the requisition is OVER-SANCTION. Declared beside the
# transition table rather than branched inside the handler, so the two cannot drift.
# In-sanction requisitions ignore this map entirely and keep today's PENDING_HR ->
# PENDING_MD edge byte for byte.
REQ_ESCALATION_ROUTING = {"hr-approve": ReqApproval.PENDING_ESCALATION}

# The escalation ladder is capped. A cyclic or absurdly deep reporting chain must not turn
# one requisition into a twenty-step approval marathon.
MAX_ESCALATION_LEVELS = 5


class EscalationStatus(str, Enum):
    PENDING  = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


def md_approval_is_mandatory() -> bool:
    """MD approval cannot be skipped, asserted from the table rather than trusted.

    The requirement "MD is compulsory" is only as strong as the transition table: it holds
    exactly while `APPROVED` is reachable from ONE row, that row starts at `PENDING_MD`, and
    it demands `REQUISITION_APPROVE_MD`. Adding a well-meaning shortcut later -- an
    `escalate-approve` that lands on APPROVED when the chain is empty, say -- would silently
    remove the MD from the loop. This function is what the test asserts, so that change
    fails loudly instead.
    """
    rows = [spec for spec in REQ_TRANSITIONS.values() if spec[1] is ReqApproval.APPROVED]
    return (len(rows) == 1
            and rows[0][0] is ReqApproval.PENDING_MD
            and rows[0][2] is Cap.REQUISITION_APPROVE_MD)

AUDIT_REQ_CREATED     = "requisition raised"
AUDIT_REQ_UPDATED     = "requisition updated"
AUDIT_REQ_DELETED     = "requisition deleted"
AUDIT_REQ_HR_APPROVED = "requisition HR-approved"
AUDIT_REQ_HR_REJECTED = "requisition rejected (HR)"
AUDIT_REQ_MD_APPROVED = "requisition approved (MD)"
AUDIT_REQ_MD_REJECTED = "requisition rejected (MD)"
AUDIT_REQ_CLOSED      = "requisition closing status changed"
AUDIT_JD_UPDATED      = "job description updated"

# action -> audit label, so the trail cannot drift from the transition table.
AUDIT_REQ_ESCALATED   = "requisition escalated (over-sanction)"
AUDIT_REQ_ESC_APPROVED = "requisition approved (escalation)"
AUDIT_REQ_ESC_REJECTED = "requisition rejected (escalation)"

REQ_AUDIT_ACTIONS = {
    "hr-approve": AUDIT_REQ_HR_APPROVED,
    "hr-reject":  AUDIT_REQ_HR_REJECTED,
    "md-approve": AUDIT_REQ_MD_APPROVED,
    "md-reject":  AUDIT_REQ_MD_REJECTED,
    "escalate-approve": AUDIT_REQ_ESC_APPROVED,
    "escalate-reject":  AUDIT_REQ_ESC_REJECTED,
}

ENTITY_JD = "job_description"


# =============================================================
# Phase 11-R, Item 6 - dual budget capture
# =============================================================
# How far the two figures may differ and still count as agreeing. Zero by default: a
# requisition's budget is an exact number somebody signed off, not an estimate. It is a
# named constant rather than a literal `==` so a client who works in thousands can widen it
# in one reviewable place.
BUDGET_TOLERANCE = 0.0


class BudgetStatus(str, Enum):
    NOT_SET  = "Not Set"    # neither figure captured
    PENDING  = "Pending"    # one side has answered, the other has not
    MATCHED  = "Matched"
    MISMATCH = "Mismatch"


def budget_status(req: dict) -> str:
    """The budget state of a requisition, DERIVED on every read and never stored.

    A stored flag would go stale the moment somebody corrects a figure, and the correction
    is exactly the case that matters. Tolerates documents written before this phase: both
    fields absent reads as `Not Set`, which is the truth about them.
    """
    req = req or {}
    sanctioned = req.get("budget_sanctioned_amount")
    hod = req.get("budget_hod_amount")
    if sanctioned is None and hod is None:
        return BudgetStatus.NOT_SET.value
    if sanctioned is None or hod is None:
        return BudgetStatus.PENDING.value
    try:
        delta = abs(float(sanctioned) - float(hod))
    except (TypeError, ValueError):
        # Unreadable figures are not silently "Matched" -- they are a disagreement we
        # cannot resolve, which is what Mismatch means.
        return BudgetStatus.MISMATCH.value
    return (BudgetStatus.MATCHED.value if delta <= BUDGET_TOLERANCE
            else BudgetStatus.MISMATCH.value)


def budget_delta(req: dict):
    """Signed difference (HOD-approved minus management-sanctioned), or None."""
    try:
        return float(req.get("budget_hod_amount")) - float(req.get("budget_sanctioned_amount"))
    except (TypeError, ValueError):
        return None


# Actions that require remarks CONDITIONALLY, on top of the flat `remark_required` slot in
# REQ_TRANSITIONS. Declared here so the whole "when must an approver explain themselves"
# rule is readable in one place rather than scattered through the handler.
#
# The rule (confirmed with the business, see PHASE_11R_REPORT §Decisions): a budget mismatch
# WARNS and notifies, it does not block. But an MD who approves a requisition whose two
# budget figures disagree must say why -- an unexplained approval over a known disagreement
# is exactly the record an audit later needs.
REQ_CONDITIONAL_REMARKS = {
    "md-approve": lambda req: budget_status(req) == BudgetStatus.MISMATCH.value,
}

REQ_CONDITIONAL_REMARK_REASONS = {
    "md-approve": ("The sanctioned and HOD-approved budgets do not match. "
                   "Record a remark explaining the approval."),
}


class RequisitionType(str, Enum):
    NEW_POSITION = "New Position"
    REPLACEMENT  = "Replacement"


# -- API models --
class JobDescriptionIn(BaseModel):
    """The JD authored WITH its requisition.

    Mandatory content is `responsibilities` OR at least one attachment -- enforced in the
    service, because it is a cross-field rule Pydantic cannot express cleanly.
    """
    title: Optional[str] = None          # defaults to the designation name
    responsibilities: Optional[str] = None
    skills: Optional[str] = None
    qualifications: Optional[str] = None
    experience: Optional[str] = None
    ctc: Optional[str] = None
    location: Optional[str] = None
    benefits: Optional[str] = None
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    attachments: List[dict] = Field(default_factory=list)   # [{name, url}]


class JobDescriptionUpdate(BaseModel):
    title: Optional[str] = None
    responsibilities: Optional[str] = None
    skills: Optional[str] = None
    qualifications: Optional[str] = None
    experience: Optional[str] = None
    ctc: Optional[str] = None
    location: Optional[str] = None
    benefits: Optional[str] = None
    employment_type: Optional[EmploymentType] = None
    attachments: Optional[List[dict]] = None


class RequisitionIn(BaseModel):
    """Raise a hiring requisition together with its job description.

    `department_id` and `designation_id` are REFERENCES to the Phase 2 masters, not free
    text. That is the point of building those masters: the source had a hard-coded
    department dropdown that disagreed with a second hard-coded dropdown on the same screen,
    and free-text designations (FRONTEND_ANALYSIS 6.2, 15).
    """
    department_id: str
    designation_id: str
    vacancy: int = 1
    experience_required: str
    qualification: str
    essential_skills: str
    required_date: str                    # YYYY-MM-DD
    assignee_id: str                      # who will run the recruitment
    offering_ctc: Optional[float] = None
    urgency_level: Urgency = Urgency.MEDIUM
    work_location: WorkLocation = WorkLocation.OFFICE
    gender_preferred: GenderPreference = GenderPreference.ANY
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    notes: Optional[str] = None
    jd: JobDescriptionIn

    # ── Phase 11-R, Item 4 ── which client this vacancy is being filled FOR.
    # Optional: an in-house requisition has no client, and every requisition raised before
    # this phase has none either.
    client_id: Optional[str] = None

    # ── Phase 11-R, Item 6 ── dual budget capture. All optional; omitting both preserves
    # the pre-phase behaviour exactly (budget_status reads "Not Set").
    budget_sanctioned_amount: Optional[float] = None   # sanctioned by management
    budget_sanctioned_by: Optional[str] = None         # user_id
    budget_sanctioned_ref: Optional[str] = None        # approval reference / note
    budget_sanctioned_on: Optional[str] = None         # YYYY-MM-DD
    budget_hod_amount: Optional[float] = None          # approved by the HOD
    budget_hod_by: Optional[str] = None
    budget_hod_on: Optional[str] = None
    budget_remarks: Optional[str] = None

    # ── Phase 11-R, Item 7 ── replacement vs a genuinely new position.
    requisition_type: RequisitionType = RequisitionType.NEW_POSITION
    replacement_for_user_id: Optional[str] = None      # required when Replacement
    replacement_for_name: Optional[str] = None         # denormalised label
    replacement_reason: Optional[str] = None           # required when Replacement
    last_working_day: Optional[str] = None             # YYYY-MM-DD


class RequisitionUpdate(BaseModel):
    """Edit requisition details. Approval fields are deliberately absent -- they change only
    through the /approve endpoint, so the state machine stays the single writer."""
    department_id: Optional[str] = None
    designation_id: Optional[str] = None
    vacancy: Optional[int] = None
    experience_required: Optional[str] = None
    qualification: Optional[str] = None
    essential_skills: Optional[str] = None
    required_date: Optional[str] = None
    assignee_id: Optional[str] = None
    offering_ctc: Optional[float] = None
    urgency_level: Optional[Urgency] = None
    work_location: Optional[WorkLocation] = None
    gender_preferred: Optional[GenderPreference] = None
    employment_type: Optional[EmploymentType] = None
    notes: Optional[str] = None

    # ── Phase 11-R ── same additions as RequisitionIn, all optional.
    client_id: Optional[str] = None
    budget_sanctioned_amount: Optional[float] = None
    budget_sanctioned_by: Optional[str] = None
    budget_sanctioned_ref: Optional[str] = None
    budget_sanctioned_on: Optional[str] = None
    budget_hod_amount: Optional[float] = None
    budget_hod_by: Optional[str] = None
    budget_hod_on: Optional[str] = None
    budget_remarks: Optional[str] = None
    requisition_type: Optional[RequisitionType] = None
    replacement_for_user_id: Optional[str] = None
    replacement_for_name: Optional[str] = None
    replacement_reason: Optional[str] = None
    last_working_day: Optional[str] = None


class RequisitionAction(BaseModel):
    action: str                            # one of REQ_ACTIONS
    remarks: Optional[str] = None
    salary_change: Optional[float] = None  # MD may revise the offered CTC on approval


class RequisitionClose(BaseModel):
    status: ReqClosing


# =============================================================
# Phase 4 - Job Postings + Public Application Intake
# =============================================================

class Platform(str, Enum):
    LINKEDIN    = "LinkedIn"
    NAUKRI      = "Naukri"
    INDEED      = "Indeed"
    FOUNDIT     = "Foundit"
    APNA        = "Apna"
    CAREER_PAGE = "Career Page"
    REFERRAL    = "Referral"
    MANUAL      = "Manual"


class ApplyLinkMode(str, Enum):
    """Where a posting sends applicants.

    AUTO     -> the built-in public form at /apply/<posting_code>; the application lands in
                the pipeline automatically.
    EXTERNAL -> the poster's own destination (a job board listing, a Google Form, ...).
                Applications made there NEVER enter this pipeline -- nothing writes them
                back. The UI must say so plainly rather than implying tracking it cannot do.
    """
    AUTO     = "auto"
    EXTERNAL = "external"


class LiveStatus(str, Enum):
    LIVE    = "Live"
    PAUSED  = "Paused"
    EXPIRED = "Expired"
    CLOSED  = "Closed"


# The master candidate lifecycle. Phase 4 only ever writes APPLIED; the rest are driven by
# Phases 5-9. Declared in full here so there is ONE list, not a growing set of string
# literals scattered across services (the source kept a modern status column AND legacy
# numbered step columns in parallel -- BACKEND_ANALYSIS Risk #7).
class AppStatus(str, Enum):
    APPLIED              = "Applied"
    UNDER_REVIEW         = "Under Review"
    SHORTLISTED          = "Shortlisted"
    # ── Phase 11-R, Item 4 ── the CV goes out to the hiring client for their verdict.
    # This is NOT ScreenAction.FORWARD, which assigns an INTERNAL owner and moves nobody.
    SHARED_WITH_CLIENT   = "Shared with Client"
    CLIENT_SHORTLISTED   = "Client Shortlisted"
    CLIENT_REJECTED      = "Client Rejected"
    ON_HOLD              = "On Hold"
    DUPLICATE            = "Duplicate"
    REJECTED             = "Rejected"
    INTERVIEW_SCHEDULED  = "Interview Scheduled"
    ASSESSMENT_PENDING   = "Assessment Pending"
    ASSESSMENT_COMPLETED = "Assessment Completed"
    ASSESSMENT_PASSED    = "Assessment Passed"
    ASSESSMENT_FAILED    = "Assessment Failed"
    TECHNICAL_ROUND      = "Technical Round"
    MD_ROUND             = "MD Round"
    SELECTED             = "Selected"
    OFFER_GENERATED      = "Offer Generated"
    OFFER_ACCEPTED       = "Offer Accepted"
    OFFER_DECLINED       = "Offer Declined"
    # ── Phase 11-R, Item 3 ── the appointment letter confirming joining terms has gone out.
    # OPTIONAL: the direct Offer Accepted -> Pre-Onboarding edge is kept, so a company that
    # does not issue appointment letters is never blocked by this stage existing.
    APPOINTMENT_LETTER_SENT = "Appointment Letter Sent"
    PRE_ONBOARDING       = "Pre-Onboarding"
    JOINED               = "Joined"
    EMPLOYEE_CREATED     = "Employee Created"


# -- Upload limits (public surface) ----------------------------------------------
MAX_UPLOAD_BYTES = 15 * 1024 * 1024          # 15 MB, matching the source's ceiling
MAX_CERTIFICATES = 10

ALLOWED_UPLOAD_MIME = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg", "image/png", "image/webp",
}

# Posting codes are public identifiers: two letters, a dash, six upper-alnum characters.
POSTING_CODE_RE = _re.compile(r"^[A-Z]{2}-[A-Z0-9]{6}$")
EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Digits, spaces and the usual separators; 7-20 characters of actual digits.
PHONE_RE = _re.compile(r"^[0-9+\-() ]{7,25}$")

AUDIT_POSTING_CREATED = "job posting published"
AUDIT_POSTING_UPDATED = "job posting updated"
AUDIT_POSTING_DELETED = "job posting deleted"
AUDIT_APPLICATION     = "application received"

ENTITY_POSTING   = "job_posting"
ENTITY_CANDIDATE_APPLICATION = "candidate"


# -- API models --
class PlatformLink(BaseModel):
    """Per-platform link configuration.

    One posting ROW per platform, each with its own code and its own destination -- so
    publishing one JD to LinkedIn + Naukri + Career Page yields three codes and three
    independently trackable application counts.
    """
    platform: Platform
    apply_link_mode: ApplyLinkMode = ApplyLinkMode.AUTO
    external_url: Optional[str] = None
    code: Optional[str] = None       # client-previewed code; honoured only if valid + unique


class PostingIn(BaseModel):
    jd_no: str
    platform_links: List[PlatformLink]
    expiry_date: Optional[str] = None          # YYYY-MM-DD
    notes: Optional[str] = None
    requires_assessment: bool = False


class PostingUpdate(BaseModel):
    live_status: Optional[LiveStatus] = None
    expiry_date: Optional[str] = None
    notes: Optional[str] = None
    apply_link_mode: Optional[ApplyLinkMode] = None
    external_url: Optional[str] = None
    requires_assessment: Optional[bool] = None


class UploadIn(BaseModel):
    """A file arriving as base64 in a JSON body -- the public forms cannot use multipart
    without a token, so this is the ingest shape for every candidate-facing upload."""
    name: str
    mime_type: str
    data: str                                   # base64, optionally a data: URL


# =============================================================
# Phase 11-R, Item 5 - referral capture
# =============================================================
class ReferralSource(str, Enum):
    EMPLOYEE          = "Employee"
    EX_EMPLOYEE       = "Ex-Employee"
    CONSULTANT_AGENCY = "Consultant / Agency"
    JOB_PORTAL        = "Job Portal"
    SOCIAL_MEDIA      = "Social Media"
    WALK_IN           = "Walk-in"
    CLIENT            = "Client"
    OTHER             = "Other"


# The `source` value a referred candidate is filed under, so referrals land in the existing
# Phase 10 `source` breakdown rather than needing a parallel one.
REFERRAL_SOURCE_LABEL = "Referral"

# Employee codes are EMP-<year>-<seq> (see ID_FORMATS). Validated as a shape BEFORE the
# lookup, exactly as posting and access codes are, so a crafted value never reaches Mongo.
EMPLOYEE_CODE_RE = _re.compile(r"^EMP-\d{4}-\d{3,}$")

# Deliberately vague, and identical for "no such code" and "belongs to another company".
# The public form must not become an employee-directory oracle -- the same discipline
# INVALID_LINK applies to posting codes.
INVALID_EMPLOYEE_CODE = "We could not verify that employee code."


class ReferralIn(BaseModel):
    """The referral block, shared by the public form and the manual-add path.

    Both intake paths capture the SAME thing: a referral entered by HR on a walk-in CV is
    worth exactly as much as one typed by the applicant, and reporting must not be able to
    tell them apart.
    """
    is_referral: bool = False
    referred_by: Optional[str] = None                # the referrer's name
    referral_source: Optional[ReferralSource] = None
    referrer_employee_code: Optional[str] = None     # e.g. EMP-2026-014
    referral_relation: Optional[str] = None


class PublicApplicationIn(BaseModel):
    """A candidate's application. Deliberately minimal and entirely untrusted."""
    candidate_name: str
    can_email: str
    can_contact: str
    declaration: bool = False
    current_location: Optional[str] = None
    total_experience: Optional[str] = None
    qualification: Optional[str] = None
    current_company: Optional[str] = None
    current_ctc: Optional[str] = None
    expected_ctc: Optional[str] = None
    notice_period: Optional[str] = None
    linkedin: Optional[str] = None
    portfolio: Optional[str] = None
    cover_note: Optional[str] = None
    resume: Optional[UploadIn] = None
    photo: Optional[UploadIn] = None
    certificates: List[UploadIn] = Field(default_factory=list)
    # ── Phase 11-R, Item 5 ── "Were you referred?" Collapsed by default in the UI, and
    # entirely optional here: an application with no referral is unchanged by this phase.
    is_referral: bool = False
    referred_by: Optional[str] = None
    referral_source: Optional[ReferralSource] = None
    referrer_employee_code: Optional[str] = None
    referral_relation: Optional[str] = None


# =============================================================
# Phase 5 - Candidate pipeline, screening, journey
# =============================================================

# Stages a candidate can never leave. Reaching one of these ends the pipeline.
TERMINAL_STATUSES = {
    AppStatus.EMPLOYEE_CREATED, AppStatus.OFFER_DECLINED, AppStatus.DUPLICATE,
}

# Available from ANY non-terminal stage. A recruiter must always be able to stop a pipeline
# or park it, whatever stage it has reached -- encoding those as per-stage edges would be
# noise, and forgetting one would trap a candidate.
ALWAYS_AVAILABLE = {AppStatus.REJECTED, AppStatus.ON_HOLD, AppStatus.DUPLICATE}

# The forward lifecycle. Only these edges advance a candidate.
#
# The source enforced NOTHING here -- any status could be set to any other, so a candidate
# could jump Applied -> Joined and skip every gate (assessment, interview, offer,
# onboarding), leaving downstream phases to reason about states that cannot legitimately
# exist. Declaring the graph makes an illegal move a 409 instead of silent corruption.
FORWARD_TRANSITIONS = {
    AppStatus.APPLIED:              {AppStatus.UNDER_REVIEW, AppStatus.SHORTLISTED},
    AppStatus.UNDER_REVIEW:         {AppStatus.SHORTLISTED},
    # Shortlisting routes by the role's assessment requirement -- the screening service
    # picks which of these two edges to take (see hrms_screening_service).
    # SHARED_WITH_CLIENT is a THIRD option, taken only when the CV is sent to the hiring
    # client for their verdict (Phase 11-R, Item 4).
    AppStatus.SHORTLISTED:          {AppStatus.ASSESSMENT_PENDING, AppStatus.INTERVIEW_SCHEDULED,
                                     AppStatus.SHARED_WITH_CLIENT},
    # The client's verdict, or -- if they never respond -- the pipeline carries on without
    # one. Sharing a CV must not be able to strand a candidate on an unanswered email.
    AppStatus.SHARED_WITH_CLIENT:   {AppStatus.CLIENT_SHORTLISTED, AppStatus.CLIENT_REJECTED,
                                     AppStatus.ASSESSMENT_PENDING, AppStatus.INTERVIEW_SCHEDULED},
    AppStatus.CLIENT_SHORTLISTED:   {AppStatus.ASSESSMENT_PENDING, AppStatus.INTERVIEW_SCHEDULED},
    # Revivable, exactly like REJECTED: a client changing their mind is a real event.
    AppStatus.CLIENT_REJECTED:      {AppStatus.UNDER_REVIEW},
    AppStatus.ASSESSMENT_PENDING:   {AppStatus.ASSESSMENT_COMPLETED},
    AppStatus.ASSESSMENT_COMPLETED: {AppStatus.ASSESSMENT_PASSED, AppStatus.ASSESSMENT_FAILED},
    AppStatus.ASSESSMENT_PASSED:    {AppStatus.INTERVIEW_SCHEDULED},
    # A failed assessment is not automatically a rejection -- HR may still park or reject it,
    # both of which come from ALWAYS_AVAILABLE.
    AppStatus.ASSESSMENT_FAILED:    set(),
    AppStatus.INTERVIEW_SCHEDULED:  {AppStatus.TECHNICAL_ROUND, AppStatus.MD_ROUND,
                                     AppStatus.SELECTED},
    AppStatus.TECHNICAL_ROUND:      {AppStatus.MD_ROUND, AppStatus.SELECTED},
    AppStatus.MD_ROUND:             {AppStatus.SELECTED},
    AppStatus.SELECTED:             {AppStatus.OFFER_GENERATED},
    # SELECTED is the REVOKE walk-back: withdrawing an offer un-does the fact that one was
    # generated, returning the candidate to the pool so revised terms can be issued. Without
    # this edge a revoked candidate is stranded -- no live offer, yet unable to receive one.
    AppStatus.OFFER_GENERATED:      {AppStatus.OFFER_ACCEPTED, AppStatus.OFFER_DECLINED,
                                     AppStatus.SELECTED},
    # Both edges are kept deliberately. A company that issues appointment letters routes
    # through APPOINTMENT_LETTER_SENT; one that does not goes straight to onboarding as it
    # always has. Removing the direct edge would force a workflow on every existing client.
    AppStatus.OFFER_ACCEPTED:       {AppStatus.APPOINTMENT_LETTER_SENT,
                                     AppStatus.PRE_ONBOARDING},
    AppStatus.APPOINTMENT_LETTER_SENT: {AppStatus.PRE_ONBOARDING},
    AppStatus.PRE_ONBOARDING:       {AppStatus.JOINED},
    AppStatus.JOINED:               {AppStatus.EMPLOYEE_CREATED},
    # Parked and rejected candidates can be revived -- a hold that cannot be lifted is a
    # dead end, and rejections are sometimes reversed.
    AppStatus.ON_HOLD:              {AppStatus.UNDER_REVIEW, AppStatus.SHORTLISTED},
    AppStatus.REJECTED:             {AppStatus.UNDER_REVIEW},
}


def allowed_next_statuses(current) -> set:
    """Every stage a candidate may legally move to from `current`."""
    current = AppStatus(current) if not isinstance(current, AppStatus) else current
    if current in TERMINAL_STATUSES:
        return set()
    return set(FORWARD_TRANSITIONS.get(current, set())) | (ALWAYS_AVAILABLE - {current})


def can_transition(current, target) -> bool:
    try:
        return AppStatus(target) in allowed_next_statuses(current)
    except ValueError:
        return False


# -- Pipeline grouping (the Kanban columns) --------------------------------------
# One declaration shared by the board, the stat tiles and the tests, so a stage can never
# be visible in one place and missing from another.
PIPELINE_COLUMNS = [
    ("applied",     "Applied",     [AppStatus.APPLIED, AppStatus.UNDER_REVIEW]),
    ("shortlisted", "Shortlisted", [AppStatus.SHORTLISTED, AppStatus.SHARED_WITH_CLIENT,
                                    AppStatus.CLIENT_SHORTLISTED]),
    ("assessment",  "Assessment",  [AppStatus.ASSESSMENT_PENDING, AppStatus.ASSESSMENT_COMPLETED,
                                    AppStatus.ASSESSMENT_PASSED, AppStatus.ASSESSMENT_FAILED]),
    ("interview",   "Interview",   [AppStatus.INTERVIEW_SCHEDULED, AppStatus.TECHNICAL_ROUND,
                                    AppStatus.MD_ROUND]),
    ("selected",    "Selected",    [AppStatus.SELECTED, AppStatus.OFFER_GENERATED,
                                    AppStatus.OFFER_ACCEPTED,
                                    AppStatus.APPOINTMENT_LETTER_SENT]),
    ("onboarding",  "Onboarding",  [AppStatus.PRE_ONBOARDING, AppStatus.JOINED,
                                    AppStatus.EMPLOYEE_CREATED]),
    ("hold",        "On Hold",     [AppStatus.ON_HOLD]),
    ("rejected",    "Rejected",    [AppStatus.REJECTED, AppStatus.DUPLICATE,
                                    AppStatus.OFFER_DECLINED, AppStatus.CLIENT_REJECTED]),
]


class ScreenAction(str, Enum):
    SHORTLIST = "shortlist"
    REVIEW    = "review"
    HOLD      = "hold"
    DUPLICATE = "duplicate"
    REJECT    = "reject"
    FORWARD   = "forward"
    # Phase 11-R, Item 4. Distinct from FORWARD on purpose: FORWARD assigns an internal
    # owner and moves nobody, this sends the CV OUT to the hiring client for their verdict.
    SHARE_WITH_CLIENT = "share_with_client"


# action -> (target status or None, remark_required, recipient_required)
# `shortlist` has no fixed target: it resolves to Assessment Pending or straight to
# interview-ready depending on the role's assessment flag.
SCREEN_ACTIONS = {
    ScreenAction.SHORTLIST: (None, False, False),
    ScreenAction.REVIEW:    (AppStatus.UNDER_REVIEW, False, False),
    ScreenAction.HOLD:      (AppStatus.ON_HOLD, False, False),
    ScreenAction.DUPLICATE: (AppStatus.DUPLICATE, False, False),
    ScreenAction.REJECT:    (AppStatus.REJECTED, True, False),
    ScreenAction.FORWARD:   (None, False, True),
    # Remark optional (a covering note to the client), recipient optional (the client
    # contact is free text on the share record, not an ERP user).
    ScreenAction.SHARE_WITH_CLIENT: (AppStatus.SHARED_WITH_CLIENT, False, False),
}

MAX_BULK_SCREEN = 200

AUDIT_CANDIDATE_ADDED   = "candidate added"
AUDIT_CANDIDATE_UPDATED = "candidate updated"
AUDIT_CANDIDATE_DELETED = "candidate deleted"
AUDIT_STAGE_CHANGED     = "stage changed"
AUDIT_SCREENED          = "candidate screened"
AUDIT_ASSIGNED          = "candidate assigned"

# Colour keys the journey timeline renders by. Kept server-side so every consumer of the
# timeline agrees on what an event means.
JOURNEY_KINDS = {
    AUDIT_APPLICATION:       "applied",
    AUDIT_CANDIDATE_ADDED:   "applied",
    AUDIT_STAGE_CHANGED:     "info",
    AUDIT_SCREENED:          "info",
    AUDIT_ASSIGNED:          "info",
    AUDIT_CANDIDATE_UPDATED: "info",
}

# Statuses that colour a journey event regardless of which action produced it.
JOURNEY_STATUS_KINDS = {
    # ── Phase 11-R ──
    AppStatus.SHARED_WITH_CLIENT: "info",
    AppStatus.CLIENT_SHORTLISTED: "success",
    AppStatus.CLIENT_REJECTED: "reject",
    AppStatus.APPOINTMENT_LETTER_SENT: "offer",
    AppStatus.SHORTLISTED: "success", AppStatus.ASSESSMENT_PASSED: "success",
    AppStatus.SELECTED: "success", AppStatus.OFFER_ACCEPTED: "success",
    AppStatus.JOINED: "success", AppStatus.EMPLOYEE_CREATED: "success",
    AppStatus.REJECTED: "reject", AppStatus.DUPLICATE: "reject",
    AppStatus.ASSESSMENT_FAILED: "reject", AppStatus.OFFER_DECLINED: "reject",
    AppStatus.ON_HOLD: "warning",
    AppStatus.INTERVIEW_SCHEDULED: "interview", AppStatus.TECHNICAL_ROUND: "interview",
    AppStatus.MD_ROUND: "interview",
    AppStatus.OFFER_GENERATED: "offer",
    AppStatus.PRE_ONBOARDING: "onboarding",
    AppStatus.ASSESSMENT_PENDING: "assessment", AppStatus.ASSESSMENT_COMPLETED: "assessment",
}

# The 7-step rail shown above the timeline: (label, statuses that mean it is reached).
JOURNEY_RAIL = [
    ("Applied",     {AppStatus.APPLIED, AppStatus.UNDER_REVIEW}),
    # Client sharing and the client's shortlist verdict belong to the shortlisting step --
    # they are a decision ABOUT a shortlisted CV, not a new stage of the candidate's journey.
    ("Shortlisted", {AppStatus.SHORTLISTED, AppStatus.SHARED_WITH_CLIENT,
                     AppStatus.CLIENT_SHORTLISTED}),
    ("Assessment",  {AppStatus.ASSESSMENT_PENDING, AppStatus.ASSESSMENT_COMPLETED,
                     AppStatus.ASSESSMENT_PASSED, AppStatus.ASSESSMENT_FAILED}),
    ("Interview",   {AppStatus.INTERVIEW_SCHEDULED, AppStatus.TECHNICAL_ROUND,
                     AppStatus.MD_ROUND}),
    ("Selected",    {AppStatus.SELECTED}),
    # The rail stays 7 steps. The appointment letter joins the Offer step rather than
    # becoming an 8th: it is a second paper in the same "terms agreed" phase, and an 8th
    # step would re-flow a rail every existing screen renders. (Stated per Item 3 §2.)
    ("Offer",       {AppStatus.OFFER_GENERATED, AppStatus.OFFER_ACCEPTED,
                     AppStatus.APPOINTMENT_LETTER_SENT}),
    ("Hired",       {AppStatus.PRE_ONBOARDING, AppStatus.JOINED, AppStatus.EMPLOYEE_CREATED}),
]


# -- API models --
class CandidateIn(BaseModel):
    """Manually add a candidate (walk-in, referral, agency CV)."""
    candidate_name: str
    can_email: Optional[str] = None
    can_contact: Optional[str] = None
    request_no: Optional[str] = None
    source: str = "Manual"
    current_location: Optional[str] = None
    total_experience: Optional[str] = None
    qualification: Optional[str] = None
    current_company: Optional[str] = None
    current_ctc: Optional[str] = None
    expected_ctc: Optional[str] = None
    notice_period: Optional[str] = None
    linkedin: Optional[str] = None
    cover_note: Optional[str] = None
    resume: Optional[UploadIn] = None
    # ── Phase 11-R, Item 5 ── the manual-add path captures the same referral detail as the
    # public form. A referral typed in by HR must be as reportable as one self-declared.
    is_referral: bool = False
    referred_by: Optional[str] = None
    referral_source: Optional[ReferralSource] = None
    referrer_employee_code: Optional[str] = None
    referral_relation: Optional[str] = None


class CandidateUpdate(BaseModel):
    """Edit candidate details, or move their stage.

    `application_status` is accepted here but validated against FORWARD_TRANSITIONS -- it is
    not a free assignment.
    """
    candidate_name: Optional[str] = None
    can_email: Optional[str] = None
    can_contact: Optional[str] = None
    application_status: Optional[AppStatus] = None
    assigned_recruiter_id: Optional[str] = None
    current_location: Optional[str] = None
    total_experience: Optional[str] = None
    qualification: Optional[str] = None
    current_company: Optional[str] = None
    current_ctc: Optional[str] = None
    expected_ctc: Optional[str] = None
    notice_period: Optional[str] = None
    linkedin: Optional[str] = None
    cover_note: Optional[str] = None
    remarks: Optional[str] = None


class ScreenIn(BaseModel):
    uks: List[str]
    action: ScreenAction
    remarks: Optional[str] = None
    forward_to_id: Optional[str] = None
    # Phase 11-R, Item 4: who at the client the CV went to. Free text, not a user reference
    # — the client contact is a person at another organisation, not an ERP account.
    client_contact: Optional[str] = None


# =============================================================
# Phase 6 - Assessments + dual review
# =============================================================

class AssessmentStatus(str, Enum):
    """Assigned -> In Progress -> Submitted -> Reviewed.

    OPENED exists so HR can tell "the candidate has not looked at it" from "they opened it
    and went quiet" -- two situations that need different follow-up.
    """
    SENT      = "Sent"        # assigned, not yet opened
    OPENED    = "Opened"      # candidate has viewed it
    COMPLETED = "Completed"   # submitted, awaiting review
    REVIEWED  = "Reviewed"    # both reviewers have decided


class Decision(str, Enum):
    PASS = "Pass"
    FAIL = "Fail"


class Recommendation(str, Enum):
    RECOMMENDED     = "Recommended"
    BORDERLINE      = "Borderline"
    NOT_RECOMMENDED = "Not Recommended"


# Auto-recommendation thresholds, as a share of max_score. Advisory only -- it never decides
# the outcome, it just saves a reviewer doing the arithmetic. Both humans still choose.
RECOMMEND_THRESHOLD  = 0.70
BORDERLINE_THRESHOLD = 0.50


def recommendation_for(score, max_score) -> Optional[str]:
    """Derive the advisory recommendation from a score, or None when unscored."""
    try:
        score = float(score)
        max_score = float(max_score)
    except (TypeError, ValueError):
        return None
    if max_score <= 0:
        return None
    ratio = score / max_score
    if ratio >= RECOMMEND_THRESHOLD:
        return Recommendation.RECOMMENDED.value
    if ratio >= BORDERLINE_THRESHOLD:
        return Recommendation.BORDERLINE.value
    return Recommendation.NOT_RECOMMENDED.value


# Reviewer slots. A submission needs BOTH filled before it resolves -- unless the
# requisition has no identifiable hiring manager, in which case HR decides alone (see
# hrms_assessment_service). Two slots rather than one because "HR liked them and the hiring
# manager did not" is exactly the disagreement worth surfacing before an interview is booked.
SLOT_HR      = "hr"
SLOT_MANAGER = "manager"

MAX_ASSESSMENT_ATTACHMENTS = 10

AUDIT_ASSESSMENT_SENT      = "assessment sent"
AUDIT_ASSESSMENT_OPENED    = "assessment opened"
AUDIT_ASSESSMENT_SUBMITTED = "assessment submitted"
AUDIT_ASSESSMENT_REVIEWED  = "assessment reviewed"
AUDIT_ASSESSMENT_RESOLVED  = "assessment outcome"

ENTITY_ASSESSMENT = "assessment"

# Stages an assessment may be sent from. A candidate must be at the assessment stage --
# sending one to somebody already in interviews is a mistake, not a workflow.
ASSESSABLE_STATUSES = {
    AppStatus.SHORTLISTED, AppStatus.ASSESSMENT_PENDING,
    AppStatus.ASSESSMENT_COMPLETED, AppStatus.ASSESSMENT_FAILED,
}


# -- API models --
class AssessmentIn(BaseModel):
    uk: str
    title: str
    instructions: Optional[str] = None
    link: Optional[str] = None            # external test URL, if any
    max_score: float = 100
    due_date: Optional[str] = None        # YYYY-MM-DD


class AssessmentReviewIn(BaseModel):
    decision: Decision
    score: Optional[float] = None
    remarks: Optional[str] = None


class PublicAssessmentIn(BaseModel):
    """A candidate's assessment submission. Entirely untrusted, like every public input."""
    response: Optional[str] = None
    attachments: List[UploadIn] = Field(default_factory=list)


# =============================================================
# Phase 7 - Interviews + scorecard evaluation
# =============================================================

class InterviewRound(str, Enum):
    HR        = "HR Round"
    TECHNICAL = "Technical"
    MANAGER   = "Manager Round"
    MD        = "MD Round"


class InterviewMode(str, Enum):
    VIRTUAL = "Virtual"
    OFFLINE = "Offline"


class InterviewStatus(str, Enum):
    SCHEDULED = "Scheduled"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    NO_SHOW   = "No Show"


class Outcome(str, Enum):
    PASS = "Pass"
    FAIL = "Fail"
    HOLD = "Hold"


# The six competencies scored 0-5 on every scorecard. Declared once so the form, the
# average, the API and the tests cannot drift apart.
EVAL_COMPETENCIES = [
    ("technical",       "Technical Knowledge"),
    ("communication",   "Communication"),
    ("problem_solving", "Problem Solving"),
    ("behavior",        "Behaviour"),
    ("confidence",      "Confidence"),
    ("team_fit",        "Team Fit"),
]
COMPETENCY_KEYS = [k for k, _ in EVAL_COMPETENCIES]
MIN_SCORE, MAX_SCORE = 0, 5

# Where a candidate goes when a round is passed. Ported from BACKEND_ANALYSIS 6.3.
#
# Every edge below is already legal in the Phase 5 lifecycle graph, so this map decides
# INTENT and FORWARD_TRANSITIONS still decides LEGALITY -- two independent checks rather
# than one table trusted blindly.
PASS_NEXT = {
    InterviewRound.HR:        AppStatus.TECHNICAL_ROUND,
    InterviewRound.TECHNICAL: AppStatus.MD_ROUND,
    InterviewRound.MANAGER:   AppStatus.MD_ROUND,
    InterviewRound.MD:        AppStatus.SELECTED,
}

# Fail and Hold are round-independent.
OUTCOME_STATUS = {
    Outcome.FAIL: AppStatus.REJECTED,
    Outcome.HOLD: AppStatus.ON_HOLD,
}

# Scheduling is blocked while an assessment-required candidate has not cleared it. These are
# the stages that mean "not cleared". A candidate whose role needs no assessment is never
# measured against this list.
PRE_ASSESSMENT_STATUSES = {
    AppStatus.APPLIED, AppStatus.UNDER_REVIEW, AppStatus.SHORTLISTED,
    AppStatus.ASSESSMENT_PENDING, AppStatus.ASSESSMENT_COMPLETED,
    AppStatus.ASSESSMENT_FAILED, AppStatus.ON_HOLD,
}

MIN_DURATION_MIN = 15
DURATION_STEP_MIN = 15
DEFAULT_DURATION_MIN = 45

AUDIT_INTERVIEW_SCHEDULED   = "interview scheduled"
AUDIT_INTERVIEW_RESCHEDULED = "interview rescheduled"
AUDIT_INTERVIEW_UPDATED     = "interview updated"
AUDIT_INTERVIEW_CANCELLED   = "interview cancelled"
AUDIT_INTERVIEW_EVALUATED   = "interview evaluated"

ENTITY_INTERVIEW = "interview"


# -- API models --
class InterviewIn(BaseModel):
    uk: str
    round: InterviewRound = InterviewRound.HR
    mode: InterviewMode = InterviewMode.VIRTUAL
    scheduled_at: str                       # ISO-8601 datetime
    duration_min: int = DEFAULT_DURATION_MIN
    interviewer_id: str
    meeting_link: Optional[str] = None      # required when mode is Virtual
    location: Optional[str] = None          # required when mode is Offline
    notes: Optional[str] = None


class InterviewUpdate(BaseModel):
    """Reschedule or change the status of an interview.

    Round, candidate and interviewer are deliberately absent: changing who is being
    interviewed, for what, would make the scorecard meaningless. Cancel and re-schedule
    instead.
    """
    scheduled_at: Optional[str] = None
    duration_min: Optional[int] = None
    mode: Optional[InterviewMode] = None
    meeting_link: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[InterviewStatus] = None


class InterviewEvaluateIn(BaseModel):
    """The scorecard. Every competency 0-5, a decision, and a typed signature.

    The signature is REQUIRED here. The source left it optional despite the UI implying
    otherwise (BACKEND_ANALYSIS 8) -- an unsigned evaluation that later decides a rejection
    is exactly the record you want attributable.
    """
    technical: int = 0
    communication: int = 0
    problem_solving: int = 0
    behavior: int = 0
    confidence: int = 0
    team_fit: int = 0
    outcome: Outcome
    remarks: Optional[str] = None
    signature: str


# =============================================================
# Phase 8 - Offers + public offer page
# =============================================================

class OfferStatus(str, Enum):
    DRAFT    = "Draft"      # being written; not visible to the candidate
    SENT     = "Sent"       # link issued, awaiting a response
    ACCEPTED = "Accepted"
    DECLINED = "Declined"
    REVOKED  = "Revoked"    # withdrawn by the company after sending


# An offer in one of these states occupies the candidate: a second one cannot be raised
# while one is live. Declined and Revoked are spent, so a fresh offer may follow.
ACTIVE_OFFER_STATUSES = {OfferStatus.DRAFT, OfferStatus.SENT, OfferStatus.ACCEPTED}

# Only a Draft is editable. Once sent, the letter the candidate is reading must not change
# underneath them -- that is the whole point of versioning it instead.
EDITABLE_OFFER_STATUSES = {OfferStatus.DRAFT}

# Candidate stages that count towards filling a requisition. Reaching `vacancy` of these
# auto-closes the requisition as Hired (Module 16 / BACKEND_ANALYSIS 6.4).
FILLED_STATUSES = {
    AppStatus.OFFER_ACCEPTED, AppStatus.PRE_ONBOARDING,
    AppStatus.JOINED, AppStatus.EMPLOYEE_CREATED,
    # Phase 11-R: an issued appointment letter means the vacancy is spoken for. Omitting it
    # would make a requisition RE-OPEN the moment the letter went out, because the candidate
    # leaves Offer Accepted for this stage.
    AppStatus.APPOINTMENT_LETTER_SENT,
}

AUDIT_OFFER_CREATED  = "offer created"
AUDIT_OFFER_EDITED   = "offer edited"
AUDIT_OFFER_SENT     = "offer sent"
AUDIT_OFFER_REVOKED  = "offer revoked"
AUDIT_OFFER_DELETED  = "offer deleted"
AUDIT_OFFER_ACCEPTED = "offer accepted"
AUDIT_OFFER_DECLINED = "offer declined"
AUDIT_REQ_AUTO_CLOSED = "requisition auto-closed (Hired)"

ENTITY_OFFER = "offer"


DEFAULT_OFFER_BODY = """We are delighted to offer you the position of {designation} at {company}.

Your annual cost to company will be {ctc}, and we would like you to join us on {joining_date}.

This offer is made on the understanding that the information you have provided during the
selection process is accurate and complete, and is subject to the satisfactory completion of
any background checks and the submission of the documents we will request separately.

We were impressed by you throughout the process and are genuinely looking forward to
working together.

Please review this letter and record your response using the buttons on this page."""


def render_offer_body(template: str, *, designation: str, company: str, ctc: str,
                      joining_date: str) -> str:
    """Fill the placeholders in an offer body.

    Deliberately a plain str.format_map with a defaulting dict rather than an f-string or
    a template engine: the body is operator-editable text, and an unknown placeholder must
    render harmlessly rather than raise or execute anything.
    """
    class _Safe(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return (template or "").format_map(_Safe(
            designation=designation or "", company=company or "",
            ctc=ctc or "", joining_date=joining_date or ""))
    except (ValueError, IndexError):
        # A stray brace in operator text should not break the letter.
        return template or ""


# -- API models --
class OfferIn(BaseModel):
    uk: str
    ctc: float
    joining_date: str                       # YYYY-MM-DD
    designation: Optional[str] = None       # defaults from the requisition
    company_name: Optional[str] = None
    location: Optional[str] = None
    content: Optional[str] = None           # defaults to DEFAULT_OFFER_BODY
    send_now: bool = False                  # create and send in one action


class OfferUpdate(BaseModel):
    """Edit a DRAFT offer. Every change bumps the version and archives the previous body."""
    ctc: Optional[float] = None
    joining_date: Optional[str] = None
    designation: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    content: Optional[str] = None
    signature: Optional[str] = None         # authorised signatory, required to send


class OfferSendIn(BaseModel):
    signature: str                          # the company's authorised signatory


class OfferRevokeIn(BaseModel):
    reason: Optional[str] = None


class PublicOfferResponseIn(BaseModel):
    """A candidate's response. Accepting requires a typed signature; declining does not --
    demanding one from someone walking away is friction with no purpose."""
    action: str                             # "accept" | "decline"
    signature: Optional[str] = None
    note: Optional[str] = None


# =============================================================
# Phase 9 - Onboarding + employee creation
# =============================================================

class OnboardStatus(str, Enum):
    PRE_ONBOARDING = "Pre-Onboarding"   # form issued, awaiting the candidate
    ONBOARDING     = "Onboarding"       # employee id minted, checklist in progress
    COMPLETED      = "Completed"         # every checklist item done


class PreOnboardStatus(str, Enum):
    PENDING   = "Pending"
    SUBMITTED = "Submitted"
    VERIFIED  = "Verified"


class BgVerification(str, Enum):
    PENDING     = "Pending"
    IN_PROGRESS = "In Progress"
    CLEARED     = "Cleared"
    FLAGGED     = "Flagged"


# The joining-day checklist. Declared once so the seed, the progress bar and the
# "all done -> Employee Created" test all read the same list.
ONBOARD_CHECKLIST = [
    ("offer_signed",      "Signed offer letter received"),
    ("documents_verified", "KYC documents verified"),
    ("bg_cleared",        "Background verification cleared"),
    ("employee_id",       "Employee ID generated"),
    ("email_created",     "Company email account created"),
    ("system_access",     "System and tool access granted"),
    ("asset_issued",      "Assets issued (laptop, ID card)"),
    ("workspace",         "Workspace allocated"),
    ("induction",         "Induction / orientation completed"),
    ("policy_ack",        "Policies acknowledged"),
    ("bank_payroll",      "Bank and payroll details recorded"),
    ("buddy_assigned",    "Reporting manager and buddy introduced"),
]
CHECKLIST_KEYS = [k for k, _ in ONBOARD_CHECKLIST]

# Checklist items the system owns. A human toggling these by hand would let the checklist
# claim something the data does not support, so they are driven by the actions that
# actually achieve them.
SYSTEM_CHECKLIST_KEYS = {"employee_id", "documents_verified", "bg_cleared"}

MAX_ONBOARD_DOCUMENTS = 15
MAX_REFERENCES = 5

# Candidate stages an onboarding may be started from.
#
# ONLY `Offer Accepted`. The lifecycle graph declares `SELECTED -> OFFER_GENERATED` and
# `OFFER_ACCEPTED -> PRE_ONBOARDING`, with no edge from Selected to Pre-Onboarding -- so
# allowing a Selected candidate here would create an onboarding whose candidate could never
# legally reach the matching stage. It is also wrong in substance: onboarding collects PAN,
# Aadhaar and bank details, and asking for those before the person has agreed to join
# gathers sensitive identity data on someone who may still say no.
#
# Phase 11-R adds APPOINTMENT_LETTER_SENT: it sits strictly AFTER Offer Accepted, so the
# consent argument above is satisfied a fortiori -- the candidate has agreed to join AND
# been sent their appointment letter. Both are onboardable because the letter is optional.
ONBOARDABLE_STATUSES = {AppStatus.OFFER_ACCEPTED, AppStatus.APPOINTMENT_LETTER_SENT}

AUDIT_ONBOARD_STARTED    = "onboarding started"
AUDIT_ONBOARD_SUBMITTED  = "pre-onboarding submitted"
AUDIT_ONBOARD_VERIFIED   = "kyc documents verified"
AUDIT_ONBOARD_DOCUMENTS  = "kyc documents updated"
AUDIT_ONBOARD_BG         = "background verification updated"
AUDIT_ONBOARD_DETAILS    = "joining details updated"
AUDIT_ONBOARD_CHECKLIST  = "onboarding checklist updated"
AUDIT_EMPLOYEE_ID_ISSUED = "employee id generated"
AUDIT_ONBOARD_COMPLETED  = "onboarding completed"
AUDIT_EMPLOYEE_LINKED    = "employee linked to a user account"

ENTITY_ONBOARDING = "onboarding"


def seed_checklist() -> list:
    return [{"key": k, "label": label, "done": False, "done_at": None, "done_by": None}
            for k, label in ONBOARD_CHECKLIST]


# -- API models --
class OnboardingIn(BaseModel):
    uk: str
    joining_date: Optional[str] = None       # YYYY-MM-DD; defaults from the accepted offer
    reporting_manager_id: Optional[str] = None


class OnboardingDetailsIn(BaseModel):
    joining_date: Optional[str] = None
    reporting_manager_id: Optional[str] = None
    asset_requirements: Optional[str] = None


class OnboardingBgIn(BaseModel):
    bg_verification: BgVerification
    note: Optional[str] = None


class OnboardingChecklistIn(BaseModel):
    key: str
    done: bool


class OnboardingDocumentsIn(BaseModel):
    """HR-side KYC upload. Kept separate from the candidate's public submission so HR can
    collect documents even before the candidate fills the form."""
    documents: List[UploadIn] = Field(default_factory=list)


class EmployeeLinkIn(BaseModel):
    """Attach an employee record created by onboarding to a real login account."""
    user_id: str


class PublicOnboardIn(BaseModel):
    """The candidate's pre-onboarding submission. Entirely untrusted.

    PAN-or-Aadhaar is required, enforced SERVER-SIDE. The source checked this in the browser
    only (BACKEND_ANALYSIS 8), so malformed or absent identity documents reached the
    database on any request that skipped the form.
    """
    pan: Optional[str] = None
    aadhaar: Optional[str] = None
    passport: Optional[str] = None
    driving_license: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[Gender] = None
    address: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    bank_ifsc: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    references: List[dict] = Field(default_factory=list)   # [{name, relation, phone}]
    asset_requirements: Optional[str] = None
    documents: List[UploadIn] = Field(default_factory=list)


# =============================================================
# Phase 10 - analytics & reports (READ-ONLY)
# =============================================================

# -- Effective rank ---------------------------------------------------------------
# A funnel built by counting `application_status` is wrong, and wrong in a way that is
# obvious once seen: a candidate sitting at `Offer Accepted` is NOT counted as having been
# interviewed, so the funnel can show more offers than interviews. FRONTEND_ANALYSIS 6.1
# describes the source working around this in the browser, per screen, inconsistently.
#
# The fix is to rank stages monotonically and count "reached AT LEAST this stage". A
# candidate's effective rank is the furthest point they can be SHOWN to have reached:
#
#     effective_rank = max(rank(application_status),
#                          rank implied by an assessment record,
#                          rank implied by an interview record,
#                          rank implied by an offer record)
#
# Evidence outranks the status field because evidence is a fact and the status is a label
# somebody can drag backwards. This also makes the funnel monotonically non-increasing by
# construction -- a property a funnel must have to mean anything.
STAGE_RANK = {
    AppStatus.APPLIED:              1,
    AppStatus.UNDER_REVIEW:         1,
    AppStatus.DUPLICATE:            1,
    AppStatus.ON_HOLD:              1,
    AppStatus.REJECTED:             1,   # ranked where they entered, not where they left
    AppStatus.SHORTLISTED:          2,
    # ── Phase 11-R ── the client-share band sits WITH Shortlisted, not after it. Sharing a
    # CV and getting a verdict is a decision about a shortlisted candidate; it does not move
    # them further down the funnel, so it must not out-rank shortlisting. CLIENT_REJECTED is
    # ranked where they ENTERED, the same treatment REJECTED gets at rank 1.
    AppStatus.SHARED_WITH_CLIENT:   2,
    AppStatus.CLIENT_SHORTLISTED:   2,
    AppStatus.CLIENT_REJECTED:      2,
    AppStatus.ASSESSMENT_PENDING:   3,
    AppStatus.ASSESSMENT_COMPLETED: 3,
    AppStatus.ASSESSMENT_PASSED:    3,
    AppStatus.ASSESSMENT_FAILED:    3,
    AppStatus.INTERVIEW_SCHEDULED:  4,
    AppStatus.TECHNICAL_ROUND:      4,
    AppStatus.MD_ROUND:             4,
    AppStatus.SELECTED:             5,
    AppStatus.OFFER_GENERATED:      6,
    AppStatus.OFFER_DECLINED:       6,   # they DID receive an offer -- that stage was reached
    AppStatus.OFFER_ACCEPTED:       7,
    # Same band as Offer Accepted / Pre-Onboarding. Existing ranks are NOT renumbered, so
    # the funnel stays monotonic and every Phase 10 figure keeps its meaning.
    AppStatus.APPOINTMENT_LETTER_SENT: 7,
    AppStatus.PRE_ONBOARDING:       7,
    AppStatus.JOINED:               7,
    AppStatus.EMPLOYEE_CREATED:     8,
}

# The funnel, declared once. `min_rank` is the bar a candidate must clear to be counted.
FUNNEL_STAGES = [
    ("applied",     "Applied",      1),
    ("shortlisted", "Shortlisted",  2),
    ("assessment",  "Assessment",   3),
    ("interview",   "Interview",    4),
    ("selected",    "Selected",     5),
    ("offered",     "Offered",      6),
    ("accepted",    "Accepted",     7),
    ("hired",       "Hired",        8),
]

# Rank floors implied by the mere EXISTENCE of a record elsewhere in the pipeline.
RANK_IF_ASSESSED    = 3
RANK_IF_INTERVIEWED = 4
RANK_IF_OFFERED     = 6
RANK_IF_ACCEPTED    = 7


def stage_rank(status) -> int:
    """Rank of an application status. Unknown statuses rank 0 -- counted in the total but
    never credited to a funnel stage, which is the honest treatment of data we cannot
    interpret."""
    try:
        return STAGE_RANK.get(AppStatus(status), 0)
    except ValueError:
        return 0


def conversion(numerator: int, denominator: int) -> float:
    """Stage-to-stage conversion as a percentage, 1 dp. Zero denominator -> 0.0, never a
    ZeroDivisionError and never a misleading 100%."""
    if not denominator:
        return 0.0
    return round(numerator * 100.0 / denominator, 1)


# -- Reports ----------------------------------------------------------------------
# An allow-list, not a free-form collection name. `entity` arrives in the URL, and mapping
# it straight onto a collection would let a caller read any collection in the database.
# Each entry declares its collection, its sortable date field, its searchable fields and
# the EXACT columns exposed -- so a field added to a document later is not silently
# published to a report or an export.
REPORT_ENTITIES = {
    "candidates": {
        "collection": COLL_CANDIDATES,
        "date_field": "applied_at",
        "search":     ["candidate_name", "can_email", "can_contact", "uk"],
        "columns": [
            ("uk", "Candidate ID"), ("candidate_name", "Name"), ("can_email", "Email"),
            ("can_contact", "Phone"), ("source", "Source"),
            ("application_status", "Stage"), ("request_no", "Requisition"),
            ("current_location", "Location"), ("total_experience", "Experience"),
            ("expected_ctc", "Expected CTC"), ("notice_period", "Notice"),
            # ── Phase 11-R ── referral detail and the client's verdict travel with the
            # candidate into every report and export automatically.
            ("referred_by", "Referred by"), ("referral_source", "Referral source"),
            ("client_share_status", "Client verdict"),
            ("applied_at", "Applied on"),
        ],
    },
    "requisitions": {
        "collection": COLL_REQUISITIONS,
        "date_field": "created_at",
        "search":     ["request_no", "designation_name", "department_name"],
        "columns": [
            ("request_no", "Requisition"), ("designation_name", "Designation"),
            ("department_name", "Department"), ("vacancy", "Vacancy"),
            ("urgency_level", "Urgency"), ("approval_status", "Approval"),
            ("closing_status", "Status"), ("assignee_name", "Hiring manager"),
            # ── Phase 11-R ── `budget_status` is DERIVED, not a stored field; the report
            # service computes it per row (see hrms_analytics_service._derive).
            ("client_name", "Client"), ("requisition_type", "Type"),
            ("budget_status", "Budget"),
            ("required_date", "Required by"), ("created_at", "Raised on"),
        ],
    },
    "interviews": {
        "collection": COLL_INTERVIEWS,
        "date_field": "scheduled_at",
        "search":     ["interview_no", "candidate_name", "interviewer_name"],
        "columns": [
            ("interview_no", "Interview"), ("candidate_name", "Candidate"),
            ("round", "Round"), ("mode", "Mode"), ("interviewer_name", "Interviewer"),
            ("status", "Status"), ("outcome", "Outcome"),
            ("average_score", "Avg score"), ("scheduled_at", "Scheduled for"),
        ],
    },
    "offers": {
        "collection": COLL_OFFERS,
        "date_field": "created_at",
        "search":     ["offer_no", "candidate_name", "designation"],
        "columns": [
            ("offer_no", "Offer"), ("candidate_name", "Candidate"),
            ("designation", "Designation"), ("status", "Status"),
            ("ctc", "CTC"), ("joining_date", "Joining date"),
            ("sent_at", "Sent on"), ("responded_at", "Responded on"),
        ],
    },
    "onboarding": {
        "collection": COLL_ONBOARDING,
        "date_field": "created_at",
        "search":     ["onb_no", "candidate_name", "employee_id"],
        "columns": [
            ("onb_no", "Onboarding"), ("candidate_name", "New hire"),
            ("designation", "Designation"), ("status", "Status"),
            ("pre_status", "Pre-onboarding"), ("bg_verification", "Background"),
            ("employee_id", "Employee ID"), ("joining_date", "Joining date"),
            ("created_at", "Started on"),
        ],
    },
}

# Columns carrying compensation. Redacted for a caller without `employee.salary.read`,
# reusing the Phase 2 boundary rather than inventing a second rule for reports.
SALARY_REPORT_COLUMNS = {"ctc", "expected_ctc", "offering_ctc", "current_ctc", "base_salary"}

# (collection, field, label) per breakdown dimension. Also an allow-list: `by` arrives in
# the query string and must never become an arbitrary field name to group on.
BREAKDOWN_FIELDS = {
    "source":      (COLL_CANDIDATES,   "source",           "Source"),
    "department":  (COLL_REQUISITIONS, "department_name",  "Department"),
    "designation": (COLL_REQUISITIONS, "designation_name", "Designation"),
    "platform":    (COLL_JOB_POSTINGS, "platform",         "Platform"),
    # ── Phase 11-R ── still an allow-list: `by` arrives in the query string and any value
    # absent from this map is rejected, so a dotted path here cannot become arbitrary.
    "client_status":   (COLL_CANDIDATES, "client_share.status", "Client verdict"),
    "referral_source": (COLL_CANDIDATES, "referral_source",     "Referral source"),
    "client":          (COLL_REQUISITIONS, "client_name",       "Client"),
}

MAX_REPORT_PAGE_SIZE = 100
DEFAULT_REPORT_PAGE_SIZE = 25
# A hard ceiling on an export. Beyond this the caller is TOLD it was truncated rather than
# handed a silently short file and left to draw conclusions from it.
MAX_EXPORT_ROWS = 5000
# The widest window an analytics query may cover. Bounds the work a single request can ask
# the database to do.
MAX_RANGE_DAYS = 1100          # ~3 years
MAX_BREAKDOWN_ROWS = 25


class ReportEntity(str, Enum):
    CANDIDATES   = "candidates"
    REQUISITIONS = "requisitions"
    INTERVIEWS   = "interviews"
    OFFERS       = "offers"
    ONBOARDING   = "onboarding"


class BreakdownBy(str, Enum):
    SOURCE      = "source"
    DEPARTMENT  = "department"
    DESIGNATION = "designation"
    PLATFORM    = "platform"
    # ── Phase 11-R ──
    CLIENT_STATUS   = "client_status"
    REFERRAL_SOURCE = "referral_source"
    CLIENT          = "client"


class ExportFormat(str, Enum):
    CSV  = "csv"
    XLSX = "xlsx"


# =============================================================
# Phase 11-R, Item 1 - the public-link registry
# =============================================================
# Four kinds of public link already existed (apply / assessment / offer / onboarding), each
# minted independently and surfaced ad-hoc, with no registry, no open tracking, no expiry
# and no revocation. The registry does not CHANGE how any of them are generated -- it
# records them, so there is one place to answer "what links are live, who opened them, and
# how do I kill one".
class LinkKind(str, Enum):
    APPLY       = "apply"
    ASSESSMENT  = "assessment"
    OFFER       = "offer"
    ONBOARDING  = "onboarding"
    APPOINTMENT = "appointment"


class LinkStatus(str, Enum):
    ACTIVE   = "Active"
    EXPIRED  = "Expired"     # past `expires_at` -- COMPUTED on read, never stored
    REVOKED  = "Revoked"     # killed by a human
    CONSUMED = "Consumed"    # its purpose completed (applied / submitted / responded)


# kind -> the relative public path template. One declaration, so the Link Manager, the
# copy-to-clipboard button and the registry can never disagree about a URL.
LINK_PATHS = {
    LinkKind.APPLY:       "/apply/{code}",
    LinkKind.ASSESSMENT:  "/assess/{code}",
    LinkKind.OFFER:       "/offer/{code}",
    LinkKind.ONBOARDING:  "/onboard/{code}",
    LinkKind.APPOINTMENT: "/appointment/{code}",
}

# Statuses in which a link still WORKS. Anything else is refused by assert_link_live().
LIVE_LINK_STATUSES = {LinkStatus.ACTIVE, LinkStatus.CONSUMED}

# Which service owns each kind, for reissue. A reissue must delegate to the owning service
# so the fresh code is one that service knows about -- minting a code here that
# hrms_offer_service has never heard of would produce a link that resolves to nothing.
REISSUABLE_KINDS = {LinkKind.ASSESSMENT, LinkKind.OFFER, LinkKind.ONBOARDING,
                    LinkKind.APPOINTMENT}

def effective_link_status(doc: dict, today: str) -> str:
    """A link's status as it actually is right now. Pure — no DB, no clock.

    Expiry is COMPUTED, exactly as hrms_posting_service._effective_status computes a
    posting's: a link past its expiry date reads Expired without a nightly job, and nothing
    is written, so the stored value still shows what an operator set.

    Revoked and Consumed are stored facts and outrank the date. A REVOKED link that is also
    past expiry is Revoked -- the human decision is the more informative answer.

    Tolerates a document with no status at all (written before this phase), which reads
    Active: the registry must never lock out a link it simply does not know about.
    """
    doc = doc or {}
    status = doc.get("status") or LinkStatus.ACTIVE.value
    if status in (LinkStatus.REVOKED.value, LinkStatus.CONSUMED.value):
        return status
    # Both are 'YYYY-MM-DD' strings, which compare correctly lexically and are immune to
    # server-timezone drift -- the same convention is_iso_date documents for every date here.
    expires = doc.get("expires_at")
    if expires and today and str(expires) < str(today):
        return LinkStatus.EXPIRED.value
    return status


AUDIT_LINK_ISSUED   = "public link issued"
AUDIT_LINK_REVOKED  = "public link revoked"
AUDIT_LINK_REISSUED = "public link reissued"

ENTITY_LINK = "link"


class LinkRevokeIn(BaseModel):
    reason: Optional[str] = None


# =============================================================
# Phase 11-R, Item 2 - documentation
# =============================================================
class DocumentOwnerType(str, Enum):
    CANDIDATE = "candidate"
    EMPLOYEE  = "employee"


class DocumentCategory(str, Enum):
    IDENTITY       = "Identity"
    EDUCATIONAL    = "Educational"
    EMPLOYMENT     = "Employment"
    STATUTORY      = "Statutory"
    COMPANY_ISSUED = "Company Issued"
    OTHER          = "Other"


class DocumentStatus(str, Enum):
    PENDING      = "Pending"        # expected, nothing uploaded yet
    UPLOADED     = "Uploaded"
    UNDER_REVIEW = "Under Review"
    VERIFIED     = "Verified"
    REJECTED     = "Rejected"
    EXPIRED      = "Expired"        # past `expiry_date` -- COMPUTED on read, never stored


# Rejecting a document requires a reason, the same rule REQ_TRANSITIONS applies to a
# rejected requisition: a refusal the owner cannot act on is not a decision, it is a wall.
DOCUMENT_STATUSES_REQUIRING_REMARKS = {DocumentStatus.REJECTED}

# A document is a small number of revisions, not a version-control system. Ten is generous
# for "the scan was blurry, here it is again" and bounds one document's storage.
MAX_DOCUMENT_VERSIONS = 10

# How many days ahead counts as "expiring soon" on the register's filter.
DOCUMENT_EXPIRY_SOON_DAYS = 30

# Seeded for a company that has no document types yet, on first read. A sensible Indian
# HR starting set -- HR edits it; nothing here is mandatory to keep.
# (name, category, applies_to, mandatory, expires)
DEFAULT_DOCUMENT_TYPES = [
    ("PAN Card",              DocumentCategory.IDENTITY,       "both",      True,  False),
    ("Aadhaar Card",          DocumentCategory.IDENTITY,       "both",      True,  False),
    ("Passport",              DocumentCategory.IDENTITY,       "both",      False, True),
    ("Address Proof",         DocumentCategory.IDENTITY,       "both",      False, False),
    ("Photograph",            DocumentCategory.IDENTITY,       "both",      True,  False),
    ("Degree Certificate",    DocumentCategory.EDUCATIONAL,    "both",      True,  False),
    ("Experience Letter",     DocumentCategory.EMPLOYMENT,     "both",      False, False),
    ("Relieving Letter",      DocumentCategory.EMPLOYMENT,     "both",      False, False),
    ("Last 3 Payslips",       DocumentCategory.EMPLOYMENT,     "candidate", False, False),
    ("Bank Proof",            DocumentCategory.STATUTORY,      "employee",  True,  False),
    ("Offer Letter Signed",   DocumentCategory.COMPANY_ISSUED, "candidate", False, False),
    ("Appointment Letter",    DocumentCategory.COMPANY_ISSUED, "candidate", False, False),
]

AUDIT_DOCUMENT_UPLOADED  = "document uploaded"
AUDIT_DOCUMENT_VERSIONED = "document version added"
AUDIT_DOCUMENT_UPDATED   = "document updated"
AUDIT_DOCUMENT_STATUS    = "document status changed"
AUDIT_DOCUMENT_DELETED   = "document deleted"
AUDIT_DOCTYPE_CREATED    = "document type created"
AUDIT_DOCTYPE_UPDATED    = "document type updated"
AUDIT_DOCTYPE_DELETED    = "document type deleted"

ENTITY_DOCUMENT      = "document"
ENTITY_DOCUMENT_TYPE = "document_type"


class DocumentTypeIn(BaseModel):
    name: str
    code: Optional[str] = None
    category: DocumentCategory = DocumentCategory.OTHER
    applies_to: str = "both"                 # candidate | employee | both
    mandatory: bool = False
    expires: bool = False
    active: bool = True


class DocumentTypeUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    category: Optional[DocumentCategory] = None
    applies_to: Optional[str] = None
    mandatory: Optional[bool] = None
    expires: Optional[bool] = None
    active: Optional[bool] = None


class DocumentIn(BaseModel):
    """Upload a document, or a new version of one.

    Supplying `doc_no` adds a VERSION to that document; omitting it creates a new one.
    One endpoint for both because they are the same act from the operator's side -- "here
    is the paperwork" -- and splitting them would make the client decide which it is.
    """
    owner_type: DocumentOwnerType
    owner_id: str                            # uk | employee_code
    type_id: str
    doc_no: Optional[str] = None             # set to add a version to an existing document
    file: UploadIn
    issue_date: Optional[str] = None         # YYYY-MM-DD
    expiry_date: Optional[str] = None        # YYYY-MM-DD
    remarks: Optional[str] = None


class DocumentUpdate(BaseModel):
    """Metadata only. The FILE is immutable -- correcting it means a new version, so the
    record of what was actually submitted at each point survives."""
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None
    remarks: Optional[str] = None
    type_id: Optional[str] = None


class DocumentStatusIn(BaseModel):
    status: DocumentStatus
    remarks: Optional[str] = None            # REQUIRED when rejecting


# =============================================================
# Phase 11-R, Item 3 - appointment letters
# =============================================================
# Deliberately its own collection rather than extra statuses on hrms_offers. An offer and an
# appointment letter are two artifacts with two lifecycles: the offer proposes terms and is
# accepted or declined; the appointment letter confirms joining and is acknowledged. Folding
# them together would mean one `status` field trying to describe two documents -- exactly
# the "two sources of truth in one column" problem Phase 5 removed from candidates.
class AppointmentStatus(str, Enum):
    NOT_GENERATED = "Not Generated"          # the eligible-list state; never stored
    GENERATED     = "Generated"              # drafted, not yet issued
    SENT          = "Sent"
    PENDING_ACK   = "Pending Acknowledgement"  # the candidate has opened it
    ACKNOWLEDGED  = "Acknowledged"
    CANCELLED     = "Cancelled"


# Only a Generated letter is editable. Identical rule, and identical reasoning, to
# EDITABLE_OFFER_STATUSES: once sent, the document the candidate is reading must not change
# underneath them.
EDITABLE_APPOINTMENT_STATUSES = {AppointmentStatus.GENERATED}

# States in which the candidate's public link still resolves.
LIVE_APPOINTMENT_STATUSES = {AppointmentStatus.SENT, AppointmentStatus.PENDING_ACK,
                             AppointmentStatus.ACKNOWLEDGED}

AUDIT_APPOINTMENT_GENERATED = "appointment letter generated"
AUDIT_APPOINTMENT_EDITED    = "appointment letter edited"
AUDIT_APPOINTMENT_SENT      = "appointment letter sent"
AUDIT_APPOINTMENT_OPENED    = "appointment letter opened"
AUDIT_APPOINTMENT_ACK       = "appointment letter acknowledged"
AUDIT_APPOINTMENT_CANCELLED = "appointment letter cancelled"

ENTITY_APPOINTMENT = "appointment"


DEFAULT_APPOINTMENT_BODY = """Further to your acceptance of our offer, we are pleased to confirm your appointment as {designation} at {company}.

Your appointment takes effect from {joining_date} and you will be based at {location}. Your annual cost to company will be {ctc}.

This appointment is subject to the terms set out in your offer letter, to the satisfactory completion of any background verification still in progress, and to the submission of the documents requested by the HR team.

Please confirm your acceptance of this appointment by acknowledging this letter below. We look forward to welcoming you to the team."""


def render_appointment_body(template: str, *, designation: str, company: str, ctc: str,
                            joining_date: str, location: str = "") -> str:
    """Fill the placeholders in an appointment letter body.

    Same mechanism, and the same reasoning, as render_offer_body: a plain format_map with a
    defaulting dict, so operator-edited text containing an unknown placeholder renders
    harmlessly rather than raising or executing anything.
    """
    class _Safe(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return (template or "").format_map(_Safe(
            designation=designation or "", company=company or "", ctc=ctc or "",
            joining_date=joining_date or "", location=location or ""))
    except (ValueError, IndexError):
        return template or ""


class AppointmentIn(BaseModel):
    uk: str
    joining_date: Optional[str] = None       # YYYY-MM-DD; defaults from the accepted offer
    designation: Optional[str] = None
    department: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    ctc: Optional[float] = None
    content: Optional[str] = None            # defaults to DEFAULT_APPOINTMENT_BODY
    signature: Optional[str] = None


class AppointmentUpdate(BaseModel):
    joining_date: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    ctc: Optional[float] = None
    content: Optional[str] = None
    signature: Optional[str] = None


class AppointmentSendIn(BaseModel):
    signature: str                           # the company's authorised signatory


class AppointmentCancelIn(BaseModel):
    reason: Optional[str] = None


class PublicAppointmentAckIn(BaseModel):
    """The candidate's acknowledgement. A typed signature is REQUIRED -- acknowledging an
    appointment letter is an act with consequences, so it is attributable, exactly as
    accepting an offer is."""
    signature: str
    note: Optional[str] = None


# =============================================================
# Phase 11-R, Item 4 - the client master + client sharing
# =============================================================
# CONFIRMED WITH THE BUSINESS (see PHASE_11R_REPORT §Decisions): this deployment is the
# recruitment-AGENCY model. A "client" is the organisation a vacancy is being filled FOR,
# held in its own master, and is NOT the same thing as `company_id` (which remains the ERP
# tenant that OWNS the data). Every requisition may name one; scoping still runs on
# company_id throughout, so the client dimension is a reporting axis, never a security one.
class ClientStatus(str, Enum):
    ACTIVE   = "Active"
    INACTIVE = "Inactive"


class ClientShareStatus(str, Enum):
    PENDING     = "Pending"
    SHORTLISTED = "Shortlisted"
    REJECTED    = "Rejected"
    ON_HOLD     = "On Hold"


# The client's verdict -> where the candidate lands. Declared as data, so the verdict
# handler is a lookup rather than a branch, and FORWARD_TRANSITIONS still decides legality.
CLIENT_RESPONSE_STATUS = {
    ClientShareStatus.SHORTLISTED: AppStatus.CLIENT_SHORTLISTED,
    ClientShareStatus.REJECTED:    AppStatus.CLIENT_REJECTED,
    ClientShareStatus.ON_HOLD:     AppStatus.ON_HOLD,
    ClientShareStatus.PENDING:     None,      # no verdict yet -- the candidate does not move
}

AUDIT_CLIENT_CREATED   = "client created"
AUDIT_CLIENT_UPDATED   = "client updated"
AUDIT_CLIENT_DELETED   = "client deleted"
AUDIT_CLIENT_SHARED    = "cv shared with client"
AUDIT_CLIENT_RESPONSE  = "client verdict recorded"

ENTITY_CLIENT = "client"


class ClientIn(BaseModel):
    name: str
    code: Optional[str] = None
    industry: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    industry: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    active: Optional[bool] = None


class ClientResponseIn(BaseModel):
    """Record the hiring client's verdict on a shared CV.

    Recorded BY an HRMS user on the client's behalf -- there is deliberately no public
    client portal in this phase, and inventing one would be a far larger surface than the
    review asked for.
    """
    uk: str
    status: ClientShareStatus
    remarks: Optional[str] = None
    responded_at: Optional[str] = None        # YYYY-MM-DD; defaults to now


# =============================================================
# Phase 11-R, Item 7 - sanctioned strength
# =============================================================
AUDIT_SANCTION_CREATED = "sanctioned strength set"
AUDIT_SANCTION_UPDATED = "sanctioned strength updated"
AUDIT_SANCTION_DELETED = "sanctioned strength removed"

ENTITY_SANCTION = "sanctioned_strength"


class SanctionedStrengthIn(BaseModel):
    department_id: str
    designation_id: str
    sanctioned_count: int
    effective_from: Optional[str] = None      # YYYY-MM-DD
    notes: Optional[str] = None


class SanctionedStrengthUpdate(BaseModel):
    sanctioned_count: Optional[int] = None
    effective_from: Optional[str] = None
    notes: Optional[str] = None


def is_over_sanction(sanctioned, actual: int, open_vacancies: int, requested: int) -> bool:
    """Whether filling `requested` more seats would exceed the sanctioned strength.

    `sanctioned is None` means no figure has ever been set for this position, which counts
    as over-sanction: a headcount nobody has authorised is precisely the case that should be
    escalated rather than waved through. Failing OPEN here would make the whole control
    optional by omission.
    """
    if sanctioned is None:
        return True
    try:
        return (int(actual) + int(open_vacancies) + int(requested)) > int(sanctioned)
    except (TypeError, ValueError):
        return True
