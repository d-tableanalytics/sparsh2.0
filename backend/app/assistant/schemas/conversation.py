"""Conversation persistence contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field, field_serializer

from app.assistant.schemas.chat import ChatMessage


def _utc_iso(value: Optional[datetime]) -> Optional[str]:
    """Serialize a timestamp as UTC ISO-8601 with an explicit offset.

    Stored datetimes are naive UTC (``datetime.utcnow``); without a tz marker
    the browser parses them as *local* time, skewing the "x ago" labels by the
    viewer's UTC offset. Tagging them UTC makes ``new Date(...)`` unambiguous.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class ConversationSummary(BaseModel):
    """Lightweight item for listing a user's conversations."""

    id: str
    title: str
    updated_at: datetime

    @field_serializer("updated_at")
    def _ser_updated_at(self, value: datetime, _info) -> Optional[str]:
        return _utc_iso(value)


class Conversation(BaseModel):
    id: Optional[str] = None
    user_id: str
    title: Optional[str] = None
    messages: List[ChatMessage] = Field(default_factory=list)
    summary: Optional[str] = None            # rolling summary of older turns
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_serializer("created_at", "updated_at")
    def _ser_timestamps(self, value: datetime, _info) -> Optional[str]:
        return _utc_iso(value)
