# Sparsh Magic HRMS — Phase 1 FRD v1.1 · Gap Analysis & Step-Wise Change Plan

**Source document:** *Sparsh Magic HRMS | Phase 1 FRD v1.1 — Configurable Employee, Attendance & Payroll* (14 October 2026)
**Codebase reviewed:** branch `BHU_22/9`, HEAD `6798611` ("hrms frd phase1")
**Target branch for this work:** `MANOJ_PHASE1_CHNAGES`
**Prepared:** 18 October 2026

---

## 0. How to read this document

Commit `6798611` already landed a large slice of this FRD (11,595 insertions across 41 files).
This document therefore is **not** a build-from-zero plan. It is:

1. A **section-by-section compliance matrix** (FRD §1–§30) against the real code, with file
   evidence for every verdict.
2. A **gap backlog** of what is genuinely missing or partial.
3. A **step-wise implementation plan** (Step 1 … Step 12), each step scoped to be
   independently committable and testable on `MANOJ_PHASE1_CHNAGES`.

Verdict legend: **DONE** = implemented and testable · **PARTIAL** = implemented but short of
what the §-text asks · **MISSING** = no implementation exists.

> **The matrix in section 2 is the audit as taken on 18 Oct 2026, before any of this plan
> was built.** It is deliberately not rewritten as steps land — it is the baseline the work
> is measured against. What has actually shipped is the status board immediately below.

### Implementation status on `MANOJ_PHASE1_CHNAGES`

| Step | Scope | Status |
|---|---|---|
| 0 | Branch + baseline | **Done** — baseline 82/82 on the Phase 1 suite |
| 1 | Payroll approval matrix (§12, §17, §20) | **Done** — `Cap.PAYROLL_CHECK`, `PayrollRunStatus.CHECKED`, `check_run`/`decide_run` split, configurable matrix, `/payroll/runs/{period}/check`, three-stage UI |
| 12 (part) | Employee master finish (§3, §4) | **Done** — photograph as a first-class field; effective-dated changes registered as a scheduled job |
| 2 | Policy version spine (§26, §28) | **Done** — definition/version/assignment collections, documented priority rule, `config.*` capability family, `/config/policies` endpoints, 28-check suite |
| 3 | Config change approval flow (§27, §30) | **Done** — request/impact/simulate/submit/decide/activate, `config.*` gates, Approval Inbox screen, 29-check suite |
| 4 | Attendance policy migration + designer | Not started |
| 5 | Attendance simulation | Not started |
| 6 | Component lifecycle & proration | Not started |
| 7 | Formula variables & versioning | Not started |
| 8 | Payroll policy versioning | Not started |
| 9 | Attendance snapshot (§8, §18) | **Done** — per-day basis frozen onto each record, lock identity on the run, submit refused when the basis moved, stale banner |
| 10 | Configurable bank file | Not started |
| 11 | Impact + config audit viewers | Not started |

Phase 1 suite now **92/92**. Full HRMS suite: 94 modules pass; 10 fail on a missing `httpx`
in the backend venv and failed identically before this work began.

---

## 1. Current state — what already exists

| Layer | Location |
|---|---|
| Domain models / collection registry / capability map | `backend/app/models/hrms.py` (9,912 lines) |
| HTTP surface | `backend/app/routes/hrms.py` (6,861 lines); FRD Phase-1 block starts at line ~6470 |
| Employee master support | `backend/app/services/hrms_employee_master_service.py` |
| Employee profile composition | `backend/app/services/hrms_employee_service.py` |
| Shift master + employee calendar | `backend/app/services/hrms_shift_service.py` |
| Attendance day / judgement | `backend/app/services/hrms_attendance_service.py`, `hrms_attendance_rules_service.py` |
| Payroll engine | `backend/app/services/hrms_payroll_service.py` (1,559 lines) |
| Formula engine | `backend/app/services/hrms_formula_engine.py` |
| Payslip | `backend/app/services/hrms_payslip_service.py` |
| Bank disbursal | `backend/app/services/hrms_disbursal_service.py` |
| Audit | `backend/app/services/hrms_audit_service.py` |
| Collection provisioning | `backend/app/db/mongodb.py` → `_ensure_hrms_collections` ← `HRMS_INDEXES` |
| Phase-1 regression suite | `backend/app/services/hrms/tests/test_frd_phase1.py` |
| Frontend | `frontend/src/features/hrms/{people,attendance,payroll,admin}/` |

**Data store is MongoDB (Motor/async).** The FRD's ER diagrams (§15, §28) are *conceptual*;
they map onto collections, not SQL tables. Every new entity below is a new collection
declared in `models/hrms.py` and provisioned via `HRMS_INDEXES`.

---

## 2. Section-by-section compliance matrix

### Module scope (§2)

| § | Requirement | Verdict | Evidence / gap |
|---|---|---|---|
| §2 | Employee Information | **DONE** | `hrms_employee_service.py`, `hrms_employee_master_service.py` |
| §2 | Attendance | **PARTIAL** | shift/policy versioning done; *policy designer + rule versioning engine* missing (see §23) |
| §2 | Salary / Compensation | **DONE** | `COLL_SALARY_COMPONENTS`, `COLL_SALARY_STRUCTURES`, effective dating + approval |
| §2 | Payroll | **DONE** | `create_run` → `calculate_payroll` → `submit_run` → `decide_run` → `lock_run` → `close_run` |
| §2 | Disbursal | **DONE** | `hrms_disbursal_service.py`, `COLL_PAYMENT_BATCHES`, `COLL_PAYMENTS` |
| §2 | Payslip | **DONE** | `hrms_payslip_service.py`, versioned template frozen at lock |

### §3 Employee Information — fields to capture

| Field group | Verdict | Note |
|---|---|---|
| Basic Identity | **PARTIAL** | `first/middle/last/display_name`, `employee_code` present. **Photograph is not a first-class employee-master field** — it exists only on the candidate record (`models/hrms.py:4255`) and via the generic document store. |
| Personal | **DONE** | `date_of_birth`, `gender`, `marital_status`, `blood_group`, `nationality` |
| Contact | **DONE** | `personal_mobile`, `official_mobile`, `personal_email`, `official_email` |
| Current / Permanent Address | **DONE** | `current_address`, `permanent_address`, `permanent_same_as_current`; keys in `ADDRESS_KEYS` incl. `district` |
| Emergency Contact | **DONE** | name / relation / phone / `emergency_contact_alt_phone` |
| Employment | **DONE** | `joined_on`, `employee_category`, `employment_status`, `probation_start/end`, `confirmation_date` |
| Organisation | **DONE** | `legal_entity`, `business_unit`, `work_location`, `department_id`, `sub_department` |
| Job | **DONE** | `designation_id`, `grade`, `level`, `job_title`, `cost_centre` |
| Reporting | **DONE** | `reporting_manager_id`, `functional_manager_id` |
| Work Configuration | **DONE** | `shift_code`, `attendance_policy_group`, `weekly_off_pattern`, `holiday_calendar` |
| Bank | **DONE** | name / branch / holder / account / IFSC / type / `bank_effective_from` |
| Statutory IDs | **DONE** | `pan`, `aadhaar`, `uan`, `pf_number`, `esi_number`, `passport`, `driving_license` |
| Salary Linkage | **DONE** | `salary_template`, `payroll_group`, `base_salary` on the profile; `annual_ctc` / `monthly_gross` resolved from the active structure by `structure_summary` and rendered on the profile (corrected 18 Oct — the first pass recorded this as PARTIAL in error) |
| Documents | **DONE** | `COLL_DOCUMENTS` + `COLL_DOCUMENT_TYPES` |
| System / Audit | **DONE** | `COLL_AUDIT_LOG`, created/modified stamps, `COLL_EMPLOYEE_HISTORY` |

### §4 Employee creation / change process — **DONE**

Duplicate check (`find_duplicates`, `EMPLOYEE_DUPLICATE_FIELDS`), configured numbering
(`hrms_id_service.py`), effective-dated scheduling (`record_changes` → `apply_due_changes`,
`cancel_scheduled`).
**One gap (now closed — see Step 12):** `apply_due_changes(company_id)` ran only lazily, on
an employee READ. A change due on the 1st was therefore not in force for a payroll
calculated before anyone happened to open the employee directory. It is now also a
scheduled job (`JOB_EFFECTIVE_DATED`, daily at 01:00, the earliest slot in the table).

### §5 Attendance configuration

| Config | Verdict | Evidence / gap |
|---|---|---|
| Shift | **DONE** | `COLL_SHIFTS`, `SHIFT_PARAMS`, versioned by effective date |
| Grace (daily + monthly buffer) | **DONE** | `daily_grace_minutes`, `monthly_buffer_minutes`, `monthly_buffer()` |
| Weekly Off | **DONE** | pattern list incl. `"Saturday#2"` (2nd Saturday) |
| Holiday Calendar | **DONE** | `COLL_HOLIDAYS`, location/calendar scoped |
| Attendance Source | **PARTIAL** | `ATTENDANCE_SOURCES = ("Manual","Google","API","Biometric","Import","Self")` is declared and stored; Import (`import_biometric`) and Self (`hrms_self_punch_service`) work. **Google and API are enum values with no ingestion path.** §19 flags this as unconfirmed. |
| Attendance Policy Group | **PARTIAL** | used as an *applicability key* on shifts (`APPLICABILITY_KEYS`); there is **no policy-group master** HR can maintain |
| Late Coming / Early Going / Half Day / Absent | **DONE** | per-shift thresholds, versioned |
| Regularisation | **PARTIAL** | window + evidence flag in `DEFAULT_ATTENDANCE_RULES`; **request *types* and a multi-level approval path are not configurable** |
| Monthly Cut-off | **PARTIAL** | `attendance_closing_day` is stored and commented **"(informational)"** — it is not enforced anywhere |

### §6 Daily attendance fields — **DONE**

Identity, schedule, actual, calculated (`worked_hours`, `payable_hours`, `late_minutes`,
`early_minutes`, `grace_applied`), status, regularisation, approval, payable day / LOP
fraction, lock flag, and raw-value audit (`original_in/out`, `original_source`).

### §7 Process flow — **DONE** end-to-end, with the §12 approval-tier caveat below.

### §8 Attendance processing & monthly closure — **DONE**

`closure_dashboard`, `lock_period`, `unlock_period` (mandatory reason), post-lock changes
routed through adjustments.
**Hardening gap:** payroll reads **live** `COLL_ATTENDANCE` rows at calculate time rather than
a frozen snapshot (`_payable_days`, `hrms_payroll_service.py:642`). The month lock blocks
writes, so this is safe in practice — but an unlock → edit → recalculate sequence silently
changes the payroll basis with no stored record of what it was. §18 asks for a snapshot.

### §9 Salary structure fields — **DONE**

`SalaryStructureIn` carries employee / effective dating / structure name / revision reason /
annual CTC / payroll group / comments; `StructureStatus` + `decide_structure` give the
approval trail; history preserved, past payroll never rewritten.

### §10 Monthly payroll input — **DONE**

Period, employee, attendance (calendar / working / present / payable / LOP + off counts),
salary basis, additional earnings, recoveries, manual adjustments, calculated totals, and
controls (exception / previous-month net / variance / maker status / checker status).

### §11 Payroll calculation logic — **DONE** — `calculate_payroll` + `resolve_lines`.

### §12 Payroll approval workflow — **PARTIAL**

Stages 1–7 and 10–13 are implemented. The gap is stages **8 vs 9**:

> §12 stage 8 = *Payroll/HR Checker* verifies; stage 9 = *Finance / Authorised Approver*
> approves, rejects or returns; stage 10 = *Payroll* locks.

In code there is **one capability, `Cap.PAYROLL_APPROVE`**, guarding both `decide_run` and
`lock_run` (`routes/hrms.py:6701`). So the Checker and the Finance Approver are the same
authority, and the three-tier matrix §19 asks to confirm cannot be expressed. Maker ≠ Checker
*is* enforced (`decide_run` refuses the submitter).

### §13 Salary disbursal — **PARTIAL**

Every field in the §13 table exists (batch, generated date, payment date, status, UTR,
failure reason, retry batch), accounts masked in the UI, full numbers only in the audited
bank file. **Gap: the bank file layout is a single hard-coded generic CSV**
(`hrms_disbursal_service.py:185`). §19 requires a bank-specific configurable layout.

### §14 Payslip — **DONE**

All sections, configurable template with `COLL_PAYSLIP_TEMPLATE_VERSIONS`, version frozen onto
the run at lock, release gated by the `payslip_release` policy (`on_lock` / `after_payment`).

### §15 / §16 ER model & relationships — **DONE** for the operational core.

Every relationship in §16 has a collection pair. §28's configuration layer does not — below.

### §17 Roles & access — **PARTIAL**

Employee / Reporting Manager / HR / Payroll Maker (`PAYROLL_PROCESS`) / System Admin are all
expressible. **Payroll/HR Checker and Finance/Authorised Approver are not separable** (same
root cause as §12).

### §18 Validation & control requirements

| Control | Verdict |
|---|---|
| Employee duplication checked | **DONE** |
| Sensitive bank / statutory / salary restricted | **DONE** (`EMPLOYEE_MASKED_FIELDS`, `SENSITIVE_HISTORY_FIELDS`, capability gates) |
| Salary / org / reporting changes effective-dated | **DONE** |
| Raw attendance traceable after regularisation | **DONE** |
| Attendance locked before payroll finalised | **DONE** (policy-gated, `require_attendance_lock`) |
| Payroll uses locked snapshot, not live attendance | **PARTIAL** — see §8 note |
| Exception reporting + previous-month variance | **DONE** |
| Maker-checker mandatory before lock | **DONE** |
| Locked payroll not edited in place | **DONE** (`create_post_lock_adjustment`) |
| Bank file only from approved/locked payroll | **DONE** |
| Payment status / UTR retained per employee & batch | **DONE** |
| Payslip reflects values actually used | **DONE** |
| Audit trail on create / update / approve / reject / lock / payment | **PARTIAL** — operational acts audited; **configuration changes only partly**: field definitions and shifts are, salary components keep a private `history` array with no audit-log view, payroll policy saves log only the changed key names |

### §19 Items requiring final confirmation — **OPEN** (see section 6 of this plan)

### §20 Phase 1 acceptance criteria — **13 of 14 demonstrable today**

The outstanding one is the three-tier Checker → Finance separation inside
*"Checker/Finance can approve, reject or return payroll."*

### §21 Cross-module configurability

| Configuration area | Verdict | Gap |
|---|---|---|
| Employee Fields | **DONE** | `COLL_FIELD_DEFINITIONS`, full §22 option set, retire-not-delete |
| Attendance Fields | **DONE** | same machinery, `FIELD_MODULES = ("employee","attendance")` |
| Attendance Rules / Policy | **PARTIAL** | shift rules are versioned and effective-dated; **OD/regularisation, LOP and monthly-closure rules are a flat dict in `hrms_settings`** with no version, no effective date, no scope |
| Salary Components | **PARTIAL** | create/modify works, an `active` flag retires; **no Draft→Approved→Active→Superseded→Retired lifecycle, no effective dating, no applicability scope** |
| Payroll Calculations | **PARTIAL** | formula / slab / percentage / sequence all configurable; **formulas are not versioned, not effective-dated, not approved before use** |
| Payroll Policy | **PARTIAL** | configurable, **but not versioned** (§21 explicitly says "with versioning") |
| Payslip Layout Mapping | **DONE** | `PayslipSection` per component, versioned template retained per period |

### §22 Configurable field management — **DONE**

Identity, 13 data types, behaviour flags, role / self / manager / payroll visibility,
validation (min/max/length/pattern/date-range + custom message), dropdown/lookup,
applicability, display, Draft/Active/Retired lifecycle with effective dates, and audit of
old/new definition. All four §22 Controls are enforced, including the data-type freeze once
values exist and the dependency check before retirement (`field_usage`).

### §23 Attendance policy & rule configuration — **PARTIAL (largest attendance gap)**

| Rule category | Verdict |
|---|---|
| Shift / Timing | **DONE** (versioned) |
| Late Coming | **DONE** (versioned) |
| Early Going | **DONE** (versioned) |
| Half Day | **PARTIAL** — working-hour threshold yes; **late/early *combination* rules no** |
| Absent | **DONE** |
| Weekly Off / Holiday | **DONE** |
| OD / Regularisation | **PARTIAL** — flat settings; no request *types*, no approval levels |
| LOP | **PARTIAL** — `sandwich_weekly_off` only; half-day = 0.5 is hard-coded; approved-leave interaction fixed in code |
| Monthly Closure | **PARTIAL** — lock/unlock authority by capability; **cut-off date not enforced**; pending-request handling not configurable |
| Applicability | **PARTIAL** — shifts carry applicability + specificity priority; **non-shift rules carry none** |

§23's headline requirement — *"HR should be able to create a new policy version, **test it**
and activate it from a future effective date"* — has **no test/simulate path for attendance**
at all.

### §24 Salary component & payroll calculation configuration

| Configuration | Verdict | Gap |
|---|---|---|
| Component Type | **DONE** | all six types |
| Calculation Method | **PARTIAL** | Fixed / Percentage / Formula / Manual / Slab present. **"Imported Input" and "Attendance-linked" are not members of `CalculationMethod`** |
| Calculation Base | **PARTIAL** | component / GROSS / CTC. **"payable days" and "statutory base" are not selectable bases** |
| Frequency | **PARTIAL** | a free-text field, **not enforced by the run** — a Quarterly component pays every month |
| Proration | **PARTIAL** | `ProrationRule` is only `PAYABLE_DAYS` / `NONE`. §24 asks for **Full month** and **working-days based** too |
| Applicability | **MISSING** | no employee / category / grade / location / payroll-group scope, no effective dates on a component |
| Rounding | **DONE** | None / Nearest / Floor / Ceiling |
| Minimum / Maximum | **DONE** | |
| Sequence | **DONE** | |
| Payslip Mapping | **DONE** | |
| Accounting / Bank Mapping | **DONE** | `accounting_code` |
| Lifecycle | **MISSING** | only a boolean `active`; no Draft/Approved/Active/Superseded/Retired |

### §25 Formula / calculation rule engine

| Capability | Verdict | Gap |
|---|---|---|
| Variables | **PARTIAL** | `BUILT_INS = {GROSS, CTC, MONTHLY_CTC}` + already-resolved component codes only. **No employee fields, no `PAYABLE_DAYS` / `LOP_DAYS` / `PRESENT_DAYS`, no payroll inputs, no named constants** (`hrms_formula_engine.py:30`; env built at `hrms_payroll_service.py:359`) |
| Operators | **DONE** | arithmetic, comparison, AND/OR/NOT |
| Conditions | **DONE** | `IF(...)` |
| Formula Versioning | **MISSING** | the component carries an incrementing `version` + `history`, but a *formula* has no version, no effective dates, no status, no approval |
| Dependency Validation | **DONE** | `find_cycle`, `dependants`, sequence-order refusal |
| Simulation | **PARTIAL** | `simulate_component` exists for a **salary component**; nothing for attendance policy or payroll policy |
| Comparison (old vs proposed) | **DONE** for components — `simulate_component` returns both |
| Audit — version stored per payroll result | **PARTIAL** | `component_version` is stamped on each result line (`hrms_payroll_service.py:347`); **formula text/version, policy version and shift version are not** |
| Failure Handling | **DONE** | critical exceptions block `submit_run` |

### §26 Policy versioning & effective-date management — **PARTIAL**

| Bullet | Verdict |
|---|---|
| Every material change creates a new version | **PARTIAL** — true for shifts, field definitions, payslip templates; **false for payroll policy, attendance rules, salary components, formulas** |
| Effective From / To | **PARTIAL** — same split |
| Scope by company / location / department / grade / category / shift / payroll group | **PARTIAL** — shifts and field definitions only |
| Documented priority rule when several match | **PARTIAL** — exists for shifts (`_specificity`, `hrms_shift_service.py:250`); nothing generic |
| History references the version originally used | **PARTIAL** — component version only |
| Retroactive change requires authorised recalculation | **PARTIAL** — enforced at payroll (post-lock adjustments) and attendance (unlock reason); **not enforced at the configuration layer** |
| Draft changes support preview / simulation | **PARTIAL** — salary components only |

### §27 Configuration change approval flow — **MISSING**

No implementation of Request → Draft → Impact Analysis → Test/Simulation → Approval →
Effective Dating → Activation. Verified absent: no `change_request`, `config_approval` or
`impact_analysis` symbol anywhere in `backend/app/`. Today a configurator with the capability
saves directly to live configuration.

### §28 ER extension — configuration & rule engine

| Conceptual entity | Mapped to | Verdict |
|---|---|---|
| `MODULE_DEFINITION` | `FIELD_MODULES` tuple | **PARTIAL** (a constant, not a registry) |
| `CUSTOM_FIELD_DEFINITION` | `COLL_FIELD_DEFINITIONS` | **DONE** |
| `CUSTOM_FIELD_OPTION` | embedded `options[]` | **DONE** |
| `CUSTOM_FIELD_VALUE` | `custom_fields` on the profile | **DONE** |
| `CALCULATION_RULE` | component fields on `COLL_SALARY_COMPONENTS` | **PARTIAL** (no standalone versioned rule) |
| `CALCULATION_VARIABLE` | — | **MISSING** |
| `POLICY_DEFINITION` / `POLICY_VERSION` / `POLICY_ASSIGNMENT` | — | **MISSING** (`COLL_POLICIES` is the *HR policy-document register*, a different thing) |
| `CONFIG_CHANGE_REQUEST` / `CONFIG_APPROVAL` | — | **MISSING** |
| `CONFIG_AUDIT_LOG` | `COLL_AUDIT_LOG` partially | **PARTIAL** |

### §29 Module-specific administrative screens

| Screen | Verdict | Where |
|---|---|---|
| Employee Field Configuration | **DONE** | `people/EmployeeMasterSetup.jsx` |
| Attendance Field Configuration | **DONE** | same screen, Module tab = Attendance |
| Attendance Policy Designer | **PARTIAL** | `attendance/ShiftMaster.jsx` covers timing / late / early / half-day / absent; **LOP, regularisation and lock rules are not in a designer** |
| Salary Component Master | **DONE** | `payroll/ComponentEditor.jsx` |
| Payroll Formula Designer | **PARTIAL** | a formula input inside ComponentEditor; **no variable picker, no version/approval UI** |
| Policy Version & Scope | **MISSING** | — |
| Configuration Impact / Dependency Viewer | **PARTIAL** | field-level only (`field_usage` endpoint); no component / policy / formula view |
| Rule Simulation | **PARTIAL** | salary component only (`POST /salary-components/{code}/simulate`) |
| Configuration Approval Inbox | **MISSING** | — |
| Configuration Audit Viewer | **PARTIAL** | `admin/AuditViewer.jsx` shows the operational audit log, not configuration versions / old-new definitions |

### §30 Additional acceptance criteria for configurability

| Criterion | Verdict |
|---|---|
| HR adds an Employee Master field without deployment | **DONE** |
| Admin changes label / visibility / mandatory / validation / options | **DONE** |
| Used fields retired, not deleted | **DONE** |
| HR creates a **future-dated attendance policy version** for a selected population | **PARTIAL** — shift versions yes; full policy no |
| Late/half-day change does not recalculate closed periods | **DONE** (`version_on`) |
| Payroll adds a component + payslip mapping without code change | **DONE** |
| Payroll revises a formula **as a new version, simulates, obtains approval** before activation | **MISSING** (simulate yes; version + approval no) |
| Circular dependencies prevented / reported | **DONE** |
| Payroll result records enough version references to reproduce | **PARTIAL** (component version only) |
| Config changes audited with requester, approver, reason, effective date, old/new | **PARTIAL** |
| Impact / dependency check before retirement | **PARTIAL** (fields only) |
| Configuration access permission-controlled and separate | **PARTIAL** — no dedicated `config.*` capability family |

---

## 3. Gap backlog (consolidated)

Grouped by workstream, each with the FRD clause it closes.

### W1 — Payroll approval matrix (§12, §17, §20)
- **G1.1** Split `Cap.PAYROLL_APPROVE` into `PAYROLL_CHECK` (stage 8) and `PAYROLL_APPROVE`
  (stage 9, Finance). Lock stays on Finance or moves to Payroll per confirmation #7.
- **G1.2** Add run status `CHECKED` between `SUBMITTED` and `APPROVED`.
- **G1.3** Configurable approval matrix in payroll policy — who checks, who approves, whether
  the checker stage is skippable.

### W2 — Configuration layer: policy versioning & scope (§21, §23, §26, §28)
- **G2.1** `COLL_POLICY_DEFINITIONS` / `COLL_POLICY_VERSIONS` / `COLL_POLICY_ASSIGNMENTS`.
- **G2.2** Generic version resolver with a documented specificity priority (generalise
  `hrms_shift_service._specificity`).
- **G2.3** Move attendance rules (OD, regularisation, LOP, closure), payroll policy and the
  approval matrix onto versioned policies.
- **G2.4** Stamp the resolved policy version onto every attendance day and payroll record.

### W3 — Configuration change approval flow (§27, §29, §30)
- **G3.1** `COLL_CONFIG_CHANGE_REQUESTS` + `COLL_CONFIG_APPROVALS`.
- **G3.2** Lifecycle Request → Draft → Impact → Simulation → Approval → Effective Dating →
  Activation.
- **G3.3** A `config.*` capability family, separate from employee/manager access.
- **G3.4** Configuration Approval Inbox + Configuration Audit Viewer screens.

### W4 — Salary component & formula lifecycle (§24, §25, §30)
- **G4.1** Component lifecycle Draft/Approved/Active/Superseded/Retired + `effective_from/to`.
- **G4.2** Component applicability scope (category / grade / location / payroll group / employee).
- **G4.3** Formula versioning: version number, effective dates, status, approver; store the
  **formula version** (not just the component version) on every payroll result line.
- **G4.4** Extend `CalculationMethod` with `IMPORTED` and `ATTENDANCE_LINKED`.
- **G4.5** Extend `ProrationRule` with `FULL_MONTH` and `WORKING_DAYS`.
- **G4.6** Enforce `frequency` in `calculate_payroll` (Quarterly / Annual / One-time).

### W5 — Formula engine variables (§25)
- **G5.1** Add attendance variables: `PAYABLE_DAYS`, `LOP_DAYS`, `PRESENT_DAYS`,
  `WORKING_DAYS`, `CALENDAR_DAYS`, `LOP_RATIO`.
- **G5.2** Add employee-field variables (`EMP_GRADE`, `EMP_CATEGORY`, `EMP_LOCATION`, …) and
  configurable named constants (§28 `CALCULATION_VARIABLE`).
- **G5.3** Variable picker in the Formula Designer UI.

### W6 — Attendance policy designer & simulation (§23, §29, §30)
- **G6.1** Attendance Policy Designer screen covering LOP, regularisation, OD and closure.
- **G6.2** Attendance-policy simulation ("test it before activation").
- **G6.3** Enforce the monthly cut-off date — today `attendance_closing_day` is informational.
- **G6.4** Configurable half-day via late/early *combination*, configurable LOP fraction,
  configurable approved-leave interaction.
- **G6.5** Attendance Policy Group master (currently a free-text applicability key).
- **G6.6** Configurable OD/regularisation request types and multi-level approval path.

### W7 — Attendance snapshot for payroll (§8, §18)
- **G7.1** Freeze a per-employee attendance basis onto the payroll record at calculate time,
  and record the attendance lock id/version the run consumed.
- **G7.2** Refuse — or require authorised recalculation for — a payroll whose attendance lock
  changed after calculation.

### W8 — Disbursal bank file (§13, §19)
- **G8.1** Configurable bank-file format master: column set, order, header/trailer, delimiter,
  date and amount formats, fixed-width option, per-bank profile.
- **G8.2** Assign a format per company/bank; stamp the format version onto the batch.

### W9 — Employee master finishing touches (§3)
- **G9.1** Photograph as a first-class employee-master field (upload, store, show on the
  profile header and on the payslip if the approved template wants it).
- ~~**G9.2** Surface `annual_ctc` / `monthly_gross` on the profile's Salary Linkage~~ —
  already implemented (`structure_summary`); the audit recorded this in error.
- **G9.3** `apply_due_changes` ran only lazily on an employee READ, so a change due on the
  1st was not in force for a payroll calculated before anyone opened the directory.
  Register it as a scheduled job.

### W10 — Impact / dependency viewer (§29, §30)
- **G10.1** Generalise `field_usage` into a dependency service covering fields, components,
  formulas and policies.
- **G10.2** Configuration Impact / Dependency Viewer screen.

### W11 — Configuration audit (§22, §27, §30)
- **G11.1** Config audit entries carrying requester, approver, reason, effective date and
  old/new definition for **every** configuration entity.
- **G11.2** Configuration Audit Viewer screen (versions + approvals + diffs).

---

## 4. Step-wise implementation plan

Each step = one branch commit, one test addition, independently reviewable.
Estimates are engineering days for one developer, backend + frontend.

> **Dependency order matters.** Steps 1–3 build the configuration spine that Steps 4–8 plug
> into. Doing W4/W6 before W2 means building versioning twice.

---

### Step 0 — Branch and baseline (0.5 d)

```bash
cd f:/D_Table_Analytics/Projects/sparsh2.0
git checkout BHU_22/9
git pull
git checkout -b MANOJ_PHASE1_CHNAGES
cd backend && python -m app.services.hrms.tests.test_frd_phase1
```

Record the baseline pass count. Every later step must keep it green.

**Deliverable:** branch created, baseline test output captured in the PR description.

---

### Step 1 — Payroll approval matrix: three tiers (W1) · 2 d

The smallest change that closes a *named acceptance criterion*, so it goes first.

| File | Change |
|---|---|
| `models/hrms.py` | Add `Cap.PAYROLL_CHECK`. Add `PayrollRunStatus.CHECKED`. Add to the default role matrix: Check → HR / Payroll; Approve → Finance / MD. |
| `models/hrms.py` | `DEFAULT_PAYROLL_POLICY` gains `approval_matrix: {"checker_required": true, "checker_cap": "payroll.check", "approver_cap": "payroll.approve", "lock_cap": "payroll.approve"}`. |
| `services/hrms_payroll_service.py` | Split `decide_run` into `check_run` (Submitted → Checked / Returned) and `decide_run` (Checked → Approved / Rejected / Returned). Both enforce actor ≠ previous-stage actor. Honour `checker_required=false` by allowing Submitted → Approved directly. |
| `services/hrms_payroll_service.py` | `lock_run` accepts the checker-skipped path; guard by `lock_cap`. |
| `routes/hrms.py` | New `POST /payroll/runs/{period}/check`; `/decision` now requires `PAYROLL_APPROVE`; `/lock` requires the policy's `lock_cap`. |
| `frontend/.../payroll/RunDetail.jsx` | Three-stage approval strip; action buttons gated on capability. |
| `frontend/.../payroll/PayrollPolicy.jsx` | Approval-matrix editor. |
| `services/hrms/tests/test_frd_phase1.py` | Maker cannot check; checker cannot approve; `checker_required=false` collapses to two stages. |

**Acceptance:** §12 stages 7–10 each performable by a distinct authority; §20's
"Checker/Finance can approve, reject or return payroll" demonstrable with three users.

---

### Step 2 — Configuration spine: policy definitions, versions, assignments (W2.1–W2.2) · 4 d

| File | Change |
|---|---|
| `models/hrms.py` | `COLL_POLICY_DEFINITIONS = "hrms_policy_definitions"`, `COLL_POLICY_VERSIONS = "hrms_policy_versions"`, `COLL_POLICY_ASSIGNMENTS = "hrms_policy_assignments"`. Mirror §28: PolicyID / ModuleID / PolicyCode / Category; VersionNo / EffectiveFrom / EffectiveTo / RuleJson / Status / ApprovedBy / ApprovedOn; AssignmentID / PolicyVersionID / Company / Location / Department / GradeLevel / EmploymentCategory / Priority. |
| `models/hrms.py` | `HRMS_INDEXES.extend([...])` — unique `(company_id, policy_code, version_no)`, lookup `(company_id, policy_code, status, effective_from)`, assignment `(company_id, policy_version_id)`. |
| **new** `services/hrms_policy_version_service.py` | `save_draft`, `activate`, `supersede`, `assign_scope`, and `resolve(company_id, policy_code, context, on_date)` — generalising `hrms_shift_service._specificity` into one documented priority rule: more matching scope keys wins; tie → higher `priority`; tie → latest `effective_from`. |
| `services/hrms_shift_service.py` | Refactor `_specificity` to call the shared resolver (behaviour-preserving). |
| `routes/hrms.py` | `GET/PUT /config/policies`, `GET /config/policies/{code}/versions`, `POST /config/policies/{code}/versions/{v}/activate`, `PUT /config/policies/{code}/versions/{v}/scope`. |
| tests | Overlapping scopes resolve deterministically; a future-dated version does not affect today; a closed period keeps its original version. |

**Acceptance:** §26 bullets 1–5 satisfiable for any policy registered on this spine.
**No behaviour change yet** — nothing is migrated onto it until Step 4.

---

### Step 3 — Configuration change approval flow (W3) · 4 d

| File | Change |
|---|---|
| `models/hrms.py` | `COLL_CONFIG_CHANGE_REQUESTS`, `COLL_CONFIG_APPROVALS`. `ConfigChangeStatus` enum: Draft / Impact Analysed / Simulated / Pending Approval / Approved / Rejected / Scheduled / Active / Superseded. |
| `models/hrms.py` | `Cap.CONFIG_REQUEST`, `CONFIG_DRAFT`, `CONFIG_APPROVE`, `CONFIG_AUDIT_READ` — the §30 "permission-controlled and separate" family. |
| **new** `services/hrms_config_change_service.py` | `request()`, `draft()`, `analyse_impact()`, `simulate()`, `approve()` / `reject()` / `return_()`, `schedule()`, `activate()`. Activation is the **only** writer to live configuration for governed entity types. |
| `services/hrms_scheduler_service.py` | Register a daily job that activates Approved-and-due change requests and calls `apply_due_changes` (closes **G9.3**). |
| `routes/hrms.py` | `/config/change-requests` CRUD + `/impact`, `/simulate`, `/decision`, `/activate`. |
| **new** `frontend/.../admin/ConfigApprovalInbox.jsx` | §29 Configuration Approval Inbox. |
| tests | A governed change cannot reach live config without approval; the approval record carries requester / approver / reason / effective date / old + new. |

**Acceptance:** §27 flow end-to-end; §30 "configuration changes are audited with requester,
approver, reason, effective date and old/new definition".

---

### Step 4 — Migrate attendance rules onto the policy spine + Policy Designer (W2.3, W6.1, W6.3–W6.6) · 5 d

| File | Change |
|---|---|
| `models/hrms.py` | Policy codes `ATT_LATE`, `ATT_EARLY`, `ATT_HALFDAY`, `ATT_ABSENT`, `ATT_LOP`, `ATT_REGULARISATION`, `ATT_OD`, `ATT_CLOSURE`, with a rule schema for each. Attendance Policy Group master (`COLL_ATTENDANCE_POLICY_GROUPS`). |
| `services/hrms_attendance_rules_service.py` | `effective_hours` / `compute_day` resolve rules through `hrms_policy_version_service.resolve(...)` for the work date, falling back to the shift version then the company policy — preserving today's behaviour where no policy version exists. |
| `services/hrms_attendance_rules_service.py` | Configurable half-day via late+early combination; configurable LOP fraction and approved-leave interaction. |
| `services/hrms_attendance_service.py` | **Enforce** the closure cut-off: refuse marking / regularisation past the cut-off for a closed month unless the actor holds the unlock capability. Configurable pending-request handling at closure. |
| `services/hrms_attendance_service.py` | Stamp `policy_version_ids` on each attendance day (**G2.4**). |
| `routes/hrms.py` | `/attendance/policies` designer endpoints, `/attendance/policy-groups`. |
| **new** `frontend/.../attendance/AttendancePolicyDesigner.jsx` | §29 "Attendance Policy Designer" — timing, late/early, half-day, absent, LOP, regularisation, lock. |
| tests | Grace 5→10 from a future date; a closed period is unchanged; the cut-off actually blocks. |

**Acceptance:** §23 fully configurable; §30 "HR can create a future-dated Attendance policy
version and apply it to a selected employee population".

---

### Step 5 — Attendance rule simulation (W6.2) · 2 d

| File | Change |
|---|---|
| **new** `services/hrms_attendance_simulation_service.py` | Re-judge a sample of employees over a sample period under the **draft** policy version; return old status / late-minutes / payable-day vs proposed, per day and per employee. Writes nothing. |
| `routes/hrms.py` | `POST /attendance/policies/{code}/versions/{v}/simulate`. |
| **new** `frontend/.../admin/RuleSimulation.jsx` | §29 "Rule Simulation" — a shared shell reused by attendance, component and formula simulations. |
| tests | Simulation output matches a real recalculation under the same rules; no writes occur. |

**Acceptance:** §23 "create a new policy version, **test it** and activate it"; §25 Simulation
and Comparison for attendance.

---

### Step 6 — Salary component lifecycle, applicability and proration (W4.1, W4.2, W4.5, W4.6) · 4 d

| File | Change |
|---|---|
| `models/hrms.py` | `ComponentLifecycle` enum: Draft / Approved / Active / Superseded / Retired. `SalaryComponentIn` gains `lifecycle`, `effective_from`, `effective_to`, `applicability: dict`. |
| `models/hrms.py` | `ProrationRule` gains `FULL_MONTH` and `WORKING_DAYS`. |
| `services/hrms_payroll_service.py` | `save_salary_component` writes a **new version row** rather than mutating when the component is Active and governed; `list_salary_components` resolves the version in force on a date. |
| `services/hrms_payroll_service.py` | `_component_lines` honours `FULL_MONTH` / `WORKING_DAYS` proration and the applicability scope. |
| `services/hrms_payroll_service.py` | `calculate_payroll` honours `frequency` — Quarterly / Annual / One-time components pay only in their due period. |
| `frontend/.../payroll/ComponentEditor.jsx` | Lifecycle chips, effective dating, applicability picker, proration and frequency selectors. |
| tests | A Draft component is not picked up by a run; a retired component stays on historical payslips; working-days proration arithmetic; a quarterly component pays once. |

**Acceptance:** §24's Lifecycle, Applicability, Proration and Frequency rows; §21 "Salary
Components … without code deployment" with version control.

---

### Step 7 — Formula engine: variables and versioning (W5, W4.3, W4.4) · 4 d

| File | Change |
|---|---|
| `models/hrms.py` | `COLL_CALCULATION_VARIABLES` (§28 `CALCULATION_VARIABLE`: name, source entity, source field, default). `CalculationMethod` gains `IMPORTED` and `ATTENDANCE_LINKED`. |
| `services/hrms_formula_engine.py` | `BUILT_INS` grows: `PAYABLE_DAYS`, `LOP_DAYS`, `PRESENT_DAYS`, `WORKING_DAYS`, `CALENDAR_DAYS`, `LOP_RATIO`, plus company-defined variables resolved from the registry. `validate()` checks against the resolved set. |
| `services/hrms_payroll_service.py` | `_formula_or_slab`'s env gains the attendance figures already computed in `_payable_days`, employee-field variables and registry constants. `calculation_base` accepts `PAYABLE_DAYS` and a statutory base. |
| `services/hrms_payroll_service.py` | Stamp `formula_version` + `formula_text` on each result line alongside `component_version` (**§25 Audit**, **§30** reproducibility). |
| `routes/hrms.py` | `/payroll/calculation-variables` CRUD. |
| `frontend/.../payroll/ComponentEditor.jsx` | **Formula Designer**: variable picker listing every available variable with its source, live validation, inline simulate. |
| tests | `IF(PAYABLE_DAYS < 15, 0, HRA)` evaluates; an unknown variable is refused at save; a result line carries enough to reproduce itself. |

**Acceptance:** §25's Variables, Formula Versioning and Audit rows; §29 "Payroll Formula
Designer"; §30 "Every payroll result records sufficient rule/component version references".

---

### Step 8 — Payroll policy versioning (W2.3 remainder) · 2 d

| File | Change |
|---|---|
| `services/hrms_payroll_service.py` | `get_payroll_policy(company_id, on_date=None)` resolves through the policy spine; `save_payroll_policy` creates a version, governed by Step 3 when the change is material. |
| `services/hrms_payroll_service.py` | Stamp `payroll_policy_version` on the run at calculate time. |
| `frontend/.../payroll/PayrollPolicy.jsx` | Version list, effective dating, draft / submit for approval. |
| tests | Changing the cut-off for next month does not alter a closed period's run. |

**Acceptance:** §21 "Payroll Policy … with versioning".

---

### Step 9 — Attendance snapshot for payroll (W7) · 2 d

| File | Change |
|---|---|
| `services/hrms_payroll_service.py` | At calculate time, persist the per-day attendance basis used (status + payable/LOP share per date) onto the payroll record, plus `attendance_lock_id` and `attendance_locked_at`. |
| `services/hrms_payroll_service.py` | `submit_run` refuses if the attendance lock for the period changed after `calculated_at` — "recalculate first". |
| `services/hrms_attendance_service.py` | `unlock_period` flags any dependent non-final payroll run as stale. |
| `frontend/.../payroll/RunDetail.jsx` | Per-employee attendance basis panel; stale-basis banner. |
| tests | Unlock → edit a day → submit is refused; recalculate clears it; a locked run is unaffected. |

**Acceptance:** §18 "Payroll must use the locked attendance snapshot, not live editable
attendance" — enforced by construction rather than by convention.

---

### Step 10 — Configurable bank file format (W8) · 3 d

| File | Change |
|---|---|
| `models/hrms.py` | `COLL_BANK_FILE_FORMATS`. Format: name, bank, delimiter / fixed-width, encoding, header rows, trailer rows, column list (`{source_field, label, order, width, format, transform}`), date format, amount format, narration template, version, status. |
| `services/hrms_disbursal_service.py` | `bank_file()` renders through the assigned format; the current CSV becomes the seeded `DEFAULT` format so existing behaviour is preserved. Stamp `format_name` + `format_version` on the batch. |
| `routes/hrms.py` | `/config/bank-file-formats` CRUD + `POST .../preview` (sample rows, writes nothing). |
| **new** `frontend/.../payroll/BankFileFormat.jsx` | Column designer with live preview. |
| tests | A fixed-width format pads correctly; amount/date formats apply; the default format's output is byte-identical to today's. |

**Acceptance:** §13 Payment Mode / file generation, with §19's "bank-specific layout and
mandatory fields" answerable by configuration.

---

### Step 11 — Impact/dependency viewer and configuration audit viewer (W10, W11) · 3 d

| File | Change |
|---|---|
| **new** `services/hrms_config_dependency_service.py` | `where_used(entity_type, code)` across fields, components, formulas, policies, payslip mapping and bank formats. Generalises `hrms_employee_master_service.field_usage`. |
| `services/hrms_payroll_service.py` / `hrms_policy_version_service.py` | Refuse retirement when dependants exist and the impact is unresolved (§22 Control 3). |
| `routes/hrms.py` | `GET /config/impact/{entity_type}/{code}`, `GET /config/audit`. |
| **new** `frontend/.../admin/ConfigImpactViewer.jsx` | §29 "Configuration Impact / Dependency Viewer". |
| **new** `frontend/.../admin/ConfigAuditViewer.jsx` | §29 "Configuration Audit Viewer" — version timeline, approvals, old/new diff. |
| tests | Retiring a component used by a live formula is refused and names the dependant. |

**Acceptance:** §29 rows 7 and 10; §30 "An impact/dependency check is available before a
field, policy or formula is retired".

---

### Step 12 — Employee master finishing touches + full regression (W9) · 2 d

| File | Change |
|---|---|
| `models/hrms.py` | `photograph` on `EmployeeProfileIn` / `EmployeeProfileUpdate` (document reference). |
| `services/hrms_employee_service.py` | Store / serve the photograph; include it in the profile view payload. |
| `services/hrms_employee_service.py` | Expose `annual_ctc` / `monthly_gross` on the Salary Linkage section, read from the active structure, capability-gated like `base_salary`. |
| `frontend/.../people/EmployeeProfile.jsx`, `AddEmployeeModal.jsx` | Photo upload + CTC display. |
| `services/hrms/tests/test_frd_phase1.py` | Extend to cover every §20 and §30 acceptance criterion explicitly — one named check per bullet. |

**Acceptance:** §3 Basic Identity and Salary Linkage complete; §20 and §30 each mapped to a
named passing check.

---

## 5. Effort summary

| Step | Workstream | Days |
|---|---|---:|
| 0 | Branch + baseline | 0.5 |
| 1 | Payroll approval matrix | 2 |
| 2 | Policy version spine | 4 |
| 3 | Config change approval flow | 4 |
| 4 | Attendance policy migration + designer | 5 |
| 5 | Attendance simulation | 2 |
| 6 | Component lifecycle & proration | 4 |
| 7 | Formula variables & versioning | 4 |
| 8 | Payroll policy versioning | 2 |
| 9 | Attendance snapshot | 2 |
| 10 | Configurable bank file | 3 |
| 11 | Impact + config audit viewers | 3 |
| 12 | Employee master finish + regression | 2 |
| | **Total** | **37.5 d** |

Roughly **7–8 working weeks** for one full-stack developer, or **about 4 weeks** split
backend/frontend across two.

### Suggested release slices

| Slice | Steps | Closes |
|---|---|---|
| **A — Compliance-critical** | 0, 1, 9, 12 | §12 / §17 / §20 approval matrix, §18 snapshot, §3 fields. Ships the named acceptance criteria. |
| **B — Configuration spine** | 2, 3, 11 | §26, §27, §28, §29, §30 governance |
| **C — Attendance configurability** | 4, 5 | §23 in full |
| **D — Payroll configurability** | 6, 7, 8 | §24, §25 in full |
| **E — Disbursal** | 10 | §13 / §19 bank format |

Slice A is independently shippable and is what a Phase 1 sign-off demo needs.

---

## 6. Open confirmations required from Sparsh Magic (FRD §19)

These block or reshape specific steps. Recommend raising all of them before Step 4.

| # | Decision | Blocks | What we need |
|---|---|---|---|
| 1 | Employee Categories | Step 6 (applicability) | Final list and applicability |
| 2 | Attendance Source | Step 4 | Google / biometric / API / manual / import or combination. **Google and API are enum values with no ingestion path today** — if either is in scope, add an integration step (≈4 d each). |
| 3 | Late / Half-Day / LOP rules | Step 4 | Exact thresholds after grace/buffer; half-day fraction; approved-leave interaction |
| 4 | Monthly attendance cut-off | Step 4 | Date **and unlock authority** — today the cut-off is stored but not enforced |
| 5 | Salary components | Step 6 | Complete earning / deduction / employer-contribution catalogue |
| 6 | Statutory applicability | Step 7 | PF / ESI / PT / TDS and entity/location rules — drives which variables and bases the engine must expose |
| 7 | **Payroll approval matrix** | **Step 1** | Exact maker / checker / finance approvers, and whether the checker stage is mandatory. **Highest priority — Step 1 is first in the plan.** |
| 8 | Bank file format | Step 10 | Bank-specific layout and mandatory fields (a sample file from the bank is ideal) |
| 9 | Payslip format | — (already configurable) | Final approved template, to seed as version 1 |
| 10 | Payslip release | — (already configurable) | `on_lock` or `after_payment` — set the policy value |
| 11 | Payment failure process | Step 10 | Owner and retry / reversal procedure |

---

## 7. Working agreement for this branch

```bash
# one commit per step, message prefixed with the step number
git commit -m "FRD Step 1: split payroll checker and finance approver tiers"

# run the Phase 1 suite before every commit
cd backend && python -m app.services.hrms.tests.test_frd_phase1
```

**Rules carried from the existing codebase — keep them:**

1. **Retire, never delete.** §21: *"The word 'remove' … means deactivate/retire for future
   use."* Anything used in employee, attendance or payroll history stays.
2. **Phase discipline on `HRMS_INDEXES`.** Collection *names* may be declared up front; a
   collection is only added to `HRMS_INDEXES` in the step that first writes it.
3. **One authorization mechanism** — `can(user, capability)` through the registry in
   `models/hrms.py`. No parallel role checks.
4. **Identity keyed on `user_id` / `employee_code`, never on a name string.**
5. **Behaviour-preserving defaults.** Every new configurable must fall back to today's
   behaviour when unconfigured, so no existing company changes on deploy.
6. **New collections provisioned idempotently** via `_ensure_hrms_collections`; index
   failures log, never block startup.

---

## 8. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Steps 4 / 6 / 8 migrate live configuration onto the policy spine | A company's attendance or payroll silently changes on deploy | Fall-back resolution order: policy version → shift version → company settings. No version rows exist at deploy, so behaviour is identical until HR creates one. Covered by a dedicated "unconfigured company is unchanged" test per step. |
| Formula variable expansion (Step 7) changes existing formula results | Payroll amounts move | New variables are additive; no existing name is redefined. `validate()` already refuses unknown names at save time, so no stored formula can reference one. |
| Step 1 changes the run status machine | In-flight runs | Migration: any run currently `Submitted` stays valid; `CHECKED` is only reachable going forward. Add a one-off backfill note to the PR. |
| Config approval flow (Step 3) blocks HR from routine edits | Operational friction | Governed entity types are a configurable list. Start with salary components + formulas + attendance policies only; field definitions keep their current direct path until the client asks otherwise. |
| §19 answers arrive late | Steps 4 / 6 / 7 / 10 rework | Build the configuration *mechanism* first (Steps 2–3); the answers then become data, not code. This is precisely why the FRD asks for configurability over hard-coded formulas (§1, §21). |

---

*End of plan.*
