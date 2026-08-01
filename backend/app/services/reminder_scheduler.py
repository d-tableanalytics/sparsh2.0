import asyncio
from datetime import datetime, timedelta
from app.db.mongodb import get_collection
from app.services.notification_service import send_reminder_email
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

from app.utils.calendar_utils import CALENDAR_COLLECTIONS, find_user_by_id
from app.models.tpms import TPMS_EVENT_KIND, TPMS_NOTIFICATIONS_ENABLED

# How far past its trigger a TPMS reminder may be and still be worth sending. Anything older
# is marked sent and skipped — see the note at the send site in check_and_trigger_reminders.
TPMS_REMINDER_MAX_AGE_HOURS = 48

# ── Spec §16 trigger schedule ─────────────────────────────────────────────────
# The source installed one time-driven trigger per job. There is a single loop here, so the
# clock times are enforced by gating on the hour and remembering the last run.
#
# Gates use `hour >= N`, not `== N`: if the process is restarted or busy at the scheduled
# minute, the job still runs on the next tick that day rather than being skipped entirely.
# Each job is remembered separately, so a failure in one never consumes another's slot.
#
# Times are UTC — the source's triggers were in the sheet's local zone. Set these to the
# UTC equivalents of your 06:00/07:00 if the business cares about local time of day.
TPMS_AUTOFEED_HOUR = 6      # syncAutoFeed            — daily @ 06:00
TPMS_SCORE_SYNC_HOUR = 6    # syncSuccessMeasures     — daily @ 06:00
TPMS_LADDER_HOUR = 7        # runEscalationLadder     — daily @ 07:00
TPMS_SEED_HOUR = 6          # seedSuccessMeasures     — monthly, 1st @ 06:00


async def start_reminder_scheduler():
    logger.info("Starting reminder scheduler background worker...")
    last_recurring_day = None
    tpms_last_run: dict = {}
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

            # TPMS scheduled sweeps, each at its own hour. Isolated so a TPMS failure can
            # never stop the reminder loop the rest of the ERP depends on.
            await run_tpms_scheduled_jobs(tpms_last_run)
        except Exception as e:
            logger.error(f"Error in reminder scheduler: {e}")
        await asyncio.sleep(60)  # tick every minute; each job gates itself on the clock


async def _run_job(state: dict, key, stamp, label: str, fn):
    """Run `fn` once per `stamp` (a date, or a (year, month) tuple for monthly jobs).

    The stamp is recorded only on success, so a failed run is retried on the next tick
    instead of being silently lost until tomorrow.
    """
    if state.get(key) == stamp:
        return
    try:
        result = await fn()
        state[key] = stamp
        logger.info(f"TPMS {label}: {result}")
    except Exception as e:
        logger.error(f"TPMS {label} failed: {e}")


async def run_tpms_scheduled_jobs(state: dict):
    """Spec §16 — the four time-driven TPMS jobs, at their specified times.

    Order matters at 06:00: the auto-feed runs before the score sync so the sync sees the
    statuses the feed has just settled. The ladder deliberately runs an hour later, as in
    the source, so it never lapses an activity the feed has not yet accounted for.
    """
    now = datetime.utcnow()
    today = now.date()

    # ── Monthly, 1st @ 06:00 — seed the new month's success-measure rows (insert-only) ──
    if today.day == 1 and now.hour >= TPMS_SEED_HOUR:
        from app.services.tpms_score_service import seed_success_measures
        period = f"{today.year:04d}-{today.month:02d}"
        await _run_job(state, "seed", (today.year, today.month), "success-measure seed",
                       lambda: seed_success_measures(period))

    # ── Daily @ 06:00 — auto-feed, then the score sync ──
    if now.hour >= TPMS_AUTOFEED_HOUR:
        from app.services.tpms_escalation_service import sync_auto_feed
        await _run_job(state, "autofeed", today, "auto-feed", sync_auto_feed)

    if now.hour >= TPMS_SCORE_SYNC_HOUR:
        from app.services.tpms_score_service import sync_success_measures
        await _run_job(state, "score_sync", today, "success-measure sync",
                       lambda: sync_success_measures())

    # ── Daily @ 07:00 — the escalation ladder ──
    if now.hour >= TPMS_LADDER_HOUR:
        from app.services.tpms_escalation_service import run_escalation_ladder
        await _run_job(state, "ladder", today, "escalation ladder", run_escalation_ladder)


async def check_and_trigger_reminders():
    now = datetime.utcnow()
    collections_to_search = CALENDAR_COLLECTIONS + ["calendar_events"]
    
    for col_name in collections_to_search:
        col = get_collection(col_name)
        # We find events that have reminders that are not sent
        query = {"reminders": {"$elemMatch": {"sent": False}}}
        events = await col.find(query).to_list(1000)
        
        for event in events:
            # TPMS activity reminders are suppressed while TPMS notifications are disabled.
            # This gate is TPMS-only (keyed on the `tpms_activity` discriminator) — reminders
            # for every other event/task fire exactly as before. Leaving them unsent (rather
            # than marking them sent) means re-enabling the flag restores them intact.
            is_tpms_event = event.get("kind") == TPMS_EVENT_KIND
            if is_tpms_event and not TPMS_NOTIFICATIONS_ENABLED:
                continue
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
                    # A TPMS reminder that is long overdue is consumed WITHOUT sending.
                    # While notifications are disabled these accumulate unsent (see the gate
                    # above), so without this window the first tick after enabling the flag
                    # would deliver every historical reminder at once — three per activity,
                    # to every doer and coach. Recent ones still fire normally.
                    # Scoped to TPMS: other modules have been sending all along and have no
                    # backlog, so their behaviour is unchanged.
                    stale = (is_tpms_event
                             and (now - trigger_time) > timedelta(hours=TPMS_REMINDER_MAX_AGE_HOURS))
                    if stale:
                        logger.info(
                            f"TPMS reminder skipped as stale ({trigger_time.isoformat()}) "
                            f"for event {event.get('_id')}"
                        )
                    else:
                        await trigger_reminder_notification(event, reminder)
                    reminder["sent"] = True
                    updated = True
            
            if updated:
                await col.update_one({"_id": event["_id"]}, {"$set": {"reminders": reminders}})


async def _send_tpms_reminder_email(user_data, event):
    """Render a TPMS activity reminder through the module's own template layer.

    Side is decided by which collection the recipient came from: a learner is the company
    side, internal staff are the staff side. Falls back to the ported default body when no
    template row is configured, exactly as every other TPMS mail kind does.
    """
    from app.services.tpms_notify_service import (
        EVENT_REMINDER, SIDE_COMPANY, SIDE_STAFF,
        build_map, fill, get_template, log_context, _default_body,
    )
    from app.services.notification_service import send_email_notification

    side = SIDE_COMPANY if user_data.get("company_id") else SIDE_STAFF
    mapping = await build_map(event)
    mapping["Recipient_Name"] = (user_data.get("full_name")
                                 or " ".join(filter(None, [user_data.get("first_name"),
                                                           user_data.get("last_name")])).strip()
                                 or user_data.get("email") or "")
    tpl = await get_template(event.get("activity") or "", EVENT_REMINDER, side)
    subject_tpl = (tpl or {}).get("subject") or "[Reminder] {{Title}} – {{Activity}}"
    body_tpl = (tpl or {}).get("body_html")
    html = fill(body_tpl, mapping) if body_tpl else _default_body(mapping, "Reminder")
    await send_email_notification(
        user_data.get("email"), fill(subject_tpl, mapping), html,
        user_id=str(user_data.get("_id")), slug=f"tpms_reminder_{side}",
        meta=log_context(event),
    )


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
    
    # H2 — honour the reminder's Channel (email / whatsapp / both). Only applied to TPMS
    # activities; every other event/task keeps the original email-always behaviour.
    is_tpms = event.get("kind") == TPMS_EVENT_KIND
    channel = ((reminder or {}).get("reminder_type") or "both").lower()
    send_email_flag = (not is_tpms) or channel in ("email", "both")

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

            if user_data and send_email_flag:
                # Spec §11 — a TPMS activity reminder uses the per-activity `reminder`
                # template (activity × reminder × side) so a configured body is actually
                # applied. Anything else keeps the generic ERP reminder mail.
                if is_tpms:
                    await _send_tpms_reminder_email(user_data, event)
                else:
                    await send_reminder_email(user_data, event)
                await _log_tpms_reminder(event, reminder, user_data, "sent", None)
        except Exception as e:
            logger.error(f"Error notifying user {uid} for reminder: {e}")
            await _log_tpms_reminder(event, reminder, locals().get("user_data"), "failed", str(e))

    # H1/H2 — WhatsApp reminder for TPMS activities when the channel includes it (gated OFF).
    if is_tpms and channel in ("whatsapp", "both"):
        try:
            from app.services.tpms_notify_service import send_whatsapp
            for side in ("company", "staff"):
                await send_whatsapp(event, "reminder", side)
        except Exception as e:
            logger.error(f"TPMS WhatsApp reminder failed: {e}")


async def _log_tpms_reminder(event, reminder, user_data, status, error):
    """H10 — per-reminder send ledger (TPMS activities only): who, which channel, and any
    error. Best-effort; a logging failure must never affect the reminder itself."""
    if event.get("kind") != TPMS_EVENT_KIND:
        return
    try:
        from app.models.tpms import COLL_REMINDER_LOGS
        await get_collection(COLL_REMINDER_LOGS).insert_one({
            "event_id": str(event.get("_id") or ""),
            "activity": event.get("activity") or "",
            "company_id": event.get("company_id") or "",
            "recipient": (user_data or {}).get("email") or "",
            "recipient_name": (user_data or {}).get("full_name") or (user_data or {}).get("name") or "",
            "channel": (reminder or {}).get("reminder_type") or "email",
            "offset_minutes": (reminder or {}).get("offset_minutes"),
            "timing_type": (reminder or {}).get("timing_type"),
            "status": status,
            "error": error,
            "sent_at": datetime.utcnow(),
        })
    except Exception as le:
        logger.error(f"TPMS reminder-log write failed: {le}")