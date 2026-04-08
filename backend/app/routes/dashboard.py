from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict
from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user, check_role
from app.models.user import UserRole
from datetime import datetime, timedelta
from bson import ObjectId

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/stats")
async def get_dashboard_stats(current_user: dict = Depends(get_current_user)):
    # Check if user is staff (admin or superadmin or coach)
    role = current_user.get("role", "").lower()
    if role not in ["superadmin", "admin", "coach"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    companies_col = get_collection("companies")
    batches_col = get_collection("batches")
    learners_col = get_collection("learners")
    from app.utils.calendar_utils import CALENDAR_COLLECTIONS
    session_cols = CALENDAR_COLLECTIONS + ["calendar_events"]

    # 1. Registered Entities (Total Companies)
    registered_entities = await companies_col.count_documents({})

    # 2. Active Batches (status='active')
    active_batches = await batches_col.count_documents({"status": "active"})

    # 3. Strategic Learners (Total learners)
    strategic_learners = await get_collection("learners").count_documents({})

    # 4. Session Velocity (Completed in last 30 days)
    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
    session_velocity = 0
    
    # 5. Operational Pulse (Last 14 Days for better trend)
    pulse_data = []
    today = datetime.utcnow().date()
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.strftime("%d %b")
        count = 0
        
        # Count sessions starting on that day that are completed
        for col in session_cols:
            count += await get_collection(col).count_documents({
                "start": {"$regex": f"^{day.isoformat()}"},
                "status": "completed"
            })
        pulse_data.append({"name": day_str, "sessions": count})

    # Total Velocity for the KPI (30 days)
    for col in session_cols:
        session_velocity += await get_collection(col).count_documents({
            "status": "completed",
            "start": {"$gte": thirty_days_ago}
        })

    # 6. Session Mix (Pie Chart)
    mix_data = []
    mix_counts = {"Strategic": 0, "Technical": 0, "Operational": 0, "Other": 0}
    for col in session_cols:
        cursor = get_collection(col).find({})
        async for session in cursor:
            s_type = session.get("session_type", "Other")
            # Map types to segments
            if any(kw in s_type for kw in ["Direct", "Strategy", "CEO"]): mix_counts["Strategic"] += 1
            elif any(kw in s_type for kw in ["Review", "Module", "Session"]): mix_counts["Technical"] += 1
            elif any(kw in s_type for kw in ["Support", "Check"]): mix_counts["Operational"] += 1
            else: mix_counts["Other"] += 1
    
    colors = {
        "Strategic": "var(--accent-indigo)", 
        "Technical": "var(--accent-orange)", 
        "Operational": "var(--accent-green)", 
        "Other": "var(--text-muted)"
    }
    for k, v in mix_counts.items():
        if v > 0:
            mix_data.append({"name": k, "value": v, "color": colors.get(k, "var(--text-muted)")})

    return {
        "kpis": {
            "registered_entities": registered_entities,
            "active_batches": active_batches,
            "strategic_learners": strategic_learners,
            "session_velocity": session_velocity
        },
        "operational_pulse": pulse_data,
        "session_mix": mix_data
    }
