"""The master department list — HRMS ▸ Departments (`hrms_departments`, one list per company).

Every module that records "which department a person belongs to" uses this list, so a
department created or renamed there is the department everywhere. On a user it is stored as
`department_id` (the master record) plus `department_name` (a readable snapshot).

NOTE: the older `department` field on users holds a ROLE-like value (HOD, MD, Manager,
Implementor, EA, HR, Other) that TPMS still reads to tell HODs and MDs apart. It is left
exactly as it was; the master department lives in the two fields above.
"""
from typing import List, Optional, Tuple

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection

COLL = "hrms_departments"


async def resolve_company_ref(company_id: str) -> str:
    """`internal` → the in-house company (Sparsh Magic's own staff carry no company_id)."""
    if str(company_id).lower() == "internal":
        from app.utils.hrms_access import internal_company_id
        cid = await internal_company_id()
        if not cid:
            raise HTTPException(status_code=400, detail="The internal company is not set up yet.")
        return cid
    return str(company_id)


async def company_departments(company_id: str) -> List[dict]:
    """Active departments of a company, A→Z: [{"id", "name"}]."""
    rows = await get_collection(COLL).find(
        {"company_id": str(company_id), "active": {"$ne": False}}, {"name": 1}).to_list(500)
    return sorted(({"id": str(r["_id"]), "name": r.get("name") or ""} for r in rows),
                  key=lambda d: d["name"].lower())


async def resolve_department(company_id: str, department_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(id, name) for a department of this company; (None, None) when none was chosen.
    A department from another company — or one that does not exist — is refused."""
    if not department_id:
        return None, None
    try:
        oid = ObjectId(str(department_id))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=422, detail="That department does not exist.")
    doc = await get_collection(COLL).find_one({"_id": oid, "company_id": str(company_id)}, {"name": 1})
    if not doc:
        raise HTTPException(status_code=422,
                            detail="That department does not belong to this company's department list.")
    return str(doc["_id"]), doc.get("name") or ""


# ─── Designations: the same idea, from HRMS ▸ Designations (`hrms_designations`) ───
# On a user it is stored as `designation_id` (the master record) plus `designation` (its name,
# the field every older screen already reads).
DESIG_COLL = "hrms_designations"


async def company_designations(company_id: str) -> List[dict]:
    """Active designations of a company, A→Z: [{"id", "name"}]."""
    rows = await get_collection(DESIG_COLL).find(
        {"company_id": str(company_id), "active": {"$ne": False}}, {"name": 1}).to_list(500)
    return sorted(({"id": str(r["_id"]), "name": r.get("name") or ""} for r in rows),
                  key=lambda d: d["name"].lower())


async def resolve_designation(company_id: str, designation_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(id, name) for a designation of this company; (None, None) when none was chosen."""
    if not designation_id:
        return None, None
    try:
        oid = ObjectId(str(designation_id))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=422, detail="That designation does not exist.")
    doc = await get_collection(DESIG_COLL).find_one({"_id": oid, "company_id": str(company_id)}, {"name": 1})
    if not doc:
        raise HTTPException(status_code=422,
                            detail="That designation does not belong to this company's designation list.")
    return str(doc["_id"]), doc.get("name") or ""


async def sync_user_org_field(company_id: str, user_id: str, field: str, value) -> None:
    """Write an HRMS department/designation change through to the user record, so the user
    record stays the one universal source (Staff / member forms set it; HRMS transfers and
    promotions keep it current). Any other field is ignored."""
    if field == "department_id":
        _id, name = await _safe(resolve_department, company_id, value)
        update = {"department_id": _id, "department_name": name}
    elif field == "designation_id":
        _id, name = await _safe(resolve_designation, company_id, value)
        update = {"designation_id": _id}
        if name is not None:
            update["designation"] = name
    else:
        return
    try:
        oid = ObjectId(str(user_id))
    except (InvalidId, TypeError):
        return
    for coll in ("staff", "learners"):
        result = await get_collection(coll).update_one({"_id": oid}, {"$set": update})
        if getattr(result, "matched_count", 0):
            return


async def _safe(resolver, company_id, value):
    """A write-through must never fail the HRMS write that triggered it."""
    try:
        return await resolver(company_id, value)
    except HTTPException:
        return None, None


async def department_by_name(company_id: str, name: str) -> Tuple[Optional[str], Optional[str]]:
    """Look a master department up by name (case-insensitive) — for Excel imports."""
    wanted = (name or "").strip().lower()
    if not wanted:
        return None, None
    for d in await company_departments(company_id):
        if d["name"].strip().lower() == wanted:
            return d["id"], d["name"]
    return None, None
