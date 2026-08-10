"""
Recurring task engine — nightly rollover, plus the shared occurrence builder.

Recurring TASKS (repeat = Daily / Weekly / Monthly / Annually / Custom …) are created as a
single first occurrence at creation time (see calendar_events.create_event). The nightly job
below, run once per day at/after midnight by the reminder scheduler, creates the NEXT
occurrence for each active series whose date has arrived — catching up any missed days — so
there is exactly one task per period, never a bulk dump of duplicates.

Personal TODOS do NOT roll forward nightly. A repeating todo is generated in full at creation
time, every occurrence up to its Repeat End Date at once (see build_series_occurrences and
calendar_events.create_event), so the whole series is visible on the calendar the moment it is
saved. The cadence stepping and anti-drift anchors are shared with the nightly engine — both go
through _next_occurrence and _fresh_occurrence.

Where a todo deliberately differs from a task is OFF-DAYS: a todo that falls on a holiday or a
weekly off is skipped outright, never shifted onto another day, whatever its cadence. A task
shifts instead, because the work is still owed to someone. See drops_off_days.

Recurring sessions/events keep their own bulk-generation behaviour in calendar_events.
"""
from datetime import datetime, timezone, timedelta
import logging

from app.db.mongodb import get_collection
from app.utils.calendar_utils import CALENDAR_COLLECTIONS

logger = logging.getLogger(__name__)

TASK_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]

# Document types the NIGHTLY job rolls forward. Tasks only: a repeating todo is generated in
# full at creation time instead (build_series_occurrences), so rolling it nightly here would
# only re-walk a series that already exists.
RECURRING_TYPES = ["task"]

# Ceilings for a single up-front series build. Occurrences is the number of documents written;
# steps is the number of cadence hops taken to find them (higher, because off-days are stepped
# over without producing a document). Both exist purely so an absurd end date — or a malformed
# cadence that never advances — cannot write an unbounded number of rows.
MAX_SERIES_OCCURRENCES = 365
MAX_SERIES_STEPS = 800

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


def _is_holiday(dt, holiday_dates) -> bool:
    """A configured holiday, judged in IST so it matches the date the user actually picked."""
    return dt.astimezone(IST).date().isoformat() in holiday_dates


def _is_weekly_off(dt) -> bool:
    """A weekly off (Sunday), judged in IST."""
    return dt.astimezone(IST).weekday() in WEEKLY_OFF_WEEKDAYS


def _is_off_day(dt, holiday_dates) -> bool:
    """A date the task must never land on: a holiday or a weekly off (Sunday). Judged in IST
    so the day/weekday matches the date the user actually picked."""
    return _is_holiday(dt, holiday_dates) or _is_weekly_off(dt)


def _steps_by_single_day(repeat_type, interval) -> bool:
    """True when consecutive occurrences are exactly one day apart (Daily, or an
    every-1-day periodic). For these, an off-day is simply dropped — the following day is
    its own occurrence, so shifting would collide with it. Every other cadence
    (Weekly/Monthly/Annually/Custom/periodic-N) instead shifts to the next working day so the
    period is never lost."""
    return repeat_type == "Daily" or (repeat_type == "periodic" and (interval or 1) == 1)


def drops_off_days(doc_type, repeat_type, interval) -> bool:
    """Whether an occurrence landing on a WEEKLY OFF is DROPPED rather than shifted forward.

    Holidays no longer come through here at all — they are always dropped, for every cadence
    and every type (see `drops_on_holiday`). This function now governs weekly offs only.

    TODOS always drop. A personal todo is a note-to-self for a specific day; if nobody is
    working that day the todo simply does not exist for that period, rather than being moved
    onto a day the user never chose.

    TASKS depend on the cadence: a daily-style task drops the day (the next day is its own
    occurrence, so shifting would collide with it), while a weekly/monthly/annual/custom task
    shifts to the next working day, because dropping a weekly off would lose a whole period of
    work that is owed to someone else.
    """
    if doc_type == "todo":
        return True
    return _steps_by_single_day(repeat_type, interval)


def drops_on_holiday() -> bool:
    """A configured holiday ALWAYS drops the occurrence — every cadence, every type.

    Nobody is working that day, so no task is created at all: no checklist, no reminders, no
    notification, no placeholder. The series then continues from its own next calendar date;
    the skipped occurrence is NOT moved to the next working day, because moving it would put
    work on a date the schedule never called for and collide with whatever that date already
    owns.

    Previously only daily-style cadences dropped, and a weekly/monthly task landing on a
    holiday was shifted forward instead. A function rather than a constant so every call site
    reads as a policy decision, and so a per-company holiday policy has one obvious seam.
    """
    return True


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


async def load_holiday_dates() -> set:
    """All active holiday dates as a set of ISO 'YYYY-MM-DD' strings.

    Same master source (collection "holidays") the Holiday module and the task
    due-date picker use, so a date marked as a holiday in one place is skipped here too.
    Inactive holidays are ignored.
    """
    col = get_collection("holidays")
    docs = await col.find({"status": {"$ne": "inactive"}}, {"holiday_date": 1}).to_list(5000)
    return {d.get("holiday_date") for d in docs if d.get("holiday_date")}


def _series_anchor_day(head: dict):
    """The series' intended day-of-month, carried forward on every occurrence. Without it a
    month too short to hold the date would pull the series down permanently (Jan 31 → Feb 28 →
    Mar 28 → …). `recurrence_day` is stamped on each generated occurrence; the FIRST occurrence
    predates it, so fall back to its own start day — the day the user actually picked, which
    was never clamped."""
    day = head.get("recurrence_day")
    if day:
        return day
    first = _parse(head.get("start"))
    return first.day if first else None


# Per-occurrence state, reset to an empty list on every new occurrence. Each of these records
# what happened during ONE period, so carrying it forward would make a fresh task claim work
# that belongs to the previous one.
#
# `completion_attachments` is the sharpest of these: the completion gate in routes/tasks.py
# accepts a task as evidenced when that array is non-empty, so an inherited copy let a new
# occurrence be completed with last period's proof and no new upload at all.
#
# `attachments` is deliberately ABSENT from this list. It holds the assigner's brief and
# reference files — the material the doer needs in order to start — and it describes the task,
# not the period. It was previously wiped on every occurrence, which is the exact inverse of
# what these two arrays mean.
_RESET_LISTS = (
    "remarks",
    "status_history",
    "completion_attachments",   # completion evidence — see above
    "follow_ups",
    "deadline_history",
    "dependency_stack",
)


def _fresh_occurrence(head: dict, target, natural, anchor_day) -> dict:
    """A new occurrence cloned from `head`, due on `target`.

    `natural` is the UNSHIFTED date this occurrence was computed for; it is stored as
    `recurrence_anchor` so the next period is always measured from the cadence's own date even
    when this one was pushed off a holiday / weekly off. Without it a single shift would drag
    the rest of the series forward permanently.

    THE definition of a fresh occurrence, used by both paths that create one — the nightly
    engine and the series-extension in routes/calendar_events.py. Keeping it in one place is
    what stops the two disagreeing about what "fresh" means.

    What a new occurrence keeps: the task itself (title, description, assignees, cadence,
    checklist ITEMS, reminders), the assigner's reference `attachments`, and the DEADLINE
    (`end`) exactly as the user assigned it.
    What it does not keep: anything recording what happened last period — ticks, completion
    timestamps, evidence, remarks, follow-ups, history, and any delegation the previous
    occurrence went through.
    """
    doc = {k: v for k, v in head.items() if k not in ("_id", "id")}
    doc["start"] = target.isoformat()
    doc["recurrence_anchor"] = natural.isoformat()
    if anchor_day:
        doc["recurrence_day"] = anchor_day

    # `end` — the deadline — is carried over UNTOUCHED by the clone above, deliberately. The
    # deadline belongs to the task as the assigner set it, not to the period, so it is never
    # recomputed here for any cadence: every occurrence of a series is due at exactly the
    # moment the user chose. (This used to move a Daily occurrence's deadline onto its own
    # date, and slide every other cadence forward by the original start-to-deadline gap.)
    # The only thing that changes a deadline is an explicit revision by the assigner —
    # routes/tasks.py revise_task_deadline, which stamps `deadline_history`.

    doc["created_at"] = datetime.utcnow()
    doc["updated_at"] = None
    if head.get("type") == "task":
        # Delegation workflow state — a todo has no workflow, only status.
        doc["workflow_status"] = "in_progress"  # new occurrences start In Progress
    doc["status"] = "schedule"
    doc["completed_at"] = None
    doc["completed_by"] = None
    doc["deleted_at"] = None

    if head.get("checklist"):
        # `completed_at` must be cleared alongside `completed`. Overriding only `completed`
        # left last period's timestamp on an unticked item, so anything reading it saw a
        # "done at" date on work that had not been done.
        doc["checklist"] = [{**c, "completed": False, "completed_at": None}
                            for c in head["checklist"]]

    for field in _RESET_LISTS:
        doc[field] = []
    doc["dependency_doer_id"] = None

    # Raising a dependency ADDS the doer to `target_staff_id` and flips `assigned_to` to
    # "other" (routes/tasks.py). Clearing only the stack would leave the new occurrence
    # assigned to whoever last helped out. The bottom of the stack records the assignment as
    # it was before any hand-off, so the original owners are restored from the data itself
    # rather than guessed at.
    stack = head.get("dependency_stack") or []
    if stack:
        base = stack[0] or {}
        doc["target_staff_id"] = base.get("assignee_ids") or []
        doc["assigned_to"] = base.get("assigned_to") or doc.get("assigned_to")

    if head.get("reminders"):
        doc["reminders"] = [{**r, "sent": False} for r in head["reminders"]]
    return doc


async def build_series_occurrences(head: dict, end_dt, holiday_dates=None, taken_dates=None):
    """Every occurrence AFTER `head`, up to and including `end_dt` — the whole series at once.

    This is the up-front counterpart to the nightly rollover: same cadence steps, same
    anti-drift anchors, same per-occurrence reset, and the same off-day policy (drops_off_days —
    a todo skips holidays and weekly offs entirely). Used to generate a repeating personal todo
    in full the moment it is saved, and to extend a series when its Repeat End Date is pushed
    out.

    `head` is the first occurrence (it is NOT included in the result). `taken_dates` is a set of
    ISO 'YYYY-MM-DD' strings already occupied by this series, so an extension can never
    duplicate a date that exists.

    Returns (occurrences, truncated) — `truncated` is True when MAX_SERIES_OCCURRENCES capped
    the build, so the caller can tell the user the series was cut short rather than silently
    delivering fewer dates than they asked for.
    """
    # Lazy import avoids any import-order coupling with the calendar_events route module.
    from app.routes.calendar_events import _next_occurrence

    repeat_type = head.get("repeat")
    curr = _parse(head.get("recurrence_anchor") or head.get("start"))
    if not curr or not end_dt or not repeat_type or repeat_type in (None, "", "Does not repeat"):
        return [], False

    if holiday_dates is None:
        holiday_dates = await load_holiday_dates()

    interval = head.get("repeat_interval", 1) or 1
    anchor_day = _series_anchor_day(head)

    # The head's own date is occupied — a shifted occurrence must never collide with it.
    seen = set(taken_dates or ())
    head_start = _parse(head.get("start"))
    if head_start:
        seen.add(_ist_date(head_start).isoformat())

    occurrences, truncated = [], False
    for _ in range(MAX_SERIES_STEPS):
        try:
            nxt = _next_occurrence(curr, repeat_type, interval, head.get("repeat_data"), anchor_day)
        except Exception as e:
            logger.error(f"Recurrence step failed while building series ({repeat_type}): {e}")
            break
        if nxt is None:
            break
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        if _ist_date(nxt) > _ist_date(end_dt):
            break

        # Off-day handling, identical to the nightly engine's — a holiday always drops the
        # occurrence for every cadence and type, while a weekly off follows drops_off_days.
        # The two paths MUST agree: the same series is built here when it is created or
        # extended, and rolled forward there overnight.
        target = nxt
        if _is_holiday(nxt, holiday_dates):
            curr = nxt
            continue
        if _is_weekly_off(nxt):
            if drops_off_days(head.get("type"), repeat_type, interval):
                curr = nxt
                continue
            shifted = _shift_to_working_day(nxt, holiday_dates)
            if shifted is None or _ist_date(shifted) > _ist_date(end_dt):
                curr = nxt
                continue
            target = shifted

        day = _ist_date(target).isoformat()
        if day not in seen:
            seen.add(day)
            occurrences.append(_fresh_occurrence(head, target, nxt, anchor_day))
            if len(occurrences) >= MAX_SERIES_OCCURRENCES:
                truncated = True
                break
        curr = nxt

    return occurrences, truncated


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
    holiday_dates = await load_holiday_dates()

    for col_name in TASK_COLLECTIONS:
        col = get_collection(col_name)
        docs = await col.find({
            "type": {"$in": RECURRING_TYPES},
            "recurring_group_id": {"$ne": None},
            "repeat": {"$nin": [None, "", "Does not repeat"]},
            "deleted_at": None,
        }).to_list(10000)

        # Keep only the latest occurrence per series (by start), and record every IST date the
        # series already covers. Both come from the documents already fetched above, so the
        # de-duplication below costs no extra query — it replaces one round trip per candidate
        # date with none at all.
        latest = {}
        dates_by_series = {}
        for d in docs:
            gid = d.get("recurring_group_id")
            if not gid:
                continue
            if gid not in latest or (d.get("start") or "") > (latest[gid].get("start") or ""):
                latest[gid] = d
            when = _parse(d.get("start"))
            if when:
                dates_by_series.setdefault(gid, set()).add(_ist_date(when))

        for gid, head in latest.items():
            existing_dates = dates_by_series.setdefault(gid, set())
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
            anchor_day = _series_anchor_day(head)

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
                # A HOLIDAY always drops the occurrence, whatever the cadence: nothing is
                # created for that date — no task, no checklist, no reminders — and the series
                # resumes at its own next calendar date. e.g. a daily 10–15 Aug task with a
                # 12 Aug holiday produces 10, 11, 13, 14, 15 Aug.
                #
                # A WEEKLY OFF keeps the older, cadence-dependent rule (drops_off_days):
                #   • Daily-style (1-day step): dropped — the next day is its own occurrence,
                #     so shifting would collide with it.
                #   • Weekly / Monthly / Annually / Custom: shifted to the next working day so
                #     a whole week or month of work is not lost.
                target = nxt
                if _is_holiday(nxt, holiday_dates):
                    skipped_holidays += 1
                    curr = nxt
                    continue
                if _is_weekly_off(nxt):
                    if drops_off_days(head.get("type"), repeat_type, interval):
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
                # Skip if an occurrence already exists for that IST date in this series.
                #
                # Compared as IST dates on BOTH sides. The previous check matched a
                # `^YYYY-MM-DD` prefix built from `target.date()` — the date in the datetime's
                # own zone — while every due/boundary decision above uses `_ist_date`. For a
                # series whose start time falls before 05:30 IST the two disagree by a day, so
                # the engine could re-create an occurrence it had already made. Deciding and
                # de-duplicating on the same calendar date removes that whole class of bug.
                if _ist_date(target) not in existing_dates:
                    # Same builder the up-front series generator uses, so a rolled-forward
                    # occurrence and a bulk-generated one are byte-for-byte the same shape.
                    await col.insert_one(_fresh_occurrence(head, target, nxt, anchor_day))
                    existing_dates.add(_ist_date(target))
                    created += 1
                curr = nxt

    if created or skipped_holidays or skipped_weekly_offs or shifted_occurrences:
        logger.info(
            f"Recurring engine: created {created} task/todo occurrence(s); "
            f"skipped {skipped_holidays} holiday and {skipped_weekly_offs} weekly-off date(s); "
            f"shifted {shifted_occurrences} occurrence(s) to the next working day."
        )
    return created
