from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class BatchBase(BaseModel):
    name: str
    product_name: str = ""
    description: Optional[str] = None
    start_date: Optional[str] = None
    target_end_date: Optional[str] = None
    status: str = "active"  # active, completed, paused
    companies: List[str] = []  # list of company_ids

class BatchCreate(BaseModel):
    name: str
    product_name: str = ""
    description: Optional[str] = None
    start_date: Optional[str] = None
    target_end_date: Optional[str] = None

class BatchUpdate(BaseModel):
    name: Optional[str] = None
    product_name: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[str] = None
    target_end_date: Optional[str] = None
    status: Optional[str] = None

class BatchResponse(BatchBase):
    id: str = Field(alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    company_count: Optional[int] = 0

    class Config:
        populate_by_name = True
