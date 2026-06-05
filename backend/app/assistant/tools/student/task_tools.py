"""Student task tool: get_my_tasks (pending session tasks/assignments)."""
from __future__ import annotations

from bson import ObjectId
from bson.errors import InvalidId

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool
from app.assistant.tools.student.session_tools import SESSION_COLLECTIONS
from app.db.mongodb import get_collection


def _oid(value: str):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


@tool(
    name="get_my_tasks",
    description=(
        "List the current user's session tasks/assignments and which are still "
        "pending vs completed. Use for 'what tasks do I have', 'what's pending', "
        "'my assignments', 'what do I still need to complete'."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={
        "include_completed": {
            "type": "boolean",
            "description": "Also list completed tasks (default false — pending only)",
        },
    },
)
async def get_my_tasks(ctx: UserContext, include_completed: bool = False) -> ToolResult:
    # Personal scope: the caller's own sessions. Task definitions live on the
    # session template; completion is tracked per company in
    # company_session_progress (done_indices).
    query = {"$or": [{"assigned_member_ids": ctx.user_id}, {"coach_ids": ctx.user_id}]}
    sessions = []
    for col_name in SESSION_COLLECTIONS:
        sessions.extend(await get_collection(col_name).find(query).to_list(200))

    pending = []
    completed = []
    for s in sessions:
        template_id = s.get("session_template_id")
        if not template_id:
            continue
        tpl = await get_collection("session_templates").find_one({"_id": _oid(template_id)})
        tasks = (tpl or {}).get("tasks") or []
        if not tasks:
            continue

        progress = await get_collection("company_session_progress").find_one(
            {"company_id": ctx.company_id, "session_id": str(s["_id"])}
        )
        done_indices = set((progress or {}).get("done_indices") or [])

        for i, t in enumerate(tasks):
            entry = {"session": s.get("title"), "task": t.get("title"), "points": t.get("points")}
            (completed if i in done_indices else pending).append(entry)

    data = {
        "pending": pending,
        "pending_count": len(pending),
        "completed_count": len(completed),
    }
    if include_completed:
        data["completed"] = completed

    return ToolResult.ok(
        "get_my_tasks",
        data,
        sources=["session_templates", "company_session_progress"],
        count=len(pending),
        scope_applied=f"personal:{ctx.user_id}",
    )
