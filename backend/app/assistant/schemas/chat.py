"""Request/response contracts for the chat endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None    # None → start a new conversation
    stream: bool = False                     # streaming enabled in Phase 2


class ChatMessage(BaseModel):
    role: str                                # user | assistant | tool | system
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tool_calls: Optional[list] = None        # retained for transparency/debugging


class AskResponse(BaseModel):
    conversation_id: str
    answer: str
    sources: List[str] = Field(default_factory=list)
    meta: Dict = Field(default_factory=dict)
