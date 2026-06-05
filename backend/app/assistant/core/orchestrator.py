"""The agent loop — the conductor.

Phase 1 implements: guardrails → context → query rewrite → prompt build →
tool-calling loop (bounded by AssistantConfig.MAX_TOOL_ITERATIONS) → format →
persist. Phase 0 exposes the interface only.
"""
from __future__ import annotations

from typing import Optional

from app.assistant.schemas.chat import AskResponse
from app.assistant.schemas.context import UserContext


class Orchestrator:
    async def handle_message(
        self,
        ctx: UserContext,
        message: str,
        conversation_id: Optional[str] = None,
    ) -> AskResponse:
        """Run one assistant turn end-to-end. Phase 1."""
        raise NotImplementedError("Orchestrator.handle_message — Phase 1")
