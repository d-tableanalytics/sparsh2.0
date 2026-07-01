from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime

class Reminder(BaseModel):
    id: str = Field(default_factory=lambda: str(datetime.utcnow().timestamp()))
    parent_type: str # task | event
    reminder_type: str # email | whatsapp | both
    timing_type: str # before | after
    offset_minutes: int
    sent: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

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
    status_remark: Optional[str] = None # Added for handover/reschedule notes
    meeting_link: Optional[str] = None
    gpt_project_id: Optional[str] = None
    gpt_project_name: Optional[str] = None
    gpt_projects: List[Dict] = []

    
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
    target_staff_id: Optional[List[str]] = []

    # Reminders
    reminders: List[Reminder] = []

    color: str = "var(--accent-indigo)"
    bg: str = "var(--accent-indigo-bg)"

    # ─── Task Management module additions (additive/optional; events are unaffected) ───
    # Richer workflow state for type=="task" docs only. The legacy `status` field
    # (schedule/completed/canceled/reschedule) stays authoritative for the Calendar page;
    # the Task Management dashboard/lists read `workflow_status`, falling back to "pending"
    # for any task created before this field existed.
    workflow_status: str = "pending" # pending, accepted, in_progress, dependent_on_others, blocked, verification, completed
    watchers: Optional[List[str]] = [] # user ids "in the loop" / subscribed to this task
    tags: Optional[List[str]] = []
    deleted_at: Optional[str] = None # soft-delete timestamp (ISO string); None = not deleted

class CalendarEventCreate(CalendarEventBase):
    pass

class CalendarEventResponse(CalendarEventBase):
    id: str = Field(alias="_id")

    class Config:
        populate_by_name = True
