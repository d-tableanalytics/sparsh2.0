# HRMS Enhancement — Implementation Prompt (Phase 11-R)

> Copy everything below the line into the implementing agent/session. It is written to be
> self-contained: it states the scope fence, the current architecture it must build on, and
> the seven work items with their exact data-model, API, UI and test obligations.

---

## ROLE

You are extending the **HRMS module** of this ERP (`c:\Users\Admin\Desktop\sparshm\sparshN\sparsh2.0`).
The module is already built through Phase 10 (Foundation → Employee Master → Requisitions →
Postings → Candidates → Assessments → Interviews → Offers → Onboarding → Analytics). You are
adding **Phase 11-R: Recruitment Review Enhancements** — seven changes requested in the HRMS
review, and **nothing else**.

---

## 1. HARD SCOPE FENCE — read first, obey absolutely

### 1.1 You may create or modify ONLY these paths

**Backend**
```
backend/app/models/hrms.py
backend/app/routes/hrms.py
backend/app/routes/hrms_public.py
backend/app/services/hrms_*_service.py          (existing + new)
backend/app/services/hrms/tests/test_phase11_*.py
backend/app/utils/hrms_access.py
backend/app/utils/hrms_public_guard.py
```

**Frontend**
```
frontend/src/features/hrms/**
frontend/src/pages/hrms/public/**
frontend/src/services/hrmsApi.js
frontend/src/services/hrmsPublicApi.js
```

**Docs**
```
docs/hrms/PHASE_11R_REPORT.md
docs/hrms/PHASE_11R_TEST_SCRIPT.md
docs/hrms/OUT_OF_SCOPE_FINDINGS.md               (append-only)
```

### 1.2 Two shared files may be touched — APPEND ONLY, no edits to existing lines

| File | Permitted change | Forbidden |
|---|---|---|
| `frontend/src/App.jsx` | Add new `<Route>` lines inside the existing `/hrms` block (~lines 245–265) and new public routes beside `/apply/:code`…`/onboard/:code` (~lines 156–159) | Reordering, editing or deleting any existing route; touching any non-HRMS route |
| `frontend/src/components/layout/Sidebar.jsx` | Add entries to the `hrmsSubmodules` array and to the `HRMS_WORKSPACE` path list (~lines 104–120) | Any change to other nav groups, roles arrays, or shared layout markup |

`backend/app/db/mongodb.py` needs **no change** — it already provisions from
`HRMS_INDEXES` in `models/hrms.py`. `main.py` needs no change — both HRMS routers are
already mounted.

### 1.3 Absolutely forbidden

- Any change to TPMS, ORM, Delegation/Tasks, Calendar, LMS, Reports, GPT/Assistant, Forms,
  Company, Auth, Notification or User modules — code, models, routes, tests or docs.
- Any change to `auth_controller.py`, `services/api.js`, `context/*`, `components/common/*`,
  `components/layout/*` (except the Sidebar append above), `utils/taskAccess.js`.
- Writing to any Mongo collection not prefixed `hrms_`. Reading `companies`, `staff` and
  `learners` is allowed (already done — see `routes/hrms.py:132`, `hrms_notify_service.py`).
- Adding a new dependency to `package.json` or `requirements.txt`. Everything needed
  (`recharts`, `xlsx`, `jspdf`, `lucide-react`, `boto3` via `s3_service`) is present.
- Building anything not listed in §4 below. No leave, no attendance, no payroll, no
  settings console — those are Phases 12–14 and are **out of scope**.

If you find a bug or an improvement outside HRMS, **do not fix it**. Append an entry to
`docs/hrms/OUT_OF_SCOPE_FINDINGS.md` in the existing `OOS-NNN` format and move on.

---

## 2. THE ARCHITECTURE YOU MUST BUILD ON (do not re-derive it)

Read these before writing code. They are the single sources of truth and every addition
below is an extension of one of them, never a parallel mechanism.

| Concern | Where it lives | Rule |
|---|---|---|
| Collection names + indexes | `models/hrms.py:38-184` (`COLL_*`, `HRMS_INDEXES`) | Declare new `COLL_*` constants and append index tuples in one block labelled `── Phase 11-R ──`. Never re-order existing entries. |
| Authorization | `models/hrms.py:235-398` (`Cap`, `ROLE_CAPABILITIES`) + `utils/hrms_access.py::can()` | Every gate resolves through `can(user, Cap.X)`. **Never** an ad-hoc role check. `HrmsRole.ADMIN` is implicitly granted everything — do not add it to the matrix. |
| Company scoping | `routes/hrms.py::_company()` + `HrmsContext.scope` | Every query carries `company_id`. `HrmsRole.MANAGER` is additionally narrowed to their own requisitions (`hrms_analytics_service._scope`, `hrms_candidate_service._scope_filter`) — new read surfaces must apply the same narrowing and **fail closed**. |
| Candidate lifecycle | `models/hrms.py:882-1055` (`AppStatus`, `FORWARD_TRANSITIONS`, `TERMINAL_STATUSES`, `ALWAYS_AVAILABLE`, `allowed_next_statuses`) | The graph is data. Adding a stage = editing the table, not adding control flow. An illegal move is a 409. |
| Requisition approval | `models/hrms.py:674-752` (`ReqApproval`, `REQ_TRANSITIONS`, `REQ_AUDIT_ACTIONS`) | Same rule: a transition table, `(required_status, resulting_status, capability, remark_required)`. |
| Business IDs | `models/hrms.py:424-465` + `services/hrms_id_service.py::next_business_id` | Atomic counter, per company, `format_business_id`. Never scan-for-max. |
| Public access codes | `utils/hrms_public_guard.py:155` `new_access_code()` (128-bit, `secrets`) | Every candidate-facing credential uses this. Never `random`. |
| Public surface defence | `utils/hrms_public_guard.py` — `enforce_rate_limit`, `validate_access_code`, `decode_upload`, `clean_text`, `INVALID_LINK` | New public routes MUST rate-limit and MUST return the vague `INVALID_LINK` for not-found / malformed / wrong-tenant alike. |
| File storage | `hrms_posting_service.py:374 _store_upload` → `s3_service.upload_file_to_s3_with_key` | Store the **S3 key**, never a signed URL (they expire). Mint URLs on demand with `get_signed_url`. Honour `MAX_UPLOAD_BYTES` (15 MB) and `ALLOWED_UPLOAD_MIME`. |
| Audit | `services/hrms_audit_service.py::audit(actor, action, entity, entity_id, detail, company_id)` | Every write emits one. Never raises into the caller. |
| Notifications | `services/hrms_notify_service.py::notify_user / notify_users / notify_hrms_role` | The ONLY delivery path. Fire-and-forget; a notification failure must never roll back the business write. Do not build an outbox or touch SMTP. |
| Analytics | `services/hrms_analytics_service.py` | READ-ONLY. No insert/update/delete, ever. Every aggregation goes through `_scope()`. Every read is capped (`SCAN_CAP`). |
| Frontend capability gating | `features/hrms/HrmsContext.jsx::can()` + `features/hrms/access.js::CAP` | Buttons are gated on the server-returned capability list from `GET /hrms/health`. Add new caps to **both** the `Cap` enum and `access.js::CAP`. |
| Frontend API layer | `services/hrmsApi.js` | Thin axios wrappers over the shared instance. **No react-query.** |
| Styling | CSS variables only (`--accent-indigo`, `--border`, `--text-main`, `--bg-card`, `--input-bg`, `--text-muted`), `lucide-react` icons, `recharts` charts | No new palette, no inline hex. |

---

## 3. CROSS-CUTTING RULES FOR EVERY ITEM BELOW

1. **Additive, never destructive.** Existing endpoints keep their paths, payload shapes and
   status codes. Existing enum members keep their string values. Existing documents remain
   readable — every new field is optional with a sane default, and every read path must
   tolerate documents written before this phase (`doc.get("x") or default`).
2. **Backfill is not migration.** Do not write a migration script. Handle missing fields at
   read time.
3. **New capability for every new decision.** If a new screen or action exists, it has a
   `Cap` and a row in `ROLE_CAPABILITIES`. Default grants follow the existing logic:
   HR/MD operate; MANAGER reads their own; EMPLOYEE self-service only; INTERNAL supports
   but never holds a client's approval capability or salary capability.
4. **Every state change → audit row + notification.** Both, every time.
5. **Server is the control; the client mirrors it.** Client-side validation may pre-empt a
   round trip but never replaces the server rule.
6. **Tests are part of the deliverable**, in `backend/app/services/hrms/tests/`, named
   `test_phase11_<item>.py`, following the existing file style. Cover the S3 dimensions:
   Positive · Negative · Edge · Permission · Validation · API · Database · Frontend · E2E.

---

## 4. THE WORK — seven items

### ITEM 1 — Link Generation: one process, trackable and retrievable

**Requested:** *"A proper Link Generation process explanation. The generated links should be
trackable and easily accessible whenever required. as we have multiple link genration in job posting but we need only
one form link but in that there should be a block of where did you find this job and then list the name of platform
that block will be madatory and when candidate fill the form then we get the source data from where they find the job post "*

**Current state.** Four kinds of public link exist, each minted independently and surfaced
ad-hoc, with **no registry, no open tracking, no expiry, no revocation and no single place
to find them**:

| Link | Minted in | Public route | Frontend helper |
|---|---|---|---|
| Apply | `hrms_posting_service.py:55-91` (`_mint_code` / `_unique_code`) | `GET|POST /hrms/public/apply/{code}` | `hrmsApi.js:111 applyUrlFor` |
| Assessment | `hrms_assessment_service.py` via `new_access_code()` | `/hrms/public/assess/{code}` | `hrmsApi.js:140 assessUrlFor` |
| Offer | `hrms_offer_service.py` via `new_access_code()` | `/hrms/public/offer/{code}` | `hrmsApi.js:173 offerUrlFor` |
| Onboarding | `hrms_onboarding_service.py` via `new_access_code()` | `/hrms/public/onboard/{code}` | `hrmsApi.js:200 onboardUrlFor` |

**Build.**

1. **`COLL_LINKS = "hrms_links"`** — the registry. One row per issued link:
   ```
   link_id            business id, LNK-<year>-<seq>   (add to ID_FORMATS)
   company_id
   kind               LinkKind: apply | assessment | offer | onboarding | appointment
   code               the posting_code or access_code — the credential itself
   path               "/apply/<code>" etc. — the relative public path
   target_type        posting | candidate | offer | onboarding
   target_id          posting_code / uk / offer_no / onb_no
   candidate_name     denormalised label for the list screen (nullable)
   request_no         nullable — enables the MANAGER row-scope narrowing
   issued_by, issued_at
   status             LinkStatus: Active | Expired | Revoked | Consumed
   expires_at         nullable ISO date
   open_count, first_opened_at, last_opened_at
   consumed_at        set when the link's purpose completes (application submitted,
                      assessment submitted, offer responded, onboarding submitted)
   revoked_at, revoked_by, revoke_reason
   ```
   Indexes: `(code)` unique · `(company_id, kind, status)` · `(company_id, created_at desc)` ·
   `(target_id)`.

2. **`services/hrms_link_service.py`** — the ONE registry surface:
   - `register_link(...)` — called by the four existing mint sites **immediately after** the
     code is generated, inside the same request. It is additive: it must not change the
     codes, the return shapes or the failure modes of those four services. If registration
     fails, log a warning and continue — a registry write must never break an offer send.
   - `record_open(code)` — called by each public `GET` handler. Increments `open_count`,
     sets `first_opened_at` / `last_opened_at`.
   - `record_consumed(code)` — called by each public `POST` handler on success.
   - `revoke(actor, company_id, link_id, reason)` — sets `Revoked`.
   - `list_links(actor, company_id, filters)` — kind / status / search / date range,
     with the MANAGER narrowing via `request_no`.
   - `effective_status(doc, today)` — computed like
     `hrms_posting_service._effective_status`: a past-expiry Active link reads Expired
     without a nightly job. Store nothing.

3. **Revocation must actually work.** Add a guard in `hrms_public_guard.py` —
   `assert_link_live(code)` — that the four public `GET`/`POST` handlers call before doing
   anything else. A `Revoked` or `Expired` link returns the existing vague `CLOSED_LINK`
   message, never a distinguishing error. Rate limiting stays exactly as configured in
   `RATE_LIMITS`; add `"link-view"` only if a new public route needs it.

4. **Backfill-free legacy handling.** A code with no registry row is treated as `Active`
   with `open_count` unknown — the guard must not lock out links issued before this phase.

5. **API** (`routes/hrms.py`, appended in a `Phase 11-R — links` block):
   ```
   GET    /hrms/links                    list + filters + stats     Cap.LINK_READ
   GET    /hrms/links/{link_id}          one, with its open history Cap.LINK_READ
   POST   /hrms/links/{link_id}/revoke   {reason}                   Cap.LINK_MANAGE
   POST   /hrms/links/{link_id}/reissue  mints a fresh code, revokes the old  Cap.LINK_MANAGE
   ```
   `reissue` delegates to the owning service (a new assessment/offer/onboarding code) —
   it must not mint a code the owning service does not know about.

6. **Capabilities.** `Cap.LINK_READ = "link.read"`, `Cap.LINK_MANAGE = "link.manage"`.
   Grants: HR ✔ read+manage · MD ✔ read+manage · INTERNAL ✔ read+manage ·
   MANAGER ✔ read only (own requisitions) · EMPLOYEE ✘.

7. **UI** — `features/hrms/links/LinkManager.jsx` at route `/hrms/links`, added to the
   `TABS` array in `common/HrmsWorkspaceBar.jsx:24-35` (label **"Links"**, icon `Link2`) and
   to `HRMS_WORKSPACE` in `Sidebar.jsx`. Table: kind · candidate/target · code · status
   chip · opens · issued by/on · expiry · copy · revoke · reissue. Filters across the top,
   stat tiles (Active / Expired / Revoked / Never opened).

8. **The "process explanation."** A short, permanent panel at the top of the Link Manager
   (and a `## Link generation` section in the phase report) stating, in plain language: how
   each link kind is generated, that codes are 128-bit and unguessable, that `external`
   postings are **not** tracked because applications made there never reach this pipeline
   (`ApplyLinkMode.EXTERNAL`, `models/hrms.py:858-869`), what "opened" counts, and what
   revoke does.

---

### ITEM 2 — Documentation module

**Requested:** *"A dedicated Documentation module where all employee/candidate-related
documents can be uploaded, updated and managed, with document-wise status tracking and easy
retrieval."*

**Current state.** Documents exist only as scattered attachments: candidate resume/photo/
certificates (`hrms_posting_service.py:374 _store_upload`), onboarding KYC docs
(`hrms_onboarding_service.py:565 _store_documents`, cap `MAX_ONBOARD_DOCUMENTS = 15`), JD
attachments. There is **no document register, no per-document status, no expiry, no
versioning and no single retrieval screen**.

**Build.**

1. **`COLL_DOCUMENTS = "hrms_documents"`** and **`COLL_DOCUMENT_TYPES = "hrms_document_types"`**.

   `hrms_document_types` — a per-company master (same shape as `hrms_departments`, reuse
   `hrms_masters_service.py` patterns): `name`, `code`, `category` (Identity / Educational /
   Employment / Statutory / Company Issued / Other), `applies_to` (`candidate` | `employee` |
   `both`), `mandatory: bool`, `expires: bool`, `active: bool`. Seed a sensible default set
   on first read for a company that has none — PAN, Aadhaar, Passport, Degree Certificate,
   Experience Letter, Relieving Letter, Last 3 Payslips, Bank Proof, Offer Letter Signed,
   Appointment Letter, Address Proof, Photograph.

   `hrms_documents` — one row per document instance:
   ```
   doc_no             DOC-<year>-<seq>   (add to ID_FORMATS)
   company_id
   owner_type         candidate | employee
   owner_id           uk  |  employee_code
   owner_name         denormalised label
   request_no         nullable — enables MANAGER narrowing for candidate docs
   type_id, type_name
   status             DocumentStatus: Pending | Uploaded | Under Review | Verified
                                    | Rejected | Expired
   current_version    int
   versions[]         [{version, file_name, s3_key, mime_type, size_bytes,
                        uploaded_by, uploaded_at, source: hr|candidate|system}]
   issue_date, expiry_date          nullable ISO dates
   verified_by, verified_at, remarks
   created_at, updated_at
   ```
   Indexes: `(doc_no)` unique · `(company_id, owner_type, owner_id)` ·
   `(company_id, status)` · `(company_id, expiry_date)` · `(request_no)`.

2. **`services/hrms_document_service.py`** — upload (new doc or new version), update
   metadata, set status, verify/reject, delete, list by owner, list by company with filters,
   checklist-for-owner (every `mandatory` type for the owner kind, with its status or
   `Pending` if absent), signed-URL retrieval, and expiry computation
   (`expiry_date < today` ⇒ reads as `Expired`, computed not stored, same pattern as
   `_effective_status`).

3. **Reuse, do not duplicate, existing files.** Candidate resume/photo/certificates and
   onboarding KYC uploads already live on their own documents. The Documentation screen
   must **surface them read-only** (project them into the same view shape with
   `source: "linked"`) rather than copying the S3 objects. Only newly uploaded documents get
   `hrms_documents` rows of their own. State this explicitly in the phase report.

4. **Storage.** Same path as everything else: `decode_upload` → `upload_file_to_s3_with_key`
   → store the **key**. Retrieval mints a fresh `get_signed_url` per request. Enforce
   `MAX_UPLOAD_BYTES` and `ALLOWED_UPLOAD_MIME`. Cap versions per document at 10.

5. **API:**
   ```
   GET    /hrms/document-types                                     Cap.DOCUMENT_READ
   POST   /hrms/document-types            create                   Cap.DOCUMENT_WRITE
   PATCH  /hrms/document-types/{id}                                Cap.DOCUMENT_WRITE
   DELETE /hrms/document-types/{id}       blocked if in use        Cap.DOCUMENT_WRITE
   GET    /hrms/documents                 filters + pagination     Cap.DOCUMENT_READ
   GET    /hrms/documents/checklist       ?owner_type&owner_id     Cap.DOCUMENT_READ
   POST   /hrms/documents                 upload (new / version)   Cap.DOCUMENT_WRITE
   PATCH  /hrms/documents/{doc_no}        metadata, dates          Cap.DOCUMENT_WRITE
   POST   /hrms/documents/{doc_no}/status {status, remarks}        Cap.DOCUMENT_VERIFY
   GET    /hrms/documents/{doc_no}/url    signed URL, short TTL    Cap.DOCUMENT_READ
   DELETE /hrms/documents/{doc_no}                                 Cap.DOCUMENT_WRITE
   ```
   Rejecting a document **requires** remarks (same rule as `REQ_TRANSITIONS` rejections).

6. **Capabilities.** `DOCUMENT_READ = "document.read"`, `DOCUMENT_WRITE = "document.write"`,
   `DOCUMENT_VERIFY = "document.verify"`. Grants: HR ✔ all · MD ✔ all · INTERNAL ✔ read+write,
   ✘ verify (verification is the client's own governance act, same reasoning as
   `REQUISITION_REVIEW_HR`) · MANAGER ✔ read (own requisitions' candidates only) ·
   EMPLOYEE ✘ from this surface (they see their own documents on their own profile, an
   inherent right handled in the route, not a capability — mirror
   `GET /hrms/employees/me`).

7. **UI:**
   - `features/hrms/documents/DocumentCenter.jsx` at `/hrms/documents` — the register:
     owner-type toggle (Employees / Candidates), search, type filter, status filter,
     expiring-soon filter, status chips, upload, version history, preview, verify/reject.
   - `features/hrms/documents/DocumentTypeManager.jsx` at `/hrms/document-types` (admin,
     alongside Departments/Designations in `hrmsSubmodules`).
   - A **Documents** tab on `people/EmployeeProfile.jsx` and on
     `recruitment/CandidateJourney.jsx`, both rendering a shared
     `documents/DocumentPanel.jsx` — one component, two mount points.
   - Sidebar: add `{ name: 'Documents', path: '/hrms/documents', icon: FolderOpen }` to
     `hrmsSubmodules`; add `/hrms/documents` to `HRMS_WORKSPACE` only if you also add a
     workspace tab (pick one home, not both — see the disjointness note in
     `HrmsWorkspaceBar.jsx:16-18`).

---

### ITEM 3 — Appointment Letter stage

**Requested:** *"An 'Appointment Letter Sent' stage/status should be added to the
recruitment workflow… track whether the appointment letter has been generated, shared,
pending, or acknowledged by the candidate."*

**Current state.** The offer letter flow is complete (`hrms_offer_service.py`, statuses
`Draft → Sent → Accepted|Declined|Revoked`, public page `/offer/{code}`,
`OfferPaper.jsx`). There is **no appointment letter** — a distinct document issued after
the offer is accepted, confirming joining terms.

**Build.**

1. **`COLL_APPOINTMENTS = "hrms_appointments"`** — do **not** overload the offer document.
   The offer and the appointment letter are two artifacts with two lifecycles.
   ```
   appointment_no     APT-<year>-<seq>   (add to ID_FORMATS)
   company_id, uk, request_no, offer_no
   candidate_name, designation, department, ctc, joining_date, location
   content            rendered body, same operator-editable template mechanism as
                      DEFAULT_OFFER_BODY / render_offer_body (models/hrms.py:1463-1495)
   version, history[]
   status             AppointmentStatus: Not Generated | Generated | Sent
                                       | Pending Acknowledgement | Acknowledged | Cancelled
   access_code        new_access_code(); unique index
   signature          authorised signatory, required to send
   generated_by/at, sent_by/at, acknowledged_at, acknowledgement_signature
   ```
   Indexes: `(appointment_no)` unique · `(access_code)` unique · `(uk)` unique ·
   `(company_id, status)` · `(request_no)`.

2. **Lifecycle integration — the careful part.** Add
   `AppStatus.APPOINTMENT_LETTER_SENT = "Appointment Letter Sent"` and wire it into **every**
   declaration that names stages, in one coherent edit:

   | Table | Change |
   |---|---|
   | `FORWARD_TRANSITIONS` (`:1011`) | `OFFER_ACCEPTED → {APPOINTMENT_LETTER_SENT, PRE_ONBOARDING}` and `APPOINTMENT_LETTER_SENT → {PRE_ONBOARDING}`. Keep the direct `OFFER_ACCEPTED → PRE_ONBOARDING` edge so a company that does not issue appointment letters is not blocked. |
   | `PIPELINE_COLUMNS` (`:1061`) | add to the `selected` column |
   | `JOURNEY_RAIL` (`:1135`) | add to the `Offer` step, or introduce an 8th step — your call, but state it |
   | `JOURNEY_STATUS_KINDS` (`:1120`) | `"offer"` |
   | `STAGE_RANK` (`:1695`) | rank 7, the same band as `OFFER_ACCEPTED` / `PRE_ONBOARDING` — **do not renumber the existing ranks**; the funnel must stay monotonic and the existing tests must stay green |
   | `ONBOARDABLE_STATUSES` (`:1594`) | add `APPOINTMENT_LETTER_SENT` alongside `OFFER_ACCEPTED` |
   | `FILLED_STATUSES` (`:1446`) | add it — an appointment letter means the vacancy is filled |
   | `hrms_offer_service` requisition auto-close | verify the `FILLED_STATUSES` count still auto-closes correctly |

   The **letter's own status** (Generated / Sent / Pending Acknowledgement / Acknowledged)
   lives on the appointment document, not on the candidate. The candidate has one pipeline
   stage; the artifact has its own state machine. Do not conflate them.

3. **Public acknowledgement page.** New route `POST|GET /hrms/public/appointment/{code}` in
   `routes/hrms_public.py`, new page `pages/hrms/public/AppointmentPage.jsx` at
   `/appointment/:code`, modelled exactly on `OfferPage.jsx` / the offer public handlers.
   Add rate-limit scopes `"appointment-view": (40, 60)` and
   `"appointment-ack": (10, 3600)` to `RATE_LIMITS`. Acknowledgement requires a typed
   signature (same reasoning as offer acceptance). Register the link with the Item 1
   registry (`kind: appointment`).

4. **API:**
   ```
   GET    /hrms/appointments                     list + filters      Cap.APPOINTMENT_READ
   GET    /hrms/appointments/eligible            Offer-Accepted cands Cap.APPOINTMENT_READ
   POST   /hrms/appointments                     generate (draft)     Cap.APPOINTMENT_WRITE
   PATCH  /hrms/appointments/{no}                edit before send     Cap.APPOINTMENT_WRITE
   POST   /hrms/appointments/{no}/send           {signature}          Cap.APPOINTMENT_SEND
   POST   /hrms/appointments/{no}/cancel         {reason}             Cap.APPOINTMENT_SEND
   ```
   Only a `Generated` letter is editable — once sent, the document the candidate is reading
   must not change underneath them (identical rule to `EDITABLE_OFFER_STATUSES`).

5. **Capabilities.** `APPOINTMENT_READ`, `APPOINTMENT_WRITE`, `APPOINTMENT_SEND`.
   Grants mirror the offer capabilities exactly: HR ✔ all · MD ✔ all · INTERNAL ✔ read only
   (sending is a commitment, same reasoning as `OFFER_SEND`) · MANAGER ✔ read ·
   EMPLOYEE ✘.

6. **UI.** `features/hrms/recruitment/AppointmentBoard.jsx` at `/hrms/appointments`, a new
   `TABS` entry in `HrmsWorkspaceBar.jsx` between **Offers** and **Onboarding**, and a
   `AppointmentPaper.jsx` preview built from `OfferPaper.jsx`. Status chips must show all
   five states. Copy-link + acknowledgement state on each row.

7. **Auto-file the letter.** On send, create an `hrms_documents` row (Item 2) of type
   *Appointment Letter*, owner `candidate`, status `Uploaded`; on acknowledgement, attach
   the signed acknowledgement and set `Verified`. This is the proof that Items 2 and 3 are
   one system, not two.

---

### ITEM 4 — Client-wise Recruitment Analytics dashboard

**Requested:** a dashboard with a **client-wise dropdown**; on selecting a client, show
Total CVs Reviewed · Selected · Rejected · Shared with Client · Client-side Rejections ·
Client-side Shortlisted · Total Joinings · other funnel metrics · **position-wise CV status**.

**Current state.** `hrms_analytics_service.py` already computes a rank-based funnel
(`FUNNEL_STAGES`, `STAGE_RANK`, `_evidence_ranks`), breakdowns
(`BREAKDOWN_FIELDS`: source / department / designation / platform) and reports
(`REPORT_ENTITIES`), all `company_id`-scoped and role-narrowed. `RecruitmentDashboard.jsx`
renders it. A company selector already exists — `HrmsContext` holds `companies` /
`companyId` / `setCompanyId`, fed by `GET /hrms/companies` (`routes/hrms.py:132`) and
rendered by `common/HrmsScopeBar.jsx`.

**⚠ Decision required before you build — see §6.** "Client" has two possible meanings here.
Confirm which, then build exactly that.

**Build (assuming the default reading in §6):**

1. **The dropdown = the existing company/client scope selector.** Mount `HrmsScopeBar` on
   `RecruitmentDashboard.jsx` (it renders nothing for a pinned client user — correct
   behaviour, do not change it). Add an **"All clients"** aggregate option, visible **only**
   to `isInternal` callers, which fans the dashboard aggregation across
   `hrms_enabled_company_ids()` and returns a per-client comparison table. A client-side
   user must never be able to request it — enforce server-side in
   `hrms_analytics_service`, not in the UI.

2. **Client-share tracking — the new data.** "Shared with client", "client-side rejection"
   and "client-side shortlisted" have no representation today. The closest existing thing is
   `ScreenAction.FORWARD`, which forwards to an internal user — that is **not** the same act.
   Add:
   - `ScreenAction.SHARE_WITH_CLIENT = "share_with_client"` in `SCREEN_ACTIONS`
     (`models/hrms.py:1090`), remark optional, recipient optional.
   - `AppStatus.SHARED_WITH_CLIENT = "Shared with Client"`,
     `AppStatus.CLIENT_SHORTLISTED = "Client Shortlisted"`,
     `AppStatus.CLIENT_REJECTED = "Client Rejected"` — wired into
     `FORWARD_TRANSITIONS`, `PIPELINE_COLUMNS`, `STAGE_RANK` (share/shortlist sit at rank 2,
     between Shortlisted and Assessment; client rejection ranks where it entered, like
     `REJECTED`), `JOURNEY_STATUS_KINDS` and `JOURNEY_RAIL`. Again: **do not renumber**
     existing ranks; insert at an existing band or extend the top.
   - A `client_share` sub-document on the candidate:
     `{shared_at, shared_by, client_contact, status: Pending|Shortlisted|Rejected|On Hold,
       responded_at, remarks}`.
   - `POST /hrms/candidates/client-response` — record the client's verdict
     (`Cap.CANDIDATE_SCREEN`).

3. **New metrics in `hrms_analytics_service.dashboard()`** — every one derived from data
   that exists after step 2, every one `_scope()`d, every one with the `link` + `filter`
   deep-link the existing tiles already carry:
   | Metric | Derivation |
   |---|---|
   | Total CVs Reviewed | candidates with `effective_rank ≥ rank(UNDER_REVIEW)` |
   | Total CVs Selected | `effective_rank ≥ rank(SELECTED)` |
   | Total CVs Rejected | status in `{REJECTED, CLIENT_REJECTED, DUPLICATE, ASSESSMENT_FAILED, OFFER_DECLINED}` |
   | Total CVs Shared with Client | `client_share.shared_at` exists |
   | Client-side Rejections | `client_share.status == Rejected` |
   | Client-side Shortlisted | `client_share.status == Shortlisted` |
   | Total Joinings | status in `{JOINED, EMPLOYEE_CREATED}` |
   | Offer acceptance rate, avg time-to-hire, avg time-to-first-response | derive from existing timestamps; state the formula in the phase report |

4. **Position-wise CV status matrix.** New endpoint
   `GET /hrms/analytics/positions` → rows = requisition (`request_no`, designation,
   department, vacancy, urgency), columns = every `AppStatus` count for that requisition
   plus the totals above. Cap `Cap.ANALYTICS_READ`. Same `_scope()`, same `SCAN_CAP`,
   same `MAX_RANGE_DAYS` window validation. Render it as a horizontally-scrolling table with
   sticky first column, plus a stacked `recharts` bar per position.

5. **Extend `BREAKDOWN_FIELDS`** with `"client_status"` → `(COLL_CANDIDATES,
   "client_share.status", "Client verdict")` and `"referral_source"` (Item 5). Both are
   allow-list entries — the endpoint must keep rejecting any `by` value not in the map.

6. **Nothing in this item writes.** `hrms_analytics_service` stays read-only. The
   client-share write path lives in `hrms_candidate_service`, where screening already lives.

---

### ITEM 5 — Referral capture on the Job Application

**Requested:** a Referral option **in the Job Application form**, capturing *Referred By*,
*Referral Source*, *Employee Name/ID (if applicable)*.

**Current state.** `Platform.REFERRAL` exists as a posting channel and `candidate.source`
is a free-ish string (`hrms_candidate_service.py:221`, `hrms_posting_service.py:474`), but
the application form (`PublicApplicationIn`, `models/hrms.py:970-988`;
`pages/hrms/public/ApplyPage.jsx`) captures **no referral detail at all**.

**Build.**

1. **Model.** Add to **both** `PublicApplicationIn` and `CandidateIn`
   (`models/hrms.py:1149`) — the manual-add path must capture the same thing:
   ```
   is_referral        bool = False
   referred_by        Optional[str]     # name of the referrer
   referral_source    Optional[ReferralSource]
   referrer_employee_code  Optional[str]   # e.g. EMP-2026-014
   referral_relation  Optional[str]
   ```
   `class ReferralSource(str, Enum)`: `EMPLOYEE`, `EX_EMPLOYEE`, `CONSULTANT_AGENCY`,
   `JOB_PORTAL`, `SOCIAL_MEDIA`, `WALK_IN`, `CLIENT`, `OTHER`.

2. **Validation, server-side.** When `is_referral` is true, `referred_by` **and**
   `referral_source` are required (422 otherwise). When `referral_source == EMPLOYEE`,
   `referrer_employee_code` is required and must match the employee-code format; validate it
   against `hrms_employee_profiles` for the posting's company and resolve the name into
   `referrer_name` on the candidate record.

3. **PRIVACY — non-negotiable.** The public form must **not** expose an employee picker,
   autocomplete or directory search. The applicant types a code; the server resolves it.
   An invalid code produces a generic *"We could not verify that employee code"* — it must
   not reveal whether the code exists, matching the `INVALID_LINK` discipline in
   `hrms_public_guard.py`. Do **not** add any public endpoint that reads
   `hrms_employee_profiles`.

4. **Effects.** Referral candidates set `source = "Referral"` so they land correctly in the
   existing `source` breakdown; add the `referral_source` breakdown dimension (Item 4 §5);
   notify the referring employee in-app when their referral is created and again when it
   reaches `SELECTED` / `JOINED` (`notify_user`, never email by default).

5. **UI.**
   - `pages/hrms/public/ApplyPage.jsx` — a "Were you referred?" toggle that reveals the
     fields. Collapsed by default; no layout shift for the majority who were not.
   - `recruitment/CandidatePipeline.jsx` add-candidate modal — the same fields.
   - Candidate detail / `CandidateJourney.jsx` — a "Referral" block showing referrer, source
     and resolved employee.
   - `REPORT_ENTITIES["candidates"]` — add `referred_by` and `referral_source` columns so
     the existing report and export pick them up automatically.

---

### ITEM 6 — Budget approval on the requisition

**Requested:** capture **Budget Sanctioned by Management** and **Budget Approved by HOD**;
on mismatch or pending approval, fire an automatic notification to the concerned
stakeholders.

**Current state.** `RequisitionIn` (`models/hrms.py:789-811`) carries a single
`offering_ctc: Optional[float]`, and `RequisitionAction` lets MD revise it via
`salary_change`. There is **no dual budget capture and no mismatch detection**.

**Build.**

1. **Model — extend `RequisitionIn` / `RequisitionUpdate`** (all optional, defaults preserve
   existing behaviour):
   ```
   budget_sanctioned_amount   Optional[float]   # by management
   budget_sanctioned_by       Optional[str]     # user_id
   budget_sanctioned_ref      Optional[str]     # approval reference / note
   budget_sanctioned_on       Optional[str]     # YYYY-MM-DD
   budget_hod_amount          Optional[float]   # approved by HOD
   budget_hod_by              Optional[str]
   budget_hod_on              Optional[str]
   budget_remarks             Optional[str]
   ```

2. **Derived, never stored:** `budget_status` computed on read —
   ```
   Not Set    both absent
   Pending    exactly one present
   Matched    both present and equal within BUDGET_TOLERANCE
   Mismatch   both present and outside tolerance
   ```
   `BUDGET_TOLERANCE = 0.0` by default (exact match); make it a module constant with a
   comment, not a magic number. Computing it means a later correction can never leave a
   stale flag.

3. **Notification triggers** (via `hrms_notify_service`, all fire-and-forget):
   - On requisition create/update where `budget_status == Mismatch` → notify HR **and** MD
     of the company (`notify_hrms_role(company_id, ["HR", "MD"], …)`) plus the creator, with
     both figures and the delta in the message body.
   - On `budget_status == Pending` at HR review → notify the HOD/department head
     (`hrms_departments.head_user_id`) that their approval is outstanding.
   - Deep-link every notification to `/hrms/requisitions` via the `link` meta field.

4. **Approval-gate rule.** A `Mismatch` does **not** block approval — that is a business
   call, not a system one — but `md-approve` on a mismatched requisition **requires
   remarks**. Implement this as data, by extending the `REQ_TRANSITIONS` tuple's
   `remark_required` slot into a callable or by a documented conditional check in
   `hrms_requisition_service`. Whichever you choose, the rule must be visible in one place,
   not scattered through the handler.

5. **UI.** A "Budget" section in `RequisitionFormModal.jsx` (both figures + refs + dates),
   a `budget_status` chip on `RequisitionList.jsx` and `RequisitionDrawer.jsx`, and a
   side-by-side sanctioned-vs-approved comparison with the delta highlighted in
   `ApprovalDialog.jsx`. Add `budget_status` to `REPORT_ENTITIES["requisitions"]` columns.

---

### ITEM 7 — Manpower Requisition Form: Replacement, Sanction-vs-Actual, Escalation

**Requested:** *Replacement* · *Sanction vs Actual* · *if the vacancy is not sanctioned then
escalation as per hierarchy, but MD is compulsory*.

**Current state.** `ReqApproval` is a 4-state machine (`PENDING_HR → PENDING_MD → APPROVED |
REJECTED`, `models/hrms.py:674-732`); MD approval is already mandatory for every
requisition. There is **no replacement flag, no sanctioned-headcount concept and no
escalation ladder**. `GET /hrms/employees/{user_id}/hierarchy` (`routes/hrms.py:369`)
already resolves a reporting chain — reuse it, do not build a second one.

**Build.**

1. **Replacement.** Extend `RequisitionIn` / `RequisitionUpdate`:
   ```
   requisition_type          RequisitionType = NEW_POSITION      # New Position | Replacement
   replacement_for_user_id   Optional[str]    # required when Replacement
   replacement_for_name      Optional[str]    # denormalised
   replacement_reason        Optional[str]    # required when Replacement
   last_working_day          Optional[str]    # YYYY-MM-DD
   ```
   Server rule: `Replacement` ⇒ `replacement_for_user_id` and `replacement_reason` required
   (422). The referenced employee must belong to the same company — validate it, same rule
   as the `forward_to_id` check in `hrms_candidate_service.py:411`.

2. **Sanctioned strength master.** `COLL_SANCTIONED_STRENGTH = "hrms_sanctioned_strength"`:
   ```
   company_id, department_id, designation_id, sanctioned_count,
   effective_from, notes, updated_by, updated_at
   ```
   Unique index on `(company_id, department_id, designation_id)`.
   **Actual** strength is *derived*, never stored — count `hrms_employee_profiles` with
   `employment_status ∈ PAYABLE_STATUSES` (`models/hrms.py:526`) for that
   department + designation. A stored count would drift the moment somebody resigns.

   API: `GET|POST|PATCH|DELETE /hrms/sanctioned-strength` under a new
   `Cap.SANCTION_READ` / `Cap.SANCTION_WRITE` (HR/MD write, MANAGER/INTERNAL read),
   plus `GET /hrms/sanctioned-strength/position?department_id&designation_id` returning
   `{sanctioned, actual, open_requisitions, available, is_over_sanction}` for live display
   on the requisition form.

3. **The over-sanction rule.** A requisition is **over-sanction** when
   `actual + open_approved_vacancies + this.vacancy > sanctioned`, or when no sanctioned
   figure exists for that position at all. Compute it once, at raise time and again at each
   approval step (headcount moves between the two), and store the evaluated snapshot on the
   requisition (`sanction_snapshot: {sanctioned, actual, requested, is_over_sanction,
   evaluated_at}`) so the approver sees the figures the decision was made on.

4. **Escalation chain.** Add `ReqApproval.PENDING_ESCALATION = "Pending Escalation"` and
   an `escalation_chain[]` on the requisition:
   `[{level, user_id, name, role, status: Pending|Approved|Rejected, acted_at, remarks}]`.
   - **In-sanction** requisitions keep today's chain **unchanged**: `PENDING_HR → PENDING_MD
     → APPROVED`. Existing behaviour must not regress.
   - **Over-sanction** requisitions route `PENDING_HR → PENDING_ESCALATION → PENDING_MD →
     APPROVED`. The escalation levels are built from the raiser's reporting chain via the
     existing `/employees/{user_id}/hierarchy` resolver, deduplicated, capped at
     `MAX_ESCALATION_LEVELS = 5`.
   - **MD is compulsory and cannot be skipped or short-circuited**, whatever the chain
     resolves to. Encode this as an assertion in the transition guard, not as a comment:
     the terminal `APPROVED` state is reachable only from `PENDING_MD` via
     `Cap.REQUISITION_APPROVE_MD`. Add an explicit test named
     `test_over_sanction_cannot_reach_approved_without_md`.
   - New actions in `REQ_TRANSITIONS`: `"escalate-approve"` and `"escalate-reject"`
     (`remark_required=True` for the reject), gated by a new
     `Cap.REQUISITION_ESCALATE` held by MANAGER and MD. Add matching entries to
     `REQ_AUDIT_ACTIONS` so the audit trail cannot drift from the table.
   - If the hierarchy resolves to nobody (an orphaned raiser), fail **closed**: route
     straight to `PENDING_MD` and record why in the audit detail. Never auto-approve.

5. **Notifications** at every hop: the next approver in the chain gets one; the raiser gets
   one on each decision; MD is told the requisition is over-sanction with the
   sanctioned-vs-actual figures in the message.

6. **UI.**
   - `RequisitionFormModal.jsx` — a "Position & sanction" block: requisition-type radio,
     replacement fields revealed conditionally, and a live sanctioned/actual/available
     readout that turns amber the moment the requested vacancy exceeds the sanction, with
     the sentence *"This requisition exceeds the sanctioned strength and will be escalated
     for approval. MD approval is mandatory."*
   - `RequisitionList.jsx` / `RequisitionDrawer.jsx` — a "Replacement" badge, an
     "Over-sanction" badge, and the escalation chain rendered as a vertical stepper showing
     who has acted.
   - `ApprovalDialog.jsx` — the sanction snapshot and the escalation position shown to the
     approver before they act.
   - New master screen `features/hrms/people/SanctionedStrength.jsx` at
     `/hrms/sanctioned-strength`, added to `hrmsSubmodules` beside Departments and
     Designations (admin-only, same `isHrmsAdminUser` condition).

---

## 5. EXPLICIT NON-GOALS

Do not build, refactor or "improve" any of these, even if they look adjacent:

- Leave, holidays, attendance, payroll, payslips (Phases 12–14).
- The HRMS settings console or the per-user permission-grant matrix (Phase 11 proper).
- Any change to the offer letter's own flow, template or public page beyond what Item 3
  explicitly requires.
- Email/SMTP wiring, an outbox, or any second delivery stack.
- Renaming, re-numbering or re-ordering existing enum values, `STAGE_RANK` entries,
  collection names, index names, route paths or capability strings.
- Rewriting existing services for style, adding type hints throughout, or reformatting
  files you are otherwise touching. Keep diffs minimal and reviewable.

---

## 6. DECISIONS TO CONFIRM BEFORE WRITING CODE

Ask these, get answers, then build. Do not guess.

1. **What is a "client" in Item 4?** In this ERP, `company_id` *is* the client — HRMS is a
   client-company module and the company selector already exists.
   *Default assumption if unanswered:* the client-wise dropdown **is** the existing company
   scope selector (`GET /hrms/companies` + `HrmsScopeBar`), extended with an internal-only
   "All clients" comparison view; and the "shared with client / client-side shortlisted /
   client-side rejected" metrics come from the new `client_share` sub-record on the
   candidate, representing CVs sent to the hiring client for their verdict.
   *The alternative* — the HRMS user is a recruitment agency with its own separate client
   master, distinct from `company_id` — would need a new `hrms_clients` collection and a
   `client_id` on every requisition. That is a materially larger change; confirm before
   taking it.

2. **Appointment letter vs offer letter.** Confirm these are two separate documents (the
   offer is issued at selection, the appointment letter at joining confirmation). If they
   are the same document in this business, Item 3 collapses into extra statuses on
   `hrms_offers` and should be built that way instead.

3. **Sanctioned strength granularity.** Department + designation (assumed), or department
   only, or department + designation + location?

4. **Budget mismatch severity.** Confirm that a mismatch warns-and-notifies but does not
   block MD approval (assumed), rather than hard-blocking.

---

## 7. DEFINITION OF DONE

Follow the roadmap's S1–S4 discipline (`docs/HRMS_IMPLEMENTATION_ROADMAP.md` §2) — it is
the house standard and this phase does not get an exemption.

**S1 — Smoke (must be 100% green)**
1. `uvicorn main:app` starts clean; startup log shows the new `hrms_*` collections
   provisioned; no new warnings.
2. `npm run build` succeeds; `npm run lint` reports **no new** errors.
3. Browser console clean across Login → Dashboard → Calendar → Tasks → TPMS → ORM →
   Reports → Settings → Profile.
4. Zero backend 5xx during the walkthrough.
5. Each non-HRMS module still performs one real write (create task, create event, open a
   TPMS form, open an ORM sheet, load the notification bell).

**S2 — Regression (the scope fence, proven)**
1. `git diff --stat` — **every** file outside `hrms*` is on the §1.2 list, with a written
   reason in the phase report.
2. `grep -c "@router" backend/app/routes/*.py` — unchanged for every non-HRMS router.
3. `App.jsx` route diff — every pre-existing route byte-identical.
4. Collection inventory diff — only new `hrms_*` collections appear.
5. Every existing HRMS test (`test_phase1_*` … `test_phase10_*`) still passes, **unmodified**.
   If one of them must change, that is a signal you broke a contract — stop and re-read.
6. The 4 canonical roles (superadmin / admin / clientadmin / clientuser) see the correct
   sidebar and are refused what they should be, across Tasks / TPMS / ORM / HRMS.

**S3 — Test dimensions**, per item: Positive · Negative · Edge · Permission · Validation ·
API (status codes + payload shape) · Database (indexes, uniqueness, idempotency) · Frontend
(render, empty/loading/error states, interactions) · End-to-End.

**S4 — Deliverables**
- All seven items implemented and working end to end.
- `backend/app/services/hrms/tests/test_phase11_*.py` — one file per item, all green.
- `docs/hrms/PHASE_11R_REPORT.md` — what shipped, tests run and their results, every
  deviation from this prompt with its reason, issues found and fixed, residual risk, and
  the §1.2 shared-file diff justification.
- `docs/hrms/PHASE_11R_TEST_SCRIPT.md` — the manual walkthrough, in the style of the
  existing `PHASE_N_TEST_SCRIPT.md` files.
- `docs/hrms/OUT_OF_SCOPE_FINDINGS.md` — any new `OOS-NNN` entries, documented and
  **not fixed**.

**Commit discipline:** work on the current `HRMS_NEW` branch. Never merge or push to `main`.
