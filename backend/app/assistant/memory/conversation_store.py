"""Conversation persistence (Mongo: assistant_conversations).

Implements the locked Conversation Persistence Contract
(docs/CONVERSATION_PERSISTENCE_CONTRACT.md): owner-scoped reads/writes, lazy
index creation, and summary bookkeeping.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from app.assistant.config import config
from app.assistant.schemas.chat import ChatMessage
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.conversation import Conversation, ConversationSummary
from app.assistant.utils.exceptions import AssistantError
from app.db.mongodb import get_collection

COLL = config.CONVERSATION_COLLECTION
_indexes_ready = False


async def ensure_indexes() -> None:
    """Idempotently create the ownership/listing index (lazy, no startup hook)."""
    global _indexes_ready
    if _indexes_ready:
        return
    await get_collection(COLL).create_index([("user_id", 1), ("updated_at", -1)])
    _indexes_ready = True


def _to_conversation(doc: dict) -> Conversation:
    return Conversation(
        id=str(doc["_id"]),
        user_id=doc["user_id"],
        title=doc.get("title"),
        messages=[ChatMessage(**m) for m in doc.get("messages", [])],
        summary=doc.get("summary"),
        created_at=doc.get("created_at") or datetime.utcnow(),
        updated_at=doc.get("updated_at") or datetime.utcnow(),
    )


def _oid(conversation_id: str) -> ObjectId:
    try:
        return ObjectId(conversation_id)
    except (InvalidId, TypeError):
        raise AssistantError("Conversation not found")  # treat bad id as not-found


async def load_or_create(ctx: UserContext, conversation_id: Optional[str]) -> Conversation:
    await ensure_indexes()
    col = get_collection(COLL)

    if conversation_id:
        # Ownership-checked fetch — id alone is never sufficient.
        doc = await col.find_one({"_id": _oid(conversation_id), "user_id": ctx.user_id})
        if not doc:
            raise AssistantError("Conversation not found")
        return _to_conversation(doc)

    now = datetime.utcnow()
    doc = {
        "user_id": ctx.user_id,
        "role": ctx.role,
        "title": None,
        "summary": None,
        "summary_upto": 0,
        "messages": [],
        "message_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    res = await col.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _to_conversation(doc)


async def append_turn(conversation: Conversation, user_msg: str, assistant_msg: str) -> None:
    now = datetime.utcnow()
    new_msgs = [
        {"role": "user", "content": user_msg, "timestamp": now},
        {"role": "assistant", "content": assistant_msg, "timestamp": now},
    ]
    await get_collection(COLL).update_one(
        {"_id": _oid(conversation.id), "user_id": conversation.user_id},
        {
            "$push": {"messages": {"$each": new_msgs}},
            "$inc": {"message_count": 2},
            "$set": {"updated_at": now},
        },
    )


async def set_title(conversation: Conversation, title: str) -> None:
    await get_collection(COLL).update_one(
        {"_id": _oid(conversation.id), "user_id": conversation.user_id},
        {"$set": {"title": title}},
    )


async def set_summary(conversation: Conversation, summary: str, summary_upto: int) -> None:
    await get_collection(COLL).update_one(
        {"_id": _oid(conversation.id), "user_id": conversation.user_id},
        {"$set": {"summary": summary, "summary_upto": summary_upto}},
    )


async def list_for_user(ctx: UserContext) -> List[ConversationSummary]:
    await ensure_indexes()
    docs = (
        await get_collection(COLL)
        .find({"user_id": ctx.user_id})
        .sort("updated_at", -1)
        .to_list(config.CONVERSATION_LIST_LIMIT)
    )
    return [
        ConversationSummary(
            id=str(d["_id"]),
            title=d.get("title") or "New conversation",
            updated_at=d.get("updated_at") or datetime.utcnow(),
        )
        for d in docs
    ]


async def delete_conversation(ctx: UserContext, conversation_id: str) -> None:
    res = await get_collection(COLL).delete_one(
        {"_id": _oid(conversation_id), "user_id": ctx.user_id}
    )
    if res.deleted_count == 0:
        raise AssistantError("Conversation not found")
