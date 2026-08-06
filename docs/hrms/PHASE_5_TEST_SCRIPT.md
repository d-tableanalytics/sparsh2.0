# HRMS Phase 5 — Manual Test Script

> Candidate pipeline, screening and journey.
>
> **Prerequisites:** HRMS enabled for Company A with a **Live posting** and at least
> 3–4 applications submitted through it (Phase 4). Accounts: **HR**, **HOD** *(who must have
> raised at least one requisition)*, plain **clientuser**, **staff admin**.

## Automated suites (all eleven must be green)

```
cd backend
for t in test_capability_parity \
         test_phase1_foundation test_phase1_integration \
         test_phase2_employee test_phase2_integration \
         test_phase3_requisition test_phase3_integration \
         test_phase4_posting test_phase4_public_security \
         test_phase5_candidate test_phase5_integration; do
  venv/Scripts/python.exe -m app.services.hrms.tests.$t
done
# expect 6 / 96 / 46 / 123 / 55 / 108 / 59 / 118 / 51 / 113 / 58  =  833
```

---

## A. Pipeline

| # | Step | Expected |
|---|---|---|
| A1 | HRMS → Candidates | Kanban with 8 columns; applicants from Phase 4 are in **Applied** |
| A2 | Column headers | Each shows a count |
| A3 | Switch to **List** | Same candidates as a table |
| A4 | Switch to **Grid** | Same candidates as cards |
| A5 | Search a partial name | Filters after ~300 ms in every layout |
| A6 | Search `Asha(` | No crash |
| A7 | Click any card | Right-side drawer opens |
| A8 | Empty pipeline | *"No candidates"* + guidance |

## B. The lifecycle — the core of this phase

| # | Step | Expected |
|---|---|---|
| B1 | Open an **Applied** candidate | *Move to stage* offers only **Shortlisted, Under Review, On Hold, Rejected, Duplicate** |
| B2 | Confirm what is **absent** | No *Joined*, *Selected*, *Offer Accepted*, *Interview Scheduled* |
| B3 | Click **Shortlisted** | Moves immediately (optimistic), toast confirms |
| B4 | Re-open | Options are now **Assessment Pending, Interview Scheduled**, + hold/reject/duplicate |
| B5 | Force an illegal move via API: `PATCH /api/hrms/candidates/<uk>` with `{"application_status":"Joined"}` | **409**, message lists what *is* allowed |
| B6 | Move a candidate to **Rejected**, then re-open | **Under Review** offered — a rejection can be reversed |
| B7 | Move one to **On Hold**, re-open | **Under Review / Shortlisted** offered — a hold can be lifted |
| B8 | Set a candidate to `Employee Created` (via API), re-open | *"This is a final stage — the pipeline ends here."* No move buttons |
| B9 | Kill the network, move a stage | Card reverts to its previous stage; error toast — **no phantom move** |

## C. Duplicates

| # | Step | Expected |
|---|---|---|
| C1 | Add two candidates with the **same email** | Both show a red **DUP** badge |
| C2 | Add one with `9876543210` and another with `+91 98765 43210` | **Both flagged** — the `+91` prefix is handled |
| C3 | Check the records | **Neither was merged or deleted** — flagging is advisory |
| C4 | Open a flagged candidate | Drawer shows *"Possible duplicate"* |

## D. Screening

| # | Step | Expected |
|---|---|---|
| D1 | HRMS → Screening | 4 stat tiles; **To screen** tab lists Applied/Under Review |
| D2 | Tick 2–3 candidates | Dark floating bar shows *"N selected"* + 6 actions |
| D3 | **Shortlist** | Toast; they leave the To-screen tab |
| D4 | Shortlist a candidate from an **assessment-required** posting | Lands in **Assessment Pending**, not Shortlisted |
| D5 | Check that candidate's journey | Shows **both** hops — Applied→Shortlisted **and** Shortlisted→Assessment Pending |
| D6 | Select a mix incl. one already at a terminal stage, apply **Hold** | *"Partly applied"* panel: N updated, M skipped, **with a reason per skip** |
| D7 | Apply the same action twice | Second run reports *"already …"* rather than silently doing nothing |
| D8 | **Reject** with an empty reason | Confirm button stays disabled |
| D9 | Reject with a reason | Moves to Rejected; reason stored and visible in the journey |
| D10 | **Forward** with no recipient chosen | Confirm disabled |
| D11 | Forward to a colleague | **Stage unchanged**; *Assigned* column shows them; they get a notification |
| D12 | Select all via the header checkbox | Every visible row selected; click again clears |
| D13 | Switch tabs | Selection clears (prevents acting on rows you can no longer see) |

## E. Journey

| # | Step | Expected |
|---|---|---|
| E1 | Open a candidate → **Journey** (route icon) | Modal with a 7-step rail + timeline |
| E2 | Rail | Reached steps ticked; current step ringed |
| E3 | Timeline | Oldest first; each event has a coloured dot, title, detail, actor, timestamp |
| E4 | A shortlist event | Coloured **green** (success) |
| E5 | A rejection event | Coloured **red** |
| E6 | An application from Phase 4 | Appears as the first event — the journey reads Phase 4's audit rows |
| E7 | A terminal candidate | *"This is a final stage"* note |

## F. Permissions

| # | Role | Check | Expected |
|---|---|---|---|
| F1 | **HOD** | Candidates list | **Only** candidates on requisitions **they raised** |
| F2 | **HOD** | Column counts | Match their own scope, not the company total |
| F3 | **HOD** | Drawer | **No** *Move to stage* section, no delete |
| F4 | **HOD** | Screening page | Table renders but **no checkboxes and no bulk bar** |
| F5 | **HOD** | Open an out-of-scope candidate by URL/API | 404 |
| F6 | **plain clientuser** | Candidates in the sidebar | Present, but the page errors — API returns 403 |
| F7 | **staff admin** | Candidates | Visible; **Add** works |
| F8 | **staff admin** | Screening bulk bar | **Absent** — no `candidate.screen` |
| F9 | **HR** | Everything | Full access |

## G. Manual add

| # | Step | Expected |
|---|---|---|
| G1 | **Add** → submit with only a name | Rejected — *"at least an email address or a phone number"* |
| G2 | Enter an invalid email | 422 |
| G3 | Add with name + phone | Created at **Applied**, appears in the pipeline |
| G4 | Delete an early-stage candidate | Confirm → removed |
| G5 | Try to delete one at **Joined** | **409** — *"part of the hiring history"* |

## H. States & theming

| # | Step | Expected |
|---|---|---|
| H1 | Slow 3G | *"Loading candidates…"* |
| H2 | Stop backend, reload | Error panel + **Try again** |
| H3 | Light ⇄ dark | All Phase 5 screens re-theme |
| H4 | 375 / 768 / 1440 px | Kanban scrolls horizontally inside its container; page never scrolls sideways |
| H5 | Console | **Zero errors** |

## I. Regression

| # | Module | Expected |
|---|---|---|
| I1–I5 | Task Management · Calendar · TPMS · ORM · Reports | All work |
| I6 | HRMS Employees / Requisitions / JDs / Postings | All work |
| I7 | **Public apply link** (incognito) | Still works, still anonymous |
| I8 | Console | No new errors |

## J. Database

| # | Check | Expected |
|---|---|---|
| J1 | Collections | Still **10** — Phase 5 added none |
| J2 | After a stage move | `hrms_audit_log` has a `stage changed` row with `"X -> Y"` |
| J3 | After a reject | Both a `stage changed` and a `candidate screened` row, reason included |
| J4 | After a forward | `assigned_recruiter_id` set; **`application_status` unchanged** |
| J5 | `staff` / `learners` | **0** documents with `uk` or `application_status` |

---

## Sign-off

- [ ] All eleven automated suites green (**833**)
- [ ] Sections A–J pass
- [ ] **B2 + B5 verified** — illegal stages are neither offered nor accepted
- [ ] **C2 verified** — `+91` phone duplicates are caught
- [ ] **D6 verified** — partial success reports skips with reasons
- [ ] **F1/F2 verified** — HOD scoping applies to rows *and* counts
- [ ] No console errors; no backend 5xx

**Tester:** ______________  **Date:** ______________  **Result:** PASS / FAIL
