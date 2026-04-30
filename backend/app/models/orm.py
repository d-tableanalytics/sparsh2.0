from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from bson import ObjectId
from datetime import datetime
from enum import Enum

class FormulaType(str, Enum):
    STANDARD = "standard" # (Actual/Target)*100
    REVERSE = "reverse"   # (Target/Actual)*100
    THRESHOLD = "threshold" # Custom logic

class ORMNode(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    name: str
    weightage: float = 0.0
    formula_type: FormulaType = FormulaType.STANDARD
    target_value: Optional[float] = None
    unit: Optional[str] = None
    allowed_fillers: List[str] = [] # List of User IDs
    allowed_viewers: List[str] = [] # List of User IDs
    is_anonymous: bool = False     # For Team Engagement
    children: List['ORMNode'] = []
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}

class ORMTemplate(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    name: str
    company_id: str
    description: Optional[str] = None
    category: Optional[str] = None # e.g. "Sales", "Operation"
    structure: List[ORMNode]
    is_active: bool = True
    reminder_config: Optional[Dict[str, Any]] = {
        "enabled": False,
        "day_of_month": 25,
        "message": "Please update your ORM scores for this month."
    }
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}

class ORMAssignment(BaseModel):
    template_id: str
    company_id: str
    batch_id: Optional[str] = None
    course_id: Optional[str] = None
    learner_ids: Optional[List[str]] = None # If assigned to specific learners
    start_date: datetime
    end_date: Optional[datetime] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ORMAchievement(BaseModel):
    assignment_id: str
    learner_id: str
    kpi_id: str # Flattened ID or path
    period: str # YYYY-MM
    actual_value: float
    target_value: float # Captured at time of entry from config
    score: float # Calculated score for this entry
    weighted_contribution: float # score * (weight/100)
    submitted_by: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    notes: Optional[str] = None

class ORMScoreSummary(BaseModel):
    learner_id: str
    assignment_id: str
    period: str
    total_score: float
    category_scores: Dict[str, float]
    updated_at: datetime = Field(default_factory=datetime.utcnow)
