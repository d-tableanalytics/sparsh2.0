from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Form
from typing import List, Optional
from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user
from app.models.calendar_event import CalendarEventCreate, CalendarEventResponse
from app.services.notification_service import (
    send_task_created_email, send_task_updated_email, send_task_deleted_email,
    send_event_created_email, send_event_updated_email, send_event_deleted_email,
    send_conflict_notification_email, send_attendance_thanks_email, send_attendance_absent_email
)
from app.services.activity_log_service import log_activity
from app.services.s3_service import upload_file_to_s3
from app.services.event_sync_service import sync_event_to_collection
from bson import ObjectId
from datetime import datetime, timedelta, timezone

router = APIRouter(prefix="/calendar/events", tags=["Calendar"])

from app.utils.calendar_utils import (

    CALENDAR_COLLECTIONS, find_user_by_id, 
    get_target_collection_name, find_event_across_collections
)

async def detect_conflicts(event_dict: dict, event_id: str = None):
    # Standardize Time Range
    try:
        new_start = datetime.fromisoformat(event_dict["start"].replace("Z", "+00:00")).replace(tzinfo=None)
        if event_dict.get("end"):
            new_end = datetime.fromisoformat(event_dict["end"].replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            new_end = new_start + timedelta(hours=1)
    except Exception as e:
        print(f"Conflict Parser Error: {e}")
        return []

    uids = set()
    creator_id = event_dict.get("user_id")
    if creator_id: uids.add(str(creator_id))
    if event_dict.get("type") == "task":
        target = event_dict.get("target_staff_id", [])
        if isinstance(target, list):
            for t in target: uids.add(str(t))
        elif target: uids.add(str(target))
    else:
        for mid in event_dict.get("assigned_member_ids", []): uids.add(str(mid))
        for cid in event_dict.get("coach_ids", []): uids.add(str(cid))
    uids = [u for u in uids if u and u != "null"]
    if not uids: return []

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

    conflicts = []
    # Search all collections for overlaps
    for col_name in (CALENDAR_COLLECTIONS + ["calendar_events"]):
        candidates = await get_collection(col_name).find(query).to_list(100)
        for ex in candidates:
            try:
                ex_start = datetime.fromisoformat(ex["start"].replace("Z", "+00:00")).replace(tzinfo=None)
                ex_end = datetime.fromisoformat(ex["end"].replace("Z", "+00:00")).replace(tzinfo=None) if ex.get("end") else ex_start + timedelta(hours=1)
                if ex_start < new_end and ex_end > new_start:
                    ex_uids = set([str(ex.get("user_id"))])
                    for mid in ex.get("assigned_member_ids", []): ex_uids.add(str(mid))
                    for cid in ex.get("coach_ids", []): ex_uids.add(str(cid))
                    target = ex.get("target_staff_id", [])
                    if isinstance(target, list):
                        for t in target: ex_uids.add(str(t))
                    elif target: ex_uids.add(str(target))
                    overlap = list(set(uids) & ex_uids)
                    if overlap: conflicts.append({"existing": ex, "users": overlap})
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
    event_dict = event.model_dump()
    # Backdate validation logic... (omitted summary for brevity, keeping existing code)
    # [STRICT BACKDATE VALIDATION CODE REMAINS UNCHANGED]
    try:
        event_start = datetime.fromisoformat(event_dict["start"].replace("Z", "+00:00")).replace(tzinfo=None)
        if event_start < datetime.utcnow():
            settings_col = get_collection("system_settings")
            settings = await settings_col.find_one({"setting_name": "backdate_control"})
            allow = False
            if settings:
                if settings.get("allow_backdate") is True: allow = True
                elif current_user.get("email") in settings.get("exception_users", []): allow = True
            if not allow:
                raise HTTPException(status_code=400, detail="Operation Blocked: Past-date scheduling is restricted by system policy.")
    except HTTPException: raise
    except Exception as e:
        print(f"CRITICAL ERROR in backdate validation: {e}")
        raise HTTPException(status_code=500, detail="Security validation failed. Request blocked.")

    event_dict["user_id"] = str(current_user["_id"])
    event_dict["created_at"] = datetime.utcnow()
    
    # ─── Target Collection Selection ───
    col_name = await get_target_collection_name(event_dict)
    col = get_collection(col_name)

    creator_name = current_user.get("full_name") or current_user.get("first_name", "System Admin")

    # ─── Recursive Generation Engine ───
    repeat_type = event_dict.get("repeat", "Does not repeat")
    end_date_str = event_dict.get("repeat_end_date")
    if repeat_type != "Does not repeat" and end_date_str:
        # Generate a unique series ID to group these occurrences
        event_dict["recurring_group_id"] = str(ObjectId())
        try:
            # Standardize Start Date
            raw_start = event_dict["start"].replace("Z", "+00:00")
            start_dt = datetime.fromisoformat(raw_start)
            if start_dt.tzinfo is None: start_dt = start_dt.replace(tzinfo=timezone.utc)

            # Standardize End Date
            raw_end = end_date_str.replace("Z", "+00:00")
            if len(raw_end) <= 10: 
                # If only date is provided, make it end-of-day UTC
                raw_end = f"{raw_end}T23:59:59+00:00"
            
            end_dt = datetime.fromisoformat(raw_end)
            if end_dt.tzinfo is None: end_dt = end_dt.replace(tzinfo=timezone.utc)

            if end_dt < start_dt:
                print(f"Recurring Skip: End date {end_dt} is before start date {start_dt}")
            else:
                generated_events = []
                curr_dt = start_dt
                interval = event_dict.get("repeat_interval", 1) or 1
                
                while curr_dt <= end_dt:
                    new_ev = event_dict.copy()
                    new_ev["start"] = curr_dt.isoformat()
                    if event_dict.get("end"):
                        raw_orig_end = event_dict["end"].replace("Z", "+00:00")
                        orig_end = datetime.fromisoformat(raw_orig_end)
                        if orig_end.tzinfo is None: orig_end = orig_end.replace(tzinfo=timezone.utc)
                        diff = orig_end - start_dt
                        new_ev["end"] = (curr_dt + diff).isoformat()
                    
                    new_ev["created_at"] = datetime.utcnow()
                    # Remove any existing ID if we are cloning
                    if "_id" in new_ev: del new_ev["_id"]
                    generated_events.append(new_ev)
                    
                    if repeat_type == "Daily": curr_dt += timedelta(days=1)
                    elif "Weekly" in repeat_type: curr_dt += timedelta(weeks=1)
                    elif repeat_type == "Monthly":
                        month = curr_dt.month + 1; year = curr_dt.year + (month - 1) // 12; month = (month - 1) % 12 + 1; day = min(curr_dt.day, 28)
                        curr_dt = curr_dt.replace(year=year, month=month, day=day)
                    elif repeat_type == "Annually": curr_dt = curr_dt.replace(year=curr_dt.year + 1)
                    elif repeat_type == "periodic": curr_dt += timedelta(days=interval)
                    else: break
                    if len(generated_events) > 365: break
                
                if generated_events:
                    await col.insert_many(generated_events)
                    # Log activity for batch creation
                    await log_activity(current_user, "Create Recurring", col_name, f"Generated {len(generated_events)} events for {event_dict['title']}")
                    return {"message": f"Successfully generated {len(generated_events)} recurring duties."}
        except Exception as e:
            print(f"RECURSIVE ENGINE FAILURE: {e}")
            # Fall back to single event creation below if recursion fails
    
    result = await col.insert_one(event_dict)
    event_dict["id"] = str(result.inserted_id)
    background_tasks.add_task(notify_users_instant, event_dict, "created", creator_name)
    await log_activity(current_user, "Create Event", col_name, f"Created in {col_name}: {event_dict['title']}")
    return {"id": str(result.inserted_id), "message": f"Event created in {col_name}"}

@router.put("/{event_id}")
async def update_event(event_id: str, updates: dict, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")
        
    is_admin = current_user.get("role") in ["superadmin", "admin"]
    is_creator = existing.get("user_id") == str(current_user["_id"])

    if not (is_admin or is_creator):
        raise HTTPException(status_code=403, detail="Not authorized to edit this event. Assignees have read-only access.")
         
    # ─── Record Completion Timestamp ───
    if updates.get("status") == "completed" and existing.get("status") != "completed":
        updates["completed_at"] = datetime.utcnow()
    elif updates.get("status") == "schedule":
        updates["completed_at"] = None

    updates["updated_at"] = datetime.utcnow()

    # ─── Movement Logic ───
    projected = {**existing, **updates}
    new_col_name = await get_target_collection_name(projected)
    
    if new_col_name != col_name and col_name != "calendar_events":
        # Move document between collections
        await get_collection(col_name).delete_one({"_id": ObjectId(event_id)})
        # Ensure we don't have _id as string if it was converted
        if "id" in projected: del projected["id"]
        await get_collection(new_col_name).insert_one(projected)
        final_doc = projected
    else:
        # Standard update within the same collection
        await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$set": updates})
        final_doc = projected

    await log_activity(current_user, "Update Event", new_col_name, f"Updated event ID: {event_id}")
    creator_name = current_user.get("full_name") or current_user.get("first_name", "System Admin")
    final_doc["id"] = str(event_id)
    background_tasks.add_task(notify_users_instant, final_doc, "updated", creator_name)

    # ─── Recurring Series Timeline Sync ───
    if updates.get("repeat_end_date") and existing.get("recurring_group_id"):
        new_end_str = updates["repeat_end_date"]
        old_end_str = existing.get("repeat_end_date")
        
        if new_end_str != old_end_str:
            try:
                gid = existing["recurring_group_id"]
                # Standardize parsing
                new_raw_end = new_end_str.replace("Z", "+00:00")
                if len(new_raw_end) <= 10: new_raw_end += "T23:59:59+00:00"
                new_end_dt = datetime.fromisoformat(new_raw_end)
                if new_end_dt.tzinfo is None: new_end_dt = new_end_dt.replace(tzinfo=timezone.utc)

                # 1. DELETE: Future occurrences past the new end date
                await get_collection(new_col_name).delete_many({
                    "recurring_group_id": gid,
                    "start": {"$gt": new_end_dt.isoformat()}
                })

                # 2. GENERATE: If expanded, create new ones
                if old_end_str:
                    old_raw_end = old_end_str.replace("Z", "+00:00")
                    if len(old_raw_end) <= 10: old_raw_end += "T23:59:59+00:00"
                    current_end_dt = datetime.fromisoformat(old_raw_end)
                    if current_end_dt.tzinfo is None: current_end_dt = current_end_dt.replace(tzinfo=timezone.utc)
                    
                    if new_end_dt > current_end_dt:
                        # Find the step from repeat_type
                        repeat_type = existing.get("repeat", "Daily")
                        interval = existing.get("repeat_interval", 1) or 1
                        
                        generated = []
                        curr_dt = current_end_dt
                        # Avoid duplicate on the current_end_dt itself
                        if repeat_type == "Daily": curr_dt += timedelta(days=1)
                        elif "Weekly" in repeat_type: curr_dt += timedelta(weeks=1)
                        elif repeat_type == "Monthly":
                            month = curr_dt.month + 1; year = curr_dt.year + (month - 1) // 12; month = (month - 1) % 12 + 1; day = min(curr_dt.day, 28)
                            curr_dt = curr_dt.replace(year=year, month=month, day=day)
                        elif repeat_type == "periodic": curr_dt += timedelta(days=interval)
                        
                        while curr_dt <= new_end_dt:
                            new_ev = {**existing, **updates}
                            new_ev["start"] = curr_dt.isoformat()
                            if new_ev.get("end"):
                                diff = (datetime.fromisoformat(existing["end"].replace("Z", "+00:00")) - datetime.fromisoformat(existing["start"].replace("Z", "+00:00")))
                                new_ev["end"] = (curr_dt + diff).isoformat()
                            
                            new_ev["created_at"] = datetime.utcnow()
                            if "_id" in new_ev: del new_ev["_id"]
                            generated.append(new_ev)
                            
                            if repeat_type == "Daily": curr_dt += timedelta(days=1)
                            elif "Weekly" in repeat_type: curr_dt += timedelta(weeks=1)
                            elif repeat_type == "Monthly":
                                month = curr_dt.month + 1; year = curr_dt.year + (month - 1) // 12; month = (month - 1) % 12 + 1; day = min(curr_dt.day, 28)
                                curr_dt = curr_dt.replace(year=year, month=month, day=day)
                            elif repeat_type == "periodic": curr_dt += timedelta(days=interval)
                            else: break
                            if len(generated) > 365: break
                        
                        if generated:
                            await get_collection(new_col_name).insert_many(generated)
            except Exception as se:
                print(f"SERIES SYNC FAILURE: {se}")

    return {"message": f"Event updated in {new_col_name}"}


@router.post("/{event_id}/attendance")
async def mark_attendance(event_id: str, attendance_data: dict, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")
    if current_user.get("role") not in ["superadmin", "admin"] and existing.get("user_id") != str(current_user["_id"]):
         raise HTTPException(status_code=403, detail="Not authorized to mark attendance")
         
    # Expected payload: {"attendees": {"user_id_1": True, "user_id_2": False}}
    attendance = attendance_data.get("attendees", {})
    
    await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$set": {"attendance": attendance, "updated_at": datetime.utcnow()}})
    await log_activity(current_user, "Mark Attendance", col_name, f"Marked attendance for session: {event_id}")
    await sync_event_to_collection(event_id)

    # Process background emails
    async def process_attendance_emails():
        user_col = get_collection("users")
        for user_id, is_present in attendance.items():
            user = await user_col.find_one({"_id": ObjectId(user_id)})
            if user:
                try:
                    if is_present:
                        await send_attendance_thanks_email(user, existing)
                    else:
                        await send_attendance_absent_email(user, existing)
                except Exception as e:
                    print(f"Error sending attendance email to {user_id}: {e}")

    background_tasks.add_task(process_attendance_emails)
    
    return {"message": "Attendance marked successfully and notifications triggered"}
    
@router.post("/{event_id}/upload-content")
async def upload_content(event_id: str, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")
    
    # Creator or Admin only
    if current_user.get("role") not in ["superadmin", "admin"] and existing.get("user_id") != str(current_user["_id"]):
         raise HTTPException(status_code=403, detail="Only the creator or an administrator can upload content")

    try:
        url = upload_file_to_s3(file.file, file.filename, file.content_type)
        content_obj = {"id": str(ObjectId()), "name": file.filename, "url": url, "file_type": file.content_type, "uploaded_by": str(current_user["_id"]), "uploaded_at": datetime.utcnow(), "views": 0}
        await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$push": {"contents": content_obj}})
        await sync_event_to_collection(event_id)
        return {"message": "Content uploaded successfully", "content": content_obj}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


import os
import aiofiles
import tempfile
from app.services.transcription_service import process_background_upload_and_transcribe

@router.post("/{event_id}/upload-resource")
async def upload_resource(event_id: str, background_tasks: BackgroundTasks, file: UploadFile = File(...), resource_type: str = Form(...), current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")

    # Creator or Admin only
    if current_user.get("role") not in ["superadmin", "admin"] and existing.get("user_id") != str(current_user["_id"]):
         raise HTTPException(status_code=403, detail="Only the creator or an administrator can upload resources")

    try:
        resource_id = str(ObjectId())
        # Processing code (omitted for brevity, remains logic-same)
        # [TMP FILE HANDLING CODE REMAINS UNCHANGED]
        tmp_dir = os.path.join(tempfile.gettempdir(), f"sparsh_uploads_{event_id}")
        os.makedirs(tmp_dir, exist_ok=True)
        local_path = os.path.join(tmp_dir, f"{resource_id}_{file.filename}")
        async with aiofiles.open(local_path, 'wb') as out_file:
            while content := await file.read(1024 * 1024): await out_file.write(content)
        resource_obj = {"id": resource_id, "name": file.filename, "url": None, "system_type": resource_type, "file_type": file.content_type, "uploaded_by": str(current_user["_id"]), "uploaded_at": datetime.utcnow(), "status": "processing", "transcription": None, "views": 0}
        await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$push": {"resources": resource_obj}})
        # ... background tasks
        background_tasks.add_task(process_background_upload_and_transcribe, event_id, resource_id, local_path, file.filename, file.content_type, resource_type)
        return {"message": "Resource accepted.", "resource": resource_obj}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{event_id}")
async def delete_event(event_id: str, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")
    if current_user.get("role") not in ["superadmin", "admin"] and existing.get("user_id") != str(current_user["_id"]):
         raise HTTPException(status_code=403, detail="Not authorized to delete this event")
    await get_collection(col_name).delete_one({"_id": ObjectId(event_id)})
    creator_name = current_user.get("full_name") or current_user.get("first_name", "System Admin")
    background_tasks.add_task(notify_users_instant, existing, "deleted", creator_name)
    return {"message": "Deleted successfully"}


@router.get("/{event_id}")
async def get_event(event_id: str, current_user: dict = Depends(get_current_user)):
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Event not found")
    event["id"] = str(event["_id"])
    del event["_id"]
    return event


@router.get("")
async def get_all_events(target_user_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    events = []
    current_uid = str(current_user["_id"])
    role = current_user.get("role", "").lower()
    effective_user_id = target_user_id if (target_user_id and role in ["superadmin", "admin"]) else current_uid
    
    # 1. Batches/Quarters (Omitted summary, logic remains)
    # [BATCHES/QUARTERS FETCH LOGIC REMAINS UNCHANGED]
    if not target_user_id:
        if role in ["superadmin", "admin"]:
            batches = await get_collection("batches").find({}).to_list(100)
            quarters = await get_collection("quarters").find({}).to_list(200)
        else:
            batch_ids = current_user.get("batch_ids", [current_user.get("batch_id")])
            batches = await get_collection("batches").find({"_id": {"$in": [ObjectId(bid) for bid in batch_ids if bid]}}).to_list(10)
            quarters = await get_collection("quarters").find({"batch_id": {"$in": [str(bid) for bid in batch_ids if bid]}}).to_list(50)
    else:
        batches = []; quarters = []
    for b in batches:
        if b.get("start_date"): events.append({"id": str(b["_id"]), "title": b["name"], "type": "batch", "start": b["start_date"], "color": "var(--accent-indigo)", "bg": "var(--accent-indigo-bg)", "editable": False})
    for q in quarters:
        if q.get("start_date"): events.append({"id": str(q["_id"]), "title": f"Q: {q['name']}", "type": "quarter", "start": q["start_date"], "color": "var(--accent-orange)", "bg": "var(--accent-orange-bg)", "editable": False})
            
    # 2. Aggregated Custom Events from 4 Collections + Legacy
    for col_name in (CALENDAR_COLLECTIONS + ["calendar_events"]):
        custom_col = get_collection(col_name)
        if role in ["superadmin", "admin"] and not target_user_id:
            batch = await custom_col.find({}).to_list(1000)
        else:
            batch = await custom_col.find({"$or": [
                {"user_id": effective_user_id},
                {"assigned_member_ids": effective_user_id},
                {"coach_ids": effective_user_id},
                {"target_staff_id": effective_user_id}
            ]}).to_list(1000)
        
        for c in batch:
            events.append({
                "id": str(c["_id"]), "title": c["title"], "type": c["type"], "start": c["start"], "end": c.get("end"), "allDay": c.get("all_day", False),
                "extendedProps": { **{k: v for k, v in c.items() if k not in ["_id", "created_at", "updated_at"]}, "id": str(c["_id"]), "isCreator": c.get("user_id") == current_uid, "isAssigned": current_uid in (c.get("target_staff_id") or []) or current_uid in (c.get("assigned_member_ids") or []), "canEdit": role in ["superadmin", "admin"] or c.get("user_id") == current_uid, "source_col": col_name }
            })
    return events


@router.get("/{event_id}/resources/{resource_id}")
async def get_resource_details(event_id: str, resource_id: str, current_user: dict = Depends(get_current_user)):
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Event not found")
    all_items = (event.get("resources") or []) + (event.get("contents") or [])
    resource = next((r for r in all_items if r.get("id") == resource_id), None)
    if not resource: raise HTTPException(status_code=404, detail="Resource not found")
    # ... URL signing logic (unchanged)
    from app.services.s3_service import get_signed_url
    url = resource.get("url")
    if url and ".amazonaws.com/" in url:
        try:
            s3_key = url.split(".amazonaws.com/")[-1]
            resource["url"] = get_signed_url(s3_key)
        except Exception: pass
    return resource


@router.post("/{event_id}/resources/{resource_id}/view")
async def track_resource_view(event_id: str, resource_id: str, current_user: dict = Depends(get_current_user)):
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Event not found")
    await get_collection(col_name).update_one({"_id": ObjectId(event_id), "resources.id": resource_id}, {"$inc": {"resources.$.views": 1}})
    await get_collection(col_name).update_one({"_id": ObjectId(event_id), "contents.id": resource_id}, {"$inc": {"contents.$.views": 1}})
    return {"message": "View tracked"}


@router.post("/{event_id}/resources/{resource_id}/chat")
async def ai_companion_chat(event_id: str, resource_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    from openai import AsyncOpenAI
    from app.config.settings import settings
    
    question = payload.get("question")
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")
        
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Event not found")
    
    resource = next((r for r in (event.get("resources") or []) if r.get("id") == resource_id), None)
    if not resource:
        resource = next((r for r in (event.get("contents") or []) if r.get("id") == resource_id), None)
    
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
        
    transcription = resource.get("transcription", "No transcription available for this file.")
    file_name = resource.get("name", "Unknown File")
    system_type = resource.get("system_type", "Document")
    
    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        
        system_prompt = f"""You are a helpful AI Companion for the Sparsh ERP system. 
You are assisting a user with a specific file: "{file_name}" (Type: {system_type}).
Below is the transcription of the audio/video content if available:
---
{transcription}
---
Please answer the user's question based strictly on this transcription and the file context. 
If the user asks about specific parts of the video/audio, try to infer timestamps if mentions of time or clear segments are in the transcription.
Structure your response clearly. Use markdown.
"""
        
        response = await client.chat.completions.create(
            model="gpt-4o", # Using a standard model
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.7
        )
        
        return {"answer": response.choices[0].message.content}
    except Exception as e:
        print(f"AI Chat Error: {e}")
        # Check if it's a quota issue
        if "insufficient_quota" in str(e):
             return {"answer": "I'm sorry, my AI processing unit (OpenAI) has run out of credits. Please contact your administrator to top up the OpenAI API quota.", "error": "insufficient_quota"}
        return {"answer": f"Error interacting with AI: {str(e)}"}
@router.patch("/{event_id}/complete")
async def complete_event(event_id: str, current_user: dict = Depends(get_current_user)):
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Event not found")
    if current_user.get("role") not in ["superadmin", "admin"] and event.get("user_id") != str(current_user["_id"]):
         raise HTTPException(status_code=403, detail="Not authorized")
    await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$set": {"status": "completed", "updated_at": datetime.utcnow()}})
    await sync_event_to_collection(event_id)
    return {"message": "Session marked as completed", "status": "completed"}

