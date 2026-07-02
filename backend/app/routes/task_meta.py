import re
from datetime import datetime, timezone
from typing import List

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.models.task_meta import NameCreate

router = APIRouter(tags=["Task Metadata"])

MANAGE_ROLES = ["superadmin", "admin", "coach", "staff", "clientadmin"]


def _serialize(doc: dict) -> dict:
    return {"id": str(doc["_id"]), "name": doc.get("name")}


async def _list_names(collection_name: str) -> List[dict]:
    docs = await get_collection(collection_name).find({}).sort("name", 1).to_list(1000)
    return [_serialize(d) for d in docs]


async def ensure_name(collection_name: str, name: str, user_id: str) -> dict:
    """Get-or-create by case-insensitive name match — used both by the explicit create
    endpoints below and as a safety-net upsert whenever a task is saved with a category/tag
    that isn't in the collection yet (see calendar_events.py create/update_event)."""
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    col = get_collection(collection_name)
    existing = await col.find_one({"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}})
    if existing:
        return _serialize(existing)

    doc = {"name": name, "created_by": user_id, "created_at": datetime.now(timezone.utc)}
    result = await col.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc)


async def sync_task_meta(category: str | None, tags: list[str] | None, user_id: str):
    """Fire-and-forget upsert so any category/tag that ends up on a saved task is always
    reflected in the persisted lists, even if it didn't go through the explicit create
    endpoints (e.g. an older cached frontend build, or a direct API call)."""
    try:
        if category and category.strip():
            await ensure_name("task_categories", category, user_id)
        for tag in (tags or []):
            if tag and tag.strip():
                await ensure_name("task_tags", tag, user_id)
    except Exception as e:
        print(f"sync_task_meta failed: {e}")


def _can_manage(current_user: dict) -> bool:
    role = (current_user.get("role") or "").lower()
    return role in MANAGE_ROLES


@router.get("/task-categories", response_model=List[dict])
async def list_task_categories(current_user: dict = Depends(get_current_user)):
    return await _list_names("task_categories")


@router.post("/task-categories", response_model=dict)
async def create_task_category(payload: NameCreate, current_user: dict = Depends(get_current_user)):
    return await ensure_name("task_categories", payload.name, str(current_user["_id"]))


@router.delete("/task-categories/{category_id}")
async def delete_task_category(category_id: str, current_user: dict = Depends(get_current_user)):
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to delete categories")
    result = await get_collection("task_categories").delete_one({"_id": ObjectId(category_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"message": "Category deleted"}


@router.get("/task-tags", response_model=List[dict])
async def list_task_tags(current_user: dict = Depends(get_current_user)):
    return await _list_names("task_tags")


@router.post("/task-tags", response_model=dict)
async def create_task_tag(payload: NameCreate, current_user: dict = Depends(get_current_user)):
    return await ensure_name("task_tags", payload.name, str(current_user["_id"]))


@router.delete("/task-tags/{tag_id}")
async def delete_task_tag(tag_id: str, current_user: dict = Depends(get_current_user)):
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to delete tags")
    result = await get_collection("task_tags").delete_one({"_id": ObjectId(tag_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"message": "Tag deleted"}
