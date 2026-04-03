from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class CalendarEventBase(BaseModel):
    title: str
    type: str = "event" # event, task
    start: str 
    end: Optional[str] = None
    all_day: bool = False
    
    # Event specific
    session_type: Optional[str] = None
    priority: Optional[str] = "Normal"
    session_template_id: Optional[str] = None
    batch_id: Optional[str] = None
    quarter_id: Optional[str] = None
    status: str = "schedule"
    assigned_departments: Optional[List[str]] = []
    assigned_member_ids: Optional[List[str]] = []
    coach_ids: Optional[List[str]] = []
    additional_details: Optional[str] = None
    meeting_link: Optional[str] = None
    
    # Task specific
    category: Optional[str] = None
    description: Optional[str] = None
    
    # Repetition
    repeat: str = "Does not repeat" # Daily, Weekly, Monthly, Yearly, Periodically, Custom
    repeat_end_date: Optional[str] = None
    repeat_interval: Optional[int] = 1
    repeat_data: Optional[dict] = None
    
    # Delegation
    assigned_to: str = "myself" # myself, other
    target_staff_id: Optional[str] = None
    
    color: str = "var(--accent-indigo)"
    bg: str = "var(--accent-indigo-bg)"

class CalendarEventCreate(CalendarEventBase):
    pass

class CalendarEventResponse(CalendarEventBase):
    id: str = Field(alias="_id")

    class Config:
        populate_by_name = True
