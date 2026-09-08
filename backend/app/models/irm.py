"""
IRM — Individual Result Matrix.

A per-PERSON score out of 100, built from four evaluation parameters. Each parameter
first produces its own achievement %, that % is then scaled by the parameter's
configured weightage, and the weighted scores are summed:

    Achievement %  = (achieved ÷ total assigned) × 100      [task-type parameters]
                   = (rating sum ÷ (rating count × 5)) × 100 [form-type parameters]
    Weighted Score = (Achievement % × Weightage) ÷ 100
    Final IRM      = Σ Weighted Score                        (out of 100)

WEIGHTAGES ARE DATA, NOT CODE
-----------------------------
The numbers below are SEED values used only the first time a company opens the module
(and as the fallback when no row exists yet). Every calculation reads the weightage
from `irm_configs`, so an admin edit takes effect on the next read — there is no
recalculation job to wait for and no weightage literal anywhere in the maths. See
app/services/irm_service.py.

The four parameters map onto data the ERP already captures:
  task           → non-delegated tasks where the person is the doer
  delegation     → tasks delegated TO the person (assigned_to == "other")
  culture        → TPMS `culture` rating matrix (their HOD's 0-5 ratings of them)
  accountability → TPMS `accountability` rating matrix (same shape)
"""
from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Optional
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# Collections
# ─────────────────────────────────────────────────────────────
COLL_IRM_CONFIG = "irm_configs"   # one row per company — the DEFAULT weightages
COLL_IRM_SCORES = "irm_scores"    # optional per (company, period, person) snapshot
# One row per (company, person) — an override for people whose mix differs from the
# company default. Deliberately a SEPARATE collection rather than a field on irm_configs:
# the company row keeps its exact meaning and existing documents are never rewritten, so a
# company that never sets an override behaves precisely as it did before.
COLL_IRM_PERSON_CONFIG = "irm_person_configs"
# Imported attendance — one row per (company, person, date) carrying the day's punches.
# Import is the ONLY writer: there is deliberately no endpoint that marks a day by hand,
# so the punch times always trace back to whatever the biometric/HR export said.
COLL_IRM_ATTENDANCE = "irm_attendance"

# Parameter source kinds — decides how the achievement % is derived.
SOURCE_TASK = "task"   # counted:  achieved ÷ assigned
SOURCE_FORM = "form"   # rated:    rating sum ÷ max possible
SOURCE_ATTENDANCE = "attendance"   # punched: punctual days ÷ days present

# ─────────────────────────────────────────────────────────────
# Shift rule — what "punctual" means for a company.
#
# Punctuality cannot be derived from punch times alone: 09:41 is early for one company and
# late for another. The shift is therefore configuration, stored on the company's own
# irm_configs row (additive — a company that never sets one uses these values), and the
# grace period is separate from the shift so "we start at 9:30, 10 minutes is fine" can be
# said directly instead of being smuggled into the start time.
# ─────────────────────────────────────────────────────────────
SHIFT_START_DEFAULT = "09:30"
SHIFT_END_DEFAULT = "18:30"
SHIFT_GRACE_DEFAULT = 10        # minutes


def default_shift() -> Dict[str, object]:
    return {"start": SHIFT_START_DEFAULT, "end": SHIFT_END_DEFAULT,
            "grace_minutes": SHIFT_GRACE_DEFAULT}


# ─────────────────────────────────────────────────────────────
# Per-task weight — how much ONE task counts for inside the Task / Delegation parameters.
#
# Distinct from the parameter weightages above, which decide how the five parameters trade
# off against each other. This decides how two tasks trade off against each other INSIDE
# one of them. 1.0 is the neutral value and the default, so every task already in the
# database keeps counting exactly as it always did.
# ─────────────────────────────────────────────────────────────
TASK_WEIGHT_DEFAULT = 1.0
TASK_WEIGHT_MIN = 0.1
TASK_WEIGHT_MAX = 10.0

# The weightages must add up to exactly this.
TOTAL_WEIGHTAGE = 100.0
# Float tolerance for that equality check (0.01 == one hundredth of a percentage point).
WEIGHTAGE_EPSILON = 0.01


# ─────────────────────────────────────────────────────────────
# Parameter registry — the rows of the IRM evaluation sheet.
# `default_weightage` seeds a company's first config and nothing else.
# ─────────────────────────────────────────────────────────────
IRM_PARAMETERS: List[dict] = [
    {
        "code": "task",
        "name": "Task",
        "default_weightage": 25.0,
        "source": SOURCE_TASK,
        "delegated": False,
        "description": "Target achievement on the person's own (non-delegated) tasks.",
    },
    {
        "code": "delegation",
        "name": "Delegation Score",
        "default_weightage": 30.0,
        "source": SOURCE_TASK,
        "delegated": True,
        "description": "Completion of tasks delegated to the person by someone else.",
    },
    {
        "code": "culture",
        "name": "Culture Form",
        "default_weightage": 25.0,
        "source": SOURCE_FORM,
        "form_type": "culture",
        "description": "Monthly Culture rating submitted by the person's HOD.",
    },
    {
        "code": "accountability",
        "name": "Accountability Form",
        "default_weightage": 20.0,
        "source": SOURCE_FORM,
        "form_type": "accountability",
        "description": "Monthly Accountability rating submitted by the person's HOD.",
    },
    {
        "code": "punctuality",
        "name": "Punctuality",
        # Seeded at ZERO on purpose. The four parameters above already total 100, and every
        # company that has saved a column saved those four. A non-zero seed would push each
        # of those existing columns to more than 100 the moment this parameter shipped,
        # which IRMConfigUpdate would then refuse to re-save. At zero the arithmetic is
        # unchanged for everyone, and a company opts in by taking weightage from the others.
        "default_weightage": 0.0,
        "source": SOURCE_ATTENDANCE,
        "description": "On-time arrival and full-shift departure, from imported punch times.",
    },
]

PARAMETER_CODES: List[str] = [p["code"] for p in IRM_PARAMETERS]
PARAMETER_BY_CODE: Dict[str, dict] = {p["code"]: p for p in IRM_PARAMETERS}


def default_weightages() -> Dict[str, float]:
    """Seed weightages, as a fresh dict (callers mutate their copy)."""
    return {p["code"]: float(p["default_weightage"]) for p in IRM_PARAMETERS}


def parameter_name(code: str) -> str:
    return (PARAMETER_BY_CODE.get(code) or {}).get("name", code)


# ─────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────
class IRMWeightageItem(BaseModel):
    """One editable weightage cell from the sheet."""
    code: str
    weightage: float

    @field_validator("code")
    @classmethod
    def _known_code(cls, v: str) -> str:
        code = str(v or "").strip()
        if code not in PARAMETER_BY_CODE:
            raise ValueError(f"Unknown IRM parameter '{v}'")
        return code

    @field_validator("weightage")
    @classmethod
    def _in_range(cls, v: float) -> float:
        try:
            w = round(float(v), 2)
        except (TypeError, ValueError):
            raise ValueError("weightage must be a number")
        if w < 0 or w > TOTAL_WEIGHTAGE:
            raise ValueError(f"weightage must be between 0 and {TOTAL_WEIGHTAGE:g}")
        return w


class IRMConfigUpdate(BaseModel):
    """Save the weightage column. Every parameter must be present exactly once and the
    column must total 100 — the sheet's GRAND TOTAL row is a hard rule, not a hint."""
    weightages: List[IRMWeightageItem]

    @field_validator("weightages")
    @classmethod
    def _complete_and_totals_100(cls, items: List[IRMWeightageItem]) -> List[IRMWeightageItem]:
        codes = [i.code for i in items]
        if len(codes) != len(set(codes)):
            raise ValueError("Each IRM parameter may appear only once")
        missing = [c for c in PARAMETER_CODES if c not in codes]
        if missing:
            names = ", ".join(parameter_name(c) for c in missing)
            raise ValueError(f"Missing weightage for: {names}")

        total = round(sum(i.weightage for i in items), 2)
        if abs(total - TOTAL_WEIGHTAGE) > WEIGHTAGE_EPSILON:
            raise ValueError(
                f"Total weightage must be exactly {TOTAL_WEIGHTAGE:g}% (currently {total:g}%)"
            )
        return items

    def as_map(self) -> Dict[str, float]:
        return {i.code: i.weightage for i in self.weightages}


# Where a resolved weightage map came from. Reported alongside every score so the screen
# can say whether a person is on their own mix or the company's.
SCOPE_PERSON = "person"
SCOPE_COMPANY = "company"
SCOPE_DEFAULT = "default"   # neither row exists — the registry seeds are in force


def _hhmm(value, field: str) -> str:
    """'9:5' → '09:05'. Raises on anything that is not a 24-hour clock time."""
    raw = str(value or "").strip()
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"{field} must be a 24-hour time like 09:30")
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"{field} must be a 24-hour time like 09:30")
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"{field} must be a 24-hour time like 09:30")
    return f"{hh:02d}:{mm:02d}"


class IRMShiftUpdate(BaseModel):
    """The company's shift rule. Saved from IRM Setup, read by the punctuality parameter."""
    start: str = SHIFT_START_DEFAULT
    end: str = SHIFT_END_DEFAULT
    grace_minutes: int = SHIFT_GRACE_DEFAULT

    @field_validator("start")
    @classmethod
    def _start(cls, v):
        return _hhmm(v, "Shift start")

    @field_validator("end")
    @classmethod
    def _end(cls, v):
        return _hhmm(v, "Shift end")

    @field_validator("grace_minutes")
    @classmethod
    def _grace(cls, v):
        try:
            g = int(v)
        except (TypeError, ValueError):
            raise ValueError("Grace must be a whole number of minutes")
        if g < 0 or g > 240:
            raise ValueError("Grace must be between 0 and 240 minutes")
        return g

    def as_map(self) -> Dict[str, object]:
        return {"start": self.start, "end": self.end, "grace_minutes": self.grace_minutes}


class IRMConfig(BaseModel):
    company_id: str
    weightages: Dict[str, float] = Field(default_factory=default_weightages)
    updated_by: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# Indexes provisioned at startup (mirrors TPMS_INDEXES in app/models/tpms.py).
IRM_INDEXES = [
    (COLL_IRM_CONFIG, [("company_id", 1)], {"unique": True, "name": "uniq_company"}),
    (COLL_IRM_PERSON_CONFIG, [("company_id", 1), ("person_id", 1)],
     {"unique": True, "name": "uniq_company_person"}),
    (COLL_IRM_PERSON_CONFIG, [("company_id", 1)], {"name": "by_company"}),
    # One row per person per day: a re-import of the same day updates rather than
    # duplicating, which is what makes re-importing a corrected file safe.
    (COLL_IRM_ATTENDANCE, [("company_id", 1), ("person_id", 1), ("date", 1)],
     {"unique": True, "name": "uniq_company_person_date"}),
    (COLL_IRM_ATTENDANCE, [("company_id", 1), ("period", 1)], {"name": "by_company_period"}),
    (COLL_IRM_SCORES, [("company_id", 1), ("period", 1), ("person_id", 1)],
     {"unique": True, "name": "uniq_company_period_person"}),
    (COLL_IRM_SCORES, [("company_id", 1), ("period", 1)], {"name": "by_company_period"}),
]
