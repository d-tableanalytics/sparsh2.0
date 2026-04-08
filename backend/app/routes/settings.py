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
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("settings", {}).get("update", False) # Fallback to settings node if it exists, or superadmin
    
    if current_user.get("role") != "superadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Only authorized personnel can update backdate settings")
    
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
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("templates", {}).get("read", False)
    
    if current_user.get("role") not in ["superadmin", "clientadmin"] and not can_read:
        raise HTTPException(status_code=403, detail="Unauthorized")

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
    # Permission check: superadmin can create for anyone, clientadmin only for their company, staff with perm
    permissions = current_user.get("permissions", {})
    can_create = permissions.get("templates", {}).get("create", False)
    
    role = current_user.get("role")
    if role not in ["superadmin", "clientadmin"] and not can_create:
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
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("templates", {}).get("update", False)
    
    role = current_user.get("role")
    if role == "clientadmin" and existing.get("company_id") != current_user.get("company_id"):
        raise HTTPException(status_code=403, detail="Unauthorized")
    if role != "superadmin" and role != "clientadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Unauthorized")

    update_data = {k: v for k, v in template.items() if k not in ["_id", "created_at", "created_by"]}
    update_data["updated_at"] = datetime.utcnow()
    
    await col.update_one({"_id": ObjectId(template_id)}, {"$set": update_data})
    return {"message": "Template updated"}

@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, current_user: dict = Depends(get_current_user)):
    col = get_collection("notification_templates")
    existing = await col.find_one({"_id": ObjectId(template_id)})
    
    permissions = current_user.get("permissions", {})
    can_delete = permissions.get("templates", {}).get("delete", False)
    
    role = current_user.get("role")
    if role == "clientadmin" and existing.get("company_id") != current_user.get("company_id"):
        raise HTTPException(status_code=403, detail="Unauthorized")
    if role != "superadmin" and role != "clientadmin" and not can_delete:
        raise HTTPException(status_code=403, detail="Unauthorized")

    await col.delete_one({"_id": ObjectId(template_id)})
    return {"message": "Template deleted"}

@router.post("/initialize-templates")
async def initialize_default_templates(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
         raise HTTPException(status_code=403, detail="Unauthorized")
    
    col = get_collection("notification_templates")
    
    defaults = [
        {
            "name": "Task Created", "slug": "task_created_email", "channel": "email",
            "subject": "New Task Assigned: {{task_name}}",
            "body": "Hello {{assigned_user}},\n\nA new task '{{task_name}}' has been assigned to you by {{assigned_by}}.\nTopic: {{topic}}\nDeadline: {{deadline}}",
            "scope": "staff", "is_active": True
        },
        {
            "name": "Task Updated", "slug": "task_updated_email", "channel": "email",
            "subject": "Update on Task: {{task_name}}",
            "body": "Hello {{assigned_user}},\n\nThe task '{{task_name}}' has been updated.\nNew Status: {{task_status}}\nPlease check your dashboard for details.",
            "scope": "staff", "is_active": True
        },
        {
            "name": "Task Deleted", "slug": "task_deleted_email", "channel": "email",
            "subject": "Task Cancelled: {{task_name}}",
            "body": "Hello {{assigned_user}},\n\nThe task '{{task_name}}' has been removed from your list.",
            "scope": "staff", "is_active": True
        },
        {
            "name": "Session Scheduled", "slug": "event_created_email", "channel": "email",
            "subject": "New Session Scheduled: {{event_title}}",
            "body": "Hello {{name}},\n\nA new training session '{{event_title}}' has been scheduled.\nDate: {{date}}\nTime: {{time}}\nLink: {{meeting_link}}",
            "scope": "staff", "is_active": True
        },
        {
            "name": "Session Rescheduled", "slug": "event_updated_email", "channel": "email",
            "subject": "Session Rescheduled: {{event_title}}",
            "body": "Hello {{name}},\n\nThe session '{{event_title}}' has been moved to a new time.\nNew Date: {{date}}\nNew Time: {{time}}",
            "scope": "staff", "is_active": True
        },
        {
            "name": "Session Cancelled", "slug": "event_deleted_email", "channel": "email",
            "subject": "Session Cancelled: {{event_title}}",
            "body": "Hello {{name}},\n\nThe session '{{event_title}}' scheduled for {{date}} has been cancelled.",
            "scope": "staff", "is_active": True
        },
        {
            "name": "User Created", "slug": "user_creation_email", "channel": "email",
            "subject": "Welcome to Sparsh 2.0",
            "body": "Hello {{name}},\n\nYour account has been created.\nRole: {{new_role}}\nLogin here: {{login_url}}\nTemporary Password: {{password}}",
            "scope": "staff", "is_active": True
        },
        {
            "name": "Profile Updated", "slug": "user_edit_email", "channel": "email",
            "subject": "Your Account Information Updated",
            "body": "Hello {{name}},\n\nYour profile details were updated by {{updated_by}}.\nIf you did not authorize this, please contact support.",
            "scope": "staff", "is_active": True
        },
        {
            "name": "User Access Removed", "slug": "user_deleted_email", "channel": "email",
            "subject": "Account Deactivation Notice",
            "body": "Hello {{name}},\n\nYour access to the platform has been revoked.",
            "scope": "staff", "is_active": True
        },
        {
            "name": "Event Reminder", "slug": "reminder_email", "channel": "email",
            "subject": "Upcoming: {{title}} in {{reminder_time}}",
            "body": "Hello {{name}},\n\nThis is a friendly reminder for '{{title}}' starting at {{event_time}}.\nLink: {{meeting_url}}",
            "scope": "staff", "is_active": True
        },
        {
            "name": "New Company Registered", "slug": "company_registration_email", "channel": "email",
            "subject": "Welcome, {{company_name}}!",
            "body": "Hello {{name}},\n\n{{company_name}} is now live on our platform.\nYou can manage your team and learners at: {{login_url}}",
            "scope": "staff", "is_active": True
        }
    ]

    for d in defaults:
        d["created_by"] = str(current_user["_id"])
        d["created_at"] = datetime.utcnow()
        # Check if already exists to avoid duplicates
        exists = await col.find_one({"slug": d["slug"], "scope": d["scope"], "company_id": None})
        if not exists:
            await col.insert_one(d)

    return {"message": "Default infrastructure initialized successfully"}


