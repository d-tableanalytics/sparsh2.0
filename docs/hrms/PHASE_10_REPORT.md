# HRMS Phase 10 — Recruitment Dashboard & Reports · Phase Report

> **Status:** ✅ COMPLETE — all 13 steps passed
> **Scope:** read-only analytics over everything Phases 3–9 produced. No new writes.
> **Roadmap:** [HRMS_IMPLEMENTATION_ROADMAP.md](../HRMS_IMPLEMENTATION_ROADMAP.md) § Phase 10
> **Scope rule honoured:** HRMS only. No new out-of-scope findings; the register stands at OOS-001…005.

Both analysis documents flag the same thing: the source HRMS computed every figure **in the browser** (FRONTEND_ANALYSIS §6.1; BACKEND_ANALYSIS records no reporting backend at all). That has three consequences, and this phase exists to remove all three.

1. **It cannot be role-scoped.** Whatever the browser is sent, it can total — so a hiring manager who should see their own requisitions is one devtools panel away from the company's whole pipeline.
2. **It does not scale.** Totalling 10k candidates client-side means shipping 10k candidates.
3. **It drifts.** Each screen re-derives "how many were interviewed" slightly differently, and no two agree.

---

## 1. What shipped

| Capability | Delivered |
|---|---|
| Dashboard | 8 KPI tiles, **every one deep-linking** to the screen that produced it |
| Hiring funnel | 8 stages by **effective rank**, with per-stage and of-total conversion |
| Positions summary | Open / vacancies / filled / on hold / cancelled |
| Offer outcomes | Draft / sent / accepted / declined / revoked + acceptance rate |
| **Time to hire** | Median **and** mean days, application → offer acceptance |
| Breakdowns | Source · department · designation · platform |
| Detailed reports | 5 tabbed tables, paginated, searchable, date-windowed |
| Export | CSV + Excel, **server-rendered**, with honest truncation |
| Salary redaction | CTC columns omitted for anyone without `employee.salary.read` |

**3 new capabilities:** `analytics.read`, `report.read`, `report.export`.

---

## 2. Design decisions worth recording

### Effective rank — why the funnel can't lie

A funnel built by counting `application_status` is wrong in a way that is obvious once seen: a candidate sitting at **Offer Accepted** no longer *has* an interview status, so the funnel shows **more offers than interviews**. Every candidate is therefore ranked by the furthest point they can be *shown* to have reached:

```
effective_rank = max(rank(application_status),
                     rank implied by an assessment record,   # 3
                     rank implied by an interview record,    # 4
                     rank implied by an offer record)        # 6, or 7 if accepted
```

Evidence outranks the status field, because evidence is a fact and a status is a label somebody can drag backwards. Each stage then counts *"reached at least this stage"*, which makes the series **monotonically non-increasing by construction** — the property a funnel must have to mean anything. Asserted directly in the harness.

Two details that matter:
- **A `Draft` offer proves nothing.** It has not been issued, so nothing has happened to the candidate. Only Sent/Accepted/Declined/Revoked count as evidence.
- **A rejected candidate ranks where they entered, not where they left.** `Offer Declined` still ranks at the offer stage — that stage genuinely was reached.

### Every number is server-side, and the UI is dumb on purpose

`RecruitmentDashboard.jsx` and `RecruitmentReports.jsx` fetch and lay out. They never total, filter or re-derive. The screen and the API therefore cannot disagree — which is the specific failure being fixed, not a stylistic preference.

The **columns are decided by the server** too. That is what makes salary redaction real: a caller without `employee.salary.read` never *receives* the CTC column, so it is absent from the payload rather than hidden in the DOM. Tested by asserting `800000` cannot be found anywhere in an internal user's export.

### `report.export` is separate from `report.read`

Reading aggregate figures on a screen and taking a file of personal data off the system are different acts. A **hiring manager gets read and not export** — proven at the HTTP layer, where they get 200 on the table and 403 on the download.

### Exports are rendered server-side

The house has two patterns: ORM builds files in the browser with `xlsx`/`jspdf`; `/reports` streams them from the backend. I followed **`/reports`**, because the rows here are already role-scoped and paginated — rebuilding a file client-side would mean shipping rows the API had correctly withheld.

But this module does **not import** `routes/reports.py`'s private `_export_*` helpers. That file is outside HRMS's scope; coupling to its internals would make HRMS break when it changes, and I have been asked not to modify it. ~40 lines of CSV/XLSX writing are duplicated deliberately: DRY *within* a module beats DRY *across* a boundary I have been told not to cross.

### CSS bars, not recharts

The roadmap sketched recharts for the funnel. The actual shape is eight horizontal bars with two labels each — recharts adds no interaction worth ~100 kB, and the percentages come from the server anyway. **Bundle delta: +1.9 kB** (3,152.43 → 3,154.33 kB). The roadmap also proposed lazy-loading the pages; with no chart library there is nothing to lazy-load, so they are imported eagerly like every other HRMS screen.

### Truncation is announced twice

An export beyond 5,000 rows is capped. The caller is told in an `X-Export-Truncated` header **and** by a note written into the file itself, because whichever one the recipient looks at must be honest. A silently short file that looks complete is worse than no file.

---

## 3. Findings

### Finding #1 — Phase 9's index fix did not work in production 🔴 **FIXED**

The live database check deferred at the end of Phase 9 ran here, and it caught exactly what it was written to catch.

Phase 9 made `uniq_user` sparse and taught the provisioner to reconcile a conflicting index by dropping and recreating it. That reconciliation keyed on **error code 85** (`IndexOptionsConflict`). Atlas raises **86** (`IndexKeySpecsConflict`):

```
[WARN] HRMS index uniq_user on hrms_employee_profiles: An existing index has the same
name as the requested index. … 'code': 86, 'codeName': 'IndexKeySpecsConflict'
```

That is the *non-reconciling* branch. So the deployed index stayed **non-sparse**, and Phase 9's landmine was still live: under a non-sparse unique index Mongo treats a missing field as null, so the **second** onboarding-created employee at any company would die on a duplicate-key error.

**Fix.** Both codes reconcile, matched on the **numeric codes alone**. The first attempt also had a `"already exists" in str(ie)` fallback — the actual message says *"has the same name as"*, so the string branch missed too. Message wording is not a stable contract; the error code is.

**Regression:** the harness now drives the provisioner with a fake that raises 85 **and** one that raises 86, asserting both drop-and-recreate with `sparse=True`, while an 11000 duplicate-key failure still never drops an index.

**Still to do — needs your go-ahead.** The corrected reconciliation has *not* been run against Atlas; you declined that step, which is entirely reasonable since it drops and recreates a live unique index. Until the backend starts against Atlas with this build, `uniq_user` remains non-sparse and the second onboarding-created employee will fail. Section K3 of the Phase 9 test script covers verifying it.

### Finding #2 — HRMS was silently locked out for every client user 🔴 **FIXED**

Phase 1's regression guard failed during this phase's S2 run:

```
FAIL  hrms_enabled survives /users/me serialisation
FAIL  governance_role survives /users/me serialisation
```

Both declarations had been removed from `UserResponse` and replaced with a `delegation_enabled` declaration — the OOS-001 fix, applied outside this work. Pydantic v2 drops any field a `response_model` does not declare, so the consequence was immediate and invisible:

- `hrms_enabled` never reached the client → `hrmsAccessState()` returned `'unknown'` forever → the route guard never admitted a client user to the module.
- `governance_role` never reached the client → `hrmsRole()` degraded **every** client user to `EMPLOYEE`.

**Fix.** Both HRMS lines restored alongside `delegation_enabled` — all three coexist; nothing about the delegation fix was touched. The guard is now broadened to assert **all four** module flags (`orm_enabled`, `tpms_enabled`, `delegation_enabled`, `hrms_enabled`) stay declared, so the next such edit fails in the harness instead of in the field.

This is the same omission that caused OOS-001 in the first place, now having bitten twice. The comment on the model says so explicitly.

### Finding #3 — a false alarm worth recording

A survey flagged that `hrms_posting_service.submit_application` writes `"company_id": company_id` unstringified while every other writer uses `str(...)`, which would make public applicants invisible to a `$match` on a string. **Traced and cleared:** `company_id` is read from the posting document, which stores `str(company_id)` at creation. The value is already a string. No change made — recorded so the next reader does not re-open it.

---

## 4. Files

### New — HRMS-owned (6)

| File | Purpose |
|---|---|
| `backend/app/services/hrms_analytics_service.py` | Every aggregation, plus CSV/XLSX rendering |
| `backend/app/services/hrms/tests/test_phase10_analytics.py` | Unit harness (**155** checks) |
| `backend/app/services/hrms/tests/test_phase10_integration.py` | HTTP harness (**103** checks) |
| `frontend/src/features/hrms/analytics/analyticsKit.js` | Layout constants + `nf` (no components) |
| `frontend/src/features/hrms/analytics/analyticsKit.jsx` | `KpiCard`, `FunnelChart`, `BarList`, `MiniStat`, `RangePicker`, `ScopeNotice` |
| `frontend/src/features/hrms/analytics/RecruitmentDashboard.jsx` | The dashboard |
| `frontend/src/features/hrms/analytics/RecruitmentReports.jsx` | The tabbed tables |

The kit is split `.js` / `.jsx` to match `components/reports/chartKit.js` — constants in a component module trip `react-refresh/only-export-components` and make a styling tweak invalidate the components too.

### Modified — HRMS-owned

`models/hrms.py` (3 capabilities, `STAGE_RANK`, `FUNNEL_STAGES`, `REPORT_ENTITIES`, `BREAKDOWN_FIELDS`, 4 indexes, 3 enums) · `routes/hrms.py` (+5 routes) · `db/mongodb.py` (Finding #1) · `models/user.py` (Finding #2) · `features/hrms/access.js` · `services/hrmsApi.js` · `test_phase1_foundation.py` (broadened guard)

### Modified — shared (0 new)

Still **9 files**, measured against the pre-HRMS baseline. Phase 10 touched two of them — `db/mongodb.py` and `models/user.py` — both to fix defects, both explained above, and neither adding a new dependency.

### Database

4 new date indexes, so a windowed dashboard is index-backed rather than filtering in memory as history accumulates:

| Collection | Index |
|---|---|
| `hrms_candidates` | `by_company_applied` — `(company_id, applied_at ↓)` |
| `hrms_offers` | `by_company_created` |
| `hrms_onboarding` | `by_company_created` |
| `hrms_requisitions` | `by_company_created` |

**Verified live:** all four exist in Atlas. 14 HRMS collections, 53 index declarations, names unique.

---

## 5. APIs (5 new, all GET)

| Method | Route | Gate |
|---|---|---|
| GET | `/hrms/analytics/dashboard` | `analytics.read` |
| GET | `/hrms/analytics/funnel` | `analytics.read` |
| GET | `/hrms/analytics/breakdown?by=` | `analytics.read` |
| GET | `/hrms/reports/{entity}` | `report.read` (CTC redacted without salary read) |
| GET | `/hrms/reports/{entity}/export?fmt=` | **`report.export`** |

`entity` and `by` are **enums, not free strings** — mapping a URL segment onto a collection name would let a caller read any collection in the database. Proven: `learners`, `staff`, `hrms_audit_log`, `companies`, `../users` are all refused, and none reaches the service.

---

## 6. Test results

| Suite | Checks | Result |
|---|---|---|
| `test_capability_parity` | 6 | ✅ |
| Phases 1–9 | 1612 | ✅ |
| `test_phase10_analytics` | **155** | ✅ |
| `test_phase10_integration` | **103** | ✅ |
| **Total** | **1876** | ✅ **1876/1876 across 21 suites** |

The unit fixture is deliberately **small and hand-counted** — 15 candidates whose expected funnel (`10 → 8 → 7 → 7 → 4 → 3 → 2 → 1`) and every KPI can be verified by reading the fixture. That is the only way to know an aggregation is *right* rather than merely self-consistent.

**Highlights:** evidence beating a stale status (a candidate whose status says *Applied* but who has a completed interview) · a Draft offer conferring no rank · funnel monotonicity asserted directly · zero-data dividing by nothing · **a hiring manager seeing 4 candidates where HR sees 10, on the dashboard, the funnel, the breakdowns and the report** · tenant isolation on all five endpoints including the export · regex metacharacters escaped in search · pagination clamped at both ends · salary omitted from columns, rows *and* exports · truncation announced in the header and inside the file · `POST/PATCH/PUT/DELETE` returning 405 on every analytics route · **90-route auth sweep still clean**.

---

## 7. Smoke (S1) & Regression (S2)

| Check | Result |
|---|---|
| All 21 suites | ✅ 1876/1876 |
| **Live DB** — 14 collections, all 4 Phase 10 indexes present | ✅ |
| `npm run build` | ✅ |
| **Bundle delta** | ✅ **+1.9 kB** (3,152.43 → 3,154.33 kB) |
| Lint — HRMS files | ✅ **0 errors** (8 warnings, pre-existing idiom) |
| Lint — whole `src` | ✅ 2 errors, both pre-existing (OOS-004) |
| Shared-file footprint | ✅ still 9 files |
| ERP `/reports` untouched and still admin-gated | ✅ |
| All four public surfaces still anonymous | ✅ |
| Task Management / Calendar / TPMS / CRM still 401 | ✅ |
| No shared chart component modified | ✅ (a new HRMS-owned kit was added instead) |

---

## 8. Residual risk

| Risk | Severity | Note |
|---|---|---|
| **`uniq_user` still non-sparse in Atlas** | **High** | Finding #1's fix is written and tested but **not yet applied to the live database** — awaiting your go-ahead to start the backend against Atlas |
| Performance target not measured at 10k candidates | Medium | Indexes are in place and every read is capped at 20k, but the roadmap's "<500 ms at 10k" was not benchmarked against real volume |
| Time-to-hire ignores candidates still in flight | Low | By design — it measures completed hires. A "current pipeline age" metric would be a separate figure |
| Stage-latency metrics absent | Medium | Candidates carry no per-stage timestamps; deriving them means parsing audit-log prose, which would make the metric hostage to a wording change. Deliberately not done |
| Export capped at 5,000 rows | Low | Announced, never silent |
| Frontend has no automated tests | Medium | Your approved decision |

---

## 9. Completion checklist

- [x] All 13 development steps passed
- [x] 1876/1876 automated checks across 21 suites
- [x] Figures reconciled against a hand-counted fixture
- [x] Cross-company isolation proven on all five endpoints
- [x] **Two production defects found and fixed** (a fix that didn't fire; HRMS locked out for all client users)
- [x] Bundle delta recorded (+1.9 kB)
- [x] `PHASE_10_REPORT.md` + `PHASE_10_TEST_SCRIPT.md`
- [ ] **Live index reconciliation** — awaiting your go-ahead
- [ ] Git tag `hrms-phase-10` — *awaiting go-ahead*

---

## 10. Ready for Phase 11

Phase 11 (Settings & RBAC console) is the natural next step, and Phase 10 sharpens the case for it:

- The capability set is now **40 members across 6 roles**, hand-maintained in `ROLE_CAPABILITIES`. A console to view and override it is overdue.
- `report.export` vs `report.read` is the clearest example yet of a distinction an administrator will want to grant per user, not per role.
- Every gate already resolves through `can(user, capability)` — the single-mechanism promise from §0.2 — so Phase 11 layers per-user grants onto an existing seam rather than refactoring one into place.
