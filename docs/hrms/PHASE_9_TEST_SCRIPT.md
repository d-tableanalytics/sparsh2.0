# HRMS Phase 9 — Manual Test Script

> Onboarding, the public joining form, and the handover that creates an employee.
>
> **Prerequisites:** at least **three candidates at `Offer Accepted`** (walk them through Phase 8 to get there), one candidate at **Selected**, and one mid-interview.
> Accounts: **HR**, **MD**, **HOD**, plain **clientuser**, **staff admin**.

## Automated suites (all nineteen must be green)

```
cd backend
for t in test_capability_parity \
         test_phase1_foundation test_phase1_integration \
         test_phase2_employee test_phase2_integration \
         test_phase3_requisition test_phase3_integration \
         test_phase4_posting test_phase4_public_security \
         test_phase5_candidate test_phase5_integration \
         test_phase6_assessment test_phase6_integration \
         test_phase7_interview test_phase7_integration \
         test_phase8_offer test_phase8_integration \
         test_phase9_onboarding test_phase9_integration; do
  venv/Scripts/python.exe -m app.services.hrms.tests.$t
done
# expect 6/96/46/125/55/108/59/118/51/113/58/96/66/98/66/99/78/170/104 = 1612
```

---

## A. Starting an onboarding

| # | Step | Expected |
|---|---|---|
| A1 | HRMS → Onboarding → **Start onboarding** | Picker lists only **Offer Accepted** candidates |
| A2 | Look for your **Selected** candidate | **Absent** |
| A3 | Look for your mid-interview candidate | **Absent** |
| A4 | Read the empty state when nobody qualifies | Explains the accepted-offer requirement *and why* (we ask for PAN/Aadhaar/bank) |
| A5 | Pick someone, leave the joining date blank, start | Created; joining date **pre-filled from the accepted offer** |
| A6 | Read the card | Status **Pre-Onboarding**, progress **0/12**, BG **Pending** |
| A7 | Check the designation | Comes from the **offer**, not the requisition |
| A8 | Start onboarding for the same person again | **409 — "already being onboarded"** (not a stage complaint) |
| A9 | Check the candidate in the pipeline | Stage is **Pre-Onboarding** |
| A10 | HR bell | Notified |

## B. The public form

| # | Step | Expected |
|---|---|---|
| B1 | Open the onboarding → copy the **pre-onboarding link** | `…/onboard/<22-char code>` |
| B2 | Look at the **board** (not the detail) in DevTools → `GET /api/hrms/onboarding` | **No `access_code` on any row** — it is a credential |
| B3 | Open the link in **incognito** | Form renders — never a login redirect |
| B4 | Read the header | Their name and role; **no** company id, offer number or salary |
| B5 | Submit with **neither PAN nor Aadhaar** | **422** — at least one is required |
| B6 | Submit `pan: ABC` | **422** — PAN is not valid |
| B7 | Submit `aadhaar: 123` | **422** — must be 12 digits |
| B8 | Submit `bank_ifsc: XX` | **422** |
| B9 | Submit `bank_account: 12ab34` | **422** — digits only |
| B10 | Submit a date of birth in the future | **422** — must be in the past |
| B11 | Attach a `.exe` | **415** |
| B12 | Attach 16 files | **422** — max 15 |
| B13 | Add 6 references | Blocked at 5 |
| B14 | **After every rejection above, check the board** | Still **Pre-Onboarding / Pending** — nothing was written |
| B15 | Submit properly: lowercase PAN, Aadhaar **with spaces**, lowercase IFSC, **one PDF** | Thank-you screen |
| B16 | **Check the PDF actually attached** | Document listed on the detail panel, source *from candidate* — **this is Finding #1's regression** |
| B17 | Check the stored values | PAN and IFSC **upper-cased**, Aadhaar spaces **stripped** |
| B18 | Reload the public link | Calm *"Thank you"* screen, not an error |
| B19 | Submit again via API | **409** — already submitted |
| B20 | HR bell | Notified that details are ready to verify |

## C. Verification & background check

| # | Step | Expected |
|---|---|---|
| C1 | On a **fresh** onboarding (nothing submitted), click **Mark documents verified** | **409** — nothing to verify yet |
| C2 | On the submitted one, click it | Pre-status **Verified**; `documents_verified` **ticks itself** |
| C3 | Try to un-tick `documents_verified` by hand | **Checkbox is disabled**; API returns **409** |
| C4 | Set background to **Cleared** | `bg_cleared` **ticks itself** |
| C5 | Set it back to **In Progress** | `bg_cleared` **un-ticks** — a withdrawn clearance must not keep asserting itself |
| C6 | Set it to **Flagged** | Warning shown; HR **and MD** notified |
| C7 | Try to hand-tick `bg_cleared` or `employee_id` | Both disabled; API **409** — *"updated automatically"* |
| C8 | Tick a human item (e.g. *Assets issued*) | Works; progress moves; **your name and the time** recorded |
| C9 | Un-tick it | Attribution cleared too |

## D. Generating the Employee ID — the handover

| # | Step | Expected |
|---|---|---|
| D1 | With BG **Flagged**, look at **Generate Employee ID** | Disabled, and the reason is **written out**: *"Background verification is flagged."* |
| D2 | Force it via API | **409** with the same wording |
| D3 | Clear the BG, but clear the **joining date** | New blocker: *"A joining date has not been set."* |
| D4 | On an onboarding whose documents are **not** verified | Blocker: *"KYC documents have not been verified."* |
| D5 | Satisfy everything, click **Generate Employee ID** | `EMP-YYYY-NNN` issued; status → **Onboarding** |
| D6 | Check the `employee_id` checklist item | Ticked automatically |
| D7 | Check the candidate's stage | **Joined** |
| D8 | Click it again | **409** — already issued |
| D9 | HR and MD bells | Notified that an employee was created |

## E. The employee who has no login

| # | Step | Expected |
|---|---|---|
| E1 | HRMS → **Employees** | The new hire is **there already**, with a **"No login yet"** badge |
| E2 | Check their name and email | From the onboarding **snapshot** |
| E3 | Click the row | Opens **Link a login account** — not a broken profile page |
| E4 | Open **Add employee** (the normal picker) | **Loads without error** — this is Finding #5's regression |
| E5 | Onboard a **second** person to Employee ID | **Also succeeds** — this is Finding #2's regression (see K3) |
| E6 | Create an ERP user for the new hire, then link it | Badge disappears; row now opens their profile |
| E7 | Try to link the same record again | **409** — already linked |
| E8 | Try to link a user from another company | **422** |
| E9 | Try to link a user who already has a profile | **409** |
| E10 | Check `staff` and `learners` in the DB | **No document** gained `identity_snapshot`, `onb_no` or `access_code` |

## F. Completion

| # | Step | Expected |
|---|---|---|
| F1 | Tick every remaining human item | On the last one, status flips to **Completed** |
| F2 | Check the candidate | **Employee Created** |
| F3 | Try to un-tick anything | **409** — *"Update the employee record instead."* |
| F4 | Try to upload a document | **409** |
| F5 | Open the public link | **410** — the form is closed |
| F6 | HR bell | Notified that onboarding is complete |

## G. Permissions

| # | Role | Check | Expected |
|---|---|---|---|
| G1 | **HR** | Everything | Full access |
| G2 | **MD** | Everything | Full access |
| G3 | **HOD** | Onboarding page | **Readable**; no Start, no checkboxes, no Generate |
| G4 | **HOD** | `POST /api/hrms/onboarding` | **403** |
| G5 | **HOD** | `POST …/generate-id` | **403** |
| G6 | **plain clientuser** | `GET /api/hrms/onboarding` | **403** |
| G7 | **staff admin** | Onboarding with `company_id` | Readable and writable |
| G8 | **staff admin** | Onboarding **without** `company_id` | **400** — internal callers must name a company |
| G9 | **HR** | Add `?company_id=<other>` to any call | **Ignored** — pinned to their own company |

## H. The four public surfaces

| # | Step | Expected |
|---|---|---|
| H1 | In incognito, open **apply**, **assess**, **offer** and **onboard** links | All four render; none redirects to login |
| H2 | Open `/onboard/short` and `/onboard/{$ne:null}` | Both **404**, **byte-identical** message |
| H3 | Compare that message with an unknown-but-well-formed code | **Identical** — no existence oracle |
| H4 | Reload the onboard form ~45 times in a minute | **429** with `Retry-After` |
| H5 | Attach a résumé to a **public job application** (Phase 4) | **Accepted** — Finding #1 regression |
| H6 | Attach a file to a **public assessment** (Phase 6) | **Accepted** — Finding #1 regression |

## I. States & theming

| # | Step | Expected |
|---|---|---|
| I1 | Slow 3G on the public form | *"Loading your form…"* |
| I2 | Invalid code | *"Link unavailable"*, nothing internal revealed |
| I3 | Light ⇄ dark on the board | Re-themes cleanly |
| I4 | 375 / 768 / 1440 px | Form and board readable; no sideways page scroll |
| I5 | Console | **Zero errors** |

## J. Regression

| # | Module | Expected |
|---|---|---|
| J1–J5 | Task Management · Calendar · TPMS · ORM · Reports | All work |
| J6 | HRMS Employees → Offers | Every earlier screen works |
| J7 | Console | No new errors |

## K. Database

| # | Check | Expected |
|---|---|---|
| K1 | Collections | **14** — `hrms_onboarding` added |
| K2 | `hrms_onboarding` indexes | `uniq_onb_no`, `uniq_access_code`, `uniq_candidate`, `by_company_status`, `uniq_employee_id` |
| K3 | **Backend startup log** | `[INFO] HRMS index uniq_user on hrms_employee_profiles rebuilt to match the spec` — **Finding #2's fix landing.** Then confirm `db.hrms_employee_profiles.getIndexes()` shows `uniq_user` with **`sparse: true`** |
| K4 | An onboarding-created profile | **No `user_id` key at all** — not `null` |
| K5 | After the handover | Audit rows: `onboarding started`, `pre-onboarding submitted`, `kyc documents verified`, `background verification updated`, `employee id generated`, `employee created` |
| K6 | After linking | `employee linked to a user account` |
| K7 | `staff` / `learners` | **0** documents with `identity_snapshot`, `onb_no` or `access_code` |

---

## Sign-off

- [ ] All nineteen automated suites green (**1612**)
- [ ] Sections A–K pass
- [ ] **B14 verified** — no rejected submission writes anything
- [ ] **B16 / H5 / H6 verified** — uploads work on all three public surfaces (Finding #1)
- [ ] **C5 verified** — a withdrawn clearance un-ticks its checklist item
- [ ] **D1–D4 verified** — every blocker is explained in words
- [ ] **E5 + K3 verified** — a second onboarding-created employee succeeds (Finding #2)
- [ ] **E10 / K7 verified** — HRMS never wrote to an identity collection
- [ ] No console errors; no backend 5xx

**Tester:** ______________  **Date:** ______________  **Result:** PASS / FAIL
