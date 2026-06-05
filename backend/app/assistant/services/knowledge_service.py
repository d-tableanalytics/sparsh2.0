"""Knowledge retrieval service (RAG bridge).

Bridges the existing `KnowledgeBase` collection (populated by the GPT Projects
feature) behind the standard RAG source contract. Retrieval is keyword-based for
now (TD-5: vector upgrade later) and ALWAYS scope-filtered to the knowledge
projects the caller may access.

Accessible-project resolution (conservative, safe subset of gpt.py logic):
  * staff/admin/superadmin → all projects (None == unrestricted)
  * learner/clientadmin    → projects linked to their batches (+ company) and
                             projects explicitly granted via gpt_permissions
Session/quarter-linked unlocks from gpt.py are intentionally NOT included yet;
being more restrictive only reduces recall, never leaks. (See TD-6.)
"""
from __future__ import annotations

import re
from typing import List, Optional, Set

from bson import ObjectId
from bson.errors import InvalidId

from app.assistant.caching import cache
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.rag import RagRetrieval, RagSource
from app.assistant.security.rbac import ROLE_AD, ROLE_SA, normalize_role
from app.db.mongodb import get_collection

KNOWLEDGE_COLLECTION = "KnowledgeBase"
SNIPPET_MAX = 500


def _maybe_oid(value: str):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def get_accessible_project_ids(ctx: UserContext) -> Optional[Set[str]]:
    """Return the set of knowledge project ids the caller may read.

    None means unrestricted (staff/admin). An empty set means no access.
    """
    if normalize_role(ctx.role) in (ROLE_SA, ROLE_AD):
        return None

    # Metadata cache: accessible projects change rarely (batch/permission edits).
    cache_key = f"accessible:{ctx.user_id}:{ctx.company_id}:{','.join(sorted(ctx.batch_ids))}"
    cached = cache.metadata_cache.get(cache_key)
    if cached is not None:
        return cached

    ids: Set[str] = set()

    # Projects linked to the user's batches (and their company's batches).
    batch_or = []
    oids = [o for o in (_maybe_oid(b) for b in ctx.batch_ids) if o]
    if oids:
        batch_or.append({"_id": {"$in": oids}})
    if ctx.company_id:
        batch_or.append({"companies": ctx.company_id})
    if batch_or:
        batches = await get_collection("batches").find({"$or": batch_or}).to_list(200)
        for b in batches:
            if b.get("gpt_project_id"):
                ids.add(str(b["gpt_project_id"]))
            for p in b.get("gpt_projects", []):
                if p.get("id"):
                    ids.add(str(p["id"]))

    # Explicit grants.
    perm_or = [{"entity_id": ctx.user_id, "entity_type": "user"}]
    if ctx.company_id:
        perm_or.append({"entity_id": ctx.company_id, "entity_type": "company"})
    perms = await get_collection("gpt_permissions").find({"$or": perm_or}).to_list(200)
    for p in perms:
        if p.get("project_id"):
            ids.add(str(p["project_id"]))

    cache.metadata_cache.set(cache_key, ids)
    return ids


def _keywords(query: str) -> List[str]:
    return [k for k in re.split(r"\W+", query.lower()) if len(k) > 3]


async def search(ctx: UserContext, query: str, limit: int = 5) -> RagRetrieval:
    accessible = await get_accessible_project_ids(ctx)

    mongo: dict = {}
    if accessible is not None:
        if not accessible:
            return RagRetrieval(query=query, sources=[], retrieval_method="keyword")
        mongo["project_id"] = {"$in": list(accessible)}

    keywords = _keywords(query)
    if keywords:
        mongo["content"] = {"$regex": "|".join(re.escape(k) for k in keywords), "$options": "i"}

    chunks = await get_collection(KNOWLEDGE_COLLECTION).find(mongo).limit(limit).to_list(limit)
    sources = [
        RagSource(
            source_id=str(c.get("_id")),
            title=c.get("filename"),
            snippet=(c.get("content") or "")[:SNIPPET_MAX],
            score=None,
            document_id=c.get("file_id"),
            collection=KNOWLEDGE_COLLECTION,
            metadata={"project_id": c.get("project_id")},
        )
        for c in chunks
    ]
    return RagRetrieval(query=query, sources=sources, retrieval_method="keyword")
