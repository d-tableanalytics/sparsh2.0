from fastapi import APIRouter, Depends, HTTPException, Body
from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user
from app.models.system_settings import SystemSettings, SystemSettingsUpdate
from app.models.notification import NotificationTemplate
from datetime import datetime
from bson import ObjectId
from typing import List, Optional

router = APIRouter(prefix="/settings", tags=["Settings"])

@router.get("/backdate-control", response_model=dict)
async def get_backdate_settings(current_user: dict = Depends(get_current_user)):
    # Standard users can read settings to check permission if needed, but validation is backend-side
    col = get_collection("system_settings")
    settings = await col.find_one({"setting_name": "backdate_control"})
    if not settings:
        default = SystemSettings().model_dump()
        result = await col.insert_one(default)
        default["_id"] = str(result.inserted_id)
        return default
    
    settings["_id"] = str(settings["_id"])
    return settings

@router.put("/backdate-control")
async def update_backdate_settings(updates: SystemSettingsUpdate = Body(...), current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Only superadmin can update backdate settings")
    
    col = get_collection("system_settings")
    print(f"DEBUG: RECEIVED UPDATES: {updates.model_dump()}")
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}

    update_data["updated_by"] = str(current_user["_id"])
    update_data["updated_at"] = datetime.utcnow()
    
    await col.update_one(
        {"setting_name": "backdate_control"},
        {"$set": update_data},
        upsert=True
    )
    return {"message": "Backdate settings updated successfully"}

@router.get("/templates", response_model=List[dict])
async def get_templates(scope: Optional[str] = None, company_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    col = get_collection("notification_templates")
    query = {}
    if scope: query["scope"] = scope
    if company_id: query["company_id"] = company_id
    
    # Client Admins should only see their company templates
    if current_user.get("role") == "clientadmin":
        query["scope"] = "company"
        query["company_id"] = current_user.get("company_id")
        
    cursor = col.find(query)
    templates = await cursor.to_list(length=200)
    for t in templates: t["_id"] = str(t["_id"])
    return templates

@router.post("/templates")
async def create_template(template: dict = Body(...), current_user: dict = Depends(get_current_user)):
    # Permission check: superadmin can create for anyone, clientadmin only for their company
    role = current_user.get("role")
    if role not in ["superadmin", "clientadmin"]:
         raise HTTPException(status_code=403, detail="Unauthorized")
    
    col = get_collection("notification_templates")
    new_template = {
        **template,
        "created_by": str(current_user["_id"]),
        "created_at": datetime.utcnow(),
        "is_active": True
    }
    
    if role == "clientadmin":
        new_template["scope"] = "company"
        new_template["company_id"] = current_user.get("company_id")
    
    result = await col.insert_one(new_template)
    return {"id": str(result.inserted_id), "message": "Template created"}

@router.put("/templates/{template_id}")
async def update_template(template_id: str, template: dict = Body(...), current_user: dict = Depends(get_current_user)):
    col = get_collection("notification_templates")
    existing = await col.find_one({"_id": ObjectId(template_id)})
    if not existing: raise HTTPException(status_code=404, detail="Not found")

    # Authorization
    role = current_user.get("role")
    if role == "clientadmin" and existing.get("company_id") != current_user.get("company_id"):
        raise HTTPException(status_code=403, detail="Unauthorized")
    if role != "superadmin" and role != "clientadmin":
        raise HTTPException(status_code=403, detail="Unauthorized")

    update_data = {k: v for k, v in template.items() if k not in ["_id", "created_at", "created_by"]}
    update_data["updated_at"] = datetime.utcnow()
    
    await col.update_one({"_id": ObjectId(template_id)}, {"$set": update_data})
    return {"message": "Template updated"}

@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, current_user: dict = Depends(get_current_user)):
    col = get_collection("notification_templates")
    existing = await col.find_one({"_id": ObjectId(template_id)})
    
    role = current_user.get("role")
    if role == "clientadmin" and existing.get("company_id") != current_user.get("company_id"):
        raise HTTPException(status_code=403, detail="Unauthorized")
    if role != "superadmin" and role != "clientadmin":
        raise HTTPException(status_code=403, detail="Unauthorized")

    await col.delete_one({"_id": ObjectId(template_id)})
    return {"message": "Template deleted"}


