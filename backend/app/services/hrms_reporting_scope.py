"""HRMS ▸ reporting-hierarchy data scope — WHO may a manager see and act on?

The one rule behind the Employee Directory, Employee 360 / profile, and every manager
report and action (leave, attendance, movements, PIP, …):

  * Company-wide visibility is for authorised HR / Admin roles only — ADMIN, HR, MD and
    Sparsh's internal HRMS operators — plus the payroll operators (FINANCE, PAYROLL_MAKER,
    PAYROLL_CHECKER), who process pay for the whole company and already see everyone's
    payroll (utils/hrms_access.PAYROLL_DATA_ROLES).
  * Everyone else — a MANAGER (HOD) above all — sees themselves and their DIRECT REPORTS:
    the people whose reporting manager they are (`reporting_manager` on the user record,
    kept in step with the profile's `reporting_manager_id`).
  * A wider hierarchy scope (reports of reports, all the way down) is NOT the default. It
    applies only where the company has explicitly approved it: `hrms_manager_scope:
    "hierarchy"` on the company document. Department membership never widens the scope —
    sharing a department is not a reporting line.

Every gap fails CLOSED: no reports → only themselves, never "everyone".
"""
from typing import List, Optional, Set

from bson import ObjectId
from bson.errors import InvalidId

from app.db.mongodb import get_collection
from app.models.hrms import HrmsRole
from app.utils.hrms_access import hrms_role

USER_COLLECTIONS = ("learners", "staff")

# Roles whose directory / profile view is the whole company.
COMPANY_WIDE_ROLES = frozenset({
    HrmsRole.ADMIN, HrmsRole.INTERNAL, HrmsRole.HR, HrmsRole.MD,
    HrmsRole.FINANCE, HrmsRole.PAYROLL_MAKER, HrmsRole.PAYROLL_CHECKER,
})

SCOPE_DIRECT = "direct"
SCOPE_HIERARCHY = "hierarchy"
_MAX_DEPTH = 15          # a reporting chain longer than this is a data loop, not an org chart


def sees_company_directory(actor: dict) -> bool:
    """May this caller see EVERY employee of the company (directory, profiles, 360)?"""
    return hrms_role(actor) in COMPANY_WIDE_ROLES


async def manager_scope_mode(company_id: Optional[str]) -> str:
    """'direct' (default) or 'hierarchy' — only an explicit company approval widens it."""
    if not company_id:
        return SCOPE_DIRECT
    try:
        company = await get_collection("companies").find_one(
            {"_id": ObjectId(str(company_id))}, {"hrms_manager_scope": 1})
    except (InvalidId, TypeError):
        return SCOPE_DIRECT
    mode = str((company or {}).get("hrms_manager_scope") or "").strip().lower()
    return SCOPE_HIERARCHY if mode == SCOPE_HIERARCHY else SCOPE_DIRECT


async def _direct_reports_of(manager_ids: List[str]) -> List[str]:
    out = []
    for coll in USER_COLLECTIONS:
        rows = await get_collection(coll).find(
            {"reporting_manager": {"$in": manager_ids}}, {"_id": 1}).to_list(5000)
        out.extend(str(r["_id"]) for r in rows)
    return out


async def team_user_ids(actor: dict, company_id: Optional[str]) -> List[str]:
    """The user ids of the people `actor` manages — direct reports, or the whole downline
    where the company approved hierarchy scope. Never includes the actor."""
    actor_id = str(actor.get("_id") or "")
    if not actor_id:
        return []
    deep = (await manager_scope_mode(company_id)) == SCOPE_HIERARCHY
    seen: Set[str] = {actor_id}
    team: List[str] = []
    frontier = [actor_id]
    for _ in range(_MAX_DEPTH if deep else 1):
        nxt = [u for u in await _direct_reports_of(frontier) if u not in seen]
        if not nxt:
            break
        seen.update(nxt)
        team.extend(nxt)
        frontier = nxt
    return team


async def visible_user_ids(actor: dict, company_id: Optional[str]) -> List[str]:
    """Self + team: the user ids a non-company-wide caller may see in the directory."""
    actor_id = str(actor.get("_id") or "")
    return ([actor_id] if actor_id else []) + await team_user_ids(actor, company_id)


def to_oids(ids) -> list:
    out = []
    for i in ids:
        try:
            out.append(ObjectId(str(i)))
        except (InvalidId, TypeError):
            continue
    return out
