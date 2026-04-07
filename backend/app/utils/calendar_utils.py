from app.db.mongodb import get_collection
from bson import ObjectId

CALENDAR_COLLECTIONS = [
    "STAFF_CALENDER_EVENTS",
    "STAFF_CALENDER_TASKS",
    "LEARNER_CALENDER_EVENTS",
    "LEARNER_CALENDER_TASKS"
]

async def find_user_by_id(user_id: str):
    """Fallback search across all user-related collections."""
    if not user_id or user_id == "null" or user_id == "undefined": return None
    try:
        oid = ObjectId(user_id) if isinstance(user_id, str) and len(user_id) == 24 else user_id
        for col in ["staff", "learners"]:
            user = await get_collection(col).find_one({"_id": oid})
            if user: return user
    except: pass
    return None

async def get_target_collection_name(event_dict: dict):
    is_event = event_dict.get("type") == "event"
    if is_event:
        if event_dict.get("batch_id") or event_dict.get("assigned_member_ids"):
            return "LEARNER_CALENDER_EVENTS"
        return "STAFF_CALENDER_EVENTS"
    else:
        targets = event_dict.get("target_staff_id", [])
        if not isinstance(targets, list): targets = [targets]
        for tid in targets:
            if not tid or tid == "null": continue
            user = await find_user_by_id(tid)
            if user:
                role = user.get("role", "").lower()
                if any(r in role for r in ["learner", "client"]):
                    return "LEARNER_CALENDER_TASKS"
        return "STAFF_CALENDER_TASKS"

async def find_event_across_collections(event_id: str):
    if not event_id: return None, None
    try:
        oid = ObjectId(event_id)
        for col_name in CALENDAR_COLLECTIONS:
            doc = await get_collection(col_name).find_one({"_id": oid})
            if doc: return doc, col_name
        doc = await get_collection("calendar_events").find_one({"_id": oid})
        if doc: return doc, "calendar_events"
    except: pass
    return None, None
