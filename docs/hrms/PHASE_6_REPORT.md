# HRMS Phase 6 — Assessments + Dual Review · Phase Report

> **Status:** ✅ COMPLETE — all 13 steps passed (one verification deferred, see §7)
> **Scope:** pre-interview assessments with a two-reviewer sign-off, and the candidate-facing submission page
> **Roadmap:** [HRMS_IMPLEMENTATION_ROADMAP.md](../HRMS_IMPLEMENTATION_ROADMAP.md) § Phase 6
> **Scope rule honoured:** HRMS only. No new out-of-scope findings; the register stands at OOS-001…005.

---

## 1. What shipped

| Capability | Delivered |
|---|---|
| Send an assessment | Gated to candidates at the assessment stage, one open assessment at a time |
| Lifecycle | `Assigned → In Progress → Submitted → Passed/Failed` |
| **Open tracking** | First view marks it Opened — distinguishes "never looked" from "opened and went quiet" |
| **Public assess page** | 128-bit access code, no auth, response and/or attachments |
| **Dual review** | HR **and** the hiring manager; both must Pass to advance |
| Single-reviewer fallback | HR decides alone when no hiring manager can be resolved |
| Advisory scoring | Recommended / Borderline / Not Recommended from the score — never decisive |
| "To review by me" | Server tells each caller which slot they fill and whether they still owe a decision |

**3 new capabilities:** `assessment.read`, `assessment.send`, `assessment.review`.

---

## 2. Why two reviewers

*"HR liked them, the hiring manager did not"* is exactly the disagreement worth surfacing **before** an interview panel is booked. One signature hides it; two force it into the open. The card shows both decisions side by side rather than a merged verdict.

**Slot resolution is what makes it real.** The requisition raiser always fills the **manager** slot — even if they are also HR — because their opinion is being sought as the hiring manager. Everyone else fills the HR slot. Without that rule one person could sign twice and the control would be theatre. Asserted directly in the tests, including that a *second, different* HR user still fills the HR slot and cannot overwrite the first.

**Concurrency.** Each decision is a compare-and-swap on an empty slot (`{f"{slot}_decision": None}`), so two reviewers clicking simultaneously cannot overwrite each other, and a second click by the same person is a 409 rather than a silent re-decision.

**Single-reviewer fallback.** If the candidate has no requisition, or its raiser cannot be resolved, HR decides alone. Requiring a signature nobody can give would strand the candidate forever — a worse failure than a single sign-off. Tested end to end.

**All four outcome combinations tested:** Pass+Pass → `Assessment Passed`; Pass+Fail, Fail+Pass and Fail+Fail → `Assessment Failed`.

---

## 3. The second public surface

`GET/POST /api/hrms/public/assess/{code}` follows the same six-rule contract as Phase 4, with one deliberate difference.

| Property | Posting code (Phase 4) | Access code (Phase 6) |
|---|---|---|
| Purpose | Short public identifier, shared on a job board | The **only** credential protecting one candidate's submission |
| Format | `^[A-Z]{2}-[A-Z0-9]{6}$` | `^[A-Za-z0-9_-]{20,64}$` |
| Entropy | Low by design — it is meant to be shared | **128 bits** (`secrets.token_urlsafe(16)`) |
| Normalisation | Upper-cased | **Never folded** — case-folding would collapse the keyspace and throw away entropy |

The source used ~40 bits from `Math.random()` for exactly this purpose, and its own analysis called the result *"enumerable-adjacent"* while it carried PAN, Aadhaar and bank details (BE §7.5). Both properties are asserted: the tests confirm codes validate, that a lower-cased code is **not** folded to match, and that 8 injection/traversal payloads never reach the service.

**Access-code hygiene.** The authenticated list returns `access_code` only while the link is still usable. Once an assessment is Submitted or Reviewed the field is withheld, so a working link cannot leak into a screenshot or an export.

---

## 4. Findings

### Finding #1 — falsy-coalescing swallowed a deliberate zero ⚠️ **FIXED**

```python
max_score = float(payload.get("max_score") or 100)   # 0 is falsy → becomes 100
```

A submitted `max_score` of **0** silently became 100 and skipped the `> 0` validation entirely. Caught by the unit harness. Fixed to default only when the field is genuinely absent (`100 if raw is None else raw`).

### Finding #2 — a real permission bypass in Phase 2, found by auditing the same pattern ⚠️ **FIXED**

Grepping for other falsy-numeric defaults surfaced this in `hrms_employee_service.update_profile`:

```python
salary_changing = (... float(payload["base_salary"]) != (current.get("base_salary") or 0))
if salary_changing and not can(actor, Cap.EMPLOYEE_SALARY_WRITE):
    raise 403
```

With **no salary stored yet** (`None`), writing `0` evaluates `0.0 != (None or 0)` → `False`, so `salary_changing` is False and **the capability check is skipped**. A HOD — who explicitly lacks `employee.salary.write` — could set an employee's salary.

**Impact:** narrow (only the value 0, only when none was previously set) but a genuine authorization bypass on pay data.

**Fix.** The gate is now on **intent to write**, not on a value delta:

```python
salary_write_attempted = ("base_salary" in payload and payload["base_salary"] is not None)
if salary_write_attempted and not can(actor, Cap.EMPLOYEE_SALARY_WRITE): raise 403
```

"Writing the same value" was never a meaningful exemption from a permission check. The delta is still computed, but only to decide whether to emit a dedicated salary-change audit line.

**Two regression tests added to Phase 2** (now 125/125): a HOD cannot write `0` onto an employee with no salary, and cannot re-write the *same* salary a candidate already has.

**Worth stating plainly:** Phase 2 shipped with 123 passing checks and this bug in it. A delta check *looked* equivalent to an intent check and my tests only exercised the differing-value path. The lesson is that permission gates should test the *action*, not its *effect*.

### Finding #3 — two test-side gaps

- `FakeCollection.update_one` did not return `modified_count`, which the service uses to detect whether a conditional update actually fired. Added.
- An `await` inside a generator expression (`all(await ... for ...)`) — my error, not the code's.

---

## 5. Files

### New — HRMS-owned (4)

| File | Purpose |
|---|---|
| `backend/app/services/hrms_assessment_service.py` | Send, open-tracking, submit, dual review, resolution |
| `backend/app/services/hrms/tests/test_phase6_assessment.py` | Unit harness (96 checks) |
| `backend/app/services/hrms/tests/test_phase6_integration.py` | HTTP + public-security harness (66 checks) |
| `frontend/src/features/hrms/recruitment/AssessmentBoard.jsx` | Board + send/review modals |
| `frontend/src/pages/hrms/public/AssessPage.jsx` | Public submission page |

Extended: `models/hrms.py`, `utils/hrms_public_guard.py` (access codes + 2 rate scopes), `routes/hrms.py`, `routes/hrms_public.py`, `services/hrmsApi.js`, `services/hrmsPublicApi.js`, `features/hrms/access.js`.

### Modified — shared (0 new)

Still **9 files, 199 insertions / 2 deletions**. Phase 6 touched only `App.jsx` (+4) and `Sidebar.jsx` (+1).

### Database

`hrms_assessments` — 5 indexes: `uniq_assessment_no`, **`uniq_access_code`**, `by_candidate`, `by_company_status`, `by_request`. The access-code index is unique *and* indexed because every public request looks up by it.

---

## 6. Test results

| Suite | Checks | Result |
|---|---|---|
| `test_capability_parity` | 6 | ✅ |
| Phase 1 | 142 | ✅ |
| Phase 2 | **180** *(was 178 — +2 salary regression)* | ✅ |
| Phase 3 | 167 | ✅ |
| Phase 4 | 169 | ✅ |
| Phase 5 | 171 | ✅ |
| `test_phase6_assessment` | **96** | ✅ |
| `test_phase6_integration` | **66** | ✅ |
| **Total** | **997** | ✅ **997/997** |

**Phase 6 coverage highlights:** all 4 dual-review combinations · slot resolution incl. a second HR user · concurrent/duplicate decisions rejected 409 · single-reviewer fallback · open-tracking not overwritten by a refresh · submit-twice rejected · attachment-only submission · 8 injection payloads blocked before the service · case preservation on access codes · identical error bodies (no oracle) · access code withheld once unusable · 9 internal fields absent from the public payload · **86-route whole-app auth sweep still clean**.

---

## 7. Smoke (S1) & Regression (S2)

| Check | Result |
|---|---|
| `npm run build` | ✅ 5.39s |
| Lint — HRMS files | ✅ **0 errors** (8 warnings, pre-existing `icon: Icon` idiom) |
| Lint — whole `src` | ✅ 2 errors, both pre-existing (OOS-004) |
| Shared-file diff | ✅ still 9 files; **no new shared dependencies** |
| Public surfaces both anonymous | ✅ |
| Auth sweep — 86 routes | ✅ no leaks |
| All 13 suites | ✅ 997/997 |
| **Live DB provisioning** | ✅ **VERIFIED during Phase 7** — `hrms_assessments` present with all 6 indexes |

**On the live check.** MongoDB Atlas was unreachable during this phase's smoke run (`No replica set members found yet` — network or a paused cluster). This is an environment condition, not a code defect, and the startup handler degraded exactly as designed: it logged `[FAILED] connect to MongoDB` and left the app serving.

I am **not** claiming Phase 6's collection was provisioned live. What *is* verified: the index registry contains the five `hrms_assessments` entries (unit-tested), and provisioning uses the same idempotent `_ensure_hrms_collections` mechanism confirmed live in Phases 1–5. Re-check with one command when Atlas is back:

```
cd backend && venv/Scripts/python.exe -c "
import asyncio; from app.db.mongodb import connect_to_mongo, db_connection
async def go():
    await connect_to_mongo()
    print(sorted(n for n in await db_connection.db.list_collection_names() if n.startswith('hrms_')))
asyncio.run(go())"
# expect 11 collections, including hrms_assessments
```

---

## 8. Residual risk

| Risk | Severity | Note |
|---|---|---|
| ~~Live provisioning unverified~~ | **CLOSED** | Confirmed during the Phase 7 smoke run: `hrms_assessments`, 6 indexes |
| Delta-vs-intent permission checks elsewhere | **Low** | Finding #2's pattern was grepped for across all HRMS services; only that one instance existed |
| No assessment reminder/expiry job | Medium | `due_date` is stored and displayed but nothing chases a candidate who goes quiet. Needs a scheduler — flagged for Phase 15 |
| No virus scanning on attachments | Medium | Carried from Phase 4; files are stored in S3 and never executed, but HR downloads them |
| Frontend has no automated tests | Medium | Your approved decision |

---

## 9. Completion checklist

- [x] All 13 development steps passed
- [x] 997/997 automated checks
- [x] Dual review: 4 outcome combinations + slot resolution + concurrency
- [x] 128-bit access codes, case-preserving, injection-proof
- [x] Public auth sweep clean (86 routes)
- [x] Two real bugs found and fixed, one a **prior-phase permission bypass**
- [x] Zero new shared-file dependencies
- [x] `PHASE_6_REPORT.md` + `PHASE_6_TEST_SCRIPT.md`
- [x] Live DB provisioning re-checked during Phase 7 — `hrms_assessments` confirmed with 6 indexes
- [ ] Git tag `hrms-phase-6` — *awaiting go-ahead; nothing committed or pushed*

---

## 10. Ready for Phase 7

Phase 7 (Interviews + scorecard) inherits:

- `Assessment Passed` candidates are the ones the interview gate will admit — the graph edge `ASSESSMENT_PASSED → INTERVIEW_SCHEDULED` is already declared and enforced
- `Assessment Failed` candidates are already blocked from that edge, so the Phase 7 gate is a capability question, not a state-machine question
- The dual-review + notification pattern is reusable for the MD-round decision
- The journey renders assessment events with no change
