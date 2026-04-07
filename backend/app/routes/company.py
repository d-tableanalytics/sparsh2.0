from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import List, Optional
from app.db.mongodb import get_db, get_collection
from app.models.company import CompanyCreate, CompanyResponse
from app.models.user import UserCreate
from app.controllers.auth_controller import get_current_user, get_password_hash
from app.services.notification_service import send_notification_from_template, send_company_registration_email
from bson import ObjectId
from datetime import datetime
from pydantic import BaseModel
import io

router = APIRouter(prefix="/companies", tags=["Companies"])

class CompanyOnboardingRequest(BaseModel):
    company: CompanyCreate
    admin: UserCreate

class CompanyStatusUpdate(BaseModel):
    status: str  # active, hold, inactive

class CompanyEditRequest(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    owner: Optional[str] = None
    email: Optional[str] = None
    contact: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    pin: Optional[str] = None
    gst: Optional[str] = None
    company_type: Optional[str] = None
    members_count: Optional[int] = None

# ─── Onboard Company ───
@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def onboard_company(request: CompanyOnboardingRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Not authorized to onboard companies")
    
    users_collection = get_collection("learners")
    companies_collection = get_collection("companies")
    
    existing_user = await users_collection.find_one({"email": request.admin.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Admin email already registered")
    
    company_dict = request.company.model_dump()
    company_dict["created_at"] = datetime.utcnow()
    company_dict["status"] = "active"
    
    company_result = await companies_collection.insert_one(company_dict)
    company_id = str(company_result.inserted_id)
    
    admin_dict = request.admin.model_dump()
    admin_dict["password"] = get_password_hash(admin_dict["password"])
    admin_dict["role"] = "clientadmin"
    admin_dict["company_id"] = company_id
    admin_dict["is_active"] = True
    admin_dict["created_at"] = datetime.utcnow()
    
    if not admin_dict.get("full_name"):
        admin_dict["full_name"] = f"{admin_dict.get('first_name', '')} {admin_dict.get('last_name', '')}".strip()
    
    admin_result = await users_collection.insert_one(admin_dict)
    admin_id = str(admin_result.inserted_id)
    
    await companies_collection.update_one(
        {"_id": company_result.inserted_id},
        {"$set": {"admin_id": admin_id}}
    )
    
    # ─── Trigger Welcome Email ───
    background_tasks.add_task(
        send_company_registration_email,
        admin_obj=admin_dict,
        company_name=company_dict.get("name"),
        raw_password=request.admin.password
    )
    
    company_dict["_id"] = company_id
    company_dict["admin_id"] = admin_id
    return company_dict

# ─── List Companies ───
@router.get("", response_model=List[CompanyResponse])
async def list_companies(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Not authorized to list companies")
    
    db = get_db()
    companies = await db.companies.find().to_list(100)
    for c in companies:
        c["_id"] = str(c["_id"])
    return companies

# ─── Get Single Company ───
@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(company_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin" and current_user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorized to view this company")
    
    db = get_db()
    company = await db.companies.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    company["_id"] = str(company["_id"])
    return company

# ─── Update Company Details ───
@router.put("/{company_id}")
async def update_company(company_id: str, updates: CompanyEditRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    companies_collection = get_collection("companies")
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    update_data["updated_at"] = datetime.utcnow()
    result = await companies_collection.update_one({"_id": ObjectId(company_id)}, {"$set": update_data})
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    
    return {"message": "Company updated successfully"}

# ─── Update Company Status ───
@router.patch("/{company_id}/status")
async def update_company_status(company_id: str, body: CompanyStatusUpdate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if body.status not in ["active", "hold", "inactive"]:
        raise HTTPException(status_code=400, detail="Invalid status. Must be: active, hold, inactive")
    
    companies_collection = get_collection("companies")
    result = await companies_collection.update_one(
        {"_id": ObjectId(company_id)},
        {"$set": {"status": body.status, "updated_at": datetime.utcnow()}}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    
    return {"message": f"Company status changed to {body.status}"}

# ─── Delete Company ───
@router.delete("/{company_id}")
async def delete_company(company_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    companies_collection = get_collection("companies")
    users_collection = get_collection("learners")
    
    company = await companies_collection.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Delete all users in that company
    await users_collection.delete_many({"company_id": company_id})
    await companies_collection.delete_one({"_id": ObjectId(company_id)})
    
    return {"message": "Company and associated users deleted"}

# ─── Get Company Users ───
@router.get("/{company_id}/users")
async def get_company_users(company_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin" and current_user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    users_collection = get_collection("learners")
    users = await users_collection.find({"company_id": company_id}).to_list(500)
    for u in users:
        u["_id"] = str(u["_id"])
        u.pop("password", None)
    return users

# ─── Bulk Create Users (JSON) ───
@router.post("/{company_id}/users/bulk")
async def bulk_create_users(company_id: str, users: List[UserCreate], background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    users_collection = get_collection("learners")
    from app.services.notification_service import send_notification_from_template
    created = 0
    skipped = 0
    
    for user_data in users:
        existing = await users_collection.find_one({"email": user_data.email})
        if existing:
            skipped += 1
            continue
        
        # Save raw password before hashing for the email
        raw_password = user_data.password
        
        user_dict = user_data.model_dump()
        user_dict["password"] = get_password_hash(user_dict["password"])
        user_dict["company_id"] = company_id
        user_dict["is_active"] = True
        user_dict["created_at"] = datetime.utcnow()
        
        if not user_dict.get("full_name"):
            user_dict["full_name"] = f"{user_dict.get('first_name', '')} {user_dict.get('last_name', '')}".strip()
        
        res = await users_collection.insert_one(user_dict)
        user_dict["_id"] = str(res.inserted_id)
        
        # Trigger Welcome Email
        background_tasks.add_task(
            send_notification_from_template,
            user_obj=user_dict,
            template_slug="user_creation",
            context={
                "name": user_dict.get("first_name", "Learner"),
                "email": user_dict["email"],
                "password": raw_password,
                "role": "Learner",
                "login_url": "http://localhost:5173/login"
            },
            delivery_type="email"
        )
        created += 1
    
    return {"message": f"Created {created} users, skipped {skipped} duplicates"}

# ─── Export XLSX Template ───
@router.get("/{company_id}/users/template")
async def download_user_template(company_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed. Run: pip install openpyxl")
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Users"
    
    headers = ["email", "password", "first_name", "last_name", "mobile", "role", "session_type", "designation", "department"]
    ws.append(headers)
    
    # Sample row
    ws.append(["user@example.com", "tempPass123", "John", "Doe", "9876543210", "clientuser", "Core", "Manager", "HOD"])
    
    # Style header
    from openpyxl.styles import Font, PatternFill
    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
    
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 20
    
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=user_template_{company_id}.xlsx"}
    )

# ─── Import XLSX Users ───
@router.post("/{company_id}/users/import")
async def import_users_xlsx(company_id: str, background_tasks: BackgroundTasks, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed")
    
    contents = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(contents))
    ws = wb.active
    
    headers = [cell.value for cell in ws[1]]
    users_collection = get_collection("learners")
    from app.services.notification_service import send_notification_from_template
    created = 0
    skipped = 0
    errors = []
    
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        row_data = dict(zip(headers, row))
        
        if not row_data.get("email") or not row_data.get("password"):
            errors.append(f"Row {row_idx}: Missing email or password")
            continue
        
        existing = await users_collection.find_one({"email": row_data["email"]})
        if existing:
            skipped += 1
            continue
        
        # Plain text password for email
        raw_password = str(row_data["password"])
        
        user_dict = {
            "email": row_data["email"],
            "password": get_password_hash(raw_password),
            "first_name": row_data.get("first_name", ""),
            "last_name": row_data.get("last_name", ""),
            "full_name": f"{row_data.get('first_name', '')} {row_data.get('last_name', '')}".strip(),
            "mobile": str(row_data.get("mobile", "")) if row_data.get("mobile") else None,
            "role": row_data.get("role", "clientuser"),
            "session_type": row_data.get("session_type", "None"),
            "designation": row_data.get("designation"),
            "department": row_data.get("department", "Other"),
            "company_id": company_id,
            "is_active": True,
            "created_at": datetime.utcnow()
        }
        
        res = await users_collection.insert_one(user_dict)
        user_dict["_id"] = str(res.inserted_id)
        
        # Trigger Welcome Email
        background_tasks.add_task(
            send_notification_from_template,
            user_obj=user_dict,
            template_slug="user_creation",
            context={
                "name": user_dict.get("first_name", "Learner"),
                "email": user_dict["email"],
                "password": raw_password,
                "role": "Learner",
                "login_url": "http://localhost:5173/login"
            },
            delivery_type="email"
        )
        created += 1
    
    return {"created": created, "skipped": skipped, "errors": errors}
