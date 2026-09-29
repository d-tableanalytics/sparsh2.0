from fastapi import APIRouter, Depends, Form, HTTPException, status, BackgroundTasks
import re
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
from bson import ObjectId
import random
import logging

logger = logging.getLogger("auth")
from app.models.auth import Token, PasswordChange, ForgotPasswordRequest, ResetPasswordRequest, AdminMemberUpdate
from app.services.activity_log_service import log_activity
from app.services.username_service import assign_username
from app.services.notification_service import send_notification_from_template, send_otp_email

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, background_tasks: BackgroundTasks):
    email = data.email.lower().strip()
    
    # 1. Search across both staff and learners
    user = await get_collection("staff").find_one({"email": email})
    if not user:
        user = await get_collection("learners").find_one({"email": email})
    
    if not user:
        # Security: Return generic message so we don't leak user emails
        return {"message": "If your email is registered, you will receive a 6-digit OTP."}

    # 2. Generate 6-digit OTP
    otp = "".join([str(random.randint(0, 9)) for _ in range(6)])
    
    # 3. Store OTP in password_resets collection
    resets_col = get_collection("password_resets")
    expires_at = datetime.utcnow() + timedelta(seconds=60)
    
    await resets_col.update_one(
        {"email": email},
        {"$set": {"otp": otp, "expires_at": expires_at}},
        upsert=True
    )
    
    # 4. Send background email
    background_tasks.add_task(send_otp_email, email, otp, user)
    
    await log_activity(user, "Password Reset OTP Requested", "auth", f"OTP generated for {email}")
    return {"message": "OTP has been sent to your registered email address."}

@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest):
    email = data.email.lower().strip()
    resets_col = get_collection("password_resets")
    
    # 1. Verify OTP record
    record = await resets_col.find_one({"email": email})
    if not record:
        raise HTTPException(status_code=400, detail="No reset request found for this email")
    
    if record["otp"] != data.otp:
        raise HTTPException(status_code=400, detail="Invalid verification code")
    
    if datetime.utcnow() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="Verification code has expired")
    
    # 2. Identify collection and update password
    hashed_password = get_password_hash(data.new_password)
    col_name = None
    
    user = await get_collection("staff").find_one({"email": email})
    if user:
        col_name = "staff"
    else:
        user = await get_collection("learners").find_one({"email": email})
        if user:
            col_name = "learners"
            
    if not col_name:
        raise HTTPException(status_code=404, detail="Account not found during reset")
        
    await get_collection(col_name).update_one(
        {"email": email},
        {"$set": {"password": hashed_password}}
    )
    
    # 3. Cleanup reset record
    await resets_col.delete_one({"email": email})
    
    await log_activity(user, "Password Reset Completed", "auth", "Password successfully changed via OTP verification")
    return {"message": "Your password has been reset successfully. You can now login with your new password."}

@router.post("/request-admin-otp")
async def request_admin_otp(current_user: dict = Depends(get_current_active_user), background_tasks: BackgroundTasks = BackgroundTasks()):
    if current_user["role"] not in ["superadmin", "admin", "clientadmin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    otp = "".join([str(random.randint(0, 9)) for _ in range(6)])
    resets_col = get_collection("password_resets")
    expires_at = datetime.utcnow() + timedelta(seconds=60)
    
    await resets_col.update_one(
        {"email": current_user["email"]},
        {"$set": {"otp": otp, "expires_at": expires_at}},
        upsert=True
    )
    
    background_tasks.add_task(send_otp_email, current_user["email"], otp, current_user)
    return {"message": "Verification code sent to your email."}

@router.post("/admin/update-member")
async def admin_update_member(data: AdminMemberUpdate, current_user: dict = Depends(get_current_active_user)):
    if current_user["role"] not in ["superadmin", "admin", "clientadmin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    # 1. Verify OTP
    resets_col = get_collection("password_resets")
    record = await resets_col.find_one({"email": current_user["email"]})
    if not record or record["otp"] != data.otp or datetime.utcnow() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")
        
    # 2. Find target user
    col_name = None
    target_user = await get_collection("staff").find_one({"_id": ObjectId(data.user_id)})
    if target_user:
        col_name = "staff"
    else:
        target_user = await get_collection("learners").find_one({"_id": ObjectId(data.user_id)})
        if target_user:
            col_name = "learners"
            
    if not col_name:
        raise HTTPException(status_code=404, detail="Target member not found")
        
    # 3. Authorization check
    if current_user["role"] == "clientadmin":
        if str(target_user.get("company_id")) != str(current_user.get("company_id")):
            raise HTTPException(status_code=403, detail="Not authorized to manage members of other companies")
            
    # 4. Perform updates
    update_dict = {}
    if data.new_email:
        update_dict["email"] = data.new_email.lower().strip()
    if data.new_password:
        update_dict["password"] = get_password_hash(data.new_password)
        
    if not update_dict:
        raise HTTPException(status_code=400, detail="No updates provided")
        
    await get_collection(col_name).update_one({"_id": ObjectId(data.user_id)}, {"$set": update_dict})
    
    # 5. Cleanup
    await resets_col.delete_one({"email": current_user["email"]})
    
    await log_activity(current_user, "Admin Action: Member Credentials Updated", "auth", f"Updated credentials for {target_user.get('email')} (ID: {data.user_id})")
    return {"message": "Member credentials updated successfully."}

@router.patch("/change-password")
async def change_password(data: PasswordChange, current_user: dict = Depends(get_current_active_user)):
    # Verify current password
    if not verify_password(data.current_password, current_user["password"]):
        raise HTTPException(status_code=400, detail="Incorrect current password")

    # Spec §15 — the new password must be at least 6 characters and must not repeat the
    # current one. Compared against the stored hash, so an identical password is caught
    # even though we never hold the old plaintext.
    if len(data.new_password or "") < 6:
        raise HTTPException(status_code=400,
                            detail="New password must be at least 6 characters long.")
    if verify_password(data.new_password, current_user["password"]):
        raise HTTPException(status_code=400,
                            detail="New password must be different from your current password.")

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
    user_dict["tag"] = "staff" if is_staff_role else "learner"
    fn = user.first_name or ""
    ln = user.last_name or ""
    user_dict["full_name"] = f"{fn} {ln}".strip()
    user_dict["created_at"] = datetime.utcnow()
    # Issued here rather than asked for: the number has to be the next free one in that
    # company, which only the server can know.
    await assign_username(user_dict, user_dict.get("company_id"))
    
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
            "username": user_dict.get("username") or "",
            "password": raw_password,
            "role": user_dict["role"],
            "login_url": "https://sparsh.app/login"
        },

        delivery_type="email"
    )


    await log_activity(user_dict, "Registration Success", "auth", f"Registered as {role}")
    return user_dict


async def _find_login_candidates(identifier: str) -> list:
    """Every account an identifier could mean, across both user collections.

    A USERNAME matches at most one account by construction, so it is tried first and wins
    outright. An EMAIL may now match several — one person, two client companies — which is
    exactly the case the username was introduced for; all of them are returned and the caller
    decides what to do about it.

    Both comparisons are case-insensitive: nobody types their own address with the same
    capitalisation twice, and a login that depends on it is a support ticket.
    """
    exact = {"$regex": f"^{re.escape(identifier.strip())}$", "$options": "i"}

    by_username = []
    for coll in ("staff", "learners"):
        async for doc in get_collection(coll).find({"username": exact}):
            doc["_source_collection"] = coll
            by_username.append(doc)
    if by_username:
        return by_username

    by_email = []
    for coll in ("staff", "learners"):
        async for doc in get_collection(coll).find({"email": exact}):
            doc["_source_collection"] = coll
            by_email.append(doc)
    return by_email


async def _company_label(company_id) -> str:
    if not company_id:
        return "Sparsh (internal)"
    try:
        doc = await get_collection("companies").find_one({"_id": ObjectId(str(company_id))})
        return (doc or {}).get("name") or "Unknown company"
    except Exception:
        return "Unknown company"


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    company_id: Optional[str] = Form(None),
):
    """Sign in with a username or an email address.

    `company_id` is only needed to break a tie: when one address belongs to accounts in
    several companies the first attempt comes back with the list, and the client re-submits
    naming one. A username never needs it.
    """
    identifier = (form_data.username or "").strip()
    logger.info(f"Login attempt for identifier: {identifier}")

    candidates = await _find_login_candidates(identifier)
    # Only the accounts whose password actually matches. Filtering by password BEFORE asking
    # which company also means the prompt cannot be used to discover where somebody holds an
    # account — a wrong password looks identical whether the address exists or not.
    matched = [u for u in candidates if u.get("password")
               and verify_password(form_data.password, u["password"])]

    if company_id:
        matched = [u for u in matched if str(u.get("company_id") or "") == str(company_id)]

    if not matched:
        logger.warning(f"Login failed (invalid credentials) for identifier: {identifier}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if len(matched) > 1:
        # One address, several accounts. Answer with the choices rather than picking: guessing
        # here signs somebody into the wrong company's data with no sign anything went wrong.
        choices = [{
            "company_id": str(u.get("company_id") or ""),
            "company_name": await _company_label(u.get("company_id")),
            "username": u.get("username"),
            "role": u.get("role"),
        } for u in matched]
        logger.info(f"Login ambiguous for {identifier}: {len(choices)} accounts")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "This email is used for more than one company. "
                           "Choose which one to sign in to, or use your username.",
                "accounts": choices,
            },
        )

    user = matched[0]

    if user.get("is_active") == False:
        logger.warning(f"Login blocked (deactivated account): {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated. Please contact your administrator."
        )

    logger.info(f"Login success for {user.get('email')} (role={user.get('role')}, id={user.get('_id')})")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            # The user's id, never their email: an address can name more than one account
            # (the same person in two client companies) and the session must not be ambiguous.
            "sub": str(user["_id"]),
            "username": user.get("username"),
            "role": user["role"],
            "full_name": user.get("full_name") or f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip() or "User",
            "email": user.get("email"),
            "mobile": user.get("mobile"),
            "designation": user.get("designation"),
            "department": user.get("department"),
            "session_type": user.get("session_type"),
            "_id": str(user["_id"]),
            "company_id": user.get("company_id"),
            "permissions": user.get("permissions", {})
        }, 
        expires_delta=access_token_expires
    )
    await log_activity(user, "User Login", "auth", "Logged in via Token")
    return {"access_token": access_token, "token_type": "bearer"}
