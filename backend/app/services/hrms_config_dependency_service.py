"""HRMS ▸ configuration impact / dependency viewer (Phase 1 FRD §22, §29, §30).

§29 asks for a "Configuration Impact / Dependency Viewer — show where a field/rule/
component is used before modification/retirement", and §30 for "An impact/dependency check
is available before a field, policy or formula is retired."

One such check existed: `hrms_employee_master_service.field_usage`, which counts how many
employee records hold a value for one custom field. Useful, and only a fifth of the
question — nothing could answer "what breaks if I retire this salary component", which is
the case where the answer is measured in money.

── What "used" means here ──────────────────────────────────────────────────────────────
Two kinds of dependency, reported separately because they have opposite consequences:

  REFERENCES   another piece of CONFIGURATION points at this one — a formula naming the
               component, a structure including it, a bank format emitting the field.
               Retiring it breaks that thing NEXT time it runs. This is what must block a
               retirement.
  HISTORY      a past payroll, payslip or employee record already used it. Retiring it
               breaks NOTHING going forward — but it is exactly why §21 says retire rather
               than delete, so the count is shown to explain why deletion is not offered.

A viewer that merged the two would make every long-serving component look un-retirable.
"""
from typing import Optional

from app.db.mongodb import get_collection
from app.models.hrms import (
    COLL_EMPLOYEE_PROFILES, COLL_FIELD_DEFINITIONS, COLL_PAYROLL_RECORDS,
    COLL_POLICY_ASSIGNMENTS, COLL_POLICY_VERSIONS, COLL_SALARY_COMPONENTS,
    COLL_SALARY_STRUCTURES, COLL_BANK_FILE_FORMATS,
)

ENTITY_COMPONENT = "salary_component"
ENTITY_FIELD = "field_definition"
ENTITY_POLICY = "policy"
DEPENDENCY_ENTITIES = (ENTITY_COMPONENT, ENTITY_FIELD, ENTITY_POLICY)


def _ref(kind: str, name: str, detail: str = None, blocking: bool = True) -> dict:
    return {"kind": kind, "name": name, "detail": detail, "blocking": blocking}


# ─────────────────────────────────────────────────────────────
# Salary component
# ─────────────────────────────────────────────────────────────
async def _component_usage(company_id: str, code: str) -> dict:
    code = str(code).strip()
    refs, history = [], []

    components = await get_collection(COLL_SALARY_COMPONENTS).find(
        {"company_id": str(company_id)}).to_list(500)
    from app.services import hrms_formula_engine as FE
    for other in components:
        if other.get("code") == code:
            continue
        # A formula naming it, or a percentage/slab taking it as a base. `dependencies`
        # already knows both shapes, so asking it keeps one definition of "depends on".
        if code in FE.dependencies(other):
            refs.append(_ref("component", other.get("code"),
                             f"{other.get('name') or ''} — {other.get('calculation_method')}"
                             f" uses {code}"))

    structures = await get_collection(COLL_SALARY_STRUCTURES).find(
        {"company_id": str(company_id), "components.code": code},
        {"employee_code": 1, "status": 1, "effective_from": 1}).to_list(2000)
    live = [s for s in structures if s.get("status") != "Rejected"]
    if live:
        refs.append(_ref("salary structure", f"{len(live)} employee structure(s)",
                         "these employees are paid this component"))

    paid = await get_collection(COLL_PAYROLL_RECORDS).count_documents(
        {"company_id": str(company_id), "lines.code": code})
    if paid:
        history.append(_ref("payroll record", f"{paid} payroll record(s)",
                            "already paid — the definition must survive for their payslips",
                            blocking=False))

    formats = await get_collection(COLL_BANK_FILE_FORMATS).find(
        {"company_id": str(company_id)}).to_list(100)
    for fmt in formats:
        if any(c.get("source") == code for c in fmt.get("columns") or []):
            refs.append(_ref("bank file format", fmt.get("name")))

    return {"references": refs, "history": history}


# ─────────────────────────────────────────────────────────────
# Configurable field
# ─────────────────────────────────────────────────────────────
async def _field_usage(company_id: str, code: str, module: str = "employee") -> dict:
    refs, history = [], []
    values = await get_collection(COLL_EMPLOYEE_PROFILES).count_documents(
        {"company_id": str(company_id), f"custom_fields.{code}": {"$exists": True}})
    if values:
        history.append(_ref("employee record", f"{values} employee(s) hold a value",
                            "retire rather than delete, so the values stay readable",
                            blocking=False))

    formats = await get_collection(COLL_BANK_FILE_FORMATS).find(
        {"company_id": str(company_id)}).to_list(100)
    for fmt in formats:
        if any(c.get("source") == code for c in fmt.get("columns") or []):
            refs.append(_ref("bank file format", fmt.get("name")))

    # A policy scoped on this field's values stops matching if the field goes.
    assignments = await get_collection(COLL_POLICY_ASSIGNMENTS).find(
        {"company_id": str(company_id)}).to_list(500)
    for a in assignments:
        if code in (a.get("scope") or {}):
            refs.append(_ref("policy scope",
                             f"{a.get('policy_code')} v{a.get('version_no')}",
                             "its applicability is defined on this field"))
    return {"references": refs, "history": history}


# ─────────────────────────────────────────────────────────────
# Policy
# ─────────────────────────────────────────────────────────────
async def _policy_usage(company_id: str, code: str) -> dict:
    refs, history = [], []
    versions = await get_collection(COLL_POLICY_VERSIONS).find(
        {"company_id": str(company_id), "policy_code": str(code).upper()}).to_list(200)
    active = [v for v in versions if v.get("status") == "Active"]
    if active:
        refs.append(_ref("policy version",
                         ", ".join(f"v{v['version_no']}" for v in active),
                         "currently judging attendance or payroll"))
    superseded = [v for v in versions if v.get("status") == "Superseded"]
    if superseded:
        history.append(_ref("policy version", f"{len(superseded)} superseded version(s)",
                            "closed periods still resolve to these", blocking=False))
    used = await get_collection(COLL_PAYROLL_RECORDS).count_documents(
        {"company_id": str(company_id), "day_policy_code": str(code).upper()})
    if used:
        history.append(_ref("payroll record", f"{used} record(s)",
                            "calculated under this policy", blocking=False))
    return {"references": refs, "history": history}


# ─────────────────────────────────────────────────────────────
# The one entry point
# ─────────────────────────────────────────────────────────────
async def where_used(company_id: str, entity_type: str, code: str,
                     module: str = "employee") -> dict:
    """Everything that points at one piece of configuration.

    `can_retire` is the question §30 actually asks. It is False only when something would
    BREAK -- history never blocks, because preserving history is the reason retirement
    exists instead of deletion.
    """
    if entity_type == ENTITY_COMPONENT:
        found = await _component_usage(company_id, code)
    elif entity_type == ENTITY_FIELD:
        found = await _field_usage(company_id, code, module)
    elif entity_type == ENTITY_POLICY:
        found = await _policy_usage(company_id, code)
    else:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"'{entity_type}' has no dependency check. Known: "
                   f"{', '.join(DEPENDENCY_ENTITIES)}.")

    blocking = [r for r in found["references"] if r.get("blocking")]
    return {
        "entity_type": entity_type, "code": code,
        "references": found["references"], "history": found["history"],
        "can_retire": not blocking,
        "blocking_count": len(blocking),
        "summary": (f"{len(blocking)} thing(s) still reference this"
                    if blocking else "Nothing references this — safe to retire"),
    }


async def assert_retirable(company_id: str, entity_type: str, code: str,
                           module: str = "employee") -> None:
    """Refuse a retirement that would break something, naming what (§22 Control 3).

    Deliberately NAMES the dependants rather than saying "in use": an administrator told
    only that something is in use has to go and find what, and the system already knows.
    """
    from fastapi import HTTPException
    impact = await where_used(company_id, entity_type, code, module)
    if impact["can_retire"]:
        return
    names = ", ".join(f"{r['kind']} {r['name']}"
                      for r in impact["references"] if r.get("blocking"))
    raise HTTPException(
        status_code=409,
        detail=f"{code} cannot be retired yet — it is still used by: {names}. "
               f"Resolve those first.")
