"""System-prompt construction: persona, RBAC context, verbosity rules. Phase 1."""
from __future__ import annotations

from app.assistant.schemas.context import UserContext


def build_system_prompt(ctx: UserContext) -> str:
    """Compose the system prompt for a given user context. Phase 1."""
    raise NotImplementedError("prompt_builder.build_system_prompt — Phase 1")
