"""HRMS > Payroll (BA/Functional Design v2.2, §7.13, §22.7; Phase 1 FRD §9-§12, §18, §24).

Component-driven, not a fixed set of fields: a salary STRUCTURE is a list of component lines
against a configurable component MASTER. Each component carries its own behaviour (FRD §24):
type (earning / deduction / employer contribution / reimbursement / recovery /
informational), calculation method (fixed, percentage of a base, manual input), proration,
rounding, min/max, sequence and payslip section.

-- The run (FRD §12) ----------------------------------------------------------------------
  HR locks attendance -> Maker creates the period and calculates (locked attendance basis,
  active structures, monthly inputs, carry-forward arrears/recoveries) -> reviews exceptions
  and previous-month variance, corrects inputs and reruns -> SUBMITS -> Checker approves,
  rejects or RETURNS (never the maker themself) -> Finance LOCKS -> payment batch / bank
  file / UTR (hrms_disbursal_service) -> period CLOSED.

-- Post-lock changes (FRD §18) ------------------------------------------------------------
A locked run is never edited in place. A correction is a post-lock adjustment -- an arrear,
recovery or reversal -- carried into a later period's calculation with its source reference.

-- Reproducibility -------------------------------------------------------------------------
Every record stores the component LINES it was calculated from (name, type, section, full
and paid amount, the structure version), so a payslip shows what was actually paid even if
the component master or the structure changes later (FRD §18, §25 Audit).
"""
import csv
import io
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from fastapi import HTTPException

from app.db.mongodb import get_collection
import re

from app.models.hrms import (
    AUDIT_PAYROLL_ADJUSTMENTS_SET, AUDIT_PAYROLL_CALCULATED, AUDIT_PAYROLL_CLOSED,
    AUDIT_PAYROLL_DECIDED, AUDIT_PAYROLL_LOCKED, AUDIT_PAYROLL_POLICY_SAVED,
    AUDIT_PAYROLL_RECORD_ADJUSTED, AUDIT_PAYROLL_RUN_CREATED, AUDIT_PAYROLL_CHECKED, AUDIT_PAYROLL_SUBMITTED,
    AUDIT_POST_LOCK_ADJUSTMENT, AUDIT_SALARY_COMPONENT_SAVED, AUDIT_SALARY_STRUCTURE_SAVED,
    AUDIT_STRUCTURE_DECIDED, COLL_CALCULATION_VARIABLES,
    COLL_ATTENDANCE, COLL_ATTENDANCE_LOCKS, COLL_EMPLOYEE_PROFILES,
    COLL_PAYROLL_CARRY_FORWARD, COLL_PAYROLL_RECORDS, COLL_PAYROLL_RUNS,
    COLL_SALARY_ADVANCES, COLL_SALARY_COMPONENTS, COLL_SALARY_STRUCTURES, COLL_SETTINGS,
    COLL_VARIABLE_PAY_RECORDS,
    DEDUCTING_TYPES, DEFAULT_PAYROLL_POLICY, PAYROLL_MATRIX_ALLOWED_CAPS, PAYROLL_MATRIX_CAP_KEYS, EARNING_TYPES,
    ENTITY_PAYROLL_RUN, ENTITY_SALARY_COMPONENT, ENTITY_SALARY_STRUCTURE,
    MAX_PAYROLL_LIST_PAGE, PAYROLL_EDITABLE_STATUSES, PAYROLL_FINAL_STATUSES,
    AdvanceStatus, AttendanceStatus, CalculationMethod, ComponentType, PayrollRunStatus,
    PayslipSection, ProrationRule, RoundingRule, StructureStatus, is_iso_date,
)
from app.services.hrms_audit_service import audit

LOCKED_SNAPSHOT_STATUSES = {"Locked"}
NON_ACTIVE_STRUCTURE = [StructureStatus.PENDING.value, StructureStatus.REJECTED.value]
UNPAID_LEAVE_CODES = {"LWP", "LOP", "UNPAID"}
MANUAL_FIELDS = ("pf", "esi", "pt", "tds", "arrears", "reimbursements", "other_earnings",
                 "other_deductions", "notice_recovery", "bonus", "remarks")


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_id(actor: Optional[dict]) -> str:
    return str((actor or {}).get("_id") or "")


def _actor_name(actor: Optional[dict]) -> Optional[str]:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email"))


def _plain(value):
    return getattr(value, "value", value)


def _round(amount: float, rule: Optional[str]) -> float:
    import math
    rule = _plain(rule) or RoundingRule.NONE.value
    if rule == RoundingRule.NEAREST.value:
        return float(math.floor(amount + 0.5))
    if rule == RoundingRule.FLOOR.value:
        return float(math.floor(amount))
    if rule == RoundingRule.CEILING.value:
        return float(math.ceil(amount))
    return round(amount, 2)


def _period_bounds(period: str) -> tuple:
    try:
        year, month = (int(x) for x in str(period).split("-"))
        days = monthrange(year, month)[1]
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Period must be YYYY-MM.")
    if not 1 <= month <= 12 or len(str(period)) != 7:
        raise HTTPException(status_code=422, detail="Period must be YYYY-MM.")
    return year, month, days, f"{period}-01", f"{period}-{days:02d}"


def _previous_period(period: str) -> str:
    year, month = (int(x) for x in period.split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def _next_period(period: str) -> str:
    year, month = (int(x) for x in period.split("-"))
    return f"{year + 1}-01" if month == 12 else f"{year}-{month + 1:02d}"


async def _get_profile(company_id: str, employee_code: str) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(status_code=404, detail="No employee with that code in this company.")
    return profile


# ─────────────────────────────────────────────────────────────
# Payroll policy (FRD §19, §24)
# ─────────────────────────────────────────────────────────────
async def get_payroll_policy(company_id: str, *, profile: Optional[dict] = None,
                             on_date: Optional[str] = None) -> dict:
    """The payroll policy in force.

    §21 asks for payroll policy to be versioned ("Change payroll cut-off, eligibility,
    component applicability, rounding and approval controls WITH VERSIONING"). The stored
    settings dict is the base; a PAY_POLICY version in force on `on_date` for this
    employee lays over it.

    `on_date` is the point of the whole thing: a run for February must read February's
    policy even if HR changed the cut-off in March. Callers that pass nothing get today's,
    which is what every existing caller wants and what they already got.
    """
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    base = {**DEFAULT_PAYROLL_POLICY, **((doc or {}).get("payroll_policy") or {})}
    from app.models.hrms import POLICY_PAY_POLICY
    from app.services import hrms_policy_version_service as PV
    return await PV.resolve_rules(company_id, POLICY_PAY_POLICY, profile or {}, on_date,
                                  default=base)


PAYROLL_POLICY_VERSION_NAME = "Payroll policy — cut-off, rounding, eligibility, approvals"


def _policy_changes(before: dict, after: dict) -> list:
    """FRD §30's old/new definition, for the keys that actually moved.

    Reporting every submitted key would bury the one that changed among a dozen that did
    not: the screen posts the whole form, so "what was saved" and "what changed" are
    different questions and the audit is asked the second one.
    """
    return [{"field": k, "old": before.get(k), "new": after[k]}
            for k in sorted(after) if before.get(k) != after[k]]


def _clean_approval_levels(levels) -> list:
    """P1-095: validate a configured approval chain. [] means "back to the default matrix".

    Each stage names a PAYROLL capability (the same allow-list the lock stage uses) and may
    be narrowed to HRMS roles. A typo is refused at save time rather than discovered when a
    payroll cannot be approved."""
    from app.models.hrms import PAYROLL_MAX_APPROVAL_LEVELS, PAYROLL_STAGE_ROLES
    if not levels:
        return []
    if not isinstance(levels, list) or len(levels) > PAYROLL_MAX_APPROVAL_LEVELS:
        raise HTTPException(
            status_code=422,
            detail=f"The approval chain has 1 to {PAYROLL_MAX_APPROVAL_LEVELS} stages.")
    out, names = [], set()
    for i, stage in enumerate(levels, start=1):
        stage = stage if isinstance(stage, dict) else {}
        name = str(stage.get("name") or "").strip()[:60]
        if not name:
            raise HTTPException(status_code=422, detail=f"Approval stage {i} needs a name.")
        if name.lower() in names:
            raise HTTPException(status_code=422, detail=f"Two approval stages are called {name}.")
        names.add(name.lower())
        cap = str(stage.get("cap") or "").strip()
        if cap not in PAYROLL_MATRIX_ALLOWED_CAPS:
            raise HTTPException(
                status_code=422,
                detail=f"{name}: the permission must be one of "
                       f"{', '.join(sorted(PAYROLL_MATRIX_ALLOWED_CAPS))}.")
        roles = sorted({str(r).strip().lower() for r in stage.get("roles") or []
                        if str(r).strip()})
        unknown = [r for r in roles if r not in PAYROLL_STAGE_ROLES]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"{name}: unknown role(s) {', '.join(unknown)}. Choose from "
                       f"{', '.join(sorted(PAYROLL_STAGE_ROLES))}.")
        out.append({"name": name, "cap": cap, "roles": roles})
    return out


def approval_chain(policy: dict) -> Optional[list]:
    """The configured approval chain (P1-095), or None when the company uses the default
    Maker -> Checker -> Finance matrix -- in which case check_run / decide_run behave
    exactly as they always have."""
    levels = (policy or {}).get("approval_levels")
    return list(levels) if levels else None


async def save_payroll_policy(actor: dict, company_id: str, payload: dict) -> dict:
    """§21 "Change payroll cut-off, eligibility, component applicability, rounding and
    approval controls WITH VERSIONING" — through the §27 change flow, not around it.

    This used to write straight into `hrms_settings.payroll_policy`. The rules that decide
    whether a run needs a checker, what rounds to the rupee and when inputs close went live
    the moment one person clicked Save: no version, no effective date, no second pair of
    eyes, and an audit row naming the KEYS that moved without the values. Meanwhile
    PAY_POLICY versions were resolvable, effective-dated and scopeable -- and no screen
    could create one, so the feature existed and was unreachable.

    Saving now DRAFTS a version and raises a change request against it. Nothing is live
    until that request is approved and activated, which is also what gives a February run
    February's cut-off after HR revises it in March.

    The flat settings dict stays the fallback BASE that every version lays over, so a
    company holding no versions resolves exactly what it resolved before. It is simply no
    longer what this screen writes.
    """
    clean = {k: _plain(v) for k, v in payload.items() if v is not None}
    # None of these is a policy rule: they describe the CHANGE / VERSION, not the payroll.
    effective_from = str(clean.pop("effective_from", "") or "").strip() or None
    effective_to = str(clean.pop("effective_to", "") or "").strip() or None
    scope = clean.pop("scope", None) or {}
    reason = str(clean.pop("change_reason", "") or "").strip()
    if "adjustment_approval_above" in clean and float(clean["adjustment_approval_above"]) < 0:
        raise HTTPException(status_code=422, detail="The approval amount cannot be negative.")
    if "excluded_employee_categories" in clean:
        clean["excluded_employee_categories"] = [
            str(c).strip() for c in clean["excluded_employee_categories"] if str(c).strip()]

    if "payslip_release" in clean and clean["payslip_release"] not in ("on_lock", "after_payment"):
        raise HTTPException(status_code=422,
                            detail="Payslip release must be on_lock or after_payment.")
    if "variance_threshold_percent" in clean and not 0 <= float(
            clean["variance_threshold_percent"]) <= 100:
        raise HTTPException(status_code=422, detail="Variance threshold must be 0-100%.")
    if "input_cutoff_day" in clean and not 1 <= int(clean["input_cutoff_day"]) <= 31:
        raise HTTPException(status_code=422, detail="Cut-off day must be 1-31.")
    # FRD §12/§19 approval matrix: a stage may only name a PAYROLL capability. Refusing an
    # unknown value here (rather than falling back silently at call time) means a mistyped
    # matrix is visible when it is saved, not discovered when a payroll will not lock.
    for key in PAYROLL_MATRIX_CAP_KEYS:
        if key in clean and str(clean[key]) not in PAYROLL_MATRIX_ALLOWED_CAPS:
            raise HTTPException(
                status_code=422,
                detail=f"{key} must be one of: {', '.join(sorted(PAYROLL_MATRIX_ALLOWED_CAPS))}.")
    if "approval_levels" in clean:
        clean["approval_levels"] = _clean_approval_levels(clean["approval_levels"])
    if not clean:
        raise HTTPException(status_code=422, detail="Nothing to change.")
    if not reason:
        raise HTTPException(
            status_code=422,
            detail="Say why the payroll policy is changing — the approver and the audit "
                   "trail both need the business reason (FRD §27).")

    from app.models.hrms import CONFIG_ENTITY_POLICY_VERSION, POLICY_PAY_POLICY
    from app.services import hrms_config_change_service as CC
    from app.services import hrms_policy_version_service as PV

    # The POLICY_DEFINITION is a fixed fact about PAY_POLICY -- its name and module are not
    # the company's to choose. Provisioning it here rather than making the user create it
    # on another screen first is what stops this being a dead end for every company that
    # has never opened the policy designer.
    await PV.save_definition(actor, company_id, {
        "code": POLICY_PAY_POLICY, "name": PAYROLL_POLICY_VERSION_NAME, "module": "payroll",
        "description": "FRD §21 — versioned payroll controls."})

    before = await get_payroll_policy(company_id)
    draft = await PV.save_draft(actor, company_id, {
        "policy_code": POLICY_PAY_POLICY,
        "effective_from": effective_from or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "effective_to": effective_to, "rules": clean, "change_reason": reason})
    if any(v for v in scope.values()):
        # §26 scope: who this version applies to. Run-level keys stay company-wide however
        # it is scoped (see PAYROLL_POLICY_RUN_LEVEL_KEYS).
        await PV.assign_scope(actor, company_id, {
            "policy_code": POLICY_PAY_POLICY, "version_no": draft["version_no"],
            "scope": scope})
    request = await CC.create_request(actor, company_id, {
        "entity_type": CONFIG_ENTITY_POLICY_VERSION, "entity_code": POLICY_PAY_POLICY,
        "version_no": draft["version_no"], "reason": reason,
        "effective_from": draft.get("effective_from"),
        "title": f"Payroll policy v{draft['version_no']}"})

    changes = _policy_changes(before, clean)
    await audit(actor, AUDIT_PAYROLL_POLICY_SAVED, ENTITY_PAYROLL_RUN, "policy",
                f"{POLICY_PAY_POLICY} v{draft['version_no']} drafted as "
                f"{request['request_no']}: "
                + (", ".join(f"{c['field']} {c['old']} -> {c['new']}" for c in changes)
                   or "no change to the policy in force"),
                company_id, changes=changes)
    # The effective policy is returned UNCHANGED, because it is: the draft is not live.
    # Returning the merged-as-if-saved dict would have the screen show the new values and
    # the runs use the old ones.
    return {**before, "pending_version": draft, "pending_request": request,
             "changes": changes}


# ─────────────────────────────────────────────────────────────
# §22.7 / FRD §24 — salary component master
# ─────────────────────────────────────────────────────────────
_DEFAULT_SECTION = {
    ComponentType.EARNING.value: PayslipSection.REGULAR_EARNINGS.value,
    ComponentType.REIMBURSEMENT.value: PayslipSection.OTHER_EARNINGS.value,
    ComponentType.DEDUCTION.value: PayslipSection.DEDUCTIONS.value,
    ComponentType.RECOVERY.value: PayslipSection.DEDUCTIONS.value,
    ComponentType.EMPLOYER_CONTRIBUTION.value: PayslipSection.EMPLOYER.value,
    ComponentType.INFORMATIONAL.value: PayslipSection.HIDDEN.value,
}
_DEFAULT_PRORATION = {
    ComponentType.EARNING.value: ProrationRule.PAYABLE_DAYS.value,
    ComponentType.EMPLOYER_CONTRIBUTION.value: ProrationRule.PAYABLE_DAYS.value,
}


def component_defaults(component: dict) -> dict:
    """A component with every behaviour key resolved. Components saved before FRD §24 carry
    only type/name, and read exactly as they always behaved: earnings prorated by payable
    days, deductions not, fixed amounts, no rounding."""
    c = dict(component)
    ctype = c.get("component_type") or ComponentType.EARNING.value
    c.setdefault("calculation_method", CalculationMethod.FIXED.value)
    c["calculation_method"] = c["calculation_method"] or CalculationMethod.FIXED.value
    default_proration = _DEFAULT_PRORATION.get(ctype, ProrationRule.NONE.value)
    # DEF-03: an employer contribution DERIVED from other components (a percentage of Basic,
    # a formula, a slab) is priced from its base exactly as the employee-side deduction on
    # the same base is, and that deduction is not prorated. Prorating only the employer half
    # again by payable days gave Employer PF 1,704 against Employee PF 1,800 on one 12%-of-
    # Basic definition. A FIXED employer amount still prorates by payable days, and an
    # explicitly configured rule always wins.
    if ctype == ComponentType.EMPLOYER_CONTRIBUTION.value and c["calculation_method"] in (
            CalculationMethod.PERCENTAGE.value, CalculationMethod.FORMULA.value,
            CalculationMethod.SLAB.value):
        default_proration = ProrationRule.NONE.value
    # Whether proration was CONFIGURED or is the type default: the editor must not save the
    # resolved default back as an explicit rule, or a later default change never reaches it.
    c["proration_configured"] = bool(c.get("proration"))
    c["proration"] = c.get("proration") or default_proration
    c["rounding"] = c.get("rounding") or RoundingRule.NONE.value
    c["payslip_section"] = c.get("payslip_section") or _DEFAULT_SECTION.get(
        ctype, PayslipSection.OTHER_EARNINGS.value)
    c["sequence"] = c.get("sequence") if c.get("sequence") is not None else 100
    c.setdefault("active", True)
    return c


# A component reaches these only through the §27 flow when components are governed.
GOVERNED_COMPONENT_STATES = ("Approved", "Active", "Superseded")
OPEN_REQUEST_STATUSES = ("Draft", "Impact Analysed", "Simulated", "Pending Approval",
                         "Approved", "Returned")


async def _stage_component_change(actor: dict, company_id: str, current: dict, changed: dict,
                                  payload: dict, now) -> dict:
    """Hold a governed revision of a live component and raise a §27 request for it.

    The revision sits under `pending_definition`, which nothing that prices pay reads, so
    payroll goes on using the live definition until the request is approved and activated
    -- at which point the old definition is kept as a Superseded version (see
    hrms_config_change_service._component_activate).
    """
    from app.models.hrms import CONFIG_ENTITY_SALARY_COMPONENT, COLL_CONFIG_CHANGE_REQUESTS
    from app.services import hrms_config_change_service as CC
    code = current["code"]
    reason = str(payload.get("change_reason") or "").strip()
    if not reason:
        raise HTTPException(
            status_code=422,
            detail=f"{code} is live, so a change to it goes for approval — say why it is "
                   f"changing; the approver needs the business reason (FRD §27).")
    if current.get("pending_request_no"):
        open_request = await get_collection(COLL_CONFIG_CHANGE_REQUESTS).find_one(
            {"company_id": str(company_id), "request_no": current["pending_request_no"],
             "status": {"$in": list(OPEN_REQUEST_STATUSES)}})
        if open_request:
            raise HTTPException(
                status_code=409,
                detail=f"{code} already has a change waiting ({current['pending_request_no']}, "
                       f"{open_request['status']}). Finish or withdraw it first.")
    coll = get_collection(COLL_SALARY_COMPONENTS)
    key = {"company_id": str(company_id), "code": code}
    await coll.update_one(key, {"$set": {"pending_definition": changed, "pending_reason": reason,
                                         "pending_by": _actor_id(actor), "pending_at": now}})
    request = await CC.create_request(actor, company_id, {
        "entity_type": CONFIG_ENTITY_SALARY_COMPONENT, "entity_code": code, "reason": reason,
        "effective_from": payload.get("effective_from"),
        "title": f"{code} — {', '.join(sorted(changed))}"[:160]})
    await coll.update_one(key, {"$set": {"pending_request_no": request["request_no"]}})
    await audit(actor, AUDIT_SALARY_COMPONENT_SAVED, ENTITY_SALARY_COMPONENT, code,
                f"staged as {request['request_no']}", company_id,
                changes=[{"field": k, "old": current.get(k), "new": v}
                         for k, v in sorted(changed.items())])
    out = _out(await coll.find_one(key))
    out["pending_request"] = request
    return out


async def save_salary_component(actor: dict, company_id: str, payload: dict) -> dict:
    code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=422, detail="A component code is required.")
    clean = {k: _plain(v) for k, v in payload.items() if k != "code"}
    method = clean.get("calculation_method")
    if method == CalculationMethod.PERCENTAGE.value:
        if clean.get("percentage") is None or not 0 < float(clean["percentage"]) <= 1000:
            raise HTTPException(status_code=422,
                                detail="A percentage component needs a percentage above 0.")
        base = str(clean.get("calculation_base") or "").strip()
        if base.upper() in ("GROSS", "CTC"):
            base = base.upper()
        if not base:
            raise HTTPException(status_code=422,
                                detail="Say what the percentage is of (a component, GROSS or CTC).")
        if base == code:
            raise HTTPException(status_code=422, detail="A component cannot be a percentage of itself.")
        clean["calculation_base"] = base
        if base not in ("GROSS", "CTC"):
            known = {c["code"]: c for c in await list_salary_components(actor, company_id)}
            if base not in known:
                raise HTTPException(status_code=422, detail=f"Unknown base component '{base}'.")
            # Circular dependency guard (FRD §25): walk the base chain.
            seen, cursor = {code}, base
            while cursor in known and known[cursor].get("calculation_method") == \
                    CalculationMethod.PERCENTAGE.value:
                cursor = known[cursor].get("calculation_base")
                if cursor in seen:
                    raise HTTPException(status_code=422,
                                        detail=f"{code} would depend on itself through {cursor}.")
                seen.add(cursor)
    if method == CalculationMethod.FORMULA.value:
        from app.services import hrms_formula_engine as FE
        known = {c["code"] for c in await list_salary_components(actor, company_id)} | {code}
        constants = set(await constants_for(company_id))
        refs = FE.validate(clean.get("formula") or "", known, constants)
        if code.upper() in refs:
            raise HTTPException(status_code=422, detail=f"{code} cannot use itself in its formula.")
        clean["formula"] = str(clean["formula"]).strip()
    if method == CalculationMethod.SLAB.value:
        from app.services import hrms_formula_engine as FE
        clean["slabs"] = FE.clean_slabs(clean.get("slabs"))
        base = str(clean.get("calculation_base") or "").strip()
        if not base:
            raise HTTPException(status_code=422, detail="Say what the slab is applied to "
                                                        "(a component, GROSS or CTC).")
        clean["calculation_base"] = base.upper() if base.upper() in ("GROSS", "CTC") else base
    if method in (CalculationMethod.FORMULA.value, CalculationMethod.SLAB.value,
                  CalculationMethod.PERCENTAGE.value):
        # FRD §25: no circular dependency anywhere in the master once this is saved.
        from app.services import hrms_formula_engine as FE
        everything = {c["code"]: c for c in await list_salary_components(actor, company_id)}
        everything[code] = {**everything.get(code, {}), **clean, "code": code}
        loop = FE.find_cycle(everything)
        if loop:
            raise HTTPException(status_code=422,
                                detail=f"{code} would depend on itself: {' -> '.join(loop)}.")
    # ── §24 Lifecycle, Applicability, Frequency, Attendance Linked ──
    if clean.get("lifecycle") is not None:
        from app.models.hrms import ComponentLifecycle
        allowed = {l.value for l in ComponentLifecycle}
        if clean["lifecycle"] not in allowed:
            raise HTTPException(status_code=422,
                                detail=f"Lifecycle must be one of: {', '.join(sorted(allowed))}.")
    if clean.get("frequency") is not None:
        from app.models.hrms import COMPONENT_FREQUENCIES
        if clean["frequency"] not in COMPONENT_FREQUENCIES:
            raise HTTPException(
                status_code=422,
                detail=f"Frequency must be one of: {', '.join(COMPONENT_FREQUENCIES)}.")
    for key in ("effective_from", "effective_to"):
        if clean.get(key) and not is_iso_date(str(clean[key])):
            raise HTTPException(status_code=422,
                                detail=f"{key.replace('_', ' ').capitalize()} must be a date "
                                       f"(YYYY-MM-DD).")
    if clean.get("effective_from") and clean.get("effective_to") \
            and clean["effective_to"] < clean["effective_from"]:
        raise HTTPException(status_code=422, detail="Effective to is before effective from.")
    if clean.get("applicability") is not None:
        from app.services.hrms_policy_version_service import _clean_scope
        clean["applicability"] = _clean_scope(clean["applicability"])
    if method == CalculationMethod.ATTENDANCE_LINKED.value:
        basis = str(clean.get("attendance_basis") or "payable_days")
        allowed_basis = ("payable_days", "present_days", "lop_days", "working_days",
                         "weekly_off_days", "holiday_days", "leave_days")
        if basis not in allowed_basis:
            raise HTTPException(
                status_code=422,
                detail=f"Attendance basis must be one of: {', '.join(allowed_basis)}.")
        clean["attendance_basis"] = basis
        if clean.get("rate") is None:
            raise HTTPException(status_code=422,
                                detail="An attendance-linked component needs a rate — the "
                                       "amount earned per day.")
        if float(clean["rate"]) < 0:
            raise HTTPException(status_code=422, detail="The rate cannot be negative.")

    clean.pop("change_reason", None)
    for key in ("min_amount", "max_amount"):
        if clean.get(key) is not None and float(clean[key]) < 0:
            raise HTTPException(status_code=422, detail=f"{key} cannot be negative.")
    if clean.get("min_amount") is not None and clean.get("max_amount") is not None and \
            float(clean["min_amount"]) > float(clean["max_amount"]):
        raise HTTPException(status_code=422, detail="Minimum is above maximum.")

    now = datetime.now(timezone.utc)
    coll = get_collection(COLL_SALARY_COMPONENTS)
    current = await coll.find_one({"company_id": str(company_id), "code": code})
    if current and current.get("component_type") and clean.get("component_type") and \
            current["component_type"] != clean["component_type"]:
        used = await get_collection(COLL_PAYROLL_RECORDS).count_documents(
            {"company_id": str(company_id), "lines.code": code})
        if used:
            raise HTTPException(
                status_code=409,
                detail="This component has been paid in a payroll, so its type cannot "
                       "change. Retire it and create a new one.")
    # §22 Control 3 / §30: a component still referenced by a live formula or structure
    # cannot be retired until that is resolved. Checked only on the TRANSITION into a
    # retired state -- re-saving an already-retired component must not start failing.
    retiring = (clean.get("active") is False and (current or {}).get("active") is not False)         or (clean.get("lifecycle") == "Retired"
            and (current or {}).get("lifecycle") != "Retired")
    if retiring:
        from app.services.hrms_config_dependency_service import (
            ENTITY_COMPONENT, assert_retirable)
        await assert_retirable(company_id, ENTITY_COMPONENT, code)

    # §27 / §30 "revise a formula as a new version, simulate it, and obtain approval before
    # activation". Salary components are governed by default, and a governed revision of a
    # LIVE component (Active, or a pre-§24 one with no lifecycle) is HELD rather than written
    # over the definition payroll is using. Retiring is not the governed move, and a Draft
    # is edited freely: it has never paid anyone.
    if current:
        from app.models.hrms import CONFIG_ENTITY_SALARY_COMPONENT
        from app.services import hrms_config_change_service as CC
        if await CC.is_governed(company_id, CONFIG_ENTITY_SALARY_COMPONENT):
            target = clean.get("lifecycle")
            if target in GOVERNED_COMPONENT_STATES and target != current.get("lifecycle"):
                raise HTTPException(
                    status_code=409,
                    detail=f"{code} cannot be made {target} directly. Raise a configuration "
                           f"change request for it and have somebody else approve it, then "
                           f"activate it from Configuration Approvals (FRD §27).")
            live = current.get("lifecycle") in (None, "Active") and \
                current.get("active") is not False
            if live and not retiring:
                # Compared against the RESOLVED definition, and with "nothing" spelt any way
                # counting as nothing: the editor posts every key, and a pre-§24 component
                # stores few of them, so a raw comparison would send an untouched save for
                # approval.
                resolved = {**component_defaults(current),
                            "frequency": current.get("frequency") or "Monthly"}
                if not resolved.pop("proration_configured"):
                    # The editor posts "" for a type-default proration; that is no change.
                    resolved["proration"] = None
                empty = (None, "", [], {})
                changed = {k: v for k, v in clean.items()
                           if resolved.get(k) != v
                           and not (resolved.get(k) in empty and v in empty)}
                if not changed:
                    return _out(current)
                return await _stage_component_change(actor, company_id, current, changed,
                                                      payload, now)

    # DEF-02 -- a NEW component is configuration too. Unguarded, it was written with no
    # lifecycle, which the pay engine reads as live, so it paid from the moment it was
    # saved. Governed, it is created as a Draft and a §27 request is raised for it; it
    # becomes Active only through _component_activate, exactly like a revision.
    new_request_reason = None
    if not current:
        from app.models.hrms import CONFIG_ENTITY_SALARY_COMPONENT
        from app.services import hrms_config_change_service as CC
        if await CC.is_governed(company_id, CONFIG_ENTITY_SALARY_COMPONENT):
            if clean.get("lifecycle") in GOVERNED_COMPONENT_STATES:
                raise HTTPException(
                    status_code=409,
                    detail=f"{code} cannot be created {clean['lifecycle']}. New components "
                           f"start as Draft and go live once somebody else approves them in "
                           f"Configuration Approvals (FRD §27).")
            clean["lifecycle"] = "Draft"
            new_request_reason = (str(payload.get("change_reason") or "").strip()
                                  or f"New salary component {code}"
                                     + (f" ({clean['name']})" if clean.get("name") else ""))

    clean["updated_at"] = now
    change = {"at": now, "by": _actor_id(actor), "by_name": _actor_name(actor),
              "reason": (payload.get("change_reason") or "").strip() or None,
              "old": {k: (current or {}).get(k) for k in clean if k != "updated_at"},
              "new": {k: v for k, v in clean.items() if k != "updated_at"}}
    await coll.update_one(
        {"company_id": str(company_id), "code": code},
        {"$set": {**clean, "version": int((current or {}).get("version") or 0) + 1},
         "$setOnInsert": {"company_id": str(company_id), "code": code, "created_at": now},
         "$push": {"history": change}},
        upsert=True,
    )
    await audit(actor, AUDIT_SALARY_COMPONENT_SAVED, ENTITY_SALARY_COMPONENT, code,
                clean.get("component_type"), company_id)
    if new_request_reason:
        request = await CC.create_request(actor, company_id, {
            "entity_type": CONFIG_ENTITY_SALARY_COMPONENT, "entity_code": code,
            "reason": new_request_reason, "effective_from": payload.get("effective_from"),
            "title": f"{code} — new component"[:160]})
        await coll.update_one({"company_id": str(company_id), "code": code},
                              {"$set": {"pending_request_no": request["request_no"]}})
        out = _out(await coll.find_one({"company_id": str(company_id), "code": code}))
        out["pending_request"] = request
        return out
    doc = await coll.find_one({"company_id": str(company_id), "code": code})
    return _out(doc)


async def list_salary_components(actor: dict, company_id: str) -> list:
    rows = await get_collection(COLL_SALARY_COMPONENTS).find(
        {"company_id": str(company_id)}).sort("code", 1).to_list(200)
    return [component_defaults(_out(r)) for r in rows]


# ─────────────────────────────────────────────────────────────
# FRD §9 — effective-dated salary structure
# ─────────────────────────────────────────────────────────────
def resolve_lines(lines: list, meta: dict, *, annual_ctc: Optional[float] = None,
                  days: Optional[dict] = None, profile: Optional[dict] = None,
                  period_end: Optional[str] = None, constants: Optional[dict] = None,
                  inputs: Optional[dict] = None) -> list:
    """Turn the entered lines into monthly amounts, in sequence order.

    A Percentage line is computed from its base: another component already resolved, GROSS
    (the earnings resolved so far) or CTC (annual CTC / 12). A base that is resolved LATER
    is refused rather than guessed -- that is what keeps formulas acyclic (FRD §25).
    """
    indexed = list(enumerate(lines))
    indexed.sort(key=lambda p: ((meta.get(p[1]["code"]) or {}).get("sequence", 100), p[0]))
    resolved, out = {}, []
    for _i, line in indexed:
        code = line["code"]
        m = component_defaults(meta.get(code) or {"component_type": ComponentType.EARNING.value})
        method = m["calculation_method"]
        pct = line.get("percentage")
        if pct is None:
            pct = m.get("percentage")
        base_code = m.get("calculation_base")
        if method in (CalculationMethod.FORMULA.value, CalculationMethod.SLAB.value):
            amount = _formula_or_slab(m, code, resolved, meta, lines, annual_ctc,
                                  days=days, profile=profile, period_end=period_end,
                                  constants=constants, inputs=inputs)
        elif method == CalculationMethod.PERCENTAGE.value and pct is not None:
            if base_code == "GROSS":
                base_amount = sum(v for c, v in resolved.items()
                                  if (meta.get(c) or {}).get("component_type")
                                  == ComponentType.EARNING.value)
            elif base_code == "CTC":
                if not annual_ctc:
                    raise HTTPException(status_code=422,
                                        detail=f"{m.get('name') or code} is a % of CTC: enter the annual CTC.")
                base_amount = float(annual_ctc) / 12.0
            else:
                if base_code not in resolved:
                    raise HTTPException(
                        status_code=422,
                        detail=f"{m.get('name') or code} is calculated from {base_code}, which "
                               f"is missing from this structure or comes later in the sequence.")
                base_amount = resolved[base_code]
            amount = base_amount * float(pct) / 100.0
        else:
            amount = float(line.get("amount") or 0)
        if amount < 0:
            raise HTTPException(status_code=422, detail=f"{code}: amounts cannot be negative.")
        if m.get("min_amount") is not None:
            amount = max(amount, float(m["min_amount"]))
        if m.get("max_amount") is not None:
            amount = min(amount, float(m["max_amount"]))
        amount = _round(amount, m["rounding"])
        resolved[code] = amount
        out.append({"code": code, "amount": amount,
                    "method": method, "percentage": pct if method ==
                    CalculationMethod.PERCENTAGE.value else None,
                    # what was typed for THIS employee, apart from the component default --
                    # a simulation of a new default must not be masked by the old one
                    "percentage_override": line.get("percentage"),
                    "base": base_code if method in (CalculationMethod.PERCENTAGE.value,
                                                    CalculationMethod.SLAB.value) else None,
                    "formula": m.get("formula") if method == CalculationMethod.FORMULA.value
                    else None,
                    # §25 Audit / §30 reproducibility: the component version alone is not
                    # enough to reproduce a line -- the same version number means nothing
                    # once the component master has been edited. The slab table and the
                    # formula TEXT that actually produced this amount travel with it.
                    "slabs": m.get("slabs") if method == CalculationMethod.SLAB.value else None,
                    "component_version": m.get("version")})
    return out


def _formula_or_slab(m: dict, code: str, resolved: dict, meta: dict, lines: list,
                     annual_ctc, *, days=None, profile=None, period_end=None,
                     constants=None, inputs=None) -> float:
    """A Formula or Slab line, from what is already resolved. A variable that IS in this
    structure but comes later in the sequence is refused (that is how loops stay out);
    one that is not in the structure at all counts as 0."""
    from app.services import hrms_formula_engine as FE
    in_structure = {l["code"] for l in lines}
    gross = sum(v for c, v in resolved.items()
                if (meta.get(c) or {}).get("component_type") == ComponentType.EARNING.value)
    # §25 Variables. The attendance figures come from the basis the run already froze
    # (never re-derived here), so a formula and the payable-days arithmetic cannot disagree.
    env = {**resolved, "GROSS": gross, "CTC": float(annual_ctc or 0),
           "MONTHLY_CTC": float(annual_ctc or 0) / 12.0,
           **FE.attendance_variables(days or {}),
           **FE.employee_variables(profile or {}, period_end),
           **FE.input_variables(inputs or {}),
           **{str(k).upper(): float(v or 0) for k, v in (constants or {}).items()}}
    name = m.get("name") or code
    needed = FE.dependencies(m)
    late = sorted(d for d in needed if d in in_structure and d not in resolved)
    if late:
        raise HTTPException(status_code=422,
                            detail=f"{name} uses {', '.join(late)}, which is worked out later "
                                   f"in the sequence. Give {name} a higher sequence number.")
    if m["calculation_method"] == CalculationMethod.FORMULA.value:
        return max(0.0, FE.evaluate(m.get("formula") or "0", env))
    base = str(m.get("calculation_base") or "GROSS")
    base_value = env.get(base.upper()) if base.upper() in FE.BUILT_INS else resolved.get(base, 0.0)
    return FE.slab_amount(m.get("slabs") or [], float(base_value or 0))


def _structure_totals(lines: list, meta: dict) -> dict:
    by_type = {}
    for line in lines:
        ctype = (meta.get(line["code"]) or {}).get("component_type") or ComponentType.EARNING.value
        by_type[ctype] = by_type.get(ctype, 0.0) + float(line.get("amount") or 0)
    gross = by_type.get(ComponentType.EARNING.value, 0.0) + \
        by_type.get(ComponentType.REIMBURSEMENT.value, 0.0)
    deductions = sum(v for t, v in by_type.items() if t in DEDUCTING_TYPES)
    employer = by_type.get(ComponentType.EMPLOYER_CONTRIBUTION.value, 0.0)
    return {"monthly_gross": round(gross, 2), "monthly_deductions": round(deductions, 2),
            "monthly_employer_contributions": round(employer, 2),
            "monthly_net": round(gross - deductions, 2)}


async def _policy_version_ref(company_id: str, on_date: str,
                              profile: Optional[dict] = None) -> Optional[dict]:
    """Which PAY_POLICY version was consumed, or None where the company runs on its stored
    settings. Stamped for §30 reproducibility.

    `profile` is what makes this answerable per EMPLOYEE. The run-level stamp (no profile)
    names the company-wide version; a record's stamp names the version that actually
    decided that person's amounts, which under a scoped policy is a different version. One
    stamp could not describe both, and the record's is the one a payslip query needs.
    """
    from app.models.hrms import POLICY_PAY_POLICY
    from app.services import hrms_policy_version_service as PV
    version = await PV.resolve(company_id, POLICY_PAY_POLICY, profile or {}, on_date)
    if not version:
        return None
    return {"policy_code": POLICY_PAY_POLICY, "version_no": version.get("version_no"),
            "effective_from": version.get("effective_from"),
            "matched_scope": version.get("matched_scope")}


async def _last_final_period(company_id: str) -> Optional[str]:
    runs = await get_collection(COLL_PAYROLL_RUNS).find(
        {"company_id": str(company_id), "status": {"$in": list(PAYROLL_FINAL_STATUSES)}},
        {"period": 1}).to_list(500)
    return max((r["period"] for r in runs if r.get("period")), default=None)


async def save_salary_structure(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    profile = await _get_profile(company_id, employee_code)
    components = payload.get("components") or []
    if not components:
        raise HTTPException(status_code=422, detail="At least one component is required.")
    effective_from = str(payload.get("effective_from") or "")
    if not is_iso_date(effective_from):
        raise HTTPException(status_code=422, detail="Effective from must be YYYY-MM-DD.")
    # FRD §9 History: "past payroll cannot be rewritten" -- a structure may not start inside
    # a period whose payroll is already locked; that difference is paid as an arrear.
    last_final = await _last_final_period(company_id)
    if last_final and effective_from[:7] <= last_final:
        raise HTTPException(
            status_code=409,
            detail=f"Payroll is locked up to {last_final}. A structure can start from "
                   f"{_next_period(last_final)}-01; pay any earlier difference as an arrear "
                   f"(post-lock adjustment).")

    meta = {c["code"]: c for c in await list_salary_components(actor, company_id)}
    lines, seen = [], set()
    for c in components:
        c = dict(c) if isinstance(c, dict) else c.model_dump()
        code = str(c.get("code") or "").strip()
        if code not in meta:
            raise HTTPException(status_code=422, detail=f"Unknown salary component '{code}'.")
        if not meta[code].get("active", True):
            raise HTTPException(status_code=422, detail=f"{code} is retired and cannot be used.")
        if code in seen:
            raise HTTPException(status_code=422, detail=f"{code} appears twice.")
        seen.add(code)
        lines.append({"code": code, "amount": c.get("amount") or 0,
                      "percentage": c.get("percentage")})
    annual_ctc = payload.get("annual_ctc")
    resolved = resolve_lines(lines, meta, annual_ctc=annual_ctc)
    totals = _structure_totals(resolved, meta)
    if not annual_ctc:
        annual_ctc = round((totals["monthly_gross"] + totals["monthly_employer_contributions"])
                           * 12, 2)

    # Employee-level: whether THIS person's salary needs a second approval. A policy
    # scoped to a grade or a location is the obvious way to ask for it, and passing no
    # profile here meant such a policy applied to nobody.
    policy = await get_payroll_policy(company_id, profile=profile)
    needs_approval = bool(policy.get("structure_approval_required"))
    now = datetime.now(timezone.utc)
    names = await _employee_names([profile])
    doc = {
        "company_id": str(company_id), "employee_code": employee_code,
        "employee_name": _name_of(profile, names),
        "payroll_group": payload.get("payroll_group") or profile.get("payroll_group"),
        "structure_name": (payload.get("structure_name") or profile.get("salary_template")
                           or None),
        "revision_reason": (payload.get("revision_reason") or "").strip() or None,
        "comments": (payload.get("comments") or "").strip() or None,
        "effective_from": effective_from,
        "components": resolved,
        "annual_ctc": round(float(annual_ctc), 2),
        **totals,
        "status": StructureStatus.PENDING.value if needs_approval else StructureStatus.ACTIVE.value,
        "created_by": _actor_id(actor), "created_by_name": _actor_name(actor),
        "submitted_by": _actor_id(actor), "submitted_by_name": _actor_name(actor),
        "submitted_at": now,
        "approved_by": None if needs_approval else _actor_id(actor),
        "approved_by_name": None if needs_approval else _actor_name(actor),
        "approved_at": None if needs_approval else now,
        "approval_mode": "maker-checker" if needs_approval else "direct (approval not required)",
        "created_at": now, "updated_at": now,
    }
    result = await get_collection(COLL_SALARY_STRUCTURES).insert_one(doc)
    doc["id"] = str(result.inserted_id)
    await audit(actor, AUDIT_SALARY_STRUCTURE_SAVED, ENTITY_SALARY_STRUCTURE, employee_code,
                f"effective {effective_from}, {doc['status']}", company_id)
    return _out(doc)


async def decide_structure(actor: dict, company_id: str, structure_id: str,
                           payload: dict) -> dict:
    """The checker's decision on a structure awaiting approval -- never by its maker."""
    try:
        oid = ObjectId(structure_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid structure id.")
    coll = get_collection(COLL_SALARY_STRUCTURES)
    doc = await coll.find_one({"_id": oid, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Structure not found.")
    if doc.get("status") != StructureStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"This structure is {doc.get('status')}.")
    if doc.get("created_by") and doc["created_by"] == _actor_id(actor):
        raise HTTPException(status_code=403,
                            detail="You set this structure, so someone else must approve it.")
    approved = bool(payload.get("approved"))
    now = datetime.now(timezone.utc)
    updates = {"status": StructureStatus.ACTIVE.value if approved else StructureStatus.REJECTED.value,
               "approved_by": _actor_id(actor), "approved_by_name": _actor_name(actor),
               "approved_at": now, "decision_comments": payload.get("comments"),
               "updated_at": now}
    await coll.update_one({"_id": oid}, {"$set": updates})
    await audit(actor, AUDIT_STRUCTURE_DECIDED, ENTITY_SALARY_STRUCTURE, doc["employee_code"],
                updates["status"], company_id)
    out = _out(await coll.find_one({"_id": oid}))
    out["id"] = structure_id
    return out


async def get_current_structure(company_id: str, employee_code: str,
                                as_of: Optional[str] = None) -> Optional[dict]:
    """The latest APPROVED structure whose effective_from is on or before `as_of` (default
    today) — never overwritten, the same never-edit-history discipline Phase MOVE-1's
    movements use. A structure awaiting approval, or rejected, is never paid."""
    as_of = as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = await get_collection(COLL_SALARY_STRUCTURES).find(
        {"company_id": str(company_id), "employee_code": employee_code,
         "effective_from": {"$lte": as_of}, "status": {"$nin": NON_ACTIVE_STRUCTURE}},
    ).to_list(500)
    if not rows:
        return None
    # Latest effective date wins; two revisions on the same date -> the later one saved.
    doc = max(rows, key=lambda r: (str(r.get("effective_from") or ""),
                                   r.get("created_at") or datetime.min.replace(tzinfo=timezone.utc)
                                   if isinstance(r.get("created_at"), datetime) else datetime.min))
    out = _out(doc)
    out["id"] = str(doc["_id"]) if doc.get("_id") is not None else None
    return out


async def list_structure_history(actor: dict, company_id: str, employee_code: str) -> list:
    """Every revision, newest first, with Effective To derived from the next approved one."""
    rows = await get_collection(COLL_SALARY_STRUCTURES).find(
        {"company_id": str(company_id), "employee_code": employee_code}
    ).sort("effective_from", -1).to_list(100)
    approved = sorted((r for r in rows if r.get("status") not in NON_ACTIVE_STRUCTURE),
                      key=lambda r: (r["effective_from"], r.get("created_at") or datetime.min))
    effective_to = {}
    for i, r in enumerate(approved):
        if i + 1 < len(approved):
            nxt = date.fromisoformat(approved[i + 1]["effective_from"][:10])
            effective_to[str(r["_id"])] = (nxt - timedelta(days=1)).isoformat()
    meta = {c["code"]: c for c in await list_salary_components(actor, company_id)}
    out = []
    for r in rows:
        item = _out(r)
        item["id"] = str(r["_id"])
        item["status"] = r.get("status") or StructureStatus.ACTIVE.value
        item["effective_to"] = effective_to.get(str(r["_id"]))
        if "monthly_gross" not in item:
            item.update(_structure_totals(item.get("components") or [], meta))
        out.append(item)
    return out


async def structure_summary(company_id: str, employee_code: str) -> Optional[dict]:
    """FRD §3 Salary linkage, for the employee profile."""
    current = await get_current_structure(company_id, employee_code)
    if not current:
        return None
    if "monthly_gross" not in current:
        meta = {c["code"]: c for c in await list_salary_components(None, company_id)}
        current.update(_structure_totals(current.get("components") or [], meta))
        current["annual_ctc"] = round((current["monthly_gross"]
                                       + current["monthly_employer_contributions"]) * 12, 2)
    return {k: current.get(k) for k in (
        "effective_from", "structure_name", "payroll_group", "annual_ctc", "monthly_gross",
        "monthly_deductions", "monthly_employer_contributions", "status")}


# A process-local cache of component_type by code, refreshed before each run. Mutated in
# place (never rebound) so a module that imported the dict keeps seeing the live values.
_component_type_cache: dict = {}
_component_meta_cache: dict = {}


def component_on(component: dict, period_end: str) -> dict:
    """The definition of a component IN FORCE on `period_end` (DEF-01, §25 "formula has
    version, effective dates").

    Activating a revision overwrites the live definition and keeps the one it replaced in
    `versions` as Superseded. A run for a period BEFORE the revision's effective date must
    be priced by that earlier version -- reading only the live definition gave a February
    run the March formula, or dropped the component altogether because its live
    `effective_from` was now later than February. The earlier version runs until the day
    before its successor starts.
    """
    start = component.get("effective_from")
    versions = [v for v in component.get("versions") or [] if v.get("status") == "Superseded"]
    if not period_end or not start or start <= period_end or not versions:
        return component
    earlier = [v for v in versions
               if not str((v.get("definition") or {}).get("effective_from") or "") > period_end]
    if not earlier:
        return component
    chosen = max(earlier, key=lambda v: int(v.get("version") or 0))
    definition = dict(chosen.get("definition") or {})
    out = {**component, **definition, "version": chosen.get("version"),
           "effective_from": definition.get("effective_from")}
    until = (date.fromisoformat(start[:10]) - timedelta(days=1)).isoformat()
    if not out.get("effective_to") or out["effective_to"] > until:
        out["effective_to"] = until
    return component_defaults(out)


async def _load_component_types(company_id: str) -> None:
    rows = await list_salary_components(None, company_id)
    _component_type_cache.clear()
    _component_type_cache.update({r["code"]: r["component_type"] for r in rows})
    _component_meta_cache.clear()
    _component_meta_cache.update({r["code"]: r for r in rows})


def _structure_gross(structure: Optional[dict]) -> float:
    """Monthly earnings of a structure (Earning lines only -- what 'gross salary' has always
    meant to the advance limit and Compensation Change)."""
    if not structure:
        return 0.0
    return round(sum(
        float(c.get("amount") or 0) for c in structure.get("components", [])
        if _component_type_cache.get(c.get("code")) == ComponentType.EARNING.value
    ), 2)


def _structure_deductions(structure: Optional[dict]) -> float:
    """The Deduction / Recovery lines of a structure — e.g. a fixed monthly Professional
    Tax. Not prorated unless the component says so."""
    if not structure:
        return 0.0
    return round(sum(
        float(c.get("amount") or 0) for c in structure.get("components", [])
        if _component_type_cache.get(c.get("code")) in DEDUCTING_TYPES
    ), 2)


async def _employee_names(profiles: list) -> dict:
    """user_id -> display name, for profiles that do not carry their own."""
    ids = [ObjectId(p["user_id"]) for p in profiles
           if p.get("user_id") and ObjectId.is_valid(str(p["user_id"]))]
    names: dict = {}
    if not ids:
        return names
    for coll in ("staff", "learners"):
        rows = await get_collection(coll).find(
            {"_id": {"$in": ids}},
            {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1}).to_list(len(ids))
        for u in rows:
            names[str(u["_id"])] = (
                u.get("full_name")
                or f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip()
                or u.get("email"))
    return names


def _name_of(profile: dict, names: dict) -> Optional[str]:
    return (profile.get("display_name") or profile.get("full_name")
            or names.get(str(profile.get("user_id") or ""))
            or (profile.get("identity_snapshot") or {}).get("name"))


# ─────────────────────────────────────────────────────────────
# §7.12 / FRD §10 — attendance basis: payable days, LOP and the day counts
# ─────────────────────────────────────────────────────────────
async def _unpaid_leave_refs(company_id: str, refs: set) -> set:
    if not refs:
        return set()
    from app.models.hrms import COLL_LEAVES, COLL_LEAVE_TYPES
    leaves = await get_collection(COLL_LEAVES).find(
        {"company_id": str(company_id), "leave_no": {"$in": list(refs)}},
        {"leave_no": 1, "leave_type": 1}).to_list(len(refs))
    types = {t.get("code"): t for t in await get_collection(COLL_LEAVE_TYPES).find(
        {"company_id": str(company_id)}).to_list(100)}
    unpaid = set()
    for lv in leaves:
        code = str(lv.get("leave_type") or "")
        t = types.get(code) or {}
        if code.upper() in UNPAID_LEAVE_CODES or t.get("paid") is False:
            unpaid.add(lv["leave_no"])
    return unpaid


def _stored_share(row: dict, kind: str, default_lop: float, default_present: float,
                  bucket: str) -> tuple:
    """Value a day from the fractions the attendance row FROZE, not from its status.

    `payable_day` / `lop_fraction` are written by the day calculator under the ATT_DAY
    policy in force on that date, so they already carry `half_day_fraction` and anything
    else that decided what the day was worth. Payroll's own numbers are the fallback for a
    row that predates the policy (neither field stored) -- which is the only case where
    re-deciding from the status is the best available answer.

    The two fields are honoured INDEPENDENTLY: `lop_fraction` sets the LOP share and
    `payable_day` the present share, which is how they are reported. A row carrying only
    one of them has the other derived, because the calculator writes them as complements.
    """
    def _num(value):
        try:
            return min(1.0, max(0.0, float(value)))
        except (TypeError, ValueError):     # a hand-edited row carrying a string
            return None

    lop = _num(row.get("lop_fraction"))
    present = _num(row.get("payable_day"))
    if lop is None and present is None:
        return (kind, default_lop, default_present, bucket)
    if lop is None:
        lop = 1.0 - present
    if present is None:
        present = 1.0 - lop
    return (kind, round(lop, 2), round(present, 2), bucket)


async def _payable_days(company_id: str, employee_code: str, period: str,
                        profile: Optional[dict] = None, calendar: Optional[dict] = None,
                        sandwich: bool = False) -> dict:
    """Every in-service day of the period is either payable or LOP.

    Present / On OD / paid leave / Weekly Off / Holiday are payable; Absent,
    unpaid leave (LWP) and a working day with NO attendance row are LOP -- the
    safer-for-the-company default where the record is silent. A day with no row that the
    employee's calendar says is a weekly off or holiday is payable. Days before joining or
    after the last working day are outside service: unpaid, but not LOP.

    How much a day is worth is the ATTENDANCE row's answer, not payroll's. The day
    calculator already applied the ATT_DAY policy in force on that date -- `half_day_fraction`
    among it -- and froze the result on the row as `payable_day` / `lop_fraction`. Payroll
    re-deciding it from the status alone is how a company that configured a half day to cost
    a quarter got charged a half in pay: the attendance screen and the payslip disagreed
    about the same day. So for a day whose worth its STATUS fixes, the stored fraction wins
    and 0.5-for-a-half-day is only the fallback for rows written before the policy existed.

    Two statuses deliberately keep payroll's own answer. ON LEAVE is decided by the LEAVE
    TYPE (paid or unpaid), which the day row does not know -- it stores 1.0 for every leave
    day, so honouring it would pay LWP. WEEKLY OFF / HOLIDAY are "off" days whose LOP share
    the sandwich rule below may still set, which is a payroll policy and not an attendance
    fact.

    `sandwich` (payroll policy): a weekly off / holiday whose neighbouring working days are
    LOP on both sides (or on its only side) is LOP too -- otherwise somebody with no
    attendance at all would still be paid every Sunday of the month.
    """
    _y, _m, days_in_period, start, end = _period_bounds(period)
    rows = await get_collection(COLL_ATTENDANCE).find(
        {"company_id": str(company_id), "employee_code": employee_code,
         "work_date": {"$gte": start, "$lte": end}},
        {"status": 1, "work_date": 1, "leave_ref": 1,
         "payable_day": 1, "lop_fraction": 1},
    ).to_list(40)
    by_day = {r.get("work_date") or "": r for r in rows}
    unpaid_refs = await _unpaid_leave_refs(
        company_id, {r["leave_ref"] for r in rows if r.get("leave_ref")})
    cal_days = (calendar or {}).get("days") or {}
    doj = (profile or {}).get("joined_on")
    lwd = (profile or {}).get("resigned_on")

    # One entry per in-service day: (kind, lop share, present share, bucket)
    #   kind: "work" (a working day) or "off" (weekly off / holiday)
    days = []
    out_of_service = 0
    unrecorded = pending = 0
    for d in range(1, days_in_period + 1):
        ds = f"{period}-{d:02d}"
        if (doj and ds < doj) or (lwd and ds > lwd):
            out_of_service += 1
            continue
        row = by_day.get(ds)
        status = (row or {}).get("status")
        if row is None:
            kind = cal_days.get(ds)
            if kind in ("Holiday", "Weekly Off"):
                days.append(("off", 0.0, 0.0, kind))
            else:
                days.append(("work", 1.0, 0.0, "unrecorded"))
                unrecorded += 1
            continue
        if status in (AttendanceStatus.PRESENT.value, AttendanceStatus.ON_OD.value):
            days.append(_stored_share(row, "work", 0.0, 1.0, "present"))
        elif status == AttendanceStatus.HALF_DAY.value:
            days.append(_stored_share(row, "work", 0.5, 0.5, "half_day"))
        elif status == AttendanceStatus.ABSENT.value:
            days.append(_stored_share(row, "work", 1.0, 0.0, "absent"))
        elif status == AttendanceStatus.ON_LEAVE.value:
            unpaid = row.get("leave_ref") in unpaid_refs
            days.append(("work", 1.0 if unpaid else 0.0, 0.0, "lwp" if unpaid else "leave"))
        elif status == AttendanceStatus.WEEKLY_OFF.value:
            days.append(("off", 0.0, 0.0, "Weekly Off"))
        elif status == AttendanceStatus.HOLIDAY.value:
            days.append(("off", 0.0, 0.0, "Holiday"))
        elif status == AttendanceStatus.PENDING.value:
            days.append(_stored_share(row, "work", 1.0, 0.0, "pending"))
            pending += 1
        else:
            days.append(("work", 0.0, 1.0, "present"))

    sandwiched = 0
    if sandwich:
        work_idx = [i for i, d in enumerate(days) if d[0] == "work"]
        for i, d in enumerate(days):
            if d[0] != "off":
                continue
            before = next((days[j] for j in reversed(work_idx) if j < i), None)
            after = next((days[j] for j in work_idx if j > i), None)
            sides = [x for x in (before, after) if x is not None]
            if sides and all(x[1] >= 1.0 for x in sides):
                days[i] = ("off", 1.0, 0.0, d[3] + " (sandwiched)")
                sandwiched += 1

    lop = sum(d[1] for d in days)
    present = sum(d[2] for d in days)
    weekly_off = sum(1 for d in days if d[3] == "Weekly Off")
    holidays = sum(1 for d in days if d[3] == "Holiday")
    leave_days = sum(1 for d in days if d[3] == "leave")
    in_service = days_in_period - out_of_service
    payable = round(in_service - lop, 2)

    # FRD §18: "Payroll must use the LOCKED attendance snapshot, not live editable
    # attendance." The month lock already stops attendance being written, so the figures
    # above were correct when they were computed -- but nothing RECORDED what they were
    # computed from, so an unlock, an edit and a recalculation would move an employee's pay
    # with no trace of which basis produced which number. This is that trace: one entry per
    # in-service day, exactly as the sum above counted it, sandwich rule included.
    basis = []
    cursor = 0
    for d in range(1, days_in_period + 1):
        ds = f"{period}-{d:02d}"
        if (doj and ds < doj) or (lwd and ds > lwd):
            continue
        kind, lop_share, present_share, bucket = days[cursor]
        cursor += 1
        basis.append({"date": ds, "kind": kind, "bucket": bucket,
                      "lop": round(lop_share, 2), "present": round(present_share, 2)})

    return {
        "days_in_period": days_in_period, "payable_days": payable,
        "lop_days": round(lop, 2), "present_days": round(present, 2),
        "weekly_off_days": weekly_off, "holiday_days": holidays, "leave_days": leave_days,
        "working_days": (calendar or {}).get("working_days"),
        "out_of_service_days": out_of_service, "unrecorded_days": unrecorded,
        "pending_days": pending, "sandwiched_off_days": sandwiched,
        "basis": basis,
    }


# ─────────────────────────────────────────────────────────────
# FRD §10-§12 — the payroll run
# ─────────────────────────────────────────────────────────────
def _trail(actor: dict, stage: str, action: str, remarks: Optional[str] = None) -> dict:
    return {"stage": stage, "action": action, "by": _actor_id(actor),
            "by_name": _actor_name(actor), "at": datetime.now(timezone.utc),
            "remarks": remarks}


async def create_run(actor: dict, company_id: str, payload: dict) -> dict:
    period = str(payload.get("period") or "")
    year, month, _days, start, end = _period_bounds(period)
    existing = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": period})
    if existing:
        raise HTTPException(status_code=409, detail=f"A payroll run for {period} already exists.")

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "period": period, "month": month, "year": year,
        "period_start": start, "period_end": end,
        "status": PayrollRunStatus.DRAFT.value,
        "eligible_count": 0, "created_by": _actor_id(actor), "created_at": now,
        "calculated_at": None, "submitted_by": None, "submitted_at": None,
        "decided_by": None, "decided_at": None, "decision_remarks": None,
        "locked_by": None, "locked_at": None, "closed_at": None,
        "totals": None, "approval_trail": [_trail(actor, "Maker", "Opened period")],
        "updated_at": now,
    }
    await get_collection(COLL_PAYROLL_RUNS).insert_one(doc)
    await audit(actor, AUDIT_PAYROLL_RUN_CREATED, ENTITY_PAYROLL_RUN, period, None, company_id)
    return _out(doc)


async def list_runs(actor: dict, company_id: str, limit: int = 100) -> list:
    rows = await get_collection(COLL_PAYROLL_RUNS).find(
        {"company_id": str(company_id)}).sort("period", -1).to_list(min(limit, MAX_PAYROLL_LIST_PAGE))
    return [_out(r) for r in rows]


async def _get_run(company_id: str, period: str) -> dict:
    doc = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": period})
    if not doc:
        raise HTTPException(status_code=404, detail=f"No payroll run for {period}.")
    return doc


async def get_run(actor: dict, company_id: str, period: str) -> dict:
    run = _out(await _get_run(company_id, period))
    lock = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
        {"company_id": str(company_id), "period": period})
    run["attendance_locked"] = (lock or {}).get("status") == "Locked"
    run["policy"] = await get_payroll_policy(company_id)
    # P1-095: the configured chain and the stage this run waits on (None = default matrix).
    chain = approval_chain(run["policy"])
    run["approval_chain"] = chain
    idx = _stage_index(run, chain) if chain else None
    run["current_stage"] = ({**chain[idx], "index": idx, "count": len(chain)}
                            if idx is not None else None)
    # FRD §18 — told to the screen BEFORE anyone clicks Submit, rather than only refusing
    # the click. A maker who unlocked the month to fix one day should see that the run is
    # stale while they are looking at it.
    run["attendance_basis_stale"] = await attendance_basis_moved(company_id, period, run)
    return run


def _assert_editable(run: dict) -> None:
    if run["status"] not in PAYROLL_EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(f"The {run['period']} payroll is {run['status']}. Inputs can change only "
                    f"while it is with the maker; a locked payroll is corrected by a post-lock "
                    f"adjustment, never in place (FRD §18)."))


async def _assert_inputs_open(actor: dict, company_id: str, period: str) -> None:
    """§19 Monthly Cut-off, where the payroll policy enforces it: a period's monthly inputs
    close on `input_cutoff_day` of that month (clamped to its length). After that only
    someone who can APPROVE payroll changes them -- a late input is a decision, not data
    entry. Not enforced (the default), the day stays advisory, as before."""
    year, month, days, _start, end = _period_bounds(period)
    policy = await get_payroll_policy(company_id, on_date=end)
    if not policy.get("enforce_input_cutoff"):
        return
    cutoff = f"{period}-{min(int(policy.get('input_cutoff_day') or days), days):02d}"
    today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    from app.models.hrms import Cap
    from app.utils.hrms_access import can
    if today > cutoff and not can(actor, Cap.PAYROLL_APPROVE):
        raise HTTPException(
            status_code=409,
            detail=f"Inputs for {period} closed on {cutoff} (the payroll policy cut-off). "
                   f"Someone who approves payroll can still change them.")


ADJ_PENDING, ADJ_APPROVED = "Pending", "Approved"


def _adjustment_key(a: dict) -> tuple:
    return (a.get("code"), round(float(a.get("amount") or 0), 2), a.get("reason"),
            a.get("reference"))


async def approve_adjustment(actor: dict, company_id: str, period: str, employee_code: str,
                             index: int) -> dict:
    """§10 Manual Adjustment "approval where needed": a second person approves a one-off
    line above the policy's amount. Never the person who entered it."""
    run = await _get_run(company_id, period)
    _assert_editable(run)
    coll = get_collection(COLL_PAYROLL_RECORDS)
    record = await coll.find_one(
        {"company_id": str(company_id), "period": period, "employee_code": employee_code})
    if not record:
        raise HTTPException(status_code=404, detail="No payroll record for that employee in this run.")
    lines = list(record.get("adjustments") or [])
    if not 0 <= index < len(lines) or lines[index].get("approval_status") != ADJ_PENDING:
        raise HTTPException(status_code=409, detail="That line is not waiting for approval.")
    if lines[index].get("entered_by") and lines[index]["entered_by"] == _actor_id(actor):
        raise HTTPException(status_code=403,
                            detail="You entered this line, so the approval is someone else's.")
    lines[index] = {**lines[index], "approval_status": ADJ_APPROVED,
                    "approved_by": _actor_id(actor), "approved_by_name": _actor_name(actor),
                    "approved_at": datetime.now(timezone.utc)}
    await coll.update_one({"_id": record["_id"]},
                          {"$set": {"adjustments": lines,
                                    "updated_at": datetime.now(timezone.utc)}})
    await audit(actor, AUDIT_PAYROLL_ADJUSTMENTS_SET, ENTITY_PAYROLL_RUN,
                f"{period}:{employee_code}", f"approved {lines[index].get('code')} "
                f"{lines[index].get('amount')}", company_id)
    return _out(await coll.find_one({"_id": record["_id"]}))


async def _eligible_profiles(company_id: str, start: str, end: str,
                             excluded_categories=None) -> list:
    """Payable employees, plus anyone who left during the period (their last month is still
    paid up to the last working day), minus anyone joining after it ends.

    FRD §4 / §21: minus anyone HR has switched off for payroll (`payroll_active` False) and
    any category the payroll policy leaves out. Both are unset by default."""
    from app.models.hrms import PAYABLE_STATUSES
    payable = [s.value for s in PAYABLE_STATUSES]
    excluded = {str(c).strip().lower() for c in (excluded_categories or [])}
    rows = await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id)}).to_list(5000)
    out = []
    for p in rows:
        if not p.get("employee_code"):
            continue
        if p.get("payroll_active") is False:
            continue
        if excluded and str(p.get("employee_category") or "").strip().lower() in excluded:
            continue
        if p.get("joined_on") and p["joined_on"] > end:
            continue
        status = p.get("employment_status")
        if status in payable:
            out.append(p)
        elif p.get("resigned_on") and start <= p["resigned_on"] <= end:
            out.append(p)
    return out


def _proration_ratio(rule: str, days: dict, ratio: float) -> float:
    """What fraction of a component is earned this period (FRD §24 Proration).

    The rules differ in their DENOMINATOR, which is the whole point: a conveyance
    allowance that only accrues on days worked is underpaid by a calendar-day divisor in a
    month with five Sundays, and overpaid by it in a month with four.
    """
    if rule == ProrationRule.PAYABLE_DAYS.value:
        return ratio
    if rule == ProrationRule.WORKING_DAYS.value:
        working = float(days.get("working_days") or 0)
        if working <= 0:
            # No working-day count on the calendar (an unconfigured holiday calendar, say).
            # Falling back to the payable-days ratio is the conservative answer: it is what
            # the component would have paid before this rule existed.
            return ratio
        off = float(days.get("weekly_off_days") or 0) + float(days.get("holiday_days") or 0)
        payable_working = max(0.0, float(days.get("payable_days") or 0) - off)
        return min(1.0, payable_working / working)
    # FULL_MONTH and NONE both pay in full; see the enum for why they are separate names.
    return 1.0


def _applies_to(component: dict, profile: dict, period_end: str) -> bool:
    """§24 Applicability -- whether a component is live for THIS employee in THIS period.

    Three gates, cheapest first:
      * lifecycle  -- only an Active component is paid. A Draft or Approved one is
                      configuration somebody is still working on.
      * dates      -- effective_from/to, compared against the period END (a component
                      effective mid-month is earned that month).
      * scope      -- the same specificity match policies use, so "applies to this person"
                      means one thing across the module.
    """
    from app.models.hrms import COMPONENT_PAYABLE_LIFECYCLE
    from app.services.hrms_policy_version_service import specificity

    lifecycle = component.get("lifecycle")
    if lifecycle is not None and lifecycle not in COMPONENT_PAYABLE_LIFECYCLE:
        return False
    # Components predating §24 carry no lifecycle at all; `active` is their switch and
    # must keep working exactly as it did.
    if lifecycle is None and component.get("active") is False:
        return False
    if component.get("effective_from") and component["effective_from"] > period_end:
        return False
    if component.get("effective_to") and component["effective_to"] < period_end:
        return False
    scope = component.get("applicability") or {}
    return not scope or specificity(scope, profile or {}) >= 0


def _due_this_period(component: dict, period: str) -> bool:
    """§24 Frequency. A quarterly or annual component is not earned every month.

    Anchored on the component's own effective_from where it has one, so "quarterly" means
    quarterly FROM WHEN IT STARTED rather than from an arbitrary calendar quarter the
    company never chose. One-time and Ad hoc are never paid automatically: somebody adds
    them to the run as an adjustment, which is what makes them one-time.
    """
    freq = (component.get("frequency") or "Monthly").strip()
    if freq in ("", "Monthly"):
        return True
    if freq in ("One-time", "Ad hoc"):
        return False
    anchor = str(component.get("effective_from") or "")[:7] or period
    try:
        months = ((int(period[:4]) - int(anchor[:4])) * 12
                  + (int(period[5:7]) - int(anchor[5:7])))
    except (ValueError, IndexError):
        return True
    if months < 0:
        return False
    if freq == "Quarterly":
        return months % 3 == 0
    if freq == "Annual":
        return months % 12 == 0
    return True


def _period_dependent(component: dict) -> bool:
    """Does this component's formula read something only a PERIOD can answer?

    A salary structure stores each component's monthly amount, resolved when the structure
    was approved. That is right for almost everything -- a percentage of Basic does not
    change between January and February, and re-deriving it at payroll time would quietly
    bypass the structure approval §9 requires.

    It is wrong for exactly one case: a formula reading PAYABLE_DAYS, LOP_DAYS or an EMP_*
    field. There is no attendance at structure-approval time, so such a formula would have
    been stored as whatever it evaluates to against zeros -- and would stay that number
    for ever, for everybody. Those components, and only those, are re-priced per period.
    """
    from app.services import hrms_formula_engine as FE
    if component.get("calculation_method") != CalculationMethod.FORMULA.value:
        return False
    try:
        refs = FE.references(component.get("formula") or "0")
    except HTTPException:
        return False
    return bool(refs & (FE.ATTENDANCE_VARS | FE.EMPLOYEE_VARS | FE.INPUT_VARS))


def _input_dependent(component: dict) -> bool:
    """Does this component's formula read a payroll input (INPUT_*)?"""
    from app.services import hrms_formula_engine as FE
    if component.get("calculation_method") != CalculationMethod.FORMULA.value:
        return False
    try:
        return bool(FE.references(component.get("formula") or "0") & FE.INPUT_VARS)
    except HTTPException:
        return False


def _reprice_for_period(structure: Optional[dict], meta: dict, days: dict,
                        profile: dict, period_end: str,
                        constants: Optional[dict] = None,
                        inputs: Optional[dict] = None) -> Optional[dict]:
    """The structure with its period-dependent formulas evaluated for THIS period.

    Returns the structure untouched when nothing depends on the period, which is the
    overwhelmingly common case and means this phase changes no existing company's figures.
    """
    components = (structure or {}).get("components") or []
    period_dependent = any(_period_dependent(meta.get(c.get("code")) or {}) for c in components)
    # DEF-01: a structure stores each line's AMOUNT as priced when it was saved. Once a
    # formula / slab / percentage is revised, that amount is stale -- re-price every derived
    # line (dependants included) from the rule in force for this period. A structure whose
    # lines all match their rule is returned untouched, as before.
    stale = any(_priced_by_other_rule(c, component_defaults(meta.get(c.get("code")) or {}))
                for c in components)
    if not period_dependent and not stale:
        return structure
    lines = [{"code": c.get("code"), "amount": c.get("amount") or 0,
              "percentage": c.get("percentage_override") or c.get("percentage")}
             for c in components]
    resolved = resolve_lines(lines, meta, annual_ctc=(structure or {}).get("annual_ctc"),
                             days=days, profile=profile, period_end=period_end,
                             constants=constants, inputs=inputs)
    fresh = {r["code"]: r["amount"] for r in resolved}

    def reprice(c: dict) -> bool:
        m = meta.get(c.get("code")) or {}
        return _period_dependent(m) or (stale and component_defaults(m).get(
            "calculation_method") in _DERIVED_METHODS)
    return {**structure,
            "components": [
                {**c, "amount": fresh.get(c.get("code"), c.get("amount"))}
                if reprice(c) else c
                for c in components]}


_DERIVED_METHODS = {CalculationMethod.FORMULA.value, CalculationMethod.SLAB.value,
                    CalculationMethod.PERCENTAGE.value}


def _priced_by_other_rule(line: dict, m: dict) -> bool:
    """True when a stored structure line was priced by a different rule than `m` (DEF-01):
    another version, another formula text, another slab table, another default %."""
    method = m.get("calculation_method")
    if method not in _DERIVED_METHODS:
        return False
    if line.get("method") and line["method"] != method:
        return True
    if m.get("version") is not None and line.get("component_version") is not None             and line["component_version"] != m["version"]:
        return True
    if method == CalculationMethod.FORMULA.value:
        return (line.get("formula") or "") != (m.get("formula") or "")
    if method == CalculationMethod.SLAB.value:
        return line.get("slabs") is not None and line.get("slabs") != m.get("slabs")
    if line.get("percentage_override") is None and m.get("percentage") is not None:
        return line.get("percentage") is not None and             float(line["percentage"]) != float(m["percentage"])
    return False


def _component_lines(structure: Optional[dict], meta: dict, ratio: float, *,
                     days: Optional[dict] = None, profile: Optional[dict] = None,
                     period: Optional[str] = None,
                     period_end: Optional[str] = None,
                     imported: Optional[dict] = None) -> list:
    """The record's component lines: full monthly amount and what is paid this month.

    The keyword arguments are all optional so every existing caller keeps working; without
    them the function behaves exactly as it did before §24 -- payable-days proration, no
    applicability test, no frequency test.
    """
    days = days or {}
    lines = []
    for c in (structure or {}).get("components", []):
        m = component_defaults(meta.get(c.get("code")) or {})
        ctype = m.get("component_type") or ComponentType.EARNING.value

        if period_end and not _applies_to(m, profile or {}, period_end):
            continue
        if period and not _due_this_period(m, period):
            continue

        full = float(c.get("amount") or 0)
        # §24 Imported Input: this period's figure from the run's imported file, as given --
        # an incentive sheet's number is already the month's amount, so it is not prorated.
        is_imported = m.get("calculation_method") == CalculationMethod.IMPORTED.value
        if is_imported:
            full = float((imported or {}).get(c.get("code"), 0) or 0)
        # §24 Attendance Linked: a rate times a quantity off the frozen attendance basis.
        if m.get("calculation_method") == CalculationMethod.ATTENDANCE_LINKED.value:
            basis_key = str(m.get("attendance_basis") or "payable_days")
            quantity = float(days.get(basis_key) or 0)
            full = round(float(m.get("rate") or c.get("amount") or 0) * quantity, 2)

        share = 1.0 if is_imported else _proration_ratio(m["proration"], days, ratio)
        prorate = not is_imported and (share != 1.0 or m["proration"] in (
            ProrationRule.PAYABLE_DAYS.value, ProrationRule.WORKING_DAYS.value))
        paid = _round(full * share, m["rounding"]) if prorate else full
        lines.append({"code": c.get("code"), "name": m.get("name") or c.get("code"),
                      "component_type": ctype, "section": m["payslip_section"],
                      "full_amount": round(full, 2), "amount": round(paid, 2),
                      "prorated": prorate and round(paid, 2) != round(full, 2),
                      "proration": m["proration"], "frequency": m.get("frequency"),
                      "component_version": m.get("version"),
                      # DEF-01: the rule itself, so a past record shows the formula it was
                      # priced by even after the component has been revised.
                      "method": m.get("calculation_method"),
                      "formula": (m.get("formula") if m.get("calculation_method")
                                  == CalculationMethod.FORMULA.value else None)})
    present = {l["code"] for l in lines}
    for code, amount in (imported or {}).items():
        m = component_defaults(meta.get(code) or {})
        if code in present or m.get("calculation_method") != CalculationMethod.IMPORTED.value:
            continue
        if period_end and not _applies_to(m, profile or {}, period_end):
            continue
        lines.append({"code": code, "name": m.get("name") or code,
                      "component_type": m.get("component_type") or ComponentType.EARNING.value,
                      "section": m["payslip_section"], "full_amount": round(float(amount), 2),
                      "amount": round(float(amount), 2), "prorated": False,
                      "proration": m["proration"], "frequency": m.get("frequency"),
                      "component_version": m.get("version"), "imported": True})
    return lines


async def import_component_inputs(actor: dict, company_id: str, period: str, filename: str,
                                  raw: bytes) -> dict:
    """FRD §24 Imported Input: an incentive sheet, a canteen deduction file. Columns: employee
    code, component code, amount. Only components whose method is Imported Input take a
    value; each file replaces what an earlier file said for the same employee + component.
    The run must be recalculated afterwards (submit_run refuses until it is)."""
    from app.services.hrms_attendance_rules_service import _pick, read_rows
    run = await _get_run(company_id, period)
    _assert_editable(run)
    await _assert_inputs_open(actor, company_id, period)
    if not str(filename or "").lower().endswith((".csv", ".xlsx", ".xlsm")):
        raise HTTPException(status_code=415, detail="Upload the inputs as CSV or Excel (.xlsx).")
    rows = read_rows(filename, raw)
    if len(rows) < 2:
        raise HTTPException(status_code=422, detail="The file has no rows under its header.")
    ci = _pick(rows[0], ("employee code", "employee_code", "emp code", "code"))
    ki = _pick(rows[0], ("component", "component code", "component_code"))
    ai = _pick(rows[0], ("amount", "value"))
    if None in (ci, ki, ai):
        raise HTTPException(status_code=422,
                            detail="Name the columns Employee Code, Component and Amount.")
    await _load_component_types(company_id)
    meta = dict(_component_meta_cache)
    by_upper = {str(k).upper(): k for k in meta}
    known = {p["employee_code"] for p in await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id)}, {"employee_code": 1}).to_list(5000)
        if p.get("employee_code")}
    stored = dict(run.get("imported_inputs") or {})
    accepted, errors = 0, []
    for n, row in enumerate(rows[1:], start=2):
        cell = lambda i: row[i] if i < len(row) else None  # noqa: E731
        code = str(cell(ci) or "").strip()
        comp = str(cell(ki) or "").strip()
        comp = by_upper.get(comp.upper(), comp)
        if not code and not comp:
            continue
        try:
            amount = round(float(cell(ai)), 2)
        except (TypeError, ValueError):
            errors.append({"row": n, "reason": "amount is not a number"})
            continue
        if code not in known:
            errors.append({"row": n, "reason": f"no employee {code}"})
        elif (meta.get(comp) or {}).get("calculation_method") != CalculationMethod.IMPORTED.value:
            errors.append({"row": n, "reason": f"{comp} is not an Imported Input component"})
        elif amount < 0:
            errors.append({"row": n, "reason": "amounts cannot be negative"})
        else:
            stored.setdefault(code, {})[comp] = amount
            accepted += 1
    now = datetime.now(timezone.utc)
    await get_collection(COLL_PAYROLL_RUNS).update_one(
        {"_id": run["_id"]}, {"$set": {"imported_inputs": stored, "imported_inputs_at": now,
                                       "imported_inputs_file": filename, "updated_at": now}})
    await audit(actor, AUDIT_PAYROLL_ADJUSTMENTS_SET, ENTITY_PAYROLL_RUN, period,
                f"imported inputs {filename}: {accepted} accepted, {len(errors)} refused",
                company_id)
    return {"accepted": accepted, "errors": errors,
            "recalculate": run.get("status") != PayrollRunStatus.DRAFT.value}


async def _employee_policy(company_id: str, run_policy: dict, profile: dict,
                           on_date: str) -> dict:
    """`run_policy` with this employee's EMPLOYEE-LEVEL keys resolved for them.

    A PAY_POLICY version can be scoped by grade, location, category or payroll group, and
    `get_payroll_policy` has always accepted a `profile` to resolve it against -- which
    every caller passed as None. A version aimed at Grade M1 therefore applied to nobody,
    and the scope UI offered a filter that changed no figure anywhere.

    The run-level keys are laid back over the result deliberately, AFTER resolution. It
    would be cheaper to resolve only the employee-level ones, but then a scoped version
    setting `checker_required: false` would depend on nobody noticing. This way a scope
    cannot reach a run-level decision even if someone writes one that tries.
    """
    from app.models.hrms import PAYROLL_POLICY_RUN_LEVEL_KEYS
    resolved = await get_payroll_policy(company_id, profile=profile, on_date=on_date)
    return {**resolved,
            **{k: v for k, v in run_policy.items() if k in PAYROLL_POLICY_RUN_LEVEL_KEYS}}


async def calculate_payroll(actor: dict, company_id: str, period: str) -> dict:
    """FRD §12 stages 3-6: load eligible employees, the locked attendance basis, active
    structures and monthly inputs, then calculate. Safe to rerun while the maker holds the
    run: hand-entered inputs (statutory figures, arrears, manual adjustments) are CARRIED
    OVER into the rebuilt records instead of being wiped."""
    run = await _get_run(company_id, period)
    _assert_editable(run)
    _y, _m, _days, start, end = _period_bounds(period)
    # §21: the policy as at the END OF THIS PERIOD, not as at today. A February run must
    # read February's cut-off and rounding even if HR revised them in March.
    policy = await get_payroll_policy(company_id, on_date=end)

    # FRD §18: payroll uses the LOCKED attendance snapshot, never live editable attendance.
    lock = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
        {"company_id": str(company_id), "period": period})
    attendance_locked = (lock or {}).get("status") == "Locked"
    # The identity of the lock this run consumed. `locked_at` is the version marker: HR
    # unlocking and re-locking produces a NEW stamp on the same row, which is what lets
    # submit_run below notice that the basis moved under a calculated run.
    attendance_basis_ref = {
        "locked": attendance_locked,
        "lock_id": str((lock or {}).get("_id") or "") or None,
        "locked_at": (lock or {}).get("locked_at"),
        "locked_by": (lock or {}).get("locked_by"),
        "locked_by_name": (lock or {}).get("locked_by_name"),
    }
    if policy.get("require_attendance_lock") and not attendance_locked:
        raise HTTPException(
            status_code=409,
            detail=f"Attendance for {period} is not locked. HR locks the month (Attendance > "
                   f"Monthly Closure) before payroll is calculated (FRD §12 stage 2).")

    await _load_component_types(company_id)
    # DEF-01: each component as it stood for THIS period, so re-running an earlier month
    # after a revision still uses -- and stamps on each line -- the version then in force.
    meta = {code: component_on(m, end) for code, m in _component_meta_cache.items()}
    # §25 constants, read once for the whole run rather than per employee.
    run_constants = await constants_for(company_id)
    profiles = await _eligible_profiles(company_id, start, end,
                                        policy.get("excluded_employee_categories"))

    records_coll = get_collection(COLL_PAYROLL_RECORDS)
    previous_inputs = {r["employee_code"]: r for r in await records_coll.find(
        {"company_id": str(company_id), "period": period}).to_list(5000)}
    previous_period = _previous_period(period)
    previous_net = {r["employee_code"]: r.get("net_pay") for r in await records_coll.find(
        {"company_id": str(company_id), "period": previous_period}).to_list(5000)}
    carry = await get_collection(COLL_PAYROLL_CARRY_FORWARD).find(
        {"company_id": str(company_id), "target_period": period,
         "status": {"$in": ["Pending", "Included"]}}).to_list(2000)
    carry_by_code: dict = {}
    for c in carry:
        carry_by_code.setdefault(c["employee_code"], []).append(c)

    now = datetime.now(timezone.utc)
    await records_coll.delete_many({"company_id": str(company_id), "period": period})
    names = await _employee_names(profiles)
    threshold = float(policy.get("variance_threshold_percent") or 0)

    from app.services.hrms_shift_service import month_calendar
    for profile in profiles:
        employee_code = profile["employee_code"]
        # §26 scoping: the rules that decide THIS person's amounts, resolved for them.
        emp_policy = await _employee_policy(company_id, policy, profile, end)
        calendar = await month_calendar(company_id, profile, period)
        structure = await get_current_structure(company_id, employee_code, end)
        days = await _payable_days(company_id, employee_code, period, profile, calendar,
                                   sandwich=bool(emp_policy.get("sandwich_weekly_off")))
        ratio = (days["payable_days"] / days["days_in_period"]) if days["days_in_period"] else 0

        # Auto roll-up: open salary-advance recovery for this employee (§7.13 step 93).
        advance = await get_collection(COLL_SALARY_ADVANCES).find_one({
            "company_id": str(company_id), "employee_code": employee_code,
            "status": AdvanceStatus.RECOVERING.value,
        })
        advance_recovery = 0.0
        if advance:
            outstanding = float(advance["amount"]) - float(advance.get("recovered_amount") or 0)
            advance_recovery = round(max(0.0, min(outstanding, float(advance["amount"]))), 2)

        # Auto roll-up: approved, not-yet-paid variable pay for this employee.
        vp_record = await get_collection(COLL_VARIABLE_PAY_RECORDS).find_one({
            "company_id": str(company_id), "employee_code": employee_code,
            "status": "Approved", "paid_in_period": None,
        })
        variable_pay_payout = float(vp_record["payable_portion"]) if vp_record else 0.0

        prior = previous_inputs.get(employee_code) or {}
        manual = {f: (prior.get(f) if prior.get(f) is not None else (None if f == "remarks" else 0))
                  for f in MANUAL_FIELDS}

        # Worked out BEFORE the structure is priced so an INPUT_* formula (§25 "payroll
        # inputs") reads this period's figures.
        structure = _reprice_for_period(
            structure, meta, days, profile, end, constants=run_constants,
            inputs={**manual, "advance_recovery": advance_recovery,
                    "variable_pay_payout": variable_pay_payout})
        lines = _component_lines(structure, meta, ratio, days=days, profile=profile,
                                 period=period, period_end=end,
                                 imported=(run.get("imported_inputs") or {}).get(employee_code))

        gross_structured = round(sum(l["full_amount"] for l in lines
                                     if l["component_type"] == ComponentType.EARNING.value), 2)
        prorated_gross = round(sum(l["amount"] for l in lines
                                   if l["component_type"] == ComponentType.EARNING.value), 2)
        # Nothing earned, nothing deducted: with no paid days a fixed deduction (e.g. PT)
        # would make net pay negative.
        if prorated_gross <= 0:
            for l in lines:
                if l["component_type"] in DEDUCTING_TYPES | {
                        ComponentType.REIMBURSEMENT.value,
                        ComponentType.EMPLOYER_CONTRIBUTION.value}:
                    l["amount"] = 0.0
        structured_deductions = round(sum(l["amount"] for l in lines
                                          if l["component_type"] in DEDUCTING_TYPES), 2)
        structured_reimbursements = round(sum(
            l["amount"] for l in lines
            if l["component_type"] == ComponentType.REIMBURSEMENT.value), 2)
        employer = round(sum(l["amount"] for l in lines
                             if l["component_type"] == ComponentType.EMPLOYER_CONTRIBUTION.value), 2)

        adjustments =[a for a in (prior.get("adjustments") or []) if not a.get("carry_forward_id")]
        for c in carry_by_code.get(employee_code, []):
            adjustments.append({
                "code": c["adjustment_type"].upper(), "name": f"{c['adjustment_type']} "
                f"({c['source_period']})",
                "component_type": (ComponentType.EARNING.value if c["adjustment_type"] == "Arrear"
                                   else ComponentType.RECOVERY.value),
                "amount": round(abs(float(c["amount"])), 2), "reason": c.get("reason"),
                "reference": f"Post-lock adjustment of {c['source_period']}",
                "carry_forward_id": str(c["_id"]),
            })

        doc = {
            "company_id": str(company_id), "period": period, "employee_code": employee_code,
            "employee_name": _name_of(profile, names),
            "date_of_joining": profile.get("joined_on"),
            "last_working_day": profile.get("resigned_on"),
            "payroll_group": profile.get("payroll_group"),
            "department_id": profile.get("department_id"),
            "work_location": profile.get("work_location"),
            **days,
            "calendar_days": days["days_in_period"],
            "structure_id": (structure or {}).get("id"),
            "structure_effective_from": (structure or {}).get("effective_from"),
            "lines": lines,
            "structured_gross": gross_structured, "prorated_gross": prorated_gross,
            "structured_deductions": structured_deductions,
            "structured_reimbursements": structured_reimbursements,
            "employer_contributions": employer,
            "advance_recovery": advance_recovery, "variable_pay_payout": variable_pay_payout,
            "vp_record_id": str(vp_record["_id"]) if vp_record else None,
            "advance_id": str(advance["_id"]) if advance else None,
            **manual,
            "adjustments": adjustments,
            "previous_period": previous_period,
            "previous_net": previous_net.get(employee_code),
            "attendance_locked": attendance_locked,
            # §30 — the version that decided THIS person's amounts, which under a scoped
            # policy is not the company-wide one stamped on the run.
            "payroll_policy_version": await _policy_version_ref(company_id, end, profile),
            "created_at": now, "updated_at": now,
        }
        doc.update(_totals(doc))
        doc.update(_net_rounding(doc, emp_policy.get("net_rounding")))
        doc.update(_exceptions(doc, profile, structure, threshold, attendance_locked))
        await records_coll.insert_one(doc)
        for c in carry_by_code.get(employee_code, []):
            await get_collection(COLL_PAYROLL_CARRY_FORWARD).update_one(
                {"_id": c["_id"]}, {"$set": {"status": "Included", "updated_at": now}})

    totals = await _run_totals(company_id, period)
    await get_collection(COLL_PAYROLL_RUNS).update_one(
        {"_id": run["_id"]},
        {"$set": {"status": PayrollRunStatus.CALCULATED.value, "eligible_count": len(profiles),
                  "calculated_at": now, "updated_at": now, "totals": totals,
                  "attendance_basis": attendance_basis_ref,
                  # §30: enough rule references to reproduce this run later.
                  "payroll_policy_version": (await _policy_version_ref(company_id, end))},
         "$push": {"approval_trail": _trail(actor, "Maker", "Calculated",
                                            f"{len(profiles)} employee(s)")}},
    )
    await audit(actor, AUDIT_PAYROLL_CALCULATED, ENTITY_PAYROLL_RUN, period,
               f"{len(profiles)} employee(s)", company_id)
    return await get_run(actor, company_id, period)


def _variance(record: dict) -> dict:
    prev = record.get("previous_net")
    if prev is None:
        return {"variance_amount": None, "variance_percent": None}
    amount = round(float(record["net_pay"]) - float(prev), 2)
    pct = round(amount / float(prev) * 100, 2) if prev else None
    return {"variance_amount": amount, "variance_percent": pct}


def _exceptions(record: dict, profile: dict, structure: Optional[dict], threshold: float,
                attendance_locked: bool) -> dict:
    """FRD §10 Controls / §25 Failure handling: CRITICAL exceptions block submission."""
    items = []

    def add(code, severity, message):
        items.append({"code": code, "severity": severity, "message": message})

    if not structure:
        add("NO_STRUCTURE", "critical", "No approved salary structure on file — gross earnings are 0.")
    if record["net_pay"] < 0:
        add("NEGATIVE_NET", "critical", "Net pay is negative — deductions exceed earnings.")
    if record["payable_days"] <= 0 and record.get("out_of_service_days", 0) < record["days_in_period"]:
        add("ZERO_PAYABLE", "warning", "No payable days this month.")
    if record.get("unrecorded_days"):
        add("UNRECORDED_DAYS", "warning",
            f"{record['unrecorded_days']} working day(s) have no attendance and were treated as LOP.")
    if record.get("sandwiched_off_days"):
        add("SANDWICH", "warning",
            f"{record['sandwiched_off_days']} weekly off / holiday day(s) fell between LOP days "
            f"and were treated as LOP (sandwich rule).")
    if record.get("pending_days"):
        add("PENDING_ATTENDANCE", "warning",
            f"{record['pending_days']} day(s) still Pending in attendance (treated as LOP).")
    if record["net_pay"] > 0 and not (profile.get("bank_account") and profile.get("bank_ifsc")):
        add("NO_BANK", "warning", "Bank account / IFSC missing — cannot be included in the bank file.")
    if not attendance_locked:
        add("ATTENDANCE_OPEN", "warning", "Attendance for this month is not locked.")
    variance = _variance(record)
    if variance["variance_percent"] is not None and threshold and \
            abs(variance["variance_percent"]) > threshold:
        add("VARIANCE", "warning",
            f"Net pay moved {variance['variance_percent']}% against last month "
            f"(threshold {threshold}%).")
    return {**variance, "exception_details": items,
            "exceptions": [i["message"] for i in items],
            "critical_exceptions": sum(1 for i in items if i["severity"] == "critical")}


def _adjustment_sum(record: dict, types) -> float:
    if isinstance(types, str):
        types = {types}
    return sum(float(a.get("amount") or 0) for a in (record.get("adjustments") or [])
               if a.get("component_type") in types)


def _totals(record: dict) -> dict:
    """FRD §11: regular earnings + additional earnings + reimbursements + arrears
    - LOP impact (already in the prorated lines) - statutory deductions - recoveries."""
    gross = (float(record["prorated_gross"]) + float(record.get("structured_reimbursements") or 0)
             + float(record.get("variable_pay_payout") or 0) + float(record.get("arrears") or 0)
             + float(record.get("reimbursements") or 0) + float(record.get("other_earnings") or 0)
             + float(record.get("bonus") or 0)
             + _adjustment_sum(record, EARNING_TYPES))
    # `.get`: records calculated before structure deductions were counted have no such key.
    deductions = (float(record.get("structured_deductions") or 0)
                  + float(record.get("pf") or 0) + float(record.get("esi") or 0)
                  + float(record.get("pt") or 0) + float(record.get("tds") or 0)
                  + float(record.get("advance_recovery") or 0)
                  + float(record.get("notice_recovery") or 0)
                  + float(record.get("other_deductions") or 0)
                  + _adjustment_sum(record, DEDUCTING_TYPES))
    employer = (float(record.get("employer_contributions") or 0)
                + _adjustment_sum(record, ComponentType.EMPLOYER_CONTRIBUTION.value))
    return {"gross_earnings": round(gross, 2), "total_deductions": round(deductions, 2),
            "net_pay": round(gross - deductions, 2),
            "total_employer_contributions": round(employer, 2),
            "cost_to_company": round(gross + employer, 2)}


def _net_rounding(record: dict, rule: Optional[str]) -> dict:
    """Payroll policy net rounding (FRD §24 Rounding). The difference is kept on the record
    so gross - deductions + rounding always equals what is paid."""
    raw = float(record["net_pay"])
    rounded = _round(raw, rule) if (rule or "None") != "None" else raw
    return {"net_pay": round(rounded, 2), "net_rounding_adjustment": round(rounded - raw, 2)}


async def _run_totals(company_id: str, period: str) -> dict:
    rows = await get_collection(COLL_PAYROLL_RECORDS).find(
        {"company_id": str(company_id), "period": period}).to_list(5000)
    return {
        "headcount": len(rows),
        "gross": round(sum(r.get("gross_earnings") or 0 for r in rows), 2),
        "deductions": round(sum(r.get("total_deductions") or 0 for r in rows), 2),
        "employer_contributions": round(sum(r.get("total_employer_contributions") or 0
                                            for r in rows), 2),
        "net": round(sum(r.get("net_pay") or 0 for r in rows), 2),
        "previous_net": round(sum(r.get("previous_net") or 0 for r in rows), 2),
        "exceptions": sum(len(r.get("exception_details") or []) for r in rows),
        "critical_exceptions": sum(r.get("critical_exceptions") or 0 for r in rows),
        "lop_days": round(sum(r.get("lop_days") or 0 for r in rows), 2),
    }


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": str(actor.get("_id") or "")})
    return (profile or {}).get("employee_code")


async def list_records(actor: dict, company_id: str, period: str) -> list:
    """Payroll roles see the run's whole population; everyone else only their own record,
    and only once it is released (FRD §14 Release)."""
    query = {"company_id": str(company_id), "period": period}
    from app.utils.hrms_access import sees_all_payroll
    if not sees_all_payroll(actor):
        own = await _own_employee_code(actor, company_id)
        query["employee_code"] = own or "__none__"
        run = await get_collection(COLL_PAYROLL_RUNS).find_one(
            {"company_id": str(company_id), "period": period}, {"status": 1})
        if (run or {}).get("status") not in PAYROLL_FINAL_STATUSES:
            return []
    rows = await get_collection(COLL_PAYROLL_RECORDS).find(query
    ).sort("employee_code", 1).to_list(5000)
    return [_out(r) for r in rows]


async def _refresh_record(record: dict, company_id: str) -> dict:
    # The profile is loaded anyway for _exceptions, so resolving the policy FOR this
    # employee costs nothing and stops a hand-entered input being re-rounded under a
    # different rule from the one that calculated the record.
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": record["employee_code"]}) or {}
    period = record.get("period")
    on_date = _period_bounds(period)[4] if period else None   # the period's last day
    policy = await get_payroll_policy(company_id, profile=profile, on_date=on_date)
    record.update(_totals(record))
    record.update(_net_rounding(record, policy.get("net_rounding")))
    structure = {"id": record.get("structure_id")} if record.get("structure_id") or \
        record.get("lines") else None
    record.update(_exceptions(record, profile, structure,
                              float(policy.get("variance_threshold_percent") or 0),
                              bool(record.get("attendance_locked", True))))
    return record


async def adjust_record(actor: dict, company_id: str, period: str, employee_code: str,
                        payload: dict) -> dict:
    """The maker's monthly inputs (FRD §10): statutory figures, reimbursements, arrears,
    bonus, other earnings / recoveries -- entered here while the run is with the maker."""
    run = await _get_run(company_id, period)
    _assert_editable(run)
    await _assert_inputs_open(actor, company_id, period)
    record = await get_collection(COLL_PAYROLL_RECORDS).find_one(
        {"company_id": str(company_id), "period": period, "employee_code": employee_code})
    if not record:
        raise HTTPException(status_code=404, detail="No payroll record for that employee in this run.")

    clean = {}
    for k, v in payload.items():
        if k == "remarks" or v is None:
            continue
        try:
            clean[k] = round(float(v), 2)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{k} must be a number.")
        if clean[k] < 0:
            raise HTTPException(status_code=422, detail=f"{k} cannot be negative.")
    if "remarks" in payload and payload["remarks"] is not None:
        clean["remarks"] = payload["remarks"]
    merged = {**record, **clean}
    # §25 payroll-input variables: a formula reading an input was priced with the value the
    # input had when the run calculated. Changing it leaves that line behind until the run
    # is recalculated, and submit_run refuses until it is.
    from app.services import hrms_formula_engine as FE
    if set(clean) & set(FE.INPUT_FIELDS.values()):
        await _load_component_types(company_id)
        if any(_input_dependent(_component_meta_cache.get(l.get("code")) or {})
               for l in record.get("lines") or []):
            merged["inputs_changed_after_calculation"] = True
    merged = await _refresh_record(merged, company_id)
    merged["updated_at"] = datetime.now(timezone.utc)
    merged["updated_by"] = _actor_id(actor)
    await get_collection(COLL_PAYROLL_RECORDS).update_one(
        {"_id": record["_id"]}, {"$set": {k: v for k, v in merged.items() if k != "_id"}})
    await _store_run_totals(company_id, period)
    await audit(actor, AUDIT_PAYROLL_RECORD_ADJUSTED, ENTITY_PAYROLL_RUN, f"{period}:{employee_code}",
               ", ".join(sorted(clean)), company_id)
    saved = await get_collection(COLL_PAYROLL_RECORDS).find_one({"_id": record["_id"]})
    return _out(saved)


async def set_adjustments(actor: dict, company_id: str, period: str, employee_code: str,
                          payload: dict) -> dict:
    """FRD §10 Manual Adjustment: type (from the component), amount, reason and source
    reference, against the same component master the salary structure uses. Lines carried
    in from a post-lock adjustment are kept -- the maker cannot drop an approved arrear."""
    run = await _get_run(company_id, period)
    _assert_editable(run)
    await _assert_inputs_open(actor, company_id, period)
    record = await get_collection(COLL_PAYROLL_RECORDS).find_one(
        {"company_id": str(company_id), "period": period, "employee_code": employee_code})
    if not record:
        raise HTTPException(status_code=404, detail="No payroll record for that employee in this run.")

    known = {c["code"]: c for c in await list_salary_components(actor, company_id)}
    resolved = [a for a in (record.get("adjustments") or []) if a.get("carry_forward_id")]
    for item in payload.get("adjustments") or []:
        item = item if isinstance(item, dict) else item.model_dump()
        code = str(item.get("code") or "").strip()
        meta = known.get(code)
        if not meta:
            raise HTTPException(status_code=422, detail=f"Unknown salary component '{code}'.")
        if not meta.get("active", True):
            raise HTTPException(status_code=422, detail=f"{code} is retired.")
        amount = round(float(item.get("amount") or 0), 2)
        if amount < 0:
            raise HTTPException(status_code=422, detail="Adjustment amounts cannot be negative; "
                                                        "use a deduction / recovery component.")
        resolved.append({"code": code, "name": meta.get("name"),
                         "component_type": meta.get("component_type"),
                         "section": meta.get("payslip_section"),
                         "amount": amount,
                         "reason": (item.get("reason") or "").strip() or None,
                         "reference": (item.get("reference") or "").strip() or None,
                         "entered_by": _actor_id(actor)})

    # §10 "approval where needed": a line above the policy's amount waits for a second
    # person. A line re-posted unchanged keeps the approval it already has.
    limit = (await get_payroll_policy(company_id, on_date=_period_bounds(period)[4])).get(
        "adjustment_approval_above")
    approved = {_adjustment_key(a): a for a in record.get("adjustments") or []
                if a.get("approval_status") == ADJ_APPROVED}
    for a in resolved:
        if a.get("carry_forward_id") or limit is None or a["amount"] <= float(limit):
            continue
        kept = approved.get(_adjustment_key(a))
        a.update({k: kept.get(k) for k in ("approval_status", "approved_by",
                                           "approved_by_name", "approved_at")}
                 if kept else {"approval_status": ADJ_PENDING})

    merged = {**record, "adjustments": resolved}
    merged = await _refresh_record(merged, company_id)
    merged["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_PAYROLL_RECORDS).update_one(
        {"_id": record["_id"]}, {"$set": {k: v for k, v in merged.items() if k != "_id"}})
    await _store_run_totals(company_id, period)
    await audit(actor, AUDIT_PAYROLL_ADJUSTMENTS_SET, ENTITY_PAYROLL_RUN,
               f"{period}:{employee_code}", f"{len(resolved)} line(s)", company_id)
    saved = await get_collection(COLL_PAYROLL_RECORDS).find_one({"_id": record["_id"]})
    return _out(saved)


async def _store_run_totals(company_id: str, period: str) -> None:
    await get_collection(COLL_PAYROLL_RUNS).update_one(
        {"company_id": str(company_id), "period": period},
        {"$set": {"totals": await _run_totals(company_id, period),
                  "updated_at": datetime.now(timezone.utc)}})


async def attendance_basis_moved(company_id: str, period: str, run: dict) -> Optional[str]:
    """Has the attendance lock changed since this run was calculated? The reason, or None.

    FRD §18 requires payroll to rest on the LOCKED attendance snapshot. The lock gate at
    calculate time is only half of that promise: HR can unlock a month afterwards, correct
    a day and leave a calculated run quietly resting on figures that no longer match the
    attendance it claims to come from. Comparing the stored lock identity against the
    current one is what closes it.

    Returns a sentence for the operator rather than a bool, because WHICH way it moved
    (unlocked, re-locked, or locked for a different reason) is what tells them what to do.
    """
    basis = run.get("attendance_basis") or {}
    if not basis.get("locked"):
        return None            # never claimed a locked basis; the calculate gate owns this
    lock = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
        {"company_id": str(company_id), "period": period})
    if not lock or lock.get("status") != "Locked":
        return (f"Attendance for {period} has been unlocked since this payroll was "
                f"calculated, so the figures no longer rest on a locked month.")
    if basis.get("lock_id") and str(lock.get("_id")) != basis["lock_id"]:
        return (f"Attendance for {period} was re-locked after this payroll was calculated.")
    if basis.get("locked_at") and lock.get("locked_at") != basis["locked_at"]:
        return (f"Attendance for {period} was unlocked and locked again after this payroll "
                f"was calculated, so a day may have changed.")
    return None


async def submit_run(actor: dict, company_id: str, period: str, payload: dict) -> dict:
    """FRD §12 stage 7: the maker submits the batch for approval. Critical exceptions block
    it (§25 Failure handling: payroll cannot be approved while critical errors remain), and
    so does an attendance basis that has moved since the run was calculated (§18)."""
    run = await _get_run(company_id, period)
    moved = await attendance_basis_moved(company_id, period, run)
    if moved:
        raise HTTPException(status_code=409,
                            detail=f"{moved} Recalculate {period} before submitting it.")
    if run.get("imported_inputs_at") and run.get("calculated_at") and \
            run["imported_inputs_at"] > run["calculated_at"]:
        raise HTTPException(status_code=409,
                            detail=f"Imported inputs arrived after {period} was calculated. "
                                   f"Recalculate it before submitting.")
    behind = await get_collection(COLL_PAYROLL_RECORDS).count_documents(
        {"company_id": str(company_id), "period": period,
         "inputs_changed_after_calculation": True})
    if behind:
        raise HTTPException(status_code=409,
                            detail=f"{behind} employee(s) had a payroll input changed that a "
                                   f"formula uses. Recalculate {period} before submitting it.")
    waiting = sum(
        1 for r in await get_collection(COLL_PAYROLL_RECORDS).find(
            {"company_id": str(company_id), "period": period}, {"adjustments": 1}).to_list(5000)
        for a in r.get("adjustments") or [] if a.get("approval_status") == ADJ_PENDING)
    if waiting:
        raise HTTPException(status_code=409,
                            detail=f"{waiting} one-off line(s) above the approval amount are "
                                   f"waiting for a second person's approval.")
    if run["status"] not in (PayrollRunStatus.CALCULATED.value, PayrollRunStatus.RETURNED.value,
                             PayrollRunStatus.REJECTED.value):
        raise HTTPException(status_code=409,
                            detail=f"{period} must be calculated before it is submitted "
                                   f"(currently \"{run['status']}\").")
    if run["status"] != PayrollRunStatus.CALCULATED.value:
        raise HTTPException(status_code=409,
                            detail="A returned or rejected payroll is recalculated before it "
                                   "is submitted again.")
    # A run calculated before the locked-attendance basis, component lines and exception
    # checks existed carries none of them; it is recalculated before anyone checks it.
    if not run.get("totals"):
        raise HTTPException(status_code=409,
                            detail=f"Recalculate the {period} payroll before submitting it — it "
                                   f"was calculated before the current payroll rules.")
    totals = await _run_totals(company_id, period)
    if totals["critical_exceptions"]:
        raise HTTPException(
            status_code=409,
            detail=f"{totals['critical_exceptions']} critical exception(s) remain — fix them "
                   f"and recalculate before submitting.")
    now = datetime.now(timezone.utc)
    await get_collection(COLL_PAYROLL_RUNS).update_one(
        {"_id": run["_id"]},
        {"$set": {"status": PayrollRunStatus.SUBMITTED.value, "submitted_by": _actor_id(actor),
                  "submitted_by_name": _actor_name(actor), "submitted_at": now,
                  "totals": totals, "updated_at": now,
                  # P1-095: a resubmitted run starts the configured chain again.
                  "approval_stage": 0, "stage_approvers": []},
         "$push": {"approval_trail": _trail(actor, "Maker", "Submitted for approval",
                                            payload.get("remarks"))}})
    await audit(actor, AUDIT_PAYROLL_SUBMITTED, ENTITY_PAYROLL_RUN, period, None, company_id)
    return await get_run(actor, company_id, period)


def _decision_action(payload: dict, allowed: dict, *, verb: str) -> tuple:
    """The action and the status it moves the run to. Shared by stages 8 and 9 so the two
    read identically to an operator: pass it on silently, say why when sending it back."""
    action = str(payload.get("action") or "").lower()
    if not action:
        action = verb if payload.get("approved") else "reject"
    if action not in allowed:
        raise HTTPException(status_code=422,
                            detail=f"Action must be {', '.join(sorted(allowed))}.")
    if action != verb and not (payload.get("remarks") or "").strip():
        raise HTTPException(status_code=422, detail="Say why the payroll is being sent back.")
    return action, allowed[action]


async def check_run(actor: dict, company_id: str, period: str, payload: dict) -> dict:
    """FRD §12 stage 8: the Payroll/HR Checker VERIFIES component values, attendance impact
    and exceptions, then passes the run to the stage-9 approver -- or returns/rejects it.

    Never the maker who submitted it. That is the maker-checker rule §18 calls mandatory,
    and it is enforced on the ACTOR, not the role: HR holds both PAYROLL_PROCESS and
    PAYROLL_CHECK (§12 names the checker "Payroll/HR Checker"), so a role-level test would
    let a single HR user wave their own run through."""
    chain = approval_chain(await get_payroll_policy(company_id))
    if chain:
        return await act_on_stage(actor, company_id, period, payload, chain=chain)
    run = await _get_run(company_id, period)
    if run["status"] != PayrollRunStatus.SUBMITTED.value:
        raise HTTPException(
            status_code=409,
            detail=f"{period} must be Submitted by the maker before it is checked "
                   f"(currently \"{run['status']}\").")
    if run.get("submitted_by") and run["submitted_by"] == _actor_id(actor):
        raise HTTPException(status_code=403,
                            detail="Maker-checker: you submitted this payroll, so someone else "
                                   "must check it.")
    action, new_status = _decision_action(
        payload,
        {"check": PayrollRunStatus.CHECKED.value,
         "reject": PayrollRunStatus.REJECTED.value,
         "return": PayrollRunStatus.RETURNED.value},
        verb="check")
    now = datetime.now(timezone.utc)
    await get_collection(COLL_PAYROLL_RUNS).update_one(
        {"_id": run["_id"]},
        {"$set": {"status": new_status, "checked_by": _actor_id(actor),
                  "checked_by_name": _actor_name(actor), "checked_at": now,
                  "check_remarks": payload.get("remarks"), "updated_at": now},
         "$push": {"approval_trail": _trail(actor, "Checker", new_status,
                                            payload.get("remarks"))}})
    await audit(actor, AUDIT_PAYROLL_CHECKED, ENTITY_PAYROLL_RUN, period, new_status, company_id)
    return await get_run(actor, company_id, period)


async def decide_run(actor: dict, company_id: str, period: str, payload: dict) -> dict:
    """FRD §12 stage 9: Finance / the Authorised Approver approves, rejects or returns.

    Which run states are acceptable here depends on the company's approval matrix:
      * checker_required=True  (the default) -- only a CHECKED run, so stage 8 cannot be
        skipped;
      * checker_required=False              -- a SUBMITTED run too, which is the pre-FRD
        two-stage shape, kept so a company that has not configured a checker is unaffected.

    The approver is never the maker, and -- when the matrix says so -- never the checker
    either. §19 leaves the exact approvers unconfirmed, which is why this is policy and
    not code."""
    policy = await get_payroll_policy(company_id)
    chain = approval_chain(policy)
    if chain:
        return await act_on_stage(actor, company_id, period, payload, chain=chain)
    run = await _get_run(company_id, period)
    checker_required = bool(policy.get("checker_required", True))

    acceptable = ([PayrollRunStatus.CHECKED.value] if checker_required
                  else [PayrollRunStatus.CHECKED.value, PayrollRunStatus.SUBMITTED.value])
    if run["status"] not in acceptable:
        expected = "Checked by the checker" if checker_required else "Submitted or Checked"
        raise HTTPException(
            status_code=409,
            detail=f"{period} must be {expected} before a decision "
                   f"(currently \"{run['status']}\").")
    if run.get("submitted_by") and run["submitted_by"] == _actor_id(actor):
        raise HTTPException(status_code=403,
                            detail="Maker-checker: you submitted this payroll, so someone else "
                                   "must approve it.")
    if (policy.get("approver_distinct_from_checker", True)
            and run.get("checked_by") and run["checked_by"] == _actor_id(actor)):
        raise HTTPException(status_code=403,
                            detail="You checked this payroll, so the approval is someone "
                                   "else's to give (FRD §12 stages 8 and 9).")
    action, new_status = _decision_action(
        payload,
        {"approve": PayrollRunStatus.APPROVED.value,
         "reject": PayrollRunStatus.REJECTED.value,
         "return": PayrollRunStatus.RETURNED.value},
        verb="approve")
    now = datetime.now(timezone.utc)
    await get_collection(COLL_PAYROLL_RUNS).update_one(
        {"_id": run["_id"]},
        {"$set": {"status": new_status, "decided_by": _actor_id(actor),
                  "decided_by_name": _actor_name(actor), "decided_at": now,
                  "decision_remarks": payload.get("remarks"), "updated_at": now},
         "$push": {"approval_trail": _trail(actor, "Approver", new_status,
                                            payload.get("remarks"))}})
    await audit(actor, AUDIT_PAYROLL_DECIDED, ENTITY_PAYROLL_RUN, period, new_status, company_id)
    return await get_run(actor, company_id, period)


def _stage_index(run: dict, chain: list) -> Optional[int]:
    """Which configured stage a run is waiting on, or None when it is not awaiting one."""
    if run.get("status") == PayrollRunStatus.SUBMITTED.value:
        return 0
    if run.get("status") == PayrollRunStatus.CHECKED.value:
        # A run checked under the default matrix before a chain was configured has passed
        # one stage, which is what the default's Checker stage is.
        idx = int(run.get("approval_stage") or 1)
        return idx if idx < len(chain) else None
    return None


def _may_act_on_stage(actor: dict, stage: dict) -> bool:
    from app.models.hrms import Cap
    from app.utils.hrms_access import can, hrms_role
    try:
        if not can(actor, Cap(stage["cap"])):
            return False
    except ValueError:
        return False
    roles = stage.get("roles") or []
    if not roles:
        return True
    role = hrms_role(actor)
    # No HRMS role at all is the Sparsh superuser, who `can()` already treats as such.
    return role is None or getattr(role, "value", role) in roles


async def act_on_stage(actor: dict, company_id: str, period: str, payload: dict, *,
                       chain: Optional[list] = None) -> dict:
    """P1-095: pass, return or reject the stage a run is waiting on, under the company's
    CONFIGURED approval chain.

    Statuses stay the ones every other screen and step already reads: Submitted until the
    first stage passes, Checked between stages, Approved once the last stage passes (and
    then Lock, unchanged). Two rules are never configurable: the maker cannot act on any
    stage of their own run, and one person cannot pass two stages of the same run."""
    chain = chain or approval_chain(await get_payroll_policy(company_id))
    if not chain:
        raise HTTPException(status_code=409,
                            detail="This company uses the standard check-then-approve steps.")
    run = await _get_run(company_id, period)
    idx = _stage_index(run, chain)
    if idx is None:
        raise HTTPException(
            status_code=409,
            detail=f"{period} is not waiting for an approval (currently \"{run['status']}\").")
    stage = chain[idx]
    if not _may_act_on_stage(actor, stage):
        raise HTTPException(status_code=403,
                            detail=f"The {stage['name']} stage is not yours to act on.")
    me = _actor_id(actor)
    if run.get("submitted_by") and run["submitted_by"] == me:
        raise HTTPException(status_code=403,
                            detail="Maker-checker: you submitted this payroll, so someone else "
                                   "must approve it.")
    if me in (run.get("stage_approvers") or []) or (
            idx and not run.get("stage_approvers") and run.get("checked_by") == me):
        raise HTTPException(status_code=403,
                            detail="You already approved an earlier stage of this payroll, so "
                                   "this stage is someone else's to give.")
    final = idx == len(chain) - 1
    passed = PayrollRunStatus.APPROVED.value if final else PayrollRunStatus.CHECKED.value
    action = str(payload.get("action") or "").lower()
    if action == "check":
        action = "approve"
    action, new_status = _decision_action(
        {**payload, "action": action},
        {"approve": passed, "reject": PayrollRunStatus.REJECTED.value,
         "return": PayrollRunStatus.RETURNED.value},
        verb="approve")
    now = datetime.now(timezone.utc)
    fields = {"status": new_status, "updated_at": now}
    if action == "approve":
        fields.update({"approval_stage": idx + 1,
                       "stage_approvers": list(run.get("stage_approvers") or []) + [me]})
        if final:
            fields.update({"decided_by": me, "decided_by_name": _actor_name(actor),
                           "decided_at": now, "decision_remarks": payload.get("remarks")})
        else:
            fields.update({"checked_by": me, "checked_by_name": _actor_name(actor),
                           "checked_at": now, "check_remarks": payload.get("remarks")})
    else:
        fields.update({"decided_by": me, "decided_by_name": _actor_name(actor),
                       "decided_at": now, "decision_remarks": payload.get("remarks")})
    await get_collection(COLL_PAYROLL_RUNS).update_one(
        {"_id": run["_id"]},
        {"$set": fields,
         "$push": {"approval_trail": _trail(actor, stage["name"], new_status,
                                            payload.get("remarks"))}})
    await audit(actor, AUDIT_PAYROLL_CHECKED if (action == "approve" and not final)
                else AUDIT_PAYROLL_DECIDED, ENTITY_PAYROLL_RUN, period,
                f"{stage['name']}: {new_status}", company_id)
    return await get_run(actor, company_id, period)


async def lock_run(actor: dict, company_id: str, period: str, payload: dict) -> dict:
    """FRD §12 stage 9: Finance locks the approved payroll. Recoveries and variable pay are
    settled, carried-in adjustments marked applied, and the payslip template is frozen for
    this period (FRD §14 Template)."""
    run = await _get_run(company_id, period)
    if run["status"] != PayrollRunStatus.APPROVED.value:
        raise HTTPException(status_code=409,
                            detail=f"Only an approved payroll can be locked "
                                   f"(currently \"{run['status']}\").")
    now = datetime.now(timezone.utc)
    from app.services.hrms_payslip_service import get_payslip_template
    template = await get_payslip_template(company_id)
    await get_collection(COLL_PAYROLL_RUNS).update_one(
        {"_id": run["_id"]},
        {"$set": {"status": PayrollRunStatus.LOCKED.value, "locked_at": now,
                  "locked_by": _actor_id(actor), "locked_by_name": _actor_name(actor),
                  "payslip_template": template,
                  "payslip_template_version": template.get("version"),
                  "totals": await _run_totals(company_id, period), "updated_at": now},
         "$push": {"approval_trail": _trail(actor, "Finance", "Locked", payload.get("remarks"))}})

    records = await get_collection(COLL_PAYROLL_RECORDS).find(
        {"company_id": str(company_id), "period": period}).to_list(5000)
    for record in records:
        if record.get("advance_id") and (record.get("advance_recovery") or 0) > 0:
            await _apply_advance_recovery(company_id, record["advance_id"], record["advance_recovery"])
        if record.get("vp_record_id"):
            await get_collection(COLL_VARIABLE_PAY_RECORDS).update_one(
                {"_id": ObjectId(record["vp_record_id"])},
                {"$set": {"paid_in_period": period}})
        for a in record.get("adjustments") or []:
            if a.get("carry_forward_id"):
                await get_collection(COLL_PAYROLL_CARRY_FORWARD).update_one(
                    {"_id": ObjectId(a["carry_forward_id"])},
                    {"$set": {"status": "Applied", "applied_in_period": period,
                              "updated_at": now}})
    await audit(actor, AUDIT_PAYROLL_LOCKED, ENTITY_PAYROLL_RUN, period, None, company_id)
    return await get_run(actor, company_id, period)


async def close_run(actor: dict, company_id: str, period: str, payload: dict) -> dict:
    """FRD §12 stage 13: close the period once payment is confirmed (or explicitly with a
    reason when some payments are being handled outside the batch)."""
    run = await _get_run(company_id, period)
    if run["status"] not in (PayrollRunStatus.LOCKED.value, PayrollRunStatus.PAID.value):
        raise HTTPException(status_code=409, detail="Only a locked payroll can be closed.")
    from app.services.hrms_disbursal_service import payment_summary
    summary = await payment_summary(company_id, period)
    # DEF-04 -- a payment the bank FAILED/REJECTED (and nobody has retried) or one still
    # Pending in a batch is unfinished business, not something a remark can wave through:
    # once the period is closed no retry batch can be raised, so the money would be stuck.
    # It must be retried, or confirmed as paid (UTR + date) if it was settled outside the
    # batch. A reason still covers people never put in a batch at all (paid off-system).
    if summary["failed"] or summary["pending"]:
        parts = []
        if summary["failed"]:
            parts.append(f"{summary['failed']} failed/rejected payment(s) not yet retried")
        if summary["pending"]:
            parts.append(f"{summary['pending']} payment(s) still pending with the bank")
        raise HTTPException(
            status_code=409,
            detail=f"This period cannot be closed: {' and '.join(parts)}. Under Disbursal, "
                   f"retry them in a new batch or record them as Processed with the UTR and "
                   f"payment date, then close.")
    if summary["unpaid"] and not (payload.get("remarks") or "").strip():
        raise HTTPException(
            status_code=409,
            detail=f"{summary['unpaid']} employee(s) are not yet paid. Record their payment, "
                   f"or give a reason to close anyway.")
    now = datetime.now(timezone.utc)
    await get_collection(COLL_PAYROLL_RUNS).update_one(
        {"_id": run["_id"]},
        {"$set": {"status": PayrollRunStatus.CLOSED.value, "closed_at": now,
                  "closed_by": _actor_id(actor), "payment_summary": summary,
                  "updated_at": now},
         "$push": {"approval_trail": _trail(actor, "Finance", "Closed", payload.get("remarks"))}})
    await audit(actor, AUDIT_PAYROLL_CLOSED, ENTITY_PAYROLL_RUN, period, None, company_id)
    return await get_run(actor, company_id, period)


async def _apply_advance_recovery(company_id: str, advance_id: str, amount: float) -> None:
    advance = await get_collection(COLL_SALARY_ADVANCES).find_one({"_id": ObjectId(advance_id)})
    if not advance:
        return
    recovered = float(advance.get("recovered_amount") or 0) + amount
    status = (AdvanceStatus.CLOSED.value if recovered >= float(advance["amount"])
             else AdvanceStatus.RECOVERING.value)
    await get_collection(COLL_SALARY_ADVANCES).update_one(
        {"_id": advance["_id"]},
        {"$set": {"recovered_amount": round(recovered, 2), "status": status,
                  "updated_at": datetime.now(timezone.utc)}},
    )


# ─────────────────────────────────────────────────────────────
# FRD §18 — post-lock adjustments (arrear / recovery / reversal)
# ─────────────────────────────────────────────────────────────
async def create_post_lock_adjustment(actor: dict, company_id: str, period: str,
                                      payload: dict) -> dict:
    run = await _get_run(company_id, period)
    if run["status"] not in PAYROLL_FINAL_STATUSES:
        raise HTTPException(status_code=409,
                            detail="Post-lock adjustments are for locked payrolls; this one is "
                                   "still editable.")
    employee_code = str(payload.get("employee_code") or "").strip()
    record = await get_collection(COLL_PAYROLL_RECORDS).find_one(
        {"company_id": str(company_id), "period": period, "employee_code": employee_code})
    if not record:
        raise HTTPException(status_code=404, detail="That employee was not in this payroll.")
    kind = str(payload.get("adjustment_type") or "").title()
    if kind not in ("Arrear", "Recovery", "Reversal"):
        raise HTTPException(status_code=422, detail="Type must be Arrear, Recovery or Reversal.")
    amount = round(float(payload.get("amount") or 0), 2)
    if amount <= 0:
        raise HTTPException(status_code=422, detail="Amount must be above 0.")
    reason = (payload.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A reason is required.")
    target = str(payload.get("target_period") or _next_period(period))
    _period_bounds(target)
    if target <= period:
        raise HTTPException(status_code=422, detail="The adjustment lands in a LATER period.")
    target_run = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": target})
    if target_run and target_run.get("status") not in PAYROLL_EDITABLE_STATUSES:
        raise HTTPException(status_code=409,
                            detail=f"The {target} payroll is already {target_run['status']}.")
    now = datetime.now(timezone.utc)
    doc = {"company_id": str(company_id), "employee_code": employee_code,
           "employee_name": record.get("employee_name"), "source_period": period,
           "target_period": target,
           "adjustment_type": "Recovery" if kind == "Reversal" else kind,
           "is_reversal": kind == "Reversal", "amount": amount, "reason": reason,
           "status": "Pending", "created_by": _actor_id(actor),
           "created_by_name": _actor_name(actor), "created_at": now, "updated_at": now}
    result = await get_collection(COLL_PAYROLL_CARRY_FORWARD).insert_one(dict(doc))
    await audit(actor, AUDIT_POST_LOCK_ADJUSTMENT, ENTITY_PAYROLL_RUN,
                f"{period}:{employee_code}", f"{kind} {amount} -> {target}", company_id)
    doc["id"] = str(result.inserted_id)
    return doc


async def list_post_lock_adjustments(actor: dict, company_id: str, period: str) -> list:
    rows = await get_collection(COLL_PAYROLL_CARRY_FORWARD).find(
        {"company_id": str(company_id),
         "$or": [{"source_period": period}, {"target_period": period}]}
    ).sort("created_at", -1).to_list(1000)
    out = []
    for r in rows:
        r = dict(r)
        r["id"] = str(r.pop("_id"))
        out.append(r)
    return out


# ─────────────────────────────────────────────────────────────
# FRD §20 — payroll register
# ─────────────────────────────────────────────────────────────
async def payroll_register_csv(actor: dict, company_id: str, period: str) -> str:
    from app.utils.hrms_access import sees_all_payroll
    if not sees_all_payroll(actor):
        raise HTTPException(status_code=403, detail="Only payroll roles can export the register.")
    records = await get_collection(COLL_PAYROLL_RECORDS).find(
        {"company_id": str(company_id), "period": period}).sort("employee_code", 1).to_list(5000)
    codes = []
    for r in records:
        for line in r.get("lines") or []:
            if line["code"] not in codes:
                codes.append(line["code"])
    buf = io.StringIO()
    writer = csv.writer(buf)
    head = ["Employee ID", "Name", "DOJ", "LWD", "Calendar days", "Working days",
            "Present days", "Payable days", "LOP days", "Weekly off", "Holidays"]
    head += codes
    head += ["Reimbursements", "Arrears", "Variable pay", "Bonus", "Other earnings",
             "Gross earnings", "PF", "ESI", "PT", "TDS", "Advance recovery",
             "Notice recovery", "Other deductions", "Adjustments (net)", "Total deductions",
             "Employer contributions", "Net pay", "Previous net", "Variance", "Variance %",
             "Exceptions"]
    writer.writerow(head)
    for r in records:
        by_code = {l["code"]: l["amount"] for l in r.get("lines") or []}
        adj = _adjustment_sum(r, EARNING_TYPES) - _adjustment_sum(r, DEDUCTING_TYPES)
        writer.writerow(
            [r["employee_code"], r.get("employee_name"), r.get("date_of_joining"),
             r.get("last_working_day"), r.get("days_in_period"), r.get("working_days"),
             r.get("present_days"), r.get("payable_days"), r.get("lop_days"),
             r.get("weekly_off_days"), r.get("holiday_days")]
            + [by_code.get(c, 0) for c in codes]
            + [r.get("reimbursements"), r.get("arrears"), r.get("variable_pay_payout"),
               r.get("bonus"), r.get("other_earnings"), r.get("gross_earnings"),
               r.get("pf"), r.get("esi"), r.get("pt"), r.get("tds"), r.get("advance_recovery"),
               r.get("notice_recovery"), r.get("other_deductions"), round(adj, 2),
               r.get("total_deductions"), r.get("total_employer_contributions"),
               r.get("net_pay"), r.get("previous_net"), r.get("variance_amount"),
               r.get("variance_percent"), "; ".join(r.get("exceptions") or [])])
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# FRD §25 / §29 — simulate a component change before it is saved
# ─────────────────────────────────────────────────────────────
async def simulate_component(actor: dict, company_id: str, code: str, payload: dict) -> dict:
    """Old result versus proposed rule, for every employee whose CURRENT structure carries
    this component or something that depends on it. Nothing is written."""
    from app.services import hrms_formula_engine as FE
    current = {c["code"]: c for c in await list_salary_components(actor, company_id)}
    proposed_def = component_defaults({**current.get(code, {}),
                                       **{k: _plain(v) for k, v in payload.items()
                                          if v is not None}, "code": code})
    if proposed_def.get("calculation_method") == CalculationMethod.FORMULA.value:
        FE.validate(proposed_def.get("formula") or "", set(current) | {code})
    if proposed_def.get("calculation_method") == CalculationMethod.SLAB.value:
        proposed_def["slabs"] = FE.clean_slabs(proposed_def.get("slabs"))
    proposed = {**current, code: proposed_def}
    loop = FE.find_cycle(proposed)
    if loop:
        raise HTTPException(status_code=422,
                            detail=f"{code} would depend on itself: {' -> '.join(loop)}.")
    affected_codes = {code} | set(FE.dependants(proposed, code))

    profiles = await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id)}, {"employee_code": 1, "user_id": 1,
                                          "identity_snapshot": 1, "display_name": 1}).to_list(5000)
    names = await _employee_names(profiles)
    rows, errors = [], []
    for profile in profiles:
        ecode = profile.get("employee_code")
        if not ecode:
            continue
        structure = await get_current_structure(company_id, ecode)
        if not structure:
            continue
        lines = []
        for l in structure.get("components", []):
            if "percentage_override" in l:
                override = l["percentage_override"]
            else:   # saved before overrides were kept apart: a default-equal % is no override
                default = (current.get(l["code"]) or {}).get("percentage")
                override = None if l.get("percentage") == default else l.get("percentage")
            lines.append({"code": l["code"], "amount": l.get("amount") or 0,
                          "percentage": override})
        if not affected_codes & {l["code"] for l in lines}:
            continue
        try:
            new_lines = resolve_lines(lines, proposed, annual_ctc=structure.get("annual_ctc"))
        except HTTPException as e:
            errors.append({"employee_code": ecode, "error": e.detail})
            continue
        old_totals = _structure_totals(structure.get("components", []), current)
        new_totals = _structure_totals(new_lines, proposed)
        old_amt = {l["code"]: l.get("amount") or 0 for l in structure.get("components", [])}
        new_amt = {l["code"]: l["amount"] for l in new_lines}
        changed = {c: {"old": old_amt.get(c, 0), "new": new_amt.get(c, 0)}
                   for c in sorted(affected_codes) if c in new_amt
                   and round(old_amt.get(c, 0), 2) != round(new_amt.get(c, 0), 2)}
        rows.append({"employee_code": ecode, "employee_name": _name_of(profile, names),
                     "components": changed,
                     "old_monthly_gross": old_totals["monthly_gross"],
                     "new_monthly_gross": new_totals["monthly_gross"],
                     "old_monthly_net": old_totals["monthly_net"],
                     "new_monthly_net": new_totals["monthly_net"],
                     "net_difference": round(new_totals["monthly_net"]
                                             - old_totals["monthly_net"], 2),
                     "employer_difference": round(
                         new_totals["monthly_employer_contributions"]
                         - old_totals["monthly_employer_contributions"], 2)})
    return {"code": code, "dependants": sorted(affected_codes - {code}),
            "employees": rows, "errors": errors,
            "summary": {"employees_affected": sum(1 for r in rows if r["components"]),
                        "monthly_net_difference": round(sum(r["net_difference"] for r in rows), 2),
                        "monthly_employer_difference": round(
                            sum(r["employer_difference"] for r in rows), 2)},
            "note": "Simulation only — nothing was saved. Saved structures keep their amounts "
                    "until a new structure revision is made; past payroll is never rewritten."}


# ─────────────────────────────────────────────────────────────
# Calculation variables (FRD §25 "constants", §28 CALCULATION_VARIABLE)
# ─────────────────────────────────────────────────────────────
_VARIABLE_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,39}$")


async def list_calculation_variables(company_id: str) -> list:
    """The company's named constants. Read by the formula validator and by payroll."""
    rows = await get_collection(COLL_CALCULATION_VARIABLES).find(
        {"company_id": str(company_id)}).sort("name", 1).to_list(200)
    return [_out(r) for r in rows]


async def constants_for(company_id: str) -> dict:
    """{NAME: value} for the formula environment."""
    return {r["name"]: float(r.get("value") or 0)
            for r in await list_calculation_variables(company_id)}


async def save_calculation_variable(actor: dict, company_id: str, payload: dict) -> dict:
    """Define or update one named constant.

    The name is checked against the BUILT-IN variables and refused on collision: a company
    constant shadowing PAYABLE_DAYS would silently change what every formula using it
    means, and the formula text would give no hint that it had happened.
    """
    from app.services import hrms_formula_engine as FE
    name = str(payload.get("name") or "").strip().upper()
    if not _VARIABLE_NAME.match(name):
        raise HTTPException(
            status_code=422,
            detail="A variable name is 2-40 characters, UPPER CASE, starting with a letter "
                   "(e.g. PF_WAGE_CEILING).")
    if name in FE.BUILT_INS:
        raise HTTPException(
            status_code=422,
            detail=f"{name} is a built-in variable and cannot be redefined.")
    try:
        value = float(payload.get("value"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="A variable needs a numeric value.")

    now = datetime.now(timezone.utc)
    coll = get_collection(COLL_CALCULATION_VARIABLES)
    current = await coll.find_one({"company_id": str(company_id), "name": name})
    await coll.update_one(
        {"company_id": str(company_id), "name": name},
        {"$set": {"value": value,
                  "label": str(payload.get("label") or "").strip()[:120] or None,
                  "description": str(payload.get("description") or "").strip()[:300] or None,
                  "updated_at": now, "updated_by": _actor_id(actor),
                  "version": int((current or {}).get("version") or 0) + 1},
         "$setOnInsert": {"company_id": str(company_id), "name": name, "created_at": now},
         # A statutory figure changes, and every payroll calculated before the change has
         # to stay explicable. The old value is kept rather than overwritten.
         "$push": {"history": {"at": now, "by": _actor_id(actor),
                               "by_name": _actor_name(actor),
                               "old": (current or {}).get("value"), "new": value,
                               "reason": str(payload.get("change_reason") or "").strip() or None}}},
        upsert=True)
    await audit(actor, AUDIT_SALARY_COMPONENT_SAVED, ENTITY_SALARY_COMPONENT,
                f"variable {name}", str(value), company_id)
    return _out(await coll.find_one({"company_id": str(company_id), "name": name}))


async def delete_calculation_variable(actor: dict, company_id: str, name: str) -> dict:
    """Remove a constant, refusing while any formula still reads it."""
    from app.services import hrms_formula_engine as FE
    name = str(name).strip().upper()
    users = [c["code"] for c in await list_salary_components(actor, company_id)
             if c.get("calculation_method") == CalculationMethod.FORMULA.value
             and name in FE.references(c.get("formula") or "0")]
    if users:
        raise HTTPException(
            status_code=409,
            detail=f"{name} is still used by: {', '.join(users)}. Change those formulas first.")
    await get_collection(COLL_CALCULATION_VARIABLES).delete_one(
        {"company_id": str(company_id), "name": name})
    return {"removed": True}


async def preview_payroll_policy(company_id: str, period: str, *, version_no: int) -> dict:
    """FRD §26 draft preview for PAY_POLICY: what a DRAFT version would change about a run
    already calculated -- net rounding, who the eligibility rule leaves out, and who the
    variance threshold flags. Writes nothing. Previewed company-wide: a scoped version's
    per-employee keys are shown as if they applied to everyone."""
    from app.models.hrms import POLICY_PAY_POLICY
    from app.services import hrms_policy_version_service as PV
    draft = await PV._require_version(company_id, POLICY_PAY_POLICY, int(version_no))
    end = _period_bounds(period)[4]
    live = await get_payroll_policy(company_id, on_date=end)
    proposed = {**live, **{k: v for k, v in (draft.get("rules") or {}).items() if v is not None}}
    changed_rules = sorted(k for k in proposed if proposed.get(k) != live.get(k))
    records = await get_collection(COLL_PAYROLL_RECORDS).find(
        {"company_id": str(company_id), "period": period}).to_list(5000)
    out = {"policy_code": POLICY_PAY_POLICY, "version_no": int(version_no), "period": period,
           "changed_rules": changed_rules, "records_examined": len(records),
           "simulated_at": datetime.now(timezone.utc)}
    if not records:
        return {**out, "changes": [],
                "note": f"No calculated payroll for {period} to test against — calculate it first."}
    categories = {p["employee_code"]: str(p.get("employee_category") or "").strip().lower()
                  for p in await get_collection(COLL_EMPLOYEE_PROFILES).find(
                      {"company_id": str(company_id)},
                      {"employee_code": 1, "employee_category": 1}).to_list(5000)
                  if p.get("employee_code")}

    def judge(rules: dict, r: dict) -> dict:
        excluded = {str(c).strip().lower() for c in rules.get("excluded_employee_categories") or []}
        if excluded and categories.get(r["employee_code"]) in excluded:
            return {"net": 0.0, "left_out": True, "flagged": False}
        raw = float(r.get("net_pay") or 0) - float(r.get("net_rounding_adjustment") or 0)
        pct = r.get("variance_percent")
        limit = float(rules.get("variance_threshold_percent") or 0)
        return {"net": _net_rounding({"net_pay": raw}, rules.get("net_rounding"))["net_pay"],
                "left_out": False,
                "flagged": pct is not None and limit > 0 and abs(float(pct)) > limit}

    changes = []
    net_was = net_now = 0.0
    for r in records:
        was, now = judge(live, r), judge(proposed, r)
        net_was += was["net"]
        net_now += now["net"]
        if was != now:
            changes.append({"employee_code": r["employee_code"],
                            "employee_name": r.get("employee_name"), "was": was, "now": now})
    return {**out, "net_was": round(net_was, 2), "net_now": round(net_now, 2),
            "employees_changed": len(changes),
            "left_out": sum(1 for c in changes if c["now"]["left_out"]),
            "variance_flags_was": sum(1 for r in records if judge(live, r)["flagged"]),
            "variance_flags_now": sum(1 for r in records if judge(proposed, r)["flagged"]),
            "changes": changes}
