"""Request/response contracts for the chat endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None    # None → start a new conversation
    stream: bool = False                     # streaming enabled in Phase 2
    # Index of a prior user message being edited; the stored conversation is
    # truncated to before it so the assistant answers the revised question
    # instead of replaying stale history. None → normal append.
    edit_from_index: Optional[int] = None


class ToolAttribution(BaseModel):
    """Which tool produced data backing an assistant turn (persisted per turn)."""

    tool: str
    sources: List[str] = Field(default_factory=list)
    scope_applied: Optional[str] = None
    success: bool = True
    count: Optional[int] = None


class ChatMessage(BaseModel):
    role: str                                # user | assistant | tool | system
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tool_calls: Optional[list] = None        # retained for transparency/debugging
    attributions: Optional[List[ToolAttribution]] = None   # set on assistant turns


class AskResponse(BaseModel):
    conversation_id: str
    answer: str
    sources: List[str] = Field(default_factory=list)
    meta: Dict = Field(default_factory=dict)
