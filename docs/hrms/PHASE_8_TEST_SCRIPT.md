# HRMS Phase 8 — Manual Test Script

> Offers, versioning, the public letter, and requisition auto-closure.
>
> **Prerequisites:** at least three candidates at **Selected** (walk one through Phase 7 to
> get there), one requisition with **vacancy = 1** and one with **vacancy = 2**.
> Accounts: **HR**, **MD**, **HOD**, plain **clientuser**, **staff admin**.

## Automated suites (all seventeen must be green)

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
         test_phase8_offer test_phase8_integration; do
  venv/Scripts/python.exe -m app.services.hrms.tests.$t
done
# expect 6/96/46/125/55/108/59/118/51/113/58/96/66/98/66/99/78 = 1338
```

---

## A. Creating a draft

| # | Step | Expected |
|---|---|---|
| A1 | HRMS → Offers → **New offer** | Candidate list shows only **Selected** candidates |
| A2 | Look for someone mid-interview | **Absent** |
| A3 | Select a candidate | **CTC pre-fills** from the JD (or requisition, or their expectation) |
| A4 | Read the empty state when nobody is offerable | Explains the Selected requirement |
| A5 | Set CTC to 0 | **422** — must be greater than zero |
| A6 | Set a joining date in the past | **422** |
| A7 | **Save draft** | Card appears with status **Draft**, version **v1** |
| A8 | Try to create a second offer for the same person | **409** — already has a live offer |

## B. Versioned editing — the core of this phase

| # | Step | Expected |
|---|---|---|
| B1 | Open the draft → **Edit** | Letter body is editable |
| B2 | Read the placeholder hint | `{designation}`, `{company}`, `{ctc}`, `{joining_date}` are filled automatically |
| B3 | Change the body, **Save draft** | Toast says *"Saved as v2"* |
| B4 | Click the **history** icon | Shows **v1** with who edited it and when |
| B5 | Edit again and save | **v3**; history now has two entries |
| B6 | Clear the body entirely and save | **422** — cannot be empty |
| B7 | Click the **eye** icon | Preview renders the formal letterhead |
| B8 | Compare the preview to what you typed | Placeholders are resolved, table shows CTC / joining date |

## C. Sending freezes the letter

| # | Step | Expected |
|---|---|---|
| C1 | Try to send with no signatory | Button disabled; API returns **422** |
| C2 | Enter the signatory and **Send to candidate** | Status becomes **Sent** |
| C3 | Check the candidate | Stage is **Offer Generated** |
| C4 | Re-open the offer | Editor is now a **read-only preview** with a note explaining why |
| C5 | Force a PATCH via API | **409** — *"can no longer be edited"* |
| C6 | Try to delete it | **409** — *"revoke it instead"* |
| C7 | Send again via API | **409** |
| C8 | On a new draft, use **Send now** from the create modal | Created and sent in one action |
| C9 | Try **Send now** with an empty signatory | **422**, and **no draft is left behind** — re-check the board |

## D. The public letter

| # | Step | Expected |
|---|---|---|
| D1 | Copy the link from a **Sent** offer | `…/offer/<22-char code>` |
| D2 | Open it in **incognito** | Letter renders — never a login redirect |
| D3 | Compare with the internal preview | **Identical** — same component |
| D4 | Copy the link of a **Draft** (there is none shown) | Confirms the code is only exposed while Sent |
| D5 | Take a Draft's `access_code` from the DB and open it | **404** — a draft is invisible publicly |
| D6 | Try `/offer/short` and `/offer/{$ne:null}` | Both **404**, byte-identical message |
| D7 | Click **Save a PDF copy** | Print dialog; the letter prints **without** the buttons, keeping its accent bars |

## E. Accept / decline

| # | Step | Expected |
|---|---|---|
| E1 | Click **Accept this offer** | Signature field appears |
| E2 | Confirm with an empty name | Blocked — *"type your full name"* |
| E3 | Type a name and confirm | Celebration screen; letter now shows the candidate's signature block |
| E4 | Check the candidate in HRMS | Stage **Offer Accepted** |
| E5 | HR bell | Notified |
| E6 | Reload the public link | *"Already responded"*, no buttons |
| E7 | Try to respond again via API | **409** |
| E8 | On another offer, click **Decline**, add a note, confirm | Recorded **without** a signature |
| E9 | Check the candidate | Stage **Offer Declined** |
| E10 | Check the offer card in HRMS | Shows the candidate's note |

## F. Revoke — and the walk-back

| # | Step | Expected |
|---|---|---|
| F1 | Try to revoke a **Draft** | **409** — only a sent offer |
| F2 | Revoke a **Sent** offer, giving a reason | Status **Revoked** |
| F3 | Open the public link | **410** — *"This offer has been withdrawn"* |
| F4 | Try to accept it | **410** |
| F5 | **Check the candidate's stage** | Back to **Selected** — not stranded at Offer Generated |
| F6 | Raise a new offer for them with revised terms | **Works** — this is the whole point of F5 |

## G. CTC redaction

| # | Role | Check | Expected |
|---|---|---|---|
| G1 | **HR** | Offer cards | CTC tile visible |
| G2 | **staff admin** | Offer cards | **No CTC tile** |
| G3 | **staff admin** | DevTools → `GET /api/hrms/offers` | **No `ctc` key on any row**, `ctc_visible: false` |
| G4 | **staff admin** | Check `history` entries in that payload | **No `ctc` there either** |
| G5 | **HOD** | Offers page | Readable; **no** New offer / Send / Revoke |
| G6 | **plain clientuser** | Offers | API **403** |

## H. Requisition auto-closure (Module 16)

| # | Step | Expected |
|---|---|---|
| H1 | Use a requisition with **vacancy = 1**; accept its offer | Requisition closes as **Hired** |
| H2 | HR and MD bells | Notified that the requisition is filled |
| H3 | Use a requisition with **vacancy = 2**; accept ONE offer | Requisition stays **Open** |
| H4 | Accept the SECOND offer | Now closes as **Hired** |
| H5 | Put a requisition on **Hold**, fill its vacancy | Stays on **Hold** — a human decision outranks the arithmetic |
| H6 | Check the audit log | `requisition auto-closed (Hired)` rows present |

## I. States & theming

| # | Step | Expected |
|---|---|---|
| I1 | Slow 3G on the public page | *"Loading your offer…"* |
| I2 | Invalid code | *"Link unavailable"*, nothing internal revealed |
| I3 | Light ⇄ dark on the board | Re-themes; **the letter stays light** — it is a document |
| I4 | 375 / 768 / 1440 px | Letter stays readable; no sideways page scroll |
| I5 | Console | **Zero errors** |

## J. Regression

| # | Module | Expected |
|---|---|---|
| J1–J5 | Task Management · Calendar · TPMS · ORM · Reports | All work |
| J6 | HRMS Employees → Interviews | All earlier screens work |
| J7 | Public **apply**, **assess** and **offer** (incognito) | All three work, all anonymous |
| J8 | Console | No new errors |

## K. Database

| # | Check | Expected |
|---|---|---|
| K1 | Collections | **13** — `hrms_offers` added |
| K2 | `hrms_offers` indexes | `uniq_offer_no`, `uniq_access_code`, `by_candidate`, `by_company_status`, `by_request` |
| K3 | After edits | `history` array holds each earlier version with its own CTC and body |
| K4 | After acceptance | Audit rows: `offer created`, `offer edited`, `offer sent`, `offer accepted`, `stage changed` |
| K5 | After a 1-vacancy acceptance | `requisition auto-closed (Hired)` row |
| K6 | `staff` / `learners` | **0** documents with `offer_no` or `access_code` |

---

## Sign-off

- [ ] All seventeen automated suites green (**1338**)
- [ ] Sections A–K pass
- [ ] **B3–B5 verified** — every edit is versioned and recoverable
- [ ] **C4/C5 verified** — a sent letter cannot change under the candidate
- [ ] **C9 verified** — a failed create-and-send leaves nothing behind
- [ ] **F5/F6 verified** — revoking walks the candidate back so revised terms are possible
- [ ] **G3/G4 verified** — CTC absent from the payload, including history
- [ ] **H3/H4/H5 verified** — closure arithmetic and the Hold exemption
- [ ] No console errors; no backend 5xx

**Tester:** ______________  **Date:** ______________  **Result:** PASS / FAIL
