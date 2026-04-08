from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum

class UserRole(str, Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    CLIENTADMIN = "clientadmin"
    CLIENTUSER = "clientuser"
    CUSTOM = "custom"

class UserBase(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None # Derivable or stored
    mobile: Optional[str] = None
    role: str = "clientuser"
    company_id: Optional[str] = None
    is_active: bool = True
    
    # Business specific fields
    session_type: Optional[str] = "None" # Core, Support, Both, None
    designation: Optional[str] = None
    department: Optional[str] = "Other" # HOD, Implementor, EA, MD, Other
    
    # Highly Granular CRUD Permissions
    permissions: dict = {
        "batches": {"create": False, "read": True, "update": False, "delete": False},
        "calendar": {"create": False, "read": True, "update": False, "delete": False},
        "users": {"create": False, "read": True, "update": False, "delete": False},
        "companies": {"create": False, "read": True, "update": False, "delete": False},
        "logs": {"create": False, "read": True, "update": False, "delete": False},
        "templates": {"create": False, "read": True, "update": False, "delete": False}
    }

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: str = Field(alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
