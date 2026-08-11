# HRMS Phase 11-R — Manual Test Script

> Link registry · Documentation · Appointment letters · Client-wise analytics · Referrals ·
> Budget approval · Sanctioned strength & escalation.
>
> **Prerequisites:** a company with real pipeline history — candidates at several stages, at
> least one **accepted offer**, one live posting, and two requisitions raised by
> **different people** (one by HR, one by a HOD).
> Accounts: **HR**, **MD**, **HOD** (who raised a requisition, and who reports to somebody),
> a **second HOD** in that reporting line, a plain **clientuser**, and a **staff admin**.
> Masters: at least one department **with a head_user_id set**, two designations, and one
> employee holding an `EMP-…` code.

## Automated suites (all twenty-eight must be green)

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
         test_phase9_onboarding test_phase9_integration \
         test_phase10_analytics test_phase10_integration \
         test_phase11_links test_phase11_documents test_phase11_appointments \
         test_phase11_clients test_phase11_referral test_phase11_budget \
         test_phase11_sanction; do
  venv/Scripts/python.exe -m app.services.hrms.tests.$t
done
# expect 6/100/46/125/55/109/59/118/51/113/58/96/66/98/66/99/78/172/104/155/103
#        /57/70/77/92/43/46/81 = 2543
```

**Frontend gates**

```
cd frontend
npx vite build          # must exit 0
npm run lint            # must report NO NEW errors  ← not yet run; do this first
```

---

## A. Item 1 — the link register

| # | Step | Expected |
|---|---|---|
| A1 | HRMS → **Links** tab | Table + 5 stat tiles (Active / Completed / Expired / Revoked / Never opened) |
| A2 | Open **How link generation works** | A permanent panel explaining generation, the 128-bit codes, the mandatory source block, what "opened" counts, and what revoke does |
| A3 | Publish a posting to 2 platforms (**auto** mode) | Two rows appear, kind **Application**, status Active, 0 opens |
| A4 | Publish one with **external** mode | **No row appears.** The panel explains why — those applications never reach this pipeline |
| A5 | Send an assessment / offer / onboarding form | A row appears for each, with the candidate's name |
| A6 | Open a candidate link in a private window | `Opens` increments; `Never opened` tile drops by one |
| A7 | Open it twice more | Count is 3. *(It counts page views, not people — a forwarded link counts each open.)* |
| A8 | Submit the assessment / respond to the offer | Status → **Completed**; the page still opens for the candidate |
| A9 | **Revoke** a live offer link, give a reason | Status → Revoked |
| A10 | Open that link in a private window | **Refused.** Message is the generic *"no longer accepting"* — identical to a closed position, never "this was withdrawn from you" |
| A11 | Try to revoke it again | 409, *"already revoked"* |
| A12 | **Reissue** an offer link | New row appears; old row → Revoked, reason *"Reissued"*; the **old URL stops working** and the new one opens |
| A13 | Try to reissue an **Application** link | Refused — *"its code is printed on every job board"* |
| A14 | Set a posting's expiry to yesterday, reload Links | Its row reads **Expired** with no nightly job. The posting's stored status is unchanged |
| A15 | Open a link **created before this phase** (an old offer) | **Still works.** No migration was run and none is needed |
| A16 | Log in as the **HOD** | Sees only links for requisitions **they** raised; the notice says so |
| A17 | As a plain **clientuser** | The Links tab is absent; `/hrms/links` is refused |

## B. Item 2 — documentation

| # | Step | Expected |
|---|---|---|
| B1 | HRMS → **Documents** (sidebar) | Register with an Employees/Candidates toggle and 5 stat tiles |
| B2 | HRMS → **Document Types** (admin) | A default set already exists (PAN, Aadhaar, Degree…) — seeded on first read |
| B3 | Add a type, mark it **Mandatory** + **Expires** | Saved; appears in checklists immediately |
| B4 | Add a type with an existing name in different case | 409, *"already exists"* |
| B5 | Employee profile → **Documents** tab | The full checklist; everything not yet supplied reads **Pending** |
| B6 | Upload a PAN card | Status → Uploaded, `v1` |
| B7 | Upload again on the **same row** | `v2` — one document with two versions, **not** two documents |
| B8 | **Verify** it, then upload another version | Status resets to **Uploaded** and the verification is cleared — a replaced file is not verified |
| B9 | **Reject** with no reason | Refused — a reason is required |
| B10 | Reject with a reason | Status → Rejected, reason shown |
| B11 | Set an expiry date in the past, reload | Reads **Expired**; try to set `Expired` by hand → refused, *"derived"* |
| B12 | Candidate journey → **Documents** | The **same panel**, for that candidate |
| B13 | On a candidate who applied with a CV | The resume, photo and certificates appear under *"Files attached elsewhere"*, marked read-only |
| B14 | Confirm they were not copied | The register has no `DOC-…` row for the resume — the original stays the single source |
| B15 | Delete a **Verified** document | Refused — *"compliance record"*; reject it instead |
| B16 | Delete a document type that is in use | Refused, with the count; deactivating is offered |
| B17 | Rename a type in use | The rename shows on the existing documents too |
| B18 | Filter **Expiring soon** | Only documents expiring inside 30 days |
| B19 | As **staff admin** (Sparsh support) | Can upload; **cannot** verify — verification is the client's own act |

## C. Item 3 — appointment letters

| # | Step | Expected |
|---|---|---|
| C1 | HRMS → **Appointments** tab | Sits between **Offers** and **Onboarding** |
| C2 | Click **Generate** | Only candidates who have **accepted an offer** are listed |
| C3 | Pick one | Joining date, CTC and designation **pre-fill from the accepted offer** |
| C4 | Generate | Status **Generated**; candidate stage unchanged |
| C5 | Copy the link and open it | **404, "not valid"** — an unsent letter does not exist to the world |
| C6 | Edit the letter | Allowed; version bumps to v2 |
| C7 | **Send** with no signature | Refused — an authorised signatory is required |
| C8 | Send with a signature | Status **Sent**; candidate stage → **Appointment Letter Sent** |
| C9 | Try to edit now | Refused — the candidate is reading it |
| C10 | Check **Links** | An `Appointment` row appeared automatically |
| C11 | Check the candidate's **Documents** | An *Appointment Letter* row appeared automatically, status Uploaded |
| C12 | Open the candidate link in a private window | The letter renders; it is the **same paper** HR previewed |
| C13 | Reload the board | Status → **Pending Acknowledgement** — they opened it but have not signed |
| C14 | Acknowledge with no name | Refused |
| C15 | Acknowledge with a typed name | Confirmation shown; HR notified |
| C16 | Check the document again | Now **Verified** — Items 2 and 3 are one system |
| C17 | Try to acknowledge again | 409 |
| C18 | Try to **cancel** an acknowledged letter | Refused — they have already acted on it |
| C19 | Cancel a *sent* letter, then open its link | Refused; its Links row reads Revoked |
| C20 | Take a **different** accepted candidate straight to onboarding | **Works.** The appointment stage is optional and does not block anyone |
| C21 | Onboarding → onboardable list | Includes both Offer-Accepted **and** Appointment-Letter-Sent candidates |
| C22 | Requisition with 1 vacancy, letter sent | Requisition stays **Hired** — it does not re-open |
| C23 | As **staff admin** | Can see letters; **cannot** send one |

## D. Item 4 — clients and client-wise analytics

| # | Step | Expected |
|---|---|---|
| D1 | HRMS → **Clients** (admin sidebar) | Client master with requisition counts |
| D2 | Add a client | `CLI-…` id minted |
| D3 | Add one with the same name in different case | 409 |
| D4 | Raise a requisition, pick the client | Client badge shows on the requisition row |
| D5 | Try to delete that client | Refused, with the requisition count; deactivate is offered |
| D6 | Rename the client | The requisition's badge updates too |
| D7 | Screening → select 2 candidates → **Share with client** | Stage → **Shared with Client**; a client contact can be recorded |
| D8 | Open one candidate | A *Shared with client* block shows, verdict **Pending** |
| D9 | Record verdict **Shortlisted** | Stage → **Client Shortlisted**; whoever shared it is notified |
| D10 | Record **Rejected** with no reason | Refused |
| D11 | Record **Rejected** with a reason | Stage → **Client Rejected** |
| D12 | On a *different* shared candidate, move straight to Interview | **Allowed** — a silent client must not strand a candidate |
| D13 | Dashboard → **Client** dropdown | Present; defaults to **All clients** |
| D14 | Read the new tiles | CVs reviewed / selected / rejected, Shared with client, Client shortlisted, Client rejections, Total joinings |
| D15 | Click each new tile | Lands on the screen that produced the number |
| D16 | **Client comparison** table (All clients view) | One row per client, plus an *In-house / no client* row |
| D17 | Select one client | Comparison table disappears; every figure narrows to that client |
| D18 | **Position-wise CV status** | One row per requisition, one column per stage, sticky first column, horizontal scroll |
| D19 | Check the funnel after sharing CVs | Shortlisted count is **unchanged** — sharing does not advance the funnel |
| D20 | As the **HOD**, select a client | Sees only requisitions that are **both** theirs and that client's |

## E. Item 5 — referrals

| # | Step | Expected |
|---|---|---|
| E1 | Open a live apply link | *"Where did you find this job?"* is present and **required** |
| E2 | Submit without answering it | Refused |
| E3 | Submit choosing *Job portal*, no referral | Accepted; candidate's Source stays the posting's platform, the answer is recorded separately |
| E4 | Tick *"Somebody referred me"* | Referrer fields appear; nothing shifts for people who leave it unticked |
| E5 | Choose **Referred by an employee** | An employee-code box appears |
| E6 | Confirm there is **no** name picker or autocomplete | Correct — the applicant types a code, the server resolves it |
| E7 | Submit with a **wrong** code | *"We could not verify that employee code."* |
| E8 | Submit with a code from **another company** | **The identical message.** The form must not reveal who exists |
| E9 | Submit with a malformed code (`HACK-1`) | **The identical message** |
| E10 | Submit with a valid code | Accepted |
| E11 | Open the candidate | Source is **Referral**; the Referral block shows the **resolved employee name** |
| E12 | Log in as the referring employee | An in-app notification says their referral applied. **No email** |
| E13 | Move that candidate to **Selected** | The referrer is notified again |
| E14 | Move another referral to **Shortlisted** | **No** notification — only Selected and Joined |
| E15 | Candidates → **Add candidate** → tick referred | The same fields, validated identically |
| E16 | Add a candidate **without** ticking it | Accepted — the manual path has no applicant to ask |
| E17 | Reports → Candidates | `Referred by` and `Referral source` columns present; export carries them |
| E18 | Dashboard → **Referral sources** breakdown | Grouped counts |

## F. Item 6 — budget approval

| # | Step | Expected |
|---|---|---|
| F1 | Raise a requisition, leave both budgets empty | No chip. Behaves exactly as before this phase |
| F2 | Enter **only** the management figure | Chip **Budget pending**; the **department head** is notified |
| F3 | Enter both, **equal** | Chip **Matched** |
| F4 | Enter both, **different** | Chip **Budget mismatch**; the form shows the difference live |
| F5 | Check notifications | HR, MD **and** the creator are told, with **both figures and the delta in the message** |
| F6 | HR reviews and forwards the mismatched one | **Allowed with no remark** — HR forwards, it does not decide the money |
| F7 | As MD, open it | The dialog shows sanctioned vs approved **side by side** with the delta |
| F8 | Approve with **no** remark | Refused — *"the budgets do not match"* |
| F9 | Approve **with** a remark | **Goes through.** A mismatch warns; it never blocks |
| F10 | Re-open it | Still reads Mismatch — approving does not erase the disagreement |
| F11 | Correct the two figures to match | Chip flips to **Matched** immediately, with no migration |
| F12 | Reports → Requisitions | A `Budget` column, computed per row |

## G. Item 7 — replacement, sanction and escalation

| # | Step | Expected |
|---|---|---|
| G1 | HRMS → **Sanctioned Strength** (admin) | Table + a panel explaining that *no figure* means escalation |
| G2 | Set Ops/Analyst = 4 | Row shows Sanctioned 4, **Actual counted live** from employee profiles |
| G3 | Mark one of those employees **Resigned** | Actual drops by one on reload — nothing was stored |
| G4 | Raise a requisition for Ops/Analyst, 1 vacancy | The form shows Sanctioned / Filled / Committed / Available live |
| G5 | Raise it while within sanction | No amber warning |
| G6 | Set the sanction to 1 and raise another | Amber: *"exceeds the sanctioned strength and will be escalated… MD approval is mandatory"* |
| G7 | Check notifications at raise time | The raiser **and** MD are told, **with the figures** — not after HR review |
| G8 | Choose **Replacement**, name nobody | Refused |
| G9 | Choose Replacement, name somebody, no reason | Refused |
| G10 | Complete it | **Replacement** badge on the row |
| G11 | Edit it and clear the reason | Refused — the rule is re-checked against the merged record |
| G12 | HR forwards an **in-sanction** requisition | Goes **straight to Pending MD Approval** — the old chain, unchanged |
| G13 | HR forwards the **over-sanction** one | Goes to **Pending Escalation**; the chain is built from the raiser's reporting line |
| G14 | Open it | A vertical stepper shows each rung and who has acted |
| G15 | Check notifications | Rung 1 is notified, with the sanction figures |
| G16 | As a **different** manager (not that rung, not MD), try to approve | Refused — *"Only they, or the MD"* |
| G17 | As rung 1, approve | Stays **Pending Escalation**, advances to level 2; rung 1 shows Approved |
| G18 | **Try to jump to MD approval now** | **409.** MD approval is not reachable from escalation |
| G19 | As the last rung, approve | Now **Pending MD Approval**; MD is notified the chain is complete |
| G20 | As MD, approve | **Approved.** This is the only path to Approved |
| G21 | Reject at an escalation step with no reason | Refused |
| G22 | Reject with a reason | Requisition **and its JD** are rejected |
| G23 | Raise one as a user with **no reporting manager**, HR forwards | Routes **straight to MD** — never auto-approved. The audit trail records why |
| G24 | Delete a sanctioned figure | Warns that future requisitions for that position will be escalated |
| G25 | Approve two requisitions for one position, then raise a third | The **committed** count includes the first two — five requisitions for one seat cannot each pass |

## H. Regression — nothing outside HRMS moved

| # | Step | Expected |
|---|---|---|
| H1 | Log in as **superadmin**, **admin**, **clientadmin**, **clientuser** in turn | Each sees their correct sidebar; nothing new appears for a plain clientuser |
| H2 | Dashboard, Calendar, Tasks, TPMS, ORM, Reports, Settings, Profile | All render; **browser console clean** |
| H3 | Create a task | Works |
| H4 | Create a calendar event | Works |
| H5 | Open a TPMS form | Works |
| H6 | Open an ORM sheet | Works |
| H7 | Load the notification bell | Works |
| H8 | Watch the server log through all of the above | **Zero 5xx** |
| H9 | Existing HRMS flows: raise → post → apply → screen → assess → interview → offer → onboard | Unchanged end to end |
| H10 | An offer link issued **before** this phase | Still opens |
