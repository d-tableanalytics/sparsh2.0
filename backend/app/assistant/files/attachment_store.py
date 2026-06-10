"""Persistence for assistant attachments (Mongo: assistant_attachments).

Owner-scoped reads/writes — an attachment id alone is never sufficient; every
query also filters by ``uploaded_by``. Mirrors the style of
app/assistant/memory/conversation_store.py (lazy index creation, no startup hook).

One document combines the product spec's `attachments` + `attachment_processing`
tables (MongoDB is schema-less, so embedding the processing fields is idiomatic
and avoids a join).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from app.assistant.config import config
from app.assistant.schemas.context import UserContext
from app.assistant.utils.exceptions import AssistantError
from app.db.mongodb import get_collection

COLL = config.ATTACHMENT_COLLECTION
CHUNK_COLL = config.ATTACHMENT_CHUNK_COLLECTION
_indexes_ready = False


async def ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    await get_collection(COLL).create_index([("uploaded_by", 1), ("conversation_id", 1)])
    await get_collection(CHUNK_COLL).create_index([("conversation_id", 1), ("attachment_id", 1)])
    _indexes_ready = True


def _oid(attachment_id: str) -> ObjectId:
    try:
        return ObjectId(attachment_id)
    except (InvalidId, TypeError):
        raise AssistantError("Attachment not found")


async def create_stub(
    ctx: UserContext,
    *,
    conversation_id: Optional[str],
    filename: str,
    mime_type: str,
    size: int,
    kind: str,
) -> str:
    """Insert a processing stub immediately so the UI can poll status. Returns id."""
    await ensure_indexes()
    now = datetime.utcnow()
    doc = {
        "uploaded_by": ctx.user_id,
        "conversation_id": conversation_id,
        "message_index": None,
        "filename": filename,
        "original_filename": filename,
        "mime_type": mime_type,
        "size": size,
        "kind": kind,
        "storage_provider": None,
        "storage_ref": None,
        "status": "processing",
        "extracted_text": None,
        "transcript": None,
        "summary": None,
        "images": [],
        "metadata": {},
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    res = await get_collection(COLL).insert_one(doc)
    return str(res.inserted_id)


async def set_stored(attachment_id: str, provider: str, ref: str) -> None:
    await get_collection(COLL).update_one(
        {"_id": _oid(attachment_id)},
        {"$set": {"storage_provider": provider, "storage_ref": ref,
                  "updated_at": datetime.utcnow()}},
    )


async def set_extraction(
    attachment_id: str,
    *,
    extracted_text: str,
    images: list,
    summary: Optional[str],
    metadata: dict,
    status: str = "completed",
) -> None:
    await get_collection(COLL).update_one(
        {"_id": _oid(attachment_id)},
        {"$set": {
            "extracted_text": extracted_text,
            "images": images,
            "summary": summary,
            "metadata": metadata,
            "status": status,
            "updated_at": datetime.utcnow(),
        }},
    )


async def set_failed(attachment_id: str, error: str) -> None:
    await get_collection(COLL).update_one(
        {"_id": _oid(attachment_id)},
        {"$set": {"status": "failed", "error": error, "updated_at": datetime.utcnow()}},
    )


async def get_for_user(ctx: UserContext, attachment_id: str) -> dict:
    doc = await get_collection(COLL).find_one(
        {"_id": _oid(attachment_id), "uploaded_by": ctx.user_id}
    )
    if not doc:
        raise AssistantError("Attachment not found")
    return doc


async def get_many_for_user(ctx: UserContext, ids: List[str]) -> List[dict]:
    """Owner-scoped batch fetch, preserving the requested order."""
    oids = []
    for i in ids:
        try:
            oids.append(ObjectId(i))
        except (InvalidId, TypeError):
            continue
    if not oids:
        return []
    docs = await get_collection(COLL).find(
        {"_id": {"$in": oids}, "uploaded_by": ctx.user_id}
    ).to_list(len(oids))
    by_id = {str(d["_id"]): d for d in docs}
    return [by_id[i] for i in ids if i in by_id]


async def list_for_conversation(ctx: UserContext, conversation_id: str) -> List[dict]:
    await ensure_indexes()
    return await get_collection(COLL).find(
        {"uploaded_by": ctx.user_id, "conversation_id": conversation_id}
    ).sort("created_at", 1).to_list(200)


async def link_to_conversation(ctx: UserContext, ids: List[str], conversation_id: str) -> None:
    """Attach uploaded-before-conversation files to the conversation they were
    finally sent in (uploads can precede the first message of a new chat)."""
    oids = []
    for i in ids:
        try:
            oids.append(ObjectId(i))
        except (InvalidId, TypeError):
            continue
    if not oids:
        return
    await get_collection(COLL).update_many(
        {"_id": {"$in": oids}, "uploaded_by": ctx.user_id},
        {"$set": {"conversation_id": conversation_id, "updated_at": datetime.utcnow()}},
    )


async def delete_for_user(ctx: UserContext, attachment_id: str) -> dict:
    """Delete an attachment doc + its retrieval chunks. Returns the removed doc
    (so the caller can purge the stored file). Raises if not owned/found."""
    doc = await get_for_user(ctx, attachment_id)
    await get_collection(COLL).delete_one({"_id": _oid(attachment_id), "uploaded_by": ctx.user_id})
    await get_collection(CHUNK_COLL).delete_many({"attachment_id": attachment_id})
    return doc


# ── Retrieval chunks (back the search_uploaded_files tool) ─────────────────
async def save_chunks(conversation_id: Optional[str], attachment_id: str,
                      filename: str, chunks: List[str]) -> None:
    if not chunks or not conversation_id:
        return
    await ensure_indexes()
    docs = [
        {"conversation_id": conversation_id, "attachment_id": attachment_id,
         "filename": filename, "content": c, "created_at": datetime.utcnow()}
        for c in chunks
    ]
    await get_collection(CHUNK_COLL).insert_many(docs)


async def ensure_chunks_for_conversation(
    conversation_id: str, attachment_id: str, filename: str, text: str
) -> None:
    """Backfill retrieval chunks for an attachment under this conversation, if
    none exist yet. Idempotent — safe to call on every turn.

    Files uploaded in a brand-new chat are processed with conversation_id=None
    (the conversation isn't created until the first message is sent), so
    ``process_attachment`` skips chunk indexing. The first time the file is
    actually used we learn the real conversation id and index here — otherwise
    ``search_uploaded_files`` (and therefore every follow-up turn) finds nothing.
    """
    if not conversation_id or not text:
        return
    await ensure_indexes()
    existing = await get_collection(CHUNK_COLL).count_documents(
        {"conversation_id": conversation_id, "attachment_id": attachment_id}, limit=1
    )
    if existing:
        return
    from app.services.gpt_service import chunk_text
    await save_chunks(conversation_id, attachment_id, filename, chunk_text(text))


async def conversation_has_attachments(ctx: UserContext, conversation_id: str) -> bool:
    """Whether this conversation has any of the caller's uploaded files. Used to
    tell the model it can pull file content via search_uploaded_files on turns
    where no new attachment was sent (the composer tray is cleared after a send)."""
    count = await get_collection(COLL).count_documents(
        {"uploaded_by": ctx.user_id, "conversation_id": conversation_id}, limit=1
    )
    return count > 0


async def search_chunks(conversation_id: str, query: str, limit: int = 6) -> List[dict]:
    """Keyword retrieval over a conversation's attachment chunks (mirrors
    gpt_service.get_relevant_context)."""
    from app.services.gpt_service import _kb_keywords

    col = get_collection(CHUNK_COLL)
    # Word-tokenized + escaped: raw tokens like "c++" or "(forecast)" would
    # otherwise produce an invalid $regex and fail the whole tool call.
    keywords = _kb_keywords(query)
    if keywords:
        q = {"conversation_id": conversation_id,
             "content": {"$regex": "|".join(keywords), "$options": "i"}}
    else:
        q = {"conversation_id": conversation_id}
    return await col.find(q).limit(limit).to_list(limit)
