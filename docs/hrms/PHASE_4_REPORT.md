# HRMS Phase 4 — Job Postings + Public Application Intake · Phase Report

> **Status:** ✅ COMPLETE — all 13 steps of the development order passed
> **Scope:** publishing approved JDs across channels, and the module's first public surface
> **Roadmap:** [HRMS_IMPLEMENTATION_ROADMAP.md](../HRMS_IMPLEMENTATION_ROADMAP.md) § Phase 4
> **Scope rule honoured:** HRMS only. Findings outside it are in [OUT_OF_SCOPE_FINDINGS.md](OUT_OF_SCOPE_FINDINGS.md), documented and untouched.

---

## 1. What shipped

The roadmap called this *"the project's main security work"*. It opens the only endpoints in the ERP reachable with no token, by anyone, that accept files and personal data.

| Capability | Delivered |
|---|---|
| Publish an approved JD | One posting **row per platform**, each with its own code and destination |
| Per-platform destination | `auto` (built-in form) vs `external` (poster's own URL), configured independently |
| Lifecycle | Live / Pause / Close, plus read-time expiry |
| Application count | **Computed from candidates on every read** — never stored, so it cannot drift |
| Assessment flag | Copied onto each applicant at apply time, gating Phases 6–7 |
| **Public job ad** | `GET /api/hrms/public/apply/{code}` — no auth |
| **Public application** | `POST /api/hrms/public/apply/{code}` — no auth, with file upload |
| Public guard | Rate limiting, code validation, upload validation, PII-safe errors |

---

## 2. The public surface — every defence, and why

`routes/hrms_public.py` opens with a six-rule contract. Each rule is enforced by an assertion in `test_phase4_public_security.py`, so a future change that breaks one fails a test rather than shipping.

| # | Rule | How it is enforced |
|---|---|---|
| 1 | **No authentication, no company gate** | No `Depends(get_current_user)` on the router. Verified anonymously, including with a garbage bearer token present |
| 2 | **The code is validated before any query** | `validate_posting_code` pattern-matches `^[A-Z]{2}-[A-Z0-9]{6}$` first. **13 injection/traversal payloads** tested — all refused, and none reached the service |
| 3 | **Rate limited before any work** | Two independent axes: per-IP and **per posting code**. The second exists because the first is defeatable with a proxy pool |
| 4 | **Errors are vague and identical** | Unknown and malformed codes return byte-identical 404s, so the endpoint is not an existence oracle. Mirrors `/auth/forgot-password` |
| 5 | **Responses expose only what a candidate needs** | 8 internal fields asserted absent from the public ad; the submit response is limited to `{ok, duplicate, reference, message}` |
| 6 | **Not gated by `hrms_enabled`** | Deliberate — gating it would let an applicant infer a client's subscription state from a shared link |

**NoSQL injection is structurally impossible here, not merely unlikely.** The code must match a strict pattern before any database call happens, so a crafted `{"$ne": null}` can never arrive at Mongo as an operator document. Tested explicitly.

### Why a new rate limiter rather than the existing one

`app/assistant/ratelimit.py` exists and is clean, but its own docstring says a shared store is needed for multi-worker deployments. It is **in-process**: state is lost on restart and not shared across workers or containers, so an attacker spreading requests across workers multiplies their effective limit. Acceptable for an authenticated assistant; not for an internet-facing form. Reusing it would also couple HRMS's public-surface security to another module's config.

**Fixed window, deliberately.** A sliding window must store every hit timestamp — so a flood makes the limiter's own storage grow, turning the defence into an amplifier. A fixed-window counter is O(1) storage per key per window. The cost is boundary burst (up to 2× across a window edge), which is the right trade for abuse prevention.

**Fails open.** If the rate-limit store is unavailable the module keeps serving. A hiring form that refuses every applicant because a counter collection is down is worse than one that is briefly unthrottled — and the per-code ceiling and upload limits remain in force. Tested.

### Upload handling

- Declared size checked **before** decoding, so a 1 GB payload is rejected without being materialised; decoded size re-checked because the declared length is attacker-controlled.
- MIME allow-list (PDF / Word / images); 15 MB; ≤10 certificates.
- Filenames reduced to inert: path separators, traversal sequences and control characters stripped. `../../../etc/passwd` → `passwd`.
- **Uploads happen only after validation passes**, so a rejected form never costs storage. Tested.
- The **S3 key** is persisted, not a signed URL — signed URLs expire in an hour and would leave dead links in every candidate record.

---

## 3. Findings

### Finding #1 — the capability parity guard caught a real drift ✅ **WORKING AS INTENDED**

I added `posting.read` / `posting.write` to the backend `Cap` enum and forgot the frontend `CAP` map. `test_capability_parity` failed at **4/6** and named both missing entries.

This is precisely the Phase 2 defect — where the same omission silently hid every write control from HR and shipped. This time it was caught automatically, before the frontend was even exercised. The guard added in Phase 3 has now paid for itself once.

### Finding #2 — the security sweep found two unauthenticated endpoints ⚠️ **OUT OF SCOPE, DOCUMENTED**

The new whole-app sweep enumerates every authenticated `GET` route and asserts none answers without a token. It swept 87 and found two: `/api/assistant/health` and `/api/assistant/ready`.

Both are **pre-existing and deliberate** — the Assistant's own router documents them as liveness/readiness probes, which must be anonymous to be useful to Docker. Not caused by Phase 4, and not mine to change.

`/ready` does disclose a little more than it needs (DB reachability, whether an OpenAI key is set, feature flags). Recorded as **OOS-005** with a recommendation; **not changed**.

The sweep allow-lists them by **exact path, never by prefix**, so a future `/api/assistant/*` route is still swept.

### Finding #3 — my own sweep was silently testing nothing ⚠️ **FIXED**

First run reported *"swept 0 authenticated GET routes"*. I had put `"/"` in the intended-public **prefix** list — and `"/"` is a prefix of every path, so every route was skipped. The test passed while asserting nothing.

Worth stating plainly: a security test that vacuously passes is worse than no test, because it manufactures confidence. The assertion `swept 85 routes` now guards against exactly that recurrence.

### Finding #4 — two test-side errors, not code errors

- `FakeCollection` had no `insert_many`, which the multi-platform publish needs. Added to the shared fake.
- I asserted 4 surviving candidates where the flow creates 3 (duplicates and validation failures create none). The test now derives the number rather than hardcoding it.

---

## 4. Files

### New — HRMS-owned (8)

| File | Purpose |
|---|---|
| `backend/app/utils/hrms_public_guard.py` | **Rate limiting, code validation, upload validation, sanitisers** |
| `backend/app/routes/hrms_public.py` | **The unauthenticated router** (2 endpoints, 6-rule contract) |
| `backend/app/services/hrms_posting_service.py` | Postings + public application intake |
| `backend/app/services/hrms/tests/test_phase4_posting.py` | Unit harness (118 checks) |
| `backend/app/services/hrms/tests/test_phase4_public_security.py` | **Security harness (51 checks)** |
| `frontend/src/services/hrmsPublicApi.js` | **Separate anonymous axios client** |
| `frontend/src/features/hrms/recruitment/PostingList.jsx` | Posting cards, KPIs, lifecycle |
| `frontend/src/features/hrms/recruitment/CreatePostingModal.jsx` | Per-platform link config + live code preview |
| `frontend/src/pages/hrms/public/ApplyPage.jsx` | **Public application page** |

**Why a separate public API client.** `services/api.js` attaches the bearer token from `localStorage`. If an HR user happened to be signed in on the same browser, the shared instance would silently attach *their* credentials to a public request — an accidental privilege leak. A bare axios instance keeps the public surface genuinely anonymous.

### Modified — shared (0 new)

Still the same **9 files**, now **187 insertions / 2 deletions**. Both deletions are import lines re-added with one item appended (`hrms_public` in `main.py`, `Megaphone` in `Sidebar.jsx`) — effectively 100% additive.

The public React route is registered **outside `PrivateRoute`** in `App.jsx`; wrapping it would redirect every applicant to `/login`.

---

## 5. Database

| Collection | Indexes |
|---|---|
| `hrms_job_postings` | `uniq_posting_code` (unique) · `by_jd` · `by_company_live` · `by_request` |
| `hrms_candidates` | `uniq_uk` (unique) · `by_company_status` · `by_posting` · `by_request` · **`by_company_email`** · **`by_company_phone`** |
| `hrms_public_rate_limit` | **TTL on `expires_at`** |

The two candidate contact indexes exist because duplicate detection runs on **every** public application — an unindexed scan there is a denial-of-service vector, not just slow.

Live-verified: **10 HRMS collections**, TTL present, identity collections unpolluted.

---

## 6. Test results

| Suite | Checks | Result |
|---|---|---|
| `test_capability_parity` | 6 | ✅ |
| `test_phase1_foundation` | 96 | ✅ |
| `test_phase1_integration` | 46 | ✅ |
| `test_phase2_employee` | 123 | ✅ |
| `test_phase2_integration` | 55 | ✅ |
| `test_phase3_requisition` | 108 | ✅ |
| `test_phase3_integration` | 59 | ✅ |
| `test_phase4_posting` | **118** | ✅ |
| `test_phase4_public_security` | **51** | ✅ |
| **Total** | **662** | ✅ **662/662** |

**Security coverage specifically:**
- 13 injection / traversal / malformed codes — all refused, none reached the service
- Anonymous access proven on both public endpoints, including with a garbage bearer token
- **85-route whole-app sweep** — no authenticated endpoint answers without a token
- Identical error bodies for unknown vs malformed codes (no existence oracle)
- 8 internal fields asserted absent from the public ad
- Forged `application_status` / `company_id` / `uk` / `requires_assessment` fields dropped by the schema
- Rate limiting on both axes, keyed on the first forwarded hop, failing open when its store is down
- Malformed codes rejected *before* the limiter is consulted
- Upload: MIME, oversize, corrupt base64, and no-storage-on-invalid-form

---

## 7. Smoke (S1) & Regression (S2)

| Check | Result |
|---|---|
| App boots; 10 HRMS collections; TTL index present; no new warnings | ✅ |
| `npm run build` | ✅ 3.42s |
| Lint — HRMS files | ✅ **0 errors** (6 warnings, pre-existing `icon: Icon` idiom) |
| Lint — whole `src` | ✅ 2 errors, both pre-existing (OOS-004) |
| Identity collections unpolluted | ✅ 0 |
| Shared-file diff | ✅ still 9 files; **no new shared dependencies** |
| Public routes do not break `PrivateRoute` | ✅ every other route still 401 |
| `/api/tasks`, `/api/users/me`, `/api/tpms/activities`, `/api/holidays` | ✅ still 401, not 404 |
| Phases 1–3 suites | ✅ green |

---

## 8. Residual risk

| Risk | Severity | Note |
|---|---|---|
| Rate limiting is per-IP and per-code, not per-identity | Medium | Inherent to an anonymous form. A rotating proxy pool can still spread load; the per-code ceiling bounds the damage. A CAPTCHA is the next step if abuse appears — deliberately not added, as it costs every honest applicant |
| Boundary burst (up to 2× limit across a window edge) | Low | Accepted trade for O(1) limiter storage — see §2 |
| Limiter fails open | Low | Deliberate: availability of a hiring form beats perfect throttling |
| No virus scanning on uploads | Medium | Files are stored in S3 and never executed, but they are downloaded by HR. Out of scope for Phase 4; worth a scanning step before Phase 15 |
| `external` postings can never report applications | None — by design | Surfaced in the UI in red on both the create modal and the card |
| Frontend has no automated tests | Medium | Your approved decision; the parity guard covers the highest-risk slice |

---

## 9. Completion checklist

- [x] All 13 development steps passed
- [x] 662/662 automated checks
- [x] **Security review of the public surface: 51 assertions, 85-route sweep**
- [x] Rate limiting verified on both axes, including fail-open
- [x] Codes validated before any query (injection structurally impossible)
- [x] No auth regression on any existing route
- [x] Zero new shared-file dependencies
- [x] `PHASE_4_REPORT.md` + `PHASE_4_TEST_SCRIPT.md` + OOS-005
- [ ] Git tag `hrms-phase-4` — *awaiting go-ahead; nothing committed or pushed*

---

## 10. Ready for Phase 5

Phase 5 (Candidates + Screening) inherits a populated pipeline:

- `hrms_candidates` is created and filled by Phase 4; Phase 5 adds the stage machine and screening
- `AppStatus` already declares all 20 lifecycle values in one place
- `requires_assessment` is on each candidate, ready to route shortlisting into Phase 6
- The audit trail already records every application, which Phase 5's candidate journey reads
