"""Assistant API routes.

Phase 0: endpoints are registered and authenticated, but return explicit
"not implemented" placeholders. No LLM calls, no DB writes. The orchestrator is
wired in Phase 1.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.assistant.config import config
from app.assistant.dependencies import get_user_context
from app.assistant.schemas.chat import AskRequest, AskResponse
from app.assistant.schemas.context import UserContext

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/health")
async def health():
    """Liveness + phase marker for the assistant module."""
    return {
        "status": "ok",
        "enabled": config.ENABLED,
        "phase": "0-scaffold",
        "implemented": False,
    }


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest, ctx: UserContext = Depends(get_user_context)):
    """Main chat endpoint (placeholder until Phase 1).

    Authentication and UserContext injection are live, so the request pipeline
    can be exercised end-to-end without any model integration.
    """
    return AskResponse(
        conversation_id=req.conversation_id or "pending",
        answer=(
            "The Sparsh ERP AI Assistant is being set up (Phase 0 scaffold). "
            "Conversational answers arrive in Phase 1."
        ),
        sources=[],
        meta={"phase": "0-scaffold", "implemented": False, "role_scope": ctx.role},
    )


@router.get("/conversations")
async def list_conversations(ctx: UserContext = Depends(get_user_context)):
    """List the caller's conversations (placeholder until Phase 2)."""
    return {"conversations": [], "meta": {"phase": "0-scaffold", "implemented": False}}
