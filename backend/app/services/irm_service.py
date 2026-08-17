"""
IRM ▸ calculation engine.

Read-only over existing data: nothing here writes to tasks or to TPMS form submissions.
It reads the company's weightage config, derives each person's achievement % per
parameter, applies the configured weightage, and sums.

    Achievement %  = (achieved ÷ assigned) × 100          task-type parameters
                   = (Σ rating ÷ (n × 5)) × 100           form-type parameters
    Weighted Score = (Achievement % × Weightage) ÷ 100
    Final IRM      = Σ Weighted Score

No weightage literal appears below — every number comes from `irm_configs` (seeded
from app.models.irm.IRM_PARAMETERS the first time a company is read). Change a
weightage and the very next read recomputes with it; nothing is cached.

MISSING DATA
------------
A parameter with nothing to score (no tasks assigned that month, HOD hasn't rated the
person yet) reports `achievement: None` and contributes 0 — never a division by zero
and never a silent 0% that reads like a real failure. Because that dilutes the total,
each row also carries `applicable_weightage` (the weightage that DID have data) and
`final_irm_applicable` (the score rebased onto it), so a partially-scored month can be
read honestly. `final_irm` stays the plain out-of-100 sum the sheet specifies.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.db.mongodb import get_collection
from app.models.forms import SCALE_MAX, submission_collection
from app.models.irm import (
    COLL_IRM_CONFIG, COLL_IRM_SCORES,
    IRM_PARAMETERS,
    SOURCE_FORM, SOURCE_TASK,
    TOTAL_WEIGHTAGE, WEIGHTAGE_EPSILON,
    default_weightages,
)
from app.models.tpms import period_tokens
from app.services.report_service import fetch_tasks, doer_ids, is_delegated
from app.routes.tasks import _resolve_workflow_status

logger = logging.getLogger(__name__)

# The user collections a company's people live in (same union as TPMS ▸ Forms members).
PERSON_COLLECTIONS = ("staff", "learners")


# ─────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────
def current_period() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def period_bounds(period: str) -> tuple:
    """'YYYY-MM' → (start_iso, end_iso) covering the whole month.

    Task documents store `start` as an ISO string, so the window is compared as text —
    which is why the bounds are produced in the same ISO shape.
    """
    try:
        year, month = int(period[:4]), int(period[5:7])
        first = datetime(year, month, 1)
    except (TypeError, ValueError, IndexError):
        raise ValueError(f"Invalid period '{period}' — expected YYYY-MM")
    next_first = datetime(year + (month == 12), (month % 12) + 1, 1)
    last_moment = next_first - timedelta(microseconds=1)
    return first.isoformat(), last_moment.isoformat()


def _pct(part: float, whole: float) -> Optional[float]:
    """part/whole as a percentage, or None when there is nothing to divide by."""
    if not whole:
        return None
    return round(part / whole * 100, 2)


def _display_name(u: dict) -> str:
    return (
        u.get("full_name")
        or f"{u.get('first_name', '') or ''} {u.get('last_name', '') or ''}".strip()
        or u.get("email")
        or "Unknown"
    )


# ─────────────────────────────────────────────────────────────
# Weightage config — the editable cells from the sheet
# ─────────────────────────────────────────────────────────────
async def get_weightages(company_id: str) -> Dict[str, float]:
    """The company's weightage map, seeded from the registry for anything unset.

    A parameter added to the registry later inherits its default rather than scoring
    0 for every company that saved a config before it existed.
    """
    doc = await get_collection(COLL_IRM_CONFIG).find_one({"company_id": str(company_id)})
    weights = default_weightages()
    for code, value in ((doc or {}).get("weightages") or {}).items():
        if code in weights:
            try:
                weights[code] = round(float(value), 2)
            except (TypeError, ValueError):
                continue
    return weights


async def get_config(company_id: str) -> dict:
    """Weightages plus the parameter metadata the UI renders the sheet from."""
    doc = await get_collection(COLL_IRM_CONFIG).find_one({"company_id": str(company_id)})
    weights = await get_weightages(company_id)
    parameters = [{
        "code": p["code"],
        "name": p["name"],
        "description": p.get("description", ""),
        "source": p["source"],
        "default_weightage": p["default_weightage"],
        "weightage": weights[p["code"]],
    } for p in IRM_PARAMETERS]
    total = round(sum(weights.values()), 2)
    return {
        "company_id": str(company_id),
        "parameters": parameters,
        "weightages": weights,
        "total_weightage": total,
        "required_total": TOTAL_WEIGHTAGE,
        "is_valid": abs(total - TOTAL_WEIGHTAGE) <= WEIGHTAGE_EPSILON,
        "is_customised": bool(doc),
        "updated_at": (doc or {}).get("updated_at"),
        "updated_by": (doc or {}).get("updated_by"),
    }


async def save_weightages(company_id: str, weightages: Dict[str, float], user: dict) -> dict:
    """Persist the weightage column. The 100% rule is enforced by IRMConfigUpdate before
    this is reached; it is re-checked here so a direct service call can't bypass it."""
    total = round(sum(weightages.values()), 2)
    if abs(total - TOTAL_WEIGHTAGE) > WEIGHTAGE_EPSILON:
        raise ValueError(
            f"Total weightage must be exactly {TOTAL_WEIGHTAGE:g}% (currently {total:g}%)"
        )
    await get_collection(COLL_IRM_CONFIG).update_one(
        {"company_id": str(company_id)},
        {"$set": {
            "company_id": str(company_id),
            "weightages": {c: round(float(w), 2) for c, w in weightages.items()},
            "updated_by": (user or {}).get("full_name") or (user or {}).get("email"),
            "updated_at": datetime.utcnow(),
        },
         "$setOnInsert": {"created_at": datetime.utcnow()}},
        upsert=True,
    )
    return await get_config(company_id)


# ─────────────────────────────────────────────────────────────
# Raw achievement inputs
# ─────────────────────────────────────────────────────────────
async def load_people(company_id: str) -> Dict[str, dict]:
    """{person_id: {...}} for the company's active roster.

    Keyed by Mongo _id. `employee_id` is captured too because TPMS rating cells may be
    written against either identifier (see routes/forms.py) — _form_totals maps those
    back onto the person.
    """
    people: Dict[str, dict] = {}
    query = {"company_id": str(company_id), "is_active": {"$ne": False}}
    for coll in PERSON_COLLECTIONS:
        for u in await get_collection(coll).find(query).to_list(2000):
            pid = str(u["_id"])
            people[pid] = {
                "person_id": pid,
                "name": _display_name(u),
                "email": u.get("email"),
                "employee_id": u.get("employee_id") or u.get("emp_id") or u.get("emp_code"),
                "designation": u.get("designation"),
                "department": u.get("department"),
                "role": u.get("role"),
            }
    return people


async def _task_totals(company_id: str, period: str, people: Dict[str, dict]) -> Dict[str, dict]:
    """{person_id: {"task": {assigned, achieved}, "delegation": {assigned, achieved}}}

    A task counts for whoever DOES it (`doer_ids`), split by how it reached them:
    delegated to them by someone else → Delegation Score; their own → Task.
    """
    start_iso, end_iso = period_bounds(period)
    tasks = await fetch_tasks(start_iso, end_iso)
    cid = str(company_id)

    totals = {pid: {"task": {"assigned": 0, "achieved": 0},
                    "delegation": {"assigned": 0, "achieved": 0}} for pid in people}

    for doc in tasks:
        if str(doc.get("company_id") or "") != cid:
            continue  # a company's IRM only counts that company's tasks
        bucket = "delegation" if is_delegated(doc) else "task"
        completed = _resolve_workflow_status(doc) == "completed"
        for pid in doer_ids(doc):
            row = totals.get(pid)
            if row is None:
                continue  # doer is not on this company's active roster
            row[bucket]["assigned"] += 1
            if completed:
                row[bucket]["achieved"] += 1
    return totals


async def _form_totals(company_id: str, period: str, form_type: str,
                       people: Dict[str, dict]) -> Dict[str, dict]:
    """{person_id: {"points": Σ rating, "max_points": n × SCALE_MAX, "ratings": n}}

    Rating matrices store one cell per (criterion, member) — ratings.{code}.{member_id}
    — so a member rated on 3 of 5 criteria is scored out of 3, not penalised for the
    two the HOD skipped.
    """
    coll = submission_collection(form_type)
    totals = {pid: {"points": 0.0, "max_points": 0.0, "ratings": 0} for pid in people}
    if not coll:
        return totals

    # employee_id → person_id, because a cell may be keyed by either.
    alias = {str(p["employee_id"]): pid for pid, p in people.items() if p.get("employee_id")}

    docs = await get_collection(coll).find({
        "company_id": str(company_id),
        "period": {"$in": period_tokens(period)},
    }).to_list(2000)

    for d in docs:
        for _code, members in (d.get("ratings") or {}).items():
            for member_id, cell in (members or {}).items():
                pid = member_id if member_id in totals else alias.get(str(member_id))
                if pid is None:
                    continue
                rating = (cell or {}).get("rating")
                if not isinstance(rating, (int, float)):
                    continue
                row = totals[pid]
                row["points"] += float(rating)
                row["max_points"] += float(SCALE_MAX)
                row["ratings"] += 1
    return totals


# ─────────────────────────────────────────────────────────────
# The calculation
# ─────────────────────────────────────────────────────────────
def _build_row(person: dict, weights: Dict[str, float],
               task_totals: dict, form_totals: Dict[str, dict]) -> dict:
    """One person's IRM — every intermediate value kept so the maths stays auditable."""
    breakdown: List[dict] = []
    final_irm = 0.0
    applicable_weightage = 0.0

    for p in IRM_PARAMETERS:
        code = p["code"]
        weightage = float(weights.get(code, 0.0))

        if p["source"] == SOURCE_TASK:
            counts = (task_totals or {}).get(code) or {"assigned": 0, "achieved": 0}
            achieved, assigned = counts["achieved"], counts["assigned"]
            achievement = _pct(achieved, assigned)
            detail = {"achieved": achieved, "assigned": assigned}
        else:
            f = (form_totals.get(code) or {})
            achievement = _pct(f.get("points", 0.0), f.get("max_points", 0.0))
            detail = {
                "achieved": round(f.get("points", 0.0), 2),
                "assigned": round(f.get("max_points", 0.0), 2),
                "ratings": f.get("ratings", 0),
                "scale_max": SCALE_MAX,
            }

        has_data = achievement is not None
        # (Achievement % × Weightage) ÷ 100 — the sheet's formula, verbatim.
        weighted = round(achievement * weightage / 100, 2) if has_data else 0.0
        final_irm += weighted
        if has_data:
            applicable_weightage += weightage

        breakdown.append({
            "code": code,
            "name": p["name"],
            "source": p["source"],
            "weightage": round(weightage, 2),
            "achievement": achievement,          # None = nothing to score
            "weighted_score": weighted,
            "max_score": round(weightage, 2),    # the most this parameter can contribute
            "has_data": has_data,
            **detail,
        })

    final_irm = round(final_irm, 2)
    applicable_weightage = round(applicable_weightage, 2)
    return {
        **person,
        "parameters": breakdown,
        "final_irm": final_irm,
        "total_weightage": round(sum(weights.values()), 2),
        # Rebased onto only the parameters that had data — None when nothing did.
        "applicable_weightage": applicable_weightage,
        "final_irm_applicable": (round(final_irm / applicable_weightage * 100, 2)
                                 if applicable_weightage else None),
        "has_data": applicable_weightage > 0,
    }


async def compute_company_irm(company_id: str, period: Optional[str] = None,
                              person_id: Optional[str] = None) -> dict:
    """Every person's IRM for a company and period (or just one person).

    Always computed live from the current config, so an admin's weightage edit is
    reflected on the next call with no recalculation step in between.
    """
    period = period or current_period()
    period_bounds(period)  # validate early — a bad period should 400, not score 0

    weights = await get_weightages(company_id)
    people = await load_people(company_id)
    if person_id:
        people = {pid: p for pid, p in people.items() if pid == str(person_id)}

    tasks = await _task_totals(company_id, period, people)
    forms = {p["code"]: await _form_totals(company_id, period, p["form_type"], people)
             for p in IRM_PARAMETERS if p["source"] == SOURCE_FORM}

    rows = [
        _build_row(
            person,
            weights,
            tasks.get(pid, {}),
            {code: totals.get(pid, {}) for code, totals in forms.items()},
        )
        for pid, person in people.items()
    ]
    # Highest IRM first; people with no data at all sink to the bottom.
    rows.sort(key=lambda r: (r["has_data"], r["final_irm"]), reverse=True)

    scored = [r for r in rows if r["has_data"]]
    total_weightage = round(sum(weights.values()), 2)
    return {
        "company_id": str(company_id),
        "period": period,
        "weightages": weights,
        "total_weightage": total_weightage,
        "is_valid_weightage": abs(total_weightage - TOTAL_WEIGHTAGE) <= WEIGHTAGE_EPSILON,
        "parameters": [{"code": p["code"], "name": p["name"], "source": p["source"],
                        "weightage": weights.get(p["code"], 0.0)} for p in IRM_PARAMETERS],
        "rows": rows,
        "summary": {
            "people": len(rows),
            "scored": len(scored),
            "average_irm": round(sum(r["final_irm"] for r in scored) / len(scored), 2) if scored else None,
            "highest": scored[0]["final_irm"] if scored else None,
            "lowest": scored[-1]["final_irm"] if scored else None,
        },
    }


async def recalculate_and_store(company_id: str, period: Optional[str] = None) -> dict:
    """Snapshot the computed IRM into `irm_scores` for history/reporting.

    The API always serves freshly computed numbers, so this is a record of what the
    score was under the weightages in force — not a cache the reads depend on.
    """
    result = await compute_company_irm(company_id, period)
    now = datetime.utcnow()
    col = get_collection(COLL_IRM_SCORES)

    for row in result["rows"]:
        await col.update_one(
            {"company_id": result["company_id"], "period": result["period"],
             "person_id": row["person_id"]},
            {"$set": {
                "company_id": result["company_id"],
                "period": result["period"],
                "person_id": row["person_id"],
                "person_name": row.get("name"),
                "weightages": result["weightages"],
                "parameters": row["parameters"],
                "final_irm": row["final_irm"],
                "final_irm_applicable": row["final_irm_applicable"],
                "applicable_weightage": row["applicable_weightage"],
                "computed_at": now,
            }},
            upsert=True,
        )

    logger.info("IRM recalculated: %s rows [company=%s period=%s]",
                len(result["rows"]), result["company_id"], result["period"])
    return {"company_id": result["company_id"], "period": result["period"],
            "recalculated": len(result["rows"]), "computed_at": now}
