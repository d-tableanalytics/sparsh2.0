from fastapi import APIRouter, Depends, HTTPException, status
from app.models.orm import ORMCreateRequest
from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.utils.orm_utils import sync_orm_to_calendar
from bson import ObjectId
from datetime import datetime
from typing import List

router = APIRouter(prefix="/orm", tags=["ORM"])

# Fields that vary month-to-month. Structure (names, weightages, audit config,
# assignedUsers, frequency, etc.) is shared and always read from ORM_Configs;
# only these per-subsection values are partitioned by month in ORM_Monthly.
MONTHLY_VALUE_FIELDS = [
    "target", "achievement", "unitName", "remarks",
    "googleSheetLink", "googleFormLink", "surveyDoerName", "surveyDoerEmail",
    "auditChecklist", "teamEngagementChecklist", "budgetAdherenceChecklist",
]


def _current_period() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def _overlay_values(parameters, values, fields=None):
    """Overlay month-specific values from `values` (a {subsection_id: {...}} map)
    onto the shared structure in-place."""
    fields = fields or MONTHLY_VALUE_FIELDS
    for p in parameters:
        for s in p.get("subsections", []):
            mv = values.get(s.get("id"))
            if not mv:
                continue
            for f in fields:
                if f in mv and mv[f] is not None:
                    s[f] = mv[f]


def _reset_achievements(parameters):
    for p in parameters:
        for s in p.get("subsections", []):
            s["achievement"] = 0

def _extract_monthly_values(parameters):
    """Pull the per-month value fields out of a full parameters list into a
    {subsection_id: {field: value}} map for storage in ORM_Monthly."""
    values = {}
    for p in parameters:
        for s in p.get("subsections", []):
            sid = s.get("id")
            if sid is None:
                continue
            values[sid] = {f: s.get(f) for f in MONTHLY_VALUE_FIELDS if f in s}
    return values


async def _upsert_monthly(company_id: str, period: str, parameters):
    monthly_col = get_collection("ORM_Monthly")
    await monthly_col.update_one(
        {"company_id": company_id, "period": period},
        {
            "$set": {
                "company_id": company_id,
                "period": period,
                "values": _extract_monthly_values(parameters),
                "updated_at": datetime.utcnow(),
            },
            "$setOnInsert": {"created_at": datetime.utcnow()},
        },
        upsert=True,
    )


@router.post("")
async def save_orm(request: ORMCreateRequest, current_user: dict = Depends(get_current_user)):
    # Only clientadmin or admin can save the ORM configuration for their company
    if current_user.get("role") not in ["superadmin", "admin", "clientadmin"]:
        raise HTTPException(status_code=403, detail="Not authorized to design ORM")

    # Only the current month is editable; past months are read-only history.
    period = request.period or _current_period()
    if period != _current_period():
        raise HTTPException(status_code=403, detail="Past months are read-only and cannot be modified")

    col = get_collection("ORM_Configs")

    orm_data = request.model_dump()
    orm_data.pop("period", None)
    orm_data["updated_at"] = datetime.utcnow()

    # Check if ORM already exists for this company
    existing = await col.find_one({"company_id": request.company_id})

    if existing:
        await col.update_one(
            {"company_id": request.company_id},
            {"$set": orm_data}
        )
    else:
        orm_data["created_at"] = datetime.utcnow()
        await col.insert_one(orm_data)

    # Persist this month's values separately so each month keeps its own snapshot.
    await _upsert_monthly(request.company_id, period, orm_data["parameters"])

    # Sync to calendar
    await sync_orm_to_calendar(request.company_id, orm_data["parameters"], str(current_user["_id"]))
    return {"message": "ORM saved successfully", "period": period}

@router.get("/{company_id}")
async def get_orm(company_id: str, period: str = None, current_user: dict = Depends(get_current_user)):
    col = get_collection("ORM_Configs")
    orm = await col.find_one({"company_id": company_id})

    if not orm:
        return {"parameters": [], "message": "No ORM found"}

    orm["_id"] = str(orm["_id"])

    period = period or _current_period()
    current_period = _current_period()
    parameters = orm.get("parameters", [])

    monthly_col = get_collection("ORM_Monthly")
    monthly = await monthly_col.find_one({"company_id": company_id, "period": period})

    if monthly:
        # This month already has its own saved snapshot.
        _overlay_values(parameters, monthly.get("values", {}))
        orm["has_month_data"] = True
    else:
        # No snapshot yet for this period. Carry forward the most recent prior
        # month's values (with achievements cleared), else fall back to the
        # config's embedded values as-is (legacy / first month).
        prior = await monthly_col.find_one(
            {"company_id": company_id, "period": {"$lt": period}},
            sort=[("period", -1)],
        )
        if prior:
            _overlay_values(parameters, prior.get("values", {}))
            _reset_achievements(parameters)
        orm["has_month_data"] = False

    orm["period"] = period
    orm["is_current_period"] = period == current_period
    orm["parameters"] = parameters
    return orm
