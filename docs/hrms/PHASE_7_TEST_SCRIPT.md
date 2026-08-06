# HRMS Phase 7 — Manual Test Script

> Interviews, the assessment gate, scorecards and the decision chain.
>
> **Prerequisites:** candidates at several stages — one **Shortlisted** with no assessment
> requirement, one **Assessment Pending**, one **Assessment Failed**, one
> **Assessment Passed**. Accounts: **HR**, **HOD**, **MD** (clientadmin or governance MD),
> a plain **clientuser** who will be booked as an interviewer, and a **staff admin**.

## Automated suites (all fifteen must be green)

```
cd backend
for t in test_capability_parity \
         test_phase1_foundation test_phase1_integration \
         test_phase2_employee test_phase2_integration \
         test_phase3_requisition test_phase3_integration \
         test_phase4_posting test_phase4_public_security \
         test_phase5_candidate test_phase5_integration \
         test_phase6_assessment test_phase6_integration \
         test_phase7_interview test_phase7_integration; do
  venv/Scripts/python.exe -m app.services.hrms.tests.$t
done
# expect 6/96/46/125/55/108/59/118/51/113/58/96/66/98/66 = 1161
```

---

## A. The assessment gate — the headline behaviour

| # | Step | Expected |
|---|---|---|
| A1 | HRMS → Interviews → **Schedule**, open the candidate list | Only schedulable candidates appear |
| A2 | Look for the **Assessment Pending** candidate | **Absent** |
| A3 | Look for the **Assessment Failed** candidate | **Absent** |
| A4 | Look for the **Assessment Passed** candidate | **Present** |
| A5 | Look for the Shortlisted no-assessment candidate | **Present** — no assessment required, so no gate |
| A6 | Read the empty-state text when nothing is schedulable | Explains the Assessment Passed requirement |
| A7 | Force it via API: `POST /api/hrms/interviews` with the Pending candidate | **409** naming the stage they are actually at |

## B. Scheduling

| # | Step | Expected |
|---|---|---|
| B1 | Schedule a **Virtual** HR Round with a meeting link | Created; card appears under the right day header |
| B2 | Leave the meeting link empty | **422** — *"needs a meeting link"* |
| B3 | Meeting link `meet.example/x` (no scheme) | **422** |
| B4 | Switch to **In person**, leave location empty | **422** — *"needs a location"* |
| B5 | Pick a date in the past | **422** — *"cannot be scheduled in the past"* |
| B6 | Duration 10 | **422** — minimum 15 |
| B7 | Duration 20 | **422** — 15-minute steps |
| B8 | No interviewer | Submit disabled |
| B9 | After scheduling, check the candidate | Stage is **Interview Scheduled** |
| B10 | Interviewer's notification bell | Notified, with date/time and the link |

## C. The board

| # | Step | Expected |
|---|---|---|
| C1 | Look at the day headers | **Today** / **Tomorrow** / weekday + date |
| C2 | Stat tiles | Today · Upcoming · Completed · Cancelled/No show |
| C3 | Filter by round | Filters correctly |
| C4 | Filter by status | Filters correctly |
| C5 | A Virtual interview that is Scheduled | Shows a **Join** button |
| C6 | An in-person interview | Shows the location, no Join |
| C7 | Empty state | Sensible guidance for schedulers vs. interviewers |

## D. The pass chain — walk it end to end

Use one candidate throughout.

| # | Step | Expected candidate stage |
|---|---|---|
| D1 | Schedule **HR Round**, evaluate → **Pass** | **Technical Round** |
| D2 | Schedule **Technical**, evaluate → **Pass** | **MD Round** |
| D3 | Schedule **MD Round** with the **MD** as interviewer | — |
| D4 | As **HR**, try to evaluate it | **403** — *"Only the MD"* |
| D5 | As the **MD**, evaluate → **Approve** | **Selected** |
| D6 | Check the candidate journey | Every round and outcome appears in order |

## D-bis. The other outcomes

| # | Step | Expected |
|---|---|---|
| D7 | On a fresh candidate, evaluate a round → **Fail** | Candidate **Rejected** |
| D8 | On another, evaluate → **Hold** | Candidate **On Hold** |
| D9 | Schedule a **Manager Round** and pass it | Candidate **MD Round** |

## E. The scorecard

| # | Step | Expected |
|---|---|---|
| E1 | Open **Evaluate** | Six competencies with 1–5 stars |
| E2 | Click a star, then click the same star again | Resets to 0 — a mis-click is undoable |
| E3 | Submit with no decision | Button disabled |
| E4 | Submit with no signature | Button disabled; API returns **422** if forced |
| E5 | Read the signature caption | Explains the evaluation is recorded against your name |
| E6 | Submit a valid scorecard | Interview becomes **Completed**, shows the outcome and an average |
| E7 | Try to evaluate again | **409** — *"already been evaluated"* |
| E8 | On an **MD Round**, check the heading | Reads *"MD interview decision"*, buttons say **Approve / Reject** |

## F. Reschedule, No Show, cancel

| # | Step | Expected |
|---|---|---|
| F1 | Reschedule to a later date | Moves; interviewer re-notified with *"rescheduled"* |
| F2 | Download the `.ics` again | `SEQUENCE` has increased — a client treats it as an update |
| F3 | Reschedule into the past | **422** |
| F4 | Mark **No Show** on a scheduled interview | Allowed with no scorecard |
| F5 | Force `status: Completed` via API with no scorecard | **409** — *"Record the evaluation"* |
| F6 | **Cancel** an interview | Confirmed; status **Cancelled** |
| F7 | Check the DB | The row still exists — cancelled, **not deleted** |
| F8 | Cancel again | **409** |
| F9 | Try to evaluate a cancelled interview | **409** |

## G. Calendar invite

| # | Step | Expected |
|---|---|---|
| G1 | Click the download icon on a card | `INT-….ics` downloads |
| G2 | Open it in a text editor | `BEGIN:VCALENDAR`, one `VEVENT`, `METHOD:REQUEST` |
| G3 | Check `DTSTART` | Ends in `Z` (UTC) and matches the local time you booked |
| G4 | Check attendees | Two — interviewer and candidate |
| G5 | Import into Outlook / Google Calendar | Event appears at the correct local time |
| G6 | Download the `.ics` for a **cancelled** interview | `METHOD:CANCEL` and `STATUS:CANCELLED` |
| G7 | Import it | The calendar entry is **removed** |
| G8 | Note the known gap | The **candidate receives no attachment** — details are in the email text only (PHASE_7_REPORT §4) |

## H. Permissions

| # | Role | Check | Expected |
|---|---|---|---|
| H1 | **plain clientuser** booked as an interviewer | Open Interviews | Sees **only** their own interviews |
| H2 | Same user | Evaluate their own | Works |
| H3 | Same user | Schedule button | **Absent**; API **403** |
| H4 | Same user | Another interview by URL/API | **404** — not 403 |
| H5 | **HOD** | Schedule | **403** |
| H6 | **HOD** | Evaluate a non-MD round | Works |
| H7 | **HOD** as the assigned interviewer on an **MD Round** | Evaluate | **403** — *"Only the MD"* |
| H8 | **staff admin** | Schedule | Works |
| H9 | **staff admin** | Evaluate | **403** — a hiring decision |
| H10 | **HR** | Everything except MD-round decisions | Works |
| H11 | **MD** | MD-round decision | Works |

## I. States & theming

| # | Step | Expected |
|---|---|---|
| I1 | Slow 3G | *"Loading interviews…"* |
| I2 | Stop backend, reload | Error panel + **Try again** |
| I3 | Light ⇄ dark | Re-themes |
| I4 | 375 / 768 / 1440 px | Cards reflow; no sideways page scroll |
| I5 | Console | **Zero errors** |

## J. Regression

| # | Module | Expected |
|---|---|---|
| J1–J5 | Task Management · Calendar · TPMS · ORM · Reports | All work |
| J6 | HRMS Employees / Requisitions / JDs / Postings / Candidates / Screening / Assessments | All work |
| J7 | Public apply **and** public assess (incognito) | Both work, both anonymous |
| J8 | Console | No new errors |

## K. Database

| # | Check | Expected |
|---|---|---|
| K1 | Collections | **12** — `hrms_interviews` added |
| K2 | `hrms_interviews` indexes | `uniq_interview_no`, `by_candidate`, `by_company_status`, `by_company_when`, `by_interviewer` |
| K3 | After a full chain | Audit rows: `interview scheduled` ×3, `interview evaluated` ×3, `stage changed` ×3 |
| K4 | After a cancel | `interview cancelled` row; interview row still present |
| K5 | `staff` / `learners` | **0** documents with `interview_no` or `outcome` |

---

## Sign-off

- [ ] All fifteen automated suites green (**1161**)
- [ ] Sections A–K pass
- [ ] **A2/A3/A7 verified** — the assessment gate blocks in the picker *and* at the API
- [ ] **D1–D5 verified** — the full chain reaches Selected
- [ ] **H7 verified** — even the assigned interviewer cannot decide an MD round
- [ ] **G5/G7 verified** — invites import and cancellations withdraw in a real calendar
- [ ] **F7 verified** — a cancelled interview is retained, not deleted
- [ ] No console errors; no backend 5xx

**Tester:** ______________  **Date:** ______________  **Result:** PASS / FAIL
