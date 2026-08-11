# Out-of-Scope Findings — discovered while building HRMS

> **Standing rule (owner, Phase 1 close):** work only on the HRMS module. Do not modify,
> fix or refactor any other ERP module. Anything found outside HRMS is **documented here
> and left untouched** until explicitly approved.
>
> **Nothing in this file has been changed.** Each entry records what was observed, the
> impact, and the fix I would recommend *if and when* you approve it.
>
> This register is append-only and carries forward through every HRMS phase.

---

## Status legend

| Status | Meaning |
|---|---|
| 🔴 OPEN | Documented, not fixed, awaiting your decision |
| ⚪ NO ACTION | Documented; recommend leaving as-is |
| ✅ APPROVED | You approved a fix; see the phase report where it landed |

---

## OOS-001 — `delegation_enabled` is stripped from `/users/me`

| | |
|---|---|
| **Module** | Task Management / Delegation |
| **Found in** | Phase 1 |
| **Status** | 🔴 **OPEN** |
| **Severity** | Medium — an enabled module is invisible to the users it was enabled for |

**Observed.** `GET /users/me` declares `response_model=UserResponse`. Pydantic v2 drops any
field not declared on the model. `routes/user.py` sets `current_user["delegation_enabled"]`,
but `UserResponse` (in `models/user.py`) never declares it, so it is discarded before the
response is sent. The JWT does not carry it either (`routes/auth.py` payload confirmed), so
there is no second source.

**Verified, not inferred:**
```
pydantic 2.10.5
input      {'a':1, 'orm_enabled':False, 'delegation_enabled':True}
serialized {'a':1, 'orm_enabled':False}
```

**Impact.** `utils/taskAccess.js` gates client-side users on
`user.delegation_enabled === true`, which evaluates `undefined === true` → **false**.
Client-side users of a company whose Delegation toggle is **ON** therefore never see the
Task Management module. The toggle appears to work in Company Details but has no effect on
the intended audience.

**Recommended fix (one line, `backend/app/models/user.py`):**
```python
delegation_enabled: Optional[bool] = False  # Company-level Task Management access (opt-in)
```

**Why it is not applied.** Outside HRMS, and **business-visible**: applying it would
immediately grant Task Management to every client company whose toggle is already on. That
should be a deliberate product decision with its own regression pass, not a side effect of
an HRMS phase.

**Note.** HRMS declares its own `hrms_enabled` on the same model, so HRMS is unaffected.
A permanent regression guard in `test_phase1_foundation.py` asserts the HRMS flags survive
serialisation — it does **not** assert anything about `delegation_enabled`, deliberately, so
this register stays the single owner of that decision.

---

## OOS-002 — TPMS route guard may eject client users on hard refresh

| | |
|---|---|
| **Module** | TPMS |
| **Found in** | Phase 1 |
| **Status** | 🔴 **OPEN** (unverified against a live client session) |
| **Severity** | Low–Medium, if confirmed |

**Observed.** `AuthProvider` seeds `user` from the JWT immediately and merges the full
profile from `/users/me` in the background. Per-company module flags (`tpms_enabled`) exist
only on the profile, never in the token. `features/tpms/access.js` gates with
`user.tpms_enabled === true`, and `RequireTpms` redirects to `/` when that is falsy.

For the window between first render and profile merge, an entitled client user has
`tpms_enabled === undefined`, which reads as "denied".

**Impact (if confirmed).** A client-side TPMS user hard-refreshing or deep-linking into
`/tpms/*` could be redirected out of the module before their profile arrives.

**Not confirmed.** I did not test this against a live client account with TPMS enabled —
doing so is TPMS work. The reasoning is from reading `AuthContext.jsx`, `access.js` and
`TpmsGate.jsx`; the race may be too fast to observe in practice, or may not reproduce at all.

**Recommended fix (if confirmed).** The tri-state pattern HRMS now uses: distinguish
"explicitly denied" (`=== false`) from "not known yet" (absent) and wait rather than
redirect. See `features/hrms/access.js` → `hrmsAccessState()` and `HrmsGate.jsx` for a
working reference implementation.

**HRMS is immune** — this was Finding #2 in the Phase 1 report and is fixed within HRMS.

---

## OOS-003 — Assistant test harnesses require a live DB connection

| | |
|---|---|
| **Module** | Assistant |
| **Found in** | Phase 1 (regression suite) |
| **Status** | ⚪ **NO ACTION** — pre-existing, cosmetic |
| **Severity** | Low — affects test ergonomics only, not runtime |

**Observed.** `app/assistant/tests/test_phase{1,3,4}*.py` exit non-zero with:
```
HTTPException: 503: Database connection is not available…
```
They call `get_collection()` without first calling `connect_to_mongo()`.

**Proven pre-existing.** Verified by `git stash`, running against clean baseline `458c929`,
and restoring — identical failure, identical line, with HRMS entirely absent:
```
BASELINE (458c929, HRMS stashed): EXIT=1  → 503 at mongodb.py get_db()
WITH PHASE 1:                     EXIT=1  → 503 at mongodb.py get_db()
```
Not caused by HRMS. Recorded so future phases don't mistake it for a regression.

**Recommendation.** Leave it. Their earlier sections pass and print results; only the
DB-touching sections abort. Fixing it means editing Assistant tests — out of scope, and
no runtime impact.

---

## OOS-004 — Two pre-existing frontend lint errors

| | |
|---|---|
| **Module** | Calendar / shared components |
| **Found in** | Phase 1 |
| **Status** | ⚪ **NO ACTION** |
| **Severity** | Trivial |

**Observed.** `npx eslint src` reports 2 errors, both `react-refresh/only-export-components`:
- `src/components/calendar/ReminderModal.jsx:17`
- `src/components/common/StyledSelect.jsx:20`

Neither file was touched by HRMS. HRMS's own files contribute **0 errors**. Recorded so the
"0 new errors" claim in each phase report has a stated baseline.

**Recommendation.** Leave them, or fold into unrelated cleanup. The same rule fired on
`HrmsContext.jsx`; HRMS resolved it with the disable comment already used in
`context/AuthContext.jsx`.

---

## OOS-005 — Assistant liveness/readiness probes are unauthenticated

| | |
|---|---|
| **Module** | Assistant |
| **Found in** | Phase 4 (by the new whole-app authentication sweep) |
| **Status** | ⚪ **NO ACTION** — pre-existing and deliberate |
| **Severity** | Low — mild configuration disclosure |

**Observed.** Phase 4 added a security test that enumerates every authenticated `GET` route
in the application and asserts none answers without a token. It swept 87 routes and found
two that do:

```
/api/assistant/health  -> 200  {"status":"ok","enabled":true,"phase":"4"}
/api/assistant/ready   -> 503  {"ready":false,"checks":{"database":false,"openai_key":true,
                                "enabled":true},"flags":{...}}
```

**Deliberate, not a defect.** `app/assistant/router.py` documents these in its own docstring
as *"liveness (no dependencies)"* and *"readiness (DB + key + flags)"*. Orchestration probes
have to answer without credentials to be useful to Docker or a load balancer.

**The mild concern.** `/ready` tells an anonymous caller whether the database is reachable,
whether an OpenAI key is configured, and which feature flags are on. That is more internal
state than a readiness probe strictly needs, and in a compromise it is useful reconnaissance.

**Recommendation (if you ever want it tightened).** Keep `/health` fully public — it returns
nothing sensitive. Reduce `/ready` to a bare `{"ready": bool}` with the detail behind auth,
or bind it to the internal Docker network only. Neither is urgent.

**Not changed.** Assistant module, out of scope. The HRMS security sweep allow-lists these
two by **exact path** (never by prefix), so any *future* `/api/assistant/*` route is still
swept and would fail the test.

---

## Shared-file changes HRMS *has* made (for your visibility)

Not out-of-scope findings — these are changes HRMS required and made deliberately. Listed
here so the whole shared-surface footprint sits in one place. All additive; full
justification in [PHASE_1_REPORT.md](PHASE_1_REPORT.md) §2.

| File | Change | HRMS-necessary because |
|---|---|---|
| `backend/main.py` | import + mount `hrms.router` | The only way to serve the module |
| `backend/app/db/mongodb.py` | `_ensure_hrms_collections` + call | The only provisioning point; mirrors the two `_ensure_*` already there |
| `backend/app/models/company.py` | `+ hrms_enabled: bool = False` | The per-company toggle |
| `backend/app/routes/user.py` | surface `hrms_enabled` on `/me` | The client cannot gate without it |
| `backend/app/models/user.py` | `+ hrms_enabled`, `+ governance_role` | Both are stripped otherwise (OOS-001 root cause). `governance_role` drives the HRMS frontend role map |
| `backend/app/routes/company.py` | `PATCH /{id}/hrms-access` | The toggle endpoint; mirrors `tpms-access` |
| `frontend/src/App.jsx` | HRMS routes | Additive routes only |
| `frontend/src/components/layout/Sidebar.jsx` | HRMS nav entry | Additive entry |
| `frontend/src/pages/CompanyDetails.jsx` | HRMS toggle | Fourth `ModuleToggle` beside the existing three |

> ⚠️ **One of these deserves your explicit blessing:** `governance_role` on `UserResponse`.
> It is HRMS-necessary (without it the HRMS frontend cannot distinguish HR from HOD from
> Implementor) and purely additive — every other module ignores unknown fields, and no
> existing behaviour changes. But it does alter a **shared** response model, so if you would
> rather HRMS resolved the ladder some other way, say so and I will rework it inside HRMS.

---

## Status update — Phase 10 (2026-08-10)

**OOS-001 (`delegation_enabled` stripped from `/users/me`) — RESOLVED, outside this work.**
A `delegation_enabled` declaration was added to `UserResponse` by an edit outside the HRMS
scope. No action was needed from HRMS and none was taken.

However, that same edit **removed** the two HRMS declarations (`hrms_enabled`,
`governance_role`) that Phase 1 had added to the same class, which silently locked every
client user out of HRMS. Phase 1's regression guard caught it during Phase 10's S2 run; the
lines were restored alongside `delegation_enabled` (all three coexist) and the guard now
asserts all four module flags stay declared. See PHASE_10_REPORT §3 Finding #2.

**No new out-of-scope findings in Phases 9 or 10.** The register stands at OOS-001…005.

---

## Status update — Phase 11-R (2026-08-11)

**No new out-of-scope findings.** The register stands at OOS-001…005.

Phase 11-R touched no module outside HRMS. Its full shared-surface footprint is two
files, both already on the Phase 1 list above and both extended additively:

| File | Phase 11-R change |
|---|---|
| `frontend/src/App.jsx` | 7 new imports; 1 new public route (`/appointment/:code`); 6 new child routes inside the existing `/hrms` block. No pre-existing route line altered. |
| `frontend/src/components/layout/Sidebar.jsx` | 2 icon imports; 2 entries appended to `HRMS_WORKSPACE`; 4 entries appended to `hrmsSubmodules`. No other nav group touched. |

Three observations were made while working and are recorded here rather than acted on,
because fixing any of them would mean editing a module Phase 11-R has no mandate over.

### OOS-006 — `get_db()` raises `HTTPException(503)`, which makes every caller's error handling a trap

`backend/app/db/mongodb.py:181` raises a **transport-layer** exception type for an
**infrastructure** failure. Any service that legitimately wants to swallow a database
outage — every fire-and-forget path in this codebase — must write `except Exception`, and
any that writes the more precise-looking `except HTTPException: raise` silently converts a
Mongo hiccup into a user-facing 503.

Phase 11-R hit this exactly once, in `assert_link_live`: the guard re-raised the 503 and
turned every candidate-facing public page into an error whenever the database was
unreachable. It was caught by `test_phase4_public_security` and fixed **inside HRMS** by
catching bare `Exception` with a comment explaining why. The general hazard remains for
every other module.

*Suggested fix (not made):* raise a plain `RuntimeError`/`ConnectionError` from `get_db()`
and let the routing layer translate it, so "the database is down" and "this request is
forbidden" stop sharing a type.

### OOS-007 — the HRMS test double silently ignored operators real Mongo supports

`FakeCollection` in `test_phase2_employee.py` — imported by every HRMS test file — did not
implement `$set` inside `find_one_and_update`, did not implement `update_many` at all, and
resolved dotted field paths (`client_share.status`) as literal keys. Each gap fails
**silently**: the service under test appears to work while the write goes nowhere.

Fixed inside HRMS (the file is an HRMS test), and noted here because it is a pattern worth
watching: a fake that no-ops on an unsupported operator is worse than one that raises. The
`aggregate()` implementation in the same class gets this right — it raises
`NotImplementedError` for any stage it does not know — and the write methods should
eventually do the same.

### OOS-008 — `POST /hrms/public/apply/{code}` gained a required field

Not a finding against another module, recorded here for visibility because it is the one
**contract change** in this phase. Item 1 required the "where did you find this job" block
to be mandatory, and a mandatory rule that is only enforced in the browser is not enforced
at all (§3.5). `referral_source` is therefore now required server-side.

Any integration that posts applications directly — there is none known — would need to send
it. The in-repo caller (`ApplyPage.jsx`) and the Phase 4 test fixture were both updated.
