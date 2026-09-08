"""
Notification module registry — the catalogue behind Task Management ▸ Templates.

TPMS wires notifications by (activity × side × event) because a TPMS notification is about a
scheduled ACTIVITY. Task & Delegation has no such axis: a notification is about a TASK, and the
trigger alone identifies it. So the wiring key here is the trigger's slug — exactly the key
`notification_templates` has always used — and this module only adds the *catalogue* the admin
screen needs: which triggers exist, what each one is for, which placeholders it can offer, and
which module it belongs to.

Two modules are registered:

  • delegation — the Task & Delegation lifecycle (assign, accept, complete, verify, …).
    Most slugs here are pre-existing and already fired from task_notifications.py; nothing
    about when THOSE send changes. Six are new: the two halves of a reassignment, raised by
    the task update route, and four time-driven nudges raised by task_nudge_service's daily
    sweep — the daily and weekly due reminders, the overdue alert, and the alternate-day chase
    on a task waiting for its assigner to close it.

  • checklist — REPEAT tasks (repeat = Daily / Weekly / Monthly / …). A repeat occurrence is
    itself a `type: "task"` document, so its assign/complete/verify notifications already come
    from the delegation triggers above. What the recurrence engine produces that no delegation
    trigger covers is the SERIES lifecycle: an occurrence being rolled forward, and the series
    reaching its end date. Those two are the checklist triggers, and they are new.

No trigger listed here sends anything until an admin creates an ACTIVE template for it — that
is the pre-existing Task & Delegation rule (see notification_service.active_user_template), and
every NEW slug is deliberately left out of the settings seeds. That matters most for the
recurring nudges: a deploy must not be able to start mailing an assignee every single day.
Turning each one on is an explicit choice made in Task Management ▸ Templates.
"""
from typing import Dict, List, Optional

MODULE_DELEGATION = "delegation"
MODULE_CHECKLIST = "checklist"

# ─────────────────────────────────────────────────────────────
# Checklist (repeat task) trigger slugs — NEW.
#
# Fired by recurring_task_service. Kept as constants so the engine, the registry and the
# settings seeds cannot drift apart on a typo.
# ─────────────────────────────────────────────────────────────
CHECKLIST_OCCURRENCE_CREATED = "checklist_occurrence_created"
CHECKLIST_SERIES_COMPLETED = "checklist_series_completed"


def _trigger(slug: str, label: str, description: str) -> dict:
    return {"slug": slug, "label": label, "description": description}


# ─────────────────────────────────────────────────────────────
# Placeholder catalogues.
#
# These are exactly the keys the sending code puts in its context dict, so a field offered in
# the UI is guaranteed to resolve at send time rather than rendering as a literal
# "{{placeholder}}". Delegation's list mirrors task_notifications._build_context; checklist's
# mirrors checklist_notifications.build_context.
# ─────────────────────────────────────────────────────────────
DELEGATION_VARIABLES = [
    "task_name", "assigned_user", "assigned_by", "actor_name", "deadline", "critical_level",
    "description", "task_status", "task_category", "name", "date", "day", "time",
    "reason", "doer_name", "remark", "old_deadline", "new_deadline",
    "parent_task", "subtask_name", "loop_person",
    # Reassignment + the time-driven nudges. Populated by whichever trigger raises them and
    # empty elsewhere, which is harmless — render_template only substitutes the keys a body
    # actually uses.
    "previous_assignee", "new_assignee", "due_date", "days_overdue", "days_remaining",
]

CHECKLIST_VARIABLES = [
    "task_name", "assigned_user", "assigned_by", "deadline", "critical_level", "description",
    "name", "date", "day", "time",
    # Repeat-series specific.
    "repeat_type", "repeat_interval", "occurrence_date", "repeat_end_date",
    "series_total", "task_category",
]


NOTIFY_MODULES: Dict[str, dict] = {
    MODULE_DELEGATION: {
        "key": MODULE_DELEGATION,
        "label": "Delegation",
        "description": "Task & Delegation lifecycle — assignment, progress and verification.",
        "variables": DELEGATION_VARIABLES,
        "triggers": [
            _trigger("task_created", "Task Created",
                     "A task was created with assignees. Goes to the assignees."),
            _trigger("task_assigned", "Task Assigned",
                     "People were added to an existing task. Goes only to the new assignees."),
            _trigger("task_assignment_confirmation", "Assignment Confirmation (Assigner)",
                     "The assigner's own receipt that their assignment went out. Email only."),
            _trigger("task_updated", "Task Updated",
                     "Task details changed. Goes to everyone on the task."),
            _trigger("task_deleted", "Task Deleted",
                     "A task was deleted. Goes to its assignees and watchers."),
            _trigger("task_accepted", "Task Accepted",
                     "The doer accepted the task. Reported up to the assigner."),
            _trigger("task_completed", "Task Completed",
                     "The doer marked the task complete. Reported up to the assigner."),
            _trigger("task_reopened", "Task Reopened",
                     "The assigner reopened the task. Reported back down to the doer."),
            _trigger("task_verification_requested", "Verification Requested",
                     "The doer asked for sign-off. Reported up to the assigner."),
            _trigger("task_verification_approved", "Verification Approved",
                     "The assigner signed the work off. Reported back down to the doer."),
            _trigger("task_deadline_revised", "Deadline Revised",
                     "The due date moved. Goes to everyone on the task."),
            _trigger("task_blocked", "Task Blocked",
                     "The doer flagged the task as blocked. Reported up to the assigner."),
            _trigger("task_dependent_on_other", "Dependent on Other",
                     "The task was handed to another doer it now depends on."),
            _trigger("task_follow_up_added", "Follow-up Added",
                     "A follow-up was posted. Goes to everyone on the task."),
            _trigger("task_subtask_created", "Subtask Created",
                     "A subtask was created. Goes to its assignees and the assigner."),
            _trigger("task_in_loop_added", "In Loop Person",
                     "Someone was put in the loop as a watcher."),
            _trigger("upcoming_task_reminder", "Upcoming Task Reminder",
                     "Fired by the reminder scheduler when a task's reminder time arrives."),
            # ─── Reassignment (raised by the task update route) ───
            _trigger("task_reassigned", "Task Reassigned",
                     "The task was handed over — somebody taken off and somebody else put on "
                     "in the same edit. Goes to the new holder, the assigner and the watchers."),
            _trigger("task_unassigned", "Removed from Task",
                     "Sent to the person taken off the task. They are no longer on it, so no "
                     "other trigger reaches them."),
            # ─── Time-driven (raised by the nightly sweep, not by any user action) ───
            _trigger("task_due_reminder_daily", "Daily Due Reminder",
                     "Every day until the task is completed or its due date is reached. Goes "
                     "to the assignees."),
            _trigger("task_due_reminder_weekly", "Weekly Due Reminder",
                     "Every 7 days while the task is open, plus the due date itself when one "
                     "is set. The lighter cadence for longer-lived work."),
            _trigger("task_overdue", "Overdue Alert",
                     "Once, on the first sweep after a deadline is missed. Goes to the "
                     "assignees, the assigner and the watchers."),
            _trigger("task_verification_pending_reminder", "Verification Chase (Assigner)",
                     "Every alternate day while a task sits in verification, until the "
                     "assigner closes it out. Goes to the assigner only."),
        ],
    },
    MODULE_CHECKLIST: {
        "key": MODULE_CHECKLIST,
        "label": "Checklist (Repeat Tasks)",
        "description": ("Repeating task series. A repeat occurrence is a task, so its "
                        "assignment and completion notifications come from the Delegation "
                        "triggers — these two cover the series itself."),
        "variables": CHECKLIST_VARIABLES,
        "triggers": [
            _trigger(CHECKLIST_OCCURRENCE_CREATED, "Repeat Task Generated",
                     "The nightly recurrence engine rolled the series forward and created this "
                     "period's occurrence. Goes to its assignees and watchers."),
            _trigger(CHECKLIST_SERIES_COMPLETED, "Repeat Series Ended",
                     "The series passed its Repeat End Date and will generate no further "
                     "occurrences. Sent once, to the assigner and assignees."),
        ],
    },
}

# Every slug this registry knows, module-tagged. Used to reject a wiring row for a trigger
# that does not exist rather than silently storing a template nothing will ever read.
SLUG_MODULE: Dict[str, str] = {
    t["slug"]: key for key, mod in NOTIFY_MODULES.items() for t in mod["triggers"]
}


def module_for_slug(slug: str) -> Optional[str]:
    """Which module a trigger slug belongs to, or None when it is not a registered trigger.

    Accepts a channel-suffixed slug ("task_created_email") as well as the bare trigger, because
    that is how the slug is stored on a `notification_templates` document.
    """
    if not slug:
        return None
    bare = str(slug)
    for suffix in ("_email", "_whatsapp"):
        if bare.endswith(suffix):
            bare = bare[: -len(suffix)]
            break
    return SLUG_MODULE.get(bare)


def module_triggers(module: str) -> List[dict]:
    return list((NOTIFY_MODULES.get(module) or {}).get("triggers") or [])


def module_variables(module: str) -> List[str]:
    return list((NOTIFY_MODULES.get(module) or {}).get("variables") or [])
