from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from app.models.user import UserResponse, UserRole
from app.controllers.auth_controller import (
    get_current_active_user, get_current_user,
    check_role, get_password_hash
)
from app.db.mongodb import get_collection
from bson import ObjectId
from datetime import datetime
from pydantic import BaseModel

router = APIRouter(prefix="/users", tags=["Users"])

# ─── List Users (Combined) ───
@router.get("/")
async def list_users(current_user: dict = Depends(get_current_user)):
    staff = await get_collection("staff").find({}).to_list(1000)
    learners = await get_collection("learners").find({}).to_list(1000)
    
    all_users = staff + learners
    for u in all_users:
        u["_id"] = str(u["_id"])
        u.pop("password", None)
    return all_users

# ─── Models ───
class UserEditRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    mobile: Optional[str] = None
    role: Optional[str] = None
    session_type: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None

class UserStatusUpdate(BaseModel):
    is_active: bool

# ─── Current User ───
@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: dict = Depends(get_current_active_user)):
    current_user["_id"] = str(current_user["_id"])
    return current_user

# ─── Helper to find user in any collection ───
async def find_user_by_id(user_id: str):
    for col_name in ["staff", "learners"]:
        user = await get_collection(col_name).find_one({"_id": ObjectId(user_id)})
        if user:
            return user, col_name
    return None, None

# ─── Get Single User ───
@router.get("/{user_id}")
async def get_user(user_id: str, current_user: dict = Depends(get_current_user)):
    user, _ = await find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user["_id"] = str(user["_id"])
    user.pop("password", None)
    return user

# ─── Update User ───
@router.put("/{user_id}")
async def update_user(user_id: str, updates: UserEditRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    user, col_name = await find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    update_data["updated_at"] = datetime.utcnow()
    await get_collection(col_name).update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
    return {"message": "User updated successfully"}

# ─── Delete User ───
@router.delete("/{user_id}")
async def delete_user(user_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    user, col_name = await find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    await get_collection(col_name).delete_one({"_id": ObjectId(user_id)})
    return {"message": "User deleted"}

# ─── Get User Activity/History ───
@router.get("/{user_id}/activity")
async def get_user_activity(user_id: str, current_user: dict = Depends(get_current_user)):
    """Returns learning progress, attendance, and activity history for a member."""
    if current_user.get("role") != "superadmin":
        if str(current_user.get("_id")) != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")
    
    # Learnings
    learnings_col = get_collection("learnings")
    learnings = await learnings_col.find({"user_id": user_id}).sort("date", -1).to_list(100)
    for l in learnings:
        l["_id"] = str(l["_id"])
    
    # Attendance
    attendance_col = get_collection("attendance")
    attendance = await attendance_col.find({"user_id": user_id}).sort("date", -1).to_list(100)
    for a in attendance:
        a["_id"] = str(a["_id"])
    
    # Activity log
    activity_col = get_collection("activity_log")
    activities = await activity_col.find({"user_id": user_id}).sort("timestamp", -1).to_list(50)
    for act in activities:
        act["_id"] = str(act["_id"])
    
    return {
        "learnings": learnings,
        "attendance": attendance,
        "activities": activities
    }

# ─── Admin Dashboard ───
@router.get("/admin/dashboard")
async def admin_dashboard(current_user: dict = Depends(check_role([UserRole.SUPERADMIN, UserRole.ADMIN]))):
    return {"message": f"Welcome, Admin {current_user['full_name']}"}
