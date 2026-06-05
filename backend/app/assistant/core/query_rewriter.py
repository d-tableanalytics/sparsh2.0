"""Query rewriting layer.

Normalizes vague/elliptical queries and resolves follow-up references using the
conversation summary, before tool selection. Skipped when the query is already
explicit. Phase 2.
"""
from __future__ import annotations

from app.assistant.schemas.context import UserContext


async def rewrite(ctx: UserContext, message: str, conversation_summary: str = "") -> dict:
    """Return {"rewritten_query": str, "intent_hint": str | None}. Phase 2."""
    raise NotImplementedError("query_rewriter.rewrite — Phase 2")
