"""Documentation — one library for employee and candidate documents.

The review document asks for a place where every employee/candidate document can be uploaded,
updated and managed, with document-wise status tracking and easy retrieval. That is three
things, and each is handled here:

  * upload/update — files go to S3 under a gated prefix (`upload_file_to_s3_with_key`, the same
    helper resumes and punch selfies use). Only the key is stored; the bytes never live in
    Mongo.
  * status        — Pending → Uploaded → Verified | Rejected, plus Expired, which is derived
    from `expires_on` at read time rather than needing a sweep job.
  * retrieval     — reads are served as short-lived signed URLs, so a document is never a
    permanently public object.

Replacing a file supersedes rather than overwrites: the version counter goes up and the
previous key is retained on the document's history, because "we replaced the wrong scan" is a
recoverable mistake only if the old key still exists.
"""
import io
import logging
from datetime import datetime, timezone, date
from typing import Optional

from app.db.mongodb import get_collection
from app.models.hrms import (
    COL_DOCUMENTS, SEQ_DOCUMENT,
    DOC_OWNER_TYPES, DOC_OWNER_EMPLOYEE, DOC_OWNER_CANDIDATE,
    DOC_PENDING, DOC_UPLOADED, DOC_VERIFIED, DOC_REJECTED, DOC_EXPIRED, DOC_STATUSES,
)
from app.utils.counters import next_code
from app.services.s3_service import upload_file_to_s3_with_key, get_signed_url

logger = logging.getLogger(__name__)

DOCUMENT_PREFIX = "hrms/documents"


async def generate_document_no() -> str:
    return await next_code(SEQ_DOCUMENT, "DOC", width=4)


def validate_document(payload: dict) -> None:
    owner_type = (payload.get("owner_type") or "").strip()
    if owner_type not in DOC_OWNER_TYPES:
        raise ValueError(f"owner_type must be one of {DOC_OWNER_TYPES}")
    if not (payload.get("owner_id") or "").strip():
        raise ValueError("owner_id is required")
    if not (payload.get("doc_type") or "").strip():
        raise ValueError("Document type is required")
    status = payload.get("status")
    if status and status not in DOC_STATUSES:
        raise ValueError(f"status must be one of {DOC_STATUSES}")


def store_document(blob: bytes, extension: str, content_type: str, doc_no: str,
                   version: int) -> str:
    """Put a document on S3 under the gated prefix. Returns the key, or "" on failure.

    The version is part of the key, so superseding a file cannot overwrite the bytes of the
    one it replaced.
    """
    try:
        name = f"{DOCUMENT_PREFIX}/{doc_no}-v{version}{extension}"
        result = upload_file_to_s3_with_key(io.BytesIO(blob), name, content_type)
        return (result or {}).get("key") or ""
    except Exception as e:
        logger.error("Document upload failed for %s: %s", doc_no, e)
        return ""


def effective_status(doc: dict) -> str:
    """Stored status, with expiry applied.

    Derived rather than stored so an expiry that passes overnight is reflected on the next read
    without a sweep job. A verified-but-expired document reads as Expired: that is the state HR
    needs to act on.
    """
    stored = doc.get("status") or DOC_PENDING
    if stored in (DOC_REJECTED, DOC_PENDING):
        return stored
    expires = doc.get("expires_on")
    if expires:
        try:
            if date.fromisoformat(str(expires)[:10]) < date.today():
                return DOC_EXPIRED
        except ValueError:
            pass
    return stored


def serialize_document(doc: dict, include_key: bool = False) -> dict:
    """A document for an internal reader.

    The S3 key is withheld by default — retrieval goes through the download endpoint, which
    issues a short-lived signed URL, so the key itself is not something a list response hands
    out for later reuse.
    """
    out = {
        "id": str(doc.get("_id")),
        "documentNo": doc.get("document_no") or "",
        "ownerType": doc.get("owner_type") or "",
        "ownerId": doc.get("owner_id") or "",
        "ownerName": doc.get("owner_name") or "",
        "docType": doc.get("doc_type") or "",
        "title": doc.get("title") or "",
        "status": effective_status(doc),
        "storedStatus": doc.get("status") or DOC_PENDING,
        "version": int(doc.get("version") or 0),
        "hasFile": bool(doc.get("s3_key")),
        "fileName": doc.get("file_name") or "",
        "remarks": doc.get("remarks") or "",
        "expiresOn": doc.get("expires_on"),
        "uploadedBy": doc.get("uploaded_by_name") or "",
        "uploadedAt": doc.get("uploaded_at"),
        "verifiedBy": doc.get("verified_by_name") or "",
        "verifiedAt": doc.get("verified_at"),
        "createdAt": doc.get("created_at"),
        "updatedAt": doc.get("updated_at"),
        # Superseded versions, newest first — what makes a replaced file recoverable.
        "history": [
            {"version": h.get("version"), "fileName": h.get("file_name") or "",
             "replacedAt": h.get("replaced_at")}
            for h in reversed(doc.get("history") or [])
        ],
    }
    if include_key:
        out["s3Key"] = doc.get("s3_key") or ""
    return out


def signed_download_url(doc: dict, expires_in: int = 300) -> Optional[str]:
    """Short-lived URL for one document, or None when there is no file yet."""
    key = doc.get("s3_key")
    if not key:
        return None
    try:
        return get_signed_url(key, expires_in=expires_in)
    except Exception as e:
        logger.error("Signed URL failed for %s: %s", doc.get("document_no"), e)
        return None


async def resolve_owner_name(owner_type: str, owner_id: str) -> str:
    """Display name for the document's owner, denormalised onto the document.

    Stored alongside the id so the library lists without a per-row join, matching how postings
    and candidates already carry department and designation.
    """
    from app.models.hrms import COL_EMPLOYEES, COL_CANDIDATES
    try:
        if owner_type == DOC_OWNER_EMPLOYEE:
            row = await get_collection(COL_EMPLOYEES).find_one(
                {"employee_code": owner_id}, {"full_name": 1})
            return (row or {}).get("full_name") or ""
        if owner_type == DOC_OWNER_CANDIDATE:
            row = await get_collection(COL_CANDIDATES).find_one({"uk": owner_id}, {"full_name": 1})
            return (row or {}).get("full_name") or ""
    except Exception as e:
        logger.warning("Owner lookup failed for %s/%s: %s", owner_type, owner_id, e)
    return ""


async def document_stats(query: dict) -> dict:
    """Counts by effective status for the library header.

    Computed in Python rather than as a $group because Expired is derived from a date rather
    than stored, so the database cannot group on it.
    """
    counts = {s: 0 for s in DOC_STATUSES}
    async for doc in get_collection(COL_DOCUMENTS).find(query, {"status": 1, "expires_on": 1}):
        counts[effective_status(doc)] = counts.get(effective_status(doc), 0) + 1
    counts["total"] = sum(counts[s] for s in DOC_STATUSES)
    return counts
