# HRMS Phase 8 — Offers & Public Offer Page · Phase Report

> **Status:** ✅ COMPLETE — all 13 steps passed
> **Scope:** offer letters, versioning, the public accept/decline page, and requisition auto-closure
> **Roadmap:** [HRMS_IMPLEMENTATION_ROADMAP.md](../HRMS_IMPLEMENTATION_ROADMAP.md) § Phase 8
> **Scope rule honoured:** HRMS only. No new out-of-scope findings; the register stands at OOS-001…005.

---

## 1. What shipped

| Capability | Delivered |
|---|---|
| Draft an offer | Gated to `Selected` candidates; one live offer each |
| Suggested CTC | JD → requisition → the candidate's own expectation |
| **Versioned editing** | Every draft edit archives the previous body and bumps the version |
| Send | Requires an authorised signatory; freezes the letter |
| Revoke | Withdraws a sent offer **and walks the candidate back to Selected** |
| Delete | Drafts only — a sent offer is part of the record |
| **Public offer page** | 128-bit code, formal letterhead, accept/decline, print-to-PDF |
| **Requisition auto-closure** | Module 16 — closes as Hired once vacancies are filled |
| CTC redaction | Omitted for anyone without `employee.salary.read` |

**3 new capabilities:** `offer.read`, `offer.write`, `offer.send`.

---

## 2. Design decisions worth recording

**Only a Draft is editable.** Once sent, the letter the candidate is reading must not change underneath them — that is the entire reason for versioning it instead. Edits after sending are a 409 telling the operator to revoke and re-issue. The UI reflects this rather than surprising anyone: the editor becomes a read-only preview.

**One `OfferPaper` component, two consumers.** The recruiter's preview and the public page render the *same* component. Two separate renderings would drift, and the one that drifts is the one somebody signs.

**CTC follows the salary boundary, not a new rule.** An offer is a compensation document, so `ctc` is **omitted** (not nulled) for a caller lacking `employee.salary.read` — reusing the Phase 2 capability rather than inventing a second concept. Archived versions in `history` are redacted too, which is the easy thing to forget.

**Accepting is signed; declining is not.** Acceptance forms an agreement, so it carries a typed signature. Demanding one from somebody walking away is friction with no purpose.

**A Draft is invisible publicly.** It has not been issued, so as far as the world is concerned it does not exist — same opaque 404 as an unknown code. A revoked offer returns **410 Gone**, which is honest with the candidate without revealing anything internal.

**Auto-closure never overrides a human.** `reconcile_requisition_closure` only touches an **Open** requisition. Hold, Cancel and Closed are human decisions and outrank arithmetic. Tested: a Hold requisition with its vacancy filled stays on Hold.

---

## 3. Findings

### Finding #1 — create-and-send could half-succeed ⚠️ **FIXED**

`create_offer` inserted the draft and *then* validated the signature when `send_now` was set. A missing signature returned 422 — but left an orphaned draft behind, which then blocked any retry with *"already has a live offer"*.

**Fix.** The signature is validated **before anything is written**. An operation that reports failure must not half-succeed — the same all-or-nothing rule applied to Phase 4's multi-platform publish. A test now asserts the collection is unchanged after a failed create-and-send.

### Finding #2 — revoking stranded the candidate ⚠️ **FIXED (lifecycle graph extended)**

Revoking a sent offer left the candidate at **`Offer Generated`**. That state then lied — no offer was outstanding — and worse, it was a dead end: raising revised terms requires `Selected`, and the Phase 5 graph had no edge back.

Found because a test tried the realistic sequence *offer → revoke → re-offer with revised terms* and hit a 409.

**Fix, in two parts:**
1. `OFFER_GENERATED → SELECTED` added to `FORWARD_TRANSITIONS`, commented as the revoke walk-back.
2. `revoke_offer` now moves the candidate back and audits the reason.

`Offer Declined` remains terminal — the candidate said no, and that is final.

This is the kind of gap that only surfaces when you test a *sequence* rather than an operation. The graph was correct for every forward path and wrong for the one path that goes backwards.

### Finding #3 — a capability escalation the tests caught

`POST /offers` with `send_now: true` performs a send. Gating the endpoint on `offer.write` alone would have let a drafter issue a binding letter by setting a flag. The route now requires **both** `offer.write` and `offer.send` when `send_now` is set, and the integration harness proves it by temporarily stripping `offer.send` from HR and asserting the flagged create is refused while a plain create still succeeds.

---

## 4. Files

### New — HRMS-owned (5)

| File | Purpose |
|---|---|
| `backend/app/services/hrms_offer_service.py` | Offers + Module 16 auto-closure |
| `backend/app/services/hrms/tests/test_phase8_offer.py` | Unit harness (99 checks) |
| `backend/app/services/hrms/tests/test_phase8_integration.py` | HTTP + public-security harness (78 checks) |
| `frontend/src/features/hrms/recruitment/OfferPaper.jsx` | The letterhead — shared by preview and public page |
| `frontend/src/features/hrms/recruitment/OfferBoard.jsx` | Board, create modal, versioned editor |
| `frontend/src/pages/hrms/public/OfferPage.jsx` | Public letter + accept/decline + print |

### Modified — shared (0 new)

Still **9 files, 208 insertions / 2 deletions**. Phase 8 touched only `App.jsx` (+4) and `Sidebar.jsx` (+1).

### Database

`hrms_offers` — 6 indexes: `uniq_offer_no`, **`uniq_access_code`**, `by_candidate`, `by_company_status`, `by_request`.

---

## 5. APIs (9 new)

| Method | Route | Gate |
|---|---|---|
| GET | `/hrms/offers` | `offer.read` (CTC redacted without salary read) |
| GET | `/hrms/offers/offerable` | `offer.write` |
| POST | `/hrms/offers` | `offer.write` **+ `offer.send` when `send_now`** |
| PATCH | `/hrms/offers/{no}` | `offer.write` (Draft only) |
| POST | `/hrms/offers/{no}/send` | `offer.send` |
| POST | `/hrms/offers/{no}/revoke` | `offer.send` |
| DELETE | `/hrms/offers/{no}` | `offer.write` (Draft only) |
| GET | `/hrms/public/offer/{code}` | **none — public** |
| POST | `/hrms/public/offer/{code}` | **none — public** |

Two new rate scopes: `offer-view` (40/min — a candidate re-reads terms) and `offer-respond` (10/hour — responded to once).

---

## 6. Test results

| Suite | Checks | Result |
|---|---|---|
| `test_capability_parity` | 6 | ✅ |
| Phases 1–7 | 1155 | ✅ |
| `test_phase8_offer` | **99** | ✅ |
| `test_phase8_integration` | **78** | ✅ |
| **Total** | **1338** | ✅ **1338/1338** |

**Phase 8 highlights:** the Selected gate · one-live-offer enforcement · 3-version edit history with pre-edit values preserved · send/revoke/delete lifecycle with every illegal transition refused · **CTC omitted for INTERNAL including inside `history`** · draft invisible publicly, revoked returns 410 · accept requires a signature, decline does not · **auto-closure arithmetic: a 1-vacancy requisition closes, a 2-vacancy one stays Open after one acceptance and closes after two, a Hold requisition never closes** · templating renders unknown placeholders harmlessly and survives a stray brace · 6 injection payloads blocked before the service · **86-route auth sweep still clean**.

---

## 7. Smoke (S1) & Regression (S2)

| Check | Result |
|---|---|
| Live DB — **13 collections**, `hrms_offers` with 6 indexes | ✅ |
| Identity collections unpolluted | ✅ 0 |
| `npm run build` | ✅ 2.78s |
| Lint — HRMS files | ✅ **0 errors** (8 warnings, pre-existing idiom) |
| Lint — whole `src` | ✅ 2 errors, both pre-existing (OOS-004) |
| Shared-file diff | ✅ still 9 files; no new shared dependencies |
| All three public surfaces still anonymous | ✅ |
| All 17 suites | ✅ 1338/1338 |

---

## 8. Residual risk

| Risk | Severity | Note |
|---|---|---|
| Offer letters are print-to-PDF, not server-generated | Medium | The roadmap defers server-side PDF; browser print works and is the documented interim |
| No offer expiry / reminder | Medium | A sent offer waits indefinitely. Needs a scheduler — carried with the Phase 6/7 reminder gap for Phase 15 |
| Candidate gets no emailed copy of the letter | Medium | Same shared-notification-attachment limitation flagged in Phase 7 §4 — **awaiting your approval** |
| `history` grows unbounded on a heavily-edited draft | Low | Bounded in practice by drafting effort; worth a cap if it ever matters |
| Frontend has no automated tests | Medium | Your approved decision |

---

## 9. Completion checklist

- [x] All 13 development steps passed
- [x] 1338/1338 automated checks
- [x] Versioning proven to preserve pre-edit values
- [x] CTC redaction verified including archived versions
- [x] Auto-closure arithmetic verified at 1-vacancy, 2-vacancy and Hold
- [x] Two real defects found and fixed (partial write, stranded candidate)
- [x] One capability escalation closed (`send_now`)
- [x] Zero new shared-file dependencies
- [x] `PHASE_8_REPORT.md` + `PHASE_8_TEST_SCRIPT.md`
- [ ] Git tag `hrms-phase-8` — *awaiting go-ahead; nothing committed or pushed*

---

## 10. Ready for Phase 9

Phase 9 (Onboarding) inherits an `Offer Accepted` pool:

- `OFFER_ACCEPTED → PRE_ONBOARDING → JOINED → EMPLOYEE_CREATED` is already declared and enforced
- The 128-bit access-code machinery serves a fourth public page
- `reconcile_requisition_closure` is already written and will be re-run when an Employee ID is minted
- Phase 2's employee master is the destination — Phase 9 is where recruitment finally becomes an employee record
