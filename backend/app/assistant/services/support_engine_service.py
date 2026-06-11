"""Support Engine project-name listing (prompt discoverability).

Gives the system prompt the names of the Support Engine projects the caller can
see, so the model recognises a bare project name ("what is sourcing") as a
platform module instead of deflecting it as out-of-scope — and routes it to
get_support_engine_status rather than search_knowledge.

Uses the SAME access source as the get_support_engine_status tool
(`gpt_access_service.get_projects_with_access`, lightweight), so the hint names
can never drift from what the tool will actually return. Results are cached in
the slow-changing metadata cache: project membership changes rarely (batch /
permission edits), and the prompt is built on every turn, so an uncached fetch
per message would add the learner access-resolution cost (batch/quarter/session
scans) to every request.
"""
from __future__ import annotations

from typing import List

from app.assistant.caching import cache
from app.assistant.schemas.context import UserContext
from app.services import gpt_access_service


async def list_project_names(ctx: UserContext) -> List[str]:
    """Sorted, de-duplicated names of the Support Engine projects the user can see.

    Returns [] on any error (graceful degradation: the prompt simply omits the
    discoverability hint and behaves as before). Errors are NOT cached so a
    transient failure doesn't suppress names for the whole TTL.
    """
    cache_key = (
        f"se_names:{ctx.user_id}:{ctx.company_id}:{ctx.role}:"
        f"{','.join(sorted(ctx.batch_ids))}"
    )
    cached = cache.metadata_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        projects = await gpt_access_service.get_projects_with_access(
            user_id=ctx.user_id,
            role=ctx.role,
            company_id=ctx.company_id,
            direct_batch_ids=ctx.batch_ids,
            lightweight=True,  # title/description only; skips the ~10s heavy fetch
        )
    except Exception:
        return []

    names = sorted({
        (p.get("title") or p.get("name") or "").strip()
        for p in projects
        if (p.get("title") or p.get("name") or "").strip()
    })
    cache.metadata_cache.set(cache_key, names)
    return names
