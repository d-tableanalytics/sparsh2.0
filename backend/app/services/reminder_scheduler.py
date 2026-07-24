import asyncio
from datetime import datetime, timedelta
from app.db.mongodb import get_collection
from app.services.notification_service import send_reminder_email
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

from app.utils.calendar_utils import CALENDAR_COLLECTIONS, find_user_by_id

async def start_reminder_scheduler():
    logger.info("Starting reminder scheduler background worker...")
    last_recurring_day = None
    while True:
        try:
            await check_and_trigger_reminders()

            # Once per day (first tick after midnight, and at startup), roll recurring
            # task series forward — creating each day's/week's/month's next occurrence.
            today = datetime.utcnow().date()
            if today != last_recurring_day:
                try:
                    from app.services.recurring_task_service import generate_due_recurring_tasks
                    await generate_due_recurring_tasks()
                    last_recurring_day = today
                except Exception as e:
                    logger.error(f"Error generating recurring tasks: {e}")

                # TPMS daily sweeps. Each is isolated so a TPMS failure can never stop
                # the reminder loop the rest of the ERP depends on.
                await run_tpms_daily_jobs()
        except Exception as e:
            logger.error(f"Error in reminder scheduler: {e}")
        await asyncio.sleep(60) # Check every minute

async def run_tpms_daily_jobs():
    """TPMS's once-a-day sweeps, ported from the Apps Script's time-driven triggers.

    Order mirrors the source's trigger times: the auto-feed ran at ~06:00 and the
    escalation ladder at ~07:00, so the feed sees the previous day's statuses before
    the ladder can lapse anything.

    Each job is wrapped individually — a TPMS failure must never break the reminder
    loop that Tasks and the Calendar depend on.
    """
    try:
        from app.services.tpms_escalation_service import sync_auto_feed
        result = await sync_auto_feed()
        logger.info(f"TPMS auto-feed: {result}")
    except Exception as e:
        logger.error(f"TPMS auto-feed failed: {e}")

    try:
        from app.services.tpms_escalation_service import run_escalation_ladder
        result = await run_escalation_ladder()
        logger.info(f"TPMS escalation ladder: {result}")
    except Exception as e:
        logger.error(f"TPMS escalation ladder failed: {e}")

    try:
        from app.services.tpms_score_service import run_daily as tpms_scores
        result = await tpms_scores()
        logger.info(f"TPMS success measures: {result}")
    except Exception as e:
        logger.error(f"TPMS success-measure sync failed: {e}")


async def check_and_trigger_reminders():
    now = datetime.utcnow()
    collections_to_search = CALENDAR_COLLECTIONS + ["calendar_events"]
    
    for col_name in collections_to_search:
        col = get_collection(col_name)
        # We find events that have reminders that are not sent
        query = {"reminders": {"$elemMatch": {"sent": False}}}
        events = await col.find(query).to_list(1000)
        
        for event in events:
            reminders = event.get("reminders", [])
            event_time_str = event.get("start")
            if not event_time_str: continue
            
            try:
                # Robust ISO parsing
                clean_time = event_time_str.replace("Z", "+00:00").replace(" ", "T")
                event_time = datetime.fromisoformat(clean_time).replace(tzinfo=None)
            except Exception as e:
                logger.error(f"Date Parse Error for event {event.get('_id')}: {e}")
                continue

            updated = False
            for reminder in reminders:
                if reminder.get("sent"): continue
                
                offset = int(reminder.get("offset_minutes", 0))
                timing = reminder.get("timing_type", "before")
                
                if timing == "before":
                    trigger_time = event_time - timedelta(minutes=offset)
                else:
                    trigger_time = event_time + timedelta(minutes=offset)
                
                # If trigger time reached or passed
                if trigger_time <= now:
                    # Trigger notification to relevant parties
                    await trigger_reminder_notification(event, reminder)
                    reminder["sent"] = True
                    updated = True
            
            if updated:
                await col.update_one({"_id": event["_id"]}, {"$set": {"reminders": reminders}})


async def trigger_reminder_notification(event, reminder):
    user_ids = set()
    user_ids.add(event.get("user_id")) # Always notify the creator
    
    if event.get("type") == "task":
        target = event.get("target_staff_id", [])
        if isinstance(target, list):
            for tid in target: 
                if tid: user_ids.add(tid)
        elif target: user_ids.add(target)
    else:
        for mid in event.get("assigned_member_ids", []) or []:
            if mid: user_ids.add(mid)
        for cid in event.get("coach_ids", []) or []:
            if cid: user_ids.add(cid)
    
    for uid in user_ids:
        if not uid or uid == "null": continue
        try:
            # Fallback search across collections
            user_data = None
            try:
                oid = ObjectId(uid) if isinstance(uid, str) and len(uid) == 24 else uid
                for col_name in ["staff", "learners"]:
                    user_data = await get_collection(col_name).find_one({"_id": oid})
                    if user_data: break
            except: 
                pass # Continue search to other users

            if user_data:
                await send_reminder_email(user_data, event)
        except Exception as e:
            logger.error(f"Error notifying user {uid} for reminder: {e}")