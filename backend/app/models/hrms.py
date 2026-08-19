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
# No COLL_CLIENTS: a client is a company from the ERP's Companies section, read through
# hrms_client_service. Storing them again here is what that module exists to prevent.
#
# What IS stored is the ENGAGEMENT -- the fact that this tenant provides recruitment services
# to that company, and which of this tenant's users work on it. That relationship exists
# nowhere in the ERP and cannot be derived, so without it there is no way to answer "is this
# company a client OF ours", which is the question every client-scope check rests on.
COLL_CLIENT_ENGAGEMENTS  = "hrms_client_engagements"
COLL_SANCTIONED_STRENGTH = "hrms_sanctioned_strength"

# Internal (in-house) recruitment track. Every one of these carries `request_no`, and the
# candidate-linked ones also carry `uk`, so the single analytics scope filter keeps working.
COLL_POSITION_SCORECARDS = "hrms_position_scorecards"
# ── Phase INT-4 ── the SOP's step 5 telephonic screen. Carries `request_no` AND `uk`: it
# describes work done on one candidate against one vacancy.
COLL_TELEPHONIC          = "hrms_telephonic_screenings"
COLL_REFERENCE_CHECKS    = "hrms_reference_checks"
COLL_PROBATION_REVIEWS   = "hrms_probation_reviews"
COLL_EXCEPTIONS          = "hrms_exceptions"

# ── Phase INT-2 — closing the remaining SOP gaps ──
# Same rule as the block above: every one of these carries `request_no` where it describes
# WORK (a shortlist decision, a touchpoint, a message, a survey response), so the single
# analytics scope filter reaches them unchanged. The four that are CONFIGURATION rather than
# work -- interview windows, salary bands, communication templates, the policy register --
# do not, for exactly the reason hrms_document_types does not: a template belongs to a
# company, not to one vacancy.
COLL_SHORTLIST_REVIEWS   = "hrms_shortlist_reviews"      # SOP §5 shortlisting committee
COLL_INTERVIEW_WINDOWS   = "hrms_interview_windows"      # Annexure C batch interview slots
COLL_PREBOARDING         = "hrms_preboarding_touchpoints"  # SOP §6 pre-boarding engagement
COLL_SALARY_BANDS        = "hrms_salary_bands"           # Annexure C standing bands
COLL_COMM_TEMPLATES      = "hrms_comm_templates"         # Annexure C candidate experience
COLL_COMM_LOG            = "hrms_comm_log"               # append-only send record
COLL_SURVEYS             = "hrms_surveys"                # SOP §10 new-hire experience
COLL_SURVEY_RESPONSES    = "hrms_survey_responses"
COLL_POLICIES            = "hrms_policies"               # SOP §14 policy register
COLL_POLICY_REVISIONS    = "hrms_policy_revisions"
COLL_PURGE_BATCHES       = "hrms_purge_batches"          # SOP §13 retention purge proposals

# ── Phase INT-3 ── the scheduled-job ledger (SOP §12 reminders and escalations).
#
# One row per (company, job): the stamp of the last SUCCESSFUL run. It is deliberately
# durable rather than in-memory, unlike the TPMS job state it sits beside: a TPMS sweep is
# an idempotent sync, so re-running it after a restart costs nothing, whereas re-running a
# reminder job SENDS THE REMINDER AGAIN. Process memory resets on every deploy; this does
# not.
#
# CONFIGURATION, not work, so it carries no `request_no` -- the same reason the four
# Phase INT-2 configuration collections above carry none.
#
# Carries a UNIQUE index on (company_id, job_key), declared in HRMS_INDEXES below. Without
# it, two workers claiming the same slot in the same instant can leave two rows, and a job
# reading the stale one runs a second time.
COLL_JOB_RUNS            = "hrms_job_runs"

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

    # Clients have no collection of their own: they ARE the ERP's companies. The index that
    # matters for client-wise reporting is on the requisition that names one.
    (COLL_REQUISITIONS, [("company_id", 1), ("client_id", 1)], {"name": "by_company_client"}),
    # Internal track: every list and every KPI filters by track first.
    (COLL_REQUISITIONS, [("company_id", 1), ("requisition_track", 1)],
     {"name": "by_company_track"}),

    # ── Client engagements ──
    (COLL_CLIENT_ENGAGEMENTS, [("engagement_id", 1)],   {"unique": True,
                                                         "name": "uniq_engagement_id"}),
    # One engagement per (tenant, client). A second would mean two answers to "are they our
    # client", and two member lists to keep in step.
    (COLL_CLIENT_ENGAGEMENTS, [("company_id", 1), ("client_id", 1)],
     {"unique": True, "name": "uniq_company_client"}),
    # THE index the scope resolver reads on every client-scoped request.
    (COLL_CLIENT_ENGAGEMENTS, [("company_id", 1), ("member_user_ids", 1), ("status", 1)],
     {"name": "by_member_scope"}),

    # ── Internal recruitment track ──
    # One scorecard per requisition -- the uniqueness IS the rule, exactly as it is for
    # sanctioned strength.
    (COLL_POSITION_SCORECARDS, [("scr_no", 1)],               {"unique": True,
                                                               "name": "uniq_scr_no"}),
    (COLL_POSITION_SCORECARDS, [("company_id", 1), ("request_no", 1)],
     {"unique": True, "name": "uniq_company_request"}),

    (COLL_REFERENCE_CHECKS, [("ref_no", 1)],                  {"unique": True,
                                                               "name": "uniq_ref_no"}),
    # A candidate may have SEVERAL referees, so this is deliberately not unique.
    (COLL_REFERENCE_CHECKS, [("company_id", 1), ("uk", 1)],   {"name": "by_company_candidate"}),
    (COLL_REFERENCE_CHECKS, [("request_no", 1)],              {"name": "by_request"}),

    (COLL_PROBATION_REVIEWS, [("prb_no", 1)],                 {"unique": True,
                                                               "name": "uniq_prb_no"}),
    # One live probation per employee. A second term after an extension updates this record
    # rather than opening a competing one.
    (COLL_PROBATION_REVIEWS, [("company_id", 1), ("employee_code", 1)],
     {"unique": True, "name": "uniq_company_employee"}),
    # `GET /probation/due` sorts on this, and it is the field the SLA breach sweep reads.
    (COLL_PROBATION_REVIEWS, [("company_id", 1), ("ends_on", 1)], {"name": "by_company_end"}),

    (COLL_EXCEPTIONS, [("exc_no", 1)],                        {"unique": True,
                                                               "name": "uniq_exc_no"}),
    # The gate checks read this exact shape: "is there an APPROVED exception of this type
    # for this requisition (and candidate)".
    (COLL_EXCEPTIONS, [("company_id", 1), ("request_no", 1), ("exception_type", 1),
                       ("status", 1)],                        {"name": "by_gate_lookup"}),
    (COLL_EXCEPTIONS, [("company_id", 1), ("uk", 1)],         {"name": "by_company_candidate"}),

    # One sanctioned figure per position per company — the uniqueness IS the rule.
    (COLL_SANCTIONED_STRENGTH,
     [("company_id", 1), ("department_id", 1), ("designation_id", 1)],
     {"unique": True, "name": "uniq_company_position"}),

    # ── Phase INT-2 ──
    (COLL_SHORTLIST_REVIEWS, [("slr_no", 1)],                {"unique": True,
                                                              "name": "uniq_slr_no"}),
    # The gate on `Selected` asks "is there a committee record covering this candidate on
    # this requisition", so both are indexed. Deliberately NOT unique: a second intake on
    # the same requisition is a second committee sitting, not a correction of the first.
    (COLL_SHORTLIST_REVIEWS, [("company_id", 1), ("request_no", 1)],
     {"name": "by_company_request"}),
    (COLL_SHORTLIST_REVIEWS, [("company_id", 1), ("candidate_uks", 1)],
     {"name": "by_company_candidate"}),

    # Scheduling looks a window up by department and weekday on every booking.
    (COLL_INTERVIEW_WINDOWS, [("company_id", 1), ("department_id", 1), ("weekday", 1)],
     {"name": "by_company_department_day"}),

    (COLL_PREBOARDING, [("pbt_no", 1)],                      {"unique": True,
                                                              "name": "uniq_pbt_no"}),
    # `GET /preboarding/due` reads the LATEST touchpoint per candidate, so this is the
    # index it sorts on.
    (COLL_PREBOARDING, [("company_id", 1), ("candidate_uk", 1), ("contacted_at", -1)],
     {"name": "by_company_candidate_recent"}),
    (COLL_PREBOARDING, [("request_no", 1)],                  {"name": "by_request"}),

    # One ACTIVE band per (department, designation, grade) is a rule the service enforces
    # rather than the index, because a superseded band stays on file with its own
    # effective dates -- uniqueness here would make history impossible to keep.
    (COLL_SALARY_BANDS, [("band_no", 1)],                    {"unique": True,
                                                              "name": "uniq_band_no"}),
    (COLL_SALARY_BANDS,
     [("company_id", 1), ("department_id", 1), ("designation_id", 1), ("status", 1)],
     {"name": "by_company_position_status"}),

    # A template is addressed by its KEY, which is why the key is what must be unique.
    (COLL_COMM_TEMPLATES, [("company_id", 1), ("key", 1)],   {"unique": True,
                                                              "name": "uniq_company_key"}),
    (COLL_COMM_LOG, [("company_id", 1), ("candidate_uk", 1), ("sent_at", -1)],
     {"name": "by_company_candidate_recent"}),
    (COLL_COMM_LOG, [("request_no", 1)],                     {"name": "by_request"}),

    (COLL_SURVEYS, [("srv_no", 1)],                          {"unique": True,
                                                              "name": "uniq_srv_no"}),
    (COLL_SURVEYS, [("company_id", 1), ("kind", 1)],         {"name": "by_company_kind"}),
    (COLL_SURVEY_RESPONSES, [("srp_no", 1)],                 {"unique": True,
                                                              "name": "uniq_srp_no"}),
    # One response per instrument per employee. The uniqueness IS the de-duplication, and
    # it is the only reason `employee_code` is stored at all -- see SURVEY_MIN_RESPONSES.
    (COLL_SURVEY_RESPONSES, [("company_id", 1), ("srv_no", 1), ("employee_code", 1)],
     {"unique": True, "sparse": True, "name": "uniq_survey_employee"}),
    (COLL_SURVEY_RESPONSES, [("request_no", 1)],             {"name": "by_request"}),

    (COLL_POLICIES, [("company_id", 1), ("policy_key", 1)],  {"unique": True,
                                                              "name": "uniq_company_policy"}),
    # The review-due sweep is a range scan on this.
    (COLL_POLICIES, [("company_id", 1), ("next_review_due", 1)],
     {"name": "by_company_review_due"}),
    (COLL_POLICY_REVISIONS, [("company_id", 1), ("policy_key", 1), ("version", 1)],
     {"unique": True, "name": "uniq_company_policy_version"}),

    (COLL_PURGE_BATCHES, [("batch_no", 1)],                  {"unique": True,
                                                              "name": "uniq_batch_no"}),
    (COLL_PURGE_BATCHES, [("company_id", 1), ("status", 1)], {"name": "by_company_status"}),

    # ── Phase INT-3: the scheduled-job ledger ──
    # UNIQUE, and load-bearing rather than tidy. The ledger is what stops a reminder job
    # running twice in one period, and it can only do that if one (company, job) means one
    # row. Two workers starting the same slot in the same instant both find no row and both
    # insert; this index is what makes the loser's insert raise instead of leaving a second
    # row that `already_ran` might read and let the job fire again.
    (COLL_JOB_RUNS, [("company_id", 1), ("job_key", 1)],     {"unique": True,
                                                              "name": "uniq_company_job"}),

    # ── Phase INT-4: telephonic screening ──
    # NOT unique on (company, candidate): a second call happens (the first was cut off, the
    # candidate asked to be rung back), and the gate asks whether ANY screen passed.
    (COLL_TELEPHONIC, [("tel_no", 1)],                       {"unique": True,
                                                              "name": "uniq_tel_no"}),
    (COLL_TELEPHONIC, [("company_id", 1), ("uk", 1)],        {"name": "by_candidate"}),
    (COLL_TELEPHONIC, [("company_id", 1), ("outcome", 1)],   {"name": "by_company_outcome"}),
    (COLL_TELEPHONIC, [("request_no", 1)],                   {"name": "by_request"}),
    # ── Later phases append their indexes here, one phase at a time. ──
]


# ─────────────────────────────────────────────────────────────
# Roles — translation from the ERP identity model to HRMS roles
# ─────────────────────────────────────────────────────────────
# The ERP has two user collections and two role axes:
#   • `staff`    → role: superadmin | admin | coach | staff        (Sparsh internal)
#   • `learners` → role: clientadmin | clientuser                  (client-side)
#                  + governance_role: MD | HR | FINANCE | HOD | IMPLEMENTOR
#                    (the client ladder, already used by auth_controller.client_rank)
#
# HRMS is a CLIENT-COMPANY module: a client's HR team hires and pays their own staff,
# scoped by company_id. Sparsh internal staff get cross-company admin/support visibility.
# This mirrors TPMS/ORM/Delegation exactly.
class HrmsRole(str, Enum):
    ADMIN    = "admin"      # Sparsh superadmin — full HRMS owner, cross-company
    INTERNAL = "internal"   # Sparsh admin/coach/staff — cross-company operator + support
    MD       = "md"         # client MD / clientadmin — final approver within their company
    HR       = "hr"         # client HR — the recruitment + HR-ops operator
    # Internal-track budget authority. The Internal Recruitment SOP treats
    # "Management / Finance" as ONE accountable actor (Annexure B), so FINANCE holds the
    # budget and offer approvals but NOT the hiring judgement — it approves what a role
    # costs, never who fills it.
    FINANCE  = "finance"
    MANAGER  = "manager"    # client HOD — hiring manager; raises reqs, co-reviews assessments
    EMPLOYEE = "employee"   # client implementor / plain user — self-service only
    # A user of a CLIENT ORGANISATION this tenant recruits for -- not a Sparsh user at all.
    # The distinction that matters: every role above is scoped by company_id alone, and this
    # one is additionally scoped to the client engagements it belongs to. See
    # utils/hrms_access.scope_client_ids.
    CLIENT   = "client"


# Which ERP roles map into the two internal HRMS roles.
INTERNAL_OWNER_ROLES = {"superadmin"}
INTERNAL_STAFF_ROLES = {"admin", "coach", "staff"}
CLIENT_ROLES         = {"clientadmin", "clientuser"}

# Client governance ladder → HRMS role. `clientadmin` is the company's top authority and
# maps to MD independently of governance_role (auth_controller.client_rank does the same).
GOVERNANCE_TO_HRMS = {
    "MD":          HrmsRole.MD,
    "HR":          HrmsRole.HR,
    # Peer of HR on the governance ladder (auth_controller.CLIENT_RANK gives both 3): a
    # finance controller is not senior to HR, they own a different decision.
    "FINANCE":     HrmsRole.FINANCE,
    "HOD":         HrmsRole.MANAGER,
    "IMPLEMENTOR": HrmsRole.EMPLOYEE,
    # A user of a client organisation. Ranked lowest by auth_controller.CLIENT_RANK: they
    # are not part of this company's governance ladder at all, and must never be able to
    # assign work up it.
    "CLIENT":      HrmsRole.CLIENT,
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
    # Item 4 — the client dimension (recruitment-agency model; see PHASE_11R_REPORT
    # §Decisions). Reading a client still means reading a COMPANY, which is why there is no
    # capability here for editing one -- that remains the Companies module's `companies.write`.
    CLIENT_READ  = "client.read"
    # Manage ENGAGEMENTS, which is a different act from editing a company: it records that
    # this tenant recruits for that company, and which of this tenant's users work on it.
    # That relationship is HRMS's own, so the capability is too.
    CLIENT_WRITE = "client.write"
    # Item 7 — sanctioned strength + the escalation ladder.
    SANCTION_READ  = "sanction.read"
    SANCTION_WRITE = "sanction.write"
    REQUISITION_ESCALATE = "requisition.escalate"   # act on an over-sanction escalation step

    # ══ Internal (in-house) recruitment track ══
    # Sparsh Magic hiring for itself. The defining difference from the client track is that
    # the budget is owned INTERNALLY, so these capabilities are all about who may commit the
    # company's own money and who may confirm its own people.
    #
    # Granted per Annexure B of the Internal Recruitment SOP (RACI). Where the SOP says
    # "A" (accountable) the capability is an approval; where it says "R" (responsible) it is
    # a write; "C"/"I" get read only.
    #
    # The mandatory budget gate. No sourcing may begin before it clears (SOP §11:
    # "No internal role may be sourced without prior written headcount and budget
    # approval"), and that is enforced in the posting and candidate services, not the UI.
    REQUISITION_APPROVE_BUDGET = "requisition.approve_budget"
    # The position scorecard: HR drafts, the HOD approves, Management also approves for
    # managerial+ roles.
    SCORECARD_READ    = "scorecard.read"
    SCORECARD_WRITE   = "scorecard.write"
    SCORECARD_APPROVE = "scorecard.approve"
    # Reference checks. Mandatory before an internal offer, because Sparsh Magic bears the
    # direct employment risk rather than a client.
    REFERENCE_READ  = "reference.read"
    REFERENCE_WRITE = "reference.write"
    # ── Phase INT-4 ── the telephonic screen (SOP step 5). Annexure B makes HR Responsible
    # and everybody else Informed, so WRITE is HR's alone; the HOD and Management read it
    # because they interview off the back of it.
    TELEPHONIC_READ  = "telephonic.read"
    TELEPHONIC_WRITE = "telephonic.write"
    # Offer approval. Annexure B marks this "A" for Management/Finance and Table 2 calls it
    # mandatory, so it is a real act and not merely a band check on the CTC.
    OFFER_APPROVE = "offer.approve"
    # Probation. Recorded against the EMPLOYEE, not the candidate — see the note above
    # TERMINAL_STATUSES for why the candidate lifecycle is deliberately left alone.
    PROBATION_READ    = "probation.read"
    PROBATION_REVIEW  = "probation.review"
    PROBATION_CONFIRM = "probation.confirm"
    # Day-1 induction checklist.
    INDUCTION_READ  = "induction.read"
    INDUCTION_WRITE = "induction.write"
    # The exception log. An APPROVED exception is the only thing that unblocks the
    # reference-check and salary-band gates — there is deliberately no override flag.
    EXCEPTION_READ    = "exception.read"
    EXCEPTION_WRITE   = "exception.write"
    EXCEPTION_APPROVE = "exception.approve"
    # Closing the personnel file, which is what closes an internal requisition (there is no
    # client handover in this track).
    PERSONNEL_FILE_CLOSE = "personnel_file.close"

    # ══ Phase INT-2 — the remaining SOP controls ══
    # The internal shortlisting committee (SOP §5). Deliberately NOT granted to FINANCE:
    # Finance approves what a role costs, never who fills it, and this record is entirely
    # about who fills it. Same line REFERENCE_* and CANDIDATE_SCREEN already draw.
    SHORTLIST_READ  = "shortlist.read"
    SHORTLIST_WRITE = "shortlist.write"
    # Pre-boarding engagement (SOP §6). Tracking, not a gate -- nothing is blocked by it,
    # which is why there is no third "approve" capability here.
    PREBOARDING_READ  = "preboarding.read"
    PREBOARDING_WRITE = "preboarding.write"
    # The standing salary-band master (Annexure C). WRITE is Finance and the MD alone: a
    # band agreed annually with Finance is Finance's artifact, and HR reading it is what
    # lets the budget gate pre-fill from it.
    SALARY_BAND_READ  = "salary_band.read"
    SALARY_BAND_WRITE = "salary_band.write"
    # Candidate communications (Annexure C). Sending and reading the log are operational;
    # editing a TEMPLATE is not -- the templates carry the equal-opportunity and data-use
    # wording, so changing one is closer to a policy act than an HR one.
    COMM_READ           = "comm.read"
    COMM_WRITE          = "comm.write"
    COMM_TEMPLATE_WRITE = "comm.template.write"
    # New-hire experience surveys (SOP §10). READ is the AGGREGATE only -- the service
    # refuses a breakdown below SURVEY_MIN_RESPONSES, so this capability can never become
    # a way to read one person's answers.
    SURVEY_READ  = "survey.read"
    SURVEY_WRITE = "survey.write"
    # The policy register (SOP §14). APPROVE is the MD's alone: approving a revision is
    # what makes a version the one in force.
    POLICY_READ    = "policy.read"
    POLICY_WRITE   = "policy.write"
    POLICY_APPROVE = "policy.approve"
    # Executing a retention purge (SOP §13). MD only, and the same standard as probation
    # confirmation because both destroy or end something.
    RETENTION_PURGE = "retention.purge"
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
        # Setting up an engagement is administrative support work, not a governance
        # decision about the client's hiring -- the same line that gives INTERNAL
        # LINK_MANAGE and DOCUMENT_WRITE but withholds every approval.
        Cap.CLIENT_READ, Cap.CLIENT_WRITE,
        Cap.SANCTION_READ,
        # ── Internal track ── READS ONLY, for the reason the rest of this set is shaped the
        # way it is: Sparsh staff support the client's hiring, they do not govern it. Budget
        # approval, scorecard sign-off, offer approval, probation confirmation and exception
        # approval are all the client's own acts, exactly like REQUISITION_APPROVE_MD and
        # DOCUMENT_VERIFY above.
        Cap.SCORECARD_READ,
        Cap.REFERENCE_READ,
        Cap.TELEPHONIC_READ,
        Cap.PROBATION_READ,
        Cap.INDUCTION_READ,
        Cap.EXCEPTION_READ,
        # ── Phase INT-2 ── reads only, for the same reason as the block above. Note the
        # absences: no SALARY_BAND_READ (a client's pay structure is not support-staff
        # business, exactly as EMPLOYEE_SALARY_READ is withheld) and no COMM_WRITE (a
        # message to a candidate goes out over the client's name).
        Cap.SHORTLIST_READ,
        Cap.PREBOARDING_READ,
        Cap.COMM_READ,
        Cap.SURVEY_READ,
        Cap.POLICY_READ,
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
        # ── Internal track ── the MD is the top of the ladder and holds EVERY internal
        # capability, for the same reason it holds REQUISITION_ESCALATE: a governance chain
        # whose final authority cannot act is a trap, not a control. In a company with no
        # FINANCE user the MD alone can therefore run the whole internal track.
        Cap.REQUISITION_APPROVE_BUDGET,
        Cap.SCORECARD_READ, Cap.SCORECARD_WRITE, Cap.SCORECARD_APPROVE,
        Cap.REFERENCE_READ, Cap.REFERENCE_WRITE,
        Cap.TELEPHONIC_READ, Cap.TELEPHONIC_WRITE,
        Cap.OFFER_APPROVE,
        Cap.PROBATION_READ, Cap.PROBATION_REVIEW, Cap.PROBATION_CONFIRM,
        Cap.INDUCTION_READ, Cap.INDUCTION_WRITE,
        Cap.EXCEPTION_READ, Cap.EXCEPTION_WRITE, Cap.EXCEPTION_APPROVE,
        Cap.PERSONNEL_FILE_CLOSE,
        # ── Phase INT-2 ── the MD holds every one of these, on the same reasoning as the
        # block above: a governance chain whose final authority cannot act is a trap. Two
        # of them are the MD's ALONE -- approving a policy revision and executing a
        # retention purge -- because both are irreversible statements about the company.
        Cap.SHORTLIST_READ, Cap.SHORTLIST_WRITE,
        Cap.PREBOARDING_READ, Cap.PREBOARDING_WRITE,
        Cap.SALARY_BAND_READ, Cap.SALARY_BAND_WRITE,
        Cap.COMM_READ, Cap.COMM_WRITE, Cap.COMM_TEMPLATE_WRITE,
        Cap.SURVEY_READ, Cap.SURVEY_WRITE,
        Cap.POLICY_READ, Cap.POLICY_WRITE, Cap.POLICY_APPROVE,
        Cap.RETENTION_PURGE,
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
        Cap.CLIENT_READ,
        Cap.SANCTION_READ, Cap.SANCTION_WRITE,
        # Deliberately NO REQUISITION_ESCALATE: the escalation ladder is the reporting
        # hierarchy above the raiser, and HR reviewing then also escalating would collapse
        # two stages into one person -- the same separation the HR/MD split already draws.
        # ── Internal track ── HR is "R" (responsible) on almost every line of Annexure B:
        # it drafts the scorecard, runs sourcing and screening, conducts the reference check,
        # releases the offer, runs induction and closes the personnel file.
        Cap.SCORECARD_READ, Cap.SCORECARD_WRITE,
        Cap.REFERENCE_READ, Cap.REFERENCE_WRITE,
        Cap.TELEPHONIC_READ, Cap.TELEPHONIC_WRITE,
        Cap.PROBATION_READ, Cap.PROBATION_REVIEW,
        Cap.INDUCTION_READ, Cap.INDUCTION_WRITE,
        Cap.EXCEPTION_READ, Cap.EXCEPTION_WRITE,
        Cap.PERSONNEL_FILE_CLOSE,
        # Deliberately ABSENT, and each for a reason the RACI states outright:
        #   REQUISITION_APPROVE_BUDGET -- Annexure B gives HR "C" on budget, Management "A".
        #   SCORECARD_APPROVE          -- HR drafts ("R"), the HOD approves ("A").
        #   OFFER_APPROVE              -- HR verifies budget compliance, Management approves.
        #   PROBATION_CONFIRM          -- HR recommends ("C"), the HOD confirms ("A/R").
        #   EXCEPTION_APPROVE          -- HR may raise one, Management/Finance approves it.
        # Every one of those is the same separation-of-duties the HR/MD split already draws.
        #
        # ── Phase INT-2 ── HR is "R" on every one of these lines too: it convenes the
        # shortlisting committee, runs pre-boarding engagement, sends candidate
        # communications, administers the surveys and maintains the policy register.
        Cap.SHORTLIST_READ, Cap.SHORTLIST_WRITE,
        Cap.PREBOARDING_READ, Cap.PREBOARDING_WRITE,
        Cap.COMM_READ, Cap.COMM_WRITE,
        Cap.SURVEY_READ, Cap.SURVEY_WRITE,
        Cap.POLICY_READ, Cap.POLICY_WRITE,
        # READ, not write: the band master is agreed annually WITH Finance (Annexure C), so
        # HR reads what was agreed and the budget gate pre-fills from it. HR rewriting the
        # band would make the annual agreement a suggestion.
        Cap.SALARY_BAND_READ,
        # Deliberately ABSENT, each for the reason the block above states:
        #   SALARY_BAND_WRITE   -- Finance and the MD agree the bands.
        #   COMM_TEMPLATE_WRITE -- the templates carry the EEO and data-use wording.
        #   POLICY_APPROVE      -- HR drafts a revision; the MD makes it the one in force.
        #   RETENTION_PURGE     -- destroying records is not an operational act.
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
        # ── Internal track ── the HOD is "A" on the scorecard, the shortlist, the panel
        # interview and probation confirmation (Annexure B), so those are approvals here.
        # Budget is NOT theirs: Annexure B gives the HOD "C" on headcount and budget.
        Cap.SCORECARD_READ, Cap.SCORECARD_APPROVE,
        Cap.REFERENCE_READ,
        # "I" on telephonic screening (Annexure B) -- the HOD interviews off the back of
        # the call, so they read it; recording one is HR's act alone.
        Cap.TELEPHONIC_READ,
        Cap.PROBATION_READ, Cap.PROBATION_REVIEW, Cap.PROBATION_CONFIRM,
        Cap.INDUCTION_READ,
        # May RAISE an exception, never approve one -- Annexure B puts exception approval
        # with Management/Finance.
        Cap.EXCEPTION_READ, Cap.EXCEPTION_WRITE,
        # ── Phase INT-2 ── the HOD SITS on the shortlisting committee (SOP §5 requires HR
        # AND the HOD), so this is a write, not a read. Everything else is read: the HOD is
        # informed about pre-boarding and the policy register, and sees survey scores for
        # their own team through the same row scoping the candidate list applies.
        Cap.SHORTLIST_READ, Cap.SHORTLIST_WRITE,
        Cap.PREBOARDING_READ,
        Cap.SURVEY_READ,
        Cap.POLICY_READ,
    },
    # Self-service, plus the deliberate exception that ANY employee may raise a hiring
    # requisition (FRONTEND_ANALYSIS §5: "anyone may raise a hiring requisition"). Reading
    # your OWN profile is not a capability -- it is an inherent right handled in the route,
    # so it can never be revoked by a permission edit.
    HrmsRole.EMPLOYEE: {
        Cap.MODULE_ACCESS,
        Cap.REQUISITION_READ, Cap.REQUISITION_CREATE, Cap.JD_READ,
        Cap.INTERVIEW_EVALUATE,
        # ── Phase INT-2 ── the recruitment policy is the one document in this module every
        # employee is entitled to read; SOP §14 exists to keep it current and visible. It is
        # the register, not the workflow -- no write of any kind comes with it.
        Cap.POLICY_READ,
    },
    # ── A user of a CLIENT ORGANISATION ──
    #
    # DELIBERATELY MINIMAL, and it will stay that way until the phase that secures each
    # surface lands. This set is the floor a client user needs to open the module and see
    # that their requisitions exist; it is NOT the eventual client permission model.
    #
    # Everything else is absent ON PURPOSE, because the row-level client scope that would
    # make it safe does not exist yet:
    #   CANDIDATE_READ   -- candidates carry no client scope (Phase: candidate isolation)
    #   DOCUMENT_READ    -- CVs carry no client scope (Phase: document security)
    #   INTERVIEW_*      -- (Phase: interview / client review)
    #   ANALYTICS_READ   -- the client_id filter is caller-supplied and unvalidated
    # Granting any of them now would hand a client user every OTHER client's data, because
    # the services narrow by company and manager-ownership only. The capability is not the
    # missing piece; the scope is.
    #
    # Future capabilities this role will need, named here so the gap is documented rather
    # than shipped as dead permissions (see §14 of the phase brief):
    #   client.requisition.read / write, client.candidate.read / review,
    #   client.interview.read / feedback, client.hiring_decision.write,
    #   client.dashboard.read
    HrmsRole.CLIENT: {
        Cap.MODULE_ACCESS,
        # Their OWN requisitions only. The client narrowing that makes this true is applied
        # by the requisition service in a later phase; until then a CLIENT user sees the
        # tenant's requisitions, which is why no client user should be provisioned yet.
        Cap.REQUISITION_READ,
        # Needed to render their own client's name. Reading the client LIST is a separate
        # concern already gated by CLIENT_READ; narrowing that list is a later phase.
        Cap.CLIENT_READ,
    },
    # ── Internal track ── the budget authority, and nothing else.
    #
    # Annexure B gives Management/Finance "A" on exactly five lines: headcount & budget
    # approval, salary negotiation, offer approval, exception approval, and KPI reporting.
    # This set is those five plus the reads needed to make them informed decisions.
    #
    # What is deliberately ABSENT is the whole hiring judgement: no CANDIDATE_SCREEN, no
    # INTERVIEW_EVALUATE, no OFFER_WRITE, no PROBATION_CONFIRM. Finance approves what a role
    # COSTS; it never decides who fills it. Nor does it hold MODULE_ADMIN.
    HrmsRole.FINANCE: {
        Cap.MODULE_ACCESS,
        # Enough context to judge a budget request: the requisition, its position, the
        # sanctioned headcount it is drawn against, and the analytics behind "KPI /
        # dashboard reporting", which Annexure B makes Management/Finance accountable for.
        Cap.REQUISITION_READ, Cap.JD_READ,
        Cap.SANCTION_READ,
        Cap.EMPLOYEE_READ,
        Cap.ANALYTICS_READ, Cap.REPORT_READ, Cap.REPORT_EXPORT,
        # Salary visibility WITHOUT salary write: approving a band requires seeing what the
        # company already pays, but the payroll record itself stays HR's and MD's.
        Cap.EMPLOYEE_SALARY_READ,
        # The two mandatory gates, and the offer read that makes the second one meaningful.
        Cap.REQUISITION_APPROVE_BUDGET,
        Cap.OFFER_READ, Cap.OFFER_APPROVE,
        Cap.SCORECARD_READ,
        Cap.EXCEPTION_READ, Cap.EXCEPTION_APPROVE,
        # ── Phase INT-2 ── the standing salary bands are Finance's own artifact: Annexure C
        # asks Finance to agree them annually so an individual requisition does not need a
        # fresh budget conversation. Reading the survey scores follows the same line as
        # ANALYTICS_READ -- Annexure B makes Management/Finance accountable for KPI
        # reporting, and new-hire satisfaction is one of the eight KPIs.
        Cap.SALARY_BAND_READ, Cap.SALARY_BAND_WRITE,
        Cap.SURVEY_READ,
        Cap.POLICY_READ,
        # Deliberately ABSENT: SHORTLIST_* and PREBOARDING_*. Both are about WHO fills a
        # role and whether they still want it -- the hiring judgement Finance never holds.
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
    # No "client" sequence: a client is a company and already has an id.
    # ── Internal recruitment track ──
    "scorecard":   ("SCR",    True,  3),   # SCR-2026-001
    "reference":   ("REF",    True,  3),   # REF-2026-001
    "telephonic":  ("TEL",    True,  3),   # TEL-2026-001
    "probation":   ("PRB",    True,  3),   # PRB-2026-001
    "exception":   ("EXC",    True,  3),   # EXC-2026-001
    # ── Client engagements ──
    "engagement":  ("CLI-ENG", True, 3),   # CLI-ENG-2026-001
    # ── Phase INT-2 ──
    "shortlist":   ("SLR",    True,  3),   # SLR-2026-001  shortlisting committee record
    "preboarding": ("PBT",    True,  3),   # PBT-2026-001  pre-boarding touchpoint
    "salary_band": ("SAL",    True,  3),   # SAL-2026-001  standing band
    "survey":      ("SRV",    True,  3),   # SRV-2026-001  survey instrument
    "survey_response": ("SRP", True, 3),   # SRP-2026-001  one submission
    "purge_batch": ("PRG",    True,  3),   # PRG-2026-001  a retention purge proposal
    # No "policy" sequence: a policy is addressed by its `policy_key` (internal_recruitment,
    # profit_recruitment), which is stable across versions in a way a minted number is not.
    # No "comm_log" sequence either: the log is append-only volume, and a business id on
    # every email would burn a counter for a record nobody ever cites by number.
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

    # ── Client scope ──
    # Pydantic DROPS undeclared fields on a response_model, so anything the frontend gates
    # on has to be declared here. The same omission has bitten UserResponse twice.
    #
    # `is_client_user` and `allowed_client_ids` are the SERVER's answer, resolved from the
    # engagement records. The frontend renders from them; it never derives them, and a
    # client id it sends back is never an authorisation input.
    is_client_user: bool = False
    # None  -> not client-scoped (a Sparsh user); no client filter applies.
    # []    -> client-scoped with no valid membership; everything must fail closed.
    allowed_client_ids: Optional[List[str]] = None


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


# ── Seniority bands (Phase INT-2) ──
# The vocabulary the Internal Recruitment SOP states its interview rules in: who must sit on
# a panel (§5) and which roles need a final Management round before an offer (§5).
#
# Four values, deliberately closed. "Senior" and "managerial" differ in kind rather than
# degree -- a senior individual contributor and a manager need the same panel but are not the
# same thing -- so collapsing them would lose a distinction the org chart cares about even
# though these two rules happen to treat them alike.
class DesignationLevel(str, Enum):
    JUNIOR     = "junior"
    MID        = "mid"
    SENIOR     = "senior"
    MANAGERIAL = "managerial"


# The DEFAULT for a designation that has never been banded. `mid` rather than `junior`,
# because the whole point is that existing rows stay valid AND keep a real panel requirement:
# defaulting to junior would be the same table but would read as a deliberate "this is a
# junior role", which nobody decided.
DEFAULT_DESIGNATION_LEVEL = DesignationLevel.MID

# Levels the SOP treats as "managerial and above": a mandatory Management final round before
# the offer stage, and Management on the interview panel. Named once so the final-round gate
# and the panel table cannot disagree about which roles they cover.
MANAGERIAL_LEVELS = {DesignationLevel.SENIOR, DesignationLevel.MANAGERIAL}


def designation_level(designation: Optional[dict]) -> DesignationLevel:
    """The seniority band of a designation row. Pure -- no DB, no clock.

    An absent, empty or unrecognised value reads as the default rather than raising: a
    designation created before this phase has no band, and refusing to schedule an interview
    because of that would break hiring to enforce a field nobody has filled in yet.
    """
    raw = (designation or {}).get("designation_level")
    try:
        return DesignationLevel(raw)
    except (ValueError, TypeError):
        return DEFAULT_DESIGNATION_LEVEL


def is_managerial_level(level) -> bool:
    """Whether a seniority band counts as managerial-and-above for the SOP's §5 rules."""
    try:
        return DesignationLevel(getattr(level, "value", level)) in MANAGERIAL_LEVELS
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
    # ── Phase INT-2 ── the SENIORITY BAND, which is what the SOP's panel-composition and
    # final-round rules are stated in terms of (SOP §5). Deliberately NOT folded into
    # `level` above: that field is an integer grade a company numbers however it likes, and
    # overloading it with four fixed strings would break every row that already has one.
    # Absent reads as `mid` -- see designation_level().
    designation_level: Optional[DesignationLevel] = None


class DesignationUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    level: Optional[int] = None
    active: Optional[bool] = None
    designation_level: Optional[DesignationLevel] = None


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

class RequisitionTrack(str, Enum):
    """Whose vacancy this is, and therefore whose money and whose rules.

    CLIENT   -> the recruitment-agency model the module was built for. A client company owns
                the budget, CVs are shared with them for a verdict, and they issue the offer.
    INTERNAL -> Sparsh Magic hiring for itself, governed by the Internal Recruitment SOP.
                There is NO client: headcount, salary band and budget are approved internally
                by Management/Finance and HR issues the offer directly.

    Defaults to CLIENT, so every requisition raised before this phase keeps its exact
    behaviour, and IMMUTABLE after creation -- changing the track mid-flight would invalidate
    an approval already granted under different rules.
    """
    CLIENT   = "client"
    INTERNAL = "internal"


class ReqApproval(str, Enum):
    """The approval machine. A requisition and its JD move through ONE unified chain -- the
    source's separate JD approval was removed and the JD is co-approved at the MD stage
    (BACKEND_ANALYSIS 6.7).

    TWO chains share these states, selected by `requisition_track`:

      client   : Pending HR Review -> [Pending Escalation] -> Pending MD Approval -> Approved
      internal : Pending HR Verification -> Pending Budget Approval
                 -> [Pending Escalation] -> Pending Scorecard Approval -> Approved

    The internal chain inserts a MANDATORY budget gate before anything may be sourced (SOP
    §11), and ends on the position scorecard rather than a single MD sign-off. The client
    chain's states are untouched, so no existing requisition changes meaning.
    """
    PENDING_HR = "Pending HR Review"
    # Phase 11-R, Item 7: an OVER-SANCTION requisition is routed through the raiser's
    # reporting line before it reaches the MD. An in-sanction requisition never enters this
    # state, so the existing three-step chain is completely unchanged for it.
    # Shared by both tracks -- the ladder does not care whose budget it is.
    PENDING_ESCALATION = "Pending Escalation"
    PENDING_MD = "Pending MD Approval"
    APPROVED   = "Approved"
    REJECTED   = "Rejected"
    # ── Internal track only ──
    # Named "Verification" rather than "Review" because the SOP's step is a check that the
    # requisition is complete and justified, not the headcount judgement -- that is the next
    # state, and it is Management's.
    PENDING_HR_VERIFICATION = "Pending HR Verification"
    PENDING_BUDGET          = "Pending Budget Approval"
    PENDING_SCORECARD       = "Pending Scorecard Approval"


# The states each track may legally occupy. A requisition that somehow holds a state from the
# other track's chain is a bug, and these sets are what make that assertable.
TRACK_APPROVAL_STATES = {
    RequisitionTrack.CLIENT: {
        ReqApproval.PENDING_HR, ReqApproval.PENDING_ESCALATION, ReqApproval.PENDING_MD,
        ReqApproval.APPROVED, ReqApproval.REJECTED,
    },
    RequisitionTrack.INTERNAL: {
        ReqApproval.PENDING_HR_VERIFICATION, ReqApproval.PENDING_BUDGET,
        ReqApproval.PENDING_ESCALATION, ReqApproval.PENDING_SCORECARD,
        ReqApproval.APPROVED, ReqApproval.REJECTED,
    },
}

# Approval states in which an internal requisition has NOT yet cleared its budget gate.
# Sourcing of any kind -- publishing a posting, creating a candidate -- is refused while a
# requisition sits in one of these. Declared once here so the posting service and the
# candidate service cannot drift apart on what "before budget approval" means.
PRE_BUDGET_STATES = {
    ReqApproval.PENDING_HR_VERIFICATION.value,
    ReqApproval.PENDING_BUDGET.value,
}


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


# ── Internal track: a SECOND table, not a branch inside the first ──
#
# The client table above is left byte-for-byte alone, which is what makes "the agency track
# is unchanged" a fact rather than a hope: `md_approval_is_mandatory()` still inspects it and
# still finds exactly one road to APPROVED.
#
# The internal chain differs in two ways the SOP requires:
#   * a MANDATORY budget gate before anything may be sourced (SOP §11), and
#   * the chain ends on the position SCORECARD rather than a single MD sign-off, because
#     Annexure B makes the HOD accountable for the scorecard and Management accountable for
#     the budget -- two different people, two different gates.
#
# The over-sanction detour hangs off `budget-approve` here rather than `hr-verify`: there is
# no point asking a reporting line to justify extra headcount before anyone has agreed to
# pay for it.
INTERNAL_REQ_TRANSITIONS = {
    "hr-verify":         (ReqApproval.PENDING_HR_VERIFICATION, ReqApproval.PENDING_BUDGET,
                          Cap.REQUISITION_REVIEW_HR, False),
    "hr-reject":         (ReqApproval.PENDING_HR_VERIFICATION, ReqApproval.REJECTED,
                          Cap.REQUISITION_REVIEW_HR, True),
    "budget-approve":    (ReqApproval.PENDING_BUDGET, ReqApproval.PENDING_SCORECARD,
                          Cap.REQUISITION_APPROVE_BUDGET, False),
    "budget-reject":     (ReqApproval.PENDING_BUDGET, ReqApproval.REJECTED,
                          Cap.REQUISITION_APPROVE_BUDGET, True),
    # Same ladder, same capability, same cap on depth -- it simply returns to the scorecard
    # gate instead of to the MD.
    "escalate-approve":  (ReqApproval.PENDING_ESCALATION, ReqApproval.PENDING_SCORECARD,
                          Cap.REQUISITION_ESCALATE, False),
    "escalate-reject":   (ReqApproval.PENDING_ESCALATION, ReqApproval.REJECTED,
                          Cap.REQUISITION_ESCALATE, True),
    "scorecard-approve": (ReqApproval.PENDING_SCORECARD, ReqApproval.APPROVED,
                          Cap.SCORECARD_APPROVE, False),
    "scorecard-reject":  (ReqApproval.PENDING_SCORECARD, ReqApproval.REJECTED,
                          Cap.SCORECARD_APPROVE, True),
}

INTERNAL_ESCALATION_ROUTING = {"budget-approve": ReqApproval.PENDING_ESCALATION}

# Which table drives which track. The service looks the pair up rather than branching on the
# track in four places, so adding a third track later is a table, not a rewrite.
TRACK_TRANSITIONS = {
    RequisitionTrack.CLIENT:   (REQ_TRANSITIONS, REQ_ESCALATION_ROUTING),
    RequisitionTrack.INTERNAL: (INTERNAL_REQ_TRANSITIONS, INTERNAL_ESCALATION_ROUTING),
}


def budget_approval_is_mandatory() -> bool:
    """The internal-track twin of `md_approval_is_mandatory`, asserted from the table.

    "No internal role may be sourced without prior written headcount and budget approval"
    (SOP §11) holds exactly while: PENDING_BUDGET is on the ONLY road out of HR verification,
    the single action that leaves it forward demands REQUISITION_APPROVE_BUDGET, and APPROVED
    is unreachable without passing through it.

    A later shortcut -- an `hr-verify` that lands straight on PENDING_SCORECARD, say -- would
    silently delete the gate. This is what the test asserts, so that change fails loudly.
    """
    forward = [spec for action, spec in INTERNAL_REQ_TRANSITIONS.items()
               if spec[0] is ReqApproval.PENDING_BUDGET
               and spec[1] is not ReqApproval.REJECTED]
    if not (len(forward) == 1 and forward[0][2] is Cap.REQUISITION_APPROVE_BUDGET):
        return False
    # Nothing may reach APPROVED except through the scorecard gate, which itself is only
    # reachable from the budget gate or the escalation ladder that follows it.
    approved_from = {spec[0] for spec in INTERNAL_REQ_TRANSITIONS.values()
                     if spec[1] is ReqApproval.APPROVED}
    if approved_from != {ReqApproval.PENDING_SCORECARD}:
        return False
    scorecard_from = {spec[0] for spec in INTERNAL_REQ_TRANSITIONS.values()
                      if spec[1] is ReqApproval.PENDING_SCORECARD}
    return scorecard_from == {ReqApproval.PENDING_BUDGET, ReqApproval.PENDING_ESCALATION}

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

AUDIT_REQ_HR_VERIFIED  = "requisition HR-verified (internal)"
AUDIT_REQ_BUDGET_OK    = "requisition budget approved (internal)"
AUDIT_REQ_BUDGET_NO    = "requisition rejected at budget (internal)"
AUDIT_REQ_SCORECARD_OK = "requisition scorecard approved (internal)"
AUDIT_REQ_SCORECARD_NO = "requisition rejected at scorecard (internal)"

REQ_AUDIT_ACTIONS = {
    "hr-approve": AUDIT_REQ_HR_APPROVED,
    "hr-reject":  AUDIT_REQ_HR_REJECTED,
    "md-approve": AUDIT_REQ_MD_APPROVED,
    "md-reject":  AUDIT_REQ_MD_REJECTED,
    "escalate-approve": AUDIT_REQ_ESC_APPROVED,
    "escalate-reject":  AUDIT_REQ_ESC_REJECTED,
    # ── Internal track ──
    "hr-verify":         AUDIT_REQ_HR_VERIFIED,
    "budget-approve":    AUDIT_REQ_BUDGET_OK,
    "budget-reject":     AUDIT_REQ_BUDGET_NO,
    "scorecard-approve": AUDIT_REQ_SCORECARD_OK,
    "scorecard-reject":  AUDIT_REQ_SCORECARD_NO,
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

    # ── Which hiring track this vacancy runs on ──
    # Defaults to CLIENT so every existing caller is unchanged. INTERNAL is Sparsh Magic's
    # own vacancy: it may not name a client, and it enters the budget-gated chain instead of
    # the HR -> MD one. Immutable once raised.
    requisition_track: RequisitionTrack = RequisitionTrack.CLIENT

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
    # ── Internal track ── required by `budget-approve` and ignored by every other action.
    # Carried on the same body rather than on a parallel endpoint so the approval chain stays
    # ONE surface, which is what keeps the UI's ApprovalDialog reusable across both tracks.
    approved_headcount: Optional[int] = None
    approved_salary_band_min: Optional[float] = None
    approved_salary_band_max: Optional[float] = None


class RequisitionClose(BaseModel):
    status: ReqClosing


# =============================================================
# Phase 4 - Job Postings + Public Application Intake
# =============================================================

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
    # ── Phase INT-4 ── the SOP's step 5, "brief telephonic interview by HR", which sits
    # between CV screening and the panel. Two statuses rather than one, because the outcome
    # is the point: a phone screen nobody can see the result of is a call that may as well
    # not have happened.
    #
    # NOT a rejection reason on the candidate. TELEPHONIC_REJECTED is revivable (a candidate
    # who was unreachable on Tuesday is not permanently unsuitable), which a terminal
    # REJECTED is not.
    TELEPHONIC_PASSED    = "Telephonic Passed"
    TELEPHONIC_REJECTED  = "Telephonic Rejected"
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
class PostingIn(BaseModel):
    """Publish a JD. ONE posting, ONE link.

    There is deliberately no platform here. A posting used to be created once per job board,
    which meant one link per board and a `source` inferred from whichever URL the applicant
    happened to click -- an inference that was wrong the moment a link was forwarded. The
    single link is shared wherever the company likes, and the application form asks the
    applicant where they found the role. The answer is what fills `source`.
    """
    jd_no: str
    apply_link_mode: ApplyLinkMode = ApplyLinkMode.AUTO
    external_url: Optional[str] = None
    code: Optional[str] = None       # client-previewed code; honoured only if valid + unique
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

    # ── Phase INT-2 (SOP §11) ── the two acknowledgements the policy commits us to asking
    # for. BOTH are required on the internal track and stamped with a timestamp, because an
    # acknowledgement with no time on it cannot be tied to the wording that was shown. The
    # wording itself lives in hrms_comm_templates so legal can change it without a deploy.
    eeo_ack: bool = False
    data_use_ack: bool = False
    # ── Phase INT-2 (Annexure C talent pool) ── entirely optional, and OFF by default. A
    # candidate enters the pool only by ticking this; there is no path that opts them in
    # because somebody found their CV useful.
    consent_to_retain: bool = False


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
    # ── Phase INT-4 ── the telephonic edges are ADDED, not substituted. The direct
    # Shortlisted -> Assessment / Interview edges stay, so the client track (and an internal
    # role with an approved waiver) is never forced through a phone screen by the shape of
    # the graph. The SOP's ordering is enforced by `assert_telephonic_cleared` at interview
    # scheduling, where it can be waived by an approved exception -- a missing edge cannot.
    AppStatus.SHORTLISTED:          {AppStatus.ASSESSMENT_PENDING, AppStatus.INTERVIEW_SCHEDULED,
                                     AppStatus.SHARED_WITH_CLIENT,
                                     AppStatus.TELEPHONIC_PASSED,
                                     AppStatus.TELEPHONIC_REJECTED},
    # A passed phone screen leads where a shortlist does: the SOP puts the skill assessment
    # (Annexure B) between the call and the panel, so both onward edges exist.
    AppStatus.TELEPHONIC_PASSED:    {AppStatus.ASSESSMENT_PENDING, AppStatus.INTERVIEW_SCHEDULED,
                                     AppStatus.SHARED_WITH_CLIENT},
    # Revivable, exactly like CLIENT_REJECTED: somebody unreachable on Tuesday is not
    # permanently unsuitable, and a dead end here would force HR to re-key the candidate.
    AppStatus.TELEPHONIC_REJECTED:  {AppStatus.UNDER_REVIEW},
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
    # TELEPHONIC_PASSED sits here, with the rest of rank 2: the board column and the funnel
    # rank must agree, or a candidate appears in one place and is counted in another.
    ("shortlisted", "Shortlisted", [AppStatus.SHORTLISTED, AppStatus.SHARED_WITH_CLIENT,
                                    AppStatus.CLIENT_SHORTLISTED,
                                    AppStatus.TELEPHONIC_PASSED]),
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
    # TELEPHONIC_REJECTED groups with the other "declined at a stage" outcomes, exactly as
    # CLIENT_REJECTED does -- both rank 2 in the funnel and both read as a rejection here.
    ("rejected",    "Rejected",    [AppStatus.REJECTED, AppStatus.DUPLICATE,
                                    AppStatus.OFFER_DECLINED, AppStatus.CLIENT_REJECTED,
                                    AppStatus.TELEPHONIC_REJECTED]),
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
class PanelMemberIn(BaseModel):
    """One person on an interview panel (Phase INT-2, SOP §5).

    Separate from `interviewer_id`, which stays exactly what it always was: the person who
    OWNS the booking, gets the invite and may score it. The panel is who else is in the room,
    and it is what the composition rule is checked against.
    """
    user_id: str
    # ── SOP §11 conflict of interest ── a member marked `recused` may not submit a scorecard
    # (422 in hrms_interview_service). Declaring a conflict is not itself disqualifying;
    # standing down is what removes it.
    coi_declared: bool = False
    coi_relationship: Optional[str] = None
    recused: bool = False


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
    # ── Phase INT-2 ── optional here and REQUIRED by the internal track's composition
    # check, which is where the 422 comes from. Optional in the model so a client-track
    # booking is byte-for-byte the call it always was.
    panel: List[PanelMemberIn] = Field(default_factory=list)


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
    # ── Phase INT-2 ── the panel may change (somebody is away, a conflict is declared) and
    # the composition rule is re-checked on every change, so a panel cannot be edited down
    # below what the SOP requires after the booking is made.
    panel: Optional[List[PanelMemberIn]] = None


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

# The induction keys are declared beside INDUCTION_CHECKLIST, further down this file, so this
# list is completed there rather than here -- see `induction_checklist_keys()`.

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


def seed_checklist(track: str = None) -> list:
    """The checklist a new onboarding record starts with.

    An INTERNAL-track joiner additionally gets the Day-1 induction items (SOP §7). The base
    twelve are unchanged for everybody, so a client-track onboarding shows exactly the list
    it always has -- the induction items are appended, never interleaved, so the existing
    order is preserved too.
    """
    items = [{"key": k, "label": label, "done": False, "done_at": None, "done_by": None}
             for k, label in ONBOARD_CHECKLIST]
    if track == RequisitionTrack.INTERNAL.value:
        items += [{"key": k, "label": label, "done": False, "done_at": None,
                   "done_by": None, "induction": True}
                  for k, label in INDUCTION_CHECKLIST]
    return items


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
    # ── Phase INT-4 ── the telephonic band sits WITH Shortlisted, for exactly the reason the
    # client-share band does: a phone screen is a decision ABOUT a shortlisted candidate, not
    # a further stage of the funnel. Ranking it 3 would push assessment and interview up and
    # renumber every Phase 10 figure. TELEPHONIC_REJECTED is ranked where the candidate
    # ENTERED, the same treatment REJECTED and CLIENT_REJECTED get.
    AppStatus.TELEPHONIC_PASSED:    2,
    AppStatus.TELEPHONIC_REJECTED:  2,
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
            # ── Internal track ── empty on the client track, where no scorecard exists.
            ("scorecard_score", "Scorecard"), ("scorecard_band", "Band"),
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
    # ── Internal recruitment track ──
    # Both carry `request_no`, so the single analytics scope filter reaches them unchanged.
    #
    # `retention_until` is on both, per SOP §13. It is the date the record may be considered
    # for disposal, computed and stored when the record is written. NOTHING PURGES IT --
    # exposing the date on a report is the whole of what this phase does with retention.
    "probation": {
        "collection": COLL_PROBATION_REVIEWS,
        "date_field": "created_at",
        "search":     ["prb_no", "employee_code", "employee_name"],
        "columns": [
            ("prb_no", "Probation"), ("employee_code", "Employee"),
            ("employee_name", "Name"), ("request_no", "Requisition"),
            ("started_on", "Started"), ("duration_months", "Months"),
            ("ends_on", "Ends"), ("outcome", "Outcome"), ("rating", "Rating"),
            ("extension_count", "Extensions"),
            ("confirmed_by_name", "Decided by"), ("confirmed_at", "Decided on"),
            ("retention_until", "Keep until"), ("created_at", "Opened on"),
        ],
    },
    "exceptions": {
        "collection": COLL_EXCEPTIONS,
        "date_field": "created_at",
        "search":     ["exc_no", "request_no", "reason"],
        "columns": [
            ("exc_no", "Exception"), ("exception_type", "Type"),
            ("gate", "Lifts gate"), ("request_no", "Requisition"),
            ("uk", "Candidate"), ("candidate_name", "Candidate name"),
            ("status", "Status"), ("reason", "Reason"),
            ("raised_by_name", "Raised by"), ("raised_at", "Raised on"),
            ("approved_by_name", "Decided by"), ("approved_at", "Decided on"),
            ("decision_remarks", "Decision remarks"), ("created_at", "Logged on"),
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
    # A posting no longer carries a platform -- one posting, one link, shared anywhere. The
    # channel is `source`, answered by the applicant, so grouping by platform would only
    # ever count a field nothing writes.
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
    # ── Internal recruitment track ──
    PROBATION    = "probation"
    EXCEPTIONS   = "exceptions"


class BreakdownBy(str, Enum):
    SOURCE      = "source"
    DEPARTMENT  = "department"
    DESIGNATION = "designation"
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
    # ── Phase INT-2 ── the new-hire experience surveys (SOP §10). Registered like every
    # other public credential rather than inventing a second link mechanism, so revocation,
    # expiry and open-tracking all work on it for free.
    SURVEY      = "survey"


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
    LinkKind.SURVEY:      "/survey/{code}",
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
#
# Phase INT-2 adds a sixth column, `statutory_required` (SOP §11). It is NOT the same thing
# as `mandatory`: mandatory means "collect this", statutory_required means "probation cannot
# be CONFIRMED until this is Verified". A photograph is mandatory and is not a statutory
# check; a degree certificate is both. Defaults to False everywhere else, so a type HR added
# by hand never silently starts blocking confirmations.
# (name, category, applies_to, mandatory, expires, statutory_required)
DEFAULT_DOCUMENT_TYPES = [
    ("PAN Card",              DocumentCategory.IDENTITY,       "both",      True,  False, True),
    ("Aadhaar Card",          DocumentCategory.IDENTITY,       "both",      True,  False, True),
    ("Passport",              DocumentCategory.IDENTITY,       "both",      False, True,  False),
    ("Address Proof",         DocumentCategory.IDENTITY,       "both",      False, False, False),
    # Mandatory to collect, but nobody's employment turns on a photograph.
    ("Photograph",            DocumentCategory.IDENTITY,       "both",      True,  False, False),
    ("Degree Certificate",    DocumentCategory.EDUCATIONAL,    "both",      True,  False, True),
    ("Experience Letter",     DocumentCategory.EMPLOYMENT,     "both",      False, False, False),
    ("Relieving Letter",      DocumentCategory.EMPLOYMENT,     "both",      False, False, False),
    ("Last 3 Payslips",       DocumentCategory.EMPLOYMENT,     "candidate", False, False, False),
    ("Bank Proof",            DocumentCategory.STATUTORY,      "employee",  True,  False, False),
    ("Offer Letter Signed",   DocumentCategory.COMPANY_ISSUED, "candidate", False, False, False),
    ("Appointment Letter",    DocumentCategory.COMPANY_ISSUED, "candidate", False, False, False),
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
    # ── Phase INT-2 ── SOP §11: a document flagged here must be Verified before probation
    # can be confirmed. Defaults False so an existing type never starts gating by surprise.
    statutory_required: bool = False


class DocumentTypeUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    category: Optional[DocumentCategory] = None
    applies_to: Optional[str] = None
    mandatory: Optional[bool] = None
    expires: Optional[bool] = None
    active: Optional[bool] = None
    statutory_required: Optional[bool] = None


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

# A client is not created, updated or deleted here -- it is a company, and the Companies
# module audits its own writes. What HRMS does to a client is share a CV and record a verdict,
# so those are the only two actions this module has to account for.
AUDIT_CLIENT_SHARED    = "cv shared with client"
AUDIT_CLIENT_RESPONSE  = "client verdict recorded"

# ── Internal recruitment track ──
AUDIT_BUDGET_APPROVED    = "headcount and budget approved"
AUDIT_SCORECARD_CREATED  = "position scorecard drafted"
AUDIT_SCORECARD_UPDATED  = "position scorecard updated"
AUDIT_SCORECARD_APPROVED = "position scorecard approved"
AUDIT_SCORECARD_EVALUATED = "candidate scored against the position scorecard"
AUDIT_REFERENCE_RECORDED = "reference check recorded"
AUDIT_REFERENCE_UPDATED  = "reference check updated"
AUDIT_OFFER_APPROVED     = "offer approved"
AUDIT_PROBATION_STARTED  = "probation review opened"
AUDIT_PROBATION_UPDATED  = "probation review updated"
AUDIT_PROBATION_CONFIRMED = "probation outcome recorded"
AUDIT_EXCEPTION_RAISED   = "exception raised"
AUDIT_EXCEPTION_DECIDED  = "exception decided"
AUDIT_PERSONNEL_FILE_CLOSED = "personnel file closed"
AUDIT_SLA_BREACHED       = "sla target breached"

ENTITY_SCORECARD = "position_scorecard"
ENTITY_REFERENCE = "reference_check"
ENTITY_PROBATION = "probation_review"
ENTITY_EXCEPTION = "exception"


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


# =============================================================
# Internal (in-house) recruitment track
# =============================================================
# Sparsh Magic hiring for itself, governed by the Internal Recruitment Policy & SOP.
#
# Everything below is ADDITIVE. A client-track requisition never enters any of these states,
# never has a scorecard, and is never blocked by the budget or reference gates -- so the
# agency track behaves exactly as it did before this phase.
#
# Where the two tracks differ in KIND: on the client track the client owns the budget and the
# verdict, so the module's job is to route CVs and record answers. Here Sparsh Magic owns
# both, so the module's job is to enforce its own governance -- which is why this half of the
# module is mostly gates rather than pipeline.

# -- SLA / TAT (SOP §8) -------------------------------------------------------------
# (key, label, target in WORKING days, measured from)
#
# `measured_from` names the milestone the clock starts at, so the table reads as the chain it
# is rather than four independent deadlines. None means "from the requisition itself".
#
# Working days exclude Saturday and Sunday. Public holidays are NOT excluded in this phase.
# The ERP has a holidays master (app/models/holiday.py) and honouring it is a small change,
# but doing it silently would make two companies with different holiday lists disagree about
# whether the same requisition breached -- a decision to take deliberately, not by default.
# Phase INT-2 completes the table. SOP §8 has SIX milestones and two of them are measured
# against a stored DATE rather than a preceding milestone, so the table carries an explicit
# `anchor` discriminator and stays declarative -- one table, two evaluators, no branching in
# the sweep. `sweep_open_breaches()` therefore picks the new rows up with no new sweep code.
#
#   anchor="milestone"  target_days working days after `measured_from` (None = the
#                       requisition itself). Evaluated by hrms_sla_service._status.
#   anchor="date"       due ON a date the record carries; `source` names which record and
#                       which field. `target_days` is null because there is no elapsed-time
#                       target to state, and reporting one would invent a number.
ANCHOR_MILESTONE = "milestone"
ANCHOR_DATE      = "date"

SLA_MILESTONES = [
    {"key": "budget_approved",    "label": "Budget / headcount approved",
     "anchor": ANCHOR_MILESTONE,  "target_days": 3,  "measured_from": None},
    {"key": "scorecard_approved", "label": "Position scorecard approved",
     "anchor": ANCHOR_MILESTONE,  "target_days": 2,  "measured_from": "budget_approved"},
    {"key": "shortlist_ready",    "label": "Shortlist ready for HOD review",
     "anchor": ANCHOR_MILESTONE,  "target_days": 15, "measured_from": None},
    {"key": "offer_released",     "label": "Offer released after selection",
     "anchor": ANCHOR_MILESTONE,  "target_days": 3,  "measured_from": "final_selection"},
    # ── The two date-anchored ones (Phase INT-2) ──
    # `collection` and `due_field` name where the date lives; `done` is how the service
    # decides the obligation was met. Both are per-RECORD, so one requisition with three
    # joiners reports three induction rows -- an aggregate "induction done" would hide the
    # one person nobody inducted.
    {"key": "induction_due",         "label": "Induction completed (Day 1)",
     "anchor": ANCHOR_DATE,          "target_days": None,
     "measured_from": "joining date (Day 1)",
     "collection": COLL_ONBOARDING,  "due_field": "joining_date", "id_field": "onb_no",
     "name_field": "candidate_name"},
    {"key": "probation_review_due",  "label": "Probation review before the end date",
     "anchor": ANCHOR_DATE,          "target_days": None,
     "measured_from": "probation end date",
     "collection": COLL_PROBATION_REVIEWS, "due_field": "ends_on", "id_field": "prb_no",
     "name_field": "employee_name"},
]

# The milestone keys a service may stamp. Only the milestone-anchored ones are stampable:
# a date-anchored row has nothing to stamp, its due date IS the record's own field.
STAMPABLE_MILESTONES = {m["key"] for m in SLA_MILESTONES
                        if m["anchor"] == ANCHOR_MILESTONE}


def sla_milestone(key: str) -> Optional[dict]:
    """One row of the SLA table by key, or None. Pure."""
    return next((m for m in SLA_MILESTONES if m["key"] == key), None)

# -- Record retention (SOP §13) -----------------------------------------------------
# Years to keep each record type. THIS PHASE COMPUTES AND STORES `retention_until` AND
# EXPOSES IT ON REPORTS. IT DOES NOT PURGE. There is deliberately no deletion job: an
# automated purge of employment records is a decision for the business and its auditors, not
# a side effect of a feature phase.
RETENTION_YEARS = {
    "requisition":          3,   # from requisition closure
    "candidate_selected":   3,   # from joining, then it lives on in the personnel file
    "candidate_unselected": 1,   # then securely purged -- manually, for now
    "offer":                3,   # employment + 3
    "reference":            3,   # employment + 3
    # A phone screen is candidate data, so it follows the CANDIDATE, not the employee: one
    # year for somebody who was not hired. A record of a call is not worth keeping for three
    # years about a person who never joined.
    "telephonic":           1,
    "probation":            3,   # employment + 3
}


class ScorecardCategory(str, Enum):
    SKILL       = "skill"
    EXPERIENCE  = "experience"
    CULTURE_FIT = "culture_fit"


class ScorecardStatus(str, Enum):
    DRAFT            = "Draft"
    PENDING_APPROVAL = "Pending Approval"
    APPROVED         = "Approved"
    REJECTED         = "Rejected"


# The scoring decision guide. BOTH SOPs (Internal §5 and Part A §13) define FOUR bands, not
# three. The band is SURFACED, never auto-applied -- HR still decides, because a rubric that
# silently rejects people is one nobody will trust or correct.
#
#   >= 4.0        Strong      recommend
#   3.5 - 3.9     Consider    proceed with a second opinion
#   3.0 - 3.4     Hold        park; do not progress on this evidence alone
#   <  3.0        Reject
#
# Declared as an ordered floor table rather than a chain of ifs, so the boundaries are
# readable in one place and a test can walk them. The order matters: the FIRST floor a score
# clears wins, so the list runs highest to lowest.
SCORE_STRONG_AT    = 4.0
SCORE_CONSIDER_AT  = 3.5
SCORE_HOLD_AT      = 3.0
SCORE_REJECT_BELOW = 3.0     # kept: the offer/probation copy still cites "below 3.0"
SCORE_MIN = 1
SCORE_MAX = 5

SCORE_BANDS = [
    (SCORE_STRONG_AT,   "Strong"),
    (SCORE_CONSIDER_AT, "Consider"),
    (SCORE_HOLD_AT,     "Hold"),
]
SCORE_BAND_REJECT = "Reject"

# Every band, in descending order, for a UI that renders the guide beside the score. The
# label is the SAME string score_band() returns, so a legend can never drift from a result.
SCORE_BAND_GUIDE = [
    {"band": "Strong",   "from": SCORE_STRONG_AT,   "to": None,  "advice": "Recommend."},
    {"band": "Consider", "from": SCORE_CONSIDER_AT, "to": 3.9,
     "advice": "Proceed, with a second opinion."},
    {"band": "Hold",     "from": SCORE_HOLD_AT,     "to": 3.4,
     "advice": "Park. Do not progress on this evidence alone."},
    {"band": SCORE_BAND_REJECT, "from": None,       "to": 2.99, "advice": "Do not proceed."},
]


def score_band(weighted: Optional[float]) -> Optional[str]:
    """Strong / Consider / Hold / Reject for a weighted 1-5 score, or None if unscored.

    Read from SCORE_BANDS rather than branched, so the four boundaries live in one table the
    tests walk directly. Anything below the lowest floor is Reject.
    """
    if weighted is None:
        return None
    try:
        value = float(weighted)
    except (TypeError, ValueError):
        return None
    for floor, label in SCORE_BANDS:
        if value >= floor:
            return label
    return SCORE_BAND_REJECT


class ReferenceMode(str, Enum):
    PHONE     = "Phone"
    EMAIL     = "Email"
    LETTER    = "Letter"
    IN_PERSON = "In Person"


class ReferenceOutcome(str, Enum):
    POSITIVE         = "Positive"
    NEGATIVE         = "Negative"
    UNABLE_TO_VERIFY = "Unable to Verify"


# What opens the offer gate. An "Unable to Verify" reference is completed WORK but not a
# clearance, so it does not open it -- an exception must be logged instead, which is exactly
# the trail the SOP asks for.
REFERENCE_CLEARS_OFFER = {ReferenceOutcome.POSITIVE.value}


# -- Phase INT-4  The telephonic screen (SOP step 5, Annexure B "Telephonic screening") -----
class TelephonicOutcome(str, Enum):
    PASSED   = "Passed"
    REJECTED = "Rejected"
    # A call that did not happen is not a verdict. Without this, an unreachable candidate
    # forces HR to choose between recording a rejection they did not decide and recording
    # nothing at all -- and "nothing at all" is what makes a pipeline look stalled for no
    # visible reason.
    NO_ANSWER = "No Answer"


# What opens the interview gate. `No Answer` is an outcome, not a clearance -- the same
# distinction REFERENCE_CLEARS_OFFER draws for "Unable to Verify".
TELEPHONIC_CLEARS_INTERVIEW = {TelephonicOutcome.PASSED.value}

# Which candidate status each outcome moves to. Declared as data so the mapping is readable
# in one place; `No Answer` deliberately maps to NOTHING, because a call nobody answered has
# not decided anything about the candidate and must not move them.
TELEPHONIC_STATUS_FOR_OUTCOME = {
    TelephonicOutcome.PASSED.value:   AppStatus.TELEPHONIC_PASSED,
    TelephonicOutcome.REJECTED.value: AppStatus.TELEPHONIC_REJECTED,
    TelephonicOutcome.NO_ANSWER.value: None,
}

# The rated dimensions, and their weights in the overall score.
#
# Weighted rather than a flat average, and declared as a table: SOP step 5 calls this a
# screen for suitability, so how well somebody understands the role they applied for counts
# for more than how motivated they sound. Ratings run 1-5 and band through the SAME
# `score_band()` the position scorecard uses -- two scoring vocabularies in one recruitment
# process is how a "3" comes to mean two different things.
TELEPHONIC_CRITERIA = [
    ("communication",     "Communication",      0.30),
    ("role_understanding", "Role understanding", 0.30),
    ("motivation",        "Motivation",         0.20),
    ("suitability",       "Initial suitability", 0.20),
]

TELEPHONIC_RATING_MIN = 1
TELEPHONIC_RATING_MAX = 5

AUDIT_TELEPHONIC_RECORDED = "telephonic screening recorded"
AUDIT_TELEPHONIC_UPDATED  = "telephonic screening updated"
ENTITY_TELEPHONIC = "telephonic_screening"


class ProbationOutcome(str, Enum):
    PENDING    = "Pending"
    CONFIRMED  = "Confirmed"
    EXTENDED   = "Extended"
    TERMINATED = "Terminated"


# SOP §7: "typically 3-6 months, per employment terms". The default is the top of that range,
# and every probation record carries its own duration -- so a shorter term is data, not code.
DEFAULT_PROBATION_MONTHS = 6
MIN_PROBATION_MONTHS = 1
MAX_PROBATION_MONTHS = 12


class ExceptionType(str, Enum):
    EXTENDED_TAT         = "Extended TAT"
    RELAXED_SCORECARD    = "Relaxed Scorecard"
    OFFER_OUTSIDE_BUDGET = "Offer Outside Budget"
    REFERENCE_WAIVED     = "Reference Check Waived"
    # ── Phase INT-2 ── SOP §11 requires statutory pre-employment checks to clear before
    # confirmation. Like every other gate on this track, the ONLY way past it is an approved
    # exception -- confirming somebody whose background check is still open is a decision a
    # company may need to take, and it must be one somebody signed.
    STATUTORY_WAIVED     = "Statutory Check Waived"
    # ── Phase INT-4 ── SOP step 5 puts a telephonic screen before the panel. Skipping it
    # is a real decision (an internal referral everybody has already met, an urgent
    # backfill), and like every other deviation on this track it must be one somebody
    # signed rather than a flag on a request body.
    TELEPHONIC_WAIVED    = "Telephonic Screening Waived"
    OTHER                = "Other"


class ExceptionStatus(str, Enum):
    PENDING  = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


# Which exception type unblocks which gate. Services look the gate up here rather than
# accepting an override flag on the request body: an approved, attributable record is the
# only thing that may bypass a control, and a boolean in a payload is neither.
EXCEPTION_UNBLOCKS = {
    "reference_check": ExceptionType.REFERENCE_WAIVED.value,
    "salary_band":     ExceptionType.OFFER_OUTSIDE_BUDGET.value,
    "scorecard":       ExceptionType.RELAXED_SCORECARD.value,
    "sla":             ExceptionType.EXTENDED_TAT.value,
    # ── Phase INT-2 ──
    # The statutory pre-employment gate on probation confirmation (SOP §11).
    "statutory_check": ExceptionType.STATUTORY_WAIVED.value,
    # The shortlisting-committee gate on `Selected` (SOP §5). It shares RELAXED_SCORECARD
    # rather than getting a type of its own, because that IS the deviation being approved:
    # progressing somebody the committee has not signed off is relaxing the selection
    # criteria, and the SOP names exactly one exception type for that.
    "shortlist":       ExceptionType.RELAXED_SCORECARD.value,
    # ── Phase INT-4 ── the telephonic gate on interview scheduling (SOP step 5).
    "telephonic":      ExceptionType.TELEPHONIC_WAIVED.value,
}


def gates_for_exception_type(exception_type: str) -> list:
    """Every gate one exception type lifts, in table order.

    A plain inverted dict was fine while the map was one-to-one. It is not any more:
    `Relaxed Scorecard` lifts BOTH the scorecard gate and the shortlisting-committee gate,
    and inverting would silently keep whichever happened to be declared last. Returning the
    list makes the fan-out visible instead of arbitrary; the FIRST entry stays the primary
    label, so an existing record's `gate` field reads exactly as it did before.
    """
    return [gate for gate, value in EXCEPTION_UNBLOCKS.items() if value == exception_type]

# Day-1 induction checklist (SOP §7). Same mechanism as ONBOARD_CHECKLIST, appended to an
# onboarding record on the INTERNAL track only -- a client-track onboarding still shows
# exactly the twelve items it always has.
INDUCTION_CHECKLIST = [
    ("induction_policies",      "Company policies walked through"),
    ("induction_systems",       "Systems and access set up"),
    ("induction_introductions", "Team introductions completed"),
    ("induction_workplace",     "Workplace orientation completed"),
    ("induction_feedback",      "New-hire induction feedback collected"),
]


# -- API models ---------------------------------------------------------------------
class BudgetApprovalIn(BaseModel):
    """Clear the mandatory budget gate on an internal requisition.

    The band is REQUIRED, not optional: the point of the gate is that a figure was authorised
    BEFORE sourcing began, and an approval carrying no number would leave the later offer
    check with nothing to validate against.
    """
    approved_headcount: int
    approved_salary_band_min: float
    approved_salary_band_max: float
    remarks: Optional[str] = None


class ScorecardCriterionIn(BaseModel):
    label: str
    category: ScorecardCategory = ScorecardCategory.SKILL
    weight: float = 1.0
    max_score: int = SCORE_MAX


class ScorecardIn(BaseModel):
    request_no: str
    title: Optional[str] = None
    criteria: List[ScorecardCriterionIn]
    managerial: bool = False        # managerial+ roles additionally need MD approval
    notes: Optional[str] = None


class ScorecardUpdate(BaseModel):
    title: Optional[str] = None
    criteria: Optional[List[ScorecardCriterionIn]] = None
    managerial: Optional[bool] = None
    notes: Optional[str] = None


class ScorecardApproveIn(BaseModel):
    decision: Decision = Decision.PASS
    remarks: Optional[str] = None
    signature: str


class ScorecardEvaluateIn(BaseModel):
    """Score one candidate against their requisition's scorecard.

    `scores` is {criterion_label: 1-5}. The weighted total and its band are computed
    server-side -- the browser never derives a figure this module then acts on.
    """
    scores: Dict[str, int]
    remarks: Optional[str] = None
    signature: str


class ReferenceCheckIn(BaseModel):
    uk: str
    referee_name: str
    referee_designation: Optional[str] = None
    referee_organisation: Optional[str] = None
    relationship: Optional[str] = None
    referee_contact: Optional[str] = None
    mode: ReferenceMode = ReferenceMode.PHONE
    checked_on: Optional[str] = None            # YYYY-MM-DD
    responses: Optional[str] = None
    outcome: ReferenceOutcome = ReferenceOutcome.POSITIVE
    remarks: Optional[str] = None


class ReferenceCheckUpdate(BaseModel):
    referee_name: Optional[str] = None
    referee_designation: Optional[str] = None
    referee_organisation: Optional[str] = None
    relationship: Optional[str] = None
    referee_contact: Optional[str] = None
    mode: Optional[ReferenceMode] = None
    checked_on: Optional[str] = None
    responses: Optional[str] = None
    outcome: Optional[ReferenceOutcome] = None
    remarks: Optional[str] = None


class TelephonicScreeningIn(BaseModel):
    """SOP step 5 — the brief telephonic interview by HR.

    Split into what the call ESTABLISHES (notice period, expectation, location,
    availability — facts the candidate stated) and what the caller JUDGED (the four rated
    dimensions). Mixing them would let a rating stand in for a fact, and "seemed available"
    is not an availability date anybody can plan a joining around.
    """
    uk: str
    screened_on: Optional[str] = None            # YYYY-MM-DD, defaults to today
    duration_minutes: Optional[int] = None
    # What the candidate said.
    notice_period_days: Optional[int] = None
    expected_ctc: Optional[float] = None
    current_location: Optional[str] = None
    availability: Optional[str] = None
    # What the caller judged, 1-5 each.
    communication: Optional[float] = None
    role_understanding: Optional[float] = None
    motivation: Optional[float] = None
    suitability: Optional[float] = None
    outcome: TelephonicOutcome = TelephonicOutcome.PASSED
    comments: Optional[str] = None


class TelephonicScreeningUpdate(BaseModel):
    screened_on: Optional[str] = None
    duration_minutes: Optional[int] = None
    notice_period_days: Optional[int] = None
    expected_ctc: Optional[float] = None
    current_location: Optional[str] = None
    availability: Optional[str] = None
    communication: Optional[float] = None
    role_understanding: Optional[float] = None
    motivation: Optional[float] = None
    suitability: Optional[float] = None
    outcome: Optional[TelephonicOutcome] = None
    comments: Optional[str] = None


class OfferApproveIn(BaseModel):
    """Annexure B marks offer approval "A" for Management/Finance, and mandatory."""
    remarks: Optional[str] = None
    signature: str


class ProbationIn(BaseModel):
    employee_code: str
    request_no: Optional[str] = None            # carried so analytics scoping still works
    started_on: Optional[str] = None            # YYYY-MM-DD; defaults to the joining date
    duration_months: int = DEFAULT_PROBATION_MONTHS
    reviewer_id: Optional[str] = None
    notes: Optional[str] = None


class ProbationUpdate(BaseModel):
    started_on: Optional[str] = None
    duration_months: Optional[int] = None
    reviewer_id: Optional[str] = None
    rating: Optional[float] = None              # against the position scorecard, 1-5
    notes: Optional[str] = None


class ProbationConfirmIn(BaseModel):
    outcome: ProbationOutcome
    rating: Optional[float] = None
    extended_to: Optional[str] = None           # required when the outcome is Extended
    remarks: Optional[str] = None
    signature: str


class ExceptionIn(BaseModel):
    request_no: str
    exception_type: ExceptionType
    reason: str
    uk: Optional[str] = None                    # when candidate-specific
    linked_entity: Optional[str] = None         # e.g. the offer_no this would unblock


class ExceptionDecisionIn(BaseModel):
    decision: ExceptionStatus
    remarks: Optional[str] = None
    signature: str


class PersonnelFileCloseIn(BaseModel):
    employee_code: str
    closure_note: str


# =============================================================
# Phase INT-2 — the remaining Internal Recruitment SOP controls
# =============================================================
# Everything below is ADDITIVE and internal-track only. No client-track requisition enters
# any of it: the panel and final-round gates return early on the client track, the
# shortlisting committee refuses a client requisition outright, and the pre-boarding,
# survey and policy surfaces are governance records with no client-track counterpart.

# -- INT-2.1  Interview governance (SOP §5) ------------------------------------------
# WHO MUST BE IN THE ROOM, as a table rather than code branching.
#
# SOP §5: "Interviews shall be conducted by a panel comprising HR and the Department Head,
# with Management joining for managerial and above." A chain of ifs would put the rule in
# four places (the scheduler, the picker, the tests and the docs); a table puts it in one,
# and adding a level later is a data change.
#
# The roles named are HRMS roles, so the check reads the same vocabulary every capability
# check does -- there is no second notion of "who counts as HR" anywhere in this module.
REQUIRED_PANEL_ROLES = {
    DesignationLevel.JUNIOR:     [HrmsRole.HR, HrmsRole.MANAGER],
    DesignationLevel.MID:        [HrmsRole.HR, HrmsRole.MANAGER],
    DesignationLevel.SENIOR:     [HrmsRole.HR, HrmsRole.MANAGER, HrmsRole.MD],
    DesignationLevel.MANAGERIAL: [HrmsRole.HR, HrmsRole.MANAGER, HrmsRole.MD],
}


def required_panel_roles(level) -> list:
    """The roles a panel must cover for this seniority band.

    Returned as a LIST, in the order the SOP states them, so the UI can show "still needed:
    HR, Management" in a stable order rather than whatever a set happens to iterate in.
    An unknown band falls back to the default band's requirement rather than to an empty
    list: failing OPEN here would make the whole control optional for any designation
    somebody forgot to band.
    """
    try:
        band = DesignationLevel(getattr(level, "value", level))
    except (ValueError, TypeError):
        band = DEFAULT_DESIGNATION_LEVEL
    return list(REQUIRED_PANEL_ROLES[band])


def final_round_is_mandatory(level) -> bool:
    """Whether SOP §5's Management final round applies to this band.

    Asserted from MANAGERIAL_LEVELS rather than re-listing the bands, so this and the panel
    table cannot drift. The test walks every band against both.
    """
    return is_managerial_level(level)


# The round that satisfies the mandatory Management final interview. Named here rather than
# hard-coded in the service, so "which round IS the final one" is answerable from the model.
FINAL_ROUND = InterviewRound.MD
# The outcome that counts as having PASSED it. A Hold is not a pass -- it is a decision
# deferred, and treating it as clearance would let an undecided candidate reach an offer.
FINAL_ROUND_PASSING = {Outcome.PASS.value}


class ShortlistOutcome(str, Enum):
    """What the committee decided about the intake as a whole."""
    PENDING   = "Pending"        # convened, not yet decided
    FINALISED = "Finalised"      # the named candidates go to the final interview
    DEFERRED  = "Deferred"       # more sourcing needed; nobody progresses on this sitting


class CommitteeDecision(str, Enum):
    AGREE  = "Agree"
    OBJECT = "Object"


# SOP §5 requires HR AND the Department Head to finalise candidates. Two ROLES, and -- the
# part that makes it a control rather than a formality -- two different PEOPLE. Exactly the
# rule hrms_scorecard_service._approval_state already enforces for a managerial scorecard,
# reused here rather than re-derived.
SHORTLIST_COMMITTEE_ROLES = [HrmsRole.HR, HrmsRole.MANAGER]
SHORTLIST_MIN_MEMBERS = 2

AUDIT_SHORTLIST_CONVENED = "shortlisting committee convened"
AUDIT_SHORTLIST_DECIDED  = "shortlisting committee decision recorded"
ENTITY_SHORTLIST = "shortlist_review"


# -- Batch interview windows (Annexure C) ---------------------------------------------
# "Schedule interviews in batches to reduce panel disruption."
#
# A WARNING, never a refusal. A hard block on out-of-window scheduling would make an urgent
# hire impossible at 4pm on a Friday, which is precisely when an urgent hire happens. The
# response carries the warning; the booking goes through.
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

AUDIT_WINDOW_CREATED = "interview window defined"
AUDIT_WINDOW_UPDATED = "interview window updated"
AUDIT_WINDOW_DELETED = "interview window removed"
ENTITY_INTERVIEW_WINDOW = "interview_window"

# HH:MM, 24-hour. Validated as a shape before it is compared, so a window can never be
# stored in a form the comparison silently reads as "never matches".
TIME_RE = _re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# -- INT-2.3  Pre-boarding engagement (SOP §6) -----------------------------------------
# The window between "they accepted" and "they walked in" is where an offer is lost to a
# counter-offer. The SOP names the practice; this records it.
#
# NOTHING IS GATED ON IT. It is engagement tracking, not a control: a candidate with no
# touchpoint still onboards exactly as they always did. What it does is put them on a due
# list and raise a flag when somebody says they are wavering.
class PreboardingMode(str, Enum):
    CALL     = "Call"
    EMAIL    = "Email"
    WHATSAPP = "WhatsApp"
    MEETING  = "Meeting"


class PreboardingSentiment(str, Enum):
    POSITIVE = "Positive"
    NEUTRAL  = "Neutral"
    AT_RISK  = "At Risk"


# Candidate stages that are IN the pre-boarding window: they have accepted and have not yet
# joined. A candidate outside these is not "overdue a touchpoint", they are simply not in
# this phase of the process.
PREBOARDING_STATUSES = {
    AppStatus.OFFER_ACCEPTED, AppStatus.APPOINTMENT_LETTER_SENT, AppStatus.PRE_ONBOARDING,
}

# How long a candidate in that window may go without contact before they appear on
# `GET /preboarding/due`. Seven days, because the SOP's practice is weekly contact and a
# tighter figure would fill the list with people somebody spoke to on Friday.
PREBOARDING_CONTACT_DAYS = 7

AUDIT_PREBOARDING_LOGGED = "pre-boarding touchpoint recorded"
ENTITY_PREBOARDING = "preboarding_touchpoint"


# -- INT-2.5  The standing salary-band master (Annexure C) -----------------------------
# "Pre-define standard salary bands per role/grade with Finance annually, so individual
# requisitions don't need a fresh budget discussion each time."
#
# THE MASTER IS A CONVENIENCE, NEVER AN AUTHORITY. The budget gate pre-fills from it; the
# offer check reads the band STAMPED ON THE REQUISITION and never this table. That
# separation is the whole design: a master edited in April must not retroactively legalise
# an offer approved in March.
class SalaryBandStatus(str, Enum):
    ACTIVE      = "Active"
    SUPERSEDED  = "Superseded"   # replaced by a newer band for the same position
    RETIRED     = "Retired"      # withdrawn without a replacement


# Where the band on a requisition came from. Stamped at the budget gate so a reader can tell
# "Finance's standing figure" from "the approver typed something else", and the second case
# is required to carry a reason.
BAND_SOURCE_MASTER = "master"
BAND_SOURCE_MANUAL = "manual"

AUDIT_SALARY_BAND_CREATED    = "salary band published"
AUDIT_SALARY_BAND_UPDATED    = "salary band updated"
AUDIT_SALARY_BAND_SUPERSEDED = "salary band superseded"
ENTITY_SALARY_BAND = "salary_band"


# -- INT-2.6  Talent pool (Annexure C) --------------------------------------------------
# "Build and maintain an internal talent pool of prior applicants and referrals."
#
# The compliance shape matters more than the feature. A CV kept because it is "in the pool"
# past the retention period the candidate consented to is exactly the failure SOP §11 and
# §13 exist to prevent -- so consent is REQUIRED to enter the pool, and the consent expiry
# may never outlive `retention_until`. Enforced in the service; stated here.
AUDIT_TALENT_POOL_ADDED   = "candidate added to the talent pool"
AUDIT_TALENT_POOL_REMOVED = "candidate removed from the talent pool"

MAX_TALENT_POOL_TAGS = 12


# -- INT-2.7  Candidate communications (Annexure C) -------------------------------------
# Four commitments the SOP makes to applicants and nothing implemented them: acknowledge
# every application, keep them updated, tell them when they are out, and put the offer terms
# in writing before the formal letter.
#
# Delivery goes through hrms_notify_service. There is deliberately no second mail path --
# the module already learned that lesson once (see that module's docstring on the source's
# hrms_email_outbox).
class CommChannel(str, Enum):
    EMAIL = "email"
    INAPP = "inapp"


class CommStatus(str, Enum):
    SENT    = "Sent"
    FAILED  = "Failed"
    SKIPPED = "Skipped"       # no address / no template / suppressed in a seed run


# The six seeded templates. Seeded on FIRST READ for a company that has none, exactly as
# DEFAULT_DOCUMENT_TYPES are -- so a company that never opens the screen still gets working
# copy, and one that edits it is never overwritten.
#
# `{placeholders}` are filled by render_comm_body, which uses the same defaulting format_map
# render_offer_body does: an unknown placeholder renders harmlessly rather than raising.
#
# The EEO and data-use wording lives here (not in code) for the reason INT-2.10 requires:
# legal must be able to change it without a deploy.
# (key, channel, subject, body, variables)
DEFAULT_COMM_TEMPLATES = [
    ("application_acknowledged", CommChannel.EMAIL,
     "We have received your application for {designation}",
     "Dear {candidate_name},\n\n"
     "Thank you for applying for {designation}. Your application has been received and is "
     "with our recruitment team.\n\n"
     "We review every application we receive. If your profile matches what the role needs, "
     "we will be in touch to arrange a conversation. If we do not progress your application "
     "this time, we will tell you.\n\n"
     "Reference: {reference}\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "reference", "company"]),

    ("stage_update", CommChannel.EMAIL,
     "An update on your application for {designation}",
     "Dear {candidate_name},\n\n"
     "Your application for {designation} has moved to: {stage}.\n\n"
     "{note}\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "stage", "note", "company"]),

    ("interview_scheduled", CommChannel.EMAIL,
     "Your interview for {designation}",
     "Dear {candidate_name},\n\n"
     "We would like to invite you to the {round} for {designation}.\n\n"
     "When: {when}\nWhere: {where}\n\n"
     "If that time does not work for you, reply to this message and we will find another.\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "round", "when", "where", "company"]),

    ("rejection_closure", CommChannel.EMAIL,
     "Your application for {designation}",
     "Dear {candidate_name},\n\n"
     "Thank you for the time you gave to your application for {designation}.\n\n"
     "On this occasion we will not be taking it further. The decision reflects the fit "
     "between the role's requirements and the profiles we saw; it is not a judgement on your "
     "wider experience.\n\n"
     "We are grateful you considered us, and we wish you well.\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "company"]),

    ("offer_summary", CommChannel.EMAIL,
     "Summary of the offer we intend to make you",
     "Dear {candidate_name},\n\n"
     "Ahead of the formal letter, here is a summary of what we intend to offer:\n\n"
     "Role: {designation}\nAnnual cost to company: {ctc}\nProposed joining date: "
     "{joining_date}\nLocation: {location}\n\n"
     "This summary is for your review; the formal offer letter follows and is the binding "
     "document. Do come back to us with any questions before then.\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "ctc", "joining_date", "location", "company"]),

    ("preboarding_checkin", CommChannel.EMAIL,
     "Looking forward to {joining_date}",
     "Dear {candidate_name},\n\n"
     "We are looking forward to you joining us on {joining_date} as {designation}.\n\n"
     "If anything has changed, or if there is anything you need from us before then, reply "
     "to this message -- we would much rather know early.\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "joining_date", "company"]),
]

# The equal-opportunity and data-use statements shown on the public application form (SOP
# §11). They are TEMPLATES rather than constants precisely so legal can edit the wording
# without a deploy -- the same reason the letters above are.
CONSENT_TEMPLATES = [
    ("consent_equal_opportunity", CommChannel.INAPP,
     "Equal opportunity",
     "We consider every application on merit. We do not discriminate on the basis of "
     "gender, marital status, religion, caste, disability, age or any other protected "
     "characteristic. Tick to confirm you have read this.",
     []),
    ("consent_data_use", CommChannel.INAPP,
     "How we use your information",
     "We will hold the information in this application for as long as we need it to "
     "consider you for this role, and no longer than our published retention period. We "
     "will not share it outside the hiring team without asking you. Tick to confirm you "
     "have read this and consent to us processing your application.",
     []),
]

# Templates fired automatically by a pipeline event, and the event that fires each. Declared
# as data so the wiring is readable in one place rather than inferred from five call sites.
AUTO_COMM_EVENTS = {
    "application_received": "application_acknowledged",
    "screening_rejected":   "rejection_closure",
}

# Templates that are only ever sent by hand. `offer_summary` is here deliberately: writing to
# a candidate about money is a decision, not a side effect of a status change.
MANUAL_COMM_TEMPLATES = {"offer_summary", "stage_update", "preboarding_checkin"}

AUDIT_COMM_SENT             = "candidate communication sent"
AUDIT_COMM_TEMPLATE_UPDATED = "communication template updated"
ENTITY_COMM = "communication"


def render_comm_body(template: str, values: dict) -> str:
    """Fill the placeholders in a communication template.

    Same mechanism, and the same reasoning, as render_offer_body: a plain format_map with a
    defaulting dict, so an operator-edited template containing an unknown or mistyped
    placeholder renders harmlessly rather than raising or executing anything.
    """
    class _Safe(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return (template or "").format_map(
            _Safe({k: ("" if v is None else str(v)) for k, v in (values or {}).items()}))
    except (ValueError, IndexError):
        return template or ""


# -- INT-2.8  New-hire experience surveys (SOP §10) --------------------------------------
# Two of the SOP's KPIs are unbuildable without capture: new-hire satisfaction, and an
# induction feedback SCORE where the checklist only records that feedback happened.
#
# -- Pseudonymous to the reporting layer, and that is a hard rule --------------------------
# `employee_code` is stored for ONE purpose: stopping the same person answering twice (the
# unique index above). The analytics aggregation returns SCORES ONLY, never rows, and
# refuses any breakdown with fewer than SURVEY_MIN_RESPONSES answers. A satisfaction survey
# a manager can de-anonymise measures nothing except how much people trust the survey.
class SurveyKind(str, Enum):
    INDUCTION = "induction"
    PROBATION = "probation"


# The smallest group whose average may be shown. Five is the usual small-cell threshold; the
# point is that below it a reader who knows the team can attribute an answer.
SURVEY_MIN_RESPONSES = 5
SURVEY_SUPPRESSED = (
    f"Fewer than {SURVEY_MIN_RESPONSES} responses. Individual answers would be "
    f"identifiable, so no figure is shown.")

SURVEY_SCORE_MIN = 1
SURVEY_SCORE_MAX = 5

# The two seeded instruments. (kind, title, intro, [(question_key, prompt)])
# Deliberately short: a fifteen-question form on day one is a form nobody finishes, and an
# unfinished form is worse data than five honest answers.
DEFAULT_SURVEYS = [
    (SurveyKind.INDUCTION, "Your first days with us",
     "Five quick questions about how your joining went. Your answers are reported as "
     "averages only -- nobody sees your individual response.",
     [("welcome",     "I felt welcomed and expected on my first day."),
      ("clarity",     "It was clear what my role is and what is expected of me."),
      ("systems",     "The systems, access and equipment I need were ready."),
      ("induction",   "The induction covered what I needed to know."),
      ("overall",     "Overall, my joining experience was a good one.")]),
    (SurveyKind.PROBATION, "Your first months with us",
     "Five questions at the end of your probation. Reported as averages only.",
     [("support",     "I had the support I needed to do my job well."),
      ("feedback",    "I received useful feedback during my probation."),
      ("expectations", "The role matched what I was told at interview."),
      ("development", "I can see how I can develop here."),
      ("overall",     "Overall, I am glad I joined.")]),
]

AUDIT_SURVEY_ISSUED    = "experience survey issued"
AUDIT_SURVEY_SUBMITTED = "experience survey submitted"
ENTITY_SURVEY = "survey"


# -- INT-2.11  The policy register (SOP §14) ---------------------------------------------
# "This policy shall be reviewed annually... All amendments shall be logged in the
# Modification History table."
#
# The register answers three questions a review cannot answer without it: which version is
# in force, when it is next due to be looked at, and what changed last time.
class PolicyStatus(str, Enum):
    DRAFT       = "Draft"
    IN_FORCE    = "In Force"
    SUPERSEDED  = "Superseded"
    WITHDRAWN   = "Withdrawn"


# How far ahead a review starts being announced. Thirty days is enough notice to schedule a
# conversation and not so much that the reminder becomes background noise.
POLICY_REVIEW_NOTICE_DAYS = 30
# The SOP's own cycle. A revision approved today sets the next review a year out.
POLICY_REVIEW_MONTHS = 12

# The two policies this module actually implements, seeded on first read so the register is
# never empty on a company that has both tracks running.
# (policy_key, title, version, owner_role)
DEFAULT_POLICIES = [
    ("internal_recruitment", "Sparsh Magic Internal Recruitment Policy & SOP", "1.0",
     HrmsRole.HR),
    ("profit_recruitment",   "Sparsh Magic PRO-fit Recruitment Policy & SOP", "2.0",
     HrmsRole.HR),
]

AUDIT_POLICY_REGISTERED = "policy registered"
AUDIT_POLICY_REVISED    = "policy revision logged"
AUDIT_POLICY_APPROVED   = "policy revision approved"
ENTITY_POLICY = "policy"


# -- INT-2.12  Retention purge (SOP §13) --------------------------------------------------
# `retention_until` has been stamped and reported since the internal track shipped, and
# nothing has ever deleted. This builds the job -- but NOT as a silent cron.
#
# Three properties, each of which is the reason the previous phase declined to build it:
#
#  1. A purge is PROPOSED, then approved by a human with a typed signature. The same
#     standard probation confirmation holds, because both destroy or end something.
#  2. It REDACTS rather than hard-deletes wherever a record is referenced by an audit row.
#     An audit trail full of dangling references proves nothing.
#  3. It never touches an open requisition or an active employment, whatever the dates say.
class PurgeBatchStatus(str, Enum):
    PROPOSED  = "Proposed"     # a dry run wrote this; nothing has happened
    APPROVED  = "Approved"     # signed off, execution may proceed
    EXECUTED  = "Executed"
    CANCELLED = "Cancelled"


# What a purge does to each record type, and which fields it clears.
#
# REDACT keeps the id and the audit spine and clears the personal detail. DELETE is reserved
# for rows that are pure PII with nothing referencing them. Every entry here is REDACT today
# -- every HRMS record is referenced by at least an audit row -- and the vocabulary exists so
# a later, deliberate decision to hard-delete something is a data change somebody reviews.
PURGE_REDACT = "redact"
PURGE_DELETE = "delete"

# (collection, id_field, retention_field, mode, [fields to clear])
PURGE_TARGETS = [
    (COLL_CANDIDATES, "uk", "retention_until", PURGE_REDACT,
     ["candidate_name", "can_email", "can_contact", "current_location", "linkedin",
      "portfolio", "cover_note", "resume", "photo", "certificates", "current_company",
      "current_ctc", "expected_ctc", "referred_by", "referrer_employee_code",
      "talent_pool_tags"]),
    (COLL_REFERENCE_CHECKS, "ref_no", "retention_until", PURGE_REDACT,
     ["referee_name", "referee_contact", "referee_organisation", "referee_designation",
      "responses", "remarks"]),
    (COLL_OFFERS, "offer_no", "retention_until", PURGE_REDACT,
     ["candidate_email", "content", "history", "candidate_signature", "response_note"]),
    (COLL_COMM_LOG, "candidate_uk", "retention_until", PURGE_REDACT,
     ["subject", "body", "recipient"]),
    (COLL_PREBOARDING, "pbt_no", "retention_until", PURGE_REDACT,
     ["notes"]),
    # What a candidate said about their salary, their notice period and why they want the
    # job is exactly the kind of detail retention exists to stop us keeping forever.
    (COLL_TELEPHONIC, "tel_no", "retention_until", PURGE_REDACT,
     ["comments", "expected_ctc", "notice_period_days", "current_location",
      "availability"]),
]

# What is stamped on a redacted row, so a reader never mistakes an emptied record for one
# that was always empty. This is the difference between "we purged this" and "we lost this".
PURGE_MARKER_FIELD = "purged_at"
PURGE_BATCH_FIELD  = "purged_batch_no"

AUDIT_PURGE_PROPOSED = "retention purge proposed"
AUDIT_PURGE_APPROVED = "retention purge approved"
AUDIT_PURGE_EXECUTED = "retention purge executed"
ENTITY_PURGE_BATCH = "purge_batch"


# -- Phase INT-3  The scheduled jobs (SOP §12) ---------------------------------------------
# Five governance sweeps that were written to be DRIVEN by a job runner and, until this
# phase, were driven by nothing. Declared here rather than in the service for the same
# reason SLA_MILESTONES is: the table is the specification, and a reader should be able to
# see the whole schedule without reading the loop that walks it.
#
# `hour` is a UTC gate, matched with `>=` rather than `==` so a job whose minute the process
# spent restarting still runs later that day instead of being skipped until tomorrow -- the
# rule the TPMS block beside it already follows.
#
# `cadence` picks the stamp the run is remembered against: a daily job is remembered by
# date, a weekly one by ISO year+week. A weekly job therefore runs on the first tick after
# its hour on any day of a week it has not yet run in, which is what makes it survive a
# process that was down all Monday.
JOB_CADENCE_DAILY  = "daily"
JOB_CADENCE_WEEKLY = "weekly"

JOB_SLA_SWEEP     = "sla_sweep"
JOB_PROBATION     = "probation_reminders"
JOB_PREBOARDING   = "preboarding_reminders"
JOB_POLICY_REVIEW = "policy_review"
JOB_RETENTION     = "retention_propose"

# (key, label, cadence, utc_hour)
SCHEDULED_JOBS = [
    (JOB_SLA_SWEEP,     "internal SLA breach sweep",      JOB_CADENCE_DAILY,  7),
    (JOB_PROBATION,     "probation review reminders",     JOB_CADENCE_DAILY,  7),
    (JOB_PREBOARDING,   "pre-boarding contact reminders", JOB_CADENCE_DAILY,  8),
    (JOB_POLICY_REVIEW, "policy review reminders",        JOB_CADENCE_WEEKLY, 8),
    (JOB_RETENTION,     "retention purge proposal",       JOB_CADENCE_WEEKLY, 3),
]


def scheduled_job(key: str) -> Optional[tuple]:
    """One row of the job table by key, or None. Pure."""
    return next((j for j in SCHEDULED_JOBS if j[0] == key), None)


# How far ahead of a probation end date each reminder fires, in calendar days.
#
# CALENDAR days, not working days: this is a diary note to a manager, not an SLA. The SLA
# table already owns the working-day question, and measuring a "30 days before" reminder in
# working days would put it at a date nobody could predict from the end date itself.
#
# A tier fires when the end date is that close OR CLOSER and the tier has not fired for that
# record yet, rather than on an exact-day match. Exact matching loses the reminder entirely
# if the scheduler was down that one day, which is precisely the day it mattered.
#
# Nothing here handles an OVERDUE review: the `probation_review_due` row in SLA_MILESTONES
# already reports that as a breach and `sweep_open_breaches` already escalates it. Two
# subsystems announcing the same overdue review is how people learn to ignore both.
PROBATION_REMINDER_DAYS = [30, 15, 7, 1]

# Where a record remembers which tiers it has already been reminded about. On the probation
# record itself rather than in a side ledger, so the guard survives any rebuild of the job
# and is visible to anybody reading the row.
PROBATION_REMINDED_FIELD = "reminders_sent"


# -- INT-2.13  The printable documentation set (SOP §9) ------------------------------------
# Five of the SOP's nine templates have data but no artifact. One endpoint pattern serves all
# five: `GET /{entity}/{business_no}/document`, gated by the entity's EXISTING read
# capability -- printing a record is reading it, and inventing a `document.generate`
# capability would mean a user who may read a probation review might not be able to print it,
# which is a distinction nobody wants to explain.
#
# (key, title, collection, id_field, read capability)
PRINTABLE_DOCUMENTS = {
    "requisition": ("Internal Manpower Requisition Form", COLL_REQUISITIONS,
                    "request_no", Cap.REQUISITION_READ),
    "budget-note": ("Headcount & Budget Approval Note", COLL_REQUISITIONS,
                    "request_no", Cap.REQUISITION_READ),
    "reference":   ("Reference Check Report", COLL_REFERENCE_CHECKS,
                    "ref_no", Cap.REFERENCE_READ),
    "probation":   ("Probation Review & Confirmation Record", COLL_PROBATION_REVIEWS,
                    "prb_no", Cap.PROBATION_READ),
    "personnel-file": ("Personnel File Closure Note", COLL_EMPLOYEE_PROFILES,
                       "employee_code", Cap.PERSONNEL_FILE_CLOSE),
}

# How long a generated document's signed URL lives. One hour, matching s3_service's default:
# long enough to open and print, short enough that a copied URL is not a standing grant.
DOCUMENT_URL_TTL_SECONDS = 3600

AUDIT_DOCUMENT_GENERATED = "record document generated"


# ── API models ──────────────────────────────────────────────────────────────────────
class CommitteeMemberIn(BaseModel):
    user_id: str
    decision: CommitteeDecision = CommitteeDecision.AGREE
    remarks: Optional[str] = None
    # ── SOP §11 conflict of interest ── declared per MEMBER, not per sitting: the conflict
    # belongs to a person, and a committee where one member is the candidate's cousin is
    # perfectly workable as long as that member stands down.
    coi_declared: bool = False
    coi_relationship: Optional[str] = None
    recused: bool = False


class ShortlistReviewIn(BaseModel):
    """Convene the internal shortlisting committee for one requisition (SOP §5)."""
    request_no: str
    candidate_uks: List[str] = Field(default_factory=list)
    committee_members: List[CommitteeMemberIn] = Field(default_factory=list)
    outcome: ShortlistOutcome = ShortlistOutcome.PENDING
    notes: Optional[str] = None


class ShortlistReviewUpdate(BaseModel):
    candidate_uks: Optional[List[str]] = None
    committee_members: Optional[List[CommitteeMemberIn]] = None
    outcome: Optional[ShortlistOutcome] = None
    notes: Optional[str] = None


class InterviewWindowIn(BaseModel):
    """A standing batch-interview slot (Annexure C). Advisory, never a block."""
    department_id: str
    weekday: str                                  # one of WEEKDAYS
    start_time: str                               # HH:MM, 24-hour
    end_time: str
    panel_ids: List[str] = Field(default_factory=list)
    active: bool = True
    notes: Optional[str] = None


class InterviewWindowUpdate(BaseModel):
    weekday: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    panel_ids: Optional[List[str]] = None
    active: Optional[bool] = None
    notes: Optional[str] = None


class PreboardingTouchpointIn(BaseModel):
    candidate_uk: str
    mode: PreboardingMode = PreboardingMode.CALL
    sentiment: PreboardingSentiment = PreboardingSentiment.NEUTRAL
    contacted_at: Optional[str] = None            # YYYY-MM-DD; defaults to today
    counter_offer_disclosed: bool = False
    notes: Optional[str] = None


class SalaryBandIn(BaseModel):
    department_id: str
    designation_id: str
    grade: Optional[str] = None                   # a company's own grade label, if it has one
    min: float
    max: float
    currency: str = "INR"
    effective_from: Optional[str] = None          # YYYY-MM-DD; defaults to today
    effective_to: Optional[str] = None
    notes: Optional[str] = None


class SalaryBandUpdate(BaseModel):
    grade: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    currency: Optional[str] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    status: Optional[SalaryBandStatus] = None
    notes: Optional[str] = None


class TalentPoolIn(BaseModel):
    """Add or remove a candidate from the talent pool.

    `consent_to_retain` is not a convenience flag: without it the candidate never enters the
    pool at all, because keeping a CV to consider later is a different thing from keeping it
    to process one application, and only the candidate can agree to the second.
    """
    talent_pool: bool = True
    talent_pool_tags: List[str] = Field(default_factory=list)
    consent_to_retain: bool = False
    consent_expires_at: Optional[str] = None      # YYYY-MM-DD; capped at retention_until
    remarks: Optional[str] = None


class CommTemplateUpdate(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    channel: Optional[CommChannel] = None
    active: Optional[bool] = None


class CommSendIn(BaseModel):
    """Send one templated message to one candidate, by hand."""
    candidate_uk: str
    template_key: str
    # Extra placeholder values the caller wants to supply (a covering note, a stage name).
    # Everything the module can derive -- name, designation, CTC -- is derived, not accepted,
    # so a sender cannot quote a salary the record does not hold.
    variables: Dict[str, str] = Field(default_factory=dict)


class SurveyResponseIn(BaseModel):
    """A survey submission from the public link. Entirely untrusted."""
    scores: Dict[str, int] = Field(default_factory=dict)
    comment: Optional[str] = None


class PolicyIn(BaseModel):
    policy_key: str
    title: str
    version: str = "1.0"
    effective_date: Optional[str] = None          # YYYY-MM-DD; defaults to today
    owner_role: Optional[str] = None
    next_review_due: Optional[str] = None         # defaults to +POLICY_REVIEW_MONTHS
    document_id: Optional[str] = None             # a doc_no in the document register


class PolicyRevisionIn(BaseModel):
    version: str
    summary_of_change: str
    effective_date: Optional[str] = None
    document_id: Optional[str] = None


class PolicyApproveIn(BaseModel):
    version: str
    remarks: Optional[str] = None
    signature: str


class PurgeApproveIn(BaseModel):
    """Authorise a purge proposal to execute.

    A typed signature, for the same reason probation confirmation demands one: this is the
    call that destroys records, and it has to be attributable to a person.
    """
    signature: str
    remarks: Optional[str] = None


# =============================================================
# Client engagements — the tenant/client relationship
# =============================================================
# "Sparsh Magic provides recruitment services to this company, and these of our users work
# on it." That fact exists nowhere in the ERP: a `companies` row says an organisation
# exists, not that it is OUR client. Without it, `client_id` is an unverifiable label, and
# "is this company a client of ours" -- the question every client-scope check rests on --
# has no answer.
#
# The engagement is NOT a second company record. `client_id` remains a `companies._id`;
# nothing here duplicates a name, an address or a contact.
#
# -- Membership lives HERE, not on the user ------------------------------------------------
# `learners` and `staff` are shared ERP collections owned by routes/user.py. HRMS writing
# its own array into them would widen another module's schema and put a field the frontend
# reads behind UserResponse's declaration guard. Holding the member list on the engagement
# keeps the whole relationship inside HRMS, makes "manage this client's users" a single
# document, and makes revocation atomic: closing an engagement removes its access.
#
# A user in two engagements has two clients. Multi-client is the natural shape, not a
# special case.

class EngagementStatus(str, Enum):
    ACTIVE    = "active"
    # Suspended rather than deleted: an engagement that ends still has to explain the
    # requisitions raised under it. Only ACTIVE grants scope.
    SUSPENDED = "suspended"
    ENDED     = "ended"


# The only status that resolves client scope. Declared as a set so the rule is read from
# one place rather than re-tested as `== "active"` in each caller.
ENGAGEMENT_GRANTS_SCOPE = {EngagementStatus.ACTIVE.value}

AUDIT_ENGAGEMENT_CREATED = "client engagement opened"
AUDIT_ENGAGEMENT_UPDATED = "client engagement updated"
AUDIT_ENGAGEMENT_MEMBER_ADDED   = "client engagement member added"
AUDIT_ENGAGEMENT_MEMBER_REMOVED = "client engagement member removed"

ENTITY_ENGAGEMENT = "client_engagement"


class ClientEngagementIn(BaseModel):
    """Open an engagement with an existing ERP company."""
    client_id: str                       # a companies._id
    notes: Optional[str] = None


class ClientEngagementUpdate(BaseModel):
    status: Optional[EngagementStatus] = None
    notes: Optional[str] = None


class EngagementMemberIn(BaseModel):
    """Give one user access to one client's recruitment.

    `user_id` must be a user of the SAME company as the engagement. A user from another
    tenant is refused -- company_id remains the security boundary, and client scope narrows
    inside it rather than reaching across it.
    """
    user_id: str
