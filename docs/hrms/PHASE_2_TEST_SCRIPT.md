# HRMS Phase 2 — Manual Test Script

> Frontend + end-to-end verification for the employee master. Backend logic is covered by
> two automated harnesses; this script covers rendering, navigation and browser behaviour.
>
> **Prerequisites:** backend + frontend running; HRMS enabled for **Company A**; accounts for
> a **superadmin**, a **staff admin**, a **clientadmin** of Company A, a **clientuser with
> `governance_role = "HR"`**, a **clientuser with `governance_role = "HOD"`** who is the
> reporting manager of at least one person, and a plain **clientuser (IMPLEMENTOR)**.

## Automated suites (run first — all four must be green)

```
cd backend
venv/Scripts/python.exe -m app.services.hrms.tests.test_phase1_foundation    # 96/96
venv/Scripts/python.exe -m app.services.hrms.tests.test_phase1_integration   # 43/43
venv/Scripts/python.exe -m app.services.hrms.tests.test_phase2_employee      # 123/123
venv/Scripts/python.exe -m app.services.hrms.tests.test_phase2_integration   # 54/54
```

---

## A. Navigation

| # | Step | Expected |
|---|---|---|
| A1 | As HR, expand the HRMS sidebar group | Sub-items: Overview · Employees · Departments · Designations |
| A2 | As a plain IMPLEMENTOR | Only Overview · Employees (masters hidden) |
| A3 | Click each sub-item | Correct screen; the active item highlights |
| A4 | Hard-refresh on `/hrms/employees` | Page renders; **no bounce to `/`** |
| A5 | Deep-link `/hrms/departments` directly | Renders |
| A6 | Browser back/forward across HRMS screens | State restores; no console error |

## B. Departments master (as HR)

| # | Step | Expected |
|---|---|---|
| B1 | Open Departments | Empty state, or existing rows |
| B2 | Type `Sales`, click Add | Row appears; success toast |
| B3 | Add `Sales` again | Error toast *"Department 'Sales' already exists."* |
| B4 | Add `sales` (lowercase) | Same 409 — dedupe is case-insensitive |
| B5 | Add `  Field   Ops  ` | Saved as `Field Ops` — trimmed and collapsed |
| B6 | Add an empty name | Add button disabled |
| B7 | Rename a row (pencil → type → Enter) | Renamed; toast |
| B8 | Press Escape while renaming | Cancels, keeps the original |
| B9 | Click the Active pill | Toggles to Inactive and back |
| B10 | Delete an **unused** department | Confirm → deleted |
| B11 | Delete a department **assigned to an employee** | Refused with *"…assigned to N employee(s). Reassign them first, or set it inactive…"* |
| B12 | Click **Suggest from directory** | Panel lists real values with counts; already-added ones are dimmed |
| B13 | Click a suggestion | Created; chip becomes dimmed; **no other suggestion is auto-created** |
| B14 | Repeat B1–B13 on Designations | Identical behaviour |

## C. Employee directory (as HR)

| # | Step | Expected |
|---|---|---|
| C1 | Open Employees | Table: Employee · Code · Department · Designation · Status · **Base salary** |
| C2 | Observe the count in the subtitle | Matches the company's user count |
| C3 | Type a partial name in search | Filters after ~300 ms (debounced, not per keystroke) |
| C4 | Search `Eve(` (regex metacharacter) | No results, **no crash** |
| C5 | Filter by department | Only that department's people |
| C6 | Filter by status | Filtered correctly |
| C7 | Combine search + both filters | All applied together |
| C8 | Clear filters | Full list returns |
| C9 | With >50 employees, use pagination | Page counter correct; arrows disable at the ends |
| C10 | Click a row | Opens that employee's profile |
| C11 | Employees with no HR profile | Still listed; legacy department/designation shown greyed |

## D. Add employee (as HR)

| # | Step | Expected |
|---|---|---|
| D1 | Click **Add employee** | Modal; user dropdown lists only users **without** a profile |
| D2 | Read the helper text | Explains employee records extend existing users |
| D3 | Submit with no user selected | Button disabled |
| D4 | Select a user, set department + joining date, submit | Created; toast; appears in the directory |
| D5 | Re-open the modal | That user is **no longer** in the dropdown |
| D6 | Check the new row's Code column | Auto-minted `EMP-YYYY-NNN` |
| D7 | When every user has a profile | *"Every user in this company already has an employee profile."* |

## E. Employee profile

| # | Step | Expected |
|---|---|---|
| E1 | Open a profile as HR | Four tabs: Job · Personal · Statutory & Bank · Reporting |
| E2 | Job tab | Email/mobile are **read-only** (owned by User Management) |
| E3 | Change status → Save | Toast; value persists after reload |
| E4 | Enter PAN `ABC123` → Save | 422 *"PAN is not valid (e.g. ABCDE1234F)."* |
| E5 | Enter PAN `abcde1234f` → Save | Accepted, stored uppercase |
| E6 | Enter Aadhaar `1234` → Save | 422 |
| E7 | Enter IFSC `hdfc0001234` → Save | Accepted, uppercased |
| E8 | Bank account `12AB34` → Save | 422 *"digits only"* |
| E9 | Joining date **after** resignation date | 422 *"…cannot be after…"* |
| E10 | Set resignation earlier than an already-saved joining date | 422 — validated against the stored value, not only the form |
| E11 | Negative salary → Save | 422 |
| E12 | Reporting tab | Manager chain (indented) + direct reports grid |
| E13 | Click a direct report | Navigates to their profile |
| E14 | Employee with no manager | *"No reporting manager set."* |
| E15 | Profile with no HR record yet | Blue banner: *"This person has no HR profile yet…"*; saving creates it |

## F. Permissions — the critical section

| # | Role | Step | Expected |
|---|---|---|---|
| F1 | **HOD** | Open Employees | Sees **only** their department + direct reports |
| F2 | **HOD** | Look for the salary column | **Absent entirely** |
| F3 | **HOD** | DevTools → Network → the `/employees` response | **No `base_salary` key on any row**; `salary_visible: false` |
| F4 | **HOD** | Open a profile | Fields disabled; no Save button |
| F5 | **HOD** | Open Departments | Read-only: no Add box, no edit/delete icons |
| F6 | **HOD** | URL directly to an out-of-scope employee | 404-style error, not their data |
| F7 | **IMPLEMENTOR** | Sidebar | No Departments/Designations |
| F8 | **IMPLEMENTOR** | URL directly to `/hrms/employees` | Error panel — API returns 403 |
| F9 | **IMPLEMENTOR** | `GET /api/hrms/employees/me` in DevTools | **200 with their own record incl. salary** |
| F10 | **clientadmin (MD)** | Everything | Full access incl. salary |
| F11 | **staff admin** | Open Employees | Company selector appears; salary column **absent** |
| F12 | **staff admin** | Try to edit salary on a profile | Field disabled / 403 |
| F13 | **superadmin** | Everything | Full access incl. salary |

## G. Company scoping (internal staff)

| # | Step | Expected |
|---|---|---|
| G1 | As staff admin, open Employees | Company dropdown in the header |
| G2 | Switch company | Directory reloads with that company's people |
| G3 | Only one HRMS company exists | Static label, not a dropdown |
| G4 | As HR (client), look for the selector | **Absent** — pinned server-side |
| G5 | As HR, call `/api/hrms/employees?company_id=<other>` in DevTools | Returns **your own** company's data, never the other's |

## H. States & theming

| # | Step | Expected |
|---|---|---|
| H1 | Throttle to Slow 3G, load Employees | Spinner + *"Loading employees…"* |
| H2 | Stop the backend, reload | Red error panel with **Try again** |
| H3 | Restart backend, click Try again | Loads without a page reload |
| H4 | Filter to something with no matches | *"No employees match"* + *"Try clearing the filters."* |
| H5 | Toggle light ⇄ dark | All Phase 2 screens re-theme; no hardcoded colours |
| H6 | 375px / 768px / 1440px | Table scrolls horizontally inside its container; **page never scrolls sideways** |
| H7 | Console throughout | **Zero errors, zero React warnings** |

## I. Regression — existing modules

| # | Module | Expected |
|---|---|---|
| I1 | Task Management — create a task | Works |
| I2 | Calendar — create an event | Works |
| I3 | TPMS — dashboard + a form | Works |
| I4 | ORM sheet | Renders |
| I5 | Reports | Renders |
| I6 | **User Management** — open, edit a user's name | Works; **HRMS shows the new name immediately** (no sync step) |
| I7 | Company Details — all four module toggles | All work |
| I8 | Notifications bell | Loads |
| I9 | Console throughout | No new errors |

## J. Database integrity

```
cd backend
venv/Scripts/python.exe -c "
import asyncio
from app.db.mongodb import connect_to_mongo, db_connection
async def go():
    await connect_to_mongo()
    db = db_connection.db
    for c in sorted(n for n in await db.list_collection_names() if n.startswith('hrms_')):
        print(c.ljust(26), sorted((await db[c].index_information()).keys()))
    for coll in ('staff','learners'):
        n = await db[coll].count_documents({'\$or':[{'base_salary':{'\$exists':True}},{'employee_code':{'\$exists':True}}]})
        print(f'{coll} polluted with HR fields:', n, '(must be 0)')
asyncio.run(go())"
```

| # | Check | Expected |
|---|---|---|
| J1 | Collections | `hrms_audit_log`, `hrms_counters`, `hrms_departments`, `hrms_designations`, `hrms_employee_profiles` |
| J2 | `hrms_employee_profiles` indexes | `uniq_user`, `uniq_company_code`, `by_company_status`, `by_company_department` |
| J3 | **Identity pollution** | **0 for both `staff` and `learners`** |
| J4 | Restart, re-run | Identical index counts — idempotent |
| J5 | After editing a profile | `hrms_audit_log` has an `employee profile updated` row |
| J6 | After a salary change | A separate `employee salary changed` row with old → new |

---

## Sign-off

- [ ] All four automated suites green (96 / 43 / 123 / 54 = **316**)
- [ ] Sections A–J pass
- [ ] **F3 verified in DevTools** — salary genuinely absent from the payload, not just hidden
- [ ] **G5 verified** — cross-tenant query param does not leak
- [ ] **J3 verified** — identity collections unpolluted
- [ ] No console errors; no backend 5xx
- [ ] Every existing ERP module still working (I1–I9)

**Tester:** ______________  **Date:** ______________  **Result:** PASS / FAIL
