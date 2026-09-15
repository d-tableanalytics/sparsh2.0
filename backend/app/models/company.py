from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime

class CompanyBase(BaseModel):
    name: str
    # Prefix for this company's usernames ("People to Process" -> "PTP" -> "PTP_Users001").
    # Derived from the name on first use and stored, so correcting a typo in the company name
    # later cannot silently renumber everybody. Editable: no rule reads every name the way its
    # own people do.
    username_prefix: Optional[str] = None
    domain: Optional[str] = None
    owner: Optional[str] = None
    smop_id: Optional[str] = None
    smop: Optional[str] = None
    # Internal SMOps/OM staff who manage this client. Read-side dashboard scoping honours
    # owner + admin_id + smops_ids (see tpms_dashboard_service._allowed_companies).
    smops_ids: Optional[List[str]] = []
    email: Optional[EmailStr] = None
    contact: Optional[str] = None
    
    # Address Info
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = "India"
    pin: Optional[str] = None
    
    # Business Info
    gst: Optional[str] = None
    company_type: Optional[str] = "Other" # Manufacturing, Retail, etc.
    members_count: Optional[int] = 0
    
    status: str = "active"  # active, hold, inactive
    is_active: bool = True
    orm_enabled: bool = True  # Whether the ORM module is available to this company
    # TPMS is opt-in per company: a missing flag means OFF, unlike ORM which defaults on.
    tpms_enabled: bool = False
    # Task Management (Delegation) module — opt-in per company, gates client-side access.
    delegation_enabled: bool = False
    # HRMS module — opt-in per company (a missing flag means OFF, like TPMS/Delegation).
    hrms_enabled: bool = False

class CompanyCreate(CompanyBase):
    pass

class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    username_prefix: Optional[str] = None
    owner: Optional[str] = None
    smop_id: Optional[str] = None
    smop: Optional[str] = None
    smops_ids: Optional[List[str]] = None
    is_active: Optional[bool] = None

class CompanyResponse(CompanyBase):
    id: str = Field(alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    admin_id: Optional[str] = None # Link to primary ClientAdmin User ID

    class Config:
        populate_by_name = True
