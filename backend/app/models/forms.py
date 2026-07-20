"""
TPMS ▸ Forms sub-module — models + form-type registry.

Two form KINDS are supported:

  • "rating_matrix"   — an HOD scores every team member on fixed criteria using a
                        0–5 scale (Ownership, Accountability, [Culture]).
  • "yesno_checklist" — the MD answers a flat list of questions with Yes/No + an
                        optional remark, with partial (slot-by-slot) submission
                        (Implementation Feedback).

Storage granularity is deliberately atomic so downstream Success Measure
calculations can aggregate freely without re-parsing:
  • rating_matrix   → one score per (company_id, period, hod_id, member_id, criterion_code)
  • yesno_checklist → one answer per (company_id, period, md_id, question_id)
Success Measure computation itself is intentionally NOT implemented here.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict
from datetime import datetime


SCALE_MIN = 0
SCALE_MAX = 5

KIND_RATING_MATRIX = "rating_matrix"
KIND_YESNO_CHECKLIST = "yesno_checklist"


# ─────────────────────────────────────────────────────────────
# Form-type registry (source of truth for questions/criteria).
# The frontend fetches these so the UI never hardcodes anything.
# Activate a form by filling its criteria/questions and available:True.
# ─────────────────────────────────────────────────────────────
FORM_DEFINITIONS: Dict[str, dict] = {
    "accountability": {
        "form_type": "accountability",
        "kind": KIND_RATING_MATRIX,
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
        "kind": KIND_RATING_MATRIX,
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
    # Placeholder — criteria to be supplied.
    "culture": {
        "form_type": "culture",
        "kind": KIND_RATING_MATRIX,
        "title": "Culture Checklist",
        "description": "Monthly HOD culture rating for each team member.",
        "available": False,
        "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
        "criteria": [],
    },
    # Yes/No checklist answered by the MD. Fill `questions` to activate; each is
    # {"id": "...", "title": "...", "desc": "..."}. `available` flips True once populated.
    "implementation_feedback": {
        "form_type": "implementation_feedback",
        "kind": KIND_YESNO_CHECKLIST,
        "title": "Implementation Update Feedback",
        "description": "Monthly implementation update feedback submitted by the MD (Yes/No + remark).",
        "available": False,
        "respondent": "MD",
        "questions": [],
    },
}


def get_definition(form_type: str) -> Optional[dict]:
    return FORM_DEFINITIONS.get(form_type)


def form_kind(form_type: str) -> Optional[str]:
    d = FORM_DEFINITIONS.get(form_type) or {}
    return d.get("kind")


def criteria_codes(form_type: str) -> List[str]:
    d = FORM_DEFINITIONS.get(form_type) or {}
    return [c["code"] for c in d.get("criteria", [])]


def question_map(form_type: str) -> Dict[str, dict]:
    d = FORM_DEFINITIONS.get(form_type) or {}
    return {str(q["id"]): q for q in d.get("questions", [])}


# ─────────────────────────────────────────────────────────────
# rating_matrix submission models (cell-level, partial submission)
# One "cell" = one team member rated on one criterion.
# ─────────────────────────────────────────────────────────────
class RatingCell(BaseModel):
    criterion_code: str
    member_id: str
    member_name: str
    designation: Optional[str] = None
    employee_id: Optional[str] = None
    rating: int

    @field_validator("criterion_code", "member_id", "member_name")
    @classmethod
    def _required(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("criterion_code, member_id and member_name are required")
        return str(v).strip()

    @field_validator("rating")
    @classmethod
    def _rating_in_range(cls, v: int) -> int:
        if not isinstance(v, int) or v < SCALE_MIN or v > SCALE_MAX:
            raise ValueError(f"rating must be an integer between {SCALE_MIN} and {SCALE_MAX}")
        return v


class RatingSubmissionCreate(BaseModel):
    company_id: str
    period: str
    hod_id: str
    hod_name: Optional[str] = None
    ratings: List[RatingCell]

    @field_validator("company_id", "period", "hod_id")
    @classmethod
    def _required(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("company_id, period and hod_id are required")
        return str(v).strip()

    @field_validator("ratings")
    @classmethod
    def _ratings_non_empty(cls, v: List[RatingCell]) -> List[RatingCell]:
        if not v:
            raise ValueError("At least one rating is required")
        return v


# ─────────────────────────────────────────────────────────────
# yesno_checklist submission models
# ─────────────────────────────────────────────────────────────
class FeedbackAnswer(BaseModel):
    question_id: str
    question: Optional[str] = ""       # snapshot of the question text at answer time
    checked: bool = False              # True = Yes, False = No
    remark: Optional[str] = ""

    @field_validator("question_id")
    @classmethod
    def _qid_required(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("question_id is required")
        return str(v).strip()


class FeedbackSubmissionCreate(BaseModel):
    company_id: str
    period: str
    md_id: str
    md_name: Optional[str] = None
    answers: List[FeedbackAnswer]

    @field_validator("company_id", "period", "md_id")
    @classmethod
    def _required(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("company_id, period and md_id are required")
        return str(v).strip()

    @field_validator("answers")
    @classmethod
    def _answers_non_empty(cls, v: List[FeedbackAnswer]) -> List[FeedbackAnswer]:
        if not v:
            raise ValueError("At least one answer is required")
        return v
