# HRMS Phase 7 — Interviews & Scorecard Evaluation · Phase Report

> **Status:** ✅ COMPLETE — all 13 steps passed
> **Scope:** interview scheduling, the assessment gate, structured scorecards, and the decision chain to Selected
> **Roadmap:** [HRMS_IMPLEMENTATION_ROADMAP.md](../HRMS_IMPLEMENTATION_ROADMAP.md) § Phase 7
> **Scope rule honoured:** HRMS only. No new out-of-scope findings; the register stands at OOS-001…005.

---

## 1. What shipped

| Capability | Delivered |
|---|---|
| Schedule | Virtual (link) or in-person (location), 4 round types, 15-minute steps |
| **Assessment gate** | An assessment-required candidate cannot be booked until `Assessment Passed` |
| Day-grouped board | Today / Tomorrow / weekday headers, because "what's happening today" is the question |
| Reschedule | Bumps the calendar sequence so clients treat it as an update, not a second booking |
| Cancel / No Show | Marked, never deleted — a dropped round is part of the hiring record |
| **Scorecard** | 6 competencies 0–5, decision, remarks, **required typed signature** |
| **PASS_NEXT chain** | HR → Technical → MD → **Selected**, with Fail → Rejected and Hold → On Hold |
| MD-round restriction | Only `interview.decide_md` may make the final call |
| **`.ics` invite** | RFC 5545, UTC-stamped, downloadable per interview |

**4 new capabilities:** `interview.read`, `interview.schedule`, `interview.evaluate`, `interview.decide_md`.

---

## 2. Two independent checks on every advance

`PASS_NEXT` says where a passed round *intends* to send a candidate. The Phase 5 lifecycle graph says whether that move is *legal* from where they actually are. **Both must agree.**

A single trusted table would let a stale round type push a candidate somewhere the lifecycle forbids. When the two disagree the service leaves the stage alone and writes an audit line explaining why, rather than forcing an illegal write or silently doing nothing.

Verified up front that every `PASS_NEXT` edge is already a legal graph edge — so the two mechanisms agree by construction, and a test asserts it stays that way.

**The assessment gate is largely free.** Phase 5 already declared `ASSESSMENT_PASSED → INTERVIEW_SCHEDULED` legal while `ASSESSMENT_PENDING` and `ASSESSMENT_FAILED` are not. Phase 7 adds an explicit, well-worded 409 on top so the operator sees *why*, but the underlying protection was already structural.

**Enforced twice on purpose:** the candidate picker filters to schedulable candidates, and the scheduler re-checks. The picker is a convenience; the endpoint is the boundary.

---

## 3. Design decisions worth recording

**Listing your own interviews is an inherent right, not a capability.** An interviewer who cannot open the booking they were assigned cannot do the job, and that must not be revocable by a permission edit. `GET /interviews` is therefore **not** gated — `interview.read` only *widens* the result to the whole company. Same reasoning as `/employees/me` in Phase 2.

**EMPLOYEE holds `interview.evaluate`.** Anyone can be booked as an interviewer, so anyone must be able to score. Row scoping — not the capability — restricts them to their own interviews. Withholding the capability would have made an employee interviewer useless.

**MD-round restriction is independent of who conducted it.** Even the assigned interviewer cannot record an MD-round decision without `interview.decide_md`. Tested directly: an HOD who *is* the interviewer, and *can* see the interview, still gets a 403.

**Round, candidate and interviewer are immutable after booking.** `InterviewUpdate` deliberately omits them — changing who is being interviewed, or for what, would make an existing scorecard meaningless. Cancel and re-book instead. A test asserts those fields are dropped from a PATCH.

**Completed requires a scorecard.** Marking an interview Completed with no evaluation would leave the candidate stranded mid-chain with no record of why. `No Show` remains available without one, which is the legitimate case.

**Cancel bumps the calendar sequence.** A calendar client only withdraws an entry when it sees a higher `SEQUENCE` with `METHOD:CANCEL` — otherwise the stale booking sits in everyone's diary.

---

## 4. The `.ics` builder

`services/hrms_ics.py` is pure text generation — no I/O, no clock, no DB — so it is trivially testable.

- **Times are emitted in UTC with `Z`.** The one form every client resolves identically; naive input is assumed IST (matching the rest of the ERP) and converted. Verified: IST 14:30 → `20260820T090000Z`.
- **RFC 5545 escaping** for `\`, `;`, `,` and newlines, backslash first so the others aren't double-escaped.
- **Line folding on octets, not characters**, so a multi-byte character is never split across a boundary.
- **CRLF endings**, which are mandatory — LF-only breaks strict parsers.
- No new dependency: a single VEVENT is ~40 lines of well-specified text.

### ⚠️ Limitation you should know about — invites are downloaded, not emailed

The shared `notification_service` has **no attachment channel**. Adding one means editing a module outside HRMS, which the scope rule forbids without approval.

**What I built instead:** `GET /hrms/interviews/{no}/invite.ics` serves the invite as a file, linked from every interview card. Notifications carry the date, time, duration and link/location in the message body.

This is arguably *better* for the interviewer — a link stays correct after a reschedule, whereas a mailed `.ics` goes stale — but it means **the candidate does not receive a calendar attachment**, only the details in text.

**Recommendation:** add an `attachments` parameter to `notification_service.send_email_notification`. It is additive and low-risk, but it is your call. Until then, the candidate-facing gap is real and documented.

---

## 5. Files

### New — HRMS-owned (4)

| File | Purpose |
|---|---|
| `backend/app/services/hrms_ics.py` | RFC 5545 invite builder (pure) |
| `backend/app/services/hrms_interview_service.py` | Schedule, gate, evaluate, advance |
| `backend/app/services/hrms/tests/test_phase7_interview.py` | Unit harness (98 checks) |
| `backend/app/services/hrms/tests/test_phase7_integration.py` | HTTP harness (66 checks) |
| `frontend/src/features/hrms/recruitment/InterviewBoard.jsx` | Day-grouped board + both modals |

### Modified — shared (0 new)

Still **9 files, 203 insertions / 2 deletions**. Phase 7 touched only `App.jsx` (+2) and `Sidebar.jsx` (+1).

### Database

`hrms_interviews` — 6 indexes: `uniq_interview_no`, `by_candidate`, `by_company_status`, **`by_company_when`** (the day-grouped feed sorts on it), **`by_interviewer`** (a non-privileged user's default view).

---

## 6. APIs (7 new)

| Method | Route | Gate |
|---|---|---|
| GET | `/hrms/interviews` | **none** — row-scoped; `interview.read` widens |
| GET | `/hrms/interviews/schedulable` | `interview.schedule` |
| POST | `/hrms/interviews` | `interview.schedule` |
| PATCH | `/hrms/interviews/{no}` | scheduler **or** the assigned interviewer |
| DELETE | `/hrms/interviews/{no}` | `interview.schedule` |
| POST | `/hrms/interviews/{no}/evaluate` | interviewer or `interview.evaluate`; MD round needs `interview.decide_md` |
| GET | `/hrms/interviews/{no}/invite.ics` | same visibility check as reading it |

`/schedulable` is declared before `/{interview_no}`; a test proves the ordering.

---

## 7. Test results

| Suite | Checks | Result |
|---|---|---|
| `test_capability_parity` | 6 | ✅ |
| Phase 1 | 142 | ✅ |
| Phase 2 | 180 | ✅ |
| Phase 3 | 167 | ✅ |
| Phase 4 | 169 | ✅ |
| Phase 5 | 171 | ✅ |
| Phase 6 | 162 | ✅ |
| `test_phase7_interview` | **98** | ✅ |
| `test_phase7_integration` | **66** | ✅ |
| **Total** | **1161** | ✅ **1161/1161** |

**Phase 7 highlights:** the full HR→Technical→MD→Selected chain walked end to end · Manager Round also routing to MD · Fail→Rejected and Hold→On Hold · the assessment gate blocking Pending *and* Failed while allowing Passed · 12 scheduling-validation cases · MD restriction proven against an assigned interviewer who can see the interview · employee row scoping (sees exactly their own) · reschedule sequence bump · cancel marked not deleted · double-evaluation 409 · `.ics` structure, CRLF, UTC, attendees, and `METHOD:CANCEL` on a cancelled booking · **PASS_NEXT re-checked against the lifecycle graph**.

---

## 8. Smoke (S1) & Regression (S2)

| Check | Result |
|---|---|
| Live DB — **12 collections**, `hrms_interviews` with 6 indexes | ✅ |
| **Phase 6's deferred check now closed** — `hrms_assessments` present, 6 indexes | ✅ |
| Identity collections unpolluted | ✅ 0 |
| `npm run build` | ✅ 4.32s |
| Lint — HRMS files | ✅ **0 errors** (8 warnings, pre-existing idiom) |
| Lint — whole `src` | ✅ 2 errors, both pre-existing (OOS-004) |
| Shared-file diff | ✅ still 9 files; no new shared dependencies |
| Both public surfaces still anonymous | ✅ |
| Auth sweep | ✅ no leaks |
| All 15 suites | ✅ 1161/1161 |

---

## 9. Residual risk

| Risk | Severity | Note |
|---|---|---|
| Candidate receives no `.ics` attachment | **Medium** | §4 — needs an additive change to the shared notification service; **awaiting your approval** |
| No interview reminder job | Medium | Carried from Phase 6 — the ERP has a reminder scheduler, but wiring HRMS into it touches shared code. Flagged for Phase 15 |
| No double-booking check for an interviewer | Low | Two interviews can be booked in the same slot for the same person. Worth adding; not in the roadmap's Phase 7 scope |
| Frontend has no automated tests | Medium | Your approved decision |

---

## 10. Completion checklist

- [x] All 13 development steps passed
- [x] 1161/1161 automated checks
- [x] Assessment gate enforced in the picker **and** at the boundary
- [x] Full PASS_NEXT chain verified, cross-checked against the lifecycle graph
- [x] MD-round restriction proven independent of who conducted the interview
- [x] `.ics` verified for UTC conversion, escaping, folding, CRLF and cancellation
- [x] Phase 6's deferred live-DB check closed
- [x] Zero new shared-file dependencies
- [x] `PHASE_7_REPORT.md` + `PHASE_7_TEST_SCRIPT.md`
- [ ] Git tag `hrms-phase-7` — *awaiting go-ahead; nothing committed or pushed*

---

## 11. Ready for Phase 8

Phase 8 (Offers) inherits a populated `Selected` pool:

- `MD Round → Selected` is now reachable end to end
- `SELECTED → OFFER_GENERATED → OFFER_ACCEPTED/DECLINED` edges are already declared in the Phase 5 graph
- The 128-bit access-code machinery from Phase 6 is reusable for the public offer link
- The audit trail already records every round and outcome, which the offer letter and the journey both read
