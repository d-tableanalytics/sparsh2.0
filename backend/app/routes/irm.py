"""
IRM — Individual Result Matrix ▸ API routes (mounted under /api).

  GET  /irm/parameters     the parameter registry (names, sources, seed weightages)
  GET  /irm/config         a company's weightage column + validity
  PUT  /irm/config         save the weightage column (must total exactly 100%)
  GET  /irm/scores         every person's IRM for a period, fully broken down
  GET  /irm/scores/{id}    one person's IRM
  POST /irm/recalculate    snapshot the current numbers into irm_scores

Scoping
-------
Internal staff (superadmin/admin) pass `company_id` and may read any company.
Client-side users are pinned to their own company: `clientadmin` sees the whole
roster, `clientuser` sees only their own row.

The weightage column is INTERNAL-STAFF-ONLY (superadmin/admin). It decides how every
person in every company is scored, so it is not a client-side setting — a clientadmin
reads the weightages on the scoreboard but cannot change them.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from app.controllers.auth_controller import get_current_user
from app.models.irm import (
    IRM_PARAMETERS, IRMConfigUpdate, TOTAL_WEIGHTAGE,
)
from app.services import irm_service

router = APIRouter(prefix="/irm", tags=["IRM"])

STAFF_ROLES = {"superadmin", "admin"}
CLIENT_ROLES = {"clientadmin", "clientuser"}
# Who may edit the weightage cells — internal Sparsh staff only. Reweighting changes how
# everyone is scored, so it is not a client-side setting: a clientadmin reads the
# weightages on the scoreboard but cannot change them.
CONFIG_ROLES = STAFF_ROLES
# Refreshing the stored snapshot recomputes from data that already exists and changes no
# configuration, so it stays available to a client's own admin too.
RECALC_ROLES = STAFF_ROLES | {"clientadmin"}


def _is_staff(user: dict) -> bool:
    return user.get("role") in STAFF_ROLES


def _resolve_company(user: dict, company_id: Optional[str]) -> str:
    """The company this request may act on. Client-side users are pinned to their own,
    whatever they passed; staff must name one explicitly."""
    if user.get("role") in CLIENT_ROLES:
        own = str(user.get("company_id") or "")
        if not own:
            raise HTTPException(status_code=400, detail="Your account is not linked to a company")
        return own
    if _is_staff(user):
        cid = str(company_id or "").strip()
        if not cid:
            raise HTTPException(status_code=400, detail="company_id is required")
        return cid
    raise HTTPException(status_code=403, detail="Not authorized to access IRM")


def _visible_person(user: dict) -> Optional[str]:
    """A clientuser only ever sees their own row; everyone else sees the roster."""
    if user.get("role") == "clientuser":
        return str(user.get("_id"))
    return None


@router.get("/parameters")
async def list_parameters(current_user: dict = Depends(get_current_user)):
    """The evaluation parameters, so the UI never hardcodes names or weightages."""
    return {
        "parameters": [{
            "code": p["code"],
            "name": p["name"],
            "description": p.get("description", ""),
            "source": p["source"],
            "default_weightage": p["default_weightage"],
        } for p in IRM_PARAMETERS],
        "required_total": TOTAL_WEIGHTAGE,
    }


@router.get("/config")
async def read_config(
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    cid = _resolve_company(current_user, company_id)
    config = await irm_service.get_config(cid)
    config["can_edit"] = current_user.get("role") in CONFIG_ROLES
    return config


@router.put("/config")
async def update_config(
    payload: IRMConfigUpdate,
    company_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Save the weightages. IRMConfigUpdate rejects anything that doesn't total 100%,
    so a partial column can never be persisted.

    Nothing needs recalculating afterwards: scores are derived from this config on every
    read, so the next /irm/scores call already uses the new numbers. The snapshot in
    `irm_scores` is refreshed here too, keeping stored history consistent with the change.
    """
    if current_user.get("role") not in CONFIG_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only a Super Admin or Admin can edit IRM weightages",
        )
    cid = _resolve_company(current_user, company_id)

    try:
        config = await irm_service.save_weightages(cid, payload.as_map(), current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Best-effort snapshot refresh — a storage hiccup must not fail the save itself.
    try:
        await irm_service.recalculate_and_store(cid)
    except Exception:
        pass

    config["can_edit"] = True
    config["message"] = "Weightages saved. IRM scores now use the updated values."
    return config


@router.get("/scores")
async def read_scores(
    company_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None, description="YYYY-MM; defaults to the current month"),
    current_user: dict = Depends(get_current_user),
):
    cid = _resolve_company(current_user, company_id)
    try:
        return await irm_service.compute_company_irm(cid, period, _visible_person(current_user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/scores/{person_id}")
async def read_person_score(
    person_id: str,
    company_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    cid = _resolve_company(current_user, company_id)
    restricted = _visible_person(current_user)
    if restricted and restricted != person_id:
        raise HTTPException(status_code=403, detail="You can only view your own IRM")

    try:
        result = await irm_service.compute_company_irm(cid, period, person_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not result["rows"]:
        raise HTTPException(status_code=404, detail="No such person in this company")
    return {**result, "person": result["rows"][0]}


@router.post("/recalculate")
async def recalculate(
    company_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Recompute and snapshot. Scores are always live on read, so this exists to refresh
    the stored history — e.g. after a month's tasks or ratings have settled."""
    if current_user.get("role") not in RECALC_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to recalculate IRM")
    cid = _resolve_company(current_user, company_id)
    try:
        return await irm_service.recalculate_and_store(cid, period)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
