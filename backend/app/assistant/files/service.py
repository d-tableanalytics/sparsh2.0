"""Attachment service: validation, upload orchestration, background processing.

Flow (mirrors the GPT-projects upload in app/routes/gpt.py):
  validate → temp-save (aiofiles) → create processing stub → schedule background
  job → return id immediately. The job stores the raw file, extracts content,
  indexes retrieval chunks, optionally summarizes, and flips status to
  completed/failed. The chat endpoint never blocks on heavy work.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from typing import Optional

import aiofiles
from fastapi import UploadFile

from app.assistant.config import config
from app.assistant.core.llm_client import LLMClient
from app.assistant.files import attachment_store, extractor
from app.assistant.files.storage import get_storage
from app.assistant.schemas.chat import AttachmentOut
from app.assistant.schemas.context import UserContext
from app.assistant.utils.exceptions import AssistantError

_llm = LLMClient()


class ValidationError(AssistantError):
    """Raised when an upload fails validation (surfaced as HTTP 400)."""


def _safe_name(filename: Optional[str]) -> str:
    """Strip any path components — never trust the client-supplied name."""
    return os.path.basename(filename or "file").strip() or "file"


def validate(file: UploadFile) -> str:
    """Validate one upload (extension allow/block list + size). Returns the
    sanitized filename. Raises ValidationError on rejection."""
    name = _safe_name(file.filename)
    ext = extractor.ext_of(name)

    if not ext or ext in config.BLOCKED_EXTENSIONS:
        raise ValidationError(f"File type '.{ext}' is not allowed.")
    if ext not in config.ALLOWED_EXTENSIONS:
        raise ValidationError(f"File type '.{ext}' is not supported.")

    size = getattr(file, "size", None)
    if size is not None and size > config.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise ValidationError(
            f"'{name}' exceeds the {config.MAX_FILE_SIZE_MB} MB per-file limit."
        )
    return name


async def save_and_dispatch(
    ctx: UserContext,
    file: UploadFile,
    conversation_id: Optional[str],
    background_tasks,
) -> AttachmentOut:
    """Validate, persist a stub, stream the upload to a temp file, and schedule
    background processing. Returns the stub as an AttachmentOut (status=processing)."""
    name = validate(file)
    kind = extractor.kind_of(name)

    # Stream to a temp file, enforcing the size cap even when UploadFile.size is
    # unknown (some clients omit Content-Length).
    fd, tmp_path = tempfile.mkstemp(prefix="assistant_up_", suffix=f"_{name}")
    os.close(fd)
    written = 0
    max_bytes = config.MAX_FILE_SIZE_MB * 1024 * 1024
    try:
        async with aiofiles.open(tmp_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise ValidationError(
                        f"'{name}' exceeds the {config.MAX_FILE_SIZE_MB} MB per-file limit."
                    )
                await out.write(chunk)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    attachment_id = await attachment_store.create_stub(
        ctx,
        conversation_id=conversation_id,
        filename=name,
        mime_type=file.content_type or "application/octet-stream",
        size=written,
        kind=kind,
    )

    background_tasks.add_task(
        process_attachment,
        attachment_id, tmp_path, name,
        file.content_type or "application/octet-stream",
        conversation_id,
    )

    return AttachmentOut(
        id=attachment_id, conversation_id=conversation_id, filename=name,
        mime_type=file.content_type, size=written, kind=kind,
        status="processing", created_at=datetime.utcnow(),
    )


async def process_attachment(
    attachment_id: str,
    tmp_path: str,
    filename: str,
    content_type: str,
    conversation_id: Optional[str],
) -> None:
    """Background job: store raw file, extract content, index chunks, summarize."""
    try:
        storage = get_storage()
        ref = await storage.save(tmp_path, filename, content_type)
        await attachment_store.set_stored(attachment_id, storage.provider, ref)

        result = await extractor.extract(tmp_path, filename)
        text = (result.get("text") or "").strip()
        images = result.get("images") or []
        metadata = result.get("metadata") or {}

        # Index retrieval chunks for large text (backs search_uploaded_files).
        if text and conversation_id:
            from app.services.gpt_service import chunk_text
            chunks = chunk_text(text)
            await attachment_store.save_chunks(conversation_id, attachment_id, filename, chunks)

        # Cheap one-line summary (best-effort; skip for tiny/empty extractions).
        summary = None
        if len(text) > 400:
            try:
                summary = await _llm.utility_complete(
                    f"In one sentence, describe what this file contains:\n\n{text[:3000]}",
                    max_tokens=60,
                )
            except Exception:
                summary = None

        await attachment_store.set_extraction(
            attachment_id,
            extracted_text=text,
            images=images,
            summary=summary,
            metadata=metadata,
            status="completed",
        )
    except Exception as exc:  # noqa: BLE001 — record failure, don't crash the worker
        await attachment_store.set_failed(attachment_id, str(exc))
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


async def to_out(ctx: UserContext, doc: dict, with_url: bool = True) -> AttachmentOut:
    """Map a stored doc → AttachmentOut, regenerating a fresh download URL."""
    url = None
    if with_url and doc.get("storage_ref") and doc.get("status") == "completed":
        try:
            url = await get_storage().signed_url(doc["storage_ref"])
        except Exception:
            url = None
    return AttachmentOut(
        id=str(doc["_id"]),
        conversation_id=doc.get("conversation_id"),
        filename=doc.get("filename"),
        mime_type=doc.get("mime_type"),
        size=doc.get("size"),
        kind=doc.get("kind"),
        status=doc.get("status", "processing"),
        summary=doc.get("summary"),
        error=doc.get("error"),
        url=url,
        created_at=doc.get("created_at"),
    )


async def build_attachment_context(
    ctx: UserContext, attachment_ids, conversation_id: Optional[str]
) -> dict:
    """Build the per-turn attachment context for the orchestrator.

    Returns {"text_block": str, "images": list[data-uri], "metas": list[dict]}:
      * text_block — extracted text per file, capped to protect the context window
        (over-cap files are noted so the model uses search_uploaded_files).
      * images     — base64 data URIs for gpt-4o vision (capped).
      * metas      — compact descriptors persisted on the user turn for re-render.
    Only the caller's own, fully-processed attachments are included.
    """
    empty = {"text_block": "", "images": [], "metas": []}
    if not attachment_ids:
        return empty

    docs = await attachment_store.get_many_for_user(ctx, list(attachment_ids))
    if not docs:
        return empty

    # Uploads can precede a brand-new conversation; bind them now so the
    # retrieval tool can scope chunks to this conversation.
    if conversation_id:
        await attachment_store.link_to_conversation(
            ctx, [str(d["_id"]) for d in docs], conversation_id
        )
        # Backfill retrieval chunks for files that were processed before this
        # conversation existed (their background job ran with conversation_id=None
        # and skipped indexing). Without this, follow-up turns and large-file
        # lookups via search_uploaded_files would find nothing.
        for d in docs:
            text = d.get("extracted_text") or ""
            if text:
                await attachment_store.ensure_chunks_for_conversation(
                    conversation_id, str(d["_id"]), d.get("filename"), text
                )

    parts, images, metas = [], [], []
    total = 0
    for d in docs:
        metas.append({
            "id": str(d["_id"]),
            "filename": d.get("filename"),
            "mime_type": d.get("mime_type"),
            "size": d.get("size"),
            "kind": d.get("kind"),
        })
        for img in (d.get("images") or []):
            if len(images) < config.MAX_IMAGES_PER_TURN:
                images.append(img)

        header = f"## {d.get('filename')} ({d.get('kind')})"
        text = d.get("extracted_text") or ""
        if text:
            remaining = config.MAX_TOTAL_ATTACHMENT_CHARS - total
            if remaining <= 0:
                parts.append(f"{header}\n[omitted — context limit reached; "
                             f"call search_uploaded_files to read this file]")
                continue
            cap = min(config.MAX_EXTRACTED_CHARS_PER_FILE, remaining)
            snippet = text[:cap]
            total += len(snippet)
            note = ("\n[...truncated — call search_uploaded_files for the rest...]"
                    if len(text) > cap else "")
            parts.append(f"{header}\n{snippet}{note}")
        elif d.get("summary"):
            parts.append(f"{header}\n{d.get('summary')}")
        elif d.get("status") == "failed":
            parts.append(f"{header}\n[this file could not be processed: "
                         f"{d.get('error') or 'unknown error'}]")
        elif d.get("status") != "completed":
            parts.append(f"{header}\n[still processing — ask again in a moment]")
        else:
            # Completed but no extractable text (scanned/image-only PDF, empty
            # file, or password-protected). Still name the file so the model
            # acknowledges it instead of claiming nothing was attached.
            parts.append(f"{header}\n[no readable text could be extracted from this "
                         f"file — it may be a scanned image, empty, or password-protected]")

    text_block = ""
    if parts:
        cid_hint = (f" If a file is truncated, call search_uploaded_files with "
                    f"conversation_id=\"{conversation_id}\" to read more."
                    if conversation_id else "")
        text_block = ("\n\n[Attached files — use their contents to answer the "
                      f"question.{cid_hint}]\n\n" + "\n\n".join(parts))
    return {"text_block": text_block, "images": images, "metas": metas}


async def reanalyze(ctx: UserContext, attachment_id: str, background_tasks) -> None:
    """Re-run extraction/summary for an existing attachment (POST .../analyze)."""
    doc = await attachment_store.get_for_user(ctx, attachment_id)
    ref = doc.get("storage_ref")
    if not ref:
        raise AssistantError("Attachment has no stored file to analyze")

    storage = get_storage()
    fd, tmp_path = tempfile.mkstemp(prefix="assistant_re_", suffix=f"_{doc.get('filename')}")
    os.close(fd)
    ok = await storage.download(ref, tmp_path)
    if not ok:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise AssistantError("Stored file could not be retrieved")

    await attachment_store.set_stored(attachment_id, storage.provider, ref)  # touch updated_at
    background_tasks.add_task(
        _reprocess_local, attachment_id, tmp_path,
        doc.get("filename"), doc.get("conversation_id"),
    )


async def _reprocess_local(attachment_id, tmp_path, filename, conversation_id):
    """Re-extraction path when the raw bytes are already downloaded locally."""
    try:
        result = await extractor.extract(tmp_path, filename)
        text = (result.get("text") or "").strip()
        images = result.get("images") or []
        metadata = result.get("metadata") or {}
        if text and conversation_id:
            from app.services.gpt_service import chunk_text
            await attachment_store.save_chunks(
                conversation_id, attachment_id, filename, chunk_text(text)
            )
        await attachment_store.set_extraction(
            attachment_id, extracted_text=text, images=images,
            summary=None, metadata=metadata, status="completed",
        )
    except Exception as exc:  # noqa: BLE001
        await attachment_store.set_failed(attachment_id, str(exc))
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
