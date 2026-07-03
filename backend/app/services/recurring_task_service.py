"""
Recurring task engine — nightly rollover.

Recurring TASKS (repeat = Daily / Weekly / Monthly / Annually / Custom …) are created as a
single first occurrence at creation time (see calendar_events.create_event). This job, run
once per day at/after midnight by the reminder scheduler, creates the NEXT occurrence for
each active series whose date has arrived — catching up any missed days — so there is exactly
one task per period, never a bulk dump of duplicates.

Only type == "task" documents are handled; recurring events keep their own behaviour.
"""
from datetime import datetime, timezone
import logging

from app.db.mongodb import get_collection
from app.utils.calendar_utils import CALENDAR_COLLECTIONS

logger = logging.getLogger(__name__)

TASK_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]


def _parse(v):
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def _load_holiday_dates() -> set:
    """All active holiday dates as a set of ISO 'YYYY-MM-DD' strings.

    Same master source (collection "holidays") the Holiday module and the task
    due-date picker use, so a date marked as a holiday in one place is skipped here too.
    Inactive holidays are ignored.
    """
    col = get_collection("holidays")
    docs = await col.find({"status": {"$ne": "inactive"}}, {"holiday_date": 1}).to_list(5000)
    return {d.get("holiday_date") for d in docs if d.get("holiday_date")}


async def generate_due_recurring_tasks():
    # Lazy import avoids any import-order coupling with the calendar_events route module.
    from app.routes.calendar_events import _next_occurrence

    now = datetime.now(timezone.utc)
    today = now.date()
    created = 0
    skipped_holidays = 0

    # Repeat tasks must not trigger on holidays — load the holiday set once for this run.
    holiday_dates = await _load_holiday_dates()

    for col_name in TASK_COLLECTIONS:
        col = get_collection(col_name)
        docs = await col.find({
            "type": "task",
            "recurring_group_id": {"$ne": None},
            "repeat": {"$nin": [None, "", "Does not repeat"]},
            "deleted_at": None,
        }).to_list(10000)

        # Keep only the latest occurrence per series (by start).
        latest = {}
        for d in docs:
            gid = d.get("recurring_group_id")
            if not gid:
                continue
            if gid not in latest or (d.get("start") or "") > (latest[gid].get("start") or ""):
                latest[gid] = d

        for gid, head in latest.items():
            repeat_type = head.get("repeat")
            interval = head.get("repeat_interval", 1) or 1
            end_dt = _parse(head.get("repeat_end_date"))
            curr = _parse(head.get("start"))
            if not curr:
                continue

            guard = 0
            while guard < 400:
                guard += 1
                nxt = _next_occurrence(curr, repeat_type, interval, head.get("repeat_data"))
                if nxt is None:
                    break
                if nxt.tzinfo is None:
                    nxt = nxt.replace(tzinfo=timezone.utc)
                if end_dt and nxt.date() > end_dt.date():
                    break
                if nxt.date() > today:
                    break  # future occurrence — created on its own day
                # Holiday skip: never generate an occurrence that falls on a holiday, but
                # keep advancing so the series resumes on the next valid (non-holiday) date.
                # e.g. a daily 1–10 Aug task with 3 & 7 Aug holidays generates every day
                # except 3 & 7 Aug.
                if nxt.date().isoformat() in holiday_dates:
                    curr = nxt
                    skipped_holidays += 1
                    continue
                # Skip if an occurrence already exists for that date in this series.
                day_prefix = nxt.date().isoformat()
                exists = await col.find_one({"recurring_group_id": gid, "start": {"$regex": f"^{day_prefix}"}})
                if not exists:
                    new_task = {k: v for k, v in head.items() if k != "_id"}
                    new_task["start"] = nxt.isoformat()
                    oe, os = _parse(head.get("end")), _parse(head.get("start"))
                    if oe and os:
                        new_task["end"] = (nxt + (oe - os)).isoformat()
                    new_task["created_at"] = datetime.utcnow()
                    new_task["updated_at"] = None
                    new_task["workflow_status"] = "pending"
                    new_task["status"] = "schedule"
                    new_task["completed_at"] = None
                    new_task["deleted_at"] = None
                    # Fresh reminders for the new occurrence's date.
                    if head.get("reminders"):
                        new_task["reminders"] = [{**r, "sent": False} for r in head["reminders"]]
                    await col.insert_one(new_task)
                    created += 1
                curr = nxt

    if created or skipped_holidays:
        logger.info(
            f"Recurring engine: created {created} task occurrence(s); "
            f"skipped {skipped_holidays} holiday date(s)."
        )
    return created
