"""Conversation context windowing + rolling summarization. Phase 2."""
from __future__ import annotations

from typing import List

from app.assistant.schemas.conversation import Conversation


def build_window(conversation: Conversation) -> List[dict]:
    """Return the message window (recent turns + summary) sent to the LLM. Phase 2."""
    raise NotImplementedError("context_manager.build_window — Phase 2")
