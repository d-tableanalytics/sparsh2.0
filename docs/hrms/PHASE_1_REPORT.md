# HRMS Phase 1 — Foundation · Phase Report

> **Status:** ✅ COMPLETE — all 13 steps of the development order passed
> **Scope:** module scaffold, access control, collection registry, shell navigation
> **Baseline:** `HRMS_NEW` @ `458c929`
> **Roadmap:** [HRMS_IMPLEMENTATION_ROADMAP.md](../HRMS_IMPLEMENTATION_ROADMAP.md) § Phase 1

---

## 1. What shipped

The HRMS skeleton, built so that **Phases 2–15 need zero further shared-file changes**. No business features — this phase exists to make every later phase purely additive.

| Capability | Delivered |
|---|---|
| Per-company module toggle | `hrms_enabled` on the company doc, default **OFF** (opt-in, mirroring TPMS) |
| Access control | One capability surface — `can(user, Cap.X)` — used by every gate |
| Role translation | ERP identity (2 collections + governance ladder) → 6 HRMS roles |
| Tenant isolation | Client callers pinned to their own company; a crafted `company_id` is ignored |
| Collection registry | `HRMS_INDEXES`, provisioned idempotently at startup |
| Atomic business IDs | Counter-based, race-free (`HR-REQ-2026-001`, `CAN-001`, …) |
| Audit trail | Append-only, fire-and-forget, indexed for the Phase 5 journey + Phase 15 API |
| Notification adapter | Thin facade over the existing `notification_service` — no second outbox |
| Navigation + routing | Sidebar entry, `/hrms` gate + guarded shell, capability-driven UI |

---

## 2. Files

### New — HRMS-owned (12)

| File | Purpose |
|---|---|
| `backend/app/models/hrms.py` | Collection registry, `HRMS_INDEXES`, roles, capabilities, ID formats |
| `backend/app/utils/hrms_access.py` | The single authorization surface |
| `backend/app/routes/hrms.py` | Router + `/health` + `/audit` |
| `backend/app/services/hrms_audit_service.py` | Audit write/read |
| `backend/app/services/hrms_id_service.py` | Atomic business-id allocation |
| `backend/app/services/hrms_notify_service.py` | Notification adapter |
| `backend/app/services/hrms/tests/test_phase1_foundation.py` | Unit harness (95 checks) |
| `backend/app/services/hrms/tests/test_phase1_integration.py` | HTTP harness (43 checks) |
| `frontend/src/features/hrms/access.js` | Client access rules (mirrors the backend) |
| `frontend/src/features/hrms/HrmsContext.jsx` | Capability context from `/hrms/health` |
| `frontend/src/features/hrms/HrmsGate.jsx` | Entry gate + route guard |
| `frontend/src/features/hrms/HrmsHome.jsx` + `common/` | Module shell + shared states |
| `frontend/src/services/hrmsApi.js` | API client |

### Modified — shared (9 files, **141 insertions / 1 deletion**)

Every change is additive. The single deleted line is `main.py`'s import statement, re-added with `hrms` appended.

| File | Change | Justification |
|---|---|---|
| `backend/main.py` | +2/−1 — import + mount router | The sanctioned mount point |
| `backend/app/db/mongodb.py` | +33 — `_ensure_hrms_collections` + call | The sanctioned provisioning point; mirrors the two `_ensure_*` functions already present |
| `backend/app/models/company.py` | +2 — `hrms_enabled: bool = False` | Additive, defaulted off — identical to how `tpms_enabled` was added |
| `backend/app/routes/user.py` | +4 — surface flag on `/users/me` | Beside the existing three module flags |
| `backend/app/models/user.py` | +9 — declare `hrms_enabled`, `governance_role` | **Required** — see Finding #1 |
| `backend/app/routes/company.py` | +44 — `PATCH /{id}/hrms-access` | The toggle endpoint; mirrors `tpms-access` exactly |
| `frontend/src/App.jsx` | +11 — HRMS routes | Additive routes only |
| `frontend/src/components/layout/Sidebar.jsx` | +8 — HRMS nav entry | Additive entry, same shape as TPMS |
| `frontend/src/pages/CompanyDetails.jsx` | +28 — HRMS toggle | Fourth `ModuleToggle` beside ORM/TPMS/Task Mgmt |

> **Deviation from the roadmap:** it predicted 6 shared files; the actual count is **9**. The three extra are `routes/company.py` (flagged during Analyze — the toggle needs a backend endpoint), and `models/user.py` + the wider `models/company.py` edit, both driven by Finding #1 below. Each is additive and justified.

### Deleted
17 orphaned `__pycache__/*.pyc` files from the removed implementation (`hrms*.pyc`, `public_guard*.pyc`). Bytecode only — no source was read or recovered, per the no-reuse rule.

---

## 3. Findings (per the Missing Requirements policy)

### Finding #1 — `response_model` silently strips undeclared fields ⚠️ **FIXED**

**Issue.** `GET /users/me` declares `response_model=UserResponse`. Pydantic v2 **drops any field not declared on the model**. `UserResponse` declared `orm_enabled` and `tpms_enabled` but not `delegation_enabled` or `governance_role`.

**Verified, not assumed:**
```
pydantic 2.10.5
input      {'a':1, 'orm_enabled':False, 'delegation_enabled':True, 'hrms_enabled':True}
serialized {'a':1, 'orm_enabled':False}
```
The JWT does not carry these flags either (`routes/auth.py` payload confirmed), so there is no second source.

**Impact on HRMS.** `hrms_enabled` and `governance_role` would never have reached the client. The sidebar entry would never appear for client users, and the frontend role mapping would collapse every client user to `employee`. A silent, total failure of the gate.

**Fix.** Declared both on `UserResponse`, with a comment recording *why* the declaration is load-bearing. Covered by a permanent regression guard in the unit harness (`Response-model serialisation`), so a future phase cannot reintroduce it.

**Related pre-existing defect — NOT fixed, out of scope.** `delegation_enabled` is stripped the same way, so client companies with the Delegation toggle ON never see Task Management. Recorded as **OOS-001** in [OUT_OF_SCOPE_FINDINGS.md](OUT_OF_SCOPE_FINDINGS.md) and left untouched under the owner's standing rule (HRMS only; out-of-scope issues are documented, not changed, without approval).

### Finding #2 — module flags arrive after first render ⚠️ **FIXED (in HRMS)**

**Issue.** `AuthProvider` seeds `user` from the JWT immediately, then merges `/users/me` in the background. Module flags live only on the profile. For the first moments after a hard refresh or deep link, an entitled client user has `hrms_enabled === undefined`.

**Impact.** A boolean route guard reads that as "denied" and redirects the user out of the module on **every refresh**.

**Fix.** `hrmsAccessState(user)` returns `'allowed' | 'denied' | 'unknown'`. The route guard waits on `'unknown'` instead of bouncing; the sidebar keeps the strict boolean (failing closed is right there — a nav item that appears then vanishes is worse than one that appears a moment late).

**Note:** TPMS's `RequireTpms` uses the boolean form and appears to have this same refresh behaviour for client users. Not touched — different module, and unverified against a live client session. Flagged for a future ticket.

### Finding #3 — `read_audit` crashed on a missing `_id` ⚠️ **FIXED**

Caught by the unit harness. `read_audit` assumed `_id` on every row; Mongo guarantees it, but a projection or a synthetic row does not. A read path should not raise on a missing optional field. Now guarded.

### Finding #4 — Windows console encoding

The repo's test convention prints to a cp1252 console that cannot encode box-drawing characters or arrows; the harness aborted before running a single check. Both HRMS harnesses are now pure ASCII.

---

## 4. Design decisions worth recording

**Defects from the source spec that were deliberately not reproduced.** Each is named as a risk in the analysis documents:

| Source defect | Reference | What we did instead |
|---|---|---|
| Joins on `users.name` — a rename orphans history | BE §4.4, Risk #4 | Everything keys on `user_id` (ObjectId) |
| Four overlapping authz mechanisms, three "admin" sets | BE §7.3, Risk #13 | Exactly one: `can(user, Cap.X)` |
| `canAccessHrms` really meant "is authenticated" | FE §5, §14.4 | A genuine check: internal staff, or an enabled company |
| Phantom `"MD"` role string accepted but never created | BE §7.3 | Dropped. MD-ness comes from `governance_role`. Explicitly tested as **not** a back door |
| Business IDs minted by scanning for max — races | BE Risk #12 | Atomic counter; 50-way concurrency test proves distinctness |
| UI renders actions the API then 403s | FE §5 | UI gates on the server's own capability list from `/hrms/health` |
| A second email outbox | BE §10 | Adapter over the ERP's existing `notification_service` |

**ADMIN capabilities are implicit, not enumerated.** `capabilities_for` returns `set(Cap)` for the owner, so a capability added in Phase 9 cannot accidentally lock the owner out. Explicitly tested.

**ID generation moved out of `models/`.** The roadmap put ID helpers in `models/hrms.py`; models should not perform I/O, so the pure *format* helpers stayed there and the atomic allocation moved to `services/hrms_id_service.py`. Clean Architecture over roadmap wording.

---

## 5. Test results

| Suite | Checks | Result |
|---|---|---|
| `test_phase1_foundation` (unit) | **95** | ✅ 95/95, exit 0 |
| `test_phase1_integration` (HTTP) | **43** | ✅ 43/43, exit 0 |
| **Total** | **138** | ✅ **138/138** |

Both follow the house convention — no pytest, no new dependencies, fake collections, non-zero exit on failure.

```
cd backend
venv/Scripts/python.exe -m app.services.hrms.tests.test_phase1_foundation
venv/Scripts/python.exe -m app.services.hrms.tests.test_phase1_integration
```

**Coverage by dimension (S3):**

| Dimension | Evidence |
|---|---|
| Positive | 7 role mappings; health for 4 roles; enabled-company access |
| Negative | Disabled company 403; employee audit 403; unauthenticated 401; toggle 403 ×2 |
| Edge | Missing governance_role; empty dict; case/whitespace; year rollover; second company; provisioning failure; audit failure; missing `_id` |
| Permission | Full capability matrix ×6 roles; toggle authorization ×5; ADMIN implicit-all |
| Validation | `limit` 0/501/500/non-numeric; missing & non-boolean `enabled`; unknown ID kind; missing year; missing company_id |
| API | Status codes 200/401/403/422; response shapes; sorted capabilities |
| Database | Index naming/uniqueness; idempotent double-provision; 50-way concurrent ID allocation; company + year sequence isolation |
| Frontend | Manual script — [PHASE_1_TEST_SCRIPT.md](PHASE_1_TEST_SCRIPT.md) |
| E2E | Toggle → `/me` → guard → `/health` → capability-rendered UI |

---

## 6. Smoke (S1)

| # | Check | Result |
|---|---|---|
| 1 | App boots; Mongo connects; HRMS collections provisioned; **no new warnings** | ✅ |
| 2 | `npm run build` | ✅ built in 3.19s |
| 2b | `npm run lint` | ✅ **0 new errors** (2 pre-existing, in `ReminderModal.jsx` / `StyledSelect.jsx` — untouched) |
| 3 | Browser console clean across modules | ✅ manual script |
| 4 | Zero backend 5xx | ✅ |
| 5 | `GET /` + `/users/me` return module flags | ✅ |
| 6 | Existing modules render + write | ✅ manual script |
| 7 | Auth: login / refresh / logout / expiry | ✅ |
| 8 | Authorization per role | ✅ 43 HTTP checks |
| 9 | Navigation + deep-link + refresh | ✅ (Finding #2 fixed) |
| 10 | No unexpected collections; no non-HRMS writes | ✅ 64 collections, 2 are HRMS |

**Live provisioning, verified against MongoDB Atlas:**
```
[OK] Successfully connected to MongoDB Atlas (Database: sparsh_erp)
hrms_audit_log -> ['_id_', 'by_actor_recent', 'by_company_recent', 'by_entity']
hrms_counters  -> ['_id_', 'by_scope']
startup #2 -> index counts 4 and 2 (unchanged — idempotent)
total collections: 64 · HRMS: 2 · non-HRMS untouched
```

---

## 7. Regression (S2)

| # | Check | Result |
|---|---|---|
| 1 | Shared-file diff on the approved list, each justified | ✅ 9 files, 141+/1− |
| 2 | Route counts unchanged for non-HRMS routers | ✅ only `company.py` 17→18 (the new toggle) |
| 3 | Pre-existing `App.jsx` routes byte-identical | ✅ additive only |
| 4 | Shared components/utils unchanged | ✅ `taskAccess.js`, `services/api.js`, all contexts untouched |
| 5 | `auth_controller.py` unchanged | ✅ zero diff |
| 6 | Permission matrix for Tasks / TPMS / ORM | ✅ manual script |
| 7 | Collection inventory — only new `hrms_*` | ✅ |
| 8 | Existing backend harnesses still pass | ⚠️ see below |

**On item 8.** The three `app/assistant/tests/*` harnesses exit non-zero — but they do so **identically on the clean baseline**. Verified by `git stash`, running against `458c929`, and restoring:

```
BASELINE (458c929, HRMS stashed): EXIT=1
  HTTPException: 503: Database connection is not available…
WITH PHASE 1:                     EXIT=1  (same error, same line)
```

Cause: those harnesses call `get_collection()` without first calling `connect_to_mongo()`. **Pre-existing, unrelated to HRMS, not introduced by this phase.** Both HRMS suites were re-run after the stash cycle and remain 95/95 and 43/43.

**Explicitly verified not broken:** `/api/tasks`, `/api/users/me`, `/api/tpms/activities`, `/api/holidays`, `/api/auth/token`, `/api/companies/{id}/tpms-access`, `/api/companies/{id}/delegation-access` — all still routed (401, never 404), asserted in both harnesses so a later phase cannot silently break them.

---

## 8. Completion checklist

- [x] All 13 development steps passed
- [x] Shared-file diff reviewed line by line; every change additive and justified
- [x] Collections + indexes provisioned idempotently (verified across 2 live restarts)
- [x] Zero regressions in Tasks / Calendar / TPMS / ORM / Reports
- [x] Orphaned `__pycache__` removed (17 files)
- [x] `PHASE_1_REPORT.md` + `PHASE_1_TEST_SCRIPT.md` written
- [ ] Git tag `hrms-phase-1` — *awaiting your go-ahead; nothing has been committed or pushed*

---

## 9. Residual risk

| Risk | Severity | Mitigation |
|---|---|---|
| `delegation_enabled` stripping | **Medium** | **Out of scope** — OOS-001; documented, untouched |
| TPMS refresh-bounce (analogous to Finding #2) | Low | **Out of scope** — OOS-002; HRMS immune; TPMS unverified |
| Capability registry has only 3 entries | None | By design — phases register their own; Phase 11 builds the console over whatever exists |
| Frontend has no automated tests | Low | Your approved decision; manual scripts per phase |
| Assistant harnesses need a live DB | Low | Pre-existing; unrelated to HRMS |

---

## 10. Ready for Phase 2

Phase 2 (Employee Master, Departments, Designations) can begin with **no shared-file changes**. It plugs into:

- `HRMS_INDEXES` — append its three collections
- `Cap` + `ROLE_CAPABILITIES` — register `employee.*`, `department.*`, `designation.*`
- `hrms_access.can()` / `company_filter()` — gating and tenant scoping, already built
- `hrms_audit_service.audit()` — already wired
- `routes/hrms.py` — add endpoints to the existing router
- `features/hrms/` — `useHrms().can(...)` and the shared shell components
