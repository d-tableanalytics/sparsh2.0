from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user
from app.models.calendar_event import CalendarEventCreate, CalendarEventResponse
from bson import ObjectId
from datetime import datetime, timedelta

router = APIRouter(prefix="/calendar", tags=["Calendar"])

@router.post("/events", response_model=dict)
async def create_event(event: CalendarEventCreate, current_user: dict = Depends(get_current_user)):
    col = get_collection("calendar_events")
    event_dict = event.model_dump()
    event_dict["user_id"] = str(current_user["_id"])
    event_dict["created_at"] = datetime.utcnow()
    
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
                return {"message": f"Successfully generated {len(generated_events)} recurring duties."}
        except Exception as e:
            print(f"Error in generation: {e}")
            # Fallback to single insert if generation fails logic
    
    result = await col.insert_one(event_dict)
    return {"id": str(result.inserted_id), "message": "Event created successfully"}

@router.put("/events/{event_id}")
async def update_event(event_id: str, updates: dict, current_user: dict = Depends(get_current_user)):
    col = get_collection("calendar_events")
    # RBAC: Only creator or superadmin can update
    existing = await col.find_one({"_id": ObjectId(event_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")
        
    if current_user.get("role") != "superadmin" and existing.get("user_id") != str(current_user["_id"]):
         raise HTTPException(status_code=403, detail="Not authorized to edit this event")
         
    updates["updated_at"] = datetime.utcnow()
    await col.update_one({"_id": ObjectId(event_id)}, {"$set": updates})
    return {"message": "Event updated"}

@router.delete("/events/{event_id}")
async def delete_event(event_id: str, current_user: dict = Depends(get_current_user)):
    col = get_collection("calendar_events")
    existing = await col.find_one({"_id": ObjectId(event_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")
        
    if current_user.get("role") != "superadmin" and existing.get("user_id") != str(current_user["_id"]):
         raise HTTPException(status_code=403, detail="Not authorized to delete this event")
         
    await col.delete_one({"_id": ObjectId(event_id)})
    return {"message": "Event deleted"}

@router.get("/events")
async def get_all_events(current_user: dict = Depends(get_current_user)):
    """
    Role-aware aggregation:
    - Superadmin: All events.
    - Coach: Events they created OR are assigned to.
    - Learner: Events they created OR are assigned to them (via assigned_user_id).
    """
    events = []
    user_id = str(current_user["_id"])
    role = current_user.get("role", "").lower()
    
    # ─── 1. System Events (Batches/Quarters) ───
    # Admins see all, Learners see only their batch/quarter if linked
    if role in ["superadmin", "admin"]:
        batches = await get_collection("batches").find({}).to_list(100)
        quarters = await get_collection("quarters").find({}).to_list(200)
    else:
        # Simple policy: Learners only see metadata for their own batch
        batch_ids = current_user.get("batch_ids", [current_user.get("batch_id")])
        batches = await get_collection("batches").find({"_id": {"$in": [ObjectId(bid) for bid in batch_ids if bid]}}).to_list(10)
        quarters = await get_collection("quarters").find({"batch_id": {"$in": [str(bid) for bid in batch_ids if bid]}}).to_list(50)

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
    
    if role in ["superadmin", "admin"]:
        # Administrators see everything
        user_events = await custom_col.find({}).to_list(1000)
    else:
        # Users see what they created OR what was assigned to them
        user_events = await custom_col.find({
            "$or": [
                {"user_id": user_id},
                {"assigned_user_id": user_id}
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
                "canEdit": role in ["superadmin", "admin"] or c.get("user_id") == user_id
            }
        })
    
    return events
