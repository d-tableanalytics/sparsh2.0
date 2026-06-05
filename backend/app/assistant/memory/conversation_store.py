"""Conversation persistence (Mongo: assistant_conversations).

No DB schema changes in Phase 0 — the collection is created lazily on first write
in Phase 2 (MongoDB creates collections on demand). Signatures only here.
"""
from __future__ import annotations

from typing import List, Optional

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.conversation import Conversation, ConversationSummary


async def load_or_create(ctx: UserContext, conversation_id: Optional[str]) -> Conversation:
    """Load an owned conversation or create a new one. Phase 2."""
    raise NotImplementedError("conversation_store.load_or_create — Phase 2")


async def append_turn(conversation: Conversation, user_msg: str, assistant_msg: str) -> None:
    """Append a user/assistant turn and persist. Phase 2."""
    raise NotImplementedError("conversation_store.append_turn — Phase 2")


async def list_for_user(ctx: UserContext) -> List[ConversationSummary]:
    """List the caller's conversations (most recent first). Phase 2."""
    raise NotImplementedError("conversation_store.list_for_user — Phase 2")
