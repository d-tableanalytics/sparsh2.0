"""Audit logging for assistant interactions.

Reuses the existing `activity_logs` collection. Phase 0 stub — wired in Phase 4.
"""
from __future__ import annotations

from app.assistant.schemas.context import UserContext


async def log_interaction(ctx: UserContext, message: str, answer: str, tools_used: list) -> None:
    """Persist an audit record of one assistant interaction. Phase 4."""
    raise NotImplementedError("audit.log_interaction — Phase 4")
