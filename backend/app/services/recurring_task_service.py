"""
Recurring task engine — nightly rollover.

Recurring TASKS (repeat = Daily / Weekly / Monthly / Annually / Custom …) are created as a
single first occurrence at creation time (see calendar_events.create_event). This job, run
once per day at/after midnight by the reminder scheduler, creates the NEXT occurrence for
each active series whose date has arrived — catching up any missed days — so there is exactly
one task per period, never a bulk dump of duplicates.

Only type == "task" documents are handled; recurring events keep their own behaviour.
"""
from datetime import datetime, timezone, timedelta
import logging

from app.db.mongodb import get_collection
from app.utils.calendar_utils import CALENDAR_COLLECTIONS

logger = logging.getLogger(__name__)

TASK_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]

# Weekly off day(s) — recurring occurrences never land here, matching the task due-date
# picker which blocks the same day. Python date.weekday(): Mon=0 … Sun=6, so {6} == Sunday.
# (There is no persisted per-user weekly-off setting in the backend yet — see the picker's
# WEEKLY_OFFS on the frontend.)
WEEKLY_OFF_WEEKDAYS = {6}


def _is_off_day(dt, holiday_dates) -> bool:
    """A date the task must never land on: a holiday or a weekly off (Sunday)."""
    return dt.date().isoformat() in holiday_dates or dt.weekday() in WEEKLY_OFF_WEEKDAYS


def _steps_by_single_day(repeat_type, interval) -> bool:
    """True when consecutive occurrences are exactly one day apart (Daily, or an
    every-1-day periodic). For these, an off-day is simply dropped — the following day is
    its own occurrence, so shifting would collide with it. Every other cadence
    (Weekly/Monthly/Annually/Custom/periodic-N) instead shifts to the next working day so the
    period is never lost."""
    return repeat_type == "Daily" or (repeat_type == "periodic" and (interval or 1) == 1)


def _shift_to_working_day(dt, holiday_dates, max_shift=14):
    """Move forward from an off-day to the next holiday-free, non-weekly-off day."""
    shifted = dt
    for _ in range(max_shift):
        if not _is_off_day(shifted, holiday_dates):
            return shifted
        shifted = shifted + timedelta(days=1)
    return None  # unusually long off-day streak — give up rather than loop forever


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
    skipped_weekly_offs = 0
    shifted_occurrences = 0

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
            # Advance from the NATURAL (unshifted) date of the latest occurrence, never its
            # stored `start`. When an occurrence is shifted off a holiday/weekly-off (e.g. the
            # 15th → the 16th), its `start` is the shifted date; computing the next period from
            # that would drift the whole series forward permanently. `recurrence_anchor` holds
            # the natural date for exactly this reason. Fall back to `start` for the first
            # occurrence (created by calendar_events.create_event) and legacy docs, which have
            # no anchor and were never shifted.
            curr = _parse(head.get("recurrence_anchor") or head.get("start"))
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
                # An off-day (holiday or weekly off) must never hold a task. How we handle it
                # depends on the cadence:
                #   • Daily-style (1-day step): drop that day — the next day is its own
                #     occurrence, so shifting would collide with it. e.g. a daily 1–10 Aug task
                #     with 3 & 7 Aug holidays generates every day except 3 & 7 Aug.
                #   • Weekly / Monthly / Annually / Custom: shift the occurrence forward to the
                #     next working day so the whole week/month is not lost. e.g. a monthly-15th
                #     task whose 15th is a Sunday generates on Mon the 16th instead.
                target = nxt
                if _is_off_day(nxt, holiday_dates):
                    if _steps_by_single_day(repeat_type, interval):
                        if nxt.date().isoformat() in holiday_dates:
                            skipped_holidays += 1
                        else:
                            skipped_weekly_offs += 1
                        curr = nxt
                        continue
                    shifted = _shift_to_working_day(nxt, holiday_dates)
                    if shifted is None or (end_dt and shifted.date() > end_dt.date()):
                        curr = nxt
                        continue
                    if shifted.date() > today:
                        break  # shifted target hasn't arrived yet — created on its own day
                    shifted_occurrences += 1
                    target = shifted
                # Skip if an occurrence already exists for that date in this series.
                day_prefix = target.date().isoformat()
                exists = await col.find_one({"recurring_group_id": gid, "start": {"$regex": f"^{day_prefix}"}})
                if not exists:
                    new_task = {k: v for k, v in head.items() if k != "_id"}
                    new_task["start"] = target.isoformat()
                    # Anchor for the NEXT period is always the natural date, even when this
                    # occurrence was shifted onto a working day — see the comment where `curr`
                    # is initialised. Keeps a one-off shift from drifting the series.
                    new_task["recurrence_anchor"] = nxt.isoformat()
                    oe, os = _parse(head.get("end")), _parse(head.get("start"))
                    if oe and os:
                        new_task["end"] = (target + (oe - os)).isoformat()
                    new_task["created_at"] = datetime.utcnow()
                    new_task["updated_at"] = None
                    new_task["workflow_status"] = "pending"
                    new_task["status"] = "schedule"
                    new_task["completed_at"] = None
                    new_task["completed_by"] = None
                    new_task["deleted_at"] = None
                    # A fresh occurrence must not inherit the previous period's activity: start
                    # with an unticked checklist and empty remark/attachment/status history.
                    if head.get("checklist"):
                        new_task["checklist"] = [{**c, "completed": False} for c in head["checklist"]]
                    new_task["remarks"] = []
                    new_task["attachments"] = []
                    new_task["status_history"] = []
                    # Fresh reminders for the new occurrence's date.
                    if head.get("reminders"):
                        new_task["reminders"] = [{**r, "sent": False} for r in head["reminders"]]
                    await col.insert_one(new_task)
                    created += 1
                curr = nxt

    if created or skipped_holidays or skipped_weekly_offs or shifted_occurrences:
        logger.info(
            f"Recurring engine: created {created} task occurrence(s); "
            f"skipped {skipped_holidays} holiday and {skipped_weekly_offs} weekly-off date(s); "
            f"shifted {shifted_occurrences} occurrence(s) to the next working day."
        )
    return created
