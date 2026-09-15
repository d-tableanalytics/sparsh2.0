"""HRMS ▸ User / Role / Permission Administration (SM-HR-051).

See the "Phase ACCESS-1" header comment in models/hrms.py for what this phase builds
(governance_role assignment, the read-only role/capability matrix) versus what it
deliberately reuses (account disable, already PATCH /users/{id}/status on the base
platform) versus what it defers as a workshop item (field/tab permission, configurable
data scope, delegation).
"""
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    ASSIGNABLE_GOVERNANCE_ROLES, AUDIT_GOVERNANCE_ROLE_CHANGED, CLIENT_ROLES,
    ENTITY_ACCESS, ROLE_CAPABILITIES, Cap, HrmsRole,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_employee_service import USER_COLLECTIONS, get_employee


def _oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid user id.")


async def _find_user(user_id: str):
    oid = _oid(user_id)
    for coll in USER_COLLECTIONS:
        doc = await get_collection(coll).find_one({"_id": oid})
        if doc:
            return doc, coll
    return None, None


def get_role_matrix() -> dict:
    """The role -> capability table every gate in this module resolves through, read-only.

    Served from ROLE_CAPABILITIES itself (never a hand-maintained copy) so "review access"
    can never show something the gates do not actually enforce. ADMIN is synthesized as
    every capability that exists, matching the implicit-owner rule documented on the dict
    itself in models/hrms.py — it is never listed there explicitly.
    """
    matrix = {
        role.value: sorted(cap.value for cap in caps)
        for role, caps in ROLE_CAPABILITIES.items()
    }
    matrix[HrmsRole.ADMIN.value] = sorted(cap.value for cap in Cap)
    return {"roles": matrix}


async def set_governance_role(actor: dict, user_id: str, company_id: str,
                              governance_role: Optional[str]) -> dict:
    """The BA doc's "assign" action — the one write path onto the field `hrms_role()` has
    always read for a client-side user (HOD/HR/FINANCE/MD -> MANAGER/HR/FINANCE/MD)."""
    normalized = (governance_role or "").strip().upper() or None
    if normalized and normalized not in ASSIGNABLE_GOVERNANCE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"governance_role must be one of {sorted(ASSIGNABLE_GOVERNANCE_ROLES)} or empty.")

    user, coll = await _find_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if str(user.get("company_id") or "") != str(company_id):
        # Same "404, not 403" reasoning as hrms_employee_service.get_employee — a refusal
        # must not confirm that a given id exists in another tenant.
        raise HTTPException(status_code=404, detail="User not found.")

    role = (user.get("role") or "").strip().lower()
    if role not in CLIENT_ROLES:
        raise HTTPException(
            status_code=400,
            detail="governance_role only applies to client-side users.")
    if role == "clientadmin":
        raise HTTPException(
            status_code=400,
            detail="This user already resolves to MD via their account role — "
                   "governance_role has no effect for a clientadmin.")

    previous = user.get("governance_role")
    await get_collection(coll).update_one(
        {"_id": user["_id"]}, {"$set": {"governance_role": normalized}})

    await audit(
        actor, AUDIT_GOVERNANCE_ROLE_CHANGED, ENTITY_ACCESS, user_id,
        detail=f"{previous or 'none'} -> {normalized or 'none'}", company_id=company_id)

    return await get_employee(actor, user_id, company_id=company_id)
