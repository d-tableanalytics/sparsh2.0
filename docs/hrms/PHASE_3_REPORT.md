# HRMS Phase 3 — Requisitions (FMS) + Job Descriptions · Phase Report

> **Status:** ✅ COMPLETE — all 13 steps of the development order passed
> **Scope:** hiring requisitions, co-authored job descriptions, the 4-state approval chain
> **Roadmap:** [HRMS_IMPLEMENTATION_ROADMAP.md](../HRMS_IMPLEMENTATION_ROADMAP.md) § Phase 3
> **Scope rule honoured:** HRMS only. Out-of-scope findings in [OUT_OF_SCOPE_FINDINGS.md](OUT_OF_SCOPE_FINDINGS.md), documented and untouched.

---

## 1. What shipped

The recruitment entry point, and the phase that establishes the approval pattern reused by assessments, interviews, offers and onboarding.

| Capability | Delivered |
|---|---|
| Raise requisition + JD | One form, one submission — they are approved together |
| 4-state approval chain | `Pending HR Review → Pending MD Approval → Approved / Rejected` |
| HR review stage | Forward to MD, or reject with a mandatory reason |
| MD approval stage | Approve (optionally revising CTC), or reject with a reason |
| JD co-approval | JD flips to Approved with its requisition — this is what unlocks Phase 4 posting |
| JD library | View/edit; approved JDs are frozen. No standalone approve path |
| Closing status | Open / Hired / Hold / Closed / Cancel |
| Notifications + audit | Every transition notifies the next actor and writes an audit row |

**8 new capabilities.** Departments and designations are now **real references**, not free text — the payoff for Phase 2.

---

## 2. Three correctness properties

**1. Transitions are table-driven.** `REQ_TRANSITIONS` in `models/hrms.py` maps `action → (required_status, next_status, capability, remark_required)`. The guard, the tests and this document all read from that one table; an action absent from it cannot happen. Adding a stage later is a data change, not new control flow.

**2. Transitions are compare-and-swap.** The expected status is part of the update **filter**, not a pre-read:

```python
result = await coll.update_one(
    {"request_no": ..., "approval_status": required_status.value},   # <- the guard
    {"$set": updates})
if result.matched_count == 0:
    raise HTTPException(409, "This requisition was updated by someone else…")
```

A read-then-write would let two concurrent approvals both land. Tested with 5 simultaneous approvals: **exactly 1 wins, 4 get 409.**

**3. Create is all-or-nothing.** Mongo transactions need a session this codebase never uses, so the JD is written first and **deleted again** if the requisition insert fails. The invariant that matters — *every requisition has a JD* — therefore always holds. Tested by forcing the requisition insert to throw and asserting no orphan JD remains.

*Residual:* a transaction would additionally prevent a briefly-orphaned JD if the process died between the two writes. See §9.

---

## 3. Separation of duties — a deliberate design decision needing your awareness

**`requisition.review_hr` and `requisition.approve_md` are held by different roles.** HR forwards; MD approves. Neither can complete both stages.

| Role | review_hr | approve_md |
|---|---|---|
| HR | ✅ | ❌ |
| MD / clientadmin | ❌ | ✅ |
| HOD, Employee | ❌ | ❌ |
| Sparsh INTERNAL | ❌ | ❌ — the approval chain is the client's own governance |
| superadmin | ✅ | ✅ — documented break-glass |

**Why:** a two-stage approval one person can complete alone is not a control. The source allowed `Admin` to perform both stages, which made the second stage decorative.

### ✅ DECIDED — option (a), confirmed by the owner

Separation of duties stands as built: **MD cannot clear the HR stage.** The accepted cost is that a company with **no user holding governance_role `HR`** cannot move a requisition past stage 1 (superadmin remains the break-glass, holding both).

**Mitigation shipped with the decision.** An accepted risk that fails *silently* is a support ticket waiting to happen — a requisition would sit at "Pending HR Review" indefinitely, indistinguishable from one HR simply hadn't got to. So `create_requisition` now checks whether the company has an active HR user, and when it does not:

- the **MD is notified + emailed**: *"…this company has no user with the HR role, so it cannot be reviewed. Assign the HR governance role to someone to unblock it."*
- the **raiser is notified** that their requisition was created but has no reviewer, and that the MD has been told
- the requisition is still **created, not blocked** — warning, not a wall

Verified in both directions: with an HR user present **no** escalation fires; with none, both notifications go out and the requisition is still created (`test_phase3_requisition`, 4 checks).

*Still not implemented:* a self-approval guard (raiser ≠ approver). It would deadlock a small company where HR raises their own requisitions. Recommended for Phase 11 as a configurable rule.

---

## 4. Findings

### Finding #1 — Phase 2 shipped a silent frontend defect ⚠️ **FIXED + GUARDED**

While wiring Phase 3 I found that `frontend/src/features/hrms/access.js` still declared only **Phase 1's three capabilities**. Phase 2's components were written against `CAP.EMPLOYEE_WRITE`, `CAP.DEPARTMENT_WRITE`, `CAP.EMPLOYEE_SALARY_WRITE` — all of which resolved to **`undefined`**.

`hasCap(caps, undefined)` → `caps.includes(undefined)` → `false`. So in Phase 2 as delivered:
- the **Add employee** button never rendered — for anyone, including HR
- department/designation **Add / rename / delete** controls never rendered
- the employee profile was effectively read-only for everyone
- the salary field was never editable

**Why nothing caught it.** No crash, no console error, no failing backend test — the UI simply rendered less than it should, which reads as a permissions problem rather than a bug. My backend suites cannot see JS constants, and per your decision there is no frontend test harness.

**Fix.** All 19 capabilities now declared in `CAP`.

**Guard.** New suite `test_capability_parity.py` parses `access.js` and asserts the backend `Cap` enum and the frontend `CAP` map describe **exactly the same set** — both values and key names. Any future phase that adds a capability to one side and forgets the other now fails a test instead of silently hiding controls. This is the single highest-value test in the module: it closes the drift class the source docs call out as the #1 frontend defect (FE §5, "rendering actions the API will 403 for") — here in the opposite direction.

*Honest assessment:* this should have been caught in Phase 2. The Phase 2 manual test script (B2, D1, F-series) would have found it on first run; the script was written but not executed. The parity guard now makes the automated suite catch it regardless.

### Finding #2 — two more brittle assertions ⚠️ **FIXED**

Phase 3 broke `test_phase1_integration` and `test_phase2_integration`. Both failures were the same assertion — `caps == ["module.access"]` for a plain employee — and Phase 3 legitimately granted employees `requisition.read/create` and `jd.read` (the documented "anyone may raise a requisition" intent).

Rewritten as the invariant the assertion actually meant: *an employee holds no `*.write` capability, no approval capability, and cannot see salary.* That holds for every future phase.

This is the second occurrence of the same lesson (Phase 2 Finding #3). **Rule adopted for the remaining phases: assert invariants, never snapshots.**

---

## 5. Files

### New — HRMS-owned (7)

| File | Purpose |
|---|---|
| `backend/app/services/hrms_requisition_service.py` | Requisitions + JDs: create, state machine, guards |
| `backend/app/services/hrms/tests/test_phase3_requisition.py` | Unit harness (104 checks) |
| `backend/app/services/hrms/tests/test_phase3_integration.py` | HTTP harness (59 checks) |
| `backend/app/services/hrms/tests/test_capability_parity.py` | **Cross-language drift guard** (6 checks) |
| `frontend/src/features/hrms/recruitment/RequisitionList.jsx` | List, tiles, filters |
| `frontend/src/features/hrms/recruitment/RequisitionDrawer.jsx` | Detail, stepper, stage action bars |
| `frontend/src/features/hrms/recruitment/RequisitionFormModal.jsx` | Raise / edit |
| `frontend/src/features/hrms/recruitment/ApprovalDialog.jsx` | Reusable — Phases 6–9 will reuse it |
| `frontend/src/features/hrms/recruitment/JdLibrary.jsx` | Master/detail JD library |

Extended: `models/hrms.py`, `routes/hrms.py`, `hrmsApi.js`, `access.js`.

### Modified — shared (0 new)

**Phase 3 again introduced no new shared-file dependencies** — only `App.jsx` (+5, two routes) and `Sidebar.jsx` (+4, two nav entries), both already on the Phase 1 approved list.

Cumulative shared footprint remains **9 files, 173 insertions / 1 deletion**.

---

## 6. Database

| Collection | Indexes |
|---|---|
| `hrms_requisitions` | `uniq_request_no` (unique) · `by_company_approval` · `by_company_closing` · `by_company_creator` · `by_company_department` |
| `hrms_job_descriptions` | `uniq_jd_no` (unique) · `by_request` · `by_company_status` |

Live-verified: 7 HRMS collections, idempotent, identity collections unpolluted (0 of 188 user docs).

---

## 7. APIs (9 new)

| Method | Route | Capability |
|---|---|---|
| GET | `/hrms/requisitions` | `requisition.read` (row-scoped) |
| POST | `/hrms/requisitions` | `requisition.create` — **open to all** |
| GET/PATCH/DELETE | `/hrms/requisitions/{no}` | read / `requisition.write` |
| POST | `/hrms/requisitions/{no}/approve` | **per-action, from the transition table** |
| POST | `/hrms/requisitions/{no}/close` | `requisition.close` |
| GET | `/hrms/jd`, `/hrms/jd/{jd_no}` | `jd.read` |
| PATCH | `/hrms/jd/{jd_no}` | `jd.write` |

The approve route carries **no blanket `_require()`** by design — its capability depends on the action, and lives in the same table that defines the state machine, so the gate cannot drift from the rule it guards. Asserted in the integration harness.

**Not built, deliberately:** `POST /hrms/jd` and any JD approve/reject route. JDs are co-approved with their requisition; the source's standalone workflow is documented as removed with its route left behind as dead code (BE §5.3). Tests assert both return 405/404.

---

## 8. Test results

| Suite | Checks | Result |
|---|---|---|
| `test_capability_parity` | 6 | ✅ |
| `test_phase1_foundation` | 96 | ✅ |
| `test_phase1_integration` | 46 | ✅ |
| `test_phase2_employee` | 123 | ✅ |
| `test_phase2_integration` | 55 | ✅ |
| `test_phase3_requisition` | **104** | ✅ |
| `test_phase3_integration` | **59** | ✅ |
| **Total** | **489** | ✅ **489/489** |

**Notable coverage:**
- **All 16 status × action pairs.** The 4 legal ones succeed; the **12 illegal ones each return 409** — enumerated programmatically from the transition table, so the test cannot drift from the machine.
- **Concurrency.** 5 simultaneous `hr-approve` calls → 1 win, 4 × 409.
- **Atomic create.** Forced insert failure leaves **no orphan JD**.
- **Cascade delete.** Deleting a requisition removes its JD.
- **JD content rule.** Enforced on create *and* re-checked against the merged result on edit, so an edit cannot empty a JD that was valid when raised.
- **Frozen states.** Approved requisition → not editable (409), not deletable (409). Approved JD → not editable (409).
- **Row scoping.** An employee sees only requisitions they raised, and their stat tiles match their scoped list.
- **Tenant isolation.** Cross-tenant read → 404 (not 403, which would confirm existence). Client cannot retarget list/create/approve/JD via `company_id`.

---

## 9. Smoke (S1) & Regression (S2)

| Check | Result |
|---|---|
| App boots; 7 HRMS collections provisioned; no new warnings | ✅ |
| `npm run build` | ✅ 2.53s |
| Lint — HRMS files | ✅ **0 errors** (4 warnings, same pre-existing `icon: Icon` idiom) |
| Lint — whole `src` | ✅ 2 errors, both pre-existing (OOS-004), untouched |
| Identity collections unpolluted | ✅ 0 |
| Shared-file diff | ✅ still 9 files, 1 deletion; **no new shared dependencies** |
| `/api/tasks`, `/api/users/me`, `/api/tpms/activities`, `/api/holidays` | ✅ still routed |
| Phases 1 + 2 suites | ✅ green after the Finding #2 fix |
| Assistant harnesses | ⚠️ unchanged pre-existing 503 (OOS-003) |

---

## 10. Residual risk

| Risk | Severity | Note |
|---|---|---|
| Company with no HR user cannot progress a requisition | **Low** *(was Medium)* | §3 — accepted by decision (a); now **announces itself** to the MD and the raiser at raise time rather than failing silently |
| Create-with-JD uses a compensating delete, not a transaction | Low | Invariant holds; a mid-write process death could orphan a JD. Atlas supports transactions if you want them |
| JD attachments accepted by the API but no upload UI yet | Low | The upload pipeline lands in Phase 4; the `{name,url}` contract and its validation are already in place |
| No self-approval guard (raiser may be approver) | Low | Deliberately deferred — would deadlock small companies. Recommended as configurable in Phase 11 |
| Frontend has no automated tests | **Medium** | Your approved decision. Finding #1 is what that costs; the parity guard covers the highest-risk slice |

---

## 11. Completion checklist

- [x] All 13 development steps passed
- [x] 489/489 automated checks
- [x] All 16 state × action pairs verified
- [x] Concurrency (CAS) verified
- [x] Atomic create + cascade delete verified
- [x] Separation of duties enforced and tested
- [x] Zero new shared-file dependencies
- [x] Capability drift guard added
- [x] `PHASE_3_REPORT.md` + `PHASE_3_TEST_SCRIPT.md`
- [ ] Git tag `hrms-phase-3` — *awaiting go-ahead; nothing committed or pushed*

---

## 12. Ready for Phase 4

Phase 4 (Job Postings + Public Apply) consumes what Phase 3 produced:

- **Approved JDs** are the publishable unit — `jd.status == "Approved"` is the gate
- `hrms_requisitions.vacancy` drives Phase 8/9 auto-closure
- `ApprovalDialog` is reusable as-is
- Phase 4 brings the first genuinely new infrastructure since Phase 1: the **public router**, rate limiting, and the upload pipeline (which also gives JD attachments their UI)
