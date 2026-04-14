from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from typing import Optional
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime, timedelta
from app.db.mongodb import get_collection
from app.config.settings import settings

from app.models.user import UserCreate, UserResponse
from app.models.auth import Token, PasswordChange
from app.controllers.auth_controller import (
    get_password_hash, 
    verify_password, 
    create_access_token,
    get_current_active_user,
    get_current_user
)
from app.services.activity_log_service import log_activity
from app.services.notification_service import send_notification_from_template

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.patch("/change-password")
async def change_password(data: PasswordChange, current_user: dict = Depends(get_current_active_user)):
    # Verify current password
    if not verify_password(data.current_password, current_user["password"]):
        raise HTTPException(status_code=400, detail="Incorrect current password")
    
    # Hash and update
    hashed_password = get_password_hash(data.new_password)
    col_name = "staff" if current_user["role"] in ["superadmin", "admin", "coach", "staff"] else "learners"
    await get_collection(col_name).update_one(
        {"_id": current_user["_id"]},
        {"$set": {"password": hashed_password}}
    )
    
    await log_activity(current_user, "Password Change", "auth", "Changed password via profile")
    return {"message": "Password updated successfully"}


@router.post("/register", response_model=UserResponse)
async def register(user: UserCreate, background_tasks: BackgroundTasks, current_user: Optional[dict] = Depends(get_current_user)):
    role = user.role.lower()
    is_staff_role = role in ["superadmin", "admin", "coach", "staff"]
    
    # ─── Restrict Staff Creation to Superadmin ───
    if is_staff_role:
        if not current_user or current_user.get("role") != "superadmin":
            raise HTTPException(status_code=403, detail="Only superadmin can create staff users")
            
    collection_name = "staff" if is_staff_role else "learners"
    col = get_collection(collection_name)
    
    if await col.find_one({"email": user.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Store raw password temporarily to send in email (if needed) or just confirm creation
    raw_password = user.password
    hashed_password = get_password_hash(user.password)
    user_dict = user.model_dump()
    user_dict["password"] = hashed_password
    fn = user.first_name or ""
    ln = user.last_name or ""
    user_dict["full_name"] = f"{fn} {ln}".strip()
    user_dict["created_at"] = datetime.utcnow()
    
    result = await col.insert_one(user_dict)
    user_dict["_id"] = str(result.inserted_id)
    
    # Send Welcome Email via Template
    background_tasks.add_task(
        send_notification_from_template,
        user_obj=user_dict,
        template_slug="user_creation", # The function appends _email or _whatsapp
        context={
            "name": user_dict["first_name"],
            "email": user_dict["email"],
            "password": raw_password,
            "role": user_dict["role"],
            "login_url": "https://sparsh.app/login"
        },

        delivery_type="email"
    )


    await log_activity(user_dict, "Registration Success", "auth", f"Registered as {role}")
    return user_dict


@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    # Search Staff first
    user = await get_collection("staff").find_one({"email": form_data.username})
    if not user:
        # Search Learners
        user = await get_collection("learners").find_one({"email": form_data.username})
        
    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user["email"], 
            "role": user["role"],
            "full_name": user.get("full_name") or f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip() or "User",
            "_id": str(user["_id"]),
            "company_id": user.get("company_id"),
            "permissions": user.get("permissions", {})
        }, 
        expires_delta=access_token_expires
    )
    await log_activity(user, "User Login", "auth", "Logged in via Token")
    return {"access_token": access_token, "token_type": "bearer"}
