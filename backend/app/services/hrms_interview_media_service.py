"""The interview record — the written report and the recording of the call.

-- Why this is not part of the interview -----------------------------------------------------
`hrms_interviews` holds ROUNDS: who sat on the panel, when, and how they scored six
competencies. That record is Sparsh's and stays Sparsh's — it names interviewers and carries
internal scoring, and a client reviewing a candidate has no business in either.

What a client is owed (brief §10) is different and simpler: the report that came OUT of the
process, and the ability to watch the call. Those are properties of the CANDIDATE, not of
round two of three, so they live on the candidate document and a share carries them.

Keeping them apart also keeps the scorecard honest. If the panel's scoring were the thing
shown to clients, it would start being written for clients.

-- The download asymmetry, and its honest limit ----------------------------------------------
The brief is explicit: a client may DOWNLOAD the CV, may VIEW the report, and may only WATCH
the recording. That asymmetry is real here —

    CV         -> `download_as` set, so the link arrives as `Content-Disposition: attachment`
    report     -> no disposition; the browser renders it in place
    recording  -> no disposition, a deliberately short lease, and no download affordance
                  anywhere in the client UI

— but it must not be oversold. A signed URL is a URL: anyone holding one can fetch the bytes
with any HTTP client, and an external recording link (Zoom, Meet, Teams) is governed by that
platform's sharing rules, not by ours. What this design actually delivers is that the product
offers no way to save the video, and that every open is attributed and logged. Preventing a
determined viewer from keeping a copy of a video they are authorised to watch is not
something any web player can promise, and claiming otherwise in a comment would mislead
whoever reads this next.

House convention: services validate, gate and audit; routes only check the capability.
"""
from __future__ import annotations

import base64
import binascii
import io as _io
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    ALLOWED_RECORDING_MIME, AUDIT_INTERVIEW_MEDIA_REMOVED,
    AUDIT_INTERVIEW_RECORDING_FILED, AUDIT_INTERVIEW_REPORT_FILED,
    COLL_CANDIDATE_SHARES, COLL_CANDIDATES, ENTITY_CANDIDATE, MAX_RECORDING_BYTES,
    ShareStatus,
)
from app.services.hrms_audit_service import audit
from app.utils.hrms_public_guard import clean_text, decode_upload, safe_filename

# The two kinds of interview material, and the candidate field each is stored under. Declared
# as data so the upload, the removal, the share snapshot and the routes cannot drift apart on
# what a "kind" is called.
REPORT = "report"
RECORDING = "recording"
MEDIA_FIELD = {REPORT: "interview_report", RECORDING: "interview_recording"}

# A recording link must at least be a link. Not a whitelist of providers: a company running
# its own Jitsi or serving from its own storage is a normal case, and a provider list would
# quietly break them while stopping nobody.
_ALLOWED_SCHEMES = {"http", "https"}

# How long a media lease lasts, in seconds. Matches the CV's lease: long enough to open the
# document or start the player, short enough that a link pasted elsewhere is dead by the time
# it arrives.
MEDIA_LEASE_SECONDS = 300


def _actor_name(actor: dict) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


async def _require_candidate(company_id: str, uk: str) -> dict:
    doc = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    return doc


# ─────────────────────────────────────────────────────────────
# Ingest
# ─────────────────────────────────────────────────────────────
def _decode_recording(upload) -> tuple:
    """Validate and decode a recording upload. Returns (raw_bytes, filename, mime_type).

    A near-twin of hrms_public_guard.decode_upload and deliberately not a call to it: that
    function enforces the PUBLIC allow-list and the 15 MB public ceiling, and the whole point
    here is a different allow-list and a different ceiling. Sharing the function would mean
    widening the public one, which is the change that must never happen by accident.

    The order is the same and matters for the same reason: the declared size is bounded
    BEFORE decoding, so an oversized payload is refused without being materialised.
    """
    def field(key: str) -> str:
        if isinstance(upload, dict):
            return upload.get(key) or ""
        return getattr(upload, key, "") or ""

    data = field("data")
    name = (field("name") or "recording").strip()[:180]
    mime = field("mime_type").strip().lower()

    if mime not in ALLOWED_RECORDING_MIME:
        raise HTTPException(
            status_code=415,
            detail=("That file type is not accepted for a recording. Use MP4, WebM, MOV or "
                    "an audio file — or paste the meeting platform's recording link instead."))

    if "," in data[:120] and data[:5].lower() == "data:":
        data = data.split(",", 1)[1]

    limit_mb = MAX_RECORDING_BYTES // 1024 // 1024
    too_big = (f"That recording is larger than {limit_mb} MB. Paste the meeting platform's "
               f"recording link instead — that is what the link field is for.")
    if len(data) > (MAX_RECORDING_BYTES * 4 // 3) + 1024:
        raise HTTPException(status_code=413, detail=too_big)

    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="That recording could not be read.")
    if not raw:
        raise HTTPException(status_code=400, detail="That recording is empty.")
    if len(raw) > MAX_RECORDING_BYTES:
        raise HTTPException(status_code=413, detail=too_big)

    return raw, safe_filename(name), mime


def _clean_url(value: Optional[str]) -> Optional[str]:
    """A recording link, or None. Rejects anything that is not an http(s) URL.

    `javascript:` and `data:` are the reason this is a scheme check rather than a length
    check: the value is rendered as an anchor in two UIs, one of which is shown to a user
    outside this company.
    """
    text = clean_text(value, limit=2000)
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.netloc:
        raise HTTPException(
            status_code=422,
            detail="That does not look like a recording link. It should start with https://")
    return text


async def _store(raw: bytes, name: str, mime: str, prefix: str) -> dict:
    from app.services.s3_service import upload_file_to_s3_with_key
    try:
        result = upload_file_to_s3_with_key(_io.BytesIO(raw), f"{prefix}_{name}", mime)
    except Exception as e:
        print(f"[WARN] HRMS interview media upload failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="That file could not be uploaded right now. Please try again.")
    return {"name": name,
            "key": result.get("key") if isinstance(result, dict) else None,
            "mime_type": mime,
            "size_bytes": len(raw)}


# ─────────────────────────────────────────────────────────────
# Writes
# ─────────────────────────────────────────────────────────────
async def file_report(actor: dict, company_id: str, uk: str, payload: dict) -> dict:
    """File the interview report against a candidate, replacing any previous one.

    Replacing keeps the old record in `interview_report_history` rather than overwriting it
    blind, for the reason `upload_cv` does the same: an earlier version may already have gone
    to a client, and a share pointing at a document nobody can produce is worse than one
    carrying a superseded version.
    """
    await _require_candidate(company_id, uk)

    upload = payload.get("file")
    if not upload:
        raise HTTPException(status_code=422, detail="Attach the interview report.")
    raw, name, mime = decode_upload(upload, label="Interview report")
    if not raw:
        raise HTTPException(status_code=422, detail="That file could not be read.")
    stored = await _store(raw, name, mime, f"interview_report_{uk}")

    now = datetime.now(timezone.utc)
    record = {**stored,
              "summary": clean_text(payload.get("summary"), limit=4000),
              "filed_at": now,
              "filed_by": str((actor or {}).get("_id") or ""),
              "filed_by_name": _actor_name(actor)}
    await _replace_media(company_id, uk, REPORT, record, now, actor)

    await audit(actor, AUDIT_INTERVIEW_REPORT_FILED, ENTITY_CANDIDATE, uk,
                f"interview report filed: {name}", company_id)
    return {"ok": True, "kind": REPORT, "report": _public(record)}


async def file_recording(actor: dict, company_id: str, uk: str, payload: dict) -> dict:
    """File the recording — an uploaded file OR a link, never both and never neither."""
    await _require_candidate(company_id, uk)

    upload = payload.get("file")
    url = _clean_url(payload.get("url"))
    if upload and url:
        # Refused rather than silently preferring one: two sources on one record means the
        # client watches whichever the reader happened to pick, and nobody can say which was
        # the real call.
        raise HTTPException(
            status_code=422,
            detail="Attach a recording file or paste a link — not both.")
    if not upload and not url:
        raise HTTPException(
            status_code=422,
            detail="Attach the recording, or paste the meeting platform's link.")

    now = datetime.now(timezone.utc)
    duration = payload.get("duration_min")
    try:
        duration = int(duration) if duration not in (None, "") else None
    except (TypeError, ValueError):
        duration = None

    record = {
        "title": clean_text(payload.get("title"), limit=200),
        "duration_min": duration,
        "filed_at": now,
        "filed_by": str((actor or {}).get("_id") or ""),
        "filed_by_name": _actor_name(actor),
    }
    if url:
        record.update({"source": "link", "url": url, "key": None, "name": None})
    else:
        raw, name, mime = _decode_recording(upload)
        record.update({"source": "file", "url": None,
                       **await _store(raw, name, mime, f"interview_rec_{uk}")})

    await _replace_media(company_id, uk, RECORDING, record, now, actor)
    await audit(actor, AUDIT_INTERVIEW_RECORDING_FILED, ENTITY_CANDIDATE, uk,
                f"interview recording filed ({record['source']})", company_id)
    return {"ok": True, "kind": RECORDING, "recording": _public(record)}


async def _replace_media(company_id: str, uk: str, kind: str, record: dict,
                         now: datetime, actor: dict) -> None:
    """Write one media record, archive whatever it replaced, and refresh live shares."""
    field = MEDIA_FIELD[kind]
    current = await _require_candidate(company_id, uk)
    previous = current.get(field)

    update = {"$set": {field: record, "updated_at": now}}
    if previous and (previous.get("key") or previous.get("url")):
        update["$push"] = {f"{field}_history": {
            **previous, "replaced_at": now,
            "replaced_by": str((actor or {}).get("_id") or "")}}

    await get_collection(COLL_CANDIDATES).update_one(
        {"uk": uk, "company_id": str(company_id)}, update)
    await _refresh_shares(company_id, uk)


async def remove_media(actor: dict, company_id: str, uk: str, kind: str) -> dict:
    """Unpublish the report or the recording.

    The stored object is NOT deleted, only unlinked. A client may already have been shown it,
    and the audit trail's answer to "what did they see" has to keep resolving — the same
    reason a withdrawn share keeps its row instead of vanishing.
    """
    if kind not in MEDIA_FIELD:
        raise HTTPException(status_code=422, detail="Unknown interview record type.")
    field = MEDIA_FIELD[kind]
    current = await _require_candidate(company_id, uk)
    if not current.get(field):
        raise HTTPException(status_code=404, detail=f"No interview {kind} is on file.")

    now = datetime.now(timezone.utc)
    await get_collection(COLL_CANDIDATES).update_one(
        {"uk": uk, "company_id": str(company_id)},
        {"$set": {field: None, "updated_at": now},
         "$push": {f"{field}_history": {**current[field], "removed_at": now,
                                        "removed_by": str((actor or {}).get("_id") or "")}}})
    await _refresh_shares(company_id, uk)
    await audit(actor, AUDIT_INTERVIEW_MEDIA_REMOVED, ENTITY_CANDIDATE, uk,
                f"interview {kind} removed", company_id)
    return {"ok": True, "kind": kind}


# ─────────────────────────────────────────────────────────────
# Propagation to live shares
# ─────────────────────────────────────────────────────────────
# A share carries a SNAPSHOT taken when the CV was sent, and that is the module's central
# safety property: a field added to a candidate later can never retroactively reach a client
# who was sent a CV last month (see hrms_share_service's docstring).
#
# The interview record is the one thing that must nonetheless reach an existing share, and
# the reason is the ordering of the real process: a CV goes out, the client asks to see the
# person, the interview happens afterwards. If the snapshot could never be updated, the
# interview report would only ever reach clients who were sent the CV after it existed —
# which is nearly none of them.
#
# So this is a NARROW, explicit exception rather than a hole: exactly the interview keys,
# written by Sparsh's own deliberate act of filing the material, onto shares that are still
# live. It is not a general "re-sync the snapshot" path, and it must not become one.
async def _refresh_shares(company_id: str, uk: str) -> None:
    candidate = await _require_candidate(company_id, uk)
    patch = interview_snapshot(candidate)
    await get_collection(COLL_CANDIDATE_SHARES).update_many(
        {"company_id": str(company_id), "uk": uk,
         # A withdrawn share is over. Pushing new material onto one would hand a client
         # something after we took the candidate back from them.
         "status": {"$ne": ShareStatus.WITHDRAWN.value}},
        {"$set": {f"snapshot.{k}": v for k, v in patch.items()}})


def interview_snapshot(candidate: dict) -> dict:
    """The interview keys of a share snapshot, from a candidate document.

    One function, called both when a share is first built and whenever material is filed
    afterwards, so a share created today and one refreshed today cannot disagree about what
    the snapshot's shape is.

    Keys only — never a signed URL. A URL expires, so persisting one would leave a dead link
    on the share; the client asks for a fresh one and that request is separately authorised
    and separately audited.
    """
    report = candidate.get("interview_report") or {}
    recording = candidate.get("interview_recording") or {}
    return {
        "interview_report_key": report.get("key"),
        "interview_report_name": report.get("name"),
        # The summary IS meant for the client — it is the line they read before deciding
        # whether to open the full report.
        "interview_report_summary": report.get("summary"),
        "interview_recording_key": recording.get("key"),
        "interview_recording_url": recording.get("url"),
        "interview_recording_title": recording.get("title"),
        "interview_recording_duration_min": recording.get("duration_min"),
    }


# ─────────────────────────────────────────────────────────────
# Sparsh-side reads
# ─────────────────────────────────────────────────────────────
def _public(record: dict) -> dict:
    """One media record as an API response. The S3 key never leaves the server."""
    out = {k: v for k, v in (record or {}).items() if k != "key"}
    out["has_file"] = bool((record or {}).get("key"))
    return out


async def get_media(actor: dict, company_id: str, uk: str) -> dict:
    """Both records for a candidate, for Sparsh's own screens."""
    candidate = await _require_candidate(company_id, uk)
    return {
        "uk": uk,
        "report": _public(candidate.get("interview_report")) if candidate.get("interview_report") else None,
        "recording": _public(candidate.get("interview_recording")) if candidate.get("interview_recording") else None,
    }


async def media_url(actor: dict, company_id: str, uk: str, kind: str) -> dict:
    """A short-lived link to one record, for a Sparsh-side reader.

    Inline for both: this is the "open it and look" path. Sparsh's own download of a report
    is the browser's save button on a rendered document, which needs no separate route.
    """
    if kind not in MEDIA_FIELD:
        raise HTTPException(status_code=422, detail="Unknown interview record type.")
    candidate = await _require_candidate(company_id, uk)
    record = candidate.get(MEDIA_FIELD[kind]) or {}

    if record.get("url"):
        return {"url": record["url"], "source": "link", "expires_in": None}
    key = record.get("key")
    if not key:
        raise HTTPException(status_code=404, detail=f"No interview {kind} is on file.")

    from app.services.s3_service import get_signed_url
    url = get_signed_url(key, expires_in=MEDIA_LEASE_SECONDS)
    if not url:
        raise HTTPException(
            status_code=503,
            detail="That could not be opened right now. Please try again.")
    return {"url": url, "source": "file", "expires_in": MEDIA_LEASE_SECONDS,
            "mime_type": record.get("mime_type"), "name": record.get("name")}

