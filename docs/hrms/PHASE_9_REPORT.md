# HRMS Phase 9 — Onboarding & Employee Creation · Phase Report

> **Status:** ✅ COMPLETE — all 13 steps passed
> **Scope:** pre-onboarding, KYC, background verification, the joining checklist, and the handover that turns a candidate into an employee
> **Roadmap:** [HRMS_IMPLEMENTATION_ROADMAP.md](../HRMS_IMPLEMENTATION_ROADMAP.md) § Phase 9
> **Scope rule honoured:** HRMS only. No new out-of-scope findings; the register stands at OOS-001…005.

This is the phase the whole pipeline has been heading towards. Both analysis documents named the same hole — *"Employee Management — Not found in current HRMS"* (BACKEND_ANALYSIS §2, FRONTEND_ANALYSIS §2). The source system could take a person all the way to an accepted offer and then had nowhere to put them. Phase 9 is where recruitment finally becomes an employee record.

---

## 1. What shipped

| Capability | Delivered |
|---|---|
| Start onboarding | Gated to `Offer Accepted`; terms pulled from the accepted offer |
| **Public pre-onboarding form** | Fourth anonymous surface — identity, bank, emergency contact, references, documents |
| Server-side identity validation | **PAN-or-Aadhaar enforced on the server**, plus IFSC, account, DOB, gender |
| KYC verification | A human confirms the documents; required before an Employee ID |
| Background verification | Four states; **Flagged blocks employee creation** |
| Joining checklist | 12 items, 3 of them system-owned |
| **Employee ID generation** | Mints `EMP-YYYY-NNN` **and creates the employee record** |
| **Link a login account** | Attaches an onboarding-created record to a real ERP user, later |
| Auto-completion | All 12 items done → Completed → candidate reaches `Employee Created` |

**3 new capabilities:** `onboarding.read`, `onboarding.write`, `onboarding.generate_id`.

---

## 2. The decision that shaped this phase

### An employee is created **before** they have a login

A new hire is not a user of the ERP. Their Employee ID is issued on day one; their account may appear days later, or never (a floor hire who never signs in still needs payroll). But Phase 2's employee master composes a person from *user document + HRMS profile*, and `create_profile` requires an existing `learners` user.

Two ways out:

| Option | Consequence |
|---|---|
| **(a) HRMS creates a `learners` login** | Puts an HR module in charge of authentication records it does not own. Breaks the *"HRMS never writes to `staff`/`learners`"* invariant asserted and tested in every phase since Phase 1. |
| **(b) Create the employee record unlinked** ✅ | The profile omits `user_id` entirely and carries an `identity_snapshot`. Nothing is written to an identity collection. |

**I took (b).** The profile omits `user_id` **entirely** — absent, not null, because a null value is still indexed and one unique index would then permit exactly one such row. `uniq_user` became `sparse`, the directory composes the person from the snapshot and flags them `pending_user_link`, and `POST /hrms/employees/link/{code}` attaches the account when it exists. From that moment the user document is the single source of identity and the snapshot is history.

Tested explicitly: after the handover, `learners` and `staff` are **byte-for-byte unchanged**.

> **If you would rather have (a)** — HRMS auto-provisioning a `learners` login at Employee ID time — say so and I will add it. It is a contained change, but it ends the identity-ownership invariant, so it is your call, not mine.

### Other decisions worth recording

**Only an accepted offer may be onboarded.** `ONBOARDABLE_STATUSES` was drafted as `{Offer Accepted, Selected}` and I narrowed it to `{Offer Accepted}` during design, for two reasons. The lifecycle graph declares `Selected → Offer Generated` with no edge to `Pre-Onboarding`, so a Selected onboarding could never reach the matching stage. And in substance: onboarding collects PAN, Aadhaar and bank details, which should not be gathered from somebody who may still say no.

**The checklist has two kinds of item.** Nine are human judgements (assets issued, induction done). Three — `employee_id`, `documents_verified`, `bg_cleared` — are claims the system can verify, so the system owns them and refuses a manual edit with a 409. Otherwise the checklist could assert "background cleared" while the verification sits at **Flagged**. `bg_cleared` moves in *both* directions: withdrawing a clearance un-ticks it.

**The disabled button explains itself.** `GET /hrms/onboarding/{no}` returns `id_blockers` as prose ("Background verification is flagged.", "A joining date has not been set."). A greyed-out control with no explanation is the single most common source of "the system is broken" tickets.

**Submitting is once-only.** HR verifies these details by hand; letting them change afterwards would silently invalidate that verification. A resubmit is a 409, and re-opening the link shows a calm done screen rather than an error — someone re-checking their own link has done nothing wrong.

**A completed onboarding is a record, not a document.** Edits are refused with a 409 pointing at the employee master, which is the live thing from then on.

---

## 3. Findings

### Finding #1 — every public file upload was broken 🔴 **FIXED**

`decode_upload` read its fields with `getattr`. Routes hand services `body.model_dump()`, which recursively converts nested `UploadIn` models into **plain dicts** — so `getattr(upload, "mime_type", "")` returned `""` and the guard rejected the file:

> *415 — "that file type is not accepted. Use PDF, Word or an image."*

**This was live in Phases 4 and 6.** Every résumé attached to a public job application, and every assessment attachment, was refused with a message blaming the candidate's file. It survived because the unit harnesses call services directly with `UploadIn` **objects**, and the shape only changes when a request passes through a real route.

```python
# before
data = getattr(upload, "data", "") or ""          # dict -> ""
mime = (getattr(upload, "mime_type", "") or "")   # dict -> "" -> 415

# after
def field(key):
    return (upload.get(key) if isinstance(upload, dict) else getattr(upload, key, "")) or ""
```

**Regression added**, deliberately at the HTTP layer where the defect actually lives: `test_phase9_integration` posts a real base64 PDF through `/api/hrms/public/onboard/{code}` and asserts it decodes, then asserts the same for Phase 4's `resume` and Phase 6's `attachments` after `model_dump()`. A bad mime type is still refused, so the fix widens the accepted *shape*, not the accepted *content*.

The lesson: the unit harness and the route disagreed about a data shape, and only the route was right. Integration tests that exercise the real serialisation boundary are what caught it.

### Finding #2 — the sparse index would never have reached a live database 🔴 **FIXED**

MongoDB does **not** alter an existing index when its options change. `create_index` raises `IndexOptionsConflict` (code 85) and leaves the old definition in place. `_ensure_hrms_collections` caught that, printed a warning, and moved on — so the provisioner would report success while the database kept Phase 2's **non-sparse** `uniq_user`.

Under a non-sparse unique index Mongo treats a missing field as null. So on any already-deployed company:

- the **first** onboarding-created employee → fine;
- the **second** → duplicate-key error, employee creation fails.

The provisioner now reconciles: on an options conflict *only*, it drops the index by name and recreates it from the spec, logging the rebuild. Anything else — a genuine duplicate in the data, say — is still only reported, because dropping an index because of a duplicate would destroy the constraint that found the problem. Nothing here can block startup.

Two tests cover it: a fake collection that raises code 85 (asserts drop → recreate → `sparse=True`), and one that raises 11000 (asserts **no** drop).

⚠️ **This touched `backend/app/db/mongodb.py`, a shared file.** The change is confined to `_ensure_hrms_collections` — the HRMS-only function added in Phase 1 — and no other module's provisioner or code path is altered. I made it because Phase 9 is unshippable without it. Flagging it explicitly per your standing rule on shared utilities; happy to revert and hand you a manual migration script instead.

### Finding #3 — a wrong-but-true error message ⚠️ **FIXED**

Starting an onboarding twice reported *"the candidate has not accepted an offer"*. True of the stage — the first start had already moved them to `Pre-Onboarding` — but not the reason, and actively confusing to an operator looking at an accepted offer on their screen. The duplicate check now runs first and says *"This candidate is already being onboarded."*

### Finding #4 — a public guard that crashed on unexpected input ⚠️ **FIXED**

`validate_access_code` / `validate_posting_code` did `(code or "").strip()`. A non-string raised `AttributeError` → 500, instead of the opaque 404 the public contract promises. FastAPI coerces path parameters to `str`, so this was not reachable over HTTP — but these are the last line of defence on an internet-facing surface, and a guard that crashes on unexpected input is not a guard. Both now type-check first.

### Finding #5 — Phase 2's account picker would have crashed ⚠️ **FIXED**

`list_linkable_users` did `{p["user_id"] for p in profiles}`. The moment an onboarding-created profile exists (no `user_id` key), the "Add employee" picker raised `KeyError` for **every** caller. Changed to `.get(...)` with `None` filtered out, and covered by a test.

---

## 4. Files

### New — HRMS-owned (4)

| File | Purpose |
|---|---|
| `backend/app/services/hrms_onboarding_service.py` | Onboarding + the employee handover |
| `backend/app/services/hrms/tests/test_phase9_onboarding.py` | Unit harness (**170** checks) |
| `backend/app/services/hrms/tests/test_phase9_integration.py` | HTTP + public-security harness (**104** checks) |
| `frontend/src/features/hrms/recruitment/OnboardingBoard.jsx` | Board, start modal, detail drawer |
| `frontend/src/pages/hrms/public/OnboardPage.jsx` | The public pre-onboarding form |

### Modified — HRMS-owned

`models/hrms.py` (Phase 9 block, 3 capabilities, 5 indexes, `uniq_user` → sparse) · `routes/hrms.py` (+11 routes) · `routes/hrms_public.py` (+2) · `utils/hrms_public_guard.py` (2 rate scopes, Findings #1 and #4) · `services/hrms_employee_service.py` (`create_from_onboarding`, `link_user`, unlinked composition, Finding #5) · `features/hrms/access.js` · `services/hrmsApi.js` · `services/hrmsPublicApi.js` · `people/EmployeeDirectory.jsx`

### Modified — shared (1 new)

Now **9 files, 235 insertions / 2 deletions**. Phase 9 touched `App.jsx` (+2), `Sidebar.jsx` (+2) — and `db/mongodb.py` (+22, Finding #2), which is the first shared-file change since Phase 1 and is explained above.

### Database

`hrms_onboarding` — 5 indexes: `uniq_onb_no`, `uniq_access_code`, `uniq_candidate`, `by_company_status`, `uniq_employee_id`.
`hrms_employee_profiles.uniq_user` — now `unique + sparse`.
**14 HRMS collections**, 49 index declarations, names unique.

---

## 5. APIs (13 new)

| Method | Route | Gate |
|---|---|---|
| GET | `/hrms/onboarding` | `onboarding.read` (access code omitted) |
| GET | `/hrms/onboarding/onboardable` | `onboarding.write` |
| GET | `/hrms/onboarding/{no}` | `onboarding.read` |
| POST | `/hrms/onboarding` | `onboarding.write` |
| PATCH | `/hrms/onboarding/{no}` | `onboarding.write` |
| POST | `/hrms/onboarding/{no}/bg` | `onboarding.write` |
| POST | `/hrms/onboarding/{no}/verify` | `onboarding.write` |
| POST | `/hrms/onboarding/{no}/documents` | `onboarding.write` |
| POST | `/hrms/onboarding/{no}/checklist` | `onboarding.write` |
| POST | `/hrms/onboarding/{no}/generate-id` | **`onboarding.generate_id`** |
| POST | `/hrms/employees/link/{code}` | `employee.write` |
| GET | `/hrms/public/onboard/{code}` | **none — public** |
| POST | `/hrms/public/onboard/{code}` | **none — public** |

Two new rate scopes: `onboard-view` (40/min — the form is long and gets reloaded) and `onboard-submit` (10/hour — a once-only act).

`generate_id` is a **separate capability from write** on purpose: it should be possible to let somebody run an onboarding without letting them create staff records. Proved by a test that strips only that capability and asserts the checklist still works while generate-id returns 403.

---

## 6. Test results

| Suite | Checks | Result |
|---|---|---|
| `test_capability_parity` | 6 | ✅ |
| Phases 1–8 | 1332 | ✅ |
| `test_phase9_onboarding` | **170** | ✅ |
| `test_phase9_integration` | **104** | ✅ |
| **Total** | **1612** | ✅ **1612/1612 across 19 suites** |

**Phase 9 highlights:** the Offer-Accepted gate, cross-checked against the lifecycle graph · access code absent from list payloads, present on detail · 10 leak assertions on the public form · **11 server-side validation refusals with nothing written** · PAN/IFSC upper-cased, Aadhaar spaces stripped · all three system-owned checklist items refuse a hand-tick · `bg_cleared` un-ticks when a clearance is withdrawn · every blocker on Employee ID generation, each explained in prose · **the handover asserts `user_id` is ABSENT not null, and that `learners`/`staff` are unchanged** · the new hire appears in the directory immediately · linking, double-linking, cross-tenant linking · auto-completion drives the candidate to `Employee Created` · 6 injection payloads blocked before the service, none reaching it · rate limiting on both new scopes, and a malformed code rejected *before* the limiter · **87-route auth sweep still clean**.

---

## 7. Smoke (S1) & Regression (S2)

| Check | Result |
|---|---|
| All 19 suites | ✅ 1612/1612 |
| `npm run build` | ✅ 2.62s |
| Lint — HRMS files | ✅ **0 errors** (8 warnings, pre-existing idiom) |
| Lint — whole `src` | ✅ 2 errors, both pre-existing (OOS-004) |
| Backend imports, routers mount | ✅ 69 authed + 8 public routes |
| Shared-file diff | ✅ 9 files, 235/2 — one new (Finding #2, explained) |
| All four public surfaces still anonymous | ✅ apply · assess · offer · onboard |
| Task Management / Calendar / TPMS / CRM routes still 401 | ✅ |
| Declared provisioning: 14 collections, 49 indexes, names unique | ✅ |
| **Live DB check** | ⏸ **deferred — Atlas unreachable from this network** |

The live check is the one gap. Atlas did not resolve during this run (the same transient condition as Phase 7, which was closed in Phase 8's smoke). Provisioning was verified statically instead: the spec, the provisioner's use of it, and its invocation on startup. **When you next start the backend against Atlas, watch for `[INFO] HRMS index uniq_user on hrms_employee_profiles rebuilt to match the spec`** — that line is Finding #2's fix landing. Section K of the test script covers this.

---

## 8. Residual risk

| Risk | Severity | Note |
|---|---|---|
| Live DB provisioning unverified this run | **Medium** | Deferred above; one log line confirms it |
| No emailed pre-onboarding link | Medium | HR copies the link by hand. Same shared-notification-attachment limitation flagged in Phase 7 §4 — **still awaiting your approval** |
| Documents are stored, not previewed | Low | The board lists names and source; a viewer is a small addition if wanted |
| No reminder if a new hire never submits | Medium | Needs a scheduler — carried with the Phase 6/7/8 reminder gap for Phase 15 |
| An unlinked employee has no profile page | Low | Deliberate: the profile route is keyed on `user_id`. The directory row opens the linking dialog instead |
| Frontend has no automated tests | Medium | Your approved decision |

---

## 9. Completion checklist

- [x] All 13 development steps passed
- [x] 1612/1612 automated checks across 19 suites
- [x] **Two production defects found and fixed** (public uploads 415-ing; a sparse index that would never deploy)
- [x] Three further defects fixed (misleading error, crashing guard, picker `KeyError`)
- [x] Identity collections provably never written
- [x] `generate_id` proven separable from `onboarding.write`
- [x] `PHASE_9_REPORT.md` + `PHASE_9_TEST_SCRIPT.md`
- [ ] **Live DB smoke** — deferred, Atlas unreachable
- [ ] Git tag `hrms-phase-9` — *awaiting go-ahead; nothing committed or pushed*

---

## 10. Ready for Phase 10

Phase 10 (Leave Management) inherits a real employee master:

- Employees exist with `EMP-YYYY-NNN` codes, joining dates, departments and designations
- Some of them have **no login** — leave accrual and payroll must handle `pending_user_link`, and the `_compose` path already does
- `hrms_holidays` (your Phase 0 decision) is still to be created
- The recruitment pipeline is complete end to end: requisition → JD → posting → application → screening → assessment → interview → offer → onboarding → **employee**
