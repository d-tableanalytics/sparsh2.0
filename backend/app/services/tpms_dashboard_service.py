"""
TPMS ▸ dashboard aggregation.

Ports the analytics functions from `copy_of calender/code.js`:
  • getAnalytics            (:1322) → get_analytics()
  • getStaffDashboard       (:1704) → get_staff_dashboard()
  • getLearnerDashboard     (:2298) → get_learner_dashboard()
  • getEscalationDashboard  (:2863) → get_escalation_dashboard()

Every formula below is the source's, verbatim:

    pct(done, planned)  = round(done / planned × 100)          0 when planned == 0
    avgDelay            = round(delaySum / delayN, 1)          only delays > 0 counted
    statusBand          ≥95 STRONG · ≥85 GOOD · ≥70 WATCH · else AT-RISK
    trend               this period's completion vs the previous EQUAL-LENGTH window
    overdue             not Completed/Cancelled AND date < today
    pending             not Completed/Cancelled AND date >= today

`succAvg` matches activities by fuzzy substring, which is how the source reconciles
"Accountability & Ownership Rating" with the "O&A" shorthand (code.js:1414).
"""
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from app.db.mongodb import get_collection
from app.models.tpms import (
    COLL_ACTION_ITEMS, COLL_ACTIVITIES, COLL_ESCALATIONS, COLL_SUCCESS_MEASURES,
    STATUS_CANCELLED, STATUS_COMPLETED, STATUS_LAPSED, STATUS_RESCHEDULED, STATUS_SCHEDULED,
    TPMS_EVENT_KIND, period_display,
)
from app.services.tpms_schedule_service import CAL_COLLECTIONS

logger = logging.getLogger(__name__)

STAFF_ROLES = {"superadmin", "admin"}
CLIENT_ROLES = {"clientadmin", "clientuser"}


# ─────────────────────────────────────────────────────────────
# Primitives — exact ports (code.js:1488-1492)
# ─────────────────────────────────────────────────────────────
def _pct(done: int, planned: int) -> int:
    return round(done / planned * 100) if planned > 0 else 0


def _avg_delay(acc: dict) -> float:
    return round(acc["delay_sum"] / acc["delay_n"], 1) if acc["delay_n"] > 0 else 0


def _status_band(completion: int) -> str:
    if completion >= 95:
        return "STRONG"
    if completion >= 85:
        return "GOOD"
    if completion >= 70:
        return "WATCH"
    return "AT-RISK"


def _trend(acc: dict) -> str:
    cur = _pct(acc["done"], acc["planned"])
    prev = _pct(acc["prev_done"], acc["prev_planned"])
    return "Up" if cur > prev else ("Down" if cur < prev else "Flat")


def _blank() -> dict:
    return {"planned": 0, "done": 0, "pending": 0, "overdue": 0, "cancelled": 0,
            "lapsed": 0, "rescheduled": 0, "delay_sum": 0, "delay_n": 0,
            "prev_planned": 0, "prev_done": 0}


def _today() -> str:
    return date.today().isoformat()


def _period_window(period: Optional[str]) -> tuple:
    """(from, to, prev_from, prev_to) for a 'YYYY-MM'. The previous window is the same
    length immediately before, matching the source's trend comparison."""
    if period:
        year, month = int(period[:4]), int(period[5:7])
    else:
        now = date.today()
        year, month = now.year, now.month
    first = date(year, month, 1)
    last = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    span = (last - first).days + 1
    prev_to = first - timedelta(days=1)
    prev_from = prev_to - timedelta(days=span - 1)
    return first.isoformat(), last.isoformat(), prev_from.isoformat(), prev_to.isoformat()


def _in_range(d: str, a: str, b: str) -> bool:
    return bool(d) and a <= d <= b


# ─────────────────────────────────────────────────────────────
# Shared loaders
# ─────────────────────────────────────────────────────────────
async def _load_companies() -> Dict[str, dict]:
    """company_id → {name, om_key, om_name}. `owner` may hold a staff id or a plain
    name, so resolve tolerantly and fall back to the raw value."""
    staff = {}
    for s in await get_collection("staff").find({}).to_list(500):
        staff[str(s["_id"])] = (s.get("full_name")
                                or " ".join(filter(None, [s.get("first_name"), s.get("last_name")])).strip()
                                or s.get("email") or str(s["_id"]))

    out = {}
    for c in await get_collection("companies").find({}).to_list(1000):
        cid = str(c["_id"])
        owner = str(c.get("owner") or "").strip()
        out[cid] = {
            "name": c.get("name") or cid,
            "om_key": owner,
            "om_name": staff.get(owner, owner),
        }
    return out


async def _load_events(company_ids: Optional[List[str]] = None) -> List[dict]:
    query: dict = {"kind": TPMS_EVENT_KIND}
    if company_ids is not None:
        query["company_id"] = {"$in": company_ids}
    out = []
    for coll in CAL_COLLECTIONS:
        out.extend(await get_collection(coll).find(query).to_list(10000))
    return out


def _allowed_companies(user: dict, companies: Dict[str, dict],
                       scope: dict) -> Optional[List[str]]:
    """Role scoping (code.js:1364). None = everything."""
    role = (user.get("role") or "").lower()
    if scope.get("company_id"):
        return [str(scope["company_id"])]
    if role in CLIENT_ROLES and user.get("company_id"):
        return [str(user["company_id"])]
    if role not in STAFF_ROLES:
        uid = str(user.get("_id"))
        owned = [cid for cid, i in companies.items() if i["om_key"] == uid]
        return owned
    return None


async def _action_closure() -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for a in await get_collection(COLL_ACTION_ITEMS).find({}).to_list(20000):
        cid = str(a.get("company_id") or "")
        if not cid:
            continue
        acc = out.setdefault(cid, {"closed": 0, "total": 0})
        acc["total"] += 1
        if str(a.get("status") or "") == "Closed":
            acc["closed"] += 1
    return out


async def _active_escalations() -> Dict[str, int]:
    out: Dict[str, int] = {}
    for e in await get_collection(COLL_ESCALATIONS).find({"status": {"$ne": "Resolved"}}).to_list(20000):
        cid = str(e.get("company_id") or "")
        if cid:
            out[cid] = out.get(cid, 0) + 1
    return out


def _accumulate(events: List[dict], allowed: Optional[List[str]],
                companies: Dict[str, dict], window: tuple,
                om_filter: str = "") -> tuple:
    """Fold events into totals / per-company / per-OM accumulators."""
    frm, to, prev_frm, prev_to = window
    today = _today()
    allow = set(allowed) if allowed is not None else None

    totals = _blank()
    by_company: Dict[str, dict] = {}
    by_om: Dict[str, dict] = {}

    for e in events:
        cid = str(e.get("company_id") or "")
        if allow is not None and cid not in allow:
            continue
        info = companies.get(cid) or {"name": e.get("company_name") or cid, "om_key": "", "om_name": ""}
        om_key = info["om_key"]
        if om_filter and om_key != om_filter:
            continue

        day = str(e.get("start") or "")[:10]
        status = e.get("tpms_status") or STATUS_SCHEDULED
        in_cur = _in_range(day, frm, to)
        in_prev = _in_range(day, prev_frm, prev_to)
        if not in_cur and not in_prev:
            continue

        buckets = [totals, by_company.setdefault(cid, _blank())]
        if om_key:
            buckets.append(by_om.setdefault(om_key, _blank()))

        if in_prev:
            for b in buckets:
                b["prev_planned"] += 1
                if status == STATUS_COMPLETED:
                    b["prev_done"] += 1
            if not in_cur:
                continue

        for b in buckets:
            b["planned"] += 1

        if status == STATUS_COMPLETED:
            for b in buckets:
                b["done"] += 1
            completed_at = e.get("completed_at")
            if isinstance(completed_at, datetime) and day:
                diff = (completed_at.date() - date.fromisoformat(day)).days
                if diff > 0:
                    for b in buckets:
                        b["delay_sum"] += diff
                        b["delay_n"] += 1
        elif status == STATUS_CANCELLED:
            for b in buckets:
                b["cancelled"] += 1
        else:
            if status == STATUS_LAPSED:
                for b in buckets:
                    b["lapsed"] += 1
            if status == STATUS_RESCHEDULED:
                for b in buckets:
                    b["rescheduled"] += 1
            key = "overdue" if day < today else "pending"
            for b in buckets:
                b[key] += 1

    return totals, by_company, by_om


# ─────────────────────────────────────────────────────────────
# Success-measure rollups (code.js:1395)
# ─────────────────────────────────────────────────────────────
async def _success_rollup(allowed: Optional[List[str]]) -> dict:
    query: dict = {"scope": "company"}
    if allowed is not None:
        query["company_id"] = {"$in": allowed}
    rows = await get_collection(COLL_SUCCESS_MEASURES).find(query).to_list(20000)

    per_activity: Dict[str, dict] = {}
    all_sum = all_n = 0
    for r in rows:
        target, actual = r.get("score_target"), r.get("score_actual")
        if target is None and actual is None:
            continue
        ach = round((actual or 0) / target * 100) if target else (actual or 0)
        key = str(r.get("activity") or "").lower()
        acc = per_activity.setdefault(key, {"sum": 0, "n": 0})
        acc["sum"] += ach
        acc["n"] += 1
        all_sum += ach
        all_n += 1

    def avg(needles: List[str]) -> int:
        s = n = 0
        for k, acc in per_activity.items():
            if any(nd in k for nd in needles):
                s += acc["sum"]
                n += acc["n"]
        return round(s / n) if n else 0

    return {
        "oa_rating": avg(["accountability", "o&a", "ownership"]),
        "culture_score": avg(["culture"]),
        "drm_completion": avg(["drm", "kpi"]),
        "success_score": round(all_sum / all_n) if all_n else 0,
    }


# ─────────────────────────────────────────────────────────────
# Client × activity grid — shared by the Staff and Client dashboards
# ─────────────────────────────────────────────────────────────
async def _clients_grid(events: List[dict], allowed: Optional[List[str]],
                        companies: Dict[str, dict], window: tuple) -> tuple:
    frm, to, _pf, _pt = window
    today = _today()
    allow = set(allowed) if allowed is not None else None

    catalogue = await get_collection(COLL_ACTIVITIES).find(
        {"active": {"$ne": False}}
    ).to_list(200)
    activities = [{"full": a["name"], "short": a.get("short") or a["name"]} for a in catalogue]

    grid: Dict[str, dict] = {}
    for e in events:
        cid = str(e.get("company_id") or "")
        if allow is not None and cid not in allow:
            continue
        day = str(e.get("start") or "")[:10]
        if not _in_range(day, frm, to):
            continue
        activity = e.get("activity") or ""
        status = e.get("tpms_status") or STATUS_SCHEDULED

        row = grid.setdefault(cid, {
            "company_id": cid,
            "company": (companies.get(cid) or {}).get("name") or e.get("company_name") or cid,
            "cells": {}, "done": 0, "total": 0,
        })
        cell = row["cells"].setdefault(activity, {"done": 0, "total": 0, "status": "pending"})
        cell["total"] += 1
        row["total"] += 1
        if status == STATUS_COMPLETED:
            cell["done"] += 1
            row["done"] += 1
        elif status == STATUS_CANCELLED:
            cell["status"] = "cancelled"
        elif day < today:
            cell["status"] = "overdue"

    for row in grid.values():
        for cell in row["cells"].values():
            if cell["done"] >= cell["total"] and cell["total"] > 0:
                cell["status"] = "done"
        row["pct"] = _pct(row["done"], row["total"])

    rows = sorted(grid.values(), key=lambda r: (r["company"] or "").lower())
    return activities, rows


# ─────────────────────────────────────────────────────────────
# Open action items (shared)
# ─────────────────────────────────────────────────────────────
def _delay_label(days) -> str:
    if days is None or days == "":
        return "—"
    try:
        n = int(days)
    except (TypeError, ValueError):
        return "—"
    return "On time" if n <= 0 else f"{n}d"


async def _open_actions(allowed: Optional[List[str]]) -> List[dict]:
    query: dict = {"status": {"$ne": "Closed"}}
    if allowed is not None:
        query["company_id"] = {"$in": allowed}
    rows = await get_collection(COLL_ACTION_ITEMS).find(query).to_list(5000)
    out = []
    for a in rows:
        delay = a.get("delay_days") or 0
        out.append({
            "id": str(a["_id"]),
            "company": a.get("company_name") or "",
            "activity": a.get("activity") or "",
            "action": a.get("action") or "",
            "owner": a.get("owner_name") or "",
            "employee_id": a.get("owner_id") or "",
            "target": a.get("target_date") or "",
            "actual": "",
            "status": a.get("status") or "Pending",
            "learner_delay": _delay_label(a.get("learner_delay_days")),
            "staff_delay": _delay_label(a.get("staff_delay_days")),
            "follow_up": f"Overdue {delay}d" if delay else "On track",
        })
    out.sort(key=lambda r: r["company"])
    return out


# ─────────────────────────────────────────────────────────────
# 1) Admin analytics — getAnalytics (code.js:1322)
# ─────────────────────────────────────────────────────────────
async def get_analytics(user: dict, scope: dict) -> dict:
    scope = scope or {}
    companies = await _load_companies()
    allowed = _allowed_companies(user, companies, scope)
    om_filter = str(scope.get("om_id") or scope.get("smops_id") or "")
    window = _period_window(scope.get("period"))

    events = await _load_events(allowed)
    totals, by_company, by_om = _accumulate(events, allowed, companies, window, om_filter)
    closure = await _action_closure()
    escalations = await _active_escalations()
    rollup = await _success_rollup(allowed)

    def closure_pct(cid: str):
        a = closure.get(cid)
        return _pct(a["closed"], a["total"]) if a and a["total"] > 0 else ""

    clients = []
    for cid, acc in by_company.items():
        info = companies.get(cid) or {}
        completion = _pct(acc["done"], acc["planned"])
        clients.append({
            "company_id": cid,
            "company": info.get("name") or cid,
            "om": info.get("om_name") or "",
            "done": acc["done"], "pending": acc["pending"], "overdue": acc["overdue"],
            "planned": acc["planned"], "completion": completion,
            "avg_delay": _avg_delay(acc), "trend": _trend(acc),
            "status": _status_band(completion),
            "escalations": escalations.get(cid, 0),
            "action_closure": closure_pct(cid),
        })
    clients.sort(key=lambda c: (c["company"] or "").lower())

    om_companies: Dict[str, List[str]] = {}
    for cid, info in companies.items():
        if info["om_key"]:
            om_companies.setdefault(info["om_key"], []).append(cid)

    oms = []
    for om_key, acc in by_om.items():
        owned = om_companies.get(om_key, [])
        cl_closed = cl_total = esc = 0
        for cid in owned:
            a = closure.get(cid)
            if a:
                cl_closed += a["closed"]
                cl_total += a["total"]
            esc += escalations.get(cid, 0)
        oms.append({
            "om_id": om_key,
            "om": (companies.get(owned[0]) or {}).get("om_name") if owned else om_key,
            "clients": len(owned), "planned": acc["planned"], "done": acc["done"],
            "completion": _pct(acc["done"], acc["planned"]),
            "avg_delay": _avg_delay(acc), "trend": _trend(acc),
            "escalations": esc,
            "action_closure": _pct(cl_closed, cl_total) if cl_total > 0 else "",
        })
    oms.sort(key=lambda o: -o["completion"])

    top_delayed = sorted(
        [c for c in clients if c["avg_delay"] > 0 or c["overdue"] > 0],
        key=lambda c: (-c["avg_delay"], -c["overdue"]),
    )[:5]

    scoped = allowed if allowed is not None else list(companies.keys())
    tot_closed = sum(closure[c]["closed"] for c in scoped if c in closure)
    tot_actions = sum(closure[c]["total"] for c in scoped if c in closure)
    tot_esc = sum(escalations.get(c, 0) for c in scoped)
    planned_clients = len([c for c in clients if c["planned"] > 0])

    cards = {
        "total_clients": len(scoped),
        "planned_clients": planned_clients,
        "unplanned_clients": len(scoped) - planned_clients,
        "total_oms": len(by_om),
        "planned": totals["planned"], "completed": totals["done"],
        "completion": _pct(totals["done"], totals["planned"]),
        "avg_delay": _avg_delay(totals),
        "action_closure": _pct(tot_closed, tot_actions) if tot_actions > 0 else 0,
        "escalations": tot_esc,
        **rollup,
    }

    return {
        "period": {"from": window[0], "to": window[1]},
        "selected_period": scope.get("period") or window[0][:7],
        "cards": cards, "clients": clients, "oms": oms, "top_delayed": top_delayed,
        "filters": await _filters(companies, allowed),
    }


async def _filters(companies: Dict[str, dict], allowed: Optional[List[str]]) -> dict:
    scoped = {cid: i for cid, i in companies.items()
              if allowed is None or cid in set(allowed)}
    oms = {}
    for i in scoped.values():
        if i["om_key"]:
            oms[i["om_key"]] = i["om_name"] or i["om_key"]
    periods = sorted({str(r.get("period")) for r in
                      await get_collection(COLL_SUCCESS_MEASURES).find({}, {"period": 1}).to_list(20000)
                      if r.get("period")}, reverse=True)
    return {
        "oms": [{"id": k, "name": v} for k, v in sorted(oms.items(), key=lambda kv: kv[1])],
        "companies": sorted([{"id": cid, "name": i["name"]} for cid, i in scoped.items()],
                            key=lambda c: (c["name"] or "").lower()),
        "periods": [{"id": p, "name": period_display(p)} for p in periods],
    }


# ─────────────────────────────────────────────────────────────
# 2) OM / SMOps dashboard — getStaffDashboard (code.js:1704)
# ─────────────────────────────────────────────────────────────
async def get_staff_dashboard(user: dict, scope: dict) -> dict:
    scope = scope or {}
    companies = await _load_companies()
    allowed = _allowed_companies(user, companies, scope)
    om_filter = str(scope.get("om_id") or scope.get("smops_id") or "")
    window = _period_window(scope.get("period"))

    events = await _load_events(allowed)
    totals, by_company, _by_om = _accumulate(events, allowed, companies, window, om_filter)
    closure = await _action_closure()
    escalations = await _active_escalations()
    activities, grid = await _clients_grid(events, allowed, companies, window)

    scoped = allowed if allowed is not None else list(companies.keys())
    tot_closed = sum(closure[c]["closed"] for c in scoped if c in closure)
    tot_actions = sum(closure[c]["total"] for c in scoped if c in closure)

    cards = {
        "clients": len(by_company),
        "planned": totals["planned"], "completed": totals["done"],
        "pending": totals["pending"], "overdue": totals["overdue"],
        "lapsed": totals["lapsed"], "rescheduled": totals["rescheduled"],
        "completion": _pct(totals["done"], totals["planned"]),
        "avg_delay": _avg_delay(totals),
        "action_closure": _pct(tot_closed, tot_actions) if tot_actions > 0 else 0,
        "escalations": sum(escalations.get(c, 0) for c in scoped),
    }

    alerts = []
    for c in grid:
        acc = by_company.get(c["company_id"]) or _blank()
        if acc["overdue"]:
            alerts.append({"level": "overdue",
                           "text": f"{c['company']} — {acc['overdue']} activity(s) past due"})
    if not alerts:
        alerts.append({"level": "ok", "text": "No urgent actions. You're on track."})

    return {
        "cards": cards, "activities": activities, "clients_grid": grid,
        "open_actions": await _open_actions(allowed), "alerts": alerts,
        "selected_period": scope.get("period") or window[0][:7],
        "filters": await _filters(companies, allowed),
    }


# ─────────────────────────────────────────────────────────────
# 3) Client dashboard — getLearnerDashboard (code.js:2298)
# ─────────────────────────────────────────────────────────────
async def get_learner_dashboard(user: dict, scope: dict) -> dict:
    scope = scope or {}
    companies = await _load_companies()
    allowed = _allowed_companies(user, companies, scope)
    if not allowed:
        return {"error": "Select a client to view their dashboard."}
    company_id = allowed[0]
    info = companies.get(company_id) or {}
    window = _period_window(scope.get("period"))
    period = scope.get("period") or window[0][:7]

    events = await _load_events(allowed)
    totals, _bc, _bo = _accumulate(events, allowed, companies, window)
    activities, grid = await _clients_grid(events, allowed, companies, window)

    measures = await get_collection(COLL_SUCCESS_MEASURES).find(
        {"company_id": company_id, "period": period, "scope": "company"}
    ).to_list(500)

    rows, met, partial, not_met, ach_sum, ach_n = [], 0, 0, 0, 0, 0
    for m in sorted(measures, key=lambda x: (x.get("activity") or "").lower()):
        actual, target = m.get("score_actual"), m.get("score_target")
        ach = m.get("achievement")
        has_data = actual is not None
        if not has_data:
            status = "Not Met"
            not_met += 1
        elif (ach or 0) >= 100:
            status = "Met"
            met += 1
        elif (ach or 0) > 0:
            status = "Partial"
            partial += 1
        else:
            status = "Not Met"
            not_met += 1
        if ach is not None:
            ach_sum += ach
            ach_n += 1
        rows.append({
            "activity": m.get("activity"),
            "impl_target": m.get("impl_target"), "impl_actual": m.get("impl_actual"),
            "target": target if target is not None else "",
            "actual": actual if actual is not None else "",
            "achievement": ach or 0, "status": status,
        })

    completion = _pct(totals["done"], totals["planned"])
    return {
        "company_id": company_id, "company": info.get("name") or company_id,
        "om": info.get("om_name") or "",
        "completion": completion, "status": _status_band(completion),
        "selected_period": period,
        "op_cards": {
            "planned": totals["planned"], "completed": totals["done"],
            "completion": completion, "avg_delay": _avg_delay(totals),
        },
        "cards": {
            "met": met, "partial": partial, "not_met": not_met,
            "total": len(rows),
            "avg_score": round(ach_sum / ach_n) if ach_n else 0,
            "target": 100,
        },
        "rows": rows,
        "pending_actions": await _open_actions(allowed),
        "activities": activities, "clients_grid": grid,
    }


# ─────────────────────────────────────────────────────────────
# 4) Escalation dashboard — getEscalationDashboard (code.js:2863)
# ─────────────────────────────────────────────────────────────
async def get_escalation_dashboard(user: dict, scope: dict) -> dict:
    scope = scope or {}
    companies = await _load_companies()
    allowed = _allowed_companies(user, companies, scope)

    query: dict = {}
    if allowed is not None:
        query["company_id"] = {"$in": allowed}
    rows = await get_collection(COLL_ESCALATIONS).find(query).to_list(20000)

    today = _today()
    this_month = today[:7]
    active, resolved = [], []
    overdue_days, l1, l2, l3 = [], 0, 0, 0
    resolution_days = []

    for e in rows:
        target = str(e.get("target_date") or "")
        if str(e.get("status") or "") == "Resolved":
            res_date = str(e.get("resolution_date") or "")
            if res_date[:7] == this_month:
                taken = 0
                if target and res_date:
                    try:
                        taken = (date.fromisoformat(res_date[:10]) - date.fromisoformat(target[:10])).days
                    except ValueError:
                        taken = 0
                resolution_days.append(max(0, taken))
                resolved.append({
                    "company": e.get("company_name") or "", "om": e.get("om") or "",
                    "activity": e.get("activity") or "",
                    "esc_date": e.get("escalation_date") or "",
                    "res_date": res_date, "days_taken": max(0, taken),
                    "method": e.get("resolution_method") or "",
                    "resolved_by": e.get("resolved_by") or "",
                })
            continue

        days = 0
        if target:
            try:
                days = (date.fromisoformat(today) - date.fromisoformat(target[:10])).days
            except ValueError:
                days = 0
        overdue_days.append(max(0, days))
        level = int(e.get("level") or 0)
        if level == 1:
            l1 += 1
        elif level == 2:
            l2 += 1
        elif level == 3:
            l3 += 1
        active.append({
            "company": e.get("company_name") or "", "om": e.get("om") or "",
            "activity": e.get("activity") or "", "days_overdue": max(0, days),
            "level": level, "escalated_to": e.get("escalated_to") or "",
            "esc_date": e.get("escalation_date") or "",
            "last_reminder": e.get("last_reminder") or "",
            "recommended": e.get("recommended_action") or "",
        })

    active.sort(key=lambda r: -r["days_overdue"])
    return {
        "cards": {
            "active_count": len(active),
            "avg_overdue": round(sum(overdue_days) / len(overdue_days), 1) if overdue_days else 0,
            "resolved_month": len(resolved),
            "avg_resolution": round(sum(resolution_days) / len(resolution_days), 1) if resolution_days else 0,
            "l1": l1, "l2": l2, "l3": l3,
        },
        "active": active, "resolved": resolved,
        "filters": await _filters(companies, allowed),
    }


# ─────────────────────────────────────────────────────────────
# Tracker-backed people dashboards
#
# Both read tpms_activity_tracker, where "missed" means status == Missed OR the date has
# passed without completion (code.js:3244 / 4118) — the tracker never stores "Missed"
# itself, so this derivation is what actually produces the number.
# ─────────────────────────────────────────────────────────────
async def _company_users(company_ids: Optional[List[str]]) -> Dict[str, dict]:
    query: dict = {"is_active": {"$ne": False}}
    if company_ids is not None:
        query["company_id"] = {"$in": company_ids}
    out = {}
    for u in await get_collection("learners").find(query).to_list(5000):
        out[str(u["_id"])] = {
            "id": str(u["_id"]),
            "name": (u.get("full_name")
                     or " ".join(filter(None, [u.get("first_name"), u.get("last_name")])).strip()
                     or u.get("email") or str(u["_id"])),
            "designation": u.get("designation") or "",
            "department": u.get("department") or "",
            "email": u.get("email") or "",
            "company_id": str(u.get("company_id") or ""),
        }
    return out


async def _tracker_rows(company_ids: Optional[List[str]], period: Optional[str] = None,
                        member_id: Optional[str] = None) -> List[dict]:
    from app.models.tpms import COLL_ACTIVITY_TRACKER
    query: dict = {}
    if company_ids is not None:
        query["company_id"] = {"$in": company_ids}
    if period:
        query["period"] = period
    if member_id:
        query["member_id"] = member_id
    return await get_collection(COLL_ACTIVITY_TRACKER).find(query).to_list(50000)


def _classify(status: str, day: str, today: str) -> str:
    if status == STATUS_COMPLETED:
        return "done"
    if status == STATUS_LAPSED or (day and day < today):
        return "missed"
    return "pending"


# 5) Employee activity — getEmployeeActivityDashboard (code.js:4044)
async def get_employee_activity(user: dict, scope: dict) -> dict:
    scope = scope or {}
    companies = await _load_companies()
    allowed = _allowed_companies(user, companies, scope)
    period = scope.get("period")
    today = _today()

    people = await _company_users(allowed)
    rows_raw = await _tracker_rows(allowed, period)

    agg: Dict[str, dict] = {}
    periods = set()
    for r in rows_raw:
        mid = str(r.get("member_id") or "")
        if mid not in people:
            continue
        status = str(r.get("status") or "")
        if status == STATUS_CANCELLED:
            continue
        if r.get("period"):
            periods.add(str(r["period"]))
        cell = _classify(status, str(r.get("date") or ""), today)

        a = agg.setdefault(mid, {"total": 0, "done": 0, "missed": 0,
                                 "pending": 0, "by_activity": {}})
        a["total"] += 1
        a[{"done": "done", "missed": "missed", "pending": "pending"}[cell]] += 1
        activity = str(r.get("activity") or "")
        if activity:
            ac = a["by_activity"].setdefault(activity, {"total": 0, "completed": 0})
            ac["total"] += 1
            if cell == "done":
                ac["completed"] += 1

    filter_member = str(scope.get("member_id") or "")
    filter_desig = str(scope.get("designation") or "").lower()

    rows = []
    for mid, meta in people.items():
        if filter_member and mid != filter_member:
            continue
        if filter_desig and meta["designation"].lower() != filter_desig:
            continue
        a = agg.get(mid) or {"total": 0, "done": 0, "missed": 0, "pending": 0, "by_activity": {}}
        rows.append({
            "id": mid, "name": meta["name"],
            "designation": meta["designation"] or "—",
            "department": meta["department"] or "—",
            "email": meta["email"],
            "total": a["total"], "completed": a["done"],
            "missed": a["missed"], "pending": a["pending"],
            "score": _pct(a["done"], a["total"]),
            "activities": sorted(
                [{"activity": k, "completed": v["completed"], "total": v["total"],
                  "pct": _pct(v["completed"], v["total"])}
                 for k, v in a["by_activity"].items()],
                key=lambda x: x["activity"].lower()),
        })
    rows.sort(key=lambda r: (-r["score"], r["name"].lower()))

    return {
        "company": (companies.get(allowed[0]) or {}).get("name") if allowed else "",
        "can_pick_company": (user.get("role") or "").lower() not in CLIENT_ROLES,
        "cards": {
            "total_employees": len(rows),
            "total_activities": sum(r["total"] for r in rows),
            "completed": sum(r["completed"] for r in rows),
            "missed": sum(r["missed"] for r in rows),
            "pending": sum(r["pending"] for r in rows),
            "avg_score": round(sum(r["score"] for r in rows) / len(rows)) if rows else 0,
        },
        "rows": rows,
        "selected_period": period or "",
        "period_options": [{"id": p, "name": period_display(p)} for p in sorted(periods, reverse=True)],
        "member_options": sorted([{"id": m["id"], "name": m["name"]} for m in people.values()],
                                 key=lambda x: x["name"].lower()),
        "designation_options": sorted({m["designation"] for m in people.values() if m["designation"]}),
        "company_options": (await _filters(companies, allowed))["companies"],
    }


# 6) HOD dashboard — getHodDashboard (code.js:3154)
async def get_hod_dashboard(user: dict, scope: dict) -> dict:
    scope = scope or {}
    companies = await _load_companies()
    allowed = _allowed_companies(user, companies, scope)
    window = _period_window(scope.get("period"))
    frm, to = window[0], window[1]
    today = _today()

    people = await _company_users(allowed)
    hod_options = sorted(
        [{"id": p["id"], "name": p["name"], "company_id": p["company_id"],
          "company": (companies.get(p["company_id"]) or {}).get("name") or ""}
         for p in people.values() if (p["department"] or "").lower() == "hod"],
        key=lambda h: h["name"].lower())

    target = str(scope.get("member_id") or "")
    if not target:
        # A client-side user defaults to themselves when they are an HOD.
        me = str(user.get("_id"))
        target = me if any(h["id"] == me for h in hod_options) else (
            hod_options[0]["id"] if hod_options else "")

    meta = people.get(target) or {}
    hod = {
        "id": target, "name": meta.get("name") or target or "(none)",
        "company": (companies.get(meta.get("company_id", "")) or {}).get("name") or "",
        "department": meta.get("department") or "", "email": meta.get("email") or "",
    }

    groups: Dict[tuple, dict] = {}
    tracker, planned, completed, missed, pending = [], 0, 0, 0, 0
    for r in await _tracker_rows(allowed, member_id=target or None):
        day = str(r.get("date") or "")
        if not _in_range(day, frm, to):
            continue
        status = str(r.get("status") or "")
        if status == STATUS_CANCELLED:
            continue
        cell = _classify(status, day, today)
        planned += 1
        if cell == "done":
            completed += 1
        elif cell == "missed":
            missed += 1
        else:
            pending += 1

        activity = str(r.get("activity") or "")
        per = str(r.get("period") or "")
        g = groups.setdefault((activity, per), {"activity": activity, "period": per,
                                                "total": 0, "completed": 0,
                                                "missed": 0, "pending": 0})
        g["total"] += 1
        g[{"done": "completed", "missed": "missed", "pending": "pending"}[cell]] += 1
        tracker.append({"date": day, "period": per, "activity": activity, "status": status})

    score_rows = [{
        "period": g["period"], "period_label": period_display(g["period"]) if g["period"] else "",
        "activity": g["activity"], "completed": g["completed"], "total": g["total"],
        "missed": g["missed"], "pending": g["pending"],
        "label": f"{g['completed']}/{g['total']}",
        "score": _pct(g["completed"], g["total"]),
    } for g in groups.values()]
    score_rows.sort(key=lambda r: (r["period"], r["activity"].lower()))
    tracker.sort(key=lambda r: r["date"], reverse=True)

    actions = [a for a in await _open_actions(allowed)
               if not target or a["employee_id"] == target]
    alerts = [{"level": "overdue", "text": f"{missed} activity(s) missed this period"}] if missed \
        else [{"level": "ok", "text": "Nothing urgent. On track."}]

    closure_total = len(actions)
    return {
        "hod": hod,
        "can_pick": True,
        "hod_options": hod_options,
        "selected_hod": target,
        "cards": {
            "activities": planned, "completed": completed, "missed": missed,
            "pending": pending, "completion": _pct(completed, planned),
            "open_actions": closure_total,
            "action_closure": _pct(0, closure_total) if closure_total else 100,
        },
        "score_rows": score_rows, "tracker": tracker,
        "alerts": alerts, "open_actions": actions,
        "selected_period": scope.get("period") or frm[:7],
    }


# 7) Implementation tracker — getSuccessDashboard (code.js:2449)
async def get_implementation_tracker(user: dict, scope: dict) -> dict:
    """Assembles the Success-Measure scorecard, the proof-upload panel and the
    client × activity matrix into the Implementation Tracker view."""
    scope = scope or {}
    companies = await _load_companies()
    allowed = _allowed_companies(user, companies, scope)
    window = _period_window(scope.get("period"))
    period = scope.get("period") or window[0][:7]
    company_id = allowed[0] if allowed and len(allowed) == 1 else None

    events = await _load_events(allowed)
    activities, grid = await _clients_grid(events, allowed, companies, window)

    scorecard, uploads = [], []
    if company_id:
        measures = await get_collection(COLL_SUCCESS_MEASURES).find(
            {"company_id": company_id, "period": period}
        ).to_list(500)
        for m in sorted(measures, key=lambda x: (x.get("activity") or "").lower()):
            scorecard.append({
                "activity": m.get("activity"), "scope": m.get("scope"),
                "hod_id": m.get("hod_id"), "hod_name": m.get("hod_name"),
                "impl_target": m.get("impl_target"), "impl_actual": m.get("impl_actual"),
                "score_target": m.get("score_target"), "score_actual": m.get("score_actual"),
                "achievement": m.get("achievement"),
            })
        from app.services.tpms_upload_service import list_task_uploads
        uploads = await list_task_uploads(user, company_id=company_id, period=period)

    catalogue = await get_collection(COLL_ACTIVITIES).find({"active": {"$ne": False}}).to_list(200)
    manual = [{"activity": a["name"], "scope": a.get("scope")}
              for a in catalogue if a.get("score_mode") == "manual"]

    total = len(scorecard) or len(catalogue)
    return {
        "selected_period": period,
        "selected_company": company_id,
        "cards": {
            "total": total,
            "met": len([s for s in scorecard if (s["achievement"] or 0) >= 100]),
            "partial": len([s for s in scorecard if 0 < (s["achievement"] or 0) < 100]),
            "not_met": len([s for s in scorecard if not s["achievement"]]),
        },
        "scorecard": scorecard, "uploads": uploads,
        "manual_activities": manual,
        "matrix_activities": activities, "clients": grid,
        "filters": await _filters(companies, allowed),
    }


# 8) Logs report — getLogsReport (code.js:2957)
async def get_logs_report(user: dict, channel: str, scope: dict) -> dict:
    """Email / WhatsApp delivery logs with KPI counts and a per-day sparkline.

    The Apps Script truncated to the latest 3000 rows and exported CSV in the browser.
    Here the query is paginated server-side; the client asks for what it renders.
    """
    scope = scope or {}
    query: dict = {"channel": channel} if channel else {}
    if scope.get("status"):
        query["status"] = scope["status"]
    if scope.get("from") or scope.get("to"):
        rng = {}
        if scope.get("from"):
            rng["$gte"] = datetime.fromisoformat(str(scope["from"])[:10])
        if scope.get("to"):
            rng["$lte"] = datetime.fromisoformat(str(scope["to"])[:10]) + timedelta(days=1)
        query["created_at"] = rng

    limit = min(int(scope.get("limit") or 500), 3000)
    skip = int(scope.get("skip") or 0)
    coll = get_collection("notification_logs")
    total = await coll.count_documents(query)
    docs = await coll.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)

    counts = {"total": total, "sent": 0, "failed": 0, "skipped": 0}
    spark: Dict[str, int] = {}
    rows = []
    for d in docs:
        status = str(d.get("status") or "").lower()
        if "sent" in status or "success" in status:
            counts["sent"] += 1
        elif "fail" in status:
            counts["failed"] += 1
        else:
            counts["skipped"] += 1
        created = d.get("created_at")
        day = created.date().isoformat() if isinstance(created, datetime) else ""
        if day:
            spark[day] = spark.get(day, 0) + 1
        rows.append([
            day, d.get("template_slug") or "", d.get("channel") or "",
            d.get("target_contact") or "", d.get("status") or "", d.get("error") or "",
        ])

    return {
        "type": channel or "all",
        "columns": ["Timestamp", "Action", "Channel", "Recipient", "Log Status", "Error"],
        "rows": rows, "counts": counts,
        "spark": [{"day": k, "count": v} for k, v in sorted(spark.items())],
        "truncated": total > len(rows),
        "total": total, "skip": skip, "limit": limit,
    }


# 9) Review reports — getReviewReports (code.js:3388)
REVIEW_SOURCES = [
    {"id": "accountability", "label": "Accountability Rating",
     "status": {"high": "Strong", "mid": "Moderate", "low": "Needs Focus"}},
    {"id": "ownership", "label": "Ownership Rating",
     "status": {"high": "Strong", "mid": "Moderate", "low": "Needs Focus"}},
    {"id": "culture", "label": "Culture Rating",
     "status": {"high": "Strong", "mid": "Moderate", "low": "Needs Focus"}},
    {"id": "implementation_feedback", "label": "Implementation Update Feedback",
     "status": {"high": "On Track", "mid": "Partial", "low": "Needs Focus"}},
]


async def get_review_reports(user: dict, source_id: str, scope: dict) -> dict:
    """Per-HOD submission detail plus the monthly score trend.

    Score % uses the same arithmetic as the source: Σratings ÷ (answered × 5) × 100 for
    matrices, yes ÷ answered × 100 for the checklist. Status bands ≥85 / ≥70 / below.
    """
    from app.models.forms import (KIND_YESNO_CHECKLIST, SCALE_MAX, form_kind,
                                  get_definition, submission_collection)
    scope = scope or {}
    source = next((s for s in REVIEW_SOURCES if s["id"] == source_id), REVIEW_SOURCES[0])
    ft = source["id"]
    is_yesno = form_kind(ft) == KIND_YESNO_CHECKLIST
    definition = get_definition(ft) or {}

    companies = await _load_companies()
    allowed = _allowed_companies(user, companies, scope)

    query: dict = {}
    if allowed is not None:
        query["company_id"] = {"$in": allowed}
    if scope.get("period"):
        from app.models.tpms import period_tokens
        query["period"] = {"$in": period_tokens(scope["period"])}

    docs = await get_collection(submission_collection(ft)).find(query).to_list(5000)
    respondent_key = "md_id" if is_yesno else "hod_id"
    if scope.get("respondent_id"):
        docs = [d for d in docs if str(d.get(respondent_key)) == str(scope["respondent_id"])]

    people = await _company_users(allowed)
    criteria = definition.get("criteria") or []
    questions = definition.get("questions") or []

    entries, periods, respondents = [], set(), {}
    total_ratings = total_sum = total_yes = total_answers = 0

    for d in docs:
        per = str(d.get("period") or "")
        periods.add(per)
        rid = str(d.get(respondent_key) or "")
        rname = (d.get("hod_name") or d.get("md_name")
                 or (people.get(rid) or {}).get("name") or rid)
        respondents[rid] = rname
        company = (companies.get(str(d.get("company_id"))) or {}).get("name") or ""

        if is_yesno:
            items, yes = [], 0
            for q in questions:
                ans = (d.get("answers") or {}).get(str(q["id"])) or {}
                checked = bool(ans.get("checked"))
                yes += 1 if checked else 0
                items.append({"question": q.get("title"), "yes": checked,
                              "answer": "Yes" if checked else "No",
                              "remark": ans.get("remark") or ""})
            n = len(items)
            total_yes += yes
            total_answers += n
            entries.append({"respondent_id": rid, "name": rname, "company": company,
                            "period": per, "period_label": period_display(per) if per else "",
                            "yesno": True, "items": items, "yes": yes, "total": n,
                            "score_pct": _pct(yes, n)})
        else:
            members: Dict[str, dict] = {}
            for code, cells in (d.get("ratings") or {}).items():
                for mid, cell in (cells or {}).items():
                    r = cell.get("rating")
                    if not isinstance(r, (int, float)):
                        continue
                    m = members.setdefault(mid, {
                        "name": cell.get("member_name") or (people.get(mid) or {}).get("name") or mid,
                        "ratings": {}, "sum": 0, "n": 0})
                    m["ratings"][code] = r
                    m["sum"] += r
                    m["n"] += 1
                    total_sum += r
                    total_ratings += 1
            employees = [{
                "id": mid, "name": m["name"], "ratings": m["ratings"],
                "grand_total": m["sum"],
                "score_pct": round(m["sum"] / (m["n"] * SCALE_MAX) * 100) if m["n"] else 0,
            } for mid, m in members.items()]
            employees.sort(key=lambda e: e["name"].lower())
            grand = sum(e["grand_total"] for e in employees)
            answered = sum(len(e["ratings"]) for e in employees)
            entries.append({
                "respondent_id": rid, "name": rname, "company": company, "period": per,
                "period_label": period_display(per) if per else "",
                "matrix": True,
                "questions": [{"id": c["code"], "text": c.get("title") or c["code"]} for c in criteria],
                "employees": employees,
                "avg": round(grand / answered, 2) if answered else "",
                "score_pct": round(grand / (answered * SCALE_MAX) * 100) if answered else 0,
            })

    entries.sort(key=lambda e: (e["period"], e["name"].lower()), reverse=True)

    # Monthly trend: score % per rated person across periods.
    trend_people: Dict[str, dict] = {}
    for e in entries:
        if e.get("yesno"):
            t = trend_people.setdefault(e["respondent_id"],
                                        {"name": e["name"], "company": e["company"], "scores": {}})
            t["scores"][e["period"]] = e["score_pct"]
        else:
            for emp in e["employees"]:
                t = trend_people.setdefault(emp["id"],
                                            {"name": emp["name"], "company": e["company"], "scores": {}})
                t["scores"][e["period"]] = emp["score_pct"]

    ordered = sorted(periods, reverse=True)
    return {
        "sources": [{"id": s["id"], "label": s["label"]} for s in REVIEW_SOURCES],
        "source": source,
        "is_yesno": is_yesno,
        "totals": {
            "responses": len(docs),
            "respondent_count": len(respondents),
            "avg_rating": round(total_sum / total_ratings, 2) if total_ratings else "",
            "yes_pct": _pct(total_yes, total_answers) if total_answers else "",
        },
        "entries": entries,
        "trend": {
            "periods": [{"id": p, "name": period_display(p) if p else ""} for p in ordered],
            "people": sorted(trend_people.values(), key=lambda t: t["name"].lower()),
        },
        "period_options": [{"id": p, "name": period_display(p) if p else ""} for p in ordered],
        "respondent_options": sorted(
            [{"id": k, "name": v} for k, v in respondents.items()],
            key=lambda r: r["name"].lower()),
        "can_pick": (user.get("role") or "").lower() not in CLIENT_ROLES,
        "selected_period": scope.get("period") or "",
    }
