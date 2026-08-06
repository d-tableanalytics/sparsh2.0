# HRMS Phase 6 — Manual Test Script

> Assessments with dual review, and the public submission page.
>
> **Prerequisites:** a posting created with **Requires assessment** ON, at least two
> applicants through it, and a requisition whose **raiser is the HOD account**. Accounts:
> **HR**, a second **HR2**, **HOD** (the raiser), plain **clientuser**, **staff admin**.

## Automated suites (all thirteen must be green)

```
cd backend
for t in test_capability_parity \
         test_phase1_foundation test_phase1_integration \
         test_phase2_employee test_phase2_integration \
         test_phase3_requisition test_phase3_integration \
         test_phase4_posting test_phase4_public_security \
         test_phase5_candidate test_phase5_integration \
         test_phase6_assessment test_phase6_integration; do
  venv/Scripts/python.exe -m app.services.hrms.tests.$t
done
# expect 6/96/46/125/55/108/59/118/51/113/58/96/66 = 997
```

---

## A. Sending

| # | Step | Expected |
|---|---|---|
| A1 | HRMS → Assessments → **Send** | Candidate dropdown lists only assessment-required candidates at the assessment stage |
| A2 | Check the dropdown | A candidate already in interviews is **absent** |
| A3 | Check a non-assessment role | **Absent** — those go screening → interviews directly |
| A4 | Send with a title | Created, card shows **Assigned** |
| A5 | Re-open the dropdown | That candidate is now **gone** (one open assessment at a time) |
| A6 | Try to send again via API | **409** — *"already has an open assessment"* |
| A7 | Set Max score to **0** | **422** — must be greater than zero *(this was a real bug: 0 used to become 100)* |
| A8 | External link `test.com` | **422** — must start with http:// or https:// |
| A9 | Check the candidate's stage | Moved to **Assessment Pending** |

## B. The candidate's link

| # | Step | Expected |
|---|---|---|
| B1 | Copy the link from the card | Format `…/assess/<22-char code>` |
| B2 | Inspect the code | Mixed case, letters/digits/`-`/`_` — **not** the short `XX-XXXXXX` posting format |
| B3 | Open it in **incognito** (no login) | Assessment renders — never a login redirect |
| B4 | Back in HRMS, refresh the board | Card now reads **In Progress** |
| B5 | Reload the candidate page, check `opened_at` in the DB | **Unchanged** — a refresh does not rewrite the first-view time |
| B6 | Lower-case one character of the code and open it | **404** — codes are case-sensitive |
| B7 | Try `/assess/short` and `/assess/{$ne:null}` | Both **404**, byte-identical message |

## C. Candidate submission

| # | Step | Expected |
|---|---|---|
| C1 | Submit with neither text nor files | Blocked — *"Add your response, or attach at least one file"* |
| C2 | Submit with text only | Accepted, celebration screen |
| C3 | Revisit the link | Calm *"Already submitted"* — **not** an error |
| C4 | Try to submit again via API | **409** |
| C5 | On a fresh assessment, attach 11 files | Blocked at 10 |
| C6 | Attach a 20 MB file | Blocked — 15 MB limit |
| C7 | Attach-only submission (no text) | Accepted |
| C8 | Board after submission | Card reads **Submitted** |
| C9 | Candidate stage | **Assessment Completed** |
| C10 | HR bell **and** the HOD's bell | Both notified |

## D. Dual review — the core of this phase

| # | Step | Expected |
|---|---|---|
| D1 | As **HR**, open the submitted card → **Review** | Modal shows the response, attachments, and *Hiring manager: Pending* |
| D2 | Record **Pass** with score 85 | Toast; card still reads **Submitted**, not Passed |
| D3 | Check the candidate | Still **Assessment Completed** — one decision does not advance them |
| D4 | HOD's bell | *"needs your decision"* |
| D5 | As **HR2** (different HR user), try to review | **409** — the HR slot is already filled |
| D6 | As **HR** again, try to review | **409** — no silent re-decision |
| D7 | As **HOD**, open the card | Modal shows *HR: Pass* with their remark |
| D8 | Record **Pass** | Card becomes **Passed** |
| D9 | Candidate stage | **Assessment Passed** |
| D10 | Both bells | Both reviewers hear the outcome |
| D11 | Try to review again | **409** — already fully reviewed |

## D-bis. The other three combinations

| # | HR | Manager | Expected candidate stage |
|---|---|---|---|
| D12 | Pass | Fail | **Assessment Failed** |
| D13 | Fail | Pass | **Assessment Failed** |
| D14 | Fail | Fail | **Assessment Failed** |
| D15 | For each | | Card reads **Failed**; both reviewers notified |

## D-ter. Single-reviewer fallback

| # | Step | Expected |
|---|---|---|
| D16 | Manually add a candidate with **no requisition**, flag `requires_assessment`, send an assessment | Created |
| D17 | Candidate submits; **HR** records Pass | Immediately **Reviewed** — no manager exists to wait for |
| D18 | Candidate stage | **Assessment Passed** on the single decision |

## E. Scoring hint

| # | Step | Expected |
|---|---|---|
| E1 | Enter score 85 / 100 | Suggests **Recommended** |
| E2 | Enter 55 | **Borderline** |
| E3 | Enter 20 | **Not Recommended** |
| E4 | Read the caption | States the suggestion is **advisory only** |
| E5 | Record **Fail** on a 90-scoring submission | Accepted — the score never overrides the human |
| E6 | Enter a score above max | **422** |

## F. Permissions

| # | Role | Check | Expected |
|---|---|---|---|
| F1 | **HOD** | Assessments page | Visible; **no Send button** |
| F2 | **HOD** | Review a submission they manage | Works — they are the manager slot |
| F3 | **HOD** | `POST /api/hrms/assessments` | **403** |
| F4 | **plain clientuser** | Assessments | API **403** |
| F5 | **staff admin** | Send | Works |
| F6 | **staff admin** | Review | **403** — reviewing is a hiring decision |
| F7 | **HR** | Everything | Full access |
| F8 | Any role | "To review by me" filter | Shows only cards where **that user** still owes a decision |

## G. Access-code hygiene

| # | Step | Expected |
|---|---|---|
| G1 | DevTools → `GET /api/hrms/assessments` for an **Assigned** card | `access_code` **present** (link still usable) |
| G2 | Same for a **Submitted** or **Reviewed** card | `access_code` **absent** |
| G3 | Public `GET /api/hrms/public/assess/<code>` payload | **No** `company_id`, `uk`, `manager_id`, `hr_decision`, `score`, `access_code` |

## H. States & theming

| # | Step | Expected |
|---|---|---|
| H1 | Slow 3G on the public page | Spinner + *"Loading your assessment…"* |
| H2 | Invalid code | *"Link unavailable"* card, nothing internal revealed |
| H3 | Light ⇄ dark on the board | Re-themes (the public page is intentionally light-only standalone chrome) |
| H4 | 375 / 768 / 1440 px | Both pages usable; no sideways page scroll |
| H5 | Console | **Zero errors** |

## I. Regression

| # | Module | Expected |
|---|---|---|
| I1–I5 | Task Management · Calendar · TPMS · ORM · Reports | All work |
| I6 | HRMS Employees / Requisitions / JDs / Postings / Candidates / Screening | All work |
| I7 | **Public apply link** (incognito) | Still works, still anonymous |
| I8 | Console | No new errors |

## J. Database

| # | Check | Expected |
|---|---|---|
| J1 | Collections | **11** — `hrms_assessments` added *(re-run after Atlas is reachable; see PHASE_6_REPORT §7)* |
| J2 | `hrms_assessments` indexes | `uniq_assessment_no`, `uniq_access_code`, `by_candidate`, `by_company_status`, `by_request` |
| J3 | After a full review | Audit rows: `assessment sent`, `assessment opened`, `assessment submitted`, `assessment reviewed` ×2, `assessment outcome` |
| J4 | Candidate journey | Shows the assessment events inline with the rest of the history |
| J5 | `staff` / `learners` | **0** documents with `access_code` or `hr_decision` |

---

## Sign-off

- [ ] All thirteen automated suites green (**997**)
- [ ] Sections A–J pass
- [ ] **D5/D6 verified** — no reviewer can fill a slot twice or overwrite another
- [ ] **D12–D14 verified** — any Fail means Failed
- [ ] **D16–D18 verified** — single-reviewer fallback does not strand a candidate
- [ ] **B6 verified** — access codes are case-sensitive
- [ ] **G1/G2 verified** — access code withheld once the link is unusable
- [ ] No console errors; no backend 5xx

**Tester:** ______________  **Date:** ______________  **Result:** PASS / FAIL
