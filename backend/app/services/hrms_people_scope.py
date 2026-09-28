"""HRMS ▸ whose record is this, and may the caller act on it?

One place for the three questions every people-process service keeps asking — Movements,
Absconding and Retirement alerts, and Discipline's conflict-of-interest rule:

  * the caller's OWN employee code (their linked profile),
  * the codes of the team they manage (people whose reporting manager they are),
  * a person's display name (identity lives on the user document, not the profile).

The data-scope rule is the one utils/hrms_access already states: HR / MD / owner see and act
on everyone (`sees_all_people`); a MANAGER on their own team; nobody on themselves.
"""
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import COLL_EMPLOYEE_PROFILES, HrmsRole
from app.utils.hrms_access import hrms_role, sees_all_people


async def own_code(actor: dict, company_id: str) -> Optional[str]:
    from app.services.hrms_leave_service import _own_employee_code
    return await _own_employee_code(actor, company_id)


async def team_codes(actor: dict, company_id: str) -> list:
    from app.services.hrms_leave_service import _team_employee_codes
    return await _team_employee_codes(actor, company_id)


async def name_of(profile: Optional[dict]) -> Optional[str]:
    if not profile:
        return None
    from app.services.hrms_payroll_service import _employee_names, _name_of
    return _name_of(profile, await _employee_names([profile]))


async def name_for_code(company_id: str, employee_code: str) -> Optional[str]:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    return await name_of(profile)


async def assert_may_act_for(actor: dict, company_id: str, employee_code: str, what: str) -> None:
    """HR / MD / owner: anyone but themselves. A manager: their own team. Nobody: themselves."""
    if (await own_code(actor, company_id)) == employee_code:
        raise HTTPException(status_code=403, detail=f"You cannot {what} for yourself.")
    if sees_all_people(actor):
        return
    if hrms_role(actor) == HrmsRole.MANAGER and employee_code in await team_codes(actor, company_id):
        return
    raise HTTPException(status_code=403,
                        detail=f"You can {what} only for people in your own team.")


async def scope_filter(actor: dict, company_id: str, *, initiated_field: Optional[str] = None) -> Optional[dict]:
    """A Mongo filter limiting a list to what the caller may see, or None for everything.

    HR / MD / owner: everything. A manager: their team, plus (if `initiated_field` is given)
    the records they raised themselves. Anyone else: nothing beyond their own.
    """
    if sees_all_people(actor):
        return None
    own = await own_code(actor, company_id)
    codes = [own] if own else []
    if hrms_role(actor) == HrmsRole.MANAGER:
        codes += await team_codes(actor, company_id)
    ors = [{"employee_code": {"$in": codes or ["__none__"]}}]
    if initiated_field:
        ors.append({initiated_field: str(actor.get("_id") or "")})
    return {"$or": ors}
