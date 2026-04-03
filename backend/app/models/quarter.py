from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class QuarterBase(BaseModel):
    name: str
    batch_id: str
    description: Optional[str] = None
    status: str = "active"  # active, completed, paused
    start_date: Optional[str] = None
    target_end_date: Optional[str] = None

class QuarterCreate(BaseModel):
    name: str
    batch_id: str
    description: Optional[str] = None
    start_date: Optional[str] = None
    target_end_date: Optional[str] = None

class QuarterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[str] = None
    target_end_date: Optional[str] = None

class QuarterResponse(QuarterBase):
    id: str = Field(alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
