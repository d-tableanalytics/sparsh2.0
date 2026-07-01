from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timedelta, timezone
from bson import ObjectId

from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user
from app.utils.calendar_utils import CALENDAR_COLLECTIONS, find_event_across_collections
from app.services.activity_log_service import log_activity

router = APIRouter(prefix="/tasks", tags=["Tasks"])

# calendar_event docs with type=="task" live in the same collections as calendar events
TASK_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]
ADMIN_ROLES = ["superadmin", "admin", "coach", "staff"]

# Richer workflow taken on by type=="task" docs. The legacy `status` field
# (schedule/completed/canceled/reschedule) stays authoritative for the Calendar page.
WORKFLOW_STATUSES = [
    "pending", "accepted", "in_progress", "dependent_on_others",
    "blocked", "verification", "completed",
]


def _period_to_range(period: Optional[str], start_date: Optional[str], end_date: Optional[str]):
    """Returns (start_iso, end_iso) or (None, None) meaning 'all time'."""
    now = datetime.utcnow()
    today = now.date()

    def day_bounds(d):
        start = datetime(d.year, d.month, d.day)
        end = start + timedelta(days=1) - timedelta(microseconds=1)
        return start, end

    if period == "custom":
        if start_date and end_date:
            return start_date, end_date
        return None, None

    if period == "today":
        s, e = day_bounds(today)
    elif period == "yesterday":
        s, e = day_bounds(today - timedelta(days=1))
    elif period == "this_week":
        monday = today - timedelta(days=today.weekday())
        s, _ = day_bounds(monday)
        _, e = day_bounds(monday + timedelta(days=6))
    elif period == "last_week":
        monday = today - timedelta(days=today.weekday() + 7)
        s, _ = day_bounds(monday)
        _, e = day_bounds(monday + timedelta(days=6))
    elif period == "this_month":
        first = today.replace(day=1)
        next_month = (first + timedelta(days=32)).replace(day=1)
        s, _ = day_bounds(first)
        _, e = day_bounds(next_month - timedelta(days=1))
    elif period == "last_month":
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        s, _ = day_bounds(last_month_end.replace(day=1))
        _, e = day_bounds(last_month_end)
    elif period == "this_year":
        s, _ = day_bounds(today.replace(month=1, day=1))
        _, e = day_bounds(today.replace(month=12, day=31))
    else:
        # all_time / unspecified
        return None, None

    return s.isoformat(), e.isoformat()


def _resolve_workflow_status(doc: dict) -> str:
    ws = doc.get("workflow_status")
    if ws in WORKFLOW_STATUSES:
        return ws
    # Legacy fallback for tasks created before workflow_status existed
    if doc.get("status") == "completed":
        return "completed"
    return "pending"


def _parse_iso(value):
    if not value:
        return None
    try:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        return value.replace(tzinfo=None) if value.tzinfo else value
    except Exception:
        return None


def _is_overdue(doc: dict, workflow_status: str, now: datetime) -> bool:
    if workflow_status == "completed":
        return False
    due_dt = _parse_iso(doc.get("end") or doc.get("start"))
    if not due_dt:
        return False
    return due_dt < now


def _completion_timing(doc: dict) -> Optional[str]:
    """Returns 'in_time' | 'delayed' | None (not completed, or no due date to compare against)."""
    if _resolve_workflow_status(doc) != "completed":
        return None
    completed_dt = _parse_iso(doc.get("completed_at"))
    due_dt = _parse_iso(doc.get("end") or doc.get("start"))
    if not completed_dt or not due_dt:
        return None
    return "in_time" if completed_dt <= due_dt else "delayed"


def _visibility_clauses(user_id: str):
    return [
        {"user_id": user_id},
        {"target_staff_id": user_id},
        {"target_staff_id": {"$in": [user_id]}},
        {"watchers": user_id},
        {"watchers": {"$in": [user_id]}},
    ]


async def _fetch_tasks(
    current_user: dict,
    scope: str,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    frequency: Optional[str] = None,
    assigned_to: Optional[str] = None,
    search: Optional[str] = None,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
):
    user_id = str(current_user["_id"])
    role = current_user.get("role", "").lower()
    company_id = current_user.get("company_id")
    is_admin_role = role in ADMIN_ROLES

    clauses = [{"type": "task"}]

    if start_iso and end_iso:
        clauses.append({"start": {"$gte": start_iso, "$lte": end_iso}})

    if scope == "my":
        clauses.append({"$or": [
            {"target_staff_id": user_id},
            {"target_staff_id": {"$in": [user_id]}},
            {"$and": [{"user_id": user_id}, {"assigned_to": "myself"}]},
        ]})
    elif scope == "delegated":
        clauses.append({"user_id": user_id})
        clauses.append({"assigned_to": "other"})
    elif scope == "subscribed":
        clauses.append({"$or": [{"watchers": user_id}, {"watchers": {"$in": [user_id]}}]})
    elif scope == "all":
        has_perm = (
            current_user.get("permissions", {}).get("tasks", {}).get("read")
            or current_user.get("permissions", {}).get("calendar", {}).get("read")
        )
        if not (role == "superadmin" or has_perm):
            raise HTTPException(status_code=403, detail="Not authorized to view all tasks")
        if role != "superadmin" and company_id:
            clauses.append({"$or": [{"company_id": str(company_id)}, {"user_id": user_id}]})
    elif scope == "deleted":
        if not is_admin_role:
            clauses.append({"$or": _visibility_clauses(user_id)})
    else:
        raise HTTPException(status_code=400, detail="Invalid scope")

    clauses.append({"deleted_at": {"$ne": None}} if scope == "deleted" else {"deleted_at": None})

    if category:
        clauses.append({"category": category})
    if frequency:
        clauses.append({"repeat": frequency})
    if tag:
        clauses.append({"tags": {"$in": [tag]}})
    if assigned_to:
        clauses.append({"$or": [
            {"target_staff_id": assigned_to},
            {"target_staff_id": {"$in": [assigned_to]}},
            {"$and": [{"user_id": assigned_to}, {"assigned_to": "myself"}]},
        ]})
    if search:
        clauses.append({"title": {"$regex": search, "$options": "i"}})

    query = {"$and": clauses}

    results = []
    for col_name in TASK_COLLECTIONS:
        docs = await get_collection(col_name).find(query).to_list(2000)
        for d in docs:
            d["_source_col"] = col_name
            results.append(d)
    return results


def _serialize_task(doc: dict, current_user_id: str) -> dict:
    ws = _resolve_workflow_status(doc)
    now = datetime.utcnow()
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title"),
        "type": doc.get("type"),
        "start": doc.get("start"),
        "end": doc.get("end"),
        "category": doc.get("category"),
        "tags": doc.get("tags") or [],
        "frequency": doc.get("repeat"),
        "priority": doc.get("priority") or "Normal",
        "description": doc.get("description"),
        "createdAt": doc.get("created_at"),
        "status": ws,
        "isOverdue": _is_overdue(doc, ws, now),
        "completionTiming": _completion_timing(doc),
        "assignedTo": doc.get("target_staff_id") or [],
        "assignedBy": doc.get("user_id"),
        "watchers": doc.get("watchers") or [],
        "isCreator": doc.get("user_id") == current_user_id,
        "deletedAt": doc.get("deleted_at"),
    }


@router.get("/dashboard")
async def tasks_dashboard(
    period: Optional[str] = None,
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    assignedTo: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    frequency: Optional[str] = None,
    search: Optional[str] = None,
    viewType: Optional[str] = None,
    reportType: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    role = current_user.get("role", "").lower()
    is_admin_role = role in ADMIN_ROLES

    # reportType picks which visibility scope backs the numbers: admins/staff default to an
    # org-wide view, everyone else only ever sees their own tasks regardless of tab clicked.
    scope_map = {"delegated": "delegated", "my_report": "my"}
    scope = scope_map.get(reportType, "all" if is_admin_role else "my")

    start_iso, end_iso = _period_to_range(period, startDate, endDate)
    docs = await _fetch_tasks(current_user, scope, category, tag, frequency, assignedTo, search, start_iso, end_iso)

    now = datetime.utcnow()
    summary = {
        "totalTasks": 0, "overdue": 0, "pending": 0, "accepted": 0,
        "dependentOnOthers": 0, "blocked": 0, "inProgress": 0,
        "verification": 0, "completed": 0, "inTime": 0, "delayed": 0,
    }
    status_key_map = {
        "pending": "pending", "accepted": "accepted", "in_progress": "inProgress",
        "dependent_on_others": "dependentOnOthers", "blocked": "blocked",
        "verification": "verification", "completed": "completed",
    }

    monthly_buckets = {}

    for doc in docs:
        ws = _resolve_workflow_status(doc)
        summary["totalTasks"] += 1
        summary[status_key_map.get(ws, "pending")] += 1
        if _is_overdue(doc, ws, now):
            summary["overdue"] += 1
        timing = _completion_timing(doc)
        if timing == "in_time":
            summary["inTime"] += 1
        elif timing == "delayed":
            summary["delayed"] += 1

        start_dt = _parse_iso(doc.get("start"))
        if not start_dt:
            continue
        month_key = start_dt.strftime("%B %Y")
        bucket = monthly_buckets.setdefault(month_key, {
            "month": month_key, "_sort": (start_dt.year, start_dt.month),
            "total": 0, "score": 0, "overdue": 0, "pending": 0,
            "inProgress": 0, "inTime": 0, "delayed": 0,
        })
        bucket["total"] += 1
        if ws == "pending":
            bucket["pending"] += 1
        elif ws == "in_progress":
            bucket["inProgress"] += 1
        if _is_overdue(doc, ws, now):
            bucket["overdue"] += 1
        if timing == "in_time":
            bucket["inTime"] += 1
            bucket["score"] += 1  # No existing "score" definition in the codebase; defaults to in-time count.
        elif timing == "delayed":
            bucket["delayed"] += 1

    monthly = sorted(monthly_buckets.values(), key=lambda b: b["_sort"])
    for b in monthly:
        b.pop("_sort", None)

    return {"summary": summary, "monthly": monthly}


@router.get("")
async def list_tasks(
    scope: str = Query("my"),
    category: Optional[str] = None,
    tag: Optional[str] = None,
    frequency: Optional[str] = None,
    assignedTo: Optional[str] = None,
    search: Optional[str] = None,
    period: Optional[str] = None,
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    start_iso, end_iso = _period_to_range(period, startDate, endDate)
    docs = await _fetch_tasks(current_user, scope, category, tag, frequency, assignedTo, search, start_iso, end_iso)
    user_id = str(current_user["_id"])
    return [_serialize_task(d, user_id) for d in docs]


@router.patch("/{task_id}/status")
async def update_task_status(task_id: str, body: dict, current_user: dict = Depends(get_current_user)):
    new_status = body.get("workflow_status")
    if new_status not in WORKFLOW_STATUSES:
        raise HTTPException(status_code=400, detail=f"workflow_status must be one of {WORKFLOW_STATUSES}")

    existing, col_name = await find_event_across_collections(task_id)
    if not existing or existing.get("type") != "task":
        raise HTTPException(status_code=404, detail="Task not found")

    user_id = str(current_user["_id"])
    is_admin = current_user.get("role") == "superadmin"
    is_creator = existing.get("user_id") == user_id
    is_assignee = user_id in (existing.get("target_staff_id") or [])
    if not (is_admin or is_creator or is_assignee):
        raise HTTPException(status_code=403, detail="Not authorized to update this task")

    updates = {"workflow_status": new_status, "updated_at": datetime.now(timezone.utc)}
    was_completed = _resolve_workflow_status(existing) == "completed"
    if new_status == "completed" and not was_completed:
        updates["completed_at"] = datetime.now(timezone.utc)
        updates["status"] = "completed"  # keep legacy Calendar page status in sync
    elif was_completed and new_status != "completed":
        updates["completed_at"] = None
        updates["status"] = "schedule"

    await get_collection(col_name).update_one({"_id": ObjectId(task_id)}, {"$set": updates})
    await log_activity(current_user, "Update Task Status", col_name, f"Task {task_id} -> {new_status}")
    return {"id": task_id, "workflow_status": new_status}


@router.delete("/{task_id}")
async def soft_delete_task(task_id: str, current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(task_id)
    if not existing or existing.get("type") != "task":
        raise HTTPException(status_code=404, detail="Task not found")

    is_admin = current_user.get("role") == "superadmin"
    is_creator = existing.get("user_id") == str(current_user["_id"])
    if not (is_admin or is_creator):
        raise HTTPException(status_code=403, detail="Not authorized to delete this task")

    await get_collection(col_name).update_one(
        {"_id": ObjectId(task_id)},
        {"$set": {"deleted_at": datetime.now(timezone.utc).isoformat()}},
    )
    await log_activity(current_user, "Soft Delete Task", col_name, f"Task {task_id}")
    return {"message": "Task moved to Deleted Tasks"}


@router.post("/{task_id}/restore")
async def restore_task(task_id: str, current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(task_id)
    if not existing or existing.get("type") != "task":
        raise HTTPException(status_code=404, detail="Task not found")

    is_admin = current_user.get("role") == "superadmin"
    is_creator = existing.get("user_id") == str(current_user["_id"])
    if not (is_admin or is_creator):
        raise HTTPException(status_code=403, detail="Not authorized to restore this task")

    await get_collection(col_name).update_one(
        {"_id": ObjectId(task_id)},
        {"$set": {"deleted_at": None}},
    )
    await log_activity(current_user, "Restore Task", col_name, f"Task {task_id}")
    return {"message": "Task restored"}
