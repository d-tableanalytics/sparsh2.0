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
    CONFIG_ENTITY_POLICY_VERSION, CONFIG_ENTITY_TYPES, ENTITY_CONFIG_CHANGE,
    ConfigChangeStatus, PolicyVersionStatus, is_iso_date,
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
    if version.get("status") == PolicyVersionStatus.DRAFT.value:
        await PV.set_status(actor, company_id, code, version_no,
                            PolicyVersionStatus.PENDING.value)
        version = await _policy_load(company_id, request)
    if version.get("status") == PolicyVersionStatus.PENDING.value:
        await PV.set_status(actor, company_id, code, version_no,
                            PolicyVersionStatus.APPROVED.value)
    return await PV.set_status(actor, company_id, code, version_no,
                               PolicyVersionStatus.ACTIVE.value)


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


ENTITY_HANDLERS = {
    CONFIG_ENTITY_POLICY_VERSION: {
        "load": _policy_load,
        "impact": _policy_impact,
        "activate": _policy_activate,
        "describe": _policy_describe,
    },
}


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
    if version_no is None:
        raise HTTPException(status_code=422, detail="Name which version is being changed.")

    draft = {"entity_type": entity_type, "entity_code": entity_code,
             "version_no": int(version_no)}
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
