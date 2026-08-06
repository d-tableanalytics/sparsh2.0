# HRMS Phase 5 — Candidates, Screening & Journey · Phase Report

> **Status:** ✅ COMPLETE — all 13 steps of the development order passed
> **Scope:** candidate pipeline, bulk triage, and the audit-derived candidate journey
> **Roadmap:** [HRMS_IMPLEMENTATION_ROADMAP.md](../HRMS_IMPLEMENTATION_ROADMAP.md) § Phase 5
> **Scope rule honoured:** HRMS only. No new out-of-scope findings this phase; the register stands at OOS-001…005.

---

## 1. What shipped

The working surface for everyone arriving through Phase 4, plus manual additions.

| Capability | Delivered |
|---|---|
| Pipeline | Kanban / List / Grid over one dataset, 8 server-defined columns |
| Candidate drawer | Details, contact, duplicate flag, stage move, journey |
| **Lifecycle enforcement** | Every move validated against a declared transition graph |
| Manual add | Walk-ins, referrals, agency CVs |
| Screening | shortlist · review · hold · duplicate · reject · forward, single or bulk |
| Assessment-aware shortlisting | `requires_assessment` routes to Assessment Pending |
| Duplicate detection | Advisory flagging on normalised email and phone |
| **Journey** | 7-step rail + colour-coded timeline, reconstructed from the audit trail |

**3 new capabilities:** `candidate.read`, `candidate.write`, `candidate.screen`.

---

## 2. The headline fix — a real state machine

The source enforced **nothing** on candidate status. Any value could be assigned to any other, so a candidate could go `Applied → Joined` in one write and skip assessment, interviews, offer and onboarding entirely. Every later phase then had to defend against states that cannot legitimately exist. The analysis also flags the parallel legacy `status_6..12` columns as a second source of truth (BE Risk #7) — we never created them.

Phase 5 declares the graph as data:

```python
FORWARD_TRANSITIONS = { AppStatus.APPLIED: {UNDER_REVIEW, SHORTLISTED}, … }
ALWAYS_AVAILABLE    = {REJECTED, ON_HOLD, DUPLICATE}   # from any non-terminal stage
TERMINAL_STATUSES   = {EMPLOYEE_CREATED, OFFER_DECLINED, DUPLICATE}
```

- An illegal move is a **409 that lists what *is* allowed from here**, not a silent write.
- `ALWAYS_AVAILABLE` exists so a recruiter can always stop or park a pipeline whatever stage it reached — encoding those as per-stage edges would be noise, and forgetting one would trap a candidate.
- The drawer offers only `allowed_next` — **the server's own answer** — so the UI cannot present a move the API will refuse.
- No drag-and-drop, deliberately: dropping a card into an arbitrary column implies every move is legal, and most are not.

**Tested exhaustively:** every legal edge, plus `Applied → {Joined, Selected, Offer Accepted, Employee Created, Interview Scheduled, MD Round}` all refused, terminal stages proven immovable, and `Assessment Pending → Interview` refused (must complete first).

---

## 3. Findings

### Finding #1 — duplicate detection was too weak for the country it serves ⚠️ **FIXED**

A test asserted that `+91 98765 43210` and `9876543210` are the same person. They are — but my normaliser stripped non-digits and compared the whole string, so `919876543210 ≠ 9876543210` and the duplicate went unflagged.

This module is India-specific throughout — PAN, Aadhaar, IFSC, UAN, PF/ESI, IST, rupees, professional tax. A phone matcher that misses a `+91` prefix does not do its job here.

**Fix.** `normalise_phone()` keeps the **last 10 digits** when there are at least ten, and compares shorter strings whole (so a 6-digit extension is never truncated into a false match).

**Honest limitation.** Phase 4's *blocking* duplicate check on the public form still uses an exact `can_contact` match, so `+91 98765 43210` and `9876543210` can both get through as separate applications. Phase 5's advisory flag then catches them. Making the Phase 4 block normalise would require a stored normalised field and a migration — worth doing, but it is a schema change I did not want to slip in unannounced. **Recommended for Phase 15.**

### Finding #2 — a test assertion coupled to DB availability ⚠️ **FIXED**

`"public apply route still anonymous"` asserted `status in (404, 410, 429)`. Offline the handler reaches the datastore and answers **503** — which is still proof it was not gated by auth. Rewritten to assert the property that matters: **never 401/403**.

Incidentally this run also demonstrated Phase 4's **fail-open limiter** working as designed — the log shows `[WARN] HRMS rate-limit store unavailable (view)` followed by the request proceeding.

### Design note — why partial success, not all-or-nothing

`POST /candidates/screen` returns `{moved, skipped}` and the UI shows **both**. A batch of 50 where 3 sit at an incompatible stage should move the 47 and say which 3 blocked and why. Failing wholesale would leave the recruiter to work out which ones caused it; reporting only "done" would hide candidates that never actually moved.

### Design note — shortlisting takes a legal two-hop path

Shortlisting an assessment-required candidate from `Applied` needs to reach `Assessment Pending`, but the graph has no such edge (`Applied → Assessment Pending` would skip shortlisting). The service takes `Applied → Shortlisted → Assessment Pending` and **audits both hops**, so the recorded history stays legal and the journey shows what actually happened. Asserted in the tests.

---

## 4. Files

### New — HRMS-owned (5)

| File | Purpose |
|---|---|
| `backend/app/services/hrms_candidate_service.py` | Pipeline, screening, journey (one domain, one service) |
| `backend/app/services/hrms/tests/test_phase5_candidate.py` | Unit harness (113 checks) |
| `backend/app/services/hrms/tests/test_phase5_integration.py` | HTTP harness (58 checks) |
| `frontend/src/features/hrms/recruitment/CandidatePipeline.jsx` | 3 layouts + drawer + add modal |
| `frontend/src/features/hrms/recruitment/ScreeningBoard.jsx` | Tabs, checkbox table, bulk bar, partial-result panel |
| `frontend/src/features/hrms/recruitment/CandidateJourney.jsx` | Rail + timeline (view and modal) |

### Modified — shared (0 new)

Still **9 files, 194 insertions / 2 deletions**. Phase 5 touched only `App.jsx` (+5, two routes) and `Sidebar.jsx` (+2, two nav entries).

### Database

**No new collections.** `hrms_candidates` and its six indexes were created in Phase 4, including the email and phone indexes duplicate detection needs.

---

## 5. APIs (7 new)

| Method | Route | Capability |
|---|---|---|
| GET | `/hrms/candidates` | `candidate.read` (row-scoped) |
| POST | `/hrms/candidates` | `candidate.write` |
| POST | `/hrms/candidates/screen` | `candidate.screen` |
| GET/PATCH/DELETE | `/hrms/candidates/{uk}` | read / `candidate.write` |
| GET | `/hrms/candidates/{uk}/journey` | `candidate.read` |

`/candidates/screen` is declared before `/candidates/{uk}`; a test proves the ordering by asserting the screening service is actually reached.

**Row scoping:** HR/MD/ADMIN see the whole company · INTERNAL sees all but **cannot screen** (a hiring decision belongs to the client — the same boundary Phase 3 drew for approvals) · MANAGER sees only candidates on requisitions **they raised** · EMPLOYEE gets 403.

---

## 6. Test results

| Suite | Checks | Result |
|---|---|---|
| `test_capability_parity` | 6 | ✅ |
| Phase 1 (foundation + integration) | 142 | ✅ |
| Phase 2 (employee + integration) | 178 | ✅ |
| Phase 3 (requisition + integration) | 167 | ✅ |
| Phase 4 (posting + **security**) | 169 | ✅ |
| `test_phase5_candidate` | **113** | ✅ |
| `test_phase5_integration` | **58** | ✅ |
| **Total** | **833** | ✅ **833/833** |

**Phase 5 coverage highlights:**
- Transition graph: every legal edge, 6 illegal jumps refused, all 3 terminal stages proven immovable, self-transitions impossible, unknown targets refused
- Row scoping: HOD sees only their own requisitions' candidates, **and their column counts match their scope**
- Out-of-scope and cross-tenant reads return **404, not 403**
- Duplicates: shared email flags *both* records; phone matches despite `+91` formatting; **nothing is merged or deleted**
- Screening: partial success with per-candidate reasons, bulk cap, missing-candidate handling, re-applying reported as already-there
- Forward assigns an owner **without** changing stage
- Journey: colours derive from the stage *arrived at*; a candidate with no audit rows still gets a start anchor
- Forged `uk` / `company_id` / `application_status` fields dropped by the schema

---

## 7. Smoke (S1) & Regression (S2)

| Check | Result |
|---|---|
| App boots; 10 HRMS collections; no new warnings | ✅ |
| `npm run build` | ✅ 4.15s |
| Lint — HRMS files | ✅ **0 errors** (7 warnings, pre-existing `icon: Icon` idiom) |
| Lint — whole `src` | ✅ 2 errors, both pre-existing (OOS-004) |
| Identity collections unpolluted | ✅ 0 |
| Shared-file diff | ✅ still 9 files; **no new shared dependencies** |
| Public apply surface still anonymous | ✅ |
| `/api/tasks`, `/api/users/me`, `/api/tpms/activities`, `/api/holidays` | ✅ still 401 |
| Phases 1–4 suites | ✅ all green |

---

## 8. Residual risk

| Risk | Severity | Note |
|---|---|---|
| Phase 4's blocking duplicate check does not normalise phones | **Medium** | Finding #1 — needs a stored normalised field + migration. **Recommended for Phase 15** |
| Duplicate flagging is per-result-page | Low | It compares within the loaded set (500 max). A company beyond that would need a server-side pass |
| No candidate merge | Low | Deliberate — flagging is advisory; merging is destructive and belongs behind an explicit workflow |
| No bulk CSV import | Low | Not in Phase 5 scope |
| Frontend has no automated tests | Medium | Your approved decision; the parity guard covers the highest-risk slice |

---

## 9. Completion checklist

- [x] All 13 development steps passed
- [x] 833/833 automated checks
- [x] Lifecycle graph enforced and exhaustively tested
- [x] Row scoping verified, including column counts
- [x] Zero new shared-file dependencies, zero new collections
- [x] `PHASE_5_REPORT.md` + `PHASE_5_TEST_SCRIPT.md`
- [ ] Git tag `hrms-phase-5` — *awaiting go-ahead; nothing committed or pushed*

---

## 10. Ready for Phase 6

Phase 6 (Assessments + dual review) plugs straight in:

- `requires_assessment` candidates already land in **Assessment Pending** via screening
- `ASSESSMENT_COMPLETED → {PASSED, FAILED}` edges are already declared and enforced
- The requisition raiser (Phase 3 `created_by`) is the manager-slot reviewer
- The journey renders assessment events with no change — it reads whatever is audited
- `ApprovalDialog` from Phase 3 is reusable for the Pass/Fail decision
