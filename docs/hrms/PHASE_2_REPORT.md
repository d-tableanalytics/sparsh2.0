# HRMS Phase 2 — Employee Master, Departments & Designations · Phase Report

> **Status:** ✅ COMPLETE — all 13 steps of the development order passed
> **Scope:** employee master, department master, designation master, reporting hierarchy
> **Roadmap:** [HRMS_IMPLEMENTATION_ROADMAP.md](../HRMS_IMPLEMENTATION_ROADMAP.md) § Phase 2
> **Scope rule honoured:** HRMS only. Out-of-scope findings documented in [OUT_OF_SCOPE_FINDINGS.md](OUT_OF_SCOPE_FINDINGS.md), never changed.

---

## 1. What shipped

Closes the gap both analysis documents rank first: *"Employee Management — Not found in current HRMS"* (FE §2, BE §2). Everything from here on depends on it — onboarding creates employees, leave and payroll compute over them, reporting aggregates them.

| Capability | Delivered |
|---|---|
| Employee directory | Search, department/status filters, pagination, row-scoped by role |
| Employee profile | 4 tabs — Job · Personal · Statutory & Bank · Reporting |
| Department master | CRUD, per-company, delete-protected, case-insensitive dedupe |
| Designation master | Same, sharing one service and one screen (DRY) |
| Reporting hierarchy | Manager chain upward (cycle-guarded) + direct reports |
| Salary privacy | Omitted from the payload without `employee.salary.read` |
| Directory suggestions | Read-only distinct values from user records, with counts |
| Employee codes | `EMP-YYYY-NNN`, atomic, per-company sequence |

**8 new capabilities** registered: `employee.read/write`, `employee.salary.read/write`, `department.read/write`, `designation.read/write`.

---

## 2. The central design decision

An employee is a **composition, never a copy**:

```
EmployeeView = user document (staff/learners)   ← identity, owned by the ERP
             + hrms_employee_profiles           ← HR data, owned by HRMS
             + resolved master names            ← department / designation
             + resolved reporting manager
```

**HRMS never writes to `staff` or `learners`.** Identity has exactly one owner, so a rename or email change is instantly correct everywhere with no sync step and no drift.

The source did the opposite — it kept its own `users` table and joined every HR-ops record on `users.name`, so renaming a person silently orphaned their leave history, balance ledger and permission grants (BE §4.4, Risk #4). Keying on the immutable ObjectId removes that failure mode by construction rather than mitigating it. Two tests assert the identity collections are never written, and a live query confirms **0 polluted documents** across all 188 real user records.

---

## 3. Findings

### Finding #1 — the roadmap's department seeding would have poisoned the master ⚠️ **DESIGN CHANGED**

The roadmap said: *"Seed departments from existing distinct `users.department` values on first provision (insert-only)."* I inspected the live data before implementing it:

```
learners.department (173 docs):
  'ACCOUNT', 'Accounts', 'Account & Finance', 'Accounts & Finance',
  'Admin', 'Administraion',  'ASSEMBLY', 'Assembly 1', 'Audit', 'Back Office', …
staff.department (15 docs):  'Other'   ← the field is unused on the staff side
```

**Impact if implemented as written.** Four spellings of Accounts and a typo (`Administraion`) would have become authoritative masters. Every later phase — requisitions, JDs, employee assignment, payroll grouping, reporting — would inherit that mess, and cleaning it up afterwards means re-pointing live foreign keys.

**What I built instead.** `GET /hrms/masters/suggestions` returns the distinct values **with usage counts and an `exists` flag**, read-only. HR reviews and creates the clean set with one click each. Same review-before-import philosophy already committed to for the Phase 12 holiday import. Nothing is auto-created; nothing is written to `learners`.

### Finding #2 — `GET /api/companies` is gated by another module's permission ⚠️ **RESOLVED INSIDE HRMS**

Internal staff need a company selector (every employee endpoint requires a company). The obvious source, `GET /api/companies`, requires `superadmin` **or** the Companies module's `companies.read` grant — which a staff `admin` may not hold.

**Why I did not touch it.** Widening that endpoint would modify the Companies module. Out of scope.

**What I did.** Added `GET /hrms/companies`, which returns HRMS-enabled companies for internal staff and exactly their own company for client users. HRMS owns its scoping and does not inherit another module's permission model. One extra endpoint beyond the roadmap's list, and the module stays self-contained.

### Finding #3 — two Phase 1 assertions were brittle ⚠️ **FIXED**

The Phase 2 regression run turned Phase 1 from 95/95 → 94/95 and 43/43 → 42/43. Both failures were assertions **I** wrote in Phase 1 that hardcoded a snapshot instead of the invariant:

| Assertion | Problem |
|---|---|
| `only Phase 1 collections are provisioned` — exact set `{audit_log, counters}` | Phase 2 legitimately added 3 collections |
| `admin gets every capability` — `len(caps) == 3` | Phase 2 legitimately added 8 capabilities |

Neither was a code defect. Both now assert the real invariant — *every provisioned collection is a declared `COLL_*` constant*, and *ADMIN holds `len(Cap)` capabilities* — so they hold for every future phase without editing. A test that must be edited each phase trains you to edit rather than read it.

---

## 4. Files

### New — HRMS-owned (9)

| File | Purpose |
|---|---|
| `backend/app/services/hrms_employee_service.py` | Composition, row scoping, validation, hierarchy |
| `backend/app/services/hrms_masters_service.py` | Department + designation CRUD (one service, both kinds) |
| `backend/app/services/hrms/tests/test_phase2_employee.py` | Unit harness (123 checks) |
| `backend/app/services/hrms/tests/test_phase2_integration.py` | HTTP harness (54 checks) |
| `frontend/src/features/hrms/people/EmployeeDirectory.jsx` | Directory |
| `frontend/src/features/hrms/people/EmployeeProfile.jsx` | 4-tab profile |
| `frontend/src/features/hrms/people/AddEmployeeModal.jsx` | Link a user → employee |
| `frontend/src/features/hrms/people/MasterManager.jsx` | Both masters, one screen |
| `frontend/src/features/hrms/common/HrmsScopeBar.jsx` | Company scope selector |

Extended: `models/hrms.py`, `routes/hrms.py`, `services/hrmsApi.js`, `HrmsContext.jsx`.

### Modified — shared (0 new)

**Phase 2 introduced no new shared-file dependencies.** It touched only two files already approved in Phase 1, additively:

| File | Change |
|---|---|
| `frontend/src/App.jsx` | +8 lines — four HRMS child routes |
| `frontend/src/components/layout/Sidebar.jsx` | +15 lines — HRMS submodule list |

Cumulative shared-file footprint is unchanged at **9 files, 164 insertions / 1 deletion** (the deletion is still Phase 1's `main.py` import line). This is what the roadmap promised: *"Phases 2–15 need zero further shared-file changes."*

---

## 5. Database

| Collection | Indexes |
|---|---|
| `hrms_employee_profiles` | `uniq_user` (unique) · `uniq_company_code` (unique, sparse) · `by_company_status` · `by_company_department` |
| `hrms_departments` | `uniq_company_name` (unique) |
| `hrms_designations` | `uniq_company_name` (unique) |

Live-verified against MongoDB Atlas; idempotent across two startups (index counts identical). 67 collections total, 5 are HRMS.

---

## 6. APIs (13 new)

| Method | Route | Capability |
|---|---|---|
| GET | `/hrms/companies` | any HRMS user |
| GET/POST | `/hrms/departments` | `department.read` / `.write` |
| PATCH/DELETE | `/hrms/departments/{id}` | `department.write` |
| GET/POST | `/hrms/designations` | `designation.read` / `.write` |
| PATCH/DELETE | `/hrms/designations/{id}` | `designation.write` |
| GET | `/hrms/masters/suggestions` | `department.read` |
| GET | `/hrms/employees` | `employee.read` (row-scoped) |
| POST | `/hrms/employees` | `employee.write` |
| GET/PATCH | `/hrms/employees/{user_id}` | read: self or `employee.read` |
| GET | `/hrms/employees/{user_id}/hierarchy` | `employee.read` |
| GET | `/hrms/employees/linkable` | `employee.write` |
| GET | `/hrms/employees/me` | **none — inherent right** |

`/employees/me` is deliberately not capability-gated: reading your own record cannot be revoked by a permission edit. Static paths are declared before `/{user_id}`, and a test proves the ordering (a swallowed route would raise 400 from `ObjectId("linkable")`).

---

## 7. Test results

| Suite | Checks | Result |
|---|---|---|
| `test_phase1_foundation` | 96 | ✅ |
| `test_phase1_integration` | 43 | ✅ |
| `test_phase2_employee` | **123** | ✅ |
| `test_phase2_integration` | **54** | ✅ |
| **Total** | **316** | ✅ **316/316** |

**Coverage by dimension (S3):**

| Dimension | Evidence |
|---|---|
| Positive | Create/read/update profile; masters CRUD; hierarchy; filters; search; pagination |
| Negative | 20 `expect_http` assertions — 400/403/404/409/422 each with a message fragment |
| Edge | Leap day valid / non-leap Feb 29 rejected · regex metacharacters in search escaped · circular reporting chain · duplicate differing only in case or spacing · same master name in another company · upsert on first write · lowercase PAN/IFSC · unmatched filter returns empty not everything |
| Permission | 15 capability assertions across 5 roles; INTERNAL explicitly denied client salary |
| Validation | Salary (negative/non-numeric/absurd) · dates (format/impossible/ordering, incl. against the *existing* stored date) · PAN/Aadhaar/UAN/IFSC · bank account · cross-company master references |
| API | Status codes; response shapes; query bounds; route ordering |
| Database | Unique/sparse indexes; delete-protection; identity collections unwritten |
| Frontend | Manual script — [PHASE_2_TEST_SCRIPT.md](PHASE_2_TEST_SCRIPT.md) |
| E2E | Department → designation → employee → directory → profile → hierarchy |

**Security-relevant assertions worth calling out:**
- Salary is **omitted**, not nulled — an unauthorised viewer cannot recover it from the payload or the DOM.
- Out-of-scope reads return **404, not 403** — a 403 would confirm an id exists in another tenant.
- Client callers **cannot retarget** any endpoint via `company_id`; asserted at the route boundary, not inferred from a body.
- Internal callers with no company get **400**, never silent cross-tenant data.

---

## 8. Smoke (S1) & Regression (S2)

| Check | Result |
|---|---|
| App boots; 5 HRMS collections provisioned; no new warnings | ✅ |
| Idempotent across 2 live restarts (identical index counts) | ✅ |
| `npm run build` | ✅ 2.48s |
| Lint — HRMS files | ✅ **0 errors** (2 warnings, same `icon: Icon` idiom as pre-existing code) |
| Lint — whole `src` | ✅ 2 errors, both pre-existing (OOS-004), untouched |
| Identity collections unpolluted | ✅ **0 of 188** user docs carry HR fields |
| Shared-file diff | ✅ still 9 files, additive; **no new shared dependencies** |
| Non-HRMS route counts | ✅ unchanged |
| `/api/tasks`, `/api/users/me`, `/api/tpms/activities`, `/api/holidays` | ✅ still routed (401, not 404) |
| Phase 1 suites | ✅ 96/96 and 43/43 after the Finding #3 fix |
| Assistant harnesses | ⚠️ unchanged — pre-existing 503, see OOS-003 |

---

## 9. Completion checklist

- [x] All 13 development steps passed
- [x] 316/316 automated checks
- [x] Zero new shared-file dependencies
- [x] Identity collections provably never written
- [x] Salary privacy enforced at the payload level
- [x] Multi-tenant isolation asserted at the route boundary
- [x] Live provisioning verified idempotent
- [x] Out-of-scope findings documented, not changed
- [x] `PHASE_2_REPORT.md` + `PHASE_2_TEST_SCRIPT.md`
- [ ] Git tag `hrms-phase-2` — *awaiting go-ahead; nothing committed or pushed*

---

## 10. Residual risk

| Risk | Severity | Mitigation |
|---|---|---|
| Legacy `users.department` / `.designation` still diverge from the new masters | Low | Both surfaced side-by-side in the UI (`legacy_department`) so mismatches are visible, not silent; suggestions flow drives migration |
| MANAGER scoping degrades to direct-reports-only when the HOD has no profile | Low | **Fails closed** by design; asserted in tests |
| No bulk import of employees | Low | Not in Phase 2 scope; the linkable-user picker covers onboarding one at a time |
| `employee_code` editable by HR | Low | Uniqueness enforced per company; changes audited |

---

## 11. Ready for Phase 3

Phase 3 (Requisitions + JD) plugs into what Phase 2 built, with no shared-file changes:

- `hrms_departments` / `hrms_designations` — requisition department + designation become real references, not free text
- `hrms_employee_service.get_employee()` — resolves the raiser and the hiring manager
- `Cap` + `ROLE_CAPABILITIES` — register `requisition.*` and `jd.*`
- `_require()` / `_company()` in `routes/hrms.py` — the gate and tenant-pinning helpers already exist
- `HrmsScopeBar`, `HrmsPageHeader`, `HrmsStates` — the shared shell is in place
