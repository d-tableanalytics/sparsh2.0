from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime

class CompanyBase(BaseModel):
    name: str
    domain: Optional[str] = None
    owner: Optional[str] = None
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

class CompanyCreate(CompanyBase):
    pass

class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    owner: Optional[str] = None
    is_active: Optional[bool] = None

class CompanyResponse(CompanyBase):
    id: str = Field(alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    admin_id: Optional[str] = None # Link to primary ClientAdmin User ID

    class Config:
        populate_by_name = True
