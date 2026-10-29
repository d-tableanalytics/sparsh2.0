"""HRMS ▸ configuration change approval flow (Phase 1 FRD §27, §29, §30).

§27 puts seven stages between wanting a rule changed and the rule being live:

    Request → Draft → Impact Analysis → Test/Simulation → Approval → Effective Dating
    → Activation

and §30 adds what must survive it: "Configuration changes are audited with requester,
approver, reason, effective date and old/new definition."

Before this module there was no stage at all. Anyone holding the capability saved straight
to live configuration, which meant the LOP rule that computes everybody's pay could change
with no second pair of eyes, no record of why, and nothing to compare against afterwards.

── What this governs, and what it does not ─────────────────────────────────────────────
The REQUEST is a governance wrapper around a DRAFT that already exists -- today a policy
version, later a salary component or a field definition. Keeping the two apart is what
lets one flow govern several kinds of configuration without each growing its own approval
columns, and what gives the business REASON somewhere to live: a policy version has no
natural place to record why somebody wanted it.

`ENTITY_HANDLERS` is the seam. A later phase adds a governed kind by writing a handler and
naming it in CONFIG_ENTITY_TYPES; nothing in the flow itself changes.

── Activation is the only writer ───────────────────────────────────────────────────────
A governed change reaches live configuration through `activate()` and nowhere else. That
is the whole point of the stage list -- a second path to Active would make the other six
stages decorative.

── Why the impact and simulation stages are STATES ─────────────────────────────────────
Not booleans. §27 lists them as stages with outputs, and an approver needs "has anyone
actually looked at what this breaks" answered before deciding, rather than inferring it
from a flag somebody may never have set. `submit()` refuses a request that has not been
through impact analysis for exactly that reason.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_CONFIG_ACTIVATED, AUDIT_CONFIG_DECIDED, AUDIT_CONFIG_REQUESTED,
    COLL_CONFIG_APPROVALS, COLL_CONFIG_CHANGE_REQUESTS, COLL_EMPLOYEE_PROFILES,
    COLL_FIELD_DEFINITIONS, COLL_SETTINGS,
    CONFIG_ENTITY_FIELD_DEFINITION, CONFIG_ENTITY_POLICY_VERSION,
    CONFIG_ENTITY_SALARY_COMPONENT, CONFIG_ENTITY_TYPES, CONFIG_ENTITY_ATTENDANCE_RULES,
    COLL_SALARY_COMPONENTS, COLL_SALARY_STRUCTURES, ALWAYS_GOVERNED_CONFIG_TYPES,
    DEFAULT_GOVERNED_CONFIG_TYPES, ENTITY_CONFIG_CHANGE,
    ConfigChangeStatus, FieldStatus, PolicyVersionStatus, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id

# A request may still be edited while it is the drafter's. Once submitted it is not.
DRAFTER_STATUSES = {ConfigChangeStatus.DRAFT.value,
                    ConfigChangeStatus.IMPACT_ANALYSED.value,
                    ConfigChangeStatus.SIMULATED.value,
                    ConfigChangeStatus.RETURNED.value}
# Impact analysis must have happened before anyone is asked to approve.
SUBMITTABLE_STATUSES = {ConfigChangeStatus.IMPACT_ANALYSED.value,
                        ConfigChangeStatus.SIMULATED.value,
                        ConfigChangeStatus.RETURNED.value}


def _actor_id(actor: Optional[dict]) -> str:
    return str((actor or {}).get("_id") or "")


def _actor_name(actor: Optional[dict]) -> Optional[str]:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email"))


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id", "")) or None
    return doc


# ─────────────────────────────────────────────────────────────
# Entity handlers — the seam between the flow and what it governs
# ─────────────────────────────────────────────────────────────
async def _policy_load(company_id: str, request: dict) -> dict:
    from app.services import hrms_policy_version_service as PV
    return await PV._require_version(company_id, request["entity_code"],
                                     int(request["version_no"]))


async def _policy_impact(company_id: str, request: dict) -> dict:
    """Who and what a policy-version change reaches.

    Deliberately counts EMPLOYEES rather than listing them: an approver is deciding whether
    the blast radius is what the requester claims, and "412 people in Pune" answers that
    where 412 names do not. The affected periods matter as much as the headcount -- §26
    forbids silently rewriting closed payroll, so a change effective in a closed month is
    the single most important thing to surface here.
    """
    from app.services import hrms_policy_version_service as PV
    version = await _policy_load(company_id, request)
    assignments = await get_collection("hrms_policy_assignments").find(
        {"company_id": str(company_id), "policy_code": request["entity_code"],
         "version_no": int(request["version_no"]), "active": {"$ne": False}}).to_list(200)

    profiles = await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id)}).to_list(5000)
    scopes = [a.get("scope") or {} for a in assignments] or [{}]
    affected = sum(1 for p in profiles
                   if any(PV.specificity(scope, p) >= 0 for scope in scopes))

    siblings = await PV.list_versions(company_id, request["entity_code"])
    superseding = [v["version_no"] for v in siblings
                   if v.get("status") == PolicyVersionStatus.ACTIVE.value
                   and v["version_no"] != int(request["version_no"])]

    effective_from = version.get("effective_from")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "entity": f"{request['entity_code']} v{request['version_no']}",
        "employees_affected": affected,
        "total_employees": len(profiles),
        "scopes": scopes,
        "effective_from": effective_from,
        "currently_active_versions": superseding,
        # §26: "Retroactive policy changes must require explicit authorised adjustment/
        # recalculation workflow rather than silently rewriting prior payroll." A
        # back-dated effective date is therefore a finding, not a detail.
        "retroactive": bool(effective_from and effective_from < today),
        "warnings": ([f"Effective {effective_from}, which is in the past — prior-period "
                      f"attendance and payroll are NOT recalculated automatically."]
                     if effective_from and effective_from < today else []),
    }


async def _policy_activate(actor: dict, company_id: str, request: dict) -> dict:
    from app.services import hrms_policy_version_service as PV
    code, version_no = request["entity_code"], int(request["version_no"])
    version = await _policy_load(company_id, request)
    # Walk it up to Active through the version lifecycle rather than writing the status
    # directly: the lifecycle is what supersedes the version this one displaces, and
    # bypassing it would leave two Active versions for the same population.
    #
    # `via_change_request` is how the lifecycle tells this path apart from a direct API
    # call. Approved and Active are refused to everyone else for a governed policy, so
    # without the flag activation would refuse itself.
    if version.get("status") == PolicyVersionStatus.DRAFT.value:
        await PV.set_status(actor, company_id, code, version_no,
                            PolicyVersionStatus.PENDING.value, via_change_request=True)
        version = await _policy_load(company_id, request)
    if version.get("status") == PolicyVersionStatus.PENDING.value:
        await PV.set_status(actor, company_id, code, version_no,
                            PolicyVersionStatus.APPROVED.value, via_change_request=True)
    return await PV.set_status(actor, company_id, code, version_no,
                               PolicyVersionStatus.ACTIVE.value, via_change_request=True)


async def _policy_describe(company_id: str, request: dict) -> dict:
    """The old/new definition §30 requires the audit to carry."""
    from app.services import hrms_policy_version_service as PV
    new = await _policy_load(company_id, request)
    siblings = await PV.list_versions(company_id, request["entity_code"])
    old = next((v for v in siblings
                if v.get("status") == PolicyVersionStatus.ACTIVE.value
                and v["version_no"] != int(request["version_no"])), None)
    return {"old": (old or {}).get("rules"), "new": new.get("rules"),
            "old_version": (old or {}).get("version_no"),
            "new_version": new.get("version_no")}


# ─────────────────────────────────────────────────────────────
# Salary component (FRD §25 Formula Versioning, §30)
# ─────────────────────────────────────────────────────────────
async def _component_load(company_id: str, request: dict) -> dict:
    doc = await get_collection(COLL_SALARY_COMPONENTS).find_one(
        {"company_id": str(company_id), "code": request["entity_code"]})
    if not doc:
        raise HTTPException(status_code=404,
                            detail=f"No salary component {request['entity_code']}.")
    return doc


async def _component_impact(company_id: str, request: dict) -> dict:
    """What a component change reaches: who is paid it, and what else reads it.

    Leans on the dependency service rather than re-deriving: "what depends on this" has
    one answer in this system, and two implementations would eventually disagree.
    """
    from app.services.hrms_config_dependency_service import (
        ENTITY_COMPONENT, where_used)
    code = request["entity_code"]
    component = await _component_load(company_id, request)
    usage = await where_used(company_id, ENTITY_COMPONENT, code)

    structures = await get_collection(COLL_SALARY_STRUCTURES).find(
        {"company_id": str(company_id), "components.code": code},
        {"employee_code": 1, "status": 1}).to_list(5000)
    paid_to = len({s.get("employee_code") for s in structures
                   if s.get("status") != "Rejected"})

    effective_from = component.get("effective_from")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    retroactive = bool(effective_from and effective_from < today)
    warnings = []
    if retroactive:
        warnings.append(
            f"Effective {effective_from}, which is in the past — payroll already run for "
            f"those months is NOT recalculated automatically.")
    if usage["references"]:
        warnings.append(
            f"{len(usage['references'])} other piece(s) of configuration read this "
            f"component; changing what it means changes them too.")

    return {
        "entity": f"{code} ({component.get('name') or ''})".strip(),
        "employees_affected": paid_to,
        "total_employees": await get_collection(COLL_EMPLOYEE_PROFILES).count_documents(
            {"company_id": str(company_id)}),
        "effective_from": effective_from,
        "references": usage["references"],
        "history": usage["history"],
        "retroactive": retroactive,
        "warnings": warnings,
    }


COMPONENT_CALC_KEYS = ("calculation_method", "calculation_base", "percentage", "formula",
                       "slabs", "proration", "rounding", "frequency", "min_amount",
                       "max_amount", "rate", "attendance_basis", "applicability",
                       "effective_from", "effective_to")


async def _component_activate(actor: dict, company_id: str, request: dict) -> dict:
    """Make the component live.

    A Draft simply becomes Active. A revision of a LIVE component (staged by
    hrms_payroll_service._stage_component_change) is applied here and only here: the
    definition it replaces is kept as a Superseded version (§24 Lifecycle, §25 "Formula has
    version, effective dates, status and approval"), and the approver recorded is the one
    who decided the request, not whoever pressed Activate."""
    component = await _component_load(company_id, request)
    now = datetime.now(timezone.utc)
    pending = dict(component.get("pending_definition") or {})
    pending.pop("lifecycle", None)
    # pending_request_no is cleared on every activation: a NEW component (DEF-02) carries
    # its creating request there with no staged definition behind it.
    updates = {"lifecycle": "Active", "activated_at": now, "updated_at": now,
               "pending_request_no": None,
               "approved_by": request.get("decided_by"),
               "approved_by_name": request.get("decided_by_name")}
    push = {}
    if pending:
        version = int(component.get("version") or 1)
        updates.update({**pending, "version": version + 1, "pending_definition": None,
                        "pending_reason": None, "pending_request_no": None})
        push = {
            "versions": {"version": version, "status": "Superseded",
                         "definition": {k: component.get(k) for k in COMPONENT_CALC_KEYS},
                         "superseded_at": now, "superseded_by_request": request.get("request_no")},
            "history": {"at": now, "by": _actor_id(actor), "by_name": _actor_name(actor),
                        "reason": request.get("reason"), "via": request.get("request_no"),
                        "old": {k: component.get(k) for k in pending}, "new": pending},
        }
    await get_collection(COLL_SALARY_COMPONENTS).update_one(
        {"company_id": str(company_id), "code": component["code"]},
        {"$set": updates, **({"$push": push} if push else {})})
    return await _component_load(company_id, request)


async def _component_approve(actor: dict, company_id: str, request: dict) -> None:
    """§24 lifecycle: a Draft component whose request is approved reads Approved until it
    is activated. A live one with a staged revision stays Active."""
    component = await _component_load(company_id, request)
    if component.get("lifecycle") != "Draft":
        return
    now = datetime.now(timezone.utc)
    await get_collection(COLL_SALARY_COMPONENTS).update_one(
        {"company_id": str(company_id), "code": component["code"], "lifecycle": "Draft"},
        {"$set": {"lifecycle": "Approved", "approved_by": _actor_id(actor),
                  "approved_by_name": _actor_name(actor), "approved_at": now,
                  "updated_at": now}})


async def _component_describe(company_id: str, request: dict) -> dict:
    """The old/new definition §30 requires — for a component that means the CALCULATION,
    which is what a reader of the audit actually wants to compare."""
    component = await _component_load(company_id, request)
    pending = component.get("pending_definition") or {}
    if pending:
        keys = sorted(pending)
        return {"old": {k: component.get(k) for k in keys},
                "new": {k: pending.get(k) for k in keys},
                "old_version": component.get("version"),
                "new_version": int(component.get("version") or 1) + 1}
    keys = ("calculation_method", "calculation_base", "percentage", "formula", "slabs",
            "proration", "rounding", "frequency", "min_amount", "max_amount")
    history = component.get("history") or []
    previous = history[-1].get("old") if history else None
    return {
        "old": {k: (previous or {}).get(k) for k in keys} if previous else None,
        "new": {k: component.get(k) for k in keys},
        "old_version": max(1, int(component.get("version") or 1) - 1),
        "new_version": component.get("version"),
    }


# ─────────────────────────────────────────────────────────────
# Field definition (FRD §27, §29, §30)
# ─────────────────────────────────────────────────────────────
def _field_parts(entity_code: str) -> tuple:
    """`employee.blood_group` out of the request's entity_code.

    `create_request` upper-cases every entity_code, which suits a policy code and a
    component code and does not suit a field, whose codes are lowercase by validation. The
    normalisation lives here rather than in the flow because it is this entity's spelling
    rule, not the flow's.
    """
    text = str(entity_code or "").strip().lower()
    module, _, code = text.partition(".")
    if not module or not code:
        raise HTTPException(
            status_code=422,
            detail="Name a field as module.code, e.g. employee.blood_group.")
    return module, code


async def _field_load(company_id: str, request: dict) -> dict:
    module, code = _field_parts(request["entity_code"])
    doc = await get_collection(COLL_FIELD_DEFINITIONS).find_one(
        {"company_id": str(company_id), "module": module, "code": code})
    if not doc:
        raise HTTPException(status_code=404,
                            detail=f"No {module} field '{code}'.")
    return doc


async def _field_impact(company_id: str, request: dict) -> dict:
    """What a field change reaches: who holds a value for it, and what reads it.

    Leans on the dependency service, which already answers "what points at this field" for
    the §29 viewer -- two implementations of that question would eventually disagree.
    """
    from app.services.hrms_config_dependency_service import ENTITY_FIELD, where_used
    module, code = _field_parts(request["entity_code"])
    definition = await _field_load(company_id, request)
    usage = await where_used(company_id, ENTITY_FIELD, code, module)

    holders = usage.get("holders")
    if holders is None:                     # count it ourselves when the viewer does not
        from app.services.hrms_employee_master_service import field_usage
        holders = (await field_usage(company_id, module, code)).get("employees_with_value")

    pending = definition.get("pending_definition") or {}
    warnings = []
    if pending.get("mandatory") and not definition.get("mandatory"):
        warnings.append(
            f"Becomes MANDATORY while {holders} employee(s) hold a value — every record "
            f"without one fails validation on its next save.")
    if definition.get("sensitive") and pending.get("sensitive") is False:
        warnings.append("Stops being masked, so the value becomes readable on screen "
                        "and in exports to anyone who can see the record.")
    if usage["references"]:
        warnings.append(f"{len(usage['references'])} other piece(s) of configuration read "
                        f"this field.")

    return {
        "entity": f"{module}.{code} ({definition.get('label') or ''})".strip(),
        "employees_affected": holders,
        "total_employees": await get_collection(COLL_EMPLOYEE_PROFILES).count_documents(
            {"company_id": str(company_id)}),
        "effective_from": definition.get("effective_from"),
        "references": usage["references"],
        "history": usage["history"],
        "retroactive": False,
        "warnings": warnings,
    }


async def _field_activate(actor: dict, company_id: str, request: dict) -> dict:
    """Apply the staged definition and make the field live.

    A governed edit to a LIVE field is held on the document as `pending_definition` rather
    than written over the live one, so the field goes on validating and masking exactly as
    it did while the change waits. This is the step that applies it -- and the only one.
    """
    definition = await _field_load(company_id, request)
    pending = definition.get("pending_definition") or {}
    now = datetime.now(timezone.utc)
    updates = {**pending, "status": FieldStatus.ACTIVE.value, "updated_at": now,
               "approved_by": _actor_id(actor), "approved_by_name": _actor_name(actor),
               "approved_at": now, "pending_definition": None, "pending_request_no": None}
    if not definition.get("effective_from"):
        updates["effective_from"] = now.strftime("%Y-%m-%d")
    entry = {"at": now, "by": _actor_id(actor), "by_name": _actor_name(actor),
             "reason": request.get("reason"), "via": request.get("request_no"),
             "old": {k: definition.get(k) for k in pending} or {"status": definition["status"]},
             "new": pending or {"status": FieldStatus.ACTIVE.value}}
    await get_collection(COLL_FIELD_DEFINITIONS).update_one(
        {"_id": definition["_id"]}, {"$set": updates, "$push": {"history": entry}})
    return await _field_load(company_id, request)


async def _field_approve(actor: dict, company_id: str, request: dict) -> None:
    """§22 lifecycle: a Draft field whose request is approved reads Approved until it is
    activated. A live field with a staged edit stays Active -- its live definition has not
    changed yet."""
    definition = await _field_load(company_id, request)
    if definition.get("status") != FieldStatus.DRAFT.value:
        return
    now = datetime.now(timezone.utc)
    await get_collection(COLL_FIELD_DEFINITIONS).update_one(
        {"_id": definition["_id"], "status": FieldStatus.DRAFT.value},
        {"$set": {"status": FieldStatus.APPROVED.value, "approved_by": _actor_id(actor),
                  "approved_by_name": _actor_name(actor), "approved_at": now,
                  "updated_at": now}})


# ─────────────────────────────────────────────────────────────
# Company attendance rules (FRD §30)
# ─────────────────────────────────────────────────────────────
async def _att_rules_load(company_id: str, request: dict) -> dict:
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)}) or {}
    if not (doc.get("shift_policy_pending") or {}).get("changes"):
        raise HTTPException(status_code=404,
                            detail="No attendance-rule change is waiting to be applied.")
    return doc


async def _att_rules_impact(company_id: str, request: dict) -> dict:
    doc = await _att_rules_load(company_id, request)
    pending = doc["shift_policy_pending"]
    total = await get_collection(COLL_EMPLOYEE_PROFILES).count_documents(
        {"company_id": str(company_id)})
    return {"entity": "Company attendance rules", "employees_affected": total,
            "total_employees": total,
            "effective_from": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "references": [], "history": [], "retroactive": False,
            "warnings": [f"Changes {', '.join(sorted(pending['changes']))} for every employee "
                         f"whose shift or policy does not override it. Days already judged "
                         f"keep their status."]}


async def _att_rules_activate(actor: dict, company_id: str, request: dict) -> dict:
    from app.services.hrms_attendance_service import apply_shift_policy, get_shift_policy
    doc = await _att_rules_load(company_id, request)
    pending = doc["shift_policy_pending"]
    current = await get_shift_policy(company_id)
    await apply_shift_policy(
        actor, company_id, current, {**current, **pending["changes"]}, pending.get("reason"),
        approved_by=request.get("decided_by_name") or request.get("decided_by"),
        via=request.get("request_no"))
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)}, {"$set": {"shift_policy_pending": None}})
    return await get_shift_policy(company_id)


async def _att_rules_describe(company_id: str, request: dict) -> dict:
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)}) or {}
    pending = doc.get("shift_policy_pending") or {}
    return {"old": pending.get("old"), "new": pending.get("changes"),
            "old_version": doc.get("shift_policy_version"),
            "new_version": int(doc.get("shift_policy_version") or 0) + 1}


async def _field_describe(company_id: str, request: dict) -> dict:
    """§30's old/new definition -- the staged change against what is live now."""
    definition = await _field_load(company_id, request)
    pending = definition.get("pending_definition") or {}
    keys = sorted(pending) or ["status"]
    return {
        "old": {k: definition.get(k) for k in keys},
        "new": {**{k: pending.get(k) for k in keys},
                **({} if pending else {"status": FieldStatus.ACTIVE.value})},
        "old_version": definition.get("version"),
        "new_version": int(definition.get("version") or 1),
    }


ENTITY_HANDLERS = {
    CONFIG_ENTITY_POLICY_VERSION: {
        "load": _policy_load,
        "impact": _policy_impact,
        "activate": _policy_activate,
        "describe": _policy_describe,
    },
    CONFIG_ENTITY_SALARY_COMPONENT: {
        "load": _component_load,
        "impact": _component_impact,
        "activate": _component_activate,
        "describe": _component_describe,
        "approve": _component_approve,
    },
    CONFIG_ENTITY_FIELD_DEFINITION: {
        "load": _field_load,
        "impact": _field_impact,
        "activate": _field_activate,
        "describe": _field_describe,
        "approve": _field_approve,
    },
    CONFIG_ENTITY_ATTENDANCE_RULES: {
        "load": _att_rules_load,
        "impact": _att_rules_impact,
        "activate": _att_rules_activate,
        "describe": _att_rules_describe,
    },
}


# ─────────────────────────────────────────────────────────────
# Which types this company governs
# ─────────────────────────────────────────────────────────────
async def governed_types(company_id: str) -> set:
    """The configuration types this company puts through the flow.

    Read from `hrms_settings.governed_config_types`, defaulting to the pay-deciding ones
    plus field definitions (DEFAULT_GOVERNED_CONFIG_TYPES).
    An unknown or misspelt name is DROPPED rather than honoured: a typo in this setting
    must not be able to un-govern the salary components by accident, and silently governing
    a type nothing can handle would 422 every save of it.
    """
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    stored = (doc or {}).get("governed_config_types")
    if stored is None:
        return set(DEFAULT_GOVERNED_CONFIG_TYPES)
    return {t for t in (str(x).strip() for x in stored) if t in CONFIG_ENTITY_TYPES}


async def is_governed(company_id: str, entity_type: str) -> bool:
    return entity_type in await governed_types(company_id)


async def set_governed_types(actor: dict, company_id: str, types) -> dict:
    """The admin toggle on the Configuration Approval Inbox.

    The pay-deciding types cannot be switched off. Letting an administrator un-govern the
    salary components would make the whole flow optional for the one thing it exists to
    protect, and whoever could turn it off is exactly whoever would want to.
    """
    wanted = {str(t).strip() for t in (types or [])}
    unknown = wanted - set(CONFIG_ENTITY_TYPES)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown configuration type(s): {', '.join(sorted(unknown))}. "
                   f"Known: {', '.join(CONFIG_ENTITY_TYPES)}.")
    final = sorted(wanted | set(ALWAYS_GOVERNED_CONFIG_TYPES))
    now = datetime.now(timezone.utc)
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {"governed_config_types": final, "updated_at": now},
         "$setOnInsert": {"company_id": str(company_id)}}, upsert=True)
    await audit(actor, AUDIT_CONFIG_DECIDED, ENTITY_CONFIG_CHANGE, "governed_types",
                ", ".join(final), company_id)
    return {"governed_config_types": final,
            "always_governed": sorted(ALWAYS_GOVERNED_CONFIG_TYPES),
            "known": list(CONFIG_ENTITY_TYPES)}


async def get_governed_types(company_id: str) -> dict:
    return {"governed_config_types": sorted(await governed_types(company_id)),
            "always_governed": sorted(ALWAYS_GOVERNED_CONFIG_TYPES),
            "known": list(CONFIG_ENTITY_TYPES)}


def _handler(entity_type: str) -> dict:
    handler = ENTITY_HANDLERS.get(entity_type)
    if not handler:
        raise HTTPException(
            status_code=422,
            detail=f"'{entity_type}' is not a governed configuration type. "
                   f"Governed: {', '.join(CONFIG_ENTITY_TYPES)}.")
    return handler


# ─────────────────────────────────────────────────────────────
# The flow
# ─────────────────────────────────────────────────────────────
async def _require_request(company_id: str, request_no: str) -> dict:
    doc = await get_collection(COLL_CONFIG_CHANGE_REQUESTS).find_one(
        {"company_id": str(company_id), "request_no": request_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"No change request {request_no}.")
    return doc


async def create_request(actor: dict, company_id: str, payload: dict) -> dict:
    """§27 Request — "records requested change and business reason"."""
    entity_type = str(payload.get("entity_type") or CONFIG_ENTITY_POLICY_VERSION)
    handler = _handler(entity_type)
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=422,
                            detail="Say why this change is wanted — the approver and the "
                                   "audit trail both need the business reason.")
    entity_code = str(payload.get("entity_code") or "").strip().upper()
    if not entity_code:
        raise HTTPException(status_code=422, detail="Name what is being changed.")
    version_no = payload.get("version_no")
    # A POLICY change names a version; a COMPONENT change names the component, whose own
    # `version` counter says which revision is being governed. Requiring a version number
    # for both would mean asking the requester for a number they have no way to know.
    if version_no is None and entity_type == CONFIG_ENTITY_POLICY_VERSION:
        raise HTTPException(status_code=422, detail="Name which version is being changed.")

    draft = {"entity_type": entity_type, "entity_code": entity_code,
             "version_no": int(version_no) if version_no is not None else None}
    await handler["load"](company_id, draft)      # 404s now rather than at approval time

    effective_from = payload.get("effective_from")
    if effective_from and not is_iso_date(str(effective_from)):
        raise HTTPException(status_code=422,
                            detail="Effective from must be a date (YYYY-MM-DD).")

    now = datetime.now(timezone.utc)
    request_no = await next_business_id("config_change", str(company_id), now.year)
    doc = {
        "company_id": str(company_id), "request_no": request_no, **draft,
        "title": str(payload.get("title") or "").strip()[:160] or None,
        "reason": reason, "effective_from": effective_from,
        "status": ConfigChangeStatus.DRAFT.value,
        "requested_by": _actor_id(actor), "requested_by_name": _actor_name(actor),
        "requested_at": now, "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_CONFIG_CHANGE_REQUESTS).insert_one(doc)
    await audit(actor, AUDIT_CONFIG_REQUESTED, ENTITY_CONFIG_CHANGE, request_no,
                f"{entity_code} v{version_no}", company_id)
    return _out(await _require_request(company_id, request_no))


async def _periods_reached(company_id: str, request: dict, impact: dict) -> dict:
    """§27 Impact Analysis "open/closed periods": every month from the change's effective
    date to this one, split by whether attendance or payroll has already closed it.

    Closed = attendance locked, or payroll at Locked or beyond. Those months keep the
    figures they were closed with; the approver should know a back-dated change will not
    reach them.
    """
    from app.models.hrms import COLL_ATTENDANCE_LOCKS, COLL_PAYROLL_RUNS, PAYROLL_FINAL_STATUSES
    today = datetime.now(timezone.utc).strftime("%Y-%m")
    start = str(request.get("effective_from") or impact.get("effective_from") or "")[:7] or today
    months, cursor = [], start
    while cursor <= today and len(months) < 24:
        months.append(cursor)
        y, m = int(cursor[:4]), int(cursor[5:7])
        cursor = f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"
    if not months:
        return {"from": start, "open": [], "closed": []}
    locked = {d["period"] for d in await get_collection(COLL_ATTENDANCE_LOCKS).find(
        {"company_id": str(company_id), "period": {"$in": months}, "status": "Locked"},
        {"period": 1}).to_list(100)}
    paid = {d["period"] for d in await get_collection(COLL_PAYROLL_RUNS).find(
        {"company_id": str(company_id), "period": {"$in": months},
         "status": {"$in": list(PAYROLL_FINAL_STATUSES)}}, {"period": 1}).to_list(100)}
    closed = [m for m in months if m in locked or m in paid]
    return {"from": start, "open": [m for m in months if m not in closed], "closed": closed,
            "attendance_locked": sorted(locked), "payroll_closed": sorted(paid)}


async def analyse_impact(actor: dict, company_id: str, request_no: str) -> dict:
    """§27 Impact Analysis — "identifies dependent fields, calculations, employee groups
    and open/closed periods". Stored on the request so an approver reads the same analysis
    the drafter saw, rather than one recomputed against data that has since moved."""
    request = await _require_request(company_id, request_no)
    if request["status"] not in DRAFTER_STATUSES:
        raise HTTPException(status_code=409,
                            detail=f"{request_no} is {request['status']} and is no longer "
                                   f"the drafter's to analyse.")
    impact = await _handler(request["entity_type"])["impact"](company_id, request)
    impact["periods"] = await _periods_reached(company_id, request, impact)
    if impact["periods"]["closed"]:
        impact.setdefault("warnings", []).append(
            f"Reaches {len(impact['periods']['closed'])} closed period(s) "
            f"({', '.join(impact['periods']['closed'])}) — they are NOT recalculated; a "
            f"correction there is a post-lock adjustment.")
    now = datetime.now(timezone.utc)
    await get_collection(COLL_CONFIG_CHANGE_REQUESTS).update_one(
        {"_id": request["_id"]},
        {"$set": {"impact": impact, "impact_at": now, "updated_at": now,
                  "status": ConfigChangeStatus.IMPACT_ANALYSED.value}})
    return _out(await _require_request(company_id, request_no))


async def record_simulation(actor: dict, company_id: str, request_no: str,
                            result: dict) -> dict:
    """§27 Test/Simulation — "previewed against representative data before production
    activation". The simulation itself belongs to whatever understands the rules (Step 5
    for attendance, simulate_component for payroll); this records that it happened and
    what it showed, which is what the approver is entitled to see."""
    request = await _require_request(company_id, request_no)
    if request["status"] not in DRAFTER_STATUSES:
        raise HTTPException(status_code=409,
                            detail=f"{request_no} is {request['status']} and is no longer "
                                   f"the drafter's to simulate.")
    now = datetime.now(timezone.utc)
    await get_collection(COLL_CONFIG_CHANGE_REQUESTS).update_one(
        {"_id": request["_id"]},
        {"$set": {"simulation": result or {}, "simulated_at": now, "updated_at": now,
                  "status": ConfigChangeStatus.SIMULATED.value}})
    return _out(await _require_request(company_id, request_no))


async def run_simulation(actor: dict, company_id: str, request_no: str,
                         period: Optional[str] = None) -> dict:
    """§27 Test/Simulation, run FROM the request and recorded on it.

    Picks the simulation that understands the entity -- the day re-judge for ATT_DAY, the
    request / closure / payroll previews for the other policies, the component simulation
    against a component's staged revision -- so the approver sees what the drafter saw
    without the drafter having to carry a result across screens. Field definitions have no
    calculation to simulate; impact analysis is their test.
    """
    from app.models.hrms import (POLICY_ATT_CLOSURE, POLICY_ATT_DAY,
                                 POLICY_ATT_REGULARISATION, POLICY_PAY_POLICY)
    from app.services import hrms_attendance_simulation_service as SIM
    from app.services import hrms_payroll_service as PS
    request = await _require_request(company_id, request_no)
    period = period or datetime.now(timezone.utc).strftime("%Y-%m")
    kind, code = request["entity_type"], request["entity_code"]
    if kind == CONFIG_ENTITY_POLICY_VERSION:
        version = int(request.get("version_no") or 0)
        if code == POLICY_ATT_DAY:
            result = await SIM.simulate_day_policy(company_id, period, version_no=version)
        elif code == POLICY_ATT_REGULARISATION:
            result = await SIM.preview_regularisation_policy(company_id, period,
                                                             version_no=version)
        elif code == POLICY_ATT_CLOSURE:
            result = await SIM.preview_closure_policy(actor, company_id, period,
                                                      version_no=version)
        elif code == POLICY_PAY_POLICY:
            result = await PS.preview_payroll_policy(company_id, period, version_no=version)
        else:
            raise HTTPException(status_code=422, detail=f"{code} has no simulation.")
    elif kind == CONFIG_ENTITY_SALARY_COMPONENT:
        component = await _component_load(company_id, request)
        proposed = {k: v for k, v in component.items()
                    if k not in ("_id", "history", "versions", "pending_definition")}
        proposed.update(component.get("pending_definition") or {})
        result = await PS.simulate_component(actor, company_id, component["code"], proposed)
    else:
        raise HTTPException(status_code=422,
                            detail="A field change has no calculation to simulate — its "
                                   "impact analysis is the test.")
    result = dict(result or {})
    for key in ("changes", "employees", "rows"):
        if isinstance(result.get(key), list) and len(result[key]) > 50:
            result[f"{key}_total"] = len(result[key])
            result[key] = result[key][:50]
    result["period"] = result.get("period") or period
    return await record_simulation(actor, company_id, request_no, result)


async def submit(actor: dict, company_id: str, request_no: str) -> dict:
    """Hand the request to an approver.

    Refused until impact analysis has run. §27 lists it as a stage before Approval, and an
    approver asked to decide without it is being asked to guess at the blast radius.
    """
    request = await _require_request(company_id, request_no)
    if request["status"] not in SUBMITTABLE_STATUSES:
        if request["status"] == ConfigChangeStatus.DRAFT.value:
            raise HTTPException(
                status_code=409,
                detail="Run the impact analysis before sending this for approval — the "
                       "approver needs to see what it affects.")
        raise HTTPException(status_code=409,
                            detail=f"{request_no} is {request['status']} and cannot be "
                                   f"submitted.")
    now = datetime.now(timezone.utc)
    await get_collection(COLL_CONFIG_CHANGE_REQUESTS).update_one(
        {"_id": request["_id"]},
        {"$set": {"status": ConfigChangeStatus.PENDING.value, "submitted_by": _actor_id(actor),
                  "submitted_by_name": _actor_name(actor), "submitted_at": now,
                  "updated_at": now}})
    return _out(await _require_request(company_id, request_no))


async def decide(actor: dict, company_id: str, request_no: str, payload: dict) -> dict:
    """§27 Approval — "reviews and approves/rejects/returns".

    Never the requester. A configuration change that one person can both ask for and grant
    has the same shape as a payroll one person both submits and approves, and §30 draws the
    same separation ("permission-controlled and separate").
    """
    request = await _require_request(company_id, request_no)
    if request["status"] != ConfigChangeStatus.PENDING.value:
        raise HTTPException(status_code=409,
                            detail=f"{request_no} is {request['status']}, not awaiting a "
                                   f"decision.")
    if request.get("requested_by") and request["requested_by"] == _actor_id(actor):
        raise HTTPException(status_code=403,
                            detail="You raised this change, so the approval is someone "
                                   "else's to give.")
    action = str(payload.get("action") or "").strip().lower()
    statuses = {"approve": ConfigChangeStatus.APPROVED.value,
                "reject": ConfigChangeStatus.REJECTED.value,
                "return": ConfigChangeStatus.RETURNED.value}
    if action not in statuses:
        raise HTTPException(status_code=422,
                            detail="Action must be approve, reject or return.")
    comments = str(payload.get("comments") or "").strip()
    if action != "approve" and not comments:
        raise HTTPException(status_code=422,
                            detail="Say why the change is being sent back.")

    now = datetime.now(timezone.utc)
    await get_collection(COLL_CONFIG_APPROVALS).insert_one({
        "company_id": str(company_id), "request_no": request_no, "decision": statuses[action],
        "approver_user_id": _actor_id(actor), "approver_name": _actor_name(actor),
        "comments": comments or None, "decided_at": now,
    })
    await get_collection(COLL_CONFIG_CHANGE_REQUESTS).update_one(
        {"_id": request["_id"]},
        {"$set": {"status": statuses[action], "decided_by": _actor_id(actor),
                  "decided_by_name": _actor_name(actor), "decided_at": now,
                  "decision_comments": comments or None, "updated_at": now}})
    await audit(actor, AUDIT_CONFIG_DECIDED, ENTITY_CONFIG_CHANGE, request_no,
                statuses[action], company_id)
    on_approve = (ENTITY_HANDLERS.get(request.get("entity_type")) or {}).get("approve")
    if action == "approve" and on_approve:
        await on_approve(actor, company_id, request)
    return _out(await _require_request(company_id, request_no))


async def activate(actor: dict, company_id: str, request_no: str) -> dict:
    """§27 Activation — the ONLY path from an approved change to live configuration.

    Records the old and new definition as it goes (§30), because once the change is applied
    the old one is no longer the thing the resolver returns, and reconstructing it later
    means trusting that nothing else moved in between.
    """
    request = await _require_request(company_id, request_no)
    if request["status"] != ConfigChangeStatus.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=f"{request_no} is {request['status']}. Only an approved change can be "
                   f"activated.")
    handler = _handler(request["entity_type"])
    definition = await handler["describe"](company_id, request)
    await handler["activate"](actor, company_id, request)

    now = datetime.now(timezone.utc)
    await get_collection(COLL_CONFIG_CHANGE_REQUESTS).update_one(
        {"_id": request["_id"]},
        {"$set": {"status": ConfigChangeStatus.ACTIVE.value, "activated_by": _actor_id(actor),
                  "activated_by_name": _actor_name(actor), "activated_at": now,
                  "definition_change": definition, "updated_at": now}})
    await audit(actor, AUDIT_CONFIG_ACTIVATED, ENTITY_CONFIG_CHANGE, request_no,
                f"{request['entity_code']} v{request['version_no']}", company_id)
    return _out(await _require_request(company_id, request_no))


async def withdraw(actor: dict, company_id: str, request_no: str, reason: str) -> dict:
    request = await _require_request(company_id, request_no)
    if request["status"] in (ConfigChangeStatus.ACTIVE.value,):
        raise HTTPException(status_code=409,
                            detail="An activated change cannot be withdrawn. Raise a new "
                                   "change to reverse it.")
    if not (reason or "").strip():
        raise HTTPException(status_code=422, detail="Say why it is being withdrawn.")
    await get_collection(COLL_CONFIG_CHANGE_REQUESTS).update_one(
        {"_id": request["_id"]},
        {"$set": {"status": ConfigChangeStatus.WITHDRAWN.value,
                  "decision_comments": reason.strip(),
                  "updated_at": datetime.now(timezone.utc)}})
    return _out(await _require_request(company_id, request_no))


async def list_requests(company_id: str, *, status: Optional[str] = None,
                        limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    rows = await get_collection(COLL_CONFIG_CHANGE_REQUESTS).find(query).sort(
        "created_at", -1).to_list(limit)
    return [_out(r) for r in rows]


async def get_request(company_id: str, request_no: str) -> dict:
    """One request with its decision trail — what the Configuration Audit Viewer (§29)
    and the Approval Inbox both read."""
    request = _out(await _require_request(company_id, request_no))
    request["approvals"] = [_out(a) for a in await get_collection(
        COLL_CONFIG_APPROVALS).find(
            {"company_id": str(company_id), "request_no": request_no}).sort(
                "decided_at", 1).to_list(100)]
    return request
