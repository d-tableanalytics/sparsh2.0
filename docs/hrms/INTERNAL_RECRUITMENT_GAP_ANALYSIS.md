# Sparsh Magic Internal Recruitment — Analysis & Gap Report

> **Analysis only. No code was modified to produce this.**
> Verified against the working tree on 2026-08-14 by reading source and running the full
> HRMS test suite (**53/53 files pass**).

---

## Headline

**The Sparsh Magic internal recruitment workflow is already built.** It shipped as the
`internal` requisition track plus **Phase INT-2**, and it is live in the working tree:
34 backend services, 173 authenticated endpoints, 33 collections, 84 capabilities, 30
frontend screens, 53 green test files.

The specification I was given describes, in ~90% of its sections, functionality that exists
today. Implementing it as a new module would duplicate roughly 25,000 lines of working,
tested code and break the client track.

**The correct action is not to build the workflow. It is to close a short, specific list of
gaps** — set out in §B below. The largest by far is that **no scheduler drives any of it**:
the SLA sweep, probation reminders, pre-boarding reminders, policy review reminders and the
retention purge are all written and tested, and nothing calls them.

---

## A. Existing HRMS analysis

### A.1 Architecture

| Layer | Where | Notes |
|---|---|---|
| Backend | FastAPI + MongoDB (Motor), `backend/app/` | routes → services → collections; no ORM |
| Models | `models/hrms.py` (4,518 lines) | **single source of truth**: enums, both state graphs, capability enum, role tables, collection names, id formats, SLA + retention tables, Pydantic models |
| Routes | `routes/hrms.py` (2,930 lines, 173 endpoints) | every handler opens with `_require(user, Cap.X)` |
| Public | `routes/hrms_public.py` + `utils/hrms_public_guard.py` | 6 unauthenticated surfaces, DB-backed rate limits |
| Access | `utils/hrms_access.py` (328 lines) | identity → role → capability → company scope → client scope |
| Frontend | React + Tailwind, `frontend/src/features/hrms/` | `HrmsContext` fetches `/hrms/health`, gates on server-reported capabilities, **fails closed** |
| Scheduler | `services/reminder_scheduler.py`, started from `main.py` lifespan | 60-second asyncio loop, hour-gated daily jobs (the TPMS pattern) |
| Notifications | `hrms_notify_service.py` | `notify_user` / `notify_users` / `notify_hrms_role` → in-app rows + email |
| Audit | `hrms_audit_service.py` → `hrms_audit_log` | append-only; every service writes through it |
| Documents | `hrms_document_service.py` + S3 | typed, versioned, owner-linked, separate `document.verify` capability |

### A.2 The two tracks

Everything runs on one of two **requisition tracks**, fixed at creation and immutable after:

- **`client`** — the original agency model (recruit *for* a client company). Default; a
  requisition with no `requisition_track` field reads as `client`, which is the backward
  compatibility guarantee.
- **`internal`** — Sparsh Magic hiring for itself. This is the workflow the specification
  describes.

`TRACK_TRANSITIONS` selects the state table by track, so no handler branches on track.

### A.3 What the internal track already enforces

Each of these is server-side, table-driven, and covered by tests:

| Spec section | Built as | Evidence |
|---|---|---|
| §5 Requisition | `INTERNAL_REQ_TRANSITIONS`, `hrms_requisition_service` | `test_internal_requisition_chain.py` |
| §6 Mandatory budget gate | `assert_sourcing_allowed()`, called by **both** posting and candidate creation; `budget_approval_is_mandatory()` proves `APPROVED` is unreachable without `PENDING_BUDGET` | `test_internal_budget_gate.py` |
| §7 Position scorecard | `hrms_position_scorecards`, dual approval — `required_approvals(managerial)` returns `[MANAGER, MD]` for managerial+, and refuses two signatures from one user | `test_scorecard.py` |
| §8–9 Sourcing & CV screening | postings, public apply, bulk screen (max 200, partial success) | `test_phase4/5` |
| §11 Assessment | `hrms_assessment_service`, dual review, optional per posting | `test_phase6` |
| §12 Panel interview | `hrms_interview_service` + panel composition rules; mandatory Management final round for managerial+ | `test_int2_panel_composition.py`, `test_int2_final_round_gate.py` |
| §13 Shortlisting committee | `hrms_shortlist_service`, `hrms_shortlist_reviews` | `test_int2_shortlist_committee.py` |
| §15 Reference check | `assert_reference_cleared()` runs **before any write** on offer creation; only `Positive` clears | `test_reference_gate.py` |
| §16 Salary within band | `assert_within_band()` reads the band **stamped on the requisition at its budget gate**, never the band master | `test_internal_offer_gates.py` |
| §17 Offer approval | `POST /offers/{no}/approve` (`offer.approve`); create-and-send in one call is **409 on internal**; editing CTC withdraws approval | `test_internal_offer_gates.py` |
| §18 Offer release | issued by HR directly — no client handover exists on this track | — |
| §19 Pre-boarding | `hrms_preboarding_service`, touchpoints + due list + At Risk flag | `test_int2_preboarding.py` |
| §20 Joining & induction | 5 extra induction checklist keys appended **on internal track only** | `test_phase9` |
| §21 Probation | `hrms_probation_reviews`, 1–12 months (default 6), confirm requires typed signature, confirmation closes the requisition | `test_probation.py` |
| §22 Personnel file closure | `POST /personnel-file/close` — 409 unless probation `Confirmed`, 422 on empty note | `test_probation.py` |
| §23 RACI | `ROLE_CAPABILITIES` + `required_approvals()` + panel composition tables | `test_capability_parity.py` |
| §24 Permissions | 84 capabilities, 8 roles, enforced at every route | `test_capability_parity.py` |
| §25 Multi-company | `company_id` is the **only** tenant boundary; per-company departments, salary bands, comm templates, id counters | `test_client_scope.py` |
| §26 SLA targets | `SLA_MILESTONES` — 3 / 2 / 15 / 3 working days + 2 date-anchored. **Matches the spec exactly.** | `test_sla.py`, `test_int2_sla_date_anchored.py` |
| §28 Documentation | `hrms_record_document_service` — 5 printable SOP forms as PDFs | — |
| §29 KPIs | `internal_kpis()` — all 8, with honest denominators | `test_int2_internal_kpis.py` |
| §30 Exceptions | `hrms_exceptions` + `EXCEPTION_UNBLOCKS`. **The only way to bypass a gate** — there is no override flag anywhere in the module | `test_exceptions.py` |
| §31 Compliance | PII behind capabilities; statutory pre-employment gate on confirmation; EEO + data-use acknowledgements | `test_int2_statutory_gate.py` |
| §32 Retention | `RETENTION_YEARS` stamps `retention_until`; purge **proposes → MD approves → redacts** (never hard-deletes) | `test_int2_retention_purge.py` |
| §33 Policy review | `hrms_policies` + `hrms_policy_revisions` (Modification History) | `test_int2_policy_register.py` |
| §37 Audit trail | append-only `hrms_audit_log`, every service writes through it | — |
| §41 Entities | 15 of the ~21 conceptual entities exist, under these names | — |

### A.4 Reusable infrastructure (do not rebuild)

- **Scheduler**: `start_reminder_scheduler()` — an asyncio task on a 60s tick with hour-gated
  daily jobs and per-job last-run memory. Extend this; do not add a second runner.
- **Notifications**: `hrms_notify_service` fan-out by user or by governance role.
- **Documents**: typed, versioned, S3-backed, owner-linked.
- **Audit**: one `audit()` call site pattern across all 34 services.
- **Working-day maths**: `working_days_between()` / `add_working_days()` in `hrms_sla_service`.
- **Holiday master**: the ERP has a `holidays` collection and module — **HRMS does not use it yet.**

---

## B. Gap analysis — specification vs. built code

Ten items. Everything else in the specification is already built.

| # | Gap | Spec § | Severity | Classification |
|---|---|---|---|---|
| 1 | ~~**No scheduler wiring.**~~ **CLOSED — Phase INT-3, 2026-08-14.** `hrms_scheduler_service` now drives all five sweeps from the ERP's existing reminder loop. See [§Gap 1 — closed](#gap-1--closed-phase-int-3) below. | §27 | ~~Critical~~ | Done |
| 2 | ~~**No telephonic screening stage.**~~ **CLOSED — Phase INT-4, 2026-08-15.** The record, the two statuses, the work queue and a gate on interview scheduling. See [§Gap 2 — closed](#gap-2--closed-phase-int-4). | §10, §36 | ~~High~~ | Done |
| 3 | **Working days ignore public holidays.** `working_days_between()` skips Saturday/Sunday only. The ERP has a holidays master; SLA maths does not read it. Documented as a deliberate deferral, but the spec asks for it explicitly. | §26, §42 | **High** | Extend |
| 4 | **No per-company configuration.** `COLL_SETTINGS = "hrms_settings"` is declared and referenced nowhere else. SLA targets, retention years, managerial threshold, probation default, score bands and reminder intervals are all module constants. Multi-company works for *data*; it does not work for *rules*. | §42, §25 | **High** | New |
| 5 | **Salary negotiation is a gate, not a record.** `assert_within_band()` enforces the rule correctly and names the direction (above/below) in its refusal, and `Offer Outside Budget` is the sanctioned exception. But there is no negotiation entity: no rounds, no candidate-expectation-vs-proposed-vs-approved comparison surface, no history of prior figures. | §16 | Medium | New |
| 6 | **KPI dashboard filters are date-range only.** `internal_kpis(actor, company_id, date_from, date_to)`. The spec asks for department, position, HR owner, HOD, position level and status. | §29 | Medium | Extend |
| 7 | **Internal requisition tracker is thin.** `InternalRequisitionList` renders 5 columns (Requisition, Seats, Approved band, Waiting on, actions). The spec asks for ~20 including candidate count, shortlist/interview/offer status, joining date, probation end date, SLA status/due, days elapsed and exception status. | §35 | Medium | Extend |
| 8 | **Record-level notifications missing.** The requisition approval chain is well covered (25 call sites). `hrms_scorecard_service`, `hrms_reference_service`, `hrms_probation_service` and `hrms_exception_service` emit **zero** notifications — so "probation confirmation required" and "exception approval required" never reach anyone. | §38 | Medium | Extend |
| 9 | **Candidate communication is _partly_ automated.** *(Corrected 2026-08-15 — the original wording overstated this.)* `AUTO_COMM_EVENTS` already fires **application acknowledgement** on public apply and **rejection closure** on screening rejection, via `fire_event()`. What is genuinely manual: the `stage_update` cadence and `interview_scheduled` — and the latter's **24-hour notice rule is neither enforced nor measured**. `offer_summary` and `stage_update` are in `MANUAL_COMM_TEMPLATES` **on purpose**, so automating them would reverse a documented decision. | §34 | Low | Extend |
| 10 | **Score bands: spec says three, code has four.** The spec §13 gives 4.0+ / 3.0–3.99 / <3.0. The code implements the signed SOP's **four** bands (Strong / Consider / Hold / Reject) via `SCORE_BANDS`. Spec §13 also says *"if scoring logic exists, reuse it."* | §13 | **Decision** | Conflict |

### Gap 1 — closed (Phase INT-3)

Implemented 2026-08-14. **54/54 test files pass**, including 78 new checks.

| Change | File |
|---|---|
| The driver — five jobs, the run ledger, the per-record guards | `services/hrms_scheduler_service.py` (new, 412 lines) |
| Wired into the ERP's existing 60-second loop | `services/reminder_scheduler.py` |
| `SCHEDULED_JOBS` table, `COLL_JOB_RUNS`, `PROBATION_REMINDER_DAYS`, the unique index | `models/hrms.py` |
| Tests | `services/hrms/tests/test_int3_scheduler.py` (new, 78 checks) |
| Docstrings that claimed nothing drove them | `hrms_sla_service`, `hrms_policy_service`, `scripts/hrms_retention_purge.py` |

**No second scheduler was introduced** and **no governance logic moved** — each job calls the
service that already owns the decision, so the rules stay in one place.

Three decisions worth recording, because a rewrite would lose them:

1. **The run ledger is a collection, not a dict.** The TPMS jobs beside it remember their
   last run in process memory, which is correct for them — they are idempotent syncs.
   Re-running a *reminder* job sends the reminder again, and memory resets on every deploy.
2. **Two independent guarantees.** The ledger stops a job running twice in a period; the
   per-record guards (`sla_escalated`, `reminders_sent`, an existing `Proposed` batch) stop a
   record being notified twice even if it does. The second is what makes the house
   convention — stamp on success, retry on failure — safe for something that sends email.
3. **The retention job proposes and never executes.** It refuses to write an empty batch and
   refuses to stack a second proposal while one awaits a decision. A test greps the module to
   prove it cannot call approve or execute at all.

Not included, deliberately: **the SLA targets these jobs measure against are still the
module constants.** Making them per-company is Gap 4, and doing it here would have meant
shipping a configuration service inside a wiring change.

### Gap 2 — closed (Phase INT-4)

Implemented 2026-08-15. **55/55 test files pass**, including 77 new checks. Frontend builds
clean.

| Change | File |
|---|---|
| The record, the scoring, the status moves, the gate, the work queue | `services/hrms_telephonic_service.py` (new, 489 lines) |
| 2 statuses + `STAGE_RANK` + `PIPELINE_COLUMNS` + `FORWARD_TRANSITIONS` edges, 2 capabilities, `TELEPHONIC_CRITERIA`, a new exception type + gate, retention, purge target, 4 indexes, 2 Pydantic models | `models/hrms.py` |
| The gate call, inside the internal-track branch | `services/hrms_interview_service.py` |
| 5 endpoints | `routes/hrms.py` (173 → 178) |
| `TelephonicBoard` + route + tab strip + `CAP` map + API client | `frontend/src/…` |
| Tests | `test_int4_telephonic.py` (new, 77 checks) |

**Where the gate sits: interview scheduling, not the record.** The SOP puts the call before
*the panel*, so `assert_telephonic_cleared` guards entry into interviewing — asked first,
because being told to make a ten-minute call is a cheaper refusal than being told the panel is
wrong after assembling one.

Four decisions worth recording:

1. **It is a gate, not a warning.** Annexure C chose "warn, never block" for interview
   *windows* — a scheduling convenience, where a hard refusal pushes an urgent booking
   off-system. A skipped screening *stage* is a deviation from the documented process, and the
   SOP already names the mechanism for those: a new `Telephonic Screening Waived` exception
   type, added the same way INT-2 added the statutory one. There is no override flag.
2. **`No Answer` is a third outcome that moves nobody.** Without it, an unreachable candidate
   forces HR to choose between recording a rejection they did not decide and recording
   nothing — and "nothing" is what makes a pipeline look stalled for no visible reason.
3. **Both statuses rank 2, with `Shortlisted`.** A phone screen is a decision *about* a
   shortlisted candidate, the same reasoning the client-share band already follows. Ranking it
   3 would have pushed assessment and interview up and renumbered every Phase 10 figure.
4. **An in-flight candidate is not gated retroactively.** The gate is silent once any interview
   record exists, so shipping this could not strand anybody already mid-pipeline behind a call
   nobody can go back and make.

**Two things the new test caught in code I had just written**, recorded because both are the
kind of bug that passes review: `update_screening` read `current` *after* writing to it (works
against real Mongo, silently does nothing against a fake — now captured before the write), and
`test_int2_panel_composition` began failing because its internal candidates had no phone screen
(its fixtures now carry one, so a failure there still names the right control).

### Not a gap, but worth knowing

- **Client-scope narrowing is a shipped primitive that is not wired to pipeline surfaces**
  (`assert_client_allowed`, `require_engagement`). This affects the **client** track only —
  it is not a blocker for Sparsh Magic internal hiring. Do not provision a real client user
  until it is wired.
- **Leave, attendance and payroll are not built** and are out of this scope.
- **The spec's §36 flat status lifecycle does not match the implementation, by design.** The
  module separates *requisition approval status* from *candidate status* — one requisition
  carries many candidates at different stages, so a single flat lifecycle cannot represent
  the real state. This is a better model and should not be "corrected".

---

## C. Proposed architecture for the remaining work

Minimum change, maximum reuse. No new module, no new scheduler, no new design language.

### C.1 Scheduler (gap 1) — the priority

Extend `services/reminder_scheduler.py` following the **existing TPMS pattern**: an hour
constant, a gate on `hour >= N`, and a separate last-run memory per job so one failure never
consumes another's slot.

```
HRMS_SLA_SWEEP_HOUR      = 7   daily  -> sweep_open_breaches()   per hrms-enabled company
HRMS_PROBATION_HOUR      = 7   daily  -> tiered reminders at 30 / 15 / 7 / 1 days
HRMS_PREBOARDING_HOUR    = 8   daily  -> due_touchpoints() + joining-date reminders
HRMS_POLICY_REVIEW_HOUR  = 8   weekly -> notify_due_reviews()
HRMS_RETENTION_HOUR      = 3   weekly -> purge_service.propose() ONLY (never approve)
```

Two rules this must honour:

1. **The purge job proposes; it never executes.** Execution stays behind
   `POST /purge-batches/{batch_no}/approve`, the MD's capability and a typed signature.
   Invariant 15 ("the purge redacts, never hard-deletes, and never runs without an approval")
   is not negotiable.
2. **Reminders need sent-state**, or a 60s loop re-notifies all day. Follow
   `reminder_scheduler`'s own `REMINDER_MAX_AGE_HOURS` / `sent` flag convention rather than
   inventing a second one.

Companies to iterate: those with `companies.hrms_enabled` true.

### C.2 Configuration service (gap 4)

Implement the already-declared `hrms_settings` collection as a **per-company overlay over the
existing constants** — not a replacement for them.

```python
async def hrms_config(company_id: str) -> dict:
    """Module defaults, overlaid with this company's overrides. Defaults are the constants
    that ship today, so a company with no settings row behaves exactly as it does now."""
```

Overridable: SLA target days per milestone, retention years per record type, probation
default duration, managerial threshold (`MANAGERIAL_LEVELS`), reminder intervals, score-band
floors, assessment-required default, holiday-calendar opt-in.

**This is what makes §25 multi-company real.** Today a second Sparsh group entity would share
one hard-coded rule set. Data is already per-company; rules are not.

### C.3 Holiday-aware working days (gap 3)

Add an optional holiday set to `working_days_between()` / `add_working_days()`, loaded per
company from the ERP `holidays` collection and **gated on the config flag from C.2**.

The existing deferral note is right that honouring holidays *silently* would make two
companies disagree about whether the same requisition breached. Making it an explicit,
per-company setting resolves that objection without losing the capability.

### C.4 Telephonic screening (gap 2)

New collection `hrms_telephonic_screenings`, carrying `request_no` and `uk` (invariant 12).
Two new `AppStatus` values plus their `STAGE_RANK` entries and `FORWARD_TRANSITIONS` edges —
**rank 2, alongside `Shortlisted`**, because a phone screen is a decision *about* a
shortlisted candidate, exactly as the client-share band is.

> Adding a status without its `STAGE_RANK` entry silently ranks it 0 — counted in totals,
> credited to no funnel stage. This is trap #9 in the overview.

Capture per the spec: communication, notice period, salary expectation, location,
availability, motivation, role understanding, suitability, comments, score.

### C.5 Salary negotiation record (gap 5)

New collection `hrms_salary_negotiations` (`request_no` + `uk`), one row per round: candidate
expectation, proposed CTC, the approved band as it stood, the computed verdict
(`within` / `above` / `below`), who proposed, when, and the linked exception if above.

**The gate does not move.** `assert_within_band()` stays the enforcement point; the
negotiation record is the history and the comparison surface the spec asks to *display*.

### C.6 Everything else

- Gap 6 — add filter parameters to `internal_kpis()`, reusing the existing `_scope()` and
  `SCAN_CAP` guards. **Analytics still never writes** (invariant 8; the test greps source
  text for `insert_` / `update_` / `delete_`, comments included).
- Gap 7 — extend `InternalRequisitionList` columns from data the API already returns plus one
  aggregate endpoint. Nothing computed in the browser (invariant 9).
- Gap 8 — add `notify_hrms_role` / `notify_user` calls at the four silent services.
- Gap 9 — drive template sends from the C.1 jobs; measure interview notice in the SLA table.

### C.7 What must not change

| Invariant | Why it matters here |
|---|---|
| `company_id` is the only tenant boundary | multi-company (§25) rests entirely on it |
| Filters fail closed (`$in: []`, never absent) | a widening filter is a data leak |
| Every stage move through `FORWARD_TRANSITIONS` | new telephonic statuses must use the graph |
| Every approval through `TRACK_TRANSITIONS` | no branching on track inside handlers |
| A gate is bypassed only by an approved exception | no override flags, ever |
| Analytics never writes | enforced by a source-text grep test |
| Frontend `CAP` map == backend `Cap` enum | else controls silently vanish |
| Client track behaviour is byte-for-byte preserved | every new control keys on `track == internal` and returns early |

---

## D. Database changes

### New collections (4)

| Collection | Purpose | Carries |
|---|---|---|
| `hrms_settings` | per-company rule overrides (declared today, unused) | `company_id` — config, so no `request_no`, same reason `hrms_document_types` has none |
| `hrms_telephonic_screenings` | gap 2 | `company_id`, `request_no`, `uk` |
| `hrms_salary_negotiations` | gap 5 | `company_id`, `request_no`, `uk` |
| `hrms_job_runs` | scheduler last-run + sent-state ledger | `company_id`, `job_key`, `last_run_at` |

### Modified models — `models/hrms.py` only

- `AppStatus`: `TELEPHONIC_PASSED`, `TELEPHONIC_REJECTED`
- `STAGE_RANK`: both at rank 2
- `FORWARD_TRANSITIONS`: edges in from `Shortlisted`, out to assessment/interview
- `ID_FORMATS`: `TEL-`, `NEG-`
- `Cap`: `telephonic.read/write`, `negotiation.read/write`, `settings.read/write`
  — **and the identical additions to `frontend/src/features/hrms/access.js`**
- `ROLE_CAPABILITIES`: HR gets telephonic + negotiation write; MD/FINANCE get settings write
- `SLA_MILESTONES` / `RETENTION_YEARS`: unchanged as **defaults**, read through the config
  overlay rather than directly

### Indexes

```
hrms_telephonic_screenings   (company_id, request_no)   (company_id, uk)
hrms_salary_negotiations     (company_id, request_no)   (company_id, uk)
hrms_settings                (company_id) unique
hrms_job_runs                (company_id, job_key) unique
```

### No migration is required

Every change is additive. Existing requisitions have no `requisition_track` field and
`track_of()` already reads that absence as `client`. Existing companies have no `hrms_settings`
row and the overlay falls through to today's constants. **No existing document is rewritten.**

---

## E. API changes

### New endpoints

```
GET    /hrms/settings                          settings.read     per-company config + defaults
PATCH  /hrms/settings                          settings.write    override; validated per key

GET    /hrms/telephonic-screenings             telephonic.read
POST   /hrms/telephonic-screenings             telephonic.write  201
GET    /hrms/telephonic-screenings/{tel_no}    telephonic.read
PATCH  /hrms/telephonic-screenings/{tel_no}    telephonic.write  records outcome + score

GET    /hrms/negotiations                      negotiation.read  ?uk= filter
POST   /hrms/negotiations                      negotiation.write 201; computes the verdict
GET    /hrms/candidates/{uk}/negotiation       negotiation.read  comparison surface
```

### Modified endpoints

| Endpoint | Change | Compatibility |
|---|---|---|
| `GET /hrms/analytics/internal-kpis` | + `department_id`, `designation_id`, `designation_level`, `hr_user_id`, `hod_user_id`, `status` | all optional; omitting all reproduces today's response exactly |
| `GET /hrms/requisitions` (internal track) | + tracker aggregate fields | additive keys only |
| `GET /hrms/requisitions/{no}/sla` | reads targets through the config overlay | identical output with no settings row |
| `POST /hrms/candidates/screen` | `telephonic` action added to `ScreenAction` | existing actions unchanged |

**No endpoint is removed, renamed or given a required parameter it did not have.**

---

## F. UI changes

### New screens (3)

| Route | Component | Placement |
|---|---|---|
| `/hrms/telephonic-screening` | `TelephonicBoard` | workspace tab strip (a hiring stage) |
| `/hrms/negotiations` | `NegotiationBoard` | workspace tab strip |
| `/hrms/settings` | `HrmsSettings` | sidebar, admin-only (governance) |

> The sidebar list and the workspace tab strip **must stay disjoint** — a route in
> `HRMS_WORKSPACE` must not also appear in `hrmsSubmodules`.

### Modified screens (3)

- `InternalRequisitionList` — the full tracker column set, with status badges reusing the
  existing `statusConfig` vocabulary and an SLA health indicator.
- `RecruitmentDashboard` — filter bar on the `internal_kpis` block (it already renders
  `data.internal_kpis` via `KpiGrid`).
- `CandidateJourney` — telephonic and negotiation events on the existing timeline.

All of it reuses `HrmsPageHeader`, `HrmsScopeBar`, `HrmsStates`, the existing table/card
responsive pattern and Tailwind utilities. **No new design language, no custom CSS.**

---

## G. Scheduler jobs

| Job | Frequency | Condition | Action | Notification |
|---|---|---|---|---|
| `hrms_sla_sweep` | daily 07:00 | internal requisitions with open milestones | `sweep_open_breaches()` | approaching → owner; breached → owner + Management |
| `hrms_probation_reminders` | daily 07:00 | probation `Pending`, `ends_on` in 30/15/7/1 days | tiered reminder, one per tier per record | HOD + HR; Management for managerial+ |
| `hrms_preboarding_reminders` | daily 08:00 | accepted offers with a future joining date | `due_touchpoints()` + At Risk flag | HR owner |
| `hrms_policy_review` | weekly Mon 08:00 | policy review date due | `notify_due_reviews()` | HR + Management |
| `hrms_retention_propose` | weekly Sun 03:00 | records past `retention_until` | `purge_service.propose()` — **proposal only** | MD: batch awaiting approval |

Each iterates companies with `hrms_enabled`, records its run in `hrms_job_runs`, and is
remembered independently so one failure never consumes another's slot.

**Nothing on this list deletes anything.** The retention job creates a proposal; only an MD
with `retention.purge` and a typed signature causes redaction.

---

## H. Migration strategy

There is nothing to migrate. Stated explicitly because the specification asks:

1. **No schema is rewritten.** All four new collections are new; all model changes are new
   enum members and new optional fields.
2. **Existing recruitment data is untouched.** Client-track requisitions carry no
   `requisition_track` field; `track_of()` reads absence as `client`. That default is the
   compatibility guarantee and it is already in place.
3. **Existing internal-track records keep working.** The config overlay returns today's
   constants when no settings row exists.
4. **Rollback** is removing the new routes and the scheduler constants. No data written by
   the new code is read by the old code.
5. **The one behaviour change to stage deliberately** is holiday-aware SLA maths: it alters
   whether a requisition is reported as breached. It ships **off**, per company, behind the
   config flag — turning it on is a business decision with a visible date.

---

## I. Testing plan

House convention throughout: **no pytest, no live DB, `FakeCollection`, ASCII output, exit 1
on failure**, one self-contained file per area.

### Regression first (before any change)

```bash
cd backend
for f in app/services/hrms/tests/test_*.py; do
  .venv/Scripts/python.exe -m "app.services.hrms.tests.$(basename $f .py)"
done
```

Current baseline: **53/53 pass.** This must still read 53/53 after every gap is closed, plus
the new files below.

### New test files

| File | Asserts |
|---|---|
| `test_int3_scheduler.py` | each job selects the right records; is idempotent across two ticks in one day; a failure in one job does not consume another's slot; **the retention job proposes and never executes** |
| `test_int3_config.py` | absent settings row reproduces the constants exactly; an override changes the SLA due date; an invalid key is refused; one company's override does not reach another |
| `test_int3_telephonic.py` | new statuses have `STAGE_RANK` entries; illegal transitions 409; the funnel stays monotonic; capability enforced |
| `test_int3_negotiation.py` | verdict is correct within/above/below; above-band still requires an exception; **`assert_within_band` remains the enforcement point** |
| `test_int3_holidays.py` | flag off → weekends only (today's answer, unchanged); flag on → a company holiday extends the due date; two companies with different calendars get different answers |
| `test_int3_notifications.py` | probation-due reaches the HOD; exception-pending reaches Management; no notification fires twice for one event |

### Existing tests that must be extended, not replaced

- `test_capability_parity.py` — the six new capabilities in **both** files.
- `test_e2e_recruitment_journey.py` §13 — the structural assertion that every internal control
  keys on `track == internal`. Extend it to cover telephonic and negotiation.
- `test_phase10_analytics.py` — the read-only grep. **Do not write the literal tokens
  `insert_`, `update_` or `delete_` in `hrms_analytics_service.py`, comments included.**

### Manual end-to-end, per role

Run one internal requisition through HR → HOD → Management/Finance, asserting at each gate
that the role *without* the capability is refused **by the API**, not merely by a hidden
button. Then repeat for a managerial+ role and confirm the Management stages engage, and for
a non-managerial role and confirm they do not.

---

## Recommended sequence

| | Work | Why this order |
|---|---|---|
| ~~1~~ | ~~**Scheduler wiring** (gap 1)~~ — **done 2026-08-14** | Every SOP reminder and escalation was dead. Highest value, lowest risk — the functions existed and were tested. |
| 2 | **Config service + holiday calendar** (gaps 4, 3) | Unblocks genuine multi-company. Everything after it can read config rather than constants. |
| ~~3~~ | ~~**Telephonic screening** (gap 2)~~ — **done 2026-08-15** | The one real pipeline stage that was missing. Shipped ahead of gaps 3/4 because it was the only hard ✗ in the SOP's process flow. |
| 4 | **Tracker + KPI filters + notifications** (gaps 6, 7, 8) | Visibility work, no new gates. |
| 5 | **Negotiation record** (gap 5) | The rule is already enforced; this adds the history. |
| 6 | **Automated candidate comms** (gap 9) | Depends on the scheduler from step 1. |

**Open question before step 1:** gap 10 — three score bands (this specification) or four (the
signed SOP, and what the code does)? Recommendation: **keep the four**. The SOP is the signed
policy, spec §13 itself says to reuse existing scoring logic, and once the config service in
step 2 lands the floors become a per-company setting rather than a code decision.
