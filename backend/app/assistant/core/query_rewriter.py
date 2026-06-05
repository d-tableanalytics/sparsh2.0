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

# Greetings and social niceties that need no context rewrite — answer directly.
_CASUAL = {
    # Standard greetings
    "hi", "hello", "hey", "hiya", "howdy", "yo", "sup", "heya",
    # Common typos / informal variants
    "hy", "hii", "hiii", "helo", "helo", "heyy", "heyyy", "hai",
    "helo", "hell0", "h1", "hihi", "hiiii",
    # Time-based greetings
    "good morning", "good afternoon", "good evening", "good night",
    "gm", "gn",
    # How are you variants
    "how are you", "how r u", "how are u", "how r you",
    "whats up", "what's up", "wassup", "wazzup",
    "how do you do", "how's it going", "hows it going",
    "how are you doing", "how r u doing",
    # Thanks / acknowledgement
    "thanks", "thank you", "ty", "thx", "cheers", "thnx", "thanku", "thank u",
    # Bye
    "bye", "goodbye", "good bye", "see you", "see ya", "cya", "take care",
    "bye bye", "byee", "tata",
    # Short acknowledgements
    "ok", "okay", "okk", "okkk", "alright", "cool", "nice", "great", "got it",
    "sure", "sounds good", "perfect", "awesome", "noted", "k", "kk",
}

# First-word triggers: if the message starts with one of these it's a greeting
_GREETING_STARTERS = {
    "hi", "hey", "hello", "hy", "hiya", "heya", "hii", "helo", "hai",
    "howdy", "yo", "sup", "gm", "gn",
}


def _is_casual(message: str) -> bool:
    """True for greetings / social niceties — skip context-based rewrite."""
    normalized = message.strip().lower().rstrip("!?.,;: ")
    if normalized in _CASUAL:
        return True
    # Also catch "hi there", "hey buddy", "hello everyone", etc.
    first_word = normalized.split()[0] if normalized.split() else ""
    return first_word in _GREETING_STARTERS


def _needs_rewrite(message: str) -> bool:
    if _is_casual(message):
        return False
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
    prompt = (
        "Rewrite the user's latest message into a single self-contained question, "
        "resolving any pronouns or references using the conversation context. "
        "Return ONLY the rewritten question, nothing else.\n\n"
        f"Conversation context:\n{context or '(none)'}\n\n"
        f"Latest message: {message}"
    )
    rewritten = await llm.utility_complete(prompt, max_tokens=80, meter=meter)
    rewritten = (rewritten or "").strip() or message
    return {"rewritten_query": rewritten, "intent_hint": None, "rewritten": rewritten != message}
