from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import List, Optional
from datetime import datetime
from bson import ObjectId
import functools
import asyncio

from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user
from app.services.s3_service import (
    upload_file_to_s3_with_key,
    get_signed_url,
    delete_file_from_s3,
)

router = APIRouter(prefix="/media", tags=["Media Library"])

# Roles allowed to manage the shared media library (the "staff side").
STAFF_ROLES = ["superadmin", "admin", "coach", "staff"]

ALLOWED_TYPES = ["video", "audio", "pdf", "document", "image", "other"]


def _serialize(doc: dict, with_url: bool = True) -> dict:
    doc["_id"] = str(doc["_id"])
    if with_url and doc.get("s3_key"):
        # Signed URLs expire, so generate a fresh one each time we hand a record out.
        doc["url"] = get_signed_url(doc["s3_key"])
    return doc


@router.post("")
async def upload_media(
    media_type: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    if current_user.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to upload media")

    media_type = (media_type or "other").lower().strip()
    if media_type not in ALLOWED_TYPES:
        media_type = "other"

    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    # Stream the upload to S3 off the event loop (boto3 is blocking).
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            functools.partial(
                upload_file_to_s3_with_key,
                file.file,
                file.filename,
                file.content_type or "application/octet-stream",
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    # UploadFile exposes size after read; fall back to spooled file position.
    try:
        size = file.size or 0
    except Exception:
        size = 0

    doc = {
        "media_type": media_type,
        "name": name.strip(),
        "description": (description or "").strip(),
        "file_name": file.filename,
        "content_type": file.content_type or "",
        "size": size,
        "s3_key": result["key"],
        "uploaded_by": str(current_user["_id"]),
        "created_at": datetime.utcnow(),
    }

    col = get_collection("media_library")
    res = await col.insert_one(doc)
    doc["_id"] = res.inserted_id
    serialized = _serialize(doc, with_url=False)
    serialized["url"] = result["url"]
    return {"message": "File uploaded successfully", "media": serialized}


@router.get("")
async def list_media(
    media_type: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    col = get_collection("media_library")
    query = {}
    if media_type and media_type.lower() != "all":
        query["media_type"] = media_type.lower()

    items = await col.find(query).sort("created_at", -1).to_list(500)
    return [_serialize(i) for i in items]


@router.get("/{media_id}")
async def get_media(media_id: str, current_user: dict = Depends(get_current_user)):
    col = get_collection("media_library")
    doc = await col.find_one({"_id": ObjectId(media_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Media not found")
    return _serialize(doc)


@router.delete("/{media_id}")
async def delete_media(media_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to delete media")

    col = get_collection("media_library")
    doc = await col.find_one({"_id": ObjectId(media_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Media not found")

    if doc.get("s3_key"):
        delete_file_from_s3(doc["s3_key"])

    await col.delete_one({"_id": ObjectId(media_id)})
    return {"message": "Media deleted successfully"}
