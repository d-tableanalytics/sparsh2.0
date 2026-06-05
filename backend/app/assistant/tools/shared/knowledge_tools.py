"""Shared knowledge tool: search_knowledge (RAG bridge)."""
from __future__ import annotations

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.services import knowledge_service
from app.assistant.tools.registry import tool


@tool(
    name="search_knowledge",
    description=(
        "Search the knowledge base / learning materials to answer conceptual or "
        "definition questions (e.g. 'what is polymorphism', 'explain X'). Returns "
        "cited document snippets. Use this for general knowledge, NOT for the "
        "user's personal records."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={"query": {"type": "string", "description": "What to look up in the knowledge base"}},
    required=["query"],
)
async def search_knowledge(ctx: UserContext, query: str) -> ToolResult:
    retrieval = await knowledge_service.search(ctx, query)
    data = retrieval.model_dump()

    # Attribution: KnowledgeBase + the cited document titles flow into sources.
    titles = sorted({s["title"] for s in data["sources"] if s.get("title")})
    return ToolResult.ok(
        "search_knowledge",
        data,
        sources=["KnowledgeBase"] + titles,
        count=len(data["sources"]),
        scope_applied=f"knowledge:{normalize_scope(ctx)}",
    )


def normalize_scope(ctx: UserContext) -> str:
    from app.assistant.security.rbac import ROLE_AD, ROLE_SA, normalize_role

    return "all" if normalize_role(ctx.role) in (ROLE_SA, ROLE_AD) else f"projects_of:{ctx.user_id}"
