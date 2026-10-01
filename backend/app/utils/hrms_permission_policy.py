"""HRMS Dynamic Roles & Permissions -- the per-company overrides, applied at the one gate.

`capabilities_for` (hrms_access) decides what every HRMS user may do, and every route,
service and UI hint asks it through `can()`. Its starting point is ROLE_CAPABILITIES in code
-- the DEFAULT. This module lets a company's MD / Admin change that default per capability:

  * which ROLES hold it (replacing the default list for that capability), and
  * which PEOPLE always hold it (allow) or never hold it (deny -- deny wins).

-- Why a cache ---------------------------------------------------------------------------
`capabilities_for` is synchronous and is called many times per request, so it cannot await
the database. Policies are held in memory per company and refreshed by the HRMS router gate
at most every POLICY_TTL_SECONDS (and immediately after a change on this worker). With
several workers a change is visible everywhere within that TTL.

-- What stays fixed -----------------------------------------------------------------------
  * The superadmin (HrmsRole.ADMIN) always holds everything -- the module owner can never be
    configured out of their own system.
  * LOCKED_CAPS cannot be overridden: managing permissions itself, and basic module entry.
  * Client-hiring capabilities are not part of this (client users have their own fixed set).
  * Separation-of-duty rules (nobody approves their own request, maker != checker, ...) live
    in the services and apply whatever the permissions say.
"""
import time
from typing import Dict, Optional, Set

from app.models.hrms import COLL_PERMISSION_POLICIES, Cap

POLICY_TTL_SECONDS = 20

# Never configurable: the permission to manage permissions (so the last manager cannot be
# removed), and entering the module at all (everyone's self-service rests on it).
LOCKED_CAPS = frozenset({Cap.PERMISSIONS_MANAGE, Cap.MODULE_ACCESS})

_policies: Dict[str, Dict[str, dict]] = {}   # company_id -> {cap value -> policy doc}
_loaded_at: Dict[str, float] = {}
_internal = {"id": None, "at": 0.0}


def is_editable(cap: Cap) -> bool:
    """Whether a capability can be configured on the Roles & Permissions page."""
    return cap not in LOCKED_CAPS and not cap.value.startswith("client_")


def policy_company(user: dict) -> Optional[str]:
    """Whose rules apply to this user: their own company, or -- for Sparsh's internal staff,
    who carry no company_id -- the internal company."""
    cid = (user or {}).get("company_id")
    return str(cid) if cid else _internal["id"]


async def refresh(company_id: Optional[str], *, force: bool = False) -> None:
    """(Re)load one company's rules if they are stale. Never raises."""
    if not company_id:
        return
    if not force and time.time() - _loaded_at.get(company_id, 0) < POLICY_TTL_SECONDS:
        return
    try:
        from app.db.mongodb import get_collection
        rows = await get_collection(COLL_PERMISSION_POLICIES).find(
            {"company_id": str(company_id)}).to_list(1000)
        _policies[company_id] = {r["cap"]: r for r in rows if r.get("cap")}
        _loaded_at[company_id] = time.time()
    except Exception as e:                      # pragma: no cover - never blocks a request
        print(f"[WARN] HRMS permission policies for {company_id} not loaded: {e}")


async def refresh_for_user(user: dict, *, force: bool = False) -> None:
    """Called by the HRMS router gate before every request."""
    if _internal["id"] is None or time.time() - _internal["at"] > 300:
        try:
            from app.utils.hrms_access import internal_company_id
            _internal["id"] = await internal_company_id()
        except Exception:                       # pragma: no cover
            pass
        _internal["at"] = time.time()
    await refresh(policy_company(user), force=force)


def policies_for(company_id: Optional[str]) -> Dict[str, dict]:
    return _policies.get(str(company_id), {}) if company_id else {}


def apply(user: dict, role, caps: Set[Cap]) -> Set[Cap]:
    """The company's rules on top of the default capability set. Pure, given the cache."""
    rules = policies_for(policy_company(user))
    if not rules:
        return caps
    uid = str((user or {}).get("_id") or "")
    role_value = getattr(role, "value", role)
    out = set(caps)
    for cap_value, rule in rules.items():
        try:
            cap = Cap(cap_value)
        except ValueError:
            continue
        if not is_editable(cap):
            continue
        if role_value in (rule.get("roles") or []):
            out.add(cap)
        else:
            out.discard(cap)
        if uid and uid in (rule.get("allow_users") or []):
            out.add(cap)
        if uid and uid in (rule.get("deny_users") or []):
            out.discard(cap)
    return out


def _set_cache_for_tests(company_id: str, rules: Dict[str, dict]) -> None:
    """Test hook: install a company's rules without a database."""
    _policies[str(company_id)] = dict(rules)
    _loaded_at[str(company_id)] = time.time()
