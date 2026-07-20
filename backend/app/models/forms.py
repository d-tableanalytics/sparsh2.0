"""
TPMS ▸ Forms sub-module — models + form-type registry.

These are monthly HOD "checklist" forms (Accountability, Ownership, Culture,
Implementation Feedback). Each is a rating matrix: an HOD scores every team
member on a fixed set of criteria using a 0–5 scale.

Storage granularity is deliberately atomic — one score per
(company_id, period, hod_id, member_id, criterion_code) — so downstream
Success Measure calculations can aggregate freely without re-parsing.
Success Measure computation itself is intentionally NOT implemented here.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# Form-type registry (source of truth for the questions/criteria).
# The frontend fetches these so the UI never hardcodes the criteria.
# Add Culture / Implementation Feedback criteria here once provided —
# no route or model change is required.
# ─────────────────────────────────────────────────────────────
SCALE_MIN = 0
SCALE_MAX = 5

FORM_DEFINITIONS: Dict[str, dict] = {
    "accountability": {
        "form_type": "accountability",
        "title": "Accountability Checklist",
        "description": "Monthly HOD accountability rating for each team member.",
        "available": True,
        "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
        "criteria": [
            {"code": "A1", "title": "Timely Task Completion",
             "prompt": "Is he/she ensure adherence to Position Score Card (PSC)?"},
            {"code": "A2", "title": "Departmental result Adherence",
             "prompt": "Is he/she ensuring departmental processes are adhered?"},
            {"code": "A3", "title": "Task Completion Without Follow-up",
             "prompt": "Is he/she ensuring task completion without followup?"},
            {"code": "A4", "title": "Initiative for Better DRM Score",
             "prompt": "Is he/she ensuring to take initiatives to achieve an excellent DRM Score?"},
        ],
    },
    "ownership": {
        "form_type": "ownership",
        "title": "Ownership Checklist",
        "description": "Monthly HOD ownership rating for each team member.",
        "available": True,
        "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
        "criteria": [
            {"code": "O1", "title": "Active Departmental Participation",
             "prompt": "Is he/she getting involved and actively participating in departmental activity?"},
            {"code": "O2", "title": "Departmental Problem Solving",
             "prompt": "Is he/she contributing towards solving departmental problems?"},
            {"code": "O3", "title": "Process Involvement",
             "prompt": "Is he/she interested or involved to follow the process?"},
            {"code": "O4", "title": "Organisational Result Alignment",
             "prompt": "Is he/she aligned with the organisational result Matrix?"},
        ],
    },
    # Placeholders — criteria to be supplied. `available: False` tells the UI to
    # show a "coming soon" state instead of a form. Fill `criteria` to activate.
    "culture": {
        "form_type": "culture",
        "title": "Culture Checklist",
        "description": "Monthly HOD culture rating for each team member.",
        "available": False,
        "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
        "criteria": [],
    },
    "implementation_feedback": {
        "form_type": "implementation_feedback",
        "title": "Implementation Feedback",
        "description": "Monthly implementation feedback for each team member.",
        "available": False,
        "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
        "criteria": [],
    },
}


def get_definition(form_type: str) -> Optional[dict]:
    return FORM_DEFINITIONS.get(form_type)


def criteria_codes(form_type: str) -> List[str]:
    d = FORM_DEFINITIONS.get(form_type) or {}
    return [c["code"] for c in d.get("criteria", [])]


# ─────────────────────────────────────────────────────────────
# Submission models
# ─────────────────────────────────────────────────────────────
class MemberScore(BaseModel):
    """One rated team member within a submission."""
    member_id: Optional[str] = None        # staff/learner _id or employee code
    employee_id: Optional[str] = None      # e.g. "EMP_223" if available
    member_name: str
    designation: Optional[str] = None
    department: Optional[str] = None
    # criterion_code -> score (0..5). Authoritative atomic data.
    scores: Dict[str, int] = Field(default_factory=dict)

    @field_validator("member_name")
    @classmethod
    def _name_required(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("member_name is required")
        return str(v).strip()

    @field_validator("scores")
    @classmethod
    def _scores_in_range(cls, v: Dict[str, int]) -> Dict[str, int]:
        for code, score in v.items():
            if not isinstance(score, int) or score < SCALE_MIN or score > SCALE_MAX:
                raise ValueError(f"Score for '{code}' must be an integer between {SCALE_MIN} and {SCALE_MAX}")
        return v


class FormSubmissionCreate(BaseModel):
    company_id: str
    period: str                            # raw MID as launched, e.g. "july26"
    hod_id: Optional[str] = None           # EID, e.g. "EMP_223"
    hod_name: Optional[str] = None
    members: List[MemberScore]

    @field_validator("company_id", "period")
    @classmethod
    def _required(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("company_id and period are required")
        return str(v).strip()

    @field_validator("members")
    @classmethod
    def _members_non_empty(cls, v: List[MemberScore]) -> List[MemberScore]:
        if not v:
            raise ValueError("At least one member must be rated")
        return v


class FormSubmissionResponse(BaseModel):
    id: str = Field(alias="_id")
    form_type: str
    company_id: str
    period: str
    hod_id: Optional[str] = None
    hod_name: Optional[str] = None
    members: List[dict]
    submitted_by: Optional[str] = None
    submitted_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
