from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user
from bson import ObjectId
from datetime import datetime
from pydantic import BaseModel, Field

router = APIRouter(prefix="/notifications", tags=["Notifications"])

class NotificationResponse(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    title: str
    message: str
    type: str
    is_read: bool
    created_at: datetime
    meta: Optional[dict] = {}

    class Config:
        populate_by_name = True

@router.get("/", response_model=List[dict])
async def get_notifications(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    notifications = await get_collection("in_app_notifications").find(
        {"user_id": user_id}
    ).sort("created_at", -1).to_list(100)
    
    for n in notifications:
        n["_id"] = str(n["_id"])
    return notifications

@router.get("/unread-count")
async def get_unread_count(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    count = await get_collection("in_app_notifications").count_documents(
        {"user_id": user_id, "is_read": False}
    )
    return {"count": count}

@router.put("/{notification_id}/read")
async def mark_as_read(notification_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    result = await get_collection("in_app_notifications").update_one(
        {"_id": ObjectId(notification_id), "user_id": user_id},
        {"$set": {"is_read": True}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"message": "Marked as read"}

@router.put("/mark-all-read")
async def mark_all_read(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    await get_collection("in_app_notifications").update_many(
        {"user_id": user_id, "is_read": False},
        {"$set": {"is_read": True}}
    )
    return {"message": "All notifications marked as read"}

@router.delete("/{notification_id}")
async def delete_notification(notification_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    result = await get_collection("in_app_notifications").delete_one(
        {"_id": ObjectId(notification_id), "user_id": user_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"message": "Notification deleted"}
