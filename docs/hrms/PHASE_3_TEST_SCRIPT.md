# HRMS Phase 3 — Manual Test Script

> Frontend + end-to-end verification for requisitions and job descriptions.
>
> ⚠️ **Please actually run section D.** Phase 2 shipped a defect (every write control hidden)
> that its own script would have caught on the first row — see PHASE_3_REPORT Finding #1.
> An automated parity guard now covers that specific class, but the scripts remain the only
> check on rendering and interaction.
>
> **Prerequisites:** HRMS enabled for **Company A**, with at least one department and one
> designation created (Phase 2). Accounts: **superadmin**, **staff admin**, **clientadmin (MD)**,
> **clientuser + governance_role HR**, **clientuser + governance_role HOD**, plain **clientuser**.

## Automated suites (all seven must be green)

```
cd backend
for t in test_capability_parity test_phase1_foundation test_phase1_integration \
         test_phase2_employee test_phase2_integration \
         test_phase3_requisition test_phase3_integration; do
  venv/Scripts/python.exe -m app.services.hrms.tests.$t
done
# expect 6 / 96 / 46 / 123 / 55 / 104 / 59  =  489
```

---

## A. Navigation

| # | Step | Expected |
|---|---|---|
| A1 | Expand HRMS in the sidebar | Overview · Employees · **Hiring Requisitions** · **Job Descriptions** (+ Departments/Designations for admins) |
| A2 | As a plain clientuser | Requisitions and Job Descriptions **are** visible (anyone may raise one) |
| A3 | Open each; hard-refresh on both | Render; no bounce to `/` |

## B. Raise a requisition (as HOD)

| # | Step | Expected |
|---|---|---|
| B1 | Requisitions → **New requisition** | Modal opens |
| B2 | Department / Designation dropdowns | Populated from the Phase 2 masters — **not** free-text boxes |
| B3 | With no designations created | Hint: *"add one under HRMS ▸ Designations first"* |
| B4 | Submit with empty required fields | Browser validation blocks; nothing sent |
| B5 | Fill everything, leave **Key responsibilities** empty | Error toast: *"Provide a Job Description…"* |
| B6 | Set vacancy `0` | Rejected (min=1) |
| B7 | Set required date in the past | Accepted (past dates are allowed — the field is a target, not a constraint) |
| B8 | Complete and submit | Toast: *"Requisition HR-REQ-YYYY-NNN raised — routed to HR for review"* |
| B9 | Check the list | New row, approval = **Pending HR Review**, status = **Open** |
| B10 | Check the tiles | "Total" and "Pending HR review" both incremented |

## C. The approval chain — the core of this phase

| # | Role | Step | Expected |
|---|---|---|---|
| C1 | HOD | Open the requisition | Drawer; stepper on step 2; **no action bar** — grey note *"Waiting on HR to review"* |
| C2 | **HR** | Open the same one | Blue bar: *"Awaiting your HR review"* + **Review & forward** |
| C3 | HR | Click it, then **Reject** with an empty remark | Inline error: *"A reason is required when rejecting."* |
| C4 | HR | Add a remark, click **Forward to MD** | Toast; status → **Pending MD Approval**; stepper advances |
| C5 | **HR** | Look for an approve bar now | **Absent** — HR cannot perform the MD stage |
| C6 | **MD** | Open it | Bar: *"Awaiting your approval"*; dialog subtitle shows the **HR remark** |
| C7 | MD | Change **Revised CTC**, approve | Status → **Approved**; drawer shows *"posting enabled"* |
| C8 | MD | Re-open, check Offered CTC | Shows the **revised** figure |
| C9 | **MD** | Try to find an HR-review control anywhere | **None** — separation of duties |
| C10 | HOD | Check notifications bell | Notified of forward **and** approval |
| C11 | HR | Check bell | Notified when raised and when approved |
| C12 | MD | Check bell | Notified when HR forwarded |

## C-ter. No-HR-reviewer escalation (separation of duties, decision (a))

Requires a company (or a temporary state) where **no active user holds `governance_role = HR`**.

| # | Step | Expected |
|---|---|---|
| C17 | With an HR user present, raise a requisition | **No** "no HR reviewer" warning anywhere |
| C18 | Clear the HR governance role from every user in the company | — |
| C19 | Raise a requisition as HOD | Still created, status **Pending HR Review** — warned, not blocked |
| C20 | Check the **MD's** bell + email | *"No HR reviewer for requisition …"* — names the fix: assign the HR role to someone |
| C21 | Check the **raiser's** bell | Told their requisition has no reviewer and that the MD was notified |
| C22 | Assign HR to a user, raise another | Normal HR-review notification; **no** escalation |

## C-bis. Rejection path

| # | Step | Expected |
|---|---|---|
| C13 | Raise another; HR rejects with a reason | Status → **Rejected**, closing → **Closed** |
| C14 | Open it | Red panel showing the reason |
| C15 | Job Descriptions → find its JD | Status **Rejected** |
| C16 | Raiser's bell | Notified, reason included |

## D. Permissions — please run every row

| # | Role | Check | Expected |
|---|---|---|---|
| D1 | HR | **New requisition** button | **Visible** |
| D2 | HOD | **New requisition** button | **Visible** (anyone may raise) |
| D3 | plain clientuser | **New requisition** button | **Visible** |
| D4 | HOD | Edit (pencil) / Delete on a pending requisition | **Absent** — no `requisition.write` |
| D5 | HR | Edit / Delete on a pending requisition | **Visible** |
| D6 | HR | Edit on an **Approved** requisition | **Absent**; forcing the API → 409 |
| D7 | HR | Delete on an **Approved** requisition | **Absent**; forcing the API → 409 |
| D8 | HR | Closing-status buttons on an Approved requisition | **Visible** |
| D9 | HOD | Closing-status buttons | **Absent** |
| D10 | plain clientuser | Requisition list | Only the ones **they raised** |
| D11 | plain clientuser | Tiles | Match their own scoped count, not the company total |
| D12 | plain clientuser | Open someone else's via URL/API | 404 |
| D13 | staff admin | Requisition list | Visible; **no** review/approve bars at any stage |
| D14 | superadmin | Both bars | Visible (break-glass) |

## E. Job Descriptions

| # | Step | Expected |
|---|---|---|
| E1 | Open Job Descriptions | Master/detail list |
| E2 | Look for a **New JD** button | **None** — JDs are created with their requisition |
| E3 | Select a **Pending Approval** JD | Editable; note explains it is approved with its requisition |
| E4 | Edit benefits, Save | Toast; version increments |
| E5 | Clear **Responsibilities** entirely and save | 422 — *"responsibilities or at least one attachment"* |
| E6 | Select an **Approved** JD | Fields disabled; *"Posting enabled"* chip; lock explanation |
| E7 | Force `PATCH /api/hrms/jd/{no}` on an approved JD | **409** |
| E8 | As HOD, open a pending JD | Read-only (no `jd.write`) |
| E9 | Filter by status | Works |

## F. Concurrency (two browsers)

| # | Step | Expected |
|---|---|---|
| F1 | Open the same Pending-HR-Review requisition as HR in two tabs | Both show the review bar |
| F2 | Forward in tab 1 | Succeeds |
| F3 | Forward in tab 2 | **409** — *"This requisition was updated by someone else. Reload and try again."* Not a silent overwrite |

## G. States & theming

| # | Step | Expected |
|---|---|---|
| G1 | Slow 3G on Requisitions | *"Loading requisitions…"* |
| G2 | Stop backend, reload | Error panel + **Try again** |
| G3 | Filter to no matches | *"No requisitions match"* + *"Try clearing the filters."* |
| G4 | Search `Analyst(` | No crash |
| G5 | Light ⇄ dark | All Phase 3 screens re-theme |
| G6 | 375 / 768 / 1440 px | Table scrolls inside its container; page never scrolls sideways; drawer full-width on mobile |
| G7 | Console throughout | **Zero errors / warnings** |

## H. Regression

| # | Module | Expected |
|---|---|---|
| H1–H5 | Task Management · Calendar · TPMS · ORM · Reports | All work |
| H6 | **HRMS Employees / Departments / Designations** | **All Phase 2 write controls now visible for HR** (Finding #1 fix) |
| H7 | User Management, Company Details toggles | Work |
| H8 | Console | No new errors |

## I. Database

```
cd backend
venv/Scripts/python.exe -c "
import asyncio
from app.db.mongodb import connect_to_mongo, db_connection
async def go():
    await connect_to_mongo(); db = db_connection.db
    for c in sorted(n for n in await db.list_collection_names() if n.startswith('hrms_')):
        print(c.ljust(26), sorted((await db[c].index_information()).keys()))
asyncio.run(go())"
```

| # | Check | Expected |
|---|---|---|
| I1 | Collections | 7, incl. `hrms_requisitions`, `hrms_job_descriptions` |
| I2 | After raising one | Exactly one requisition **and** one JD, cross-linked |
| I3 | After deleting a pending one | **Both** gone — no orphan JD |
| I4 | After MD approval | `hrms_job_descriptions.status == "Approved"` |
| I5 | `hrms_audit_log` | Rows for raise, HR-approve, MD-approve |
| I6 | Restart, re-run | Identical index counts |

---

## Sign-off

- [ ] All seven automated suites green (**489**)
- [ ] Sections A–I pass
- [ ] **Section D run in full** (this is the section Phase 2 needed)
- [ ] **C5 + C9 verified** — neither HR nor MD can perform both approval stages
- [ ] **F3 verified** — concurrent approval gives 409, not a silent overwrite
- [ ] **H6 verified** — Phase 2 write controls now render
- [ ] No console errors; no backend 5xx

**Tester:** ______________  **Date:** ______________  **Result:** PASS / FAIL
