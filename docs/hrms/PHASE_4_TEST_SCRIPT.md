# HRMS Phase 4 — Manual Test Script

> Job postings and the **public application surface**. Section D is a security walkthrough —
> please run it in full, ideally in a private/incognito window with no session.
>
> **Prerequisites:** HRMS enabled for Company A, with at least one **Approved** job
> description (raise a requisition → HR forwards → MD approves). Accounts: **HR**, **HOD**,
> plain **clientuser**, **staff admin**.

## Automated suites (all nine must be green)

```
cd backend
for t in test_capability_parity test_phase1_foundation test_phase1_integration \
         test_phase2_employee test_phase2_integration \
         test_phase3_requisition test_phase3_integration \
         test_phase4_posting test_phase4_public_security; do
  venv/Scripts/python.exe -m app.services.hrms.tests.$t
done
# expect 6 / 96 / 46 / 123 / 55 / 108 / 59 / 118 / 51  =  662
```

---

## A. Publishing (as HR)

| # | Step | Expected |
|---|---|---|
| A1 | HRMS → Job Postings → **New posting** | Modal opens |
| A2 | Job-description dropdown | Lists **only Approved** JDs |
| A3 | With no approved JD | Explanatory note, not an empty dropdown |
| A4 | Select 3 platforms (LinkedIn, Naukri, Career Page) | Each gets its own config block |
| A5 | Leave all on "Generate form link" | Each shows a **different** previewed `/apply/XX-XXXXXX` URL |
| A6 | Switch Naukri to "Paste external link" | URL box appears + **red warning** that applications won't appear here |
| A7 | Enter `naukri.com/job` (no scheme) and publish | Error naming the platform and requiring `http(s)://` |
| A8 | Enter `javascript:alert(1)` | Rejected |
| A9 | Fix to `https://naukri.com/job`, publish | Toast: *"Published to 3 platforms"* |
| A10 | Check the grid | **3 separate cards**, one per platform, each with its own code |
| A11 | Compare the LinkedIn card's link to the A5 preview | **Identical** — the previewed code is the stored code |
| A12 | Naukri card | Shows the external URL + red warning; has an open-in-new-tab icon |
| A13 | Tick "Require an assessment" on a new posting | Card shows *"Assessment required"* |

## B. Lifecycle & counts

| # | Step | Expected |
|---|---|---|
| B1 | Click Copy on an auto card | Tick appears; clipboard holds `…/apply/<code>` |
| B2 | Click Copy on the external card | Clipboard holds the **external URL**, not an `/apply/` link |
| B3 | Pause a posting → refresh | Status **Paused**; button becomes "Set live" |
| B4 | Close a posting | Status **Closed** |
| B5 | Set an expiry in the past (via API) and reload | Reads **Expired** without any cron job |
| B6 | KPI tiles | Live count, total applications, distinct channels |
| B7 | Delete a posting with applications | Confirm says applications are kept; card goes, **candidates remain** |

## C. The public application (incognito, logged out)

| # | Step | Expected |
|---|---|---|
| C1 | Paste an **auto** posting's link into a private window | Job ad renders — **no login redirect** |
| C2 | Look at the page chrome | **No sidebar, no ERP navigation, no branding** — standalone page |
| C3 | Ad content | Title, department, location, experience, responsibilities, skills, benefits |
| C4 | Submit with an empty name | Blocked |
| C5 | Enter `not-an-email` | Rejected — *"Please enter a valid email address."* |
| C6 | Enter phone `abc` | Rejected |
| C7 | Leave the declaration unticked | Rejected — *"Please confirm…"* |
| C8 | Attach a `.exe` as resume | **415** — *"that file type is not accepted"* |
| C9 | Attach a file >15 MB | Rejected client-side, and by the server if forced |
| C10 | Attach 11 certificates | Rejected — max 10 |
| C11 | Complete correctly with a PDF resume, submit | Success screen + **reference `CAN-…`** |
| C12 | Submit the **same email again** | *"You have already applied"* + the **same reference** — not an error, not a second record |
| C13 | Submit with the same **phone**, different email | Also detected as duplicate |
| C14 | Open an **external** posting's link | **Redirects** to the external site |
| C15 | Open a **paused/closed** posting's link | *"This position is no longer accepting applications."* |
| C16 | Open `…/apply/ZZ-ZZZZZZ` | *"This application link is not valid."* |
| C17 | As HR, check Notifications | Notified of the new application |
| C18 | Check the requisition's assignee | Also notified |

## D. Security walkthrough — please run all of it

| # | Step | Expected |
|---|---|---|
| D1 | In a private window, open `/api/hrms/postings` directly | **401** |
| D2 | Open `/api/hrms/employees`, `/api/hrms/requisitions`, `/api/hrms/jd` | **401** each |
| D3 | Open `/api/hrms/public/apply/<valid code>` | **200** — no token needed |
| D4 | Try `…/apply/{"$ne":null}` | 404, generic message |
| D5 | Try `…/apply/../../etc/passwd` | 404, generic message |
| D6 | Try `…/apply/<script>alert(1)</script>` | 404, **no script executes** |
| D7 | Compare D4/D5 responses to `…/apply/ZZ-ZZZZZZ` | **Byte-identical** — not an existence oracle |
| D8 | Inspect the public ad JSON in DevTools | **No** `company_id`, `request_no`, `jd_no`, `requires_assessment`, `posted_by` |
| D9 | Inspect the submit response | Only `ok`, `duplicate`, `reference`, `message` |
| D10 | POST an application with an extra `"application_status":"Selected"` field | Ignored — candidate is still **Applied** |
| D11 | POST 6 applications from one IP within an hour | 6th returns **429** with `Retry-After` |
| D12 | Log in as HR in one tab, open a public apply link in another | Public request carries **no Authorization header** (check DevTools) |
| D13 | Enter `<script>alert(1)</script>` as your name and submit | Stored inert; rendering it in the HRMS UI (Phase 5) shows text, no alert |
| D14 | Submit a form that fails validation but has a valid resume attached | **No file lands in S3** |

## E. States & theming

| # | Step | Expected |
|---|---|---|
| E1 | Slow 3G on the public page | *"Loading this role…"* |
| E2 | Stop the backend, load a public link | *"Link unavailable"* card, not a blank page |
| E3 | Postings grid with no data | *"No postings yet"* + guidance |
| E4 | Light ⇄ dark on Job Postings | Re-themes (the public page is intentionally light-only — it is not part of the ERP UI) |
| E5 | Public page at 375 px | Form usable; no horizontal scroll |
| E6 | Console on all pages | **Zero errors** |

## F. Regression

| # | Module | Expected |
|---|---|---|
| F1–F5 | Task Management · Calendar · TPMS · ORM · Reports | All work |
| F6 | HRMS Employees / Requisitions / JDs / masters | All work |
| F7 | Log out, then visit any authenticated route | Redirects to `/login` (public routes did not break the guard) |
| F8 | Log in again | Normal |
| F9 | Console | No new errors |

## G. Database

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
| G1 | Collections | 10, incl. `hrms_job_postings`, `hrms_candidates`, `hrms_public_rate_limit` |
| G2 | `hrms_public_rate_limit` | Has a TTL index on `expires_at` |
| G3 | `hrms_candidates` | Indexed on email and phone (duplicate detection) |
| G4 | Publish to 3 platforms | **3** posting docs, 3 distinct codes |
| G5 | After an application | One candidate, `application_status: "Applied"`, `requires_assessment` copied |
| G6 | After a duplicate submit | Still **one** candidate |
| G7 | Candidate `resume` field | Holds an S3 **key**, not an expiring signed URL |
| G8 | After rate-limited requests | Rows in `hrms_public_rate_limit` with `expires_at` |
| G9 | Delete a posting | Posting gone, **candidates remain** |

---

## Sign-off

- [ ] All nine automated suites green (**662**)
- [ ] Sections A–G pass
- [ ] **Section D run in full, in a private window**
- [ ] **D7 verified** — malformed and unknown codes give identical responses
- [ ] **D8 verified** — no internal identifiers in the public payload
- [ ] **D12 verified** — no Authorization header on public requests
- [ ] **D14 verified** — invalid form uploads nothing
- [ ] No console errors; no backend 5xx

**Tester:** ______________  **Date:** ______________  **Result:** PASS / FAIL
