"""Assistant API routes (Phase 2).

Endpoints:
  GET  /assistant/health
  POST /assistant/ask                      (JSON, or SSE stream when req.stream)
  GET  /assistant/conversations            list the caller's conversations
  GET  /assistant/conversations/{id}       owner-scoped full history
  DELETE /assistant/conversations/{id}     owner-scoped delete

Data scope and conversation ownership are enforced server-side from UserContext.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.assistant.config import config
from app.assistant.core.orchestrator import Orchestrator
from app.assistant.dependencies import get_user_context
from app.assistant.memory import conversation_store
from app.assistant.schemas.chat import AskRequest, AskResponse
from app.assistant.schemas.context import UserContext
from app.assistant.utils.exceptions import AssistantError

router = APIRouter(prefix="/assistant", tags=["assistant"])

# Single orchestrator instance (stateless per request; tools registered once).
_orchestrator = Orchestrator()


@router.get("/health")
async def health():
    return {"status": "ok", "enabled": config.ENABLED, "phase": "2", "implemented": True}


@router.post("/ask", response_model=None)
async def ask(req: AskRequest, ctx: UserContext = Depends(get_user_context)):
    """Chat endpoint. Returns JSON, or an SSE token stream when `stream=true`."""
    if not config.ENABLED:
        return AskResponse(
            conversation_id=req.conversation_id or "disabled",
            answer="The assistant is currently disabled.",
            sources=[],
            meta={"enabled": False},
        )

    if req.stream:
        return StreamingResponse(
            _orchestrator.stream_message(ctx, req.message, req.conversation_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        return await _orchestrator.handle_message(ctx, req.message, req.conversation_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/conversations")
async def list_conversations(ctx: UserContext = Depends(get_user_context)):
    items = await conversation_store.list_for_user(ctx)
    return {"conversations": [i.model_dump() for i in items]}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, ctx: UserContext = Depends(get_user_context)):
    try:
        convo = await conversation_store.load_or_create(ctx, conversation_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return convo.model_dump()


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, ctx: UserContext = Depends(get_user_context)):
    try:
        await conversation_store.delete_conversation(ctx, conversation_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": True}
