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
COLL_IRM_CONFIG = "irm_configs"   # one row per company — the editable weightages
COLL_IRM_SCORES = "irm_scores"    # optional per (company, period, person) snapshot

# Parameter source kinds — decides how the achievement % is derived.
SOURCE_TASK = "task"   # counted:  achieved ÷ assigned
SOURCE_FORM = "form"   # rated:    rating sum ÷ max possible

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


class IRMConfig(BaseModel):
    company_id: str
    weightages: Dict[str, float] = Field(default_factory=default_weightages)
    updated_by: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# Indexes provisioned at startup (mirrors TPMS_INDEXES in app/models/tpms.py).
IRM_INDEXES = [
    (COLL_IRM_CONFIG, [("company_id", 1)], {"unique": True, "name": "uniq_company"}),
    (COLL_IRM_SCORES, [("company_id", 1), ("period", 1), ("person_id", 1)],
     {"unique": True, "name": "uniq_company_period_person"}),
    (COLL_IRM_SCORES, [("company_id", 1), ("period", 1)], {"name": "by_company_period"}),
]
