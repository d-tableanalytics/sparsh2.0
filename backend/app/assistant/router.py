"""Assistant API routes (Phase 4 — production hardening).

Endpoints:
  GET  /assistant/health                   liveness (no dependencies)
  GET  /assistant/ready                    readiness (DB + key + flags)
  GET  /assistant/metrics                  operational metrics (admin only)
  POST /assistant/ask                      JSON or SSE stream
  GET  /assistant/conversations            list (owner-scoped)
  GET  /assistant/conversations/{id}       history (owner-scoped)
  DELETE /assistant/conversations/{id}     delete (owner-scoped)

Cross-cutting: correlation IDs, feature-flag gating, per-user rate limiting.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app.assistant import flags, ratelimit
from app.assistant.caching import cache
from app.assistant.config import config
from app.assistant.core.orchestrator import Orchestrator
from app.assistant.dependencies import get_user_context
from app.assistant.memory import conversation_store
from app.assistant.observability import correlation
from app.assistant.observability.metrics import metrics
from app.assistant.schemas.chat import AskRequest
from app.assistant.schemas.context import UserContext
from app.assistant.security.rbac import ROLE_AD, ROLE_SA, normalize_role
from app.assistant.utils.exceptions import AssistantError
from app.config.settings import settings
from app.db.mongodb import db_connection

router = APIRouter(prefix="/assistant", tags=["assistant"])

_orchestrator = Orchestrator()


# ── Operational ───────────────────────────────────────────────────────────
@router.get("/health")
async def health():
    """Liveness — cheap, no dependencies."""
    return {"status": "ok", "enabled": config.ENABLED, "phase": "4"}


@router.get("/ready")
async def ready():
    """Readiness — checks dependencies needed to actually serve requests."""
    db_ok = db_connection.db is not None
    key_ok = bool(settings.OPENAI_API_KEY)
    ok = db_ok and key_ok and config.ENABLED
    payload = {
        "ready": ok,
        "checks": {"database": db_ok, "openai_key": key_ok, "enabled": config.ENABLED},
        "flags": flags.snapshot(),
    }
    if not ok:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@router.get("/metrics")
async def get_metrics(ctx: UserContext = Depends(get_user_context)):
    """Operational metrics — staff/admin only."""
    if normalize_role(ctx.role) not in (ROLE_SA, ROLE_AD):
        raise HTTPException(status_code=403, detail="Not authorized")
    return {
        "metrics": metrics.snapshot(),
        "caches": {
            "metadata": cache.metadata_cache.stats(),
            "analytics": cache.analytics_cache.stats(),
            "knowledge": cache.knowledge_cache.stats(),
        },
        "flags": flags.snapshot(),
    }


# ── Chat ──────────────────────────────────────────────────────────────────
@router.post("/ask", response_model=None)
async def ask(req: AskRequest, request: Request, response: Response,
              ctx: UserContext = Depends(get_user_context)):
    cid = correlation.begin_request(request.headers.get("X-Request-ID"))

    enabled, reason = flags.is_enabled_for(ctx)
    if not enabled:
        raise HTTPException(status_code=403, detail=f"Assistant not available: {reason}")

    if config.RATE_LIMIT_ENABLED:
        allowed, retry_after = ratelimit.limiter.check(ctx.user_id)
        if not allowed:
            metrics.rate_limited += 1
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please slow down.",
                headers={"Retry-After": str(retry_after), "X-Request-ID": cid},
            )

    if req.stream and config.STREAMING_ENABLED:
        return StreamingResponse(
            _orchestrator.stream_message(ctx, req.message, req.conversation_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Request-ID": cid},
        )

    response.headers["X-Request-ID"] = cid
    try:
        return await _orchestrator.handle_message(ctx, req.message, req.conversation_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Conversation management (owner-scoped) ─────────────────────────────────
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
