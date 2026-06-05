"""Auto-title generation and rolling conversation summarization. Phase 2."""
from __future__ import annotations

from app.assistant.schemas.conversation import Conversation


async def generate_title(conversation: Conversation) -> str:
    """Generate a short title from the first exchange. Phase 2."""
    raise NotImplementedError("summarizer.generate_title — Phase 2")


async def roll_summary(conversation: Conversation) -> str:
    """Fold older turns into an updated rolling summary. Phase 2."""
    raise NotImplementedError("summarizer.roll_summary — Phase 2")
