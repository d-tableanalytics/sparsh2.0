from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user, check_role
from app.config.settings import settings
from bson import ObjectId
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
import re

router = APIRouter(prefix="/notifications", tags=["Notifications"])

class NotificationResponse(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    title: str
    message: str
    type: str
    is_read: bool
    created_at: datetime
    meta: Optional[dict] = {}

    class Config:
        populate_by_name = True

# ─── Per-user Notification Preferences (Settings ▸ Notifications) ───
# Stored in the `notification_preferences` collection keyed by user_id, so we don't have to
# touch the staff/learners user schema. Every key defaults to True when no doc exists yet.
PREFERENCE_KEYS = [
    "email_notifications", "task_reminders", "delegation_updates",
    "subscription_updates", "holiday_alerts",
]


class NotificationPreferences(BaseModel):
    email_notifications: bool = True
    task_reminders: bool = True
    delegation_updates: bool = True
    subscription_updates: bool = True
    holiday_alerts: bool = True


@router.get("/preferences")
async def get_notification_preferences(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    doc = await get_collection("notification_preferences").find_one({"user_id": user_id})
    return {k: (doc.get(k, True) if doc else True) for k in PREFERENCE_KEYS}


@router.put("/preferences")
async def update_notification_preferences(prefs: NotificationPreferences, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    data = prefs.model_dump()
    data["updated_at"] = datetime.utcnow()
    await get_collection("notification_preferences").update_one(
        {"user_id": user_id}, {"$set": {**data, "user_id": user_id}}, upsert=True
    )
    return {k: prefs.model_dump()[k] for k in PREFERENCE_KEYS}


@router.get("/", response_model=List[dict])
async def get_notifications(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    notifications = await get_collection("in_app_notifications").find(
        {"user_id": user_id}
    ).sort("created_at", -1).to_list(100)
    
    for n in notifications:
        n["_id"] = str(n["_id"])
    return notifications

@router.get("/unread-count")
async def get_unread_count(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    count = await get_collection("in_app_notifications").count_documents(
        {"user_id": user_id, "is_read": False}
    )
    return {"count": count}

@router.put("/{notification_id}/read")
async def mark_as_read(notification_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    result = await get_collection("in_app_notifications").update_one(
        {"_id": ObjectId(notification_id), "user_id": user_id},
        {"$set": {"is_read": True}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"message": "Marked as read"}

@router.put("/mark-all-read")
async def mark_all_read(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    await get_collection("in_app_notifications").update_many(
        {"user_id": user_id, "is_read": False},
        {"$set": {"is_read": True}}
    )
    return {"message": "All notifications marked as read"}

@router.delete("/{notification_id}")
async def delete_notification(notification_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    result = await get_collection("in_app_notifications").delete_one(
        {"_id": ObjectId(notification_id), "user_id": user_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"message": "Notification deleted"}


# ─── WhatsApp Delivery Dashboard (admin) ──────────────────────────────────────
# Reads the `notifications` delivery log (written by services/notification_service.log_notification)
# and surfaces sent/failed counts + logs for the business WhatsApp number, similar to the
# Meta WhatsApp Manager dashboard. Restricted to platform staff (superadmin/admin).

# The notifications collection has no index by default; every WhatsApp query filters on
# channel + sent_at, so create a compound index once (idempotent) to keep the dashboard fast.
_wa_index_ready = False


async def _ensure_wa_index():
    global _wa_index_ready
    if _wa_index_ready:
        return
    try:
        await get_collection("notifications").create_index([("channel", 1), ("sent_at", -1)])
        _wa_index_ready = True
    except Exception:
        # Index creation is best-effort; the endpoints still work without it.
        pass


def _mask_id(value: Optional[str]) -> Optional[str]:
    """Show only the last 4 chars of an identifier so it's recognizable but not fully exposed."""
    if not value:
        return None
    value = str(value)
    return value if len(value) <= 4 else f"…{value[-4:]}"


@router.get("/whatsapp/stats")
async def whatsapp_stats(
    days: int = Query(30, ge=1, le=365),
    current_user: dict = Depends(check_role(["superadmin", "admin"])),
):
    """Aggregate WhatsApp delivery metrics over the last `days` days:
    totals, success rate, a per-day sent/failed series, and a per-template breakdown."""
    await _ensure_wa_index()
    col = get_collection("notifications")
    start = datetime.utcnow() - timedelta(days=days)
    match = {"channel": "whatsapp", "sent_at": {"$gte": start}}

    # Totals by status
    totals = {"sent": 0, "failed": 0, "pending": 0}
    async for row in col.aggregate([
        {"$match": match},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]):
        totals[row["_id"] or "pending"] = row["count"]
    total = totals["sent"] + totals["failed"] + totals["pending"]
    success_rate = round((totals["sent"] / total) * 100, 1) if total else 0.0

    # Per-day series (fill gaps so the chart has one point per day)
    daily_map = {}
    async for row in col.aggregate([
        {"$match": match},
        {"$group": {
            "_id": {
                "day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$sent_at"}},
                "status": "$status",
            },
            "count": {"$sum": 1},
        }},
    ]):
        day = row["_id"]["day"]
        st = row["_id"]["status"] or "pending"
        bucket = daily_map.setdefault(day, {"date": day, "sent": 0, "failed": 0, "pending": 0})
        bucket[st] = row["count"]

    daily = []
    for i in range(days - 1, -1, -1):
        day = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        daily.append(daily_map.get(day, {"date": day, "sent": 0, "failed": 0, "pending": 0}))

    # Per-template breakdown
    template_map = {}
    async for row in col.aggregate([
        {"$match": match},
        {"$group": {
            "_id": {"slug": "$template_slug", "status": "$status"},
            "count": {"$sum": 1},
        }},
    ]):
        slug = row["_id"]["slug"] or "(unknown)"
        st = row["_id"]["status"] or "pending"
        bucket = template_map.setdefault(slug, {"slug": slug, "sent": 0, "failed": 0, "pending": 0, "total": 0})
        bucket[st] = row["count"]
        bucket["total"] += row["count"]
    by_template = sorted(template_map.values(), key=lambda t: t["total"], reverse=True)

    return {
        "days": days,
        "config": {
            "configured": bool(settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID),
            "phone_number_id": _mask_id(settings.WHATSAPP_PHONE_NUMBER_ID),
            "business_account_id": _mask_id(settings.WHATSAPP_BUSINESS_ACCOUNT_ID),
            "api_version": settings.WHATSAPP_API_VERSION,
            "default_country_code": settings.WHATSAPP_DEFAULT_COUNTRY_CODE,
        },
        "totals": {
            "total": total,
            "sent": totals["sent"],
            "failed": totals["failed"],
            "pending": totals["pending"],
            "success_rate": success_rate,
        },
        "daily": daily,
        "by_template": by_template,
    }


@router.get("/whatsapp/logs")
async def whatsapp_logs(
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(sent|failed|pending)$"),
    search: Optional[str] = None,
    days: int = Query(30, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: dict = Depends(check_role(["superadmin", "admin"])),
):
    """Paginated WhatsApp delivery log with optional status / date / recipient-or-template search."""
    await _ensure_wa_index()
    col = get_collection("notifications")
    query = {"channel": "whatsapp", "sent_at": {"$gte": datetime.utcnow() - timedelta(days=days)}}
    if status_filter:
        query["status"] = status_filter
    if search:
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        query["$or"] = [{"target_contact": rx}, {"template_slug": rx}]

    total = await col.count_documents(query)
    cursor = col.find(query).sort("sent_at", -1).skip((page - 1) * page_size).limit(page_size)
    logs = []
    async for doc in cursor:
        logs.append({
            "id": str(doc["_id"]),
            "target_contact": doc.get("target_contact"),
            "template_slug": doc.get("template_slug"),
            "status": doc.get("status"),
            "error_message": doc.get("error_message"),
            "content": doc.get("content"),
            "sent_at": doc.get("sent_at"),
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "logs": logs,
    }
