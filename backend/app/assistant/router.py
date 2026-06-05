"""Assistant API routes.

Phase 0: endpoints are registered and authenticated, but return explicit
"not implemented" placeholders. No LLM calls, no DB writes. The orchestrator is
wired in Phase 1.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.assistant.config import config
from app.assistant.core.orchestrator import Orchestrator
from app.assistant.dependencies import get_user_context
from app.assistant.schemas.chat import AskRequest, AskResponse
from app.assistant.schemas.context import UserContext

router = APIRouter(prefix="/assistant", tags=["assistant"])

# Single orchestrator instance (stateless across requests; tools registered once).
_orchestrator = Orchestrator()


@router.get("/health")
async def health():
    """Liveness + phase marker for the assistant module."""
    return {
        "status": "ok",
        "enabled": config.ENABLED,
        "phase": "1-mvp",
        "implemented": True,
    }


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest, ctx: UserContext = Depends(get_user_context)):
    """Main chat endpoint — runs the agent loop (Phase 1).

    Authentication and UserContext injection are live; data scope is enforced
    inside each tool from `ctx`, never from model arguments.
    """
    if not config.ENABLED:
        return AskResponse(
            conversation_id=req.conversation_id or "disabled",
            answer="The assistant is currently disabled.",
            sources=[],
            meta={"enabled": False},
        )

    return await _orchestrator.handle_message(ctx, req.message, req.conversation_id)


@router.get("/conversations")
async def list_conversations(ctx: UserContext = Depends(get_user_context)):
    """List the caller's conversations (placeholder until Phase 2)."""
    return {"conversations": [], "meta": {"phase": "0-scaffold", "implemented": False}}
