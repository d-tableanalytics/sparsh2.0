from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import List, Optional
from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user
from app.models.calendar_event import CalendarEventCreate, CalendarEventResponse
from app.services.notification_service import (
    send_task_created_email, send_task_updated_email, send_task_deleted_email,
    send_event_created_email, send_event_updated_email, send_event_deleted_email,
    send_conflict_notification_email
)
from app.services.activity_log_service import log_activity
from bson import ObjectId
from datetime import datetime, timedelta


router = APIRouter(prefix="/calendar/events", tags=["Calendar"])

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

async def detect_conflicts(event_dict: dict, event_id: str = None):
    """
    Checks if a given event/task conflicts with existing ones for any participant.
    Conflict logic: existing_start < new_end AND existing_end > new_start
    """
    col = get_collection("calendar_events")
    
    # ─── 1. Standardize Time Range ───
    try:
        new_start = datetime.fromisoformat(event_dict["start"].replace("Z", "+00:00")).replace(tzinfo=None)
        if event_dict.get("end"):
            new_end = datetime.fromisoformat(event_dict["end"].replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            # If no end specified, assume 1 hour as visual block for conflict
            new_end = new_start + timedelta(hours=1)
    except Exception as e:
        print(f"Conflict Parser Error: {e}")
        return []

    # ─── 2. Identify Relevant Users ───
    uids = set()
    creator_id = event_dict.get("user_id")
    if creator_id: uids.add(str(creator_id))
    
    if event_dict.get("type") == "task":
        target = event_dict.get("target_staff_id", [])
        if isinstance(target, list):
            for t in target: uids.add(str(t))
        elif target: uids.add(str(target))
    else:
        # Sessions/Events
        for mid in event_dict.get("assigned_member_ids", []): uids.add(str(mid))
        for cid in event_dict.get("coach_ids", []): uids.add(str(cid))
    
    uids = [u for u in uids if u and u != "null"]
    if not uids: return []

    # ─── 3. Query Potential Overlaps ───
    # We look for ANY event where any of our participants are involved
    query = {
        "$and": [
            {
                "$or": [
                    {"user_id": {"$in": uids}},
                    {"assigned_member_ids": {"$in": uids}},
                    {"coach_ids": {"$in": uids}},
                    {"target_staff_id": {"$in": uids}},
                    {"target_staff_id": {"$elemMatch": {"$in": uids}}}
                ]
            }
        ]
    }
    
    if event_id:
        query["$and"].append({"_id": {"$ne": ObjectId(event_id)}})

    candidates = await col.find(query).to_list(500)
    conflicts = []

    for ex in candidates:
        try:
            ex_start = datetime.fromisoformat(ex["start"].replace("Z", "+00:00")).replace(tzinfo=None)
            if ex.get("end"):
                ex_end = datetime.fromisoformat(ex["end"].replace("Z", "+00:00")).replace(tzinfo=None)
            else:
                ex_end = ex_start + timedelta(hours=1)
                
            # Logic: existing_start < new_end AND existing_end > new_start
            if ex_start < new_end and ex_end > new_start:
                # Determine overlap
                ex_uids = set()
                ex_uids.add(str(ex.get("user_id")))
                for mid in ex.get("assigned_member_ids", []): ex_uids.add(str(mid))
                for cid in ex.get("coach_ids", []): ex_uids.add(str(cid))
                target = ex.get("target_staff_id", [])
                if isinstance(target, list):
                    for t in target: ex_uids.add(str(t))
                elif target: ex_uids.add(str(target))
                
                overlap = list(set(uids) & ex_uids)
                if overlap:
                    conflicts.append({"existing": ex, "users": overlap})
        except: continue
        
    return conflicts

async def notify_users_instant(event_dict: dict, action: str, creator_name: str):
    user_ids = set()
    is_task = event_dict.get("type") == "task"

    # Identify recipients
    if is_task:
        # Assigned user
        target = event_dict.get("target_staff_id", [])
        if isinstance(target, list):
            for t in target: 
                if t: user_ids.add(t)
        elif target: user_ids.add(target)
        # Also notify creator if not already included
        user_ids.add(event_dict.get("user_id"))
    else:
        # Attendees & Coaching team
        for mid in event_dict.get("assigned_member_ids", []):
            if mid: user_ids.add(mid)
        for cid in event_dict.get("coach_ids", []):
            if cid: user_ids.add(cid)
        # Notify creator
        user_ids.add(event_dict.get("user_id"))
            
    if not user_ids: return

    # Fetch extra metadata for sessions
    batch_name = "N/A"
    quarter_name = "N/A"
    if not is_task:
        if event_dict.get("batch_id"):
            b = await get_collection("batches").find_one({"_id": ObjectId(event_dict["batch_id"])})
            if b: batch_name = b.get("name", "N/A")
        if event_dict.get("quarter_id"):
            q = await get_collection("quarters").find_one({"_id": ObjectId(event_dict["quarter_id"])})
            if q: quarter_name = q.get("name", "N/A")

    for uid in user_ids:
        if not uid: continue
        try:
            user_data = await find_user_by_id(uid)
            if not user_data: continue

            if is_task:
                if action == "created": await send_task_created_email(user_data, event_dict, creator_name)
                elif action == "updated": await send_task_updated_email(user_data, event_dict, creator_name)
                elif action == "deleted": await send_task_deleted_email(user_data, event_dict.get("title"), creator_name)
            else:
                if action == "created": await send_event_created_email(user_data, event_dict, creator_name, batch_name, quarter_name)
                elif action == "updated": await send_event_updated_email(user_data, event_dict, creator_name, batch_name, quarter_name)
                elif action == "deleted": await send_event_deleted_email(user_data, event_dict.get("title"), creator_name)
        except Exception as e:
            print(f"Notification Error for {uid}: {e}")
            
    # ─── New Conflict Logic ───
    if action in ["created", "updated"]:
        try:
            conflicts = await detect_conflicts(event_dict, event_dict.get("id"))
            for conf in conflicts:
                existing = conf["existing"]
                for conflict_uid in conf["users"]:
                    # Notify affected user about this specific conflict
                    conflict_user_data = await find_user_by_id(conflict_uid)
                    if conflict_user_data:
                        await send_conflict_notification_email(conflict_user_data, event_dict, existing)
        except Exception as e:
            print(f"Conflict Notification Error: {e}")

@router.post("/validate-conflict")
async def validate_conflict(event_data: dict, current_user: dict = Depends(get_current_user)):
    # Add creator ID if not present
    if "user_id" not in event_data:
        event_data["user_id"] = str(current_user["_id"])
    
    # We pass None for event_id as it's a prospective new one
    event_id = event_data.get("id")
    conflicts = await detect_conflicts(event_data, event_id)
    
    if conflicts:
        # Simplify response for UI
        return {
            "has_conflict": True,
            "message": "This schedule conflicts with another task or event.",
            "conflicts": [
                {"title": c["existing"]["title"], "time": c["existing"]["start"], "users": c["users"]}
                for c in conflicts
            ]
        }
    return {"has_conflict": False}

@router.post("", response_model=dict)
async def create_event(event: CalendarEventCreate, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    col = get_collection("calendar_events")
    event_dict = event.model_dump()
    
    # ─── STRICT BACKDATE VALIDATION ───
    try:
        # Standardize dates to UTC for comparison
        event_start = datetime.fromisoformat(event_dict["start"].replace("Z", "+00:00")).replace(tzinfo=None)
        
        # If event is in the past, check permissions
        if event_start < datetime.utcnow():
            settings_col = get_collection("system_settings")
            # Using find_one() - if missing, we assume RESTRICTED by default
            settings = await settings_col.find_one({"setting_name": "backdate_control"})
            
            allow = False
            if settings:
                # Global override
                if settings.get("allow_backdate") is True:
                    allow = True
                # Whitelist override
                elif current_user.get("email") in settings.get("exception_users", []):
                    allow = True
            
            if not allow:
                raise HTTPException(
                    status_code=400, 
                    detail="Operation Blocked: Past-date scheduling is restricted by system policy. Please contact SuperAdmin."
                )
    except HTTPException:
        raise
    except Exception as e:
        print(f"CRITICAL ERROR in backdate validation: {e}")
        # FAIL CLOSED: If we can't verify permission, we must block the request
        raise HTTPException(status_code=500, detail="Security validation failed. Request blocked.")


    event_dict["user_id"] = str(current_user["_id"])
    event_dict["created_at"] = datetime.utcnow()

    
    # Send notification in background
    creator_name = current_user.get("full_name") or current_user.get("first_name", "System Admin")
    background_tasks.add_task(notify_users_instant, event_dict, "created", creator_name)


    
    # ─── Recursive Generation Engine ───
    repeat_type = event_dict.get("repeat", "Does not repeat")
    end_date_str = event_dict.get("repeat_end_date")
    
    if repeat_type != "Does not repeat" and end_date_str:
        try:
            start_dt = datetime.fromisoformat(event_dict["start"].replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            # Ensure end_dt is the end of that day
            if len(end_date_str) <= 10: end_dt = end_dt.replace(hour=23, minute=59, second=59)
            
            generated_events = []
            curr_dt = start_dt
            interval = event_dict.get("repeat_interval", 1) or 1
            
            while curr_dt <= end_dt:
                new_ev = event_dict.copy()
                # Maintain original time parts but update date
                new_ev["start"] = curr_dt.isoformat()
                # If end exists, update it relatively
                if event_dict.get("end"):
                    orig_end = datetime.fromisoformat(event_dict["end"].replace("Z", "+00:00"))
                    diff = orig_end - start_dt
                    new_ev["end"] = (curr_dt + diff).isoformat()
                
                new_ev["created_at"] = datetime.utcnow()
                generated_events.append(new_ev)
                
                # Advance curr_dt based on type
                if repeat_type == "Daily": curr_dt += timedelta(days=1)
                elif "Weekly" in repeat_type: curr_dt += timedelta(weeks=1)
                elif repeat_type == "Monthly":
                    # Simple month advance
                    month = curr_dt.month + 1
                    year = curr_dt.year + (month - 1) // 12
                    month = (month - 1) % 12 + 1
                    day = min(curr_dt.day, 28) # Safety for simple implementation
                    curr_dt = curr_dt.replace(year=year, month=month, day=day)
                elif repeat_type == "Annually":
                    curr_dt = curr_dt.replace(year=curr_dt.year + 1)
                elif repeat_type == "periodic":
                    curr_dt += timedelta(days=interval)
                else: break # Failsafe
                
                if len(generated_events) > 365: break # Max 1 year of daily tasks
            
            if generated_events:
                await col.insert_many(generated_events)
                await log_activity(current_user, "Create Event", "calendar", f"Generated {len(generated_events)} recurring events")
                return {"message": f"Successfully generated {len(generated_events)} recurring duties."}
        except Exception as e:
            print(f"Error in generation: {e}")
            # Fallback to single insert if generation fails logic
    
    col = get_collection("calendar_events")
    result = await col.insert_one(event_dict)
    event_dict["id"] = str(result.inserted_id)
    await log_activity(current_user, "Create Event", "calendar", f"Created event: {event_dict['title']}")
    return {"id": str(result.inserted_id), "message": "Event created successfully"}


@router.put("/{event_id}")
async def update_event(event_id: str, updates: dict, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    col = get_collection("calendar_events")
    # RBAC: Only creator or superadmin can update
    existing = await col.find_one({"_id": ObjectId(event_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")
        
    cur_user_id = str(current_user["_id"])
    role = current_user.get("role")
    
    is_admin = role in ["superadmin", "admin"]
    is_creator = existing.get("user_id") == cur_user_id
    is_assigned = cur_user_id in (existing.get("target_staff_id") or []) or cur_user_id in (existing.get("assigned_member_ids") or [])

    if not (is_admin or is_creator or is_assigned):
        raise HTTPException(status_code=403, detail="Not authorized to edit this event")
    
    # Delegates can ONLY update status and remarks
    if not (is_admin or is_creator):
        allowed_fields = ["status", "status_remark", "completed_at"]
        updates = {k: v for k, v in updates.items() if k in allowed_fields}
        if not updates:
             raise HTTPException(status_code=403, detail="Delegates can only update status, remarks, or completion timing")
         
    if updates.get("start"):
        try:
            event_start = datetime.fromisoformat(updates["start"].replace("Z", "+00:00")).replace(tzinfo=None)
            if event_start < datetime.utcnow():
                settings_col = get_collection("system_settings")
                settings = await settings_col.find_one({"setting_name": "backdate_control"})
                
                allow = False
                if settings:
                    if settings.get("allow_backdate", False): allow = True
                    elif current_user.get("email") in settings.get("exception_users", []): allow = True
                
                if not allow:
                    raise HTTPException(status_code=400, detail="Backdated tasks or events are not allowed.")
        except HTTPException: raise
        except Exception: pass

    # ─── Record Completion Timestamp ───
    if updates.get("status") == "completed" and existing.get("status") != "completed":
        updates["completed_at"] = datetime.utcnow()
    elif updates.get("status") == "schedule": # If moved back, clear completion
        updates["completed_at"] = None

    updates["updated_at"] = datetime.utcnow()
    col = get_collection("calendar_events")
    await col.update_one({"_id": ObjectId(event_id)}, {"$set": updates})

    await log_activity(current_user, "Update Event", "calendar", f"Updated event ID: {event_id}")


    # Trigger notification
    creator_name = current_user.get("full_name") or current_user.get("first_name", "System Admin")
    background_tasks.add_task(notify_users_instant, {**existing, **updates}, "updated", creator_name)

    return {"message": "Event updated"}

@router.delete("/{event_id}")
async def delete_event(event_id: str, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    col = get_collection("calendar_events")
    existing = await col.find_one({"_id": ObjectId(event_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")
        
    if current_user.get("role") != "superadmin" and existing.get("user_id") != str(current_user["_id"]):
         raise HTTPException(status_code=403, detail="Not authorized to delete this event")
         
    col = get_collection("calendar_events")
    await col.delete_one({"_id": ObjectId(event_id)})
    await log_activity(current_user, "Delete Event", "calendar", f"Deleted event ID: {event_id}")
    
    # Notify deletion
    creator_name = current_user.get("full_name") or current_user.get("first_name", "System Admin")
    background_tasks.add_task(notify_users_instant, existing, "deleted", creator_name)
    
    return {"message": "Event deleted"}


@router.get("")
async def get_all_events(target_user_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """
    Role-aware aggregation:
    - Superadmin: All events OR specific user events if target_user_id provided.
    - Coach: Events they created OR are assigned to.
    - Learner: Events they created OR are assigned to them.
    """
    events = []
    current_uid = str(current_user["_id"])
    role = current_user.get("role", "").lower()
    
    # Check authorization for target_user_id
    effective_user_id = current_uid
    if target_user_id and role in ["superadmin", "admin"]:
        effective_user_id = target_user_id
    
    # ─── 1. System Events (Batches/Quarters) ───
    if not target_user_id:
        if role in ["superadmin", "admin"]:
            batches = await get_collection("batches").find({}).to_list(100)
            quarters = await get_collection("quarters").find({}).to_list(200)
        else:
            batch_ids = current_user.get("batch_ids", [current_user.get("batch_id")])
            batches = await get_collection("batches").find({"_id": {"$in": [ObjectId(bid) for bid in batch_ids if bid]}}).to_list(10)
            quarters = await get_collection("quarters").find({"batch_id": {"$in": [str(bid) for bid in batch_ids if bid]}}).to_list(50)
    else:
        # If looking at a target user, we don't show generic system events unless relevant
        batches = []
        quarters = []

    for b in batches:
        if b.get("start_date"):
            events.append({
                "id": str(b["_id"]), "title": b["name"], "type": "batch", "start": b["start_date"],
                "color": "var(--accent-indigo)", "bg": "var(--accent-indigo-bg)", "editable": False
            })
    for q in quarters:
        if q.get("start_date"):
            events.append({
                "id": str(q["_id"]), "title": f"Q: {q['name']}", "type": "quarter", "start": q["start_date"],
                "color": "var(--accent-orange)", "bg": "var(--accent-orange-bg)", "editable": False
            })
            
    # ─── 2. Custom Events (CalendarEvents) ───
    custom_col = get_collection("calendar_events")
    
    if role in ["superadmin", "admin"] and not target_user_id:
        # Administrators see everything if not filtering
        user_events = await custom_col.find({}).to_list(1000)
    else:
        # Show events linked to the effective_user_id
        user_events = await custom_col.find({
            "$or": [
                {"user_id": effective_user_id},
                {"assigned_member_ids": effective_user_id},
                {"coach_ids": effective_user_id},
                {"target_staff_id": effective_user_id}
            ]
        }).to_list(1000)

    for c in user_events:
        events.append({
            "id": str(c["_id"]),
            "title": c["title"],
            "type": c["type"],
            "start": c["start"],
            "end": c.get("end"),
            "color": c.get("color"),
            "bg": c.get("bg"),
            "allDay": c.get("all_day", False),
            "extendedProps": { 
                **{k: v for k, v in c.items() if k not in ["_id", "created_at", "updated_at"]},
                "id": str(c["_id"]),
                "isCreator": c.get("user_id") == current_uid,
                "isAssigned": current_uid in (c.get("target_staff_id") or []) or current_uid in (c.get("assigned_member_ids") or []),
                "canEdit": role in ["superadmin", "admin"] or c.get("user_id") == current_uid
            }

        })
    
    return events
