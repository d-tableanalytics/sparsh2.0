# HRMS Replication Roadmap — FocusPrint → Sparsh ERP

**Status:** analysis complete, no code written.
**Target branch:** `BHU_HRMS_30JULY` (currently at `c7fa9dc`, working tree clean).
**Reference project:** `C:\Users\Admin\Desktop\FOCUSPRINT\focusprint`
**Target project:** `C:\Users\Admin\Desktop\sparshm\sparshN\sparsh2.0`

> Scope note: this replicates the **HRMS** module only. FocusPrint also ships CRM, Delegation,
> Checklist and Task Center — Delegation/Checklist already have a stronger equivalent in Sparsh
> (Task & Delegation), and CRM is explicitly out of scope.

---

## 1. Project comparison

| | FocusPrint (source) | Sparsh ERP (target) |
|---|---|---|
| Backend | Next.js 14 App Router, route handlers | FastAPI (Python), APIRouter modules |
| Language | TypeScript | Python + JavaScript (no TS) |
| **Database** | **PostgreSQL (Neon), relational, 37 tables** | **MongoDB (motor), document, per-feature collections** |
| Schema | `scripts/schema.sql`, migration script | Pydantic models in `app/models/`, no migrations |
| Frontend | Next.js pages + React Query | React 18 + Vite + React Router, axios + local state |
| Auth | Signed cookie, **plaintext passwords** | JWT (jose) + bcrypt (`passlib`), `staff` / `learners` collections |
| Authz | `role` string + `user_permissions(username, permission)` | `permissions.{module}.{create,read,update,delete}` dict on the user doc |
| Files | S3 (`@aws-sdk`), local fallback | S3 (`services/s3_service.py`) |
| Notifications | In-app + email outbox (nodemailer) | In-app + **email + WhatsApp (Meta Cloud API)** + templates + logs |
| Background jobs | None (cron via HTTP GET) | `reminder_scheduler` asyncio loop (60 s) in `main.py` lifespan |
| UI kit | Tailwind, framer-motion, lucide-react, SweetAlert2 | Tailwind, framer-motion, lucide-react, custom Modal/Button |

**The defining fact:** the two systems share a UI vocabulary (Tailwind + framer-motion +
lucide-react) but nothing below it. Every table becomes a collection, every SQL query becomes a
Mongo pipeline, every route handler becomes a FastAPI endpoint. **Treat this as a
re-implementation against a spec, not a port.** The reference repo is the specification; the
only artefacts that transfer close to verbatim are business *rules* (payroll constants,
state machines) and *screen layouts*.

### Sparsh conventions the HRMS build must follow

- Routers in `app/routes/<module>.py`, registered in `main.py` with `prefix="/api"`.
- Pydantic models in `app/models/<module>.py`; `id` aliased from `_id`.
- Cross-cutting logic in `app/services/`; shared predicates in `app/controllers/auth_controller.py`.
- Every mutation calls `log_activity(...)` (`services/activity_log_service.py`).
- Notifications go through `send_notification_from_template(user, slug, context, delivery, scope)` —
  never hand-rolled email.
- Frontend pages in `src/pages/`, feature components in `src/components/<feature>/`,
  API wrappers in `src/services/`.
- Route guarding via `PrivateRoute` + a module gate component (`RequireTaskAccess` is the pattern).

---

## 2. HRMS module inventory (source of truth)

26 HRMS tables, 30 API routes, ~9,900 LOC of pages, ~5,100 LOC of API, ~3,700 LOC of lib.

| # | Module | Tables | API routes | Pages |
|---|---|---|---|---|
| 1 | Requisition (FMS) | `hrms_requisitions` | `requisitions`, `/approve`, `/close` | `/hrms/fms` |
| 2 | Job Descriptions | `hrms_job_descriptions` | `jd`, `jd/approve` | `/hrms/jd` |
| 3 | Job Postings + public apply | `hrms_job_postings`, `hrms_candidates` | `postings`, `apply/[code]` | `/hrms/postings`, `/apply/[code]` |
| 4 | Screening | `hrms_candidates` | `candidates`, `/screen`, `/journey` | `/hrms/screening`, `/hrms/candidates` |
| 5 | Assessments | `hrms_assessments` | `assessments`, `/[code]` | `/hrms/assessments`, `/assess/[code]` |
| 6 | Interviews | `hrms_interviews` | `interviews`, `/evaluate` | `/hrms/interviews` |
| 7 | Offers | `hrms_offers` | `offers`, `/[code]` | `/hrms/offers`, `/offer/[code]` |
| 8 | Onboarding | `hrms_onboarding` | `onboarding`, `/[code]` | `/hrms/onboarding`, `/onboard/[code]` |
| 9 | Employee Master | `hrms_employees`, `hrms_employee_events`, `hrms_counters` | `employees`, `/[code]` | `/hrms/employees`, `/[code]` |
| 10 | Org Structure | `hrms_departments`, `hrms_designations`, `hrms_locations` | `org` | `/hrms/org` |
| 11 | Exit Documentation | `hrms_exit_documents` | `employees/[code]/exit-docs` | employee profile tab |
| 12 | Attendance | `hrms_attendance`, `hrms_punch_segments` | `attendance`, `/team` | `/hrms/attendance` (tabs) |
| 13 | Leave | `hrms_leaves`, `hrms_leave_balances` | `leaves` | attendance tab |
| 14 | Payroll | *(nothing persisted)* | `payroll` (GET) | attendance tab |
| 15 | Holidays | `hrms_holidays` | `holidays` | attendance tab |
| 16 | HR Dashboard | — | reuses list APIs | `/hrms/dashboard` |
| 17 | Reports | — | reuses list APIs | `/hrms/reports` |
| 18 | Notifications | `hrms_notifications`, `hrms_email_outbox`, `hrms_audit_log` | `notifications` | `NotificationBell` |
| 19 | Settings / RBAC | `hrms_settings`, `user_permissions` | `admin/settings` | `/settings` |

**Recruitment (1–8) is the mature half** — the source's own audit rates it 70–85 %.
**Attendance/Leave/Payroll (12–14) are the weak half** — rated 45 % / 25 % / 15 %.

> The bundled `HRMS_ENTERPRISE_AUDIT.md` is **stale in one important place**: it reports Employee
> Master and Org Structure as 0 %/absent, but `hrms_employees`, `hrms_employee_events`,
> `hrms_departments/designations/locations`, `hrms_exit_documents`, `lib/server/employees.ts`
> (382 LOC) and the `/hrms/employees` + `/hrms/org` pages all exist. Those modules were built
> after the audit. Read the audit for *defects*, read the code for *scope*.

---

## 3. Feature mapping — HRMS feature vs Sparsh today

Legend — **Build**: nothing comparable exists · **Extend**: Sparsh has it, needs HR fields/flows ·
**Reuse**: use as-is.

| HRMS feature | Exists in Sparsh? | Verdict | Notes |
|---|---|---|---|
| Authentication / session | Yes — JWT + bcrypt, `staff`/`learners` | **Reuse** | Sparsh's is strictly better. Do **not** port FocusPrint's plaintext auth. |
| User directory | Yes — `routes/user.py`, `UserManagement.jsx` | **Extend** | Becomes the join point for Employee Master. |
| Employee Master (profile, codes, lifecycle) | No | **Build** | New `hrms_employees` collection keyed to `staff`/`learners` `_id`. |
| Employee timeline / history | No | **Build** | Mirrors `hrms_employee_events`. Sparsh has `activity_logs` — reuse the writer, separate the read model. |
| Departments master | Partial — free-text `department` on user (`HOD/Implementor/EA/MD/Other`) | **Extend** | Promote to a master collection; keep the existing values as seed. |
| Designations master | Partial — free-text `designation` on user | **Extend** | Same pattern. |
| Locations master | No | **Build** | |
| Org chart / reporting lines | Partial — `reporting_manager` on user | **Extend** | Field exists and is already used by Task & Delegation. Add the chart view. |
| Company/multi-tenant scoping | Yes — `company_id` everywhere, `companies` collection | **Reuse** | FocusPrint is single-tenant; **this is Sparsh's biggest addition and must be designed in from day one.** |
| Holidays | **Yes — `routes/holiday.py`, `models/holiday.py`, `Holiday.jsx`** | **Reuse/Extend** | Direct hit. Sparsh's model is richer (type, status, description). Only needs company scoping + a payroll consumer. |
| Attendance (employee punch) | No | **Build** | ⚠️ Sparsh already uses "attendance" for **LMS session attendance** — see Risk R-4. |
| Leave application/approval | No | **Build** | |
| Leave balances / accrual | No | **Build** | |
| Payroll engine | No | **Build** | Port the *rules*, not the code. Persist runs (source doesn't). |
| Requisition (FMS) | No | **Build** | Approval chain maps well onto Sparsh's existing permission checks. |
| Job Descriptions | No | **Build** | |
| Job Postings + public apply link | No | **Build** | ⚠️ First **unauthenticated public endpoint** in Sparsh — see Risk R-5. |
| Candidate pipeline / screening | No | **Build** | |
| Assessments | No | **Build** | Sparsh has `AssessmentPlayer.jsx` for **LMS quizzes** — different domain, do not merge. |
| Interviews + scorecards | Partial — calendar events + reminders | **Extend** | Schedule as a `calendar_event` type so it lands on the existing calendar and reminder scheduler. |
| Offers + public accept | No | **Build** | |
| Onboarding (KYC + checklist) | No | **Build** | |
| Exit documentation | No | **Build** | |
| File upload / storage | Yes — `services/s3_service.py` | **Reuse** | Add a gated `documents/` prefix with authz (source has none — Risk R-6). |
| Notifications: in-app | Yes — `notification.py`, `NotificationDrawer.jsx` | **Reuse** | |
| Notifications: email templates | Yes — `settings/templates`, `send_notification_from_template` | **Reuse** | Add HRMS slugs; no new engine. |
| Notifications: WhatsApp | Yes — Meta Cloud API | **Reuse** | Source has none. Free capability gain. |
| Notification audit log | Yes — `NotificationLog` | **Reuse** | Covers `hrms_email_outbox`. |
| Audit log | Yes — `activity_log_service` | **Reuse** | Covers `hrms_audit_log`. |
| Reports + CSV export | Yes — `services/report_service.py` (806 LOC), `ReportsDashboard.jsx` | **Extend** | Add HRMS report types to the existing framework. |
| Dashboard KPIs | Yes — `routes/dashboard.py` | **Extend** | Add an HRMS section. |
| Scheduled/background jobs | Yes — `reminder_scheduler` | **Reuse** | Hook probation/leave-accrual/exit-alert jobs into the existing loop. |
| Settings / config store | Yes — `routes/settings.py`, `system_settings.py` | **Reuse** | Covers `hrms_settings`. **Validate numeric keys** — source doesn't (Risk R-7). |
| Role & permission model | Yes — per-module CRUD dict | **Extend** | Add `hrms`, `attendance`, `payroll`, `recruitment` modules to the dict. |
| Module on/off per company | Yes — `orm_enabled`, `delegation_enabled` | **Extend** | Add `hrms_enabled`, same pattern. |
| Task delegation | Yes — richer than source | **Reuse** | Onboarding/exit checklists can be delegation tasks instead of a new engine. |

**Summary: 13 reuse · 11 extend · 17 build.** Roughly 40 % of the work is already standing
in Sparsh — mostly the plumbing (auth, notifications, files, audit, settings, reports, scheduler).

---

## 4. Deep analysis

### 4.1 Database — relational → document

Sparsh has no migration tooling; collections are created implicitly and models are Pydantic.
Follow that, but **do not naively make one collection per table.**

| Source tables | Sparsh collection | Rationale |
|---|---|---|
| `hrms_requisitions` | `hrms_requisitions` | 1:1. Collapse the 27 numbered `planned_N/actual_N` sheet columns into a `steps: [{step, planned, actual, by, remarks, delay}]` array — the source itself calls these a sheet-port artefact. |
| `hrms_candidates` + `hrms_assessments` + `hrms_interviews` + `hrms_offers` | `hrms_candidates` with embedded `assessments[]`, `interviews[]`, `offers[]` | All are 1-candidate-scoped, always read together (the "candidate journey"), and bounded in size. One read replaces four joins. |
| `hrms_job_descriptions`, `hrms_job_postings` | `hrms_jds`, `hrms_postings` | Keep separate — postings fan out per platform. |
| `hrms_onboarding` | embed into `hrms_candidates.onboarding` | Single record per candidate. |
| `hrms_employees` | `hrms_employees` | 1:1. Link to `staff`/`learners` by `user_id`, not by username string. |
| `hrms_employee_events` | `hrms_employee_events` | Keep separate — unbounded growth. |
| `hrms_departments/designations/locations` | `hrms_org_masters` with a `kind` discriminator | Three near-identical shapes; one collection with `kind: department|designation|location` matches Sparsh's `task_meta` precedent. |
| `hrms_attendance` + `hrms_punch_segments` | `hrms_attendance`, one doc per (user, date), `segments: []` embedded | Bounded per day; removes the source's dual-source-of-truth bug. |
| `hrms_leaves` | `hrms_leaves` | 1:1. |
| `hrms_leave_balances` | `hrms_leave_balances` | 1:1, `(user_id, year)` unique. |
| `hrms_holidays` | **existing `holidays`** | Reuse. Add `company_id`. |
| `hrms_settings` | **existing settings store** | Reuse. |
| `hrms_notifications`, `hrms_email_outbox`, `hrms_audit_log` | **existing `notifications`, `notification_logs`, `activity_logs`** | Reuse all three. |
| `hrms_counters` | `counters` | Atomic `findOneAndUpdate($inc)` for `EMP-YYYY-NNNN`. |
| `user_permissions` | **existing `permissions` dict on the user** | Reuse. |

**Indexes to create explicitly** — the source audit calls missing indexes its "systemic defect".
Sparsh has the same risk (no migration step). Add an idempotent index-ensure on startup:
`hrms_employees(company_id, status)`, `(user_id)`, `(employee_code unique)`;
`hrms_attendance(user_id, punch_date unique)`; `hrms_leaves(user_id, status)`;
`hrms_candidates(company_id, stage)`; text index for directory search.

### 4.2 Backend APIs

30 source routes → roughly 40 FastAPI endpoints (Next.js multiplexes verbs on one handler;
FastAPI splits them). Naming: `/api/hrms/<resource>`, mounted as one `hrms` router group or
several (`hrms_core`, `hrms_recruitment`, `hrms_attendance`) — prefer several, matching how
Sparsh already splits `orm`, `orm_sheet`, `orm_requests`.

Every endpoint takes `current_user: dict = Depends(get_current_user)` and a module gate
(`require_hrms_access`, modelled on `require_task_access`).

### 4.3 Business logic worth porting verbatim

The payroll rule set is the single densest piece of domain logic and is **already correctly
isolated** in `lib/payroll/config.ts` — pure constants, no magic numbers in the engine. Port it
as a Python dataclass 1:1:

- Shift 09:00–17:00, 8 h/day; salary spread over the month's **actual** day count.
- Late > 09:10 → flat ₹100; late > 09:15 → 1 h salary deducted.
- OT accrues from 17:00, paid only in **completed hours** (17:45 → 0, 18:00 → 1 h), ×1.0.
- Unauthorized leave → 2-day penalty; rejected-leave absence → 2-day penalty.
- 2 paid leaves/year; 9 official holidays/year.
- \> 15 leave days in a month → every Sunday that month unpaid.
- Flat ₹200 professional tax.

Also port: the requisition state machine (`Pending HR Review → Pending MD Approval →
Approved/Rejected`), the candidate pipeline stages, and offer/assessment **state-gating**
(the source does this correctly — 409 on resubmission).

### 4.4 Roles & permissions

| | FocusPrint | Sparsh |
|---|---|---|
| Roles | `Admin / Boss / HR / Delegator / Delegatee / User` (strings on the user row) | `superadmin / admin / clientadmin / clientuser / custom` |
| Grants | `user_permissions(username, permission)` — flat strings, 2 in use | `permissions.{module}.{create,read,update,delete}` on the user doc |
| Escape hatch | `role === "Admin"` short-circuits everything | `role == "superadmin"` short-circuits |

**Mapping:** FocusPrint `Admin`→`superadmin`; `Boss`/`MD`→`admin`; `HR`→ a `staff` user with
`permissions.hrms.*` granted; `User`→`clientuser`.

**New permission modules to add to the default dict in `models/user.py`:**
`hrms` (employee master, org), `recruitment` (req/JD/candidates/interviews/offers),
`attendance` (own punch is implicit; this grants team/manual edit), `payroll` (run + view all).

**Do not replicate** the source's two known permission defects: `canAccessHrms` = *any
authenticated user* guarding onboarding KYC (C-3), and notification IDOR (C-6/§18).

### 4.5 Notifications

Sparsh's fabric is a superset. Add HRMS template slugs only:
`hrms_requisition_raised`, `_approved`, `_rejected`, `hrms_interview_scheduled`,
`hrms_offer_sent`, `hrms_offer_accepted`, `hrms_onboarding_invite`,
`hrms_leave_applied`, `_approved`, `_rejected`, `hrms_probation_ending`, `hrms_exit_initiated`.
Seed them through the existing `POST /settings/initialize-templates` path.

### 4.6 Reports

`services/report_service.py` (806 LOC) + `ReportsDashboard.jsx` + `components/reports/*` already
provide filtering, company/employee scoping and export. Add HRMS report builders to that service —
**do not build a second reporting stack.** Source reports are recruitment-only and client-rendered
with no pagination; Sparsh should serve them server-side, as it already does.

### 4.7 Dashboard

`routes/dashboard.py` + `Dashboard.jsx`. Add an HRMS KPI block: headcount, joiners/exits MTD,
attendance %, pending leaves, open requisitions, offers pending. **Compute in one aggregation** —
the source pulls four full tables to derive eight KPIs, and its dashboard and reports pages
disagree because each keeps its own copy of the ranking map.

---

## 5. Frontend comparison

| Concern | FocusPrint | Sparsh | Action |
|---|---|---|---|
| Routing | File-based (App Router) | `react-router` in `App.jsx` | Add routes under `/hrms/*` |
| Layout/nav | `AppShell.tsx` + `hrms/layout.tsx` sub-nav | `layout/Sidebar.jsx`, `Navbar.jsx` | Add an HRMS sidebar group, gated on `hrms_enabled` |
| Data fetching | React Query | axios + `useEffect`/`useState` | Follow Sparsh; **do not introduce React Query** |
| Modals | SweetAlert2 + bespoke | `components/common/Modal.jsx` | Reuse |
| Buttons/inputs | Tailwind inline | `common/Button.jsx` + Tailwind | Reuse |
| Date pickers | `DatePicker.tsx`, `DateTimePicker.tsx` | `calendar/MiniDatePicker`, `CustomTimePicker` | Reuse |
| Tables | Bespoke per page, no pagination | `components/reports/*Table.jsx` patterns | Reuse patterns, add pagination |
| Filters/search | Client-side, renders every row | `FilterDropdown.jsx`, server-side filters | Follow Sparsh (server-side) |
| Notifications UI | `NotificationBell.tsx` | `NotificationDrawer.jsx` | Reuse |
| Toasts | SweetAlert2 | `NotificationContext` (`showSuccess/showError`) | Reuse |
| Selfie/voice capture | `SelfieCaptureModal`, `VoiceNoteRecorder` | none | Build (attendance only) |

**Pages to create (16):** HRMS Dashboard · Employees (list) · Employee Profile · Org Structure ·
Requisitions · Job Descriptions · Postings · Screening · Candidates · Assessments · Interviews ·
Offers · Onboarding · Attendance · Leave · Payroll · HR Reports.
**Public pages (4, unauthenticated):** Apply · Assess · Offer accept · Onboard.

---

## 6. Reusable Sparsh code — do not rebuild

| Need | Use |
|---|---|
| Auth / current user | `controllers/auth_controller.get_current_user` |
| Module gating per company | `is_company_delegation_enabled` pattern → `hrms_enabled` |
| Permission checks | `check_permission(module, action)` |
| File upload | `services/s3_service.upload_file_to_s3_with_key` |
| Email + WhatsApp + templates | `services/notification_service.send_notification_from_template` |
| In-app notification | `notification_service.create_in_app_notification` |
| Audit trail | `services/activity_log_service.log_activity` |
| Scheduled jobs | `services/reminder_scheduler` loop |
| Reports + export | `services/report_service.py`, `components/reports/*` |
| Holidays | `routes/holiday.py`, `models/holiday.py`, `pages/Holiday.jsx` |
| Reporting lines | `user.reporting_manager` |
| Company scoping | `company_id` + `routes/company.py` |
| Checklists / task assignment | Task & Delegation (`routes/tasks.py`) |
| Date/time pickers, modals, buttons, toasts | `components/common/*`, `components/calendar/*` |

---

## 7. Risks, hidden dependencies, migration challenges

**R-1 · Multi-tenancy (highest impact).** FocusPrint is single-tenant: no `company_id` anywhere in
HRMS. Sparsh is multi-tenant throughout. Every collection, query, index and permission check needs
company scoping **designed in from Phase 0** — retrofitting it later means touching every endpoint.
Decide up front: is HRMS for Sparsh's *own* staff, for *client companies*, or both?

**R-2 · Two user collections.** Sparsh splits users across `staff` and `learners`. Every HRMS
lookup must resolve across both (`find_user_by_id` already does). Decide whether employees are
`staff` only. Never key HRMS records by **username string** as the source does — key by `_id`.

**R-3 · Employee ↔ User identity.** Source links `hrms_employees.username → users.name` (a mutable
display name). Use an immutable `user_id`, and decide the rule for an employee with no login
(candidate hired but not yet provisioned) and a user with no employee record.

**R-4 · Naming collision: "attendance".** Sparsh already uses *attendance* for LMS session
attendance (`calendar_events`, `report_lms_service`). HR attendance is a different domain. Namespace
it (`hrms_attendance`, `/api/hrms/attendance`, "Workforce Attendance" in the UI) or reports and the
assistant tools will silently blend the two.

**R-5 · First public endpoints.** Apply/assess/offer/onboard are unauthenticated. Sparsh has no
anonymous surface today — CORS, rate limiting, upload caps and CSP all need deciding. The source
gets this badly wrong: ~225 MB per anonymous request, no rate limit, `Math.random()` tokens
(40 bits). **Use `secrets.token_urlsafe`, cap uploads, add throttling.**

**R-6 · Object-storage authorization.** Source streams any S3 key to any session holder (C-7) and
allows `image/svg+xml` + `application/octet-stream` served inline with no `nosniff` (C-9 → stored
XSS). Sparsh's HR documents (PAN, Aadhaar, bank) demand per-object authz and a strict allow-list.

**R-7 · Settings poisoning.** Source settings keys are unvalidated strings; a bad value NaN-poisons
payroll. Validate and type every HRMS setting on write.

**R-8 · Payroll correctness.** Source payroll persists **nothing**, has two conflicting net figures,
and its `GET` **mutates** the leave ledger. Sparsh must: persist a payroll run, make it idempotent
and lockable, and never mutate on `GET`. Do not port the bug for parity.

**R-9 · Manual attendance edits ignored by payroll.** Known source bug (`is_manual` written, not
read). Decide the precedence rule explicitly.

**R-10 · Stale reference docs.** The bundled audit understates the code (see §2). Verify against
source code, not the markdown.

**R-11 · No data migration required — confirm.** This roadmap assumes a **fresh HRMS in Sparsh**,
not a data import from the Neon database. If historical HRMS data must come across, add a
Phase 8 ETL (Postgres → Mongo) and budget separately.

**R-12 · Branch base.** `BHU_HRMS_30JULY` sits at `c7fa9dc`, which predates TPMS and the newer
Task & Delegation work present on `main`. Confirm this is the intended base before building — a
later rebase across 17 modules is expensive.

---

## 8. Implementation phases

Each phase is independently shippable and testable. **Ship Phase 0 + 1 before anything else** —
every later phase depends on them.

| Phase | Milestone | Modules | Depends on |
|---|---|---|---|
| **0** | Foundation | Module gate (`hrms_enabled`), permission modules, HRMS router skeleton, sidebar group, index-ensure, counters | — |
| **1** | Core HR | Org masters, Employee Master, employee timeline, profile UI, directory search | 0 |
| **2** | Time & Attendance | Attendance (punch, GPS, selfie, segments), team view, holiday integration | 0, 1 |
| **3** | Leave | Types, application, approval routing (uses `reporting_manager`), balances, accrual job | 1, 2 |
| **4** | Payroll | Rule engine port, persisted runs, payslip, locks | 2, 3 |
| **5** | Recruitment core | Requisitions, JD, approval chain | 0, 1 |
| **6** | Candidate pipeline | Postings + public apply, screening, assessments, interviews | 5 |
| **7** | Offer → Employee | Offers, onboarding, hire → Employee Master handoff | 1, 6 |
| **8** | Exit | Exit documents, F&F checklist, offboarding | 1 |
| **9** | Insight | HRMS dashboard KPIs, HR reports, scheduled alerts | 1–8 |

**Recommended order and why:** Core HR first because *every* other module references an employee.
Attendance → Leave → Payroll next, as a self-contained vertical that delivers daily-use value
early and is the half the source does worst (so it is genuine new work, not a port). Recruitment
after, because it is the source's strongest half and can be replicated with least ambiguity — and
its terminal step (hire) needs Employee Master to already exist. Insight last, since it aggregates
everything.

---

## 9. Per-module detail

Common to every module: **Backend** = new router in `app/routes/`, models in `app/models/`,
registered in `main.py`. **Frontend** = page in `src/pages/`, components in
`src/components/hrms/`, API wrapper in `src/services/hrmsApi.js`. **Permissions** = gated by
`require_hrms_access` + the relevant `permissions.<module>.<action>`. **Testing** = listed per
module below, plus: company isolation, permission denial (403), audit-log entry written.

---

### Phase 0 — Foundation

- **Backend:** `hrms_enabled` flag on `companies` (default **off**, matching `delegation_enabled`);
  `require_hrms_access` dependency; `app/routes/hrms.py` skeleton; startup index-ensure;
  `counters` collection + atomic `next_sequence(scope, year)`.
- **Frontend:** sidebar HRMS group gated on `user.hrms_enabled`; `/hrms` route shell;
  `RequireHrmsAccess` guard (copy `RequireTaskAccess`).
- **Database:** `companies.hrms_enabled`; `counters`.
- **API:** none (infrastructure).
- **Permissions:** add `hrms`, `recruitment`, `attendance`, `payroll` to the default dict.
- **Dependencies:** none.
- **Tests:** flag off → 403 + hidden nav; flag on → shell renders; counter is atomic under
  concurrent calls; index-ensure is idempotent across restarts.

### Phase 1 — Core HR

- **Backend:** `hrms_org_masters` CRUD (kind = department/designation/location, `active` retire,
  upsert-on-type); `hrms_employees` CRUD with `EMP-YYYY-NNNN`; sensitive-field masking for
  non-HR readers; `hrms_employee_events` append on every change.
- **Frontend:** Employees list (server-side search/filter/pagination); Employee profile
  (tabs: Personal, Job, Statutory, Documents, Timeline); Employee form modal (combobox against
  org masters); Org Structure page; org chart from `reporting_manager`.
- **Database:** `hrms_employees`, `hrms_employee_events`, `hrms_org_masters` + indexes.
- **API:** `GET/POST /api/hrms/employees`, `GET/PATCH /api/hrms/employees/{code}`,
  `GET /api/hrms/employees/{code}/events`, `GET/POST/PATCH /api/hrms/org`.
- **Permissions:** `hrms.read` directory; `hrms.create/update` HR only; statutory/bank fields
  masked unless `hrms.manage`.
- **Dependencies:** Phase 0; `staff`/`learners`; `s3_service` for photo/docs.
- **Tests:** code sequence never collides; masking honoured per role; every edit writes a timeline
  event; retiring a master doesn't break employees referencing it; directory search matches
  name/code/designation/email; a company cannot see another's employees.

### Phase 2 — Time & Attendance

- **Backend:** punch in/out with segments embedded; first-in/last-out daily summary derived, not
  duplicated; optional geofence (settings-driven, opt-in); selfie upload to gated prefix; manual
  entry with `is_manual` + actor; team view scoped to `reporting_manager` + HR.
- **Frontend:** punch widget with camera capture; my-attendance calendar; team attendance;
  manual-entry modal (HR).
- **Database:** `hrms_attendance` (unique `user_id`+`punch_date`).
- **API:** `GET/POST /api/hrms/attendance`, `GET /api/hrms/attendance/team`,
  `POST /api/hrms/attendance/manual`.
- **Permissions:** own punch = any HRMS user; team = manager/HR; manual = `attendance.update`.
- **Dependencies:** Phases 0–1; s3; existing `holidays`.
- **Tests:** double punch-in rejected; segments roll into the daily summary; geofence blocks only
  when enabled; manual edit is audited and **visible to payroll** (R-9); DST/timezone — store UTC,
  render IST.

### Phase 3 — Leave

- **Backend:** configurable leave types (not the source's 4 hardcoded strings); application →
  approval routed to `reporting_manager`, HR fallback; balance check on submit; annual accrual job
  in `reminder_scheduler`; half-day and range support.
- **Frontend:** apply form; my leaves; approvals inbox; balance card.
- **Database:** `hrms_leaves`, `hrms_leave_balances`, leave types in settings.
- **API:** `GET/POST /api/hrms/leaves`, `PATCH /api/hrms/leaves/{id}/decide`,
  `GET /api/hrms/leaves/balance`.
- **Permissions:** apply = self; decide = manager/HR.
- **Dependencies:** Phases 1–2; `reporting_manager`; notification templates.
- **Tests:** balance decrements once and only on approval; over-balance spills to unpaid; approver
  cannot approve own leave; overlapping requests rejected; accrual job idempotent per year.

### Phase 4 — Payroll

- **Backend:** port `payroll/config.ts` constants to a Python dataclass; engine reads attendance +
  leaves + holidays + balances; **persist** a payroll run (draft → locked); idempotent recompute;
  never mutate on `GET`; validated numeric settings.
- **Frontend:** run screen (month picker, preview, lock), payslip view, breakdown card.
- **Database:** `hrms_payroll_runs`, `hrms_payslips`.
- **API:** `POST /api/hrms/payroll/run`, `GET /api/hrms/payroll/{run_id}`,
  `POST /api/hrms/payroll/{run_id}/lock`, `GET /api/hrms/payroll/payslip`.
- **Permissions:** `payroll.*` — HR/admin only; employee sees own payslip after lock.
- **Dependencies:** Phases 2–3; holidays; settings.
- **Tests:** port the source's `engine.test.mts` cases as pytest; verify each rule (late fine,
  OT completed-hours, 2-day penalties, >15-leave Sunday rule, actual-day-count base); locked run
  immutable; re-run produces identical numbers; a month with no attendance does **not** fine
  everyone (source's `detect_absences` foot-gun).

### Phase 5 — Recruitment core

- **Backend:** requisitions with the `steps[]` array; state machine
  `Pending HR Review → Pending MD Approval → Approved/Rejected`; JD authored with the requisition
  and co-approved; close/hold.
- **Frontend:** requisitions list + new/edit modal + approval dialog; JD editor.
- **Database:** `hrms_requisitions`, `hrms_jds`.
- **API:** `GET/POST /api/hrms/requisitions`, `POST /api/hrms/requisitions/{no}/approve`,
  `POST /api/hrms/requisitions/{no}/close`, `GET/POST /api/hrms/jds`.
- **Permissions:** raise = `recruitment.create`; approve = `recruitment.approve` (admin/MD).
- **Dependencies:** Phases 0–1; org masters; notifications.
- **Tests:** illegal transitions rejected; approver ≠ raiser; **build the `/close` UI** (source
  ships the API with no caller); delay computation.

### Phase 6 — Candidate pipeline

- **Backend:** postings (JD × platform) with public code (`secrets.token_urlsafe`); public apply
  (rate-limited, size-capped, deduped — source has none); screening + bulk actions; assessments
  (send → submit → dual review, state-gated); interviews as `calendar_event` docs so the existing
  reminder scheduler drives them; scorecards.
- **Frontend:** postings, screening board, candidate journey, assessments, interviews + evaluate
  modal; public Apply and Assess pages.
- **Database:** `hrms_postings`, `hrms_candidates` (embedded `assessments[]`, `interviews[]`).
- **API:** `GET/POST /api/hrms/postings`; **public** `GET/POST /api/hrms/apply/{code}`,
  `GET/POST /api/hrms/assess/{code}`; `POST /api/hrms/candidates/screen`;
  `GET/POST /api/hrms/interviews`, `POST /api/hrms/interviews/{id}/evaluate`.
- **Permissions:** public routes unauthenticated but state-gated + throttled; interviewers see
  only assigned interviews.
- **Dependencies:** Phase 5; s3; calendar + reminder scheduler; **R-5**.
- **Tests:** expired/closed code rejected; resubmission → 409; **access code never leaked to
  non-owners** (source C-2 defect); upload cap and rate limit enforced; duplicate application
  handling; interview reminder fires at the right time.

### Phase 7 — Offer → Employee

- **Backend:** offer draft → send → public accept/decline (state-gated, expiry); onboarding invite
  (KYC + docs), **HR-verified state that a later public POST cannot revert** (source C-4);
  onboarding → create `hrms_employees` + optionally provision a `staff` login.
- **Frontend:** offers list + editor; onboarding tracker; public Offer and Onboard pages.
- **Database:** `hrms_candidates.offers[]`, `.onboarding`.
- **API:** `GET/POST /api/hrms/offers`; **public** `GET/POST /api/hrms/offer/{code}`,
  `GET/POST /api/hrms/onboard/{code}`; `POST /api/hrms/onboarding/{code}/convert`.
- **Permissions:** onboarding KYC readable by **HR/admin only** (source C-3 is a critical leak).
- **Dependencies:** Phases 1, 6; s3; notifications.
- **Tests:** accepted offer cannot be re-accepted; verified onboarding **cannot** be overwritten by
  the public link; conversion creates exactly one employee and is idempotent; KYC not readable by
  a non-HR user; branding comes from config, not hardcoded.

### Phase 8 — Exit

- **Backend:** initiate exit (status → On Notice), document upload/verify against a standard list,
  optional F&F checklist as delegation tasks.
- **Frontend:** exit tab on the employee profile; documents table.
- **Database:** `hrms_exit_documents`.
- **API:** `GET/POST /api/hrms/employees/{code}/exit-docs`, `POST .../exit`.
- **Permissions:** HR/admin only; documents behind the gated prefix.
- **Dependencies:** Phase 1; s3; Task & Delegation for the checklist.
- **Tests:** exit sets `exit_date` + timeline event; payroll treats an exited employee correctly;
  documents not reachable by other roles.

### Phase 9 — Insight

- **Backend:** HRMS KPI aggregation (one pipeline); HR report builders inside `report_service`;
  scheduled alerts (probation ending, document expiry, birthdays/anniversaries) on the existing
  scheduler.
- **Frontend:** HRMS dashboard; HR reports in the existing reports shell.
- **API:** `GET /api/hrms/dashboard`, `GET /api/reports/hrms/{type}`.
- **Dependencies:** Phases 1–8.
- **Tests:** dashboard and reports return **the same number for the same metric** (the source's
  known divergence); export matches on-screen data; company-scoped.

---

## 10. Open questions — needed before Phase 0

1. **Who is the HRMS for?** Sparsh's own staff, client companies, or both? This determines whether
   `hrms_employees` is company-scoped and how the module toggle behaves. *(R-1 — blocks Phase 0.)*
2. **Employees = `staff` only, or `learners` too?** *(R-2.)*
3. **Is historical HRMS data being migrated** from the Neon database, or is this a fresh start?
   *(R-11 — adds a phase if yes.)*
4. **Is `c7fa9dc` the intended branch base**, or should `BHU_HRMS_30JULY` rebase onto current
   `main` first? *(R-12.)*
5. **Payroll policy:** adopt FocusPrint's constants as-is, or re-specify for Sparsh?
6. **Scope confirmation:** HRMS only — CRM stays out?

---

## 11. Effort estimate

Rough, for sequencing rather than commitment.

| Phase | Backend | Frontend | Total |
|---|---|---|---|
| 0 Foundation | S | S | **S** |
| 1 Core HR | L | L | **XL** |
| 2 Attendance | M | L | **L** |
| 3 Leave | M | M | **M** |
| 4 Payroll | L | M | **L** |
| 5 Recruitment core | M | M | **M** |
| 6 Candidate pipeline | XL | XL | **XL** |
| 7 Offer → Employee | L | L | **L** |
| 8 Exit | S | S | **S** |
| 9 Insight | M | M | **M** |

Phases 1 and 6 dominate. Phases 0 and 8 are small enough to bundle with a neighbour.

---

## 12. Link generation — how the public links work

The HRMS issues five kinds of public link. Each one lets an unauthenticated person do exactly
one thing, and nothing else.

| Link | Issued when | Public route | Spent when |
|---|---|---|---|
| Job posting | A requisition is published to a platform | `/apply/:code` | Never — many people apply through one posting |
| Assessment | HR sends a written assessment | `/assess/:code` | The candidate submits answers |
| Offer | HR sends an offer | `/offer/:code` | The candidate accepts or declines |
| Appointment letter | HR generates the letter | `/appointment/:code` | The candidate acknowledges |
| Onboarding / KYC | HR invites a joiner | `/onboarding/:code` | The joiner submits their details |

### How a code is generated

`public_guard.public_token()` — `secrets.token_urlsafe(16)`, so 128 bits of cryptographic
randomness. Codes are never sequential, never derived from a candidate id, and never guessable
from a neighbouring one.

The code is stored on the document it belongs to: `public_code` on the posting, `access_code`
inside the relevant `assessments` / `offers` / `appointment_letter` / `onboarding` sub-document
on the candidate. That is the single copy.

### Where they are tracked

Issuing a link also writes a row to `hrms_links` (see `services/hrms_link_service.py`). That row
is a **pointer plus tracking**, not a second copy of the secret — it records the type, who
created it, expiry, open count, first/last open, whether it has been spent, and the reveal audit
trail. Every public GET calls `track_open`; every completing POST calls `mark_used`. Both are
best-effort: tracking must never stop a candidate opening their own offer.

### How HR gets a link back

Codes are deliberately **not** returned by any list or read endpoint. That rule exists because
the reference project returned every candidate's access code to any logged-in user, which its
own audit rated critical.

To retrieve one, HRMS ▸ Links offers a per-link **Reveal**, which:

1. requires the `recruitment.update` grant (not merely read),
2. re-reads the code from the document that actually holds it, so a regenerated link can never
   be revealed as its stale predecessor,
3. writes the reveal to the link's audit trail **before** returning the code — if that write
   fails, the code is not handed over,
4. returns exactly one code, for one link.

Revoking marks the registry row dead so it can no longer be revealed. To rotate the secret
itself, regenerate whatever issued it — generating a new appointment letter, for example, mints
a fresh code and supersedes the old link.
