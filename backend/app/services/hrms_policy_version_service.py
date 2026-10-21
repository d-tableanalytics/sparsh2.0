"""HRMS ▸ versioned policy spine (Phase 1 FRD §21, §23, §26, §27, §28).

The FRD asks for one thing repeatedly and in several places:

    §21  "Attendance Rules / Policy ... by effective date"
    §23  "Attendance must use a versioned rule/policy engine. HR should be able to create a
          new policy version, test it and activate it from a future effective date without
          changing prior-period attendance."
    §26  "Every material Attendance or Payroll policy change creates a new policy version
          ... Where more than one policy matches an employee, a documented priority/
          specificity rule must determine the active policy."

Before this module the only thing in HRMS that actually did that was the shift master, and
it did it for shift TIMING alone. Everything else — LOP, regularisation, OD, monthly
closure, the payroll policy — was a flat dict in `hrms_settings` with no version, no
effective date and no scope, so a company could not change a rule for next month without
silently changing last month's too.

── What a policy is here ───────────────────────────────────────────────────────────────
NOT an HR policy document. `hrms_policies` / `hrms_policy_revisions` are the SOP §14
register of prose an employee reads and acknowledges. These are CONFIGURATION: the rules
attendance and payroll calculate with. Same English word, two namespaces, deliberately.

Three collections, following §28's ER extension:

    DEFINITION   what the policy IS      (code, module, category)         — one row, ever
    VERSION      what it SAYS, from when (rules, effective dates, status) — many per policy
    ASSIGNMENT   WHO it applies to       (scope + priority)               — many per version

── The documented priority rule (§26) ──────────────────────────────────────────────────
`resolve()` picks ONE version for one employee on one date, and the order is:

    1. SPECIFICITY   — how many scope dimensions the assignment names and the employee
                       matches. A rule naming "Pune AND Grade M3" beats one naming "Pune",
                       which beats the company-wide default. This is the shift master's
                       own rule (`_specificity`), generalised.
    2. PRIORITY      — the administrator's explicit tie-break, highest first. Needed
                       because two rules can be equally specific in DIFFERENT dimensions
                       ("Pune" vs "Grade M3") and nothing about the data says which wins.
    3. EFFECTIVE_FROM — the later one, so a newer rule displaces an older equal one.
    4. VERSION_NO    — the higher one. Nothing should ever reach here; it exists so the
                       answer is deterministic rather than dependent on document order,
                       which is what makes a payroll reproducible.

A version with no assignment at all is the company-wide default, at specificity 0. That is
the ordinary case — HR writes one rule for everybody — and it must not require inventing
an empty scope row to express.

── What this module does NOT do ────────────────────────────────────────────────────────
It does not decide what a rule MEANS. `rules` is opaque here: attendance reads the keys it
understands, payroll reads its own. Teaching this module the vocabulary of every caller
would make every new rule a change in two places.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_POLICY_ASSIGNMENT_SAVED, AUDIT_POLICY_VERSION_SAVED, AUDIT_POLICY_VERSION_STATUS,
    COLL_POLICY_ASSIGNMENTS, COLL_POLICY_DEFINITIONS, COLL_POLICY_VERSIONS,
    ENTITY_POLICY_VERSION, POLICY_MODULES, POLICY_RESOLVABLE_STATUSES, POLICY_SCOPE_KEYS,
    PolicyVersionStatus, is_iso_date,
)
from app.services.hrms_audit_service import audit

# A version may be edited in place only while nobody can be calculating against it.
EDITABLE_STATUSES = {PolicyVersionStatus.DRAFT.value, PolicyVersionStatus.PENDING.value}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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


def _code(value, label="A policy code") -> str:
    code = str(value or "").strip().upper()
    if not code or len(code) > 40:
        raise HTTPException(status_code=422,
                            detail=f"{label} (up to 40 characters) is required.")
    return code


def _date(value, label: str) -> str:
    text = str(value or "").strip()
    if not is_iso_date(text):
        raise HTTPException(status_code=422, detail=f"{label} must be a date (YYYY-MM-DD).")
    return text


def _clean_scope(scope: Optional[dict]) -> dict:
    """Keep only the §26 scope dimensions, each a non-empty list of strings."""
    out = {}
    for key, values in (scope or {}).items():
        if key not in POLICY_SCOPE_KEYS:
            raise HTTPException(
                status_code=422,
                detail=f"'{key}' is not a scope dimension. Use one of: "
                       f"{', '.join(sorted(POLICY_SCOPE_KEYS))}.")
        cleaned = [str(v).strip() for v in (values or []) if str(v or "").strip()]
        if cleaned:
            out[key] = cleaned
    return out


# ─────────────────────────────────────────────────────────────
# Definitions
# ─────────────────────────────────────────────────────────────
async def list_definitions(company_id: str, module: Optional[str] = None) -> list:
    query = {"company_id": str(company_id)}
    if module:
        query["module"] = module
    rows = await get_collection(COLL_POLICY_DEFINITIONS).find(query).sort("code", 1).to_list(200)
    return [_out(r) for r in rows]


async def save_definition(actor: dict, company_id: str, payload: dict) -> dict:
    code = _code(payload.get("code"))
    module = str(payload.get("module") or "attendance").strip().lower()
    if module not in POLICY_MODULES:
        raise HTTPException(status_code=422,
                            detail=f"Module must be one of: {', '.join(POLICY_MODULES)}.")
    name = str(payload.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(status_code=422, detail="A policy name is required.")
    now = datetime.now(timezone.utc)
    coll = get_collection(COLL_POLICY_DEFINITIONS)
    await coll.update_one(
        {"company_id": str(company_id), "code": code},
        {"$set": {"name": name, "module": module,
                  "category": str(payload.get("category") or "").strip() or None,
                  "description": str(payload.get("description") or "").strip() or None,
                  "updated_at": now},
         "$setOnInsert": {"company_id": str(company_id), "code": code, "created_at": now}},
        upsert=True)
    return _out(await coll.find_one({"company_id": str(company_id), "code": code}))


async def _require_definition(company_id: str, code: str) -> dict:
    doc = await get_collection(COLL_POLICY_DEFINITIONS).find_one(
        {"company_id": str(company_id), "code": code})
    if not doc:
        raise HTTPException(status_code=404, detail=f"No policy '{code}' is configured.")
    return doc


# ─────────────────────────────────────────────────────────────
# Versions
# ─────────────────────────────────────────────────────────────
async def list_versions(company_id: str, policy_code: str) -> list:
    rows = await get_collection(COLL_POLICY_VERSIONS).find(
        {"company_id": str(company_id), "policy_code": _code(policy_code)},
    ).sort("version_no", -1).to_list(200)
    out = []
    for r in rows:
        item = _out(r)
        item["assignments"] = [_out(a) for a in await get_collection(
            COLL_POLICY_ASSIGNMENTS).find(
                {"company_id": str(company_id), "policy_code": r["policy_code"],
                 "version_no": r["version_no"]}).to_list(100)]
        out.append(item)
    return out


async def save_draft(actor: dict, company_id: str, payload: dict) -> dict:
    """Create a new DRAFT version, or edit one that has not been approved yet.

    A new version always starts as Draft, never Active: §27's flow is Draft → Impact →
    Simulation → Approval → Effective Dating → Activation, and a save that went straight
    live would make every stage after the first decorative.
    """
    policy_code = _code(payload.get("policy_code"))
    await _require_definition(company_id, policy_code)
    effective_from = _date(payload.get("effective_from"), "Effective from")
    effective_to = payload.get("effective_to")
    if effective_to:
        effective_to = _date(effective_to, "Effective to")
        if effective_to < effective_from:
            raise HTTPException(status_code=422,
                                detail="Effective to is before effective from.")
    rules = payload.get("rules")
    if not isinstance(rules, dict):
        raise HTTPException(status_code=422, detail="Rules must be an object.")

    coll = get_collection(COLL_POLICY_VERSIONS)
    now = datetime.now(timezone.utc)
    version_no = payload.get("version_no")

    if version_no is not None:
        existing = await _require_version(company_id, policy_code, int(version_no))
        if existing["status"] not in EDITABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Version {version_no} is {existing['status']} and cannot be edited. "
                       f"Create a new version instead.")
        await coll.update_one(
            {"_id": existing["_id"]},
            {"$set": {"effective_from": effective_from, "effective_to": effective_to,
                      "rules": rules, "updated_at": now,
                      "change_reason": str(payload.get("change_reason") or "").strip() or None}})
        await audit(actor, AUDIT_POLICY_VERSION_SAVED, ENTITY_POLICY_VERSION,
                    f"{policy_code} v{version_no}", "edited", company_id)
        return _out(await coll.find_one({"_id": existing["_id"]}))

    latest = await coll.find_one({"company_id": str(company_id), "policy_code": policy_code},
                                 sort=[("version_no", -1)])
    version_no = int((latest or {}).get("version_no") or 0) + 1
    doc = {
        "company_id": str(company_id), "policy_code": policy_code, "version_no": version_no,
        "effective_from": effective_from, "effective_to": effective_to, "rules": rules,
        "status": PolicyVersionStatus.DRAFT.value,
        "change_reason": str(payload.get("change_reason") or "").strip() or None,
        "created_by": _actor_id(actor), "created_by_name": _actor_name(actor),
        "created_at": now, "updated_at": now,
    }
    await coll.insert_one(doc)
    await audit(actor, AUDIT_POLICY_VERSION_SAVED, ENTITY_POLICY_VERSION,
                f"{policy_code} v{version_no}", "created", company_id)
    return _out(await coll.find_one(
        {"company_id": str(company_id), "policy_code": policy_code, "version_no": version_no}))


async def _require_version(company_id: str, policy_code: str, version_no: int) -> dict:
    doc = await get_collection(COLL_POLICY_VERSIONS).find_one(
        {"company_id": str(company_id), "policy_code": policy_code,
         "version_no": int(version_no)})
    if not doc:
        raise HTTPException(status_code=404,
                            detail=f"{policy_code} has no version {version_no}.")
    return doc


# Which status may follow which. A version never goes backwards: once something could have
# been calculated against it, "un-approving" it would rewrite history rather than correct it.
_TRANSITIONS = {
    PolicyVersionStatus.DRAFT.value: {PolicyVersionStatus.PENDING.value,
                                      PolicyVersionStatus.RETIRED.value},
    PolicyVersionStatus.PENDING.value: {PolicyVersionStatus.APPROVED.value,
                                        PolicyVersionStatus.DRAFT.value,
                                        PolicyVersionStatus.RETIRED.value},
    PolicyVersionStatus.APPROVED.value: {PolicyVersionStatus.ACTIVE.value,
                                         PolicyVersionStatus.RETIRED.value},
    PolicyVersionStatus.ACTIVE.value: {PolicyVersionStatus.SUPERSEDED.value,
                                       PolicyVersionStatus.RETIRED.value},
    PolicyVersionStatus.SUPERSEDED.value: set(),
    PolicyVersionStatus.RETIRED.value: set(),
}


async def _scope_signature(company_id: str, policy_code: str, version_no: int) -> frozenset:
    """Which population a version is aimed at, as a comparable value.

    A version with no assignment is the company-wide default, and its signature is the
    empty scope -- so two unscoped versions DO displace each other, which is the ordinary
    "HR revised the rule for everybody" case.
    """
    rows = await get_collection(COLL_POLICY_ASSIGNMENTS).find(
        {"company_id": str(company_id), "policy_code": policy_code,
         "version_no": int(version_no), "active": {"$ne": False}}).to_list(200)
    if not rows:
        return frozenset({frozenset()})
    return frozenset(
        frozenset((k, tuple(sorted(str(x) for x in v)))
                  for k, v in (r.get("scope") or {}).items() if v)
        for r in rows)


# The two statuses that make a rule REAL. §27 puts impact analysis, simulation and an
# approval between a draft and these, so they are the flow's to set and nobody else's.
GOVERNING_STATUSES = frozenset({PolicyVersionStatus.APPROVED.value,
                                PolicyVersionStatus.ACTIVE.value})


async def set_status(actor: dict, company_id: str, policy_code: str, version_no: int,
                     status: str, reason: Optional[str] = None, *,
                     via_change_request: bool = False) -> dict:
    """Move a version along its lifecycle.

    Activating supersedes whatever was Active for the same policy — it does NOT delete it.
    §21: a version already used in history must survive, because a past payroll has to stay
    reproducible and the superseded row is what makes that possible.

    APPROVED AND ACTIVE ARE NOT CALLABLE DIRECTLY for a governed policy. Anyone holding
    config.approve could walk a version Draft → Pending → Approved → Active through this
    one endpoint, which skipped the impact analysis, the simulation and the change request,
    and let the person who drafted a rule approve it themselves. §27 lists seven stages
    between wanting a rule changed and the rule being live; a second door to Active made
    the other six decorative, and it was the door the UI used.

    What stays direct is everything that does not make a rule real: Draft → Pending to hand
    it over, Pending → Draft to take it back, and Retire with a reason. None of those can
    change what the resolver returns for anybody.

    `via_change_request` is the flow identifying itself (hrms_config_change_service's
    `activate`). It is keyword-only and passed from exactly one place.
    """
    policy_code = _code(policy_code)
    version = await _require_version(company_id, policy_code, version_no)
    current = version.get("status") or PolicyVersionStatus.DRAFT.value
    if status == current:
        return _out(version)
    if status not in _TRANSITIONS.get(current, set()):
        allowed = ", ".join(sorted(_TRANSITIONS.get(current, set()))) or "nothing"
        raise HTTPException(
            status_code=409,
            detail=f"A {current} version cannot become {status}. It can become: {allowed}.")
    if status in GOVERNING_STATUSES and not via_change_request:
        from app.models.hrms import CONFIG_ENTITY_POLICY_VERSION
        from app.services import hrms_config_change_service as CC
        if await CC.is_governed(company_id, CONFIG_ENTITY_POLICY_VERSION):
            raise HTTPException(
                status_code=409,
                detail=f"{policy_code} v{version_no} cannot be set to {status} directly. "
                       f"Raise a configuration change request for it, run the impact "
                       f"analysis and have somebody else approve it — then activate it "
                       f"from the Configuration Approvals screen (FRD §27).")
    if status in (PolicyVersionStatus.RETIRED.value,) and not (reason or "").strip():
        raise HTTPException(status_code=422, detail="Say why the version is being retired.")

    now = datetime.now(timezone.utc)
    updates = {"status": status, "updated_at": now, "status_reason": (reason or None)}
    if status == PolicyVersionStatus.APPROVED.value:
        updates.update({"approved_by": _actor_id(actor),
                        "approved_by_name": _actor_name(actor), "approved_on": now})
    if status == PolicyVersionStatus.ACTIVE.value:
        updates["activated_at"] = now
        # Which Active versions this one displaces: ONLY those aimed at the same population.
        #
        # Superseding every Active version of the policy was the first implementation and it
        # was wrong. Scoping exists precisely so a company-wide rule and a Pune-specific one
        # can both be live -- that is the arrangement §26 describes, and resolution already
        # has a documented rule for choosing between them. Blanket superseding would make
        # activating the Pune rule silently switch off the default for everybody else.
        #
        # Two versions aimed at the SAME population are a different matter: nothing
        # distinguishes them except effective date, so the older one really is displaced.
        mine = await _scope_signature(company_id, policy_code, int(version_no))
        rivals = await get_collection(COLL_POLICY_VERSIONS).find(
            {"company_id": str(company_id), "policy_code": policy_code,
             "status": PolicyVersionStatus.ACTIVE.value,
             "version_no": {"$ne": int(version_no)}}).to_list(500)
        for rival in rivals:
            if await _scope_signature(company_id, policy_code,
                                      int(rival["version_no"])) != mine:
                continue
            await get_collection(COLL_POLICY_VERSIONS).update_one(
                {"_id": rival["_id"]},
                {"$set": {"status": PolicyVersionStatus.SUPERSEDED.value,
                          "superseded_by": int(version_no), "updated_at": now}})
    await get_collection(COLL_POLICY_VERSIONS).update_one(
        {"_id": version["_id"]}, {"$set": updates})
    await audit(actor, AUDIT_POLICY_VERSION_STATUS, ENTITY_POLICY_VERSION,
                f"{policy_code} v{version_no}", status, company_id)
    return _out(await _require_version(company_id, policy_code, version_no))


# ─────────────────────────────────────────────────────────────
# Assignments (scope)
# ─────────────────────────────────────────────────────────────
async def assign_scope(actor: dict, company_id: str, payload: dict) -> dict:
    policy_code = _code(payload.get("policy_code"))
    version_no = int(payload.get("version_no") or 0)
    await _require_version(company_id, policy_code, version_no)
    scope = _clean_scope(payload.get("scope"))
    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "policy_code": policy_code, "version_no": version_no,
        "scope": scope, "priority": int(payload.get("priority") or 0),
        "active": bool(payload.get("active", True)),
        "created_by": _actor_id(actor), "created_at": now, "updated_at": now,
    }
    coll = get_collection(COLL_POLICY_ASSIGNMENTS)
    assignment_id = payload.get("id")
    if assignment_id:
        await coll.update_one({"_id": ObjectId(assignment_id)},
                              {"$set": {k: v for k, v in doc.items()
                                        if k not in ("created_by", "created_at")}})
    else:
        await coll.insert_one(doc)
    await audit(actor, AUDIT_POLICY_ASSIGNMENT_SAVED, ENTITY_POLICY_VERSION,
                f"{policy_code} v{version_no}",
                ", ".join(sorted(scope)) or "company-wide", company_id)
    return {"policy_code": policy_code, "version_no": version_no, "scope": scope}


async def remove_assignment(actor: dict, company_id: str, assignment_id: str) -> dict:
    await get_collection(COLL_POLICY_ASSIGNMENTS).delete_one(
        {"_id": ObjectId(assignment_id), "company_id": str(company_id)})
    return {"removed": True}


# ─────────────────────────────────────────────────────────────
# Resolution — the documented priority rule (§26)
# ─────────────────────────────────────────────────────────────
def specificity(scope: Optional[dict], context: dict) -> int:
    """-1 when the scope excludes this employee; otherwise how many dimensions matched.

    An EMPTY scope is the company-wide default and scores 0 — it matches everybody, and
    loses to anything that names a dimension. This generalises
    hrms_shift_service._specificity, with one deliberate difference: there, a shift with no
    applicability rules returns -1 ("only ever assigned explicitly"), because a shift is
    something a person is PUT ON. A policy is something that APPLIES TO them, so the
    unscoped case is a default rather than an opt-in.
    """
    scope = scope or {}
    matched = 0
    for key, values in scope.items():
        profile_key = POLICY_SCOPE_KEYS.get(key)
        if not profile_key or not values:
            continue
        if str(context.get(profile_key) or "") not in [str(v) for v in values]:
            return -1
        matched += 1
    return matched


def _in_force(version: dict, on_date: str) -> bool:
    if (version.get("effective_from") or "9999-12-31") > on_date:
        return False
    return not (version.get("effective_to") and version["effective_to"] < on_date)


async def resolve(company_id: str, policy_code: str, context: Optional[dict] = None,
                  on_date: Optional[str] = None) -> Optional[dict]:
    """The one version in force for this employee on this date, or None.

    Returns the version with its provenance attached (`policy_code`, `version_no`,
    `effective_from`, `matched_scope`, `specificity`) so the caller can STAMP what it used
    onto whatever it calculates. §25 Audit and §30 both require exactly that: "Every payroll
    result records sufficient rule/component version references to reproduce the result
    later." A resolver that returned only the rules would make that impossible.
    """
    policy_code = _code(policy_code)
    on_date = on_date or _today()
    context = context or {}

    versions = await get_collection(COLL_POLICY_VERSIONS).find(
        {"company_id": str(company_id), "policy_code": policy_code,
         "status": {"$in": list(POLICY_RESOLVABLE_STATUSES)}}).to_list(500)
    versions = [v for v in versions if _in_force(v, on_date)]
    if not versions:
        return None

    assignments = await get_collection(COLL_POLICY_ASSIGNMENTS).find(
        {"company_id": str(company_id), "policy_code": policy_code,
         "active": {"$ne": False}}).to_list(1000)
    by_version: dict = {}
    for a in assignments:
        by_version.setdefault(int(a.get("version_no") or 0), []).append(a)

    best = None   # (specificity, priority, effective_from, version_no, version, scope)
    for version in versions:
        rows = by_version.get(int(version.get("version_no") or 0))
        # No assignment at all = the company-wide default, at specificity 0.
        candidates = rows or [{"scope": {}, "priority": 0}]
        for a in candidates:
            score = specificity(a.get("scope"), context)
            if score < 0:
                continue
            key = (score, int(a.get("priority") or 0),
                   version.get("effective_from") or "", int(version.get("version_no") or 0))
            if best is None or key > best[0]:
                best = (key, version, a.get("scope") or {})

    if best is None:
        return None
    (score, priority, _eff, _vno), version, scope = best
    out = _out(version)
    out.update({"matched_scope": scope, "specificity": score, "match_priority": priority})
    return out


async def resolve_rules(company_id: str, policy_code: str, context: Optional[dict] = None,
                        on_date: Optional[str] = None, *, default: Optional[dict] = None) -> dict:
    """`resolve()` flattened to just the rules, falling back to `default`.

    This is what a calculating service wants in the ordinary case. The fallback is what
    keeps an unconfigured company behaving EXACTLY as it did before this module existed:
    no version rows means `default`, which is the caller's existing settings dict.
    """
    version = await resolve(company_id, policy_code, context, on_date)
    if not version:
        return dict(default or {})
    return {**(default or {}), **(version.get("rules") or {})}
