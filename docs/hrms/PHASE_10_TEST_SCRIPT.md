# HRMS Phase 10 — Manual Test Script

> The recruitment dashboard, the funnel, and the detailed reports.
>
> **Prerequisites:** a company with real pipeline history — ideally candidates at several
> different stages, at least one accepted offer, one declined, one draft, and two
> requisitions raised by **different people** (one by HR, one by a HOD).
> Accounts: **HR**, **MD**, **HOD** (who raised a requisition), plain **clientuser**,
> **staff admin**.

## Automated suites (all twenty-one must be green)

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
         test_phase10_analytics test_phase10_integration; do
  venv/Scripts/python.exe -m app.services.hrms.tests.$t
done
# expect 6/100/46/125/55/108/59/118/51/113/58/96/66/98/66/99/78/172/104/155/103 = 1876
```

---

## A. The dashboard

| # | Step | Expected |
|---|---|---|
| A1 | HRMS → **Dashboard** | 8 KPI tiles, positions, offer outcomes, time to hire, 4 breakdowns |
| A2 | Read the subtitle | Shows the active window; defaults to the **last 90 days** |
| A3 | Click **Candidates** | Navigates to the candidate pipeline |
| A4 | Click every other tile | Each lands on the screen that produced its number |
| A5 | Compare **Open requisitions** with the Requisitions page | **Same number** |
| A6 | Compare **Offers sent** with the Offers board | Same, and a **Draft is NOT counted as sent** |
| A7 | Compare **Onboarding** with the Onboarding board | Same |
| A8 | Read the acceptance rate | Percentage of **responded** offers, not of all offers |
| A9 | Time to hire | Median **and** mean, with the number of hires measured |
| A10 | Pick a range with no accepted offers | *"nothing to measure"*, not `0 days` |

## B. The funnel — the heart of this phase

| # | Step | Expected |
|---|---|---|
| B1 | Read the funnel top to bottom | **Every stage ≤ the one above it.** If any stage is larger, stop and report it |
| B2 | Find a candidate at **Offer Accepted** | They are counted in **Interview** and **Selected** too |
| B3 | Take a candidate with a completed interview and drag their stage **back** to *Shortlisted* | The funnel **still counts them at Interview** — evidence outranks the label |
| B4 | Create a **Draft** offer for someone at *Selected* | **Offered does NOT increase** — a draft has not been issued |
| B5 | Send that offer | **Offered increases by 1** |
| B6 | Find a candidate whose offer was **Declined** | Still counted at **Offered** — that stage genuinely happened |
| B7 | Read the two percentages on a row | *"x% of applied"* and *"y% from previous"* — they answer different questions |
| B8 | Pick a range with zero candidates | All zeros, **no division error**, no `NaN`, no `Infinity%` |

## C. Breakdowns

| # | Step | Expected |
|---|---|---|
| C1 | **Where candidates come from** | Sources ranked, largest first, shares sum to ~100% |
| C2 | **By department** / **by role** | Drawn from requisitions |
| C3 | **By platform** | Drawn from job postings |
| C4 | `GET /api/hrms/analytics/breakdown?by=ctc` | **422** |
| C5 | `…?by=can_email`, `…?by=$where` | **422** each |

## D. Date range

| # | Step | Expected |
|---|---|---|
| D1 | Set From/To to a narrow window | Every figure recomputes |
| D2 | Click **Last 90 days** | Resets |
| D3 | Set From **after** To | **422** — start must be on or before end |
| D4 | Set a range wider than ~3 years | **422** — choose 1100 days or fewer |
| D5 | Send `date_from=31-01-2026` via the URL | **422** — YYYY-MM-DD |
| D6 | Set To = **today** | Today's activity **is included** (window runs to end of day) |

## E. Reports

| # | Step | Expected |
|---|---|---|
| E1 | HRMS → **Reports** | Five tabs; Candidates is open |
| E2 | Switch tabs | Columns change; **paging resets to 1** |
| E3 | Page forward, then switch tab | Back to page 1, not page 7 of a different table |
| E4 | Search a candidate name | Narrows |
| E5 | Search `C.*` or `.*` | Treated as **literal text**, not a regex — few or no results, never everything |
| E6 | `GET /api/hrms/reports/learners` | **404 / 422** |
| E7 | `…/reports/staff`, `…/reports/hrms_audit_log`, `…/reports/companies` | All refused |
| E8 | `…/reports/candidates?page=0` and `?page_size=5000` | **422** each |
| E9 | Widen the range until there are no rows | Empty state suggests widening the range |

## F. Export

| # | Step | Expected |
|---|---|---|
| F1 | Click **CSV** | Downloads `hrms_candidates_<from>_to_<to>.csv` |
| F2 | Open it in Excel | Headers are **human labels**; accented names render correctly (BOM) |
| F3 | Click **Excel** | Downloads `.xlsx`; header row is styled and frozen |
| F4 | Compare the file with the on-screen table | Same columns; the file has **all** rows, not just the page |
| F5 | Export a range with >5,000 rows | Toast says *"Exported the first 5,000 of N"*; the file ends with a **NOTE** line |
| F6 | DevTools → the export response headers | `X-Export-Truncated`, `X-Export-Rows`, `X-Export-Total` |
| F7 | `…/export?fmt=exe` | **422** |

## G. Permissions — the most important section

| # | Role | Check | Expected |
|---|---|---|---|
| G1 | **HR** | Dashboard, Reports, both export buttons | All present |
| G2 | **MD** | Same | All present |
| G3 | **HOD** | Dashboard | Readable, **with a notice** saying the figures cover the requisitions they raised |
| G4 | **HOD** | Compare their KPI counts with HR's | **Strictly smaller** — only their own requisitions |
| G5 | **HOD** | Reports | Readable, same notice |
| G6 | **HOD** | Export buttons | **Absent** |
| G7 | **HOD** | `GET /api/hrms/reports/candidates/export` directly | **403** |
| G8 | **plain clientuser** | Dashboard and Reports | **403** on every endpoint |
| G9 | **staff admin** | Reports → Offers | Table loads, **no CTC column at all** |
| G10 | **staff admin** | DevTools → the report payload | **No `ctc` key on any row**, `salary_visible: false` |
| G11 | **staff admin** | Export offers → open the file | **No CTC column, and no CTC value anywhere in it** |
| G12 | **HR** | Export offers | CTC present |
| G13 | **staff admin** | Dashboard without `company_id` | **400** — internal callers must name a company |
| G14 | **HR** | Add `?company_id=<another company>` to any of the five endpoints | **Ignored** — pinned to their own company |

## H. Read-only

| # | Step | Expected |
|---|---|---|
| H1 | `POST /api/hrms/analytics/dashboard` | **405** |
| H2 | `DELETE /api/hrms/reports/candidates` | **405** |
| H3 | Browse every analytics screen, then check the audit log | **No new rows** — analytics never writes |

## I. States & theming

| # | Step | Expected |
|---|---|---|
| I1 | Slow 3G on the dashboard | *"Crunching the numbers…"* |
| I2 | Break one breakdown endpoint (offline mid-load) | KPIs and funnel **still render** — a failed breakdown must not blank the page |
| I3 | Light ⇄ dark | Bars, tiles and tables all re-theme |
| I4 | 375 / 768 / 1440 px | Tables scroll **inside their own container**; the page never scrolls sideways |
| I5 | Console | **Zero errors** |

## J. Regression

| # | Module | Expected |
|---|---|---|
| J1–J5 | Task Management · Calendar · TPMS · ORM · Reports | All work |
| J6 | **`/admin/reports`** (the ERP's own reports) | Unchanged — still loads, still admin-only |
| J7 | HRMS Employees → Onboarding | Every earlier screen works |
| J8 | Public **apply / assess / offer / onboard** in incognito | All four anonymous |
| J9 | **Sign in as a client user and open HRMS** | Works — this is Finding #2's regression. If the module is invisible or you are treated as a plain employee, `UserResponse` has lost its flags again |
| J10 | Console | No new errors |

## K. Database

| # | Check | Expected |
|---|---|---|
| K1 | Collections | **14** — no new collection in this phase |
| K2 | `hrms_candidates` indexes | includes **`by_company_applied`** |
| K3 | `hrms_offers` / `hrms_onboarding` / `hrms_requisitions` | each includes **`by_company_created`** |
| K4 | **Backend startup log** | `[INFO] HRMS index uniq_user on hrms_employee_profiles rebuilt to match the spec` — **Finding #1.** Then confirm `db.hrms_employee_profiles.getIndexes()` shows `uniq_user` with **`sparse: true`** |
| K5 | After K4, onboard a **second** person to Employee ID | **Succeeds** — this is the defect Finding #1 was hiding |
| K6 | Audit log after browsing analytics | Unchanged |

---

## Sign-off

- [ ] All twenty-one automated suites green (**1876**)
- [ ] Sections A–K pass
- [ ] **B1 verified** — the funnel never increases
- [ ] **B3/B4 verified** — evidence outranks a stale status; a draft offer proves nothing
- [ ] **G4/G6/G7 verified** — a hiring manager sees only their own, and cannot export
- [ ] **G10/G11 verified** — CTC absent from the payload *and* the file
- [ ] **F5/F6 verified** — truncation announced in the header and inside the file
- [ ] **J9 verified** — a client user can still open HRMS at all
- [ ] **K4/K5 verified** — the live index is now sparse, and a second employee can be created
- [ ] No console errors; no backend 5xx

**Tester:** ______________  **Date:** ______________  **Result:** PASS / FAIL
