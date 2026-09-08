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
    COLL_IRM_CONFIG, COLL_IRM_PERSON_CONFIG, COLL_IRM_SCORES,
    IRM_PARAMETERS,
    SCOPE_COMPANY, SCOPE_DEFAULT, SCOPE_PERSON,
    SOURCE_ATTENDANCE, SOURCE_FORM, SOURCE_TASK,
    TASK_WEIGHT_DEFAULT, TASK_WEIGHT_MAX, TASK_WEIGHT_MIN,
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
def _merge_weightages(base: Dict[str, float], stored: Optional[dict]) -> Dict[str, float]:
    """Overlay a stored weightage map onto `base`, ignoring unknown or unparseable codes.

    A parameter added to the registry later inherits its default rather than scoring 0 for
    every config saved before it existed.
    """
    weights = dict(base)
    for code, value in (stored or {}).items():
        if code in weights:
            try:
                weights[code] = round(float(value), 2)
            except (TypeError, ValueError):
                continue
    return weights


async def get_weightages(company_id: str, person_id: Optional[str] = None) -> Dict[str, float]:
    """The weightage map in force — for one person, or for the company as a whole.

    Resolution is most-specific-first: the person's own override, then the company
    default, then the registry seeds. Passing no `person_id` asks for the company row,
    which is exactly what the old single-argument call meant, so every existing caller
    keeps its behaviour.
    """
    weights, _scope = await resolve_weightages(company_id, person_id)
    return weights


async def resolve_weightages(company_id: str,
                             person_id: Optional[str] = None) -> tuple:
    """(weights, scope) — scope names which row actually supplied them.

    Reported rather than inferred so the screen can say "own mix" vs "company default"
    without re-querying, and so a snapshot records what a score was actually built from.
    """
    company_doc = await get_collection(COLL_IRM_CONFIG).find_one({"company_id": str(company_id)})
    weights = _merge_weightages(default_weightages(), (company_doc or {}).get("weightages"))
    scope = SCOPE_COMPANY if company_doc else SCOPE_DEFAULT

    if person_id:
        person_doc = await get_collection(COLL_IRM_PERSON_CONFIG).find_one({
            "company_id": str(company_id), "person_id": str(person_id)})
        if person_doc:
            weights = _merge_weightages(weights, person_doc.get("weightages"))
            scope = SCOPE_PERSON
    return weights, scope


async def load_person_weightages(company_id: str) -> Dict[str, dict]:
    """{person_id: stored_weightage_map} for every override in one company.

    Fetched in a single query so scoring a roster costs one read rather than one per
    person — compute_company_irm runs this once and resolves each row from it.
    """
    rows = await get_collection(COLL_IRM_PERSON_CONFIG).find(
        {"company_id": str(company_id)}).to_list(5000)
    return {str(r.get("person_id")): (r.get("weightages") or {}) for r in rows}


async def get_config(company_id: str, person_id: Optional[str] = None) -> dict:
    """Weightages plus the parameter metadata the UI renders the sheet from.

    With `person_id` this is that person's effective sheet — their override if they have
    one, otherwise the company column they inherit. `is_customised` keeps meaning "a row
    exists at the scope being read", which is what the screen's subtitle is driven from.
    """
    if person_id:
        doc = await get_collection(COLL_IRM_PERSON_CONFIG).find_one({
            "company_id": str(company_id), "person_id": str(person_id)})
    else:
        doc = await get_collection(COLL_IRM_CONFIG).find_one({"company_id": str(company_id)})
    weights, scope = await resolve_weightages(company_id, person_id)
    parameters = [{
        "code": p["code"],
        "name": p["name"],
        "description": p.get("description", ""),
        "source": p["source"],
        "default_weightage": p["default_weightage"],
        "weightage": weights[p["code"]],
    } for p in IRM_PARAMETERS]
    total = round(sum(weights.values()), 2)
    # The shift rule travels with the config because the punctuality parameter is
    # meaningless without it — one call gives Setup both halves of the same screen.
    from app.services.irm_attendance_service import get_shift
    return {
        "company_id": str(company_id),
        "person_id": str(person_id) if person_id else None,
        "scope": scope,
        "shift": await get_shift(company_id),
        "parameters": parameters,
        "weightages": weights,
        "total_weightage": total,
        "required_total": TOTAL_WEIGHTAGE,
        "is_valid": abs(total - TOTAL_WEIGHTAGE) <= WEIGHTAGE_EPSILON,
        "is_customised": bool(doc),
        # True only when a person is being read and is riding the company column, so the
        # screen can offer "customise for this person" rather than implying they have one.
        "inherited": bool(person_id) and scope != SCOPE_PERSON,
        "updated_at": (doc or {}).get("updated_at"),
        "updated_by": (doc or {}).get("updated_by"),
    }


async def save_weightages(company_id: str, weightages: Dict[str, float], user: dict,
                          person_id: Optional[str] = None) -> dict:
    """Persist a weightage column — the company default, or one person's override.

    The 100% rule is enforced by IRMConfigUpdate before this is reached; it is re-checked
    here so a direct service call can't bypass it. It applies identically at both scopes:
    a person's sheet is still a sheet, and a column that does not total 100 cannot be read
    as a percentage of anything.
    """
    total = round(sum(weightages.values()), 2)
    if abs(total - TOTAL_WEIGHTAGE) > WEIGHTAGE_EPSILON:
        raise ValueError(
            f"Total weightage must be exactly {TOTAL_WEIGHTAGE:g}% (currently {total:g}%)"
        )
    cleaned = {c: round(float(w), 2) for c, w in weightages.items()}
    stamp = {
        "weightages": cleaned,
        "updated_by": (user or {}).get("full_name") or (user or {}).get("email"),
        "updated_at": datetime.utcnow(),
    }

    if person_id:
        await get_collection(COLL_IRM_PERSON_CONFIG).update_one(
            {"company_id": str(company_id), "person_id": str(person_id)},
            {"$set": {"company_id": str(company_id), "person_id": str(person_id), **stamp},
             "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
        )
    else:
        await get_collection(COLL_IRM_CONFIG).update_one(
            {"company_id": str(company_id)},
            {"$set": {"company_id": str(company_id), **stamp},
             "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
        )
    return await get_config(company_id, person_id)


async def clear_person_weightages(company_id: str, person_id: str) -> dict:
    """Drop one person's override so they fall back to the company column.

    Without this an override could be changed but never undone, which would make the
    company default unreachable for anyone who had ever been customised.
    """
    res = await get_collection(COLL_IRM_PERSON_CONFIG).delete_one({
        "company_id": str(company_id), "person_id": str(person_id)})
    config = await get_config(company_id, person_id)
    config["removed"] = res.deleted_count
    return config


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


def task_credit(doc: dict) -> float:
    """How much of ONE task counts as achieved, between 0 and 1.

    A task cannot be completed until every check point on it is ticked (routes/tasks.py
    enforces that on the complete call). So a task carrying a checklist already reports
    its own progress, and counting the task all-or-nothing threw that away: nine of ten
    check points done scored exactly the same as a task nobody had opened — zero — which
    made a genuinely productive month read as a failed one and gave the person no reason
    to tick anything until the last item landed.

    Completed → 1.0. Otherwise the share of check points done. A task with no checklist
    has nothing partial to measure and stays all-or-nothing, exactly as before.
    """
    if _resolve_workflow_status(doc) == "completed":
        return 1.0
    items = [c for c in (doc.get("checklist") or []) if isinstance(c, dict)]
    if not items:
        return 0.0
    done = sum(1 for c in items if c.get("completed"))
    return done / len(items)


def task_weight(doc: dict) -> float:
    """How many units of "assigned" ONE task is worth. 1.0 unless it says otherwise.

    Every task used to count the same, so a fortnight's project scored exactly as much as
    a five-minute errand and a month of small tasks could outscore a month of hard ones.
    `irm_weight` lets the person setting the task say what it is worth; absent or
    unreadable it stays 1.0, which is precisely the old behaviour — so nothing already in
    the database scores differently than it did.
    """
    try:
        w = float(doc.get("irm_weight"))
    except (TypeError, ValueError):
        return TASK_WEIGHT_DEFAULT
    if w != w:                              # NaN
        return TASK_WEIGHT_DEFAULT
    return max(TASK_WEIGHT_MIN, min(TASK_WEIGHT_MAX, round(w, 2)))


async def _task_totals(company_id: str, period: str, people: Dict[str, dict]) -> Dict[str, dict]:
    """{person_id: {"task": {...}, "delegation": {...}}} — per bucket:

        assigned   how many tasks
        achieved   credit earned, fractional (see `task_credit`)
        completed  how many finished outright
        partial    how many contributed part of a task through their checklist

    A task counts for whoever DOES it (`doer_ids`), split by how it reached them:
    delegated to them by someone else → Delegation Score; their own → Task.
    """
    start_iso, end_iso = period_bounds(period)
    tasks = await fetch_tasks(start_iso, end_iso)
    cid = str(company_id)

    def _bucket():
        # `assigned` is a sum of WEIGHTS, not a headcount, so `count` is carried alongside
        # it — the screen still wants to say "5 tasks", and 5 tasks can weigh 7.5.
        return {"assigned": 0.0, "achieved": 0.0, "completed": 0, "partial": 0, "count": 0}

    totals = {pid: {"task": _bucket(), "delegation": _bucket()} for pid in people}

    for doc in tasks:
        if str(doc.get("company_id") or "") != cid:
            continue  # a company's IRM only counts that company's tasks
        bucket = "delegation" if is_delegated(doc) else "task"
        credit = task_credit(doc)
        weight = task_weight(doc)
        for pid in doer_ids(doc):
            row = totals.get(pid)
            if row is None:
                continue  # doer is not on this company's active roster
            cell = row[bucket]
            # Both sides scale together, so the ratio is unchanged for a weight of 1 and a
            # heavier task simply counts for more of the month on both halves of it.
            cell["assigned"] += weight
            cell["achieved"] += credit * weight
            cell["count"] += 1
            if credit >= 1.0:
                cell["completed"] += 1
            elif credit > 0:
                cell["partial"] += 1
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
               task_totals: dict, form_totals: Dict[str, dict],
               scope: str = SCOPE_COMPANY,
               attendance: Optional[dict] = None) -> dict:
    """One person's IRM — every intermediate value kept so the maths stays auditable.

    `weights` is THIS person's map, which may be their own override or the company
    column. It is echoed back on the row (with the scope that produced it) so a score can
    be read without guessing which sheet it was built from.
    """
    breakdown: List[dict] = []
    final_irm = 0.0
    applicable_weightage = 0.0

    for p in IRM_PARAMETERS:
        code = p["code"]
        weightage = float(weights.get(code, 0.0))

        if p["source"] == SOURCE_ATTENDANCE:
            a = attendance or {}
            present = a.get("present", 0)
            punctual = a.get("punctual", 0)
            achievement = _pct(punctual, present)
            detail = {
                "achieved": punctual,
                "assigned": present,
                "late_in": a.get("late_in", 0),
                "early_out": a.get("early_out", 0),
                "missing_out": a.get("missing_out", 0),
            }
        elif p["source"] == SOURCE_TASK:
            counts = (task_totals or {}).get(code) or {}
            assigned = counts.get("assigned", 0)
            achieved = counts.get("achieved", 0.0)
            achievement = _pct(achieved, assigned)
            # `achieved` is credit, not a headcount — a part-finished checklist contributes
            # a fraction — so the whole/part split is sent alongside it and the screen can
            # say "3 done + 2 in progress" instead of showing a puzzling 3.6.
            detail = {
                "achieved": round(achieved, 2),
                "assigned": round(assigned, 2),
                "count": counts.get("count", 0),
                "completed": counts.get("completed", 0),
                "partial": counts.get("partial", 0),
                # True when the tasks in this bucket did not all weigh 1, so the screen can
                # explain why "3 of 5 tasks" is not the same as the percentage shown.
                "weighted": round(assigned, 2) != counts.get("count", 0),
            }
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
        "weightages": {c: round(float(w), 2) for c, w in weights.items()},
        "weightage_scope": scope,
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

    # The company column, plus every per-person override in one read. Resolving each row
    # from these two rather than querying per person keeps a 500-person roster at two
    # config reads, exactly as it was when the column was company-wide.
    company_weights, company_scope = await resolve_weightages(company_id)
    overrides = await load_person_weightages(company_id)

    people = await load_people(company_id)
    if person_id:
        people = {pid: p for pid, p in people.items() if pid == str(person_id)}

    def _weights_for(pid: str) -> tuple:
        stored = overrides.get(str(pid))
        if stored:
            return _merge_weightages(company_weights, stored), SCOPE_PERSON
        return company_weights, company_scope

    tasks = await _task_totals(company_id, period, people)
    forms = {p["code"]: await _form_totals(company_id, period, p["form_type"], people)
             for p in IRM_PARAMETERS if p["source"] == SOURCE_FORM}

    # Imported punches, scored against the company's shift rule. A month with nothing
    # imported yields no `present` days, so punctuality reports achievement None and
    # contributes nothing — the same "missing data" path every other parameter uses.
    attendance: Dict[str, dict] = {}
    if any(p["source"] == SOURCE_ATTENDANCE for p in IRM_PARAMETERS):
        from app.services.irm_attendance_service import attendance_totals
        attendance = await attendance_totals(company_id, period, people)

    rows = []
    for pid, person in people.items():
        person_weights, scope = _weights_for(pid)
        rows.append(_build_row(
            person,
            person_weights,
            tasks.get(pid, {}),
            {code: totals.get(pid, {}) for code, totals in forms.items()},
            scope,
            attendance.get(pid, {}),
        ))
    # Highest IRM first; people with no data at all sink to the bottom.
    rows.sort(key=lambda r: (r["has_data"], r["final_irm"]), reverse=True)

    scored = [r for r in rows if r["has_data"]]
    total_weightage = round(sum(company_weights.values()), 2)
    # The top-level column stays the COMPANY default — it is the sheet header, and each
    # row now carries its own `weightages` for anyone on a different mix.
    return {
        "company_id": str(company_id),
        "period": period,
        "weightages": company_weights,
        "total_weightage": total_weightage,
        "is_valid_weightage": abs(total_weightage - TOTAL_WEIGHTAGE) <= WEIGHTAGE_EPSILON,
        "customised_people": sum(1 for r in rows if r.get("weightage_scope") == SCOPE_PERSON),
        "parameters": [{"code": p["code"], "name": p["name"], "source": p["source"],
                        "weightage": company_weights.get(p["code"], 0.0)}
                       for p in IRM_PARAMETERS],
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
                # The row's OWN map, not the company column — a snapshot has to record
                # what the score was actually built from or it cannot be audited.
                "weightages": row.get("weightages") or result["weightages"],
                "weightage_scope": row.get("weightage_scope"),
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
