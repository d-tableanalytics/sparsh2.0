from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
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
from app.services.notification_service import send_user_updated_email, send_access_control_email

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
    
    # ─── Auth Check ───
    if current_user.get("role") != "superadmin":
        if str(current_user.get("_id")) != user_id:
            if current_user.get("role") == "clientadmin":
                if user.get("company_id") != current_user.get("company_id"):
                    raise HTTPException(status_code=403, detail="Not authorized to view this user")
            else:
                raise HTTPException(status_code=403, detail="Not authorized")

    user["_id"] = str(user["_id"])
    user.pop("password", None)
    return user

# ─── Update User ───
@router.put("/{user_id}")
async def update_user(user_id: str, updates: UserEditRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    user, col_name = await find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # ─── Auth Check ───
    if current_user.get("role") != "superadmin":
        if current_user.get("role") == "clientadmin":
            if user.get("company_id") != current_user.get("company_id"):
                 raise HTTPException(status_code=403, detail="Not authorized for this user")
        else:
             raise HTTPException(status_code=403, detail="Not authorized")

        
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    # ─── Check for Role/Access Change ───
    old_role = user.get("role")
    new_role = update_data.get("role")
    updated_by = current_user.get("full_name") or current_user.get("first_name", "Admin")

    update_data["updated_at"] = datetime.utcnow()
    await get_collection(col_name).update_one({"_id": ObjectId(user_id)}, {"$set": update_data})

    # ─── Trigger Notifications ───
    if new_role and new_role != old_role:
        background_tasks.add_task(send_access_control_email, user, new_role, updated_by)
    else:
        background_tasks.add_task(send_user_updated_email, user, updated_by)

    return {"message": "User updated successfully and notification triggered"}

# ─── Delete User ───
@router.delete("/{user_id}")
async def delete_user(user_id: str, current_user: dict = Depends(get_current_user)):
    user, col_name = await find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # ─── Auth Check ───
    if current_user.get("role") != "superadmin":
        if current_user.get("role") == "clientadmin":
            if user.get("company_id") != current_user.get("company_id"):
                 raise HTTPException(status_code=403, detail="Not authorized to delete this user")
        else:
             raise HTTPException(status_code=403, detail="Not authorized")

    
    await get_collection(col_name).delete_one({"_id": ObjectId(user_id)})
    return {"message": "User deleted"}

# ─── Get User Activity/History ───
@router.get("/{user_id}/activity")
async def get_user_activity(user_id: str, current_user: dict = Depends(get_current_user)):
    """Returns learning progress, attendance, and activity history for a member."""
    user, _ = await find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # ─── Auth Check ───
    authorized = False
    if current_user.get("role") == "superadmin":
        authorized = True
    elif str(current_user.get("_id")) == user_id:
        authorized = True
    elif current_user.get("role") == "clientadmin":
        # Check if user belongs to the same company
        if user.get("company_id") == current_user.get("company_id"):
            authorized = True
    
    if not authorized:
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
    activity_col = get_collection("activity_logs")
    activities = await activity_col.find({"user_id": user_id}).sort("timestamp", -1).to_list(100)
    for act in activities:
        act["_id"] = str(act["_id"])
    
    return {
        "learnings": learnings,
        "attendance": attendance,
        "activities": activities
    }

# ─── Learner Reports ───
@router.get("/me/reports")
async def get_my_reports(current_user: dict = Depends(get_current_active_user)):
    user_id = str(current_user["_id"])
    
    # 1. Activities
    activity_col = get_collection("activity_logs")
    activities = await activity_col.find({"user_id": user_id}).sort("timestamp", -1).to_list(100)
    for act in activities:
        act["_id"] = str(act["_id"])
        
    # 2. Assessments
    assessment_col = get_collection("LearnerAssessments") # Fixed typo in logic
    # Also check the typo version if it exists
    assessments_legacy = await get_collection("LearnerAsessments").find({"user_id": user_id}).to_list(100)
    assessments_new = await assessment_col.find({"user_id": user_id}).to_list(100)
    
    all_assessments = assessments_legacy + assessments_new
    for ass in all_assessments:
        ass["_id"] = str(ass["_id"])
    
    # Sort by submitted_at
    all_assessments.sort(key=lambda x: x.get("submitted_at", ""), reverse=True)

    # 3. Calculate Stats
    total_activities = len(activities)
    quizzes_taken = len(all_assessments)
    quizzes_passed = len([a for a in all_assessments if a.get("passed")])
    
    return {
        "stats": {
            "total_activities": total_activities,
            "quizzes_taken": quizzes_taken,
            "quizzes_passed": quizzes_passed,
            "pass_rate": round((quizzes_passed / quizzes_taken * 100) if quizzes_taken > 0 else 0, 1)
        },
        "activities": activities,
        "assessments": all_assessments
    }

    return {"message": f"Welcome, Admin {current_user['full_name']}"}

@router.get("/{user_id}/analytics")
async def get_user_analytics(user_id: str, current_user: dict = Depends(get_current_user)):
    user, _ = await find_user_by_id(user_id)
    if not user: raise HTTPException(status_code=404, detail="User not found")
    
    # Auth check
    if current_user.get("role") != "superadmin":
        if str(current_user.get("_id")) != user_id:
            if current_user.get("role") == "clientadmin":
                if user.get("company_id") != current_user.get("company_id"):
                    raise HTTPException(status_code=403, detail="Not authorized")
            else:
                raise HTTPException(status_code=403, detail="Not authorized")

    # 1. Weekly Scores (Last 8 assessments)
    assessments_col = get_collection("LearnerAssessments")
    assessments_new = await assessments_col.find({"user_id": user_id}).sort("submitted_at", 1).to_list(100)
    # Plus legacy if any
    assessments_old = await get_collection("LearnerAsessments").find({"user_id": user_id}).sort("submitted_at", 1).to_list(100)
    all_ass = assessments_old + assessments_new
    all_ass.sort(key=lambda x: x.get("submitted_at", ""))
    
    weekly_scores = []
    for i, ass in enumerate(all_ass[-8:]):
        weekly_scores.append({
            "week": f"A{i+1}",
            "score": ass.get("percentage", 0),
            "target": 85
        })

    # 2. Attendance Summary (Monthly)
    attendance_col = get_collection("attendance")
    attendance = await attendance_col.find({"user_id": user_id}).to_list(500)
    
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly_att = {} # {month_name: {"present": 0, "absent": 0}}
    
    for a in attendance:
        dt = a.get("date")
        if isinstance(dt, str):
            try: dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            except: continue
        if not dt: continue
        
        m_name = months[dt.month - 1]
        if m_name not in monthly_att: monthly_att[m_name] = {"present": 0, "absent": 0}
        
        status = a.get("status", "absent").lower()
        if status == "present": monthly_att[m_name]["present"] += 1
        else: monthly_att[m_name]["absent"] += 1

    attendance_data = [{"name": m, **v} for m, v in monthly_att.items()]
    # Ensure some order
    attendance_data.sort(key=lambda x: months.index(x["name"]))

    # 3. Learning Progress (Top Modules)
    # Derive from assessments for now
    module_scores = {}
    for ass in all_ass:
        mod = ass.get("session_title", "General")
        if mod not in module_scores: module_scores[mod] = []
        module_scores[mod].append(ass.get("percentage", 0))
    
    learning_progress = []
    for mod, scores in module_scores.items():
        avg = round(sum(scores) / len(scores), 1)
        learning_progress.append({
            "name": mod,
            "completed": avg,
            "total": 100
        })

    # 4. Task Breakdown
    # Check session tasks
    progress_col = get_collection("company_session_progress")
    # For a specific user? Real tasks are often per-user or per-company.
    # Assuming session tasks are global for now.
    
    return {
        "weekly_scores": weekly_scores,
        "attendance_data": attendance_data,
        "learning_progress": learning_progress[:5], # top 5
        "task_stats": [
            {"name": "Completed", "value": len([a for a in all_ass if a.get("passed")])},
            {"name": "In Progress", "value": len(all_ass) // 2}, # Mocking relative split
            {"name": "Pending", "value": 5}
        ]
    }
