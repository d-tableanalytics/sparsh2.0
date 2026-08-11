# Phase 11-R — Recruitment Review Enhancements

**Branch:** `HRMS_NEW`  ·  **Date:** 2026-08-11  ·  **Scope:** the seven review items, and nothing else.

---

## 1. Decisions taken before any code was written

§6 of the phase prompt required four questions to be answered rather than guessed. They were
put to the business and answered as follows. **One of them departs from the prompt's stated
default and materially widened the work** — it is called out first.

| # | Question | Answer | Effect |
|---|---|---|---|
| 1 | What is a "client"? | **Separate client master (agency model)** — *not* the prompt's default | ⚠️ **Deviation.** The prompt assumed `company_id` *is* the client and that the existing scope selector would serve. It does not. This deployment recruits *on behalf of* client organisations, so Item 4 additionally required a new `hrms_clients` collection, a `client_id` on every requisition, a client master screen, two new capabilities, and a client dimension threaded through five analytics endpoints. |
| 2 | Appointment letter vs offer letter | **Two separate documents** | Item 3 built as specified: its own collection, its own lifecycle, its own public page. |
| 3 | Sanctioned-strength granularity | **Department + designation** | As assumed. A location axis was offered and declined — see §6. |
| 4 | Budget mismatch severity | **Warn + notify; remarks required; never blocks** | As assumed. Implemented as `REQ_CONDITIONAL_REMARKS`. |

### The client is a reporting dimension, never a security boundary

This is the single most important consequence of decision 1, and the property most worth
re-checking in review. `company_id` remains the **only** tenant scope; `client_id` narrows
*within* one tenant. Concretely:

* every client query carries `company_id`, so a client id from another tenant finds nothing;
* `_scope(actor, company_id, client_id)` composes the client filter with the MANAGER row
  scope by **intersection**, so a hiring manager filtering by client can only ever see
  *fewer* rows, never more;
* an unknown client resolves to `$in: []` — matching nothing, failing closed.

All three are asserted in `test_phase11_clients.py` §"Analytics: the client filter NARROWS,
never widens".

---

## 2. What shipped, item by item

### Item 1 — Link generation: one process, trackable and retrievable

`hrms_links` + `services/hrms_link_service.py` + `utils/hrms_public_guard.assert_link_live`
+ `features/hrms/links/LinkManager.jsx` at `/hrms/links`.

* **Registration is additive and fire-and-forget.** The four existing mint sites (posting,
  assessment, offer, onboarding) call `register_link` immediately after generating their
  code. No code, return shape or failure mode of those services changed. `register_link`
  never raises: a registry outage cannot stop an offer going out
  (`test_phase11_links` asserts this by breaking the collection).
* **Revocation is enforced, not displayed.** Every public handler calls `assert_link_live`
  before doing any work, and a revoked or expired link gets the **existing** vague
  `CLOSED_LINK` message — indistinguishable from a filled position, so the endpoint cannot
  reveal that a link was withdrawn from one person.
* **Expiry is computed, never stored.** `effective_link_status(doc, today)` — same
  discipline as `hrms_posting_service._effective_status`.
* **Legacy links keep working.** A code with no registry row reads Active and passes. No
  migration script exists or is needed (§3.2).
* **`external` postings are deliberately absent** from the register: applications made on a
  job board never reach this pipeline, so a row promising tracking would be a lie. The Link
  Manager says so in the permanent process panel.
* **Reissue delegates.** It asks the owning service for a fresh code and revokes the old
  one; `apply` links cannot be reissued because their code is printed on published ads.

**"Where did you find this job."** The review asked for one form link carrying a mandatory
source block rather than a link per platform. `referral_source` is now **required** on
`POST /hrms/public/apply/{code}` — see §5, deviation D3, because this is the one contract
change in the phase.

### Item 2 — Documentation module

`hrms_documents` + `hrms_document_types` + `services/hrms_document_service.py` +
`DocumentCenter` / `DocumentTypeManager` / `DocumentPanel`.

* **Existing files are surfaced, never copied.** Candidate resumes, photos, certificates and
  onboarding KYC scans stay on their own records; `list_linked()` projects them into the
  register's shape with `source: "linked"`, `read_only: true`. Copying the S3 objects would
  create a second copy free to drift and double the storage. Asserted explicitly.
* **The file is immutable; corrections are versions.** `update_document` changes metadata
  only. A new version resets the status to `Uploaded` and clears any verification — a
  document that was verified and has since been *replaced* is not verified.
* **Expiry is computed** (`expiry_date < today`), and cannot be set by hand. `Rejected`
  outranks expiry, being the more actionable answer.
* **The checklist states absences.** Every applicable type appears with its status or
  `Pending`, which is the question the module exists to answer.
* **Default types seed on first read** — migration-free, and fires exactly once.
* Deleting a type in use is refused; deleting a *verified* document is refused (reject it
  instead). S3 objects are left in place on delete: a register correction must not destroy
  somebody's PAN scan on a mis-click.

### Item 3 — Appointment Letter stage

`hrms_appointments` + `services/hrms_appointment_service.py` +
`POST|GET /hrms/public/appointment/{code}` + `AppointmentBoard` / `AppointmentPaper` /
`AppointmentPage`.

* **The candidate has one stage; the artifact has its own state machine.**
  `AppStatus.APPOINTMENT_LETTER_SENT` is the pipeline stage; Generated / Sent / Pending
  Acknowledgement / Acknowledged / Cancelled live on the letter.
* **The stage is optional by construction.** `FORWARD_TRANSITIONS` keeps the direct
  `Offer Accepted → Pre-Onboarding` edge alongside the new one, so a company that issues no
  appointment letters is unaffected by this feature existing.
* **`STAGE_RANK` was not renumbered.** The new stage sits at rank 7, the same band as
  `OFFER_ACCEPTED` / `PRE_ONBOARDING`. The funnel stays monotonic and every Phase 10 figure
  keeps its meaning.
* **Journey rail — decision stated as required.** The rail stays **7 steps**; the
  appointment letter joins the existing **Offer** step rather than becoming an 8th. It is a
  second paper in the same "terms agreed" phase, and an 8th step would re-flow a rail every
  existing screen renders.
* `FILLED_STATUSES` gained it, so a requisition does not *re-open* the moment the letter
  goes out. `ONBOARDABLE_STATUSES` gained it too (it sits strictly after Offer Accepted, so
  the consent argument in the Phase 9 comment is satisfied a fortiori).
* **Items 2 and 3 are one system:** sending files the letter as an `hrms_documents` row;
  acknowledging flips that row to `Verified`. Idempotent, so send-then-acknowledge produces
  one document, not two.

### Item 4 — Client-wise recruitment analytics

`hrms_clients` + `services/hrms_client_service.py` + `client_share` on the candidate +
`GET /hrms/analytics/positions` + `ClientManager` + dashboard client dropdown.

* **`ScreenAction.SHARE_WITH_CLIENT`** is distinct from `FORWARD`: forward assigns an
  internal owner and moves nobody, this sends the CV *out* and opens a `client_share`
  record. Three new statuses (`Shared with Client`, `Client Shortlisted`,
  `Client Rejected`) are wired into every table that names stages.
* **The client band ranks *with* shortlisting (rank 2), not after it.** Sharing a CV is a
  decision *about* a shortlisted candidate; ranking it higher would inflate the funnel.
  `Client Rejected` ranks where it entered, exactly as `REJECTED` does.
* **`SHARED_WITH_CLIENT → INTERVIEW_SCHEDULED` is legal.** A client who never answers must
  not be able to strand a candidate.
* **New metric formulas** (repeated here as required):
  * `reviewed` = `effective_rank ≥ rank(Under Review)` — by evidence, so a candidate now at
    Offer Accepted still counts as reviewed;
  * `selected` = `effective_rank ≥ rank(Selected)`;
  * `rejected` = status ∈ {Rejected, Client Rejected, Duplicate, Assessment Failed, Offer
    Declined} — a *status*, not a rank, because a rejection is a destination;
  * `joinings` = status ∈ {Joined, Employee Created};
  * `shortlist_rate` = client shortlisted ÷ (shortlisted + rejected) — measured against CVs
    the client has actually **answered on**, so a slow client does not read as a quality
    problem.
* **Position matrix** columns are generated from `AppStatus` itself, so a stage added in a
  later phase appears automatically rather than silently vanishing from a report.
* **The write path lives in `hrms_candidate_service`, not analytics.**
  `hrms_analytics_service` remains read-only; the test greps its source for every mutating
  driver call.
* **No public client portal** was built. That would be a second unauthenticated surface with
  its own credentials, rate limits and threat model — far beyond what the review asked. The
  verdict is recorded by an HRMS user on the client's behalf.

### Item 5 — Referral capture

`services/hrms_referral_service.py` — **one** resolver used by both the public form and the
manual add-candidate path, so a referral typed by HR is validated and stored identically to
a self-declared one.

* **Privacy is the constraint that shaped the module.** There is no public endpoint that
  reads `hrms_employee_profiles`, no picker, no autocomplete. The applicant types a code;
  the server resolves it. **Unknown, wrong-tenant and malformed codes all produce one
  identical opaque message** — asserted by comparing the three literal strings.
* The code is pattern-checked against `EMPLOYEE_CODE_RE` **before** any query, so an
  operator document cannot reach Mongo.
* An `Employee` referral *must* resolve. Any other source treats the code as optional
  context and drops an unresolvable one silently — losing an application because somebody
  mistyped a colleague's staff number is a poor trade.
* Referrals set `source = "Referral"` so they land in the existing Phase 10 breakdown.
  A **non**-referral's answer is recorded as `referral_source` **without** overwriting
  `source`: the posting's platform is a fact about the posting, the applicant's answer is a
  fact about the applicant, and both are worth keeping.
* The referrer is notified in-app on creation and at two milestones only (Selected, Joined).
  Never by email by default — a notification channel that fires on every stage gets muted.

### Item 6 — Budget approval

* `budget_status` is **derived on every read** (`models.budget_status`) and never stored, so
  a correction can never leave a stale flag. Documents written before this phase read
  `Not Set`, which is the truth about them.
* `BUDGET_TOLERANCE = 0.0` is a named constant with a comment, not a magic `==`.
* Unreadable figures read `Mismatch` — never silently `Matched`.
* **The conditional-remarks rule lives in one declared place**, `REQ_CONDITIONAL_REMARKS`,
  keeping `REQ_TRANSITIONS` a 4-tuple so no existing consumer changed shape. A mismatch
  **warns and notifies but never blocks**; MD must record a remark when approving over one.
* Mismatch notifies HR, MD *and* the creator **with both figures and the delta in the
  message body** — a notification that makes you open a screen to learn anything is a poor
  notification. Pending routes to the department head who owes the missing figure.
* Notifications fire on **update** as well as create: the correction is exactly the moment
  people need to know.

### Item 7 — Replacement, sanction vs actual, escalation

* **Replacement** requires the person and the reason (422 otherwise), checked against the
  **merged** document on edit so an update cannot empty out what made it valid.
* **Sanctioned is stored; actual is derived.** `actual` counts `hrms_employee_profiles` in
  `PAYABLE_STATUSES` on every read. A stored figure would be wrong the moment somebody
  resigned — and "somebody resigned, can we backfill" is precisely the question this answers.
* **Committed vacancies are counted** (approved + still-open requisitions), or five
  requisitions for one seat each would all pass the check independently. A requisition is
  never measured against itself.
* **No sanctioned figure at all = over-sanction.** `is_over_sanction` fails **closed**: an
  unauthorised headcount is exactly the case worth escalating. Companies that do not run
  sanctioned strength will find everything escalates, and the requisition form says so
  before submission.
* **The snapshot is stored** — the one place a derived figure is deliberately written down,
  because the approver must see the numbers the decision was made on.
* **MD is compulsory, and it is asserted from the table rather than trusted.**
  `models.md_approval_is_mandatory()` verifies that `APPROVED` is reachable from exactly one
  row, that the row starts at `PENDING_MD`, and that it demands
  `Cap.REQUISITION_APPROVE_MD`. `test_over_sanction_cannot_reach_approved_without_md` checks
  it three ways, including driving a real over-sanction requisition and confirming a
  premature `md-approve` is a 409.
* **An orphaned raiser fails closed**: with no reporting chain the requisition routes
  *straight to MD*, never auto-approves, and the gap is written to the audit trail.
* The escalation ladder **reuses `hrms_employee_service.get_hierarchy`** rather than walking
  `reporting_manager` a second time. Its cycle sentinel is honoured and the raiser is never
  a rung on their own ladder.
* **In-sanction requisitions are untouched**: `PENDING_HR → PENDING_MD → APPROVED`, byte for
  byte, asserted directly.

---

## 3. Issues found and fixed during the work

**Finding #1 — `assert_link_live` turned a database hiccup into a 503 on every public page.**
`get_db()` raises `HTTPException(503)` when Mongo is unreachable. The guard's
`except HTTPException: raise` clause — written to let its own intentional 410 through —
re-raised that 503 instead, so every candidate-facing page would have failed whenever the
database blinked. The intentional 410 is raised *outside* the try block, so the clause was
never needed. Caught by `test_phase4_public_security` (12 failures). Fixed by catching bare
`Exception`, with a comment explaining why the broader catch is the correct one here.
Logged as **OOS-006** because the underlying hazard belongs to `mongodb.py`.

**Finding #2 — the escalation chain read keys the hierarchy resolver does not return.**
`_build_escalation_chain` looked for `chain` / `managers` / `upward`; `get_hierarchy`
returns `manager_chain`. Every ladder would have resolved empty and every over-sanction
requisition would have routed straight to MD — failing closed, so not a security hole, but
silently disabling the whole feature. Found by reading the resolver while wiring the
employee profile. Fixed, and its cycle sentinel (`circular: True`) is now honoured too.

**Finding #3 — `record_open` used three round trips and a non-atomic read-then-write.**
Rewritten onto a single `find_one_and_update`, so two concurrent opens cannot both read the
same count and write it back.

**Finding #4 — the shared test double silently no-oped on three real Mongo operators.**
`FakeCollection` ignored `$set` inside `find_one_and_update`, had no `update_many`, and
treated dotted paths (`client_share.status`) as literal keys. Each gap fails *silently* —
the service appears to work while the write goes nowhere. Extended to be faithful; logged as
**OOS-007**. All 20 pre-existing test files were re-run afterwards and are unchanged.

---

## 4. Verification

### S1 — Smoke

| Check | Result |
|---|---|
| Backend imports and assembles (`import main`) | ✅ clean, no new warnings |
| New collections provisioned from `HRMS_INDEXES` | ✅ 21 new index declarations across 6 new collections |
| `vite build` | ✅ exits 0, no errors |
| `npm run lint` | ⚠️ **not run** — see §7 |
| Browser walkthrough, non-HRMS module writes | ⚠️ **not run** — see §7 |

### S2 — Regression (the scope fence, proven)

| Check | Result |
|---|---|
| Files changed outside `hrms*` | ✅ exactly two — `App.jsx`, `Sidebar.jsx`, both on the §1.2 allow-list |
| `@router.` counts per non-HRMS router | ✅ unchanged for all 26; `hrms.py` 71 → 109, `hrms_public.py` 8 → 10 |
| `App.jsx` pre-existing routes | ✅ no pre-existing route line altered; additions are 7 imports + 7 route lines |
| Collection inventory | ✅ only new `hrms_*` collections appear |
| **All 20 pre-existing HRMS test files** | ✅ green — see the note below on the four assertions that had to move |
| 7 new Phase 11-R test files | ✅ green |

**Total: 2,543 checks across 28 files, all passing.**

#### The four pre-existing assertions that changed, and why

§S2.5 asks that existing tests pass **unmodified**, and says that needing to change one is a
signal a contract broke. Four assertions could not be satisfied simultaneously with the
phase's own explicit instructions. Each is reported rather than quietly adjusted:

| File | Assertion | Why it could not stand |
|---|---|---|
| `test_phase3_requisition.py` | `len(REQ_TRANSITIONS) == 4` | Item 7 **explicitly requires** adding `escalate-approve` and `escalate-reject` to `REQ_TRANSITIONS`. Replaced with a check that the four Phase 3 actions are still present **plus** `md_approval_is_mandatory()` — which guards the property the count was standing in for. |
| `test_phase3_requisition.py` | `illegal_ok == 12` | Same cause: 6 actions × 5 statuses. The expected count is now **derived from the table** instead of hard-coded, so it extends automatically rather than restating the table's size. |
| `test_phase9_onboarding.py` | `ONBOARDABLE_STATUSES == {OFFER_ACCEPTED}` | Item 3 **explicitly requires** adding `APPOINTMENT_LETTER_SENT`. Replaced with the *rule* it encoded: every onboardable stage is at or past Offer Accepted. |
| `test_phase10_analytics.py` | `len(kpis) == 8` | Item 4 adds 7 tiles. Relaxed to `>= 8`; the tiles that matter to Phase 10's arithmetic are checked **by key** on the following lines, which was always the real contract. |

In each case the *pinned snapshot* was replaced with the *invariant it was approximating*.
No behavioural assertion was weakened.

Two further edits were made to test files, neither an assertion:
`test_phase4_posting.py`'s `application()` fixture now sends `referral_source` (see D3), and
`FakeCollection` was extended (Finding #4).

---

## 5. Deviations from the phase prompt

**D1 — Item 4 built on the agency model, not the company-scope model.**
Decision 1 in §1. The prompt's default (client == `company_id`) was explicitly rejected by
the business. Consequence: a new collection, two capabilities, a master screen, and
`client_id` threaded through five analytics endpoints. The prompt anticipated this
possibility and asked for confirmation before taking it; confirmation was obtained.

**D2 — `REQ_TRANSITIONS` kept its 4-tuple shape.**
Item 6 offered "extending the `remark_required` slot into a callable **or** a documented
conditional check". The tuple was left alone and `REQ_CONDITIONAL_REMARKS` added beside it,
because changing the tuple's shape would have broken four existing assertions that unpack
`spec[3]` — for no gain, since the rule is equally visible in one place either way.

**D3 — `referral_source` is now required on the public application endpoint.**
The only change to an existing contract. Item 1 requires the source block to be mandatory;
§3.5 requires server enforcement of any rule that matters. §3.1's "existing endpoints keep
their payload shapes" cannot hold simultaneously. Server enforcement was chosen, because a
`required` attribute in a browser guarantees nothing about a request. Recorded as OOS-008.

**D4 — The journey rail stays at 7 steps.** Item 3 asked for a decision and a statement;
see §2 Item 3.

**D5 — No public client portal (Item 4).** Out of proportion to the review; the verdict is
recorded on the client's behalf. Stated in the service docstring and here.

**D6 — Sanctioned strength has no location axis.** Offered in decision 3 and declined:
employee profiles carry no location field, so `actual` could not be derived per location,
and a sanctioned figure with nothing to compare against is worse than none.

---

## 6. Shared-file diff justification (§1.2)

Exactly two files outside `hrms*` were touched. **Both were already modified in the working
tree before this phase began** (they appear as `M` in the session's opening `git status`), so
a raw `git diff` against `HEAD` mixes prior work with this phase's. The Phase 11-R lines are:

**`frontend/src/App.jsx`** — append-only.
7 imports added after the last HRMS import; 1 public route (`/appointment/:code`) added
beside the existing four; 6 child routes added at the end of the existing `/hrms` block.
No pre-existing route was reordered, edited or deleted; no non-HRMS route was touched.
*Necessary because* it is the only route table — a screen not registered here is unreachable.

**`frontend/src/components/layout/Sidebar.jsx`** — append-only.
2 icon imports (`FolderOpen`, `FileCog`); `appointments` and `links` appended to
`HRMS_WORKSPACE`; `Documents` appended to `hrmsSubmodules` plus 3 admin-only entries
(`Clients`, `Document Types`, `Sanctioned Strength`) appended to the existing
`isHrmsAdminUser` branch. No other nav group, roles array or shared layout markup changed.
*Necessary because* it is the only nav — and the two lists were kept **disjoint** per the
note in `HrmsWorkspaceBar.jsx`: pipeline stages (Appointments, Links) went to the tab strip,
non-stage screens (Documents, the masters) went to the sidebar.

`backend/main.py` and `backend/app/db/mongodb.py` needed **no change**, as the prompt
predicted — both routers are already mounted and provisioning already reads `HRMS_INDEXES`.

---

## 7. Residual risk / not done

1. **`npm run lint` was not executed** in this session. `vite build` passes (which catches
   syntax, import and resolution errors) but lint-only rules — unused variables, exhaustive
   deps — have not been checked on the ~20 changed/added frontend files. **Run before merge.**
2. **No browser walkthrough was performed.** S1's manual checks (console clean across the
   non-HRMS modules, one real write per module, zero 5xx) are scripted in
   `PHASE_11R_TEST_SCRIPT.md` and remain outstanding.
3. **No test ran against a real MongoDB.** The harness uses `FakeCollection`. Unique-index
   behaviour (`uniq_candidate` on appointments, `uniq_company_position` on sanctioned
   strength, `uniq_code` on links) is asserted only as a *declaration*, not exercised. The
   services all pre-check and translate duplicate-key errors, but the first real run is the
   first true test of those indexes.
4. **S3 uploads are stubbed in tests.** `hrms_document_service._store` is replaced; the real
   `upload_file_to_s3_with_key` path is unexercised. It is the same call
   `hrms_posting_service` already makes in production.
5. **The escalation ladder depends on `reporting_manager` data quality.** Where it is unset,
   everything routes straight to MD (correct, and logged) — but on a company with sparse
   reporting data the escalation feature will appear to do nothing. Worth checking the data
   before demonstrating it.
6. **`positions` and `_client_comparison` load candidates into memory** under `SCAN_CAP`
   (20,000), consistent with the rest of the module. At genuinely large volume these want to
   become aggregations.
7. **Document types seed on first read.** Two truly simultaneous first reads race; the
   unique index makes the loser's `insert_many` fail, which is caught and logged, and the
   next read returns the winner's set. Benign, but it is a race.

---

## 8. Files

**New backend (6 services + 7 test files)**
`hrms_link_service.py` · `hrms_document_service.py` · `hrms_appointment_service.py` ·
`hrms_client_service.py` · `hrms_sanction_service.py` · `hrms_referral_service.py` ·
`tests/test_phase11_{links,documents,appointments,clients,referral,budget,sanction}.py`

**Modified backend (10)**
`models/hrms.py` · `routes/hrms.py` · `routes/hrms_public.py` · `utils/hrms_public_guard.py` ·
`services/hrms_{analytics,assessment,candidate,offer,onboarding,posting,requisition}_service.py`

**New frontend (8)**
`links/LinkManager.jsx` · `documents/{DocumentCenter,DocumentTypeManager,DocumentPanel}.jsx` ·
`clients/ClientManager.jsx` · `people/SanctionedStrength.jsx` ·
`recruitment/{AppointmentBoard,AppointmentPaper}.jsx` · `pages/hrms/public/AppointmentPage.jsx`

**Modified frontend (12)**
`services/{hrmsApi,hrmsPublicApi}.js` · `features/hrms/access.js` ·
`analytics/RecruitmentDashboard.jsx` · `people/EmployeeProfile.jsx` ·
`recruitment/{ApprovalDialog,CandidateJourney,CandidatePipeline,RequisitionDrawer,RequisitionFormModal,RequisitionList,ScreeningBoard}.jsx` ·
`pages/hrms/public/ApplyPage.jsx`

**Shared (2, append-only)** `App.jsx` · `Sidebar.jsx`

**Docs (3)** this report · `PHASE_11R_TEST_SCRIPT.md` · `OUT_OF_SCOPE_FINDINGS.md` (appended)
