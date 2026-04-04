from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class SystemSettings(BaseModel):
    setting_name: str = "backdate_control"
    allow_backdate: bool = False
    exception_users: List[str] = [] # List of email addresses
    updated_by: Optional[str] = None # SuperAdmin ID
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class SystemSettingsUpdate(BaseModel):
    allow_backdate: Optional[bool] = None
    exception_users: Optional[List[str]] = None
