"""Company-level HRMS access control — the module's ONE authorization surface.

Mirrors app/utils/tpms_access.py in shape and defaults: HRMS is **opt-in per company**,
so a missing `hrms_enabled` flag means OFF and a company stays dark until an Admin /
Super Admin switches it on.

Three layers use this:
  • ensure_hrms_enabled()      — router guard; client-side users of a disabled company
                                 are refused. Internal staff always pass so they can
                                 administer and support across clients.
  • hrms_enabled_company_ids() — data-layer filter; disabled companies are excluded from
                                 every list, dashboard, report and aggregation.
  • can() / require_cap()      — the capability check every feature gate resolves through.

── Why a capability check and not role strings ──────────────────────────────────
The source HRMS accumulated four overlapping authorization mechanisms with three
different "admin" role sets, a helper (`canAccessHrms`) whose name no longer matched
what it did, an accepted-but-never-created "MD" role, and a granted-but-unread
permission (BACKEND_ANALYSIS §7.3, Risk #13). Its own analysis calls this the highest
risk of "a gate being added in the wrong place".

Here there is exactly one path: resolve the caller to an HrmsRole, resolve that role to a
capability set, and ask `can(user, Cap.X)`. Adding a capability is a one-line change in
models/hrms.py; there is nowhere else for a gate to hide.
"""
from typing import Optional, Set

from bson import ObjectId
from fastapi import Depends, HTTPException

from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.models.hrms import (
    CLIENT_ROLES, GOVERNANCE_TO_HRMS, INTERNAL_OWNER_ROLES, INTERNAL_STAFF_ROLES,
    ROLE_CAPABILITIES, TOGGLE_ROLES, Cap, HrmsRole,
)

MODULE_DISABLED_MESSAGE = (
    "The HRMS module is not enabled for your company. Please contact your administrator."
)
NO_ACCESS_MESSAGE = "You do not have access to the HRMS module."


# ─────────────────────────────────────────────────────────────
# Identity
# ─────────────────────────────────────────────────────────────
def is_internal_user(user: dict) -> bool:
    """Sparsh internal (staff collection) rather than a client-side user.

    Prefers the `_source_collection` stamp set by auth_controller.get_user_from_token,
    falls back to `tag`, then to the role — the same precedence auth_controller uses, so
    the two never disagree.
    """
    if not user:
        return False
    src = user.get("_source_collection")
    if src == "staff":
        return True
    if src == "learners":
        return False
    tag = user.get("tag")
    if tag == "staff":
        return True
    if tag == "learner":
        return False
    role = (user.get("role") or "").lower()
    return role in INTERNAL_OWNER_ROLES or role in INTERNAL_STAFF_ROLES


def is_client_side_user(user: dict) -> bool:
    return bool(user) and not is_internal_user(user)


def hrms_role(user: dict) -> Optional[HrmsRole]:
    """Resolve an ERP user to their HRMS role, or None if they have none.

    Internal:  superadmin              → ADMIN     (full owner, cross-company)
               admin / coach / staff   → INTERNAL  (cross-company operator + support)
    Client:    clientadmin             → MD        (top of their company's ladder)
               governance_role MD      → MD
               governance_role HR      → HR
               governance_role HOD     → MANAGER
               anything else           → EMPLOYEE  (self-service only)

    A client user with no governance_role falls through to EMPLOYEE, matching
    auth_controller.client_rank's treatment of the same case (lowest rank by default).
    """
    if not user:
        return None
    role = (user.get("role") or "").strip().lower()

    if is_internal_user(user):
        if role in INTERNAL_OWNER_ROLES:
            return HrmsRole.ADMIN
        return HrmsRole.INTERNAL

    if role == "clientadmin":
        return HrmsRole.MD
    if role in CLIENT_ROLES:
        governance = (user.get("governance_role") or "").strip().upper()
        return GOVERNANCE_TO_HRMS.get(governance, HrmsRole.EMPLOYEE)
    return None


# ─────────────────────────────────────────────────────────────
# Company module toggle
# ─────────────────────────────────────────────────────────────
async def is_hrms_enabled(company_id: str) -> bool:
    """Whether HRMS is switched on for a company. A missing flag means OFF — the module
    is opt-in per company, so nothing is exposed until it is explicitly enabled."""
    if not company_id:
        return False
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
    except Exception:
        return False
    if not company:
        return False
    return bool(company.get("hrms_enabled", False))


async def ensure_hrms_enabled(current_user: dict, company_id: str = None) -> None:
    """Raise 403 when a client-side user's company has HRMS switched off.

    Internal staff always pass: they administer HRMS across clients, and the data layer
    (hrms_enabled_company_ids) already excludes disabled companies from what they see.
    `company_id` defaults to the caller's own company, which is the case that matters —
    a client user can only ever act within it.
    """
    if is_internal_user(current_user):
        return
    target = company_id or str(current_user.get("company_id") or "")
    if not await is_hrms_enabled(target):
        raise HTTPException(status_code=403, detail=MODULE_DISABLED_MESSAGE)


async def hrms_enabled_company_ids() -> set:
    """Ids of every company with HRMS switched on — the data-layer filter. Aggregations
    intersect against this so a disabled company never appears in a list, dashboard,
    report, filter dropdown or rollup."""
    docs = await get_collection("companies").find(
        {"hrms_enabled": True}, {"_id": 1}
    ).to_list(5000)
    return {str(d["_id"]) for d in docs}


def can_toggle_module(user: dict) -> bool:
    """Only Admin / Super Admin may switch HRMS on or off for a company. Matches the
    TPMS toggle rule exactly."""
    return bool(user) and (user.get("role") or "").lower() in TOGGLE_ROLES


# ─────────────────────────────────────────────────────────────
# Capabilities
# ─────────────────────────────────────────────────────────────
def capabilities_for(user: dict) -> Set[Cap]:
    """Every capability this user holds.

    ADMIN holds everything implicitly — deliberately resolved as "all of Cap" rather than
    a maintained list, so a capability added in a later phase can never accidentally lock
    the module owner out of their own system.
    """
    role = hrms_role(user)
    if role is None:
        return set()
    if role == HrmsRole.ADMIN:
        return set(Cap)
    return set(ROLE_CAPABILITIES.get(role, set()))


def can(user: dict, capability: Cap) -> bool:
    """THE authorization question. Every HRMS gate — route, service or UI hint — resolves
    through this and nothing else."""
    return capability in capabilities_for(user)


def require_cap(capability: Cap):
    """FastAPI dependency factory enforcing one capability.

    Usage:  @router.get("/x", dependencies=[Depends(require_cap(Cap.AUDIT_READ))])
       or:  async def handler(user: dict = Depends(require_cap(Cap.AUDIT_READ)))
    Returns the user so the second form works.
    """
    async def _checker(current_user: dict = Depends(get_current_user)) -> dict:
        if not can(current_user, capability):
            raise HTTPException(status_code=403, detail=NO_ACCESS_MESSAGE)
        return current_user
    return _checker


# ─────────────────────────────────────────────────────────────
# Scoping
# ─────────────────────────────────────────────────────────────
def scope_company_id(user: dict, requested: str = None) -> Optional[str]:
    """The company a request should operate on.

    A client-side user is pinned to their own company — a requested id is ignored rather
    than honoured, so a crafted query string can never reach another tenant. Internal
    staff may target any company (or all, when `requested` is None).
    """
    if is_internal_user(user):
        return requested or None
    return str(user.get("company_id") or "") or None


def company_filter(user: dict, requested: str = None) -> dict:
    """A ready-made Mongo filter fragment applying tenant scoping.

    Returns `{}` for an internal user with no specific company (they see everything the
    data layer allows), otherwise `{"company_id": <scoped id>}`.
    """
    scoped = scope_company_id(user, requested)
    return {"company_id": scoped} if scoped else {}
