"""Platform-data tools: session templates, media library, notifications,
activity logs. These widen the assistant's database link so questions about
platform records beyond the learner/admin core (sessions, scores, batches...)
are answerable too — each with the same server-side RBAC scoping.
"""
from __future__ import annotations

import re
from typing import Optional

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.security.pii import redact
from app.assistant.tools.registry import tool
from app.db.mongodb import get_collection


def _safe_regex(text: str) -> dict:
    """Case-insensitive Mongo regex from user text, metacharacters escaped."""
    return {"$regex": re.escape(text.strip()), "$options": "i"}


def _clamp(value, default: int, maximum: int) -> int:
    """Forgiving limit coercion: a hallucinated non-numeric value falls back to
    the default instead of failing the whole tool call."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n or default, maximum))


@tool(
    name="get_session_templates",
    description=(
        "List the reusable session templates (coaching session blueprints): title, "
        "topic, description, and how many tasks and assessments each contains. Use "
        "for 'what session templates exist', 'which template covers X', 'how many "
        "quizzes does template Y have'. Staff only — templates contain assessment "
        "answer keys, so they are never exposed to learners (and this tool returns "
        "only summaries, never the questions or answers)."
    ),
    allowed_roles=["AD", "SA"],
    parameters={
        "name": {"type": "string", "description": "Optional title/topic keyword filter"},
        "limit": {"type": "integer", "description": "Max templates to return (default 20, max 50)"},
    },
)
async def get_session_templates(ctx: UserContext, name: Optional[str] = None, limit: int = 20) -> ToolResult:
    limit = _clamp(limit, 20, 50)
    query: dict = {}
    if name and name.strip():
        rx = _safe_regex(name)
        query = {"$or": [{"title": rx}, {"topic": rx}]}

    docs = (
        await get_collection("session_templates")
        .find(query)
        .sort("created_at", -1)
        .limit(limit)
        .to_list(limit)
    )
    items = []
    for d in docs:
        tasks = d.get("tasks") or []
        assessments = d.get("assessments") or []
        task_titles = []
        for t in tasks[:10]:
            title = t if isinstance(t, str) else (t.get("title") or t.get("name")) if isinstance(t, dict) else None
            if title:
                task_titles.append(str(title)[:80])
        items.append({
            "title": d.get("title"),
            "topic": d.get("topic"),
            "description": (d.get("description") or "")[:200],
            "task_count": len(tasks),
            "task_titles": task_titles,
            "assessment_count": len(assessments),
            "assessments": [
                {
                    "question_count": len(a.get("questions") or []),
                    "passing_score": a.get("passing_score"),
                }
                for a in assessments if isinstance(a, dict)
            ],
        })

    return ToolResult.ok(
        "get_session_templates",
        {"templates": items, "total_returned": len(items)},
        sources=["session_templates"],
        count=len(items),
        scope_applied="staff:org-wide",
    )


@tool(
    name="search_media_library",
    description=(
        "Search the shared Media Library's file catalog (videos, audio, PDFs, "
        "documents, images) by name, tag, or type. Returns file metadata — name, "
        "type, size, folder, tags, upload date — NOT the files themselves. Use for "
        "'is there a video about X', 'what PDFs are in the media library', 'find "
        "the recording of Y'. Tell the user to open the Media Library page to view "
        "or play a file."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={
        "query": {"type": "string", "description": "Optional name/tag keyword to search for"},
        "media_type": {
            "type": "string",
            "description": "Optional filter: video, audio, pdf, document, image, or other",
        },
        "limit": {"type": "integer", "description": "Max files to return (default 20, max 50)"},
    },
)
async def search_media_library(
    ctx: UserContext, query: Optional[str] = None, media_type: Optional[str] = None, limit: int = 20
) -> ToolResult:
    limit = _clamp(limit, 20, 50)
    mongo_q: dict = {}
    if media_type and media_type.strip():
        mongo_q["media_type"] = media_type.strip().lower()
    if query and query.strip():
        rx = _safe_regex(query)
        mongo_q["$or"] = [{"name": rx}, {"file_name": rx}, {"tags": rx}, {"description": rx}]

    docs = (
        await get_collection("media_library")
        .find(mongo_q)
        .sort("created_at", -1)
        .limit(limit)
        .to_list(limit)
    )
    items = [
        {
            "name": d.get("name"),
            "media_type": d.get("media_type"),
            "file_name": d.get("file_name"),
            "size_bytes": d.get("size"),
            "folder": d.get("folder"),
            "tags": d.get("tags") or [],
            "uploaded_at": d.get("created_at"),
        }
        for d in docs
    ]

    return ToolResult.ok(
        "search_media_library",
        {"files": items, "total_returned": len(items)},
        sources=["media_library"],
        count=len(items),
        scope_applied="shared-library",
    )


@tool(
    name="get_my_notifications",
    description=(
        "Return the caller's own in-app notifications: unread count and the most "
        "recent items (title, message, type, read/unread, date). Use for 'any new "
        "notifications', 'what did I miss', 'do I have unread alerts'."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={
        "only_unread": {"type": "boolean", "description": "Return only unread notifications"},
        "limit": {"type": "integer", "description": "Max notifications to return (default 10, max 30)"},
    },
)
async def get_my_notifications(ctx: UserContext, only_unread: bool = False, limit: int = 10) -> ToolResult:
    limit = _clamp(limit, 10, 30)
    col = get_collection("in_app_notifications")

    base = {"user_id": ctx.user_id}
    unread_count = await col.count_documents({**base, "is_read": False})

    q = {**base, "is_read": False} if only_unread else base
    docs = await col.find(q).sort("created_at", -1).limit(limit).to_list(limit)
    items = [
        {
            "title": d.get("title"),
            "message": (d.get("message") or "")[:300],
            "type": d.get("type"),
            "is_read": bool(d.get("is_read")),
            "created_at": d.get("created_at"),
        }
        for d in docs
    ]

    return ToolResult.ok(
        "get_my_notifications",
        {"unread_count": unread_count, "notifications": items},
        sources=["in_app_notifications"],
        count=len(items),
        scope_applied=f"personal:{ctx.user_id}",
    )


@tool(
    name="get_activity_logs",
    description=(
        "Return recent platform activity / audit-log entries (who did what, in "
        "which module, when). Superadmin only. Use for 'what happened recently', "
        "'recent activity in the Users module', 'who changed X'."
    ),
    allowed_roles=["SA"],
    parameters={
        "module": {"type": "string", "description": "Optional module filter, e.g. Users, Companies, Calendar"},
        "limit": {"type": "integer", "description": "Max entries to return (default 20, max 50)"},
    },
)
async def get_activity_logs(ctx: UserContext, module: Optional[str] = None, limit: int = 20) -> ToolResult:
    limit = _clamp(limit, 20, 50)
    q: dict = {}
    if module and module.strip():
        q["module"] = _safe_regex(module)

    docs = (
        await get_collection("activity_logs")
        .find(q)
        .sort("timestamp", -1)
        .limit(limit)
        .to_list(limit)
    )
    # PII stance: names and actions, never contact details. The user_email field
    # is omitted AND the free-text details are redact()ed — log writers embed
    # emails in the details string (e.g. "OTP generated for <email>").
    items = [
        {
            "user_name": d.get("user_name"),
            "action": d.get("action"),
            "module": d.get("module"),
            "details": redact(str(d.get("details") or ""))[:200],
            "timestamp": d.get("timestamp"),
        }
        for d in docs
    ]

    return ToolResult.ok(
        "get_activity_logs",
        {"entries": items, "total_returned": len(items)},
        sources=["activity_logs"],
        count=len(items),
        scope_applied="superadmin:org-wide",
    )
