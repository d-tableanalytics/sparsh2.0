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
        "title": "Accountability Rating",
        "description": "Monthly HOD accountability rating for each team member.",
        "available": True,
        # audience — who fills this on the client side:
        #   "hod" → each HOD rates their own team members
        #   "all" → every client-side user submits their own response
        "audience": "hod",
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
        "title": "Ownership Rating",
        "description": "Monthly HOD ownership rating for each team member.",
        "available": True,
        "audience": "hod",
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
    # Culture — an HOD rates each of their team members, exactly like Accountability and
    # Ownership. (Source of truth: HOD_Culture/code.js, which is byte-identical to the
    # Accountability form apart from sheet names + template columns. It builds the team
    # from HOD_IDs and writes one row per question × employee. The 261 rows in
    # HOD_Culture_Responses match that shape.)
    # NOTE: the Activity sheet marks "Culture Rating" as Company-wise — that governs
    # scheduling/upload scope only, NOT who fills the form.
    "culture": {
        "form_type": "culture",
        "kind": KIND_RATING_MATRIX,
        "title": "Culture Rating",
        "description": "Monthly HOD culture rating for each team member.",
        "available": True,
        "audience": "hod",
        "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
        "criteria": [
            {"code": "C1", "title": "Works in the Team",
             "prompt": "Supportive and works as a team"},
            {"code": "C2", "title": "Problem Solving Approach",
             "prompt": "Acts as a problem solver in day-to-day work situations and approches with multiple solutions."},
            {"code": "C3", "title": "Carrying Pocket Diary",
             "prompt": "Carries the Pocket Diary at all times as required"},
            {"code": "C4", "title": "Understanding the Core Ideology",
             "prompt": "Is aware of company core values and actively practices them"},
            {"code": "C5", "title": "Customer First Attitude",
             "prompt": "Exhibits a customer-first attitude for internal and external customers"},
        ],
    },
    # Yes/No checklist answered by the company's MD only — not every client-side user.
    # (Source of truth: Implementation_Update_Feedback/code.js, which resolves the
    # respondent as the MD and writes MD_ID / MD_Name columns.)
    # NOTE: Q6 asks for a list of departments — it is a free-text question living in a
    # Yes/No form. The AppScript stores it as Yes/No with the real answer in `remark`;
    # that behaviour is reproduced here deliberately.
    "implementation_feedback": {
        "form_type": "implementation_feedback",
        "kind": KIND_YESNO_CHECKLIST,
        "title": "Implementation Update Feedback",
        "description": "Monthly implementation update feedback submitted by the MD (Yes/No + remark).",
        "available": True,
        "audience": "md",
        "respondent": "md",
        "questions": [
            {"id": "Q1",  "title": "Are you receiving ORM score?", "desc": ""},
            {"id": "Q2",  "title": "Are you receiving process audit scores for all departments?", "desc": ""},
            {"id": "Q3",  "title": "Are CSI (Customer Satisfaction Index) scores being reviewed to identify improvement areas?", "desc": ""},
            {"id": "Q4",  "title": "Were actions taken on TEI (Team Engagement Index) areas to improve team engagement?", "desc": ""},
            {"id": "Q5",  "title": "Is the OHL moving towards the desired pyramid structure month on month through hiring, promotions, and structure corrections?", "desc": ""},
            {"id": "Q6",  "title": "Please mention for which departments you are receiving DRM scores?", "desc": ""},
            {"id": "Q7",  "title": "Is your implementation team making schedules and getting RRO done for IRM (Individual Result Matrix)?", "desc": ""},
            {"id": "Q8",  "title": "Are Weekly Review Meetings (WRM) happening?", "desc": ""},
            {"id": "Q9",  "title": "Are Monthly Management Reviews (MMR) being conducted?", "desc": ""},
            {"id": "Q10", "title": "Are A&O ratings happening?", "desc": ""},
            {"id": "Q11", "title": "Are culture ratings happening?", "desc": ""},
            {"id": "Q12", "title": "Are leadership scoring happening?", "desc": ""},
            {"id": "Q13", "title": "Are you receiving calendars for leaders?", "desc": ""},
            {"id": "Q14", "title": "Do you feel the implementation is moving forward with the expected speed?", "desc": ""},
            {"id": "Q15", "title": "Do teams have sufficient leadership support and decision-making speed to implement the framework?", "desc": ""},
        ],
    },
}


# ─────────────────────────────────────────────────────────────
# Physical storage — one dedicated collection ("table") per form.
# submission_collection(form_type) is the single source of truth used by the
# routes and by the DB provisioning (startup hook + scripts/setup_form_collections.py).
# ─────────────────────────────────────────────────────────────
FORM_COLLECTIONS: Dict[str, str] = {
    "accountability":         "tpms_accountability",
    "ownership":              "tpms_ownership",
    "culture":                "tpms_culture",
    "implementation_feedback": "tpms_implementation_feedback",
}


def submission_collection(form_type: str) -> Optional[str]:
    """The collection a form's submissions are stored in (one table per form)."""
    return FORM_COLLECTIONS.get(form_type)


# ─────────────────────────────────────────────────────────────
# Activity catalogue — the Success-Measure activities scheduled on the calendar and
# scored on the client dashboard. Keep in sync with the frontend Schedule Calendar list.
# ─────────────────────────────────────────────────────────────
ACTIVITY_CATALOGUE = [
    "Org Structure Update",
    "DRM & KPI data available",
    "Calendar Discipline",
    "WRM",
    "Monthly Management Review (MMR)",
    "One pager Memo",
    "Action Closure Review",
    "Accountability & Ownership Rating",
    "Culture Rating",
    "RRO",
    "Implementation Update Feedback",
    "Team Engagement Index",
    "Customer Satisfaction Index",
    "Organization Result Matrix",
]

# Activities whose "Actual Score %" is derived from a TPMS form submission.
# The value is the list of form_types averaged for that activity's score.
ACTIVITY_FORM_MAP = {
    "Accountability & Ownership Rating": ["accountability", "ownership"],
    "Culture Rating": ["culture"],
    "Implementation Update Feedback": ["implementation_feedback"],
}


def get_definition(form_type: str) -> Optional[dict]:
    return FORM_DEFINITIONS.get(form_type)


def form_kind(form_type: str) -> Optional[str]:
    d = FORM_DEFINITIONS.get(form_type) or {}
    return d.get("kind")


def form_audience(form_type: str) -> str:
    """Who fills this form on the client side:
      'hod' — each HOD rates their own team members (Accountability/Ownership/Culture)
      'md'  — only the company's MD responds (Implementation Feedback)
      'all' — every client-side user submits their own response
    Defaults to 'hod'."""
    d = FORM_DEFINITIONS.get(form_type) or {}
    return d.get("audience", "hod")


# audience → the client-side `department` value required to submit. 'all' imposes none.
AUDIENCE_DEPARTMENT = {"hod": "hod", "md": "md"}


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
