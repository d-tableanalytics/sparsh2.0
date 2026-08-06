# HRMS Phase 1 — Manual Test Script

> Frontend + end-to-end verification. The backend is covered by two automated harnesses;
> this script covers what they cannot reach — rendering, navigation and browser behaviour.
> Follows the `docs/TPMS_TEST_PLAN.md` convention.
>
> **Prerequisites:** backend running (`uvicorn main:app --reload` from `backend/`),
> frontend running (`npm run dev` from `frontend/`), and four test accounts:
> a **superadmin**, a **staff admin**, a **clientadmin** of Company A, and a **clientuser**
> of Company A with `governance_role = "HR"`.

## Automated suites (run first — both must be green)

```
cd backend
venv/Scripts/python.exe -m app.services.hrms.tests.test_phase1_foundation    # expect 95/95, exit 0
venv/Scripts/python.exe -m app.services.hrms.tests.test_phase1_integration   # expect 43/43, exit 0
```

---

## A. Module toggle (superadmin)

| # | Step | Expected |
|---|---|---|
| A1 | Log in as superadmin → Companies → open Company A | Header shows four toggles: ORM · TPMS · Task Mgmt · **HRMS** |
| A2 | Observe the HRMS toggle on a company never enabled | Renders **off** (opt-in default) |
| A3 | Click the HRMS toggle | Turns on; success toast *"HRMS enabled for {company}"* |
| A4 | Reload the page | Still on — persisted |
| A5 | DevTools → Network on toggle | `PATCH /api/companies/{id}/hrms-access` → **200**, body `{hrms_enabled:true}` |
| A6 | Toggle off, then on again | Both succeed; no console errors |
| A7 | Confirm other toggles unaffected | ORM/TPMS/Task Mgmt keep their prior state |

## B. Sidebar visibility

| # | Step | Expected |
|---|---|---|
| B1 | As superadmin, view the sidebar | **HRMS** entry visible (internal staff always) |
| B2 | As staff admin | HRMS visible |
| B3 | As clientuser of Company A (HRMS **ON**) | HRMS visible |
| B4 | Turn HRMS **OFF** for Company A; log in as that clientuser | HRMS **absent** from the sidebar |
| B5 | Collapse the sidebar (mouse out) | HRMS shows its icon; hover reveals the tooltip |
| B6 | Confirm ordering | HRMS sits between TPMS and Reports |

## C. Route access

| # | Step | Expected |
|---|---|---|
| C1 | HRMS ON — click the sidebar entry | Lands on `/hrms`, module home renders |
| C2 | Navigate to `/hrms/entry` directly | Redirects to `/hrms` |
| C3 | **Hard-refresh (Ctrl-F5) on `/hrms`** as a clientuser | Brief *"Loading…"*, then the module renders. **Must NOT bounce to `/`** — this is Finding #2 |
| C4 | Repeat C3 five times | Stays on `/hrms` every time |
| C5 | HRMS OFF — type `/hrms` in the address bar | Redirects to `/` (unreachable by URL) |
| C6 | HRMS OFF — DevTools Network | `GET /api/hrms/health` → **403**, detail *"…not enabled for your company…"* |
| C7 | Log out while on `/hrms` | Redirects to `/login`, no console error |

## D. Capability-driven rendering

| # | Step | Expected |
|---|---|---|
| D1 | As superadmin on `/hrms` | Role tile = `admin`; Scope = *All companies (internal)*; Capabilities = **3** |
| D2 | As clientadmin (Company A) | Role = `md`; Scope = the company id; chips include `module.admin` |
| D3 | As clientuser + governance_role HR | Role = `hr`; chips include `audit.read`, **exclude** `module.admin` |
| D4 | As clientuser with no governance_role | Role = `employee`; exactly one chip, `module.access` |
| D5 | Compare each against `GET /api/hrms/health` in Network | UI matches the server response exactly — no field derived client-side |

## E. States and theming

| # | Step | Expected |
|---|---|---|
| E1 | Throttle the network to Slow 3G, load `/hrms` | Spinner + *"Loading HRMS…"*, no layout jump |
| E2 | Stop the backend, reload `/hrms` | Red error panel with a **Try again** button |
| E3 | Restart the backend, click **Try again** | Content loads; no reload needed |
| E4 | Toggle light ⇄ dark theme | All HRMS surfaces re-theme; no hardcoded colours; text stays legible |
| E5 | Resize to 375px / 768px / 1440px | Tiles reflow 1→3 columns; no horizontal scroll |
| E6 | Console across all of the above | **Zero errors and zero React warnings** |

## F. Regression — existing modules must be untouched

| # | Module | Check | Expected |
|---|---|---|---|
| F1 | Task Management | Open, create a task | Works; task appears |
| F2 | Calendar | Open, create an event | Works; event appears |
| F3 | TPMS | Open dashboard + a form | Renders and submits |
| F4 | ORM | Open the ORM sheet | Renders |
| F5 | Reports | Open `/admin/reports` | Renders |
| F6 | Notifications | Open the bell | Loads |
| F7 | User Management | `/admin/users` lists users | Unchanged |
| F8 | Company Details | ORM/TPMS/Task Mgmt toggles | All still work |
| F9 | Media Library | Opens | Renders |
| F10 | Support Engine | Opens | Renders |
| F11 | Console throughout F1–F10 | | No new errors |

## G. Permission regression (per role)

| # | Role | Expected sidebar |
|---|---|---|
| G1 | superadmin | All modules incl. Companies, Reports, HRMS |
| G2 | staff admin | No Companies; HRMS present |
| G3 | clientadmin (HRMS on) | Client modules + HRMS; **no** admin links |
| G4 | clientuser (HRMS off) | Client modules; **no** HRMS |

## H. Database integrity

```
cd backend
venv/Scripts/python.exe -c "
import asyncio
from app.db.mongodb import connect_to_mongo, db_connection
async def go():
    await connect_to_mongo()
    db = db_connection.db
    names = sorted(await db.list_collection_names())
    print('HRMS collections:', [n for n in names if n.startswith('hrms_')])
    for c in [n for n in names if n.startswith('hrms_')]:
        print(' ', c, sorted((await db[c].index_information()).keys()))
    print('total collections:', len(names))
asyncio.run(go())"
```

| # | Check | Expected |
|---|---|---|
| H1 | HRMS collections | Exactly `hrms_audit_log`, `hrms_counters` |
| H2 | `hrms_audit_log` indexes | `_id_`, `by_entity`, `by_company_recent`, `by_actor_recent` |
| H3 | `hrms_counters` indexes | `_id_`, `by_scope` |
| H4 | Restart the backend, re-run | **Identical** index counts — provisioning is idempotent |
| H5 | Toggle HRMS for a company, re-run | An `hrms_audit_log` row appears with `action: "hrms module enabled"` |
| H6 | Non-HRMS collections | Count and names unchanged from before Phase 1 |

---

## Sign-off

- [ ] Both automated suites green (95/95 and 43/43)
- [ ] Sections A–H pass
- [ ] No console errors anywhere
- [ ] No backend 5xx
- [ ] Every existing ERP module verified working (F1–F11)

**Tester:** ______________  **Date:** ______________  **Result:** PASS / FAIL
