"""Notifications for the Task Management (Delegation) module.

Kept separate from the Calendar's triggers in notification_service.py even though both
modules' docs share the calendar collections (a type=="task" doc belongs to Task
Management; the Calendar list endpoint filters those out). The Email/WhatsApp engine
itself is fully reused — template resolution, channel selection, Meta-approved WhatsApp
templates and the per-template Active/Inactive switch all come from
send_notification_from_template. Only the slugs, the recipients and the context are
owned here, so a Calendar session can never fire a Task Management trigger or vice versa.

`task_created` / `task_updated` / `task_deleted` are pre-existing slugs. They have only
ever fired for delegation tasks (the Calendar has no task-creation surface), so they are
reused as-is and any template an admin already customised keeps working untouched.
"""
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from app.services.notification_service import (
    send_notification_from_template,
    create_in_app_notification,
    format_datetime_standard,
    to_ist,
)
from app.utils.calendar_utils import find_user_by_id

logger = logging.getLogger(__name__)

# Event key -> template slug. fetch_template() appends _email / _whatsapp.
TASK_EVENT_SLUGS = {
    "created": "task_created",
    "assigned": "task_assigned",
    "updated": "task_updated",
    "deleted": "task_deleted",
    "accepted": "task_accepted",
    "completed": "task_completed",
    "reopened": "task_reopened",
    "verification_requested": "task_verification_requested",
    "verification_approved": "task_verification_approved",
    "deadline_revised": "task_deadline_revised",
    "blocked": "task_blocked",
    "dependent_on_other": "task_dependent_on_other",
    "follow_up_added": "task_follow_up_added",
    "subtask_created": "task_subtask_created",
    "in_loop_added": "task_in_loop_added",
}

# In-app title + tone per event (the bell feed mirrors every email/WhatsApp trigger).
_IN_APP = {
    "created": ("New Task Assigned", "info"),
    "assigned": ("Task Assigned to You", "info"),
    "updated": ("Task Updated", "info"),
    "deleted": ("Task Deleted", "warning"),
    "accepted": ("Task Accepted", "success"),
    "completed": ("Task Completed", "success"),
    "reopened": ("Task Reopened", "warning"),
    "verification_requested": ("Verification Requested", "info"),
    "verification_approved": ("Verification Approved", "success"),
    "deadline_revised": ("Deadline Revised", "warning"),
    "blocked": ("Task Blocked", "error"),
    "dependent_on_other": ("Task Dependent on Other", "warning"),
    "follow_up_added": ("Follow-up Added", "info"),
    "subtask_created": ("Subtask Created", "info"),
    "in_loop_added": ("Added to Task Loop", "info"),
}


def _ids(value) -> set:
    """Normalise a scalar-or-list id field to a set of non-empty strings."""
    if not value:
        return set()
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    return {str(v) for v in value if v}


def recipients_for_event(event: str, task: dict, extra: Optional[dict] = None) -> set:
    """Who hears about `event`. The actor is stripped by notify_task_event — nobody is
    notified about their own action."""
    extra = extra or {}
    assigner = _ids(task.get("user_id"))
    assignees = _ids(task.get("target_staff_id"))
    watchers = _ids(task.get("watchers"))

    if event == "assigned":
        # Only the people newly put on the task, not the ones who were already on it.
        return _ids(extra.get("new_assignee_ids"))
    if event == "in_loop_added":
        # Only the people newly put in the loop (as watchers), not the existing ones.
        return _ids(extra.get("new_watcher_ids"))
    if event == "dependent_on_other":
        # The doer the task was handed to, plus the assigner tracking it.
        return _ids(extra.get("doer_id")) | assigner | watchers
    if event in ("accepted", "completed", "verification_requested", "blocked"):
        # Progress reported upward, to the person who delegated it.
        return assigner | watchers
    if event in ("reopened", "verification_approved"):
        # The assigner's verdict, reported back down to whoever did the work.
        return assignees | watchers
    if event == "deleted":
        return assignees | watchers
    if event == "created":
        return assignees | watchers
    if event == "subtask_created":
        return assignees | watchers | assigner
    # updated / deadline_revised / follow_up_added — everyone in the loop.
    return assigner | assignees | watchers


def _build_context(event: str, task: dict, actor_name: str, extra: Optional[dict], user_obj: dict) -> dict:
    """Placeholders available to Task Management templates.

    The first block reuses the exact key names the existing task_created / task_updated
    templates already use, so bodies admins wrote against those keep rendering.
    """
    extra = extra or {}
    recipient_name = user_obj.get("full_name") or user_obj.get("first_name") or "User"
    deadline = task.get("end") or task.get("start")

    # date / day / time were part of the old task_created + task_updated context. Templates an
    # admin already customised may reference them, and render_template leaves an unknown
    # placeholder in the body verbatim — so they stay populated here.
    start = task.get("start") or ""
    try:
        dt = to_ist(datetime.fromisoformat(str(start).replace("Z", "+00:00")))
        parsed_date, parsed_day = dt.strftime("%d %b %Y"), dt.strftime("%A")
        parsed_time = "Full Day Block" if task.get("all_day") else dt.strftime("%I:%M %p")
    except Exception:
        parsed_date = parsed_day = parsed_time = str(start) or "TBD"

    context = {
        # ─── Keys the pre-existing task templates already rely on ───
        "task_name": task.get("title") or "Untitled Task",
        "assigned_user": recipient_name,
        "assigned_by": actor_name,
        "deadline": format_datetime_standard(deadline),
        "critical_level": task.get("priority") or "Normal",
        "description": task.get("description") or task.get("additional_details") or "No description provided.",
        "task_status": task.get("workflow_status") or "pending",
        "name": recipient_name,
        "event_title": task.get("title") or "Untitled Task",
        "topic": task.get("title") or "Untitled Task",
        "date": parsed_date,
        "day": parsed_day,
        "time": parsed_time,
        "session_type": "Task",
        # ─── Task Management additions ───
        "actor_name": actor_name,
        "task_category": task.get("category") or "General",
        "reason": extra.get("reason") or "Not specified.",
        "doer_name": extra.get("doer_name") or "",
        "remark": extra.get("remark") or "",
        "old_deadline": format_datetime_standard(extra.get("old_end")) if extra.get("old_end") else "Not set",
        "new_deadline": format_datetime_standard(extra.get("new_end")) if extra.get("new_end") else "Not set",
        "parent_task": extra.get("parent_title") or "",
        "subtask_name": extra.get("subtask_title") or "",
        # The in-loop (watcher) member being notified. On task_in_loop_added the recipient IS
        # the person just put in the loop, so this mirrors their name; on other triggers it
        # simply names whoever is receiving the notification.
        "loop_person": recipient_name,
    }
    return context


async def notify_task_event(
    event: str,
    task: dict,
    actor: dict,
    extra: Optional[dict] = None,
    recipient_ids: Optional[Iterable[str]] = None,
) -> None:
    """Fan a Task Management lifecycle event out over Email / WhatsApp / in-app.

    Never raises into the caller — a notification failure must not roll back the task
    mutation that triggered it. Intended to be awaited from a BackgroundTask or directly
    after the DB write.
    """
    slug = TASK_EVENT_SLUGS.get(event)
    if not slug:
        logger.warning(f"notify_task_event: unknown event '{event}'")
        return

    actor_id = str(actor.get("_id") or actor.get("id") or "")
    actor_name = actor.get("full_name") or actor.get("first_name") or actor.get("email") or "A team member"

    targets = set(recipient_ids) if recipient_ids is not None else recipients_for_event(event, task, extra)
    targets = {str(t) for t in targets if t and str(t) != actor_id}
    if not targets:
        return

    # WhatsApp only goes out for staff-scoped work, mirroring the Calendar's rule.
    scope = task.get("notification_scope", "staff")
    delivery = "both" if scope == "staff" else "email"

    title, tone = _IN_APP.get(event, ("Task Notification", "info"))
    task_id = str(task.get("_id") or task.get("id") or "")

    for uid in targets:
        try:
            user_obj = await find_user_by_id(uid)
            if not user_obj:
                continue

            context = _build_context(event, task, actor_name, extra, user_obj)

            await create_in_app_notification(
                user_id=uid,
                title=title,
                message=f"{actor_name}: '{context['task_name']}'",
                type=tone,
                meta={"task_id": task_id, "event": event, "module": "task_management"},
            )
            await send_notification_from_template(user_obj, slug, context, delivery, scope)
        except Exception as e:
            # Log and keep going: one bad recipient must not silence the rest.
            logger.error(f"Task notification '{event}' failed for user {uid}: {e}")
