"""Query rewriting layer.

Normalizes vague/elliptical queries and resolves follow-up references using the
conversation summary, before tool selection. A cheap heuristic decides whether a
rewrite is even needed, so explicit questions skip the extra LLM call.

Returns: {"rewritten_query": str, "intent_hint": str | None, "rewritten": bool}
"""
from __future__ import annotations

# Pronouns / ellipsis markers that suggest the query depends on prior context.
_FOLLOWUP_MARKERS = {
    "it", "that", "this", "those", "these", "them", "they", "he", "she",
    "there", "then", "same", "one", "ones", "another", "more",
}


def _needs_rewrite(message: str) -> bool:
    words = [w.strip("?.,!").lower() for w in message.split()]
    if len(words) <= 4:                       # very short → likely elliptical
        return True
    return any(w in _FOLLOWUP_MARKERS for w in words)


async def rewrite(
    llm,
    message: str,
    conversation_summary: str = "",
    recent_context: str = "",
    meter=None,
) -> dict:
    """Resolve the message into a self-contained query when needed."""
    if not _needs_rewrite(message):
        return {"rewritten_query": message, "intent_hint": None, "rewritten": False}

    context = "\n".join(p for p in (conversation_summary, recent_context) if p)
    if not context.strip():
        # First message of a conversation: there is nothing to resolve against,
        # and rewriting without context derails it (e.g. "hi" was being turned
        # into "What would you like to discuss?", which the main model then
        # treated as the user's actual question). Pass it through unchanged so
        # direct first-attempt questions are answered as asked.
        return {"rewritten_query": message, "intent_hint": None, "rewritten": False}

    prompt = (
        "Rewrite the user's latest message into a single self-contained question, "
        "resolving any pronouns or references using the conversation context. "
        "If the message is already self-contained, or the context does not "
        "clarify it, return the message exactly as it is. "
        "Return ONLY the rewritten question, nothing else.\n\n"
        f"Conversation context:\n{context}\n\n"
        f"Latest message: {message}"
    )
    rewritten = await llm.utility_complete(prompt, max_tokens=80, meter=meter)
    rewritten = (rewritten or "").strip() or message
    return {"rewritten_query": rewritten, "intent_hint": None, "rewritten": rewritten != message}
