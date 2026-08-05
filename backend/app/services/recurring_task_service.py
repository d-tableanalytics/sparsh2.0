"""
Recurring task engine — nightly rollover.

Recurring TASKS (repeat = Daily / Weekly / Monthly / Annually / Custom …) are created as a
single first occurrence at creation time (see calendar_events.create_event). This job, run
once per day at/after midnight by the reminder scheduler, creates the NEXT occurrence for
each active series whose date has arrived — catching up any missed days — so there is exactly
one task per period, never a bulk dump of duplicates.

Personal TODOS repeat through this same engine, by the same rules (Calendar ▸ Personal Todo ▸
Frequency uses the delegation Repeat control), so the two never drift apart. Recurring
sessions/events keep their own bulk-generation behaviour.
"""
from datetime import datetime, timezone, timedelta
import logging

from app.db.mongodb import get_collection
from app.utils.calendar_utils import CALENDAR_COLLECTIONS

logger = logging.getLogger(__name__)

TASK_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]

# Document types this engine rolls forward. Todos ride along with tasks so a repeating todo
# gets exactly the delegation feature's behaviour — same cadences, same holiday / weekly-off
# handling, same one-occurrence-per-period rule.
RECURRING_TYPES = ["task", "todo"]

# The product runs on Indian Standard Time (UTC+5:30). Every "which day is it / has this
# occurrence's day arrived" decision below is made in IST, so the next occurrence is created
# at 12:00 AM IST (local midnight), not at 00:00 UTC (which is 5:30 AM IST). The scheduler that
# calls this job flips its day counter on the same IST boundary (see reminder_scheduler).
IST = timezone(timedelta(hours=5, minutes=30))


def _ist_date(dt):
    """The calendar date of a tz-aware datetime as seen in IST."""
    return dt.astimezone(IST).date()

# Weekly off day(s) — recurring occurrences never land here, matching the task due-date
# picker which blocks the same day. Python date.weekday(): Mon=0 … Sun=6, so {6} == Sunday.
# (There is no persisted per-user weekly-off setting in the backend yet — see the picker's
# WEEKLY_OFFS on the frontend.)
WEEKLY_OFF_WEEKDAYS = {6}


def _is_off_day(dt, holiday_dates) -> bool:
    """A date the task must never land on: a holiday or a weekly off (Sunday). Judged in IST
    so the day/weekday matches the date the user actually picked."""
    ist = dt.astimezone(IST)
    return ist.date().isoformat() in holiday_dates or ist.weekday() in WEEKLY_OFF_WEEKDAYS


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
    today = _ist_date(now)  # "today" in IST — the boundary the next occurrence is created on
    created = 0
    skipped_holidays = 0
    skipped_weekly_offs = 0
    shifted_occurrences = 0

    # Repeat tasks must not trigger on holidays — load the holiday set once for this run.
    holiday_dates = await _load_holiday_dates()

    for col_name in TASK_COLLECTIONS:
        col = get_collection(col_name)
        docs = await col.find({
            "type": {"$in": RECURRING_TYPES},
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
            # The series' intended day-of-month, carried forward on every occurrence. Without
            # it a month too short to hold the date would pull the series down permanently
            # (Jan 31 → Feb 28 → Mar 28 → …). `recurrence_day` is stamped on each generated
            # occurrence below; the first occurrence predates it, so fall back to its own start
            # day — which is the day the user actually picked and was never clamped.
            anchor_day = head.get("recurrence_day")
            if not anchor_day:
                first = _parse(head.get("start"))
                anchor_day = first.day if first else None

            guard = 0
            while guard < 400:
                guard += 1
                try:
                    nxt = _next_occurrence(curr, repeat_type, interval,
                                           head.get("repeat_data"), anchor_day)
                except Exception as e:
                    # One malformed series must not abort the nightly run for every other
                    # series — the outer handler would have swallowed the whole job.
                    logger.error(f"Recurrence step failed for series {gid} ({repeat_type}): {e}")
                    break
                if nxt is None:
                    break
                if nxt.tzinfo is None:
                    nxt = nxt.replace(tzinfo=timezone.utc)
                if end_dt and _ist_date(nxt) > _ist_date(end_dt):
                    break
                if _ist_date(nxt) > today:
                    break  # future occurrence — created at 12 AM IST on its own day
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
                        if _ist_date(nxt).isoformat() in holiday_dates:
                            skipped_holidays += 1
                        else:
                            skipped_weekly_offs += 1
                        curr = nxt
                        continue
                    shifted = _shift_to_working_day(nxt, holiday_dates)
                    if shifted is None or (end_dt and _ist_date(shifted) > _ist_date(end_dt)):
                        curr = nxt
                        continue
                    if _ist_date(shifted) > today:
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
                    # Propagate the intended day-of-month so the series can always climb back
                    # to it after a short month.
                    if anchor_day:
                        new_task["recurrence_day"] = anchor_day
                    oe, os = _parse(head.get("end")), _parse(head.get("start"))
                    if oe and os:
                        new_task["end"] = (target + (oe - os)).isoformat()
                    new_task["created_at"] = datetime.utcnow()
                    new_task["updated_at"] = None
                    if head.get("type") == "task":
                        # Delegation workflow state — a todo has no workflow, only status.
                        new_task["workflow_status"] = "in_progress"  # new occurrences start In Progress
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
            f"Recurring engine: created {created} task/todo occurrence(s); "
            f"skipped {skipped_holidays} holiday and {skipped_weekly_offs} weekly-off date(s); "
            f"shifted {shifted_occurrences} occurrence(s) to the next working day."
        )
    return created
