"""
TPMS ▸ core domain models + collection registry.

Ported 1:1 from the Apps Script implementation (`copy_of calender/code.js`, 4207 lines).
Where a constant here looks arbitrary, it mirrors the sheet/script exactly — the source
line is cited so behaviour can be diffed against the original.

The *forms* sub-module (rating matrices + Yes/No checklist) lives in `app.models.forms`
and is unchanged by this file. This module covers everything else: the activity
catalogue, scheduling lifecycle, reminders, escalations, action items, uploads and the
Success-Measure engine's storage.

Scheduled TPMS activities are NOT stored here — they are calendar events carrying
`kind == TPMS_EVENT_KIND` (see app/models/calendar_event.py), so they reuse the ERP's
recurrence engine, reminder scheduler and calendar UI.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# Collections
# ─────────────────────────────────────────────────────────────
COLL_ACTIVITIES          = "tpms_activities"
COLL_REMINDER_RULES      = "tpms_reminder_rules"
COLL_RESCHEDULE_REQUESTS = "tpms_reschedule_requests"
COLL_TASK_UPLOADS        = "tpms_task_uploads"
COLL_ACTIVITY_TRACKER    = "tpms_activity_tracker"
COLL_ESCALATIONS         = "tpms_escalations"
COLL_ACTION_ITEMS        = "tpms_action_items"
COLL_SUCCESS_MEASURES    = "tpms_success_measures"
COLL_MAIL_TEMPLATES      = "tpms_mail_templates"
COLL_MIGRATION_MAP       = "tpms_migration_map"   # sheet id → Mongo _id, for re-runnable migration

# Discriminator marking a calendar event as a TPMS activity.
TPMS_EVENT_KIND = "tpms_activity"


# ─────────────────────────────────────────────────────────────
# Enumerations (string constants — values match the sheet verbatim)
# ─────────────────────────────────────────────────────────────
STATUS_SCHEDULED   = "Scheduled"
STATUS_RESCHEDULED = "Rescheduled"
STATUS_CANCELLED   = "Cancelled"
STATUS_COMPLETED   = "Completed"
STATUS_LAPSED      = "Lapsed"
SCHEDULE_STATUSES = [STATUS_SCHEDULED, STATUS_RESCHEDULED, STATUS_CANCELLED,
                     STATUS_COMPLETED, STATUS_LAPSED]

# Statuses the escalation ladder and the auto-feed treat as "closed".
CLOSED_STATUSES = {STATUS_COMPLETED, STATUS_CANCELLED}

# The ERP calendar's own `status` vocabulary is lowercase and has no "Lapsed". TPMS keeps
# its five statuses in `tpms_status` and mirrors the closest ERP value into `status`, so the
# existing Calendar page keeps rendering TPMS events correctly and nothing downstream breaks.
TPMS_TO_ERP_STATUS = {
    STATUS_SCHEDULED:   "schedule",
    STATUS_RESCHEDULED: "reschedule",
    STATUS_CANCELLED:   "canceled",
    STATUS_COMPLETED:   "completed",
    STATUS_LAPSED:      "schedule",   # no ERP equivalent — stays visible as scheduled
}


def erp_status_for(tpms_status: str) -> str:
    return TPMS_TO_ERP_STATUS.get(tpms_status, "schedule")


SCOPE_COMPANY = "company"
SCOPE_HOD     = "hod"

SCORE_MODE_MANUAL = "manual"   # OM types the number in (Success_Manual)
SCORE_MODE_FORM   = "form"     # derived from TPMS form submissions
SCORE_MODE_AUTO   = "auto"     # completed ÷ total

CHANNEL_EMAIL    = "Email"
CHANNEL_WHATSAPP = "WhatsApp"
CHANNEL_BOTH     = "Both"

RECURRENCE_ONE_TIME     = "One-time"
RECURRENCE_MONTHLY      = "Monthly"
RECURRENCE_WEEKLY       = "Weekly"
RECURRENCE_PERIODICALLY = "Periodically"
# NB: the Apps Script calendar filter offers "Daily" but buildOccurrences_ never
# implements it (code.js:1304). Reproduced as-is — Daily generates nothing.
RECURRENCES = [RECURRENCE_ONE_TIME, RECURRENCE_MONTHLY, RECURRENCE_WEEKLY, RECURRENCE_PERIODICALLY]

REQUEST_PENDING  = "Pending"
REQUEST_APPROVED = "Approved"
REQUEST_REJECTED = "Rejected"

# Client-side departments the doers are grouped by. Matches the `Department` sheet and
# the hardcoded list in frontend ScheduleCalendarModal.jsx.
TPMS_DEPARTMENTS = ["HOD", "MD", "HR", "IMPLEMENTOR"]


# ─────────────────────────────────────────────────────────────
# Tunables — every value mirrors the Apps Script
# ─────────────────────────────────────────────────────────────
# Engine B — syncAutoFeed (code.js:2711-2712), daily ~06:00
AUTO_ACTION_MIN_DAYS      = 1    # overdue ≥1d → open an Action_Item
AUTO_ESCALATION_MIN_DAYS  = 5    # overdue ≥5d → open an Escalation

# Engine B — escLevel_ (code.js:2855)
ESCALATION_LEVELS = [(10, 3, "MD"), (7, 2, "HR"), (5, 1, "HOD")]  # (min_days, level, escalate_to)

# Engine A — runEscalationLadder (code.js:3755), daily ~07:00
LADDER_PENDING_DAYS  = 1   # → [Pending Action] mail, Esc_Stage 1
LADDER_CRITICAL_DAYS = 2   # → [CRITICAL] mail, Esc_Stage 2
LADDER_LAPSE_DAYS    = 3   # → Status = Lapsed, Esc_Stage 3

RESCHEDULE_MIN_HOURS = 12          # requestReschedule (code.js:3834)
UPLOAD_MAX_BYTES     = 25 * 1024 * 1024
DEFAULT_REMIND_TIME  = "09:00"     # CFG.DEFAULT_REMIND_TIME
REVIEW_MAX_RATING    = 5           # REVIEW_MAX_RATING (code.js:2016)

# Calendar Discipline is a pseudo-activity: its score is the completion rate across all
# OTHER activities that month, excluding itself and Action Closure Review (code.js:1924).
CAL_DISCIPLINE_ACTIVITY = "Calendar Discipline"
CAL_DISCIPLINE_EXCLUDE  = "Action Closure Review"

# Offset units → seconds (writeReminders_ UNIT map, code.js:1209)
OFFSET_UNIT_SECONDS = {"MINS": 60, "HRS": 3600, "DAYS": 86400}


def escalation_level(days_overdue: int) -> Dict:
    """Port of escLevel_ (code.js:2855). Returns {level, to}; level 0 = not escalated."""
    for min_days, level, to in ESCALATION_LEVELS:
        if days_overdue >= min_days:
            return {"level": level, "to": to}
    return {"level": 0, "to": ""}


# ─────────────────────────────────────────────────────────────
# Period helpers — canonical "YYYY-MM"
#
# The sheet stores months three different ways ("jul26", "July26", a real Date) and the
# Apps Script normalises them with succMonthNorm_ (code.js:1903). We store the canonical
# ISO form and generate the legacy tokens when reading migrated data.
# ─────────────────────────────────────────────────────────────
_MON_SHORT = ["jan", "feb", "mar", "apr", "may", "jun",
              "jul", "aug", "sep", "oct", "nov", "dec"]
_MON_FULL = ["january", "february", "march", "april", "may", "june",
             "july", "august", "september", "october", "november", "december"]


def period_parts(period: str):
    """'YYYY-MM' → (year, month). Raises ValueError on anything else."""
    year, month = int(str(period)[:4]), int(str(period)[5:7])
    if not 1 <= month <= 12:
        raise ValueError(f"invalid month in period {period!r}")
    return year, month


def period_tokens(period: str) -> List[str]:
    """Every spelling of a period that may appear in migrated rows, for `$in` queries.
    '2026-07' → ['2026-07', 'jul26', 'july26', 'jul-26']"""
    year, month = period_parts(period)
    yy = str(year)[-2:]
    short, full = _MON_SHORT[month - 1], _MON_FULL[month - 1]
    return list({period, f"{short}{yy}", f"{full}{yy}", f"{short}-{yy}"})


def period_from_date(value) -> str:
    """A date (or ISO string) → canonical 'YYYY-MM'. Port of midFromDate_ (code.js:1133),
    except it yields the ISO form rather than 'jul26'."""
    if isinstance(value, datetime):
        return f"{value.year:04d}-{value.month:02d}"
    s = str(value or "").strip()
    if not s:
        return ""
    return s[:7] if len(s) >= 7 and s[4] == "-" else ""


def period_display(period: str) -> str:
    """'2026-07' → 'July26' (the sheet's display form, succMonthDisplay_ code.js:1914)."""
    year, month = period_parts(period)
    return _MON_FULL[month - 1].capitalize() + str(year)[-2:]


# ─────────────────────────────────────────────────────────────
# Activity catalogue — the 14 rows of the `Activity` sheet.
# Seed data; `tpms_activities` is the runtime source of truth once migrated.
# ─────────────────────────────────────────────────────────────
class Activity(BaseModel):
    name: str
    short: str
    frequency: str                       # verbatim sheet text — drives the conflict rule
    scope: str = SCOPE_COMPANY           # company | hod  (sheet: "Responsive")
    upload_required: bool = False
    score_mode: str = SCORE_MODE_AUTO    # manual | form | auto
    doc_link: Optional[str] = None
    active: bool = True


ACTIVITY_SEED: List[dict] = [
    {"name": "Org Structure Update",               "short": "Org Str",        "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "DRM & KPI data available",           "short": "DRM/KPI",        "frequency": "once in a month", "scope": SCOPE_HOD,     "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "Calendar Discipline",                "short": "Cal Disc",       "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": False, "score_mode": SCORE_MODE_AUTO},
    {"name": "WRM",                                "short": "WRM",            "frequency": "3-4 in month",    "scope": SCOPE_HOD,     "upload_required": False, "score_mode": SCORE_MODE_MANUAL},
    {"name": "Monthly Management Review (MMR)",    "short": "MMR",            "frequency": "once",            "scope": SCOPE_COMPANY, "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "One pager Memo",                     "short": "1-Pager",        "frequency": "multiple times",  "scope": SCOPE_HOD,     "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "Action Closure Review",              "short": "Action Closure", "frequency": "multiple times",  "scope": SCOPE_HOD,     "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "Accountability & Ownership Rating",  "short": "A&O Rtg",        "frequency": "once in a month", "scope": SCOPE_HOD,     "upload_required": False, "score_mode": SCORE_MODE_FORM},
    {"name": "Culture Rating",                     "short": "Cult Rtg",       "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": False, "score_mode": SCORE_MODE_FORM},
    {"name": "RRO",                                "short": "RRO",            "frequency": "once in a month", "scope": SCOPE_HOD,     "upload_required": False, "score_mode": SCORE_MODE_MANUAL},
    {"name": "Implementation Update Feedback",     "short": "Imp Stats",      "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": False, "score_mode": SCORE_MODE_FORM},
    {"name": "Team Engagement Index",              "short": "TEI",            "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "Customer Satisfaction Index",        "short": "CSI",            "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
    {"name": "Organization Result Matrix",         "short": "ORM",            "frequency": "once in a month", "scope": SCOPE_COMPANY, "upload_required": True,  "score_mode": SCORE_MODE_MANUAL},
]


def is_once_per_month(frequency: str) -> bool:
    """Port of the conflict gate in checkScheduleConflict (code.js:758-760).
    Only "once"-type activities are duplicate-checked; "3-4 in month" and
    "multiple times" are exempt."""
    f = (frequency or "").strip().lower()
    is_once = "once" in f or f.startswith("1 ") or f == "1"
    is_multi = "multiple" in f or bool(__import__("re").search(r"\d\s*-\s*\d", f))
    return is_once and not is_multi


# ─────────────────────────────────────────────────────────────
# Reminder rules — defaults applied to every schedule on save
# (autoRemindersFromRules_, code.js:3690; seeds from ensureReminderRulesSheet_:3673)
# ─────────────────────────────────────────────────────────────
class ReminderRule(BaseModel):
    activity: str = "*"                  # "*" = applies to every activity
    stage: str
    offset_value: int
    offset_unit: str = "DAYS"            # MINS | HRS | DAYS
    offset_dir: str = "before"           # before | after
    channel: str = CHANNEL_EMAIL
    active: bool = True


REMINDER_RULE_SEED: List[dict] = [
    {"activity": "*", "stage": "Initiate (Day-2)",     "offset_value": 2, "offset_unit": "DAYS", "offset_dir": "before", "channel": CHANNEL_EMAIL, "active": True},
    {"activity": "*", "stage": "Pre-Reminder (Day-1)", "offset_value": 1, "offset_unit": "DAYS", "offset_dir": "before", "channel": CHANNEL_EMAIL, "active": True},
    {"activity": "*", "stage": "Same-day 2h before",   "offset_value": 2, "offset_unit": "HRS",  "offset_dir": "before", "channel": CHANNEL_BOTH,  "active": True},
]


# ─────────────────────────────────────────────────────────────
# Lifecycle documents
# ─────────────────────────────────────────────────────────────
class RescheduleRequest(BaseModel):
    event_id: str
    company_id: str
    company_name: Optional[str] = None
    activity: Optional[str] = None
    title: Optional[str] = None
    old_date: Optional[str] = None
    old_time: Optional[str] = None
    new_date: str
    new_time: Optional[str] = None
    reason: Optional[str] = ""
    requested_by: str
    requested_by_name: Optional[str] = None
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = REQUEST_PENDING
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    note: Optional[str] = ""


class TaskUpload(BaseModel):
    event_id: str
    company_id: str
    company_name: Optional[str] = None
    activity: Optional[str] = None
    scope: Optional[str] = None          # company | hod, from the activity catalogue
    period: Optional[str] = None         # YYYY-MM
    member_id: Optional[str] = None
    member_name: Optional[str] = None
    file_name: str
    s3_key: str
    file_url: Optional[str] = None
    uploaded_by: str
    uploaded_by_name: Optional[str] = None
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)


class ActivityTrackerRow(BaseModel):
    """One row per (company, member, activity, occurrence). Feeds the Success-Measure
    engine and the Employee Activity dashboard. Port of writeTrackerRows_ (code.js:884)."""
    company_id: str
    member_id: Optional[str] = None
    member_name: Optional[str] = None
    period: str                          # YYYY-MM
    date: str                            # YYYY-MM-DD
    activity: str
    status: str = STATUS_SCHEDULED
    event_id: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Escalation(BaseModel):
    """Written by Engine B (syncAutoFeed). One row per event, idempotent."""
    event_id: str
    company_id: str
    company_name: Optional[str] = None
    om: Optional[str] = None
    activity: Optional[str] = None
    target_date: Optional[str] = None
    actual_date: Optional[str] = None
    status: str = "Active"               # Active | Resolved
    level: int = 0
    escalated_to: Optional[str] = None   # HOD | HR | MD
    escalation_date: Optional[str] = None
    last_reminder: Optional[str] = None
    resolution_date: Optional[str] = None
    resolution_method: Optional[str] = None
    resolved_by: Optional[str] = None
    recommended_action: Optional[str] = None


class ActionItem(BaseModel):
    """Written by Engine B at overdue ≥1 day; closed when the activity completes.
    The delay split (learner vs staff) comes from the two-step completion."""
    event_id: str
    company_id: str
    company_name: Optional[str] = None
    activity: Optional[str] = None
    action: Optional[str] = None         # "Follow up: <Activity>"
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    target_date: Optional[str] = None
    status: str = "Pending"              # Pending | Closed
    delay_days: int = 0
    learner_delay_days: Optional[int] = None
    staff_delay_days: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SuccessMeasure(BaseModel):
    """One row per (company, activity, period). Merges the sheet's Success_Measures and
    Success_Manual: `scope`/`hod_id` are set only for per-HOD manual entries."""
    company_id: str
    activity: str
    period: str                          # YYYY-MM
    impl_target: Optional[int] = 100
    impl_actual: Optional[int] = None    # binary 100/0 — mirrors the Apps Script
    score_target: Optional[int] = 100
    score_actual: Optional[int] = None
    achievement: Optional[int] = None
    scope: str = SCOPE_COMPANY
    hod_id: Optional[str] = None
    hod_name: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MailTemplate(BaseModel):
    """Per activity × side × event body. Merges the sheet's `Templates` (11 columns per
    activity) and `HOD_Form_mail_templates` (6 form-specific columns)."""
    activity: str                        # activity name, form_type, or "*"
    side: str                            # staff | company | employee | admin
    event: str                           # schedule | reminder | reschedule | cancel | completed | form_summary | form_scorecard
    subject: Optional[str] = None
    body_html: str
    active: bool = True


# ─────────────────────────────────────────────────────────────
# Index specification — consumed by app/db/mongodb.py at startup
# (collection, keys, {options})
# ─────────────────────────────────────────────────────────────
TPMS_INDEXES = [
    (COLL_ACTIVITIES,          [("name", 1)],                                        {"unique": True, "name": "uniq_name"}),
    (COLL_REMINDER_RULES,      [("activity", 1), ("active", 1)],                     {"name": "by_activity_active"}),
    (COLL_RESCHEDULE_REQUESTS, [("status", 1), ("company_id", 1)],                   {"name": "by_status_company"}),
    (COLL_RESCHEDULE_REQUESTS, [("event_id", 1)],                                    {"name": "by_event"}),
    (COLL_TASK_UPLOADS,        [("event_id", 1)],                                    {"name": "by_event"}),
    (COLL_TASK_UPLOADS,        [("company_id", 1), ("period", 1)],                   {"name": "by_company_period"}),
    (COLL_ACTIVITY_TRACKER,    [("company_id", 1), ("period", 1), ("activity", 1)],  {"name": "by_company_period_activity"}),
    (COLL_ACTIVITY_TRACKER,    [("event_id", 1), ("member_id", 1)],                  {"unique": True, "name": "uniq_event_member"}),
    (COLL_ESCALATIONS,         [("event_id", 1)],                                    {"unique": True, "name": "uniq_event"}),
    (COLL_ESCALATIONS,         [("status", 1), ("company_id", 1)],                   {"name": "by_status_company"}),
    (COLL_ACTION_ITEMS,        [("event_id", 1)],                                    {"unique": True, "name": "uniq_event"}),
    (COLL_ACTION_ITEMS,        [("status", 1), ("company_id", 1)],                   {"name": "by_status_company"}),
    (COLL_SUCCESS_MEASURES,    [("company_id", 1), ("activity", 1), ("period", 1),
                                ("scope", 1), ("hod_id", 1)],                        {"unique": True, "name": "uniq_company_activity_period_scope"}),
    (COLL_SUCCESS_MEASURES,    [("company_id", 1), ("period", 1)],                   {"name": "by_company_period"}),
    (COLL_MAIL_TEMPLATES,      [("activity", 1), ("side", 1), ("event", 1)],         {"unique": True, "name": "uniq_activity_side_event"}),
]
