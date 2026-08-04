"""Public link registry — find a link again, and see whether it was used.

Every public link the HRMS issues gets a row here: what it is for, who created it, when it
expires, how often it has been opened, and whether it has been spent. That is the "trackable
and easily accessible" the review document asks for.

The design point worth stating plainly: **this registry does not store access codes.** Codes
live where they always have — embedded on the posting or candidate document — so there remains
exactly one copy of each secret. A registry row is a pointer plus tracking. Revealing a code
reads it from its real home through `resolve_code` and records who looked, which is what lets
"accessible whenever required" coexist with the existing rule that no list endpoint ever
returns a code (see hrms_candidate_service's module docstring on why that rule exists).

Registration and tracking are best-effort throughout: failing to log a link must never stop
the link from being issued, and failing to count an open must never stop a candidate opening
their offer.
"""
import logging
from datetime import datetime, timezone, date
from typing import Optional

from app.db.mongodb import get_collection
from app.models.hrms import (
    COL_LINKS, COL_POSTINGS, COL_CANDIDATES,
    LINK_TYPES, LINK_PATHS,
    LINK_POSTING, LINK_ASSESSMENT, LINK_OFFER, LINK_APPOINTMENT, LINK_ONBOARDING,
    LINK_ACTIVE, LINK_USED, LINK_EXPIRED, LINK_REVOKED,
)

logger = logging.getLogger(__name__)


async def register_link(link_type: str, *, code: str, owner_ref: str = "",
                        candidate_uk: str = "", candidate_name: str = "",
                        request_no: str = "", label: str = "",
                        expires_on: Optional[str] = None, actor: Optional[dict] = None) -> None:
    """Record that a link was issued.

    `code` is used only to locate the row later (it is stored as `code_ref`, the same value the
    embedded document holds) — this is a lookup key for an internal registry, not a second copy
    of the secret in a place the first one is not.

    Re-registering the same code updates the existing row rather than duplicating it, so
    regenerating a letter does not leave two registry entries pointing at one link.
    """
    if link_type not in LINK_TYPES:
        logger.warning("Refusing to register unknown link type %r", link_type)
        return
    try:
        now = datetime.now(timezone.utc)
        await get_collection(COL_LINKS).update_one(
            {"code_ref": code},
            {
                "$set": {
                    "link_type": link_type,
                    "code_ref": code,
                    "owner_ref": owner_ref,
                    "candidate_uk": candidate_uk,
                    "candidate_name": candidate_name,
                    "request_no": request_no,
                    "label": label,
                    "expires_on": expires_on,
                    "status": LINK_ACTIVE,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                    "created_by": str((actor or {}).get("_id") or ""),
                    "created_by_name": (actor or {}).get("full_name")
                                       or (actor or {}).get("email") or "",
                    "opened_count": 0,
                    "first_opened_at": None,
                    "last_opened_at": None,
                    "used_at": None,
                    "reveals": [],
                },
            },
            upsert=True,
        )
    except Exception as e:
        logger.error("Link registration failed for %s: %s", link_type, e)


async def track_open(code: str) -> None:
    """Count a public open. Best-effort: never let tracking break the candidate's page."""
    try:
        now = datetime.now(timezone.utc)
        await get_collection(COL_LINKS).update_one(
            {"code_ref": code},
            {"$inc": {"opened_count": 1},
             "$set": {"last_opened_at": now},
             "$min": {"first_opened_at": now}},
        )
    except Exception as e:
        logger.warning("Link open tracking failed: %s", e)


async def mark_used(code: str) -> None:
    """The link has been spent — application submitted, offer answered, letter acknowledged."""
    try:
        now = datetime.now(timezone.utc)
        await get_collection(COL_LINKS).update_one(
            {"code_ref": code},
            {"$set": {"status": LINK_USED, "used_at": now, "updated_at": now}},
        )
    except Exception as e:
        logger.warning("Link use tracking failed: %s", e)


def effective_status(doc: dict) -> str:
    """Stored status with expiry applied, derived at read time like document status is."""
    stored = doc.get("status") or LINK_ACTIVE
    if stored in (LINK_USED, LINK_REVOKED):
        return stored
    expires = doc.get("expires_on")
    if expires:
        try:
            if date.fromisoformat(str(expires)[:10]) < date.today():
                return LINK_EXPIRED
        except ValueError:
            pass
    return stored


def serialize_link(doc: dict) -> dict:
    """A registry row. Never includes the code — that is what the reveal endpoint is for."""
    return {
        "id": str(doc.get("_id")),
        "linkType": doc.get("link_type") or "",
        "path": LINK_PATHS.get(doc.get("link_type"), ""),
        "label": doc.get("label") or "",
        "candidateUk": doc.get("candidate_uk") or "",
        "candidateName": doc.get("candidate_name") or "",
        "requestNo": doc.get("request_no") or "",
        "status": effective_status(doc),
        "expiresOn": doc.get("expires_on"),
        "openedCount": int(doc.get("opened_count") or 0),
        "firstOpenedAt": doc.get("first_opened_at"),
        "lastOpenedAt": doc.get("last_opened_at"),
        "usedAt": doc.get("used_at"),
        "createdBy": doc.get("created_by_name") or "",
        "createdAt": doc.get("created_at"),
        "revealCount": len(doc.get("reveals") or []),
        "lastRevealedBy": (doc.get("reveals") or [{}])[-1].get("by_name") if doc.get("reveals") else "",
        "lastRevealedAt": (doc.get("reveals") or [{}])[-1].get("at") if doc.get("reveals") else None,
    }


async def resolve_code(doc: dict) -> Optional[str]:
    """Read the code from where it actually lives.

    Deliberately re-read from the source document rather than trusted from the registry row, so
    a link that was regenerated (new code on the candidate) can never be revealed as its stale
    predecessor.
    """
    link_type = doc.get("link_type")
    code_ref = doc.get("code_ref")
    try:
        if link_type == LINK_POSTING:
            row = await get_collection(COL_POSTINGS).find_one(
                {"public_code": code_ref}, {"public_code": 1})
            return (row or {}).get("public_code")

        if link_type == LINK_ASSESSMENT:
            row = await get_collection(COL_CANDIDATES).find_one(
                {"assessments.access_code": code_ref}, {"assessments": 1})
            for a in (row or {}).get("assessments") or []:
                if a.get("access_code") == code_ref:
                    return a.get("access_code")
            return None

        if link_type == LINK_OFFER:
            row = await get_collection(COL_CANDIDATES).find_one(
                {"offers.access_code": code_ref}, {"offers": 1})
            for o in (row or {}).get("offers") or []:
                if o.get("access_code") == code_ref:
                    return o.get("access_code")
            return None

        if link_type == LINK_APPOINTMENT:
            row = await get_collection(COL_CANDIDATES).find_one(
                {"appointment_letter.access_code": code_ref}, {"appointment_letter": 1})
            return ((row or {}).get("appointment_letter") or {}).get("access_code")

        if link_type == LINK_ONBOARDING:
            row = await get_collection(COL_CANDIDATES).find_one(
                {"onboarding.access_code": code_ref}, {"onboarding": 1})
            return ((row or {}).get("onboarding") or {}).get("access_code")
    except Exception as e:
        logger.error("Code resolution failed for %s: %s", link_type, e)
    return None


async def record_reveal(doc: dict, actor: dict) -> None:
    """Append to the audit trail. This one is NOT best-effort.

    If the audit write fails the caller must not hand over the code — an unlogged reveal is
    precisely the thing this design exists to prevent, so the exception propagates.
    """
    await get_collection(COL_LINKS).update_one(
        {"_id": doc["_id"]},
        {"$push": {"reveals": {
            "by": str(actor.get("_id")),
            "by_name": actor.get("full_name") or actor.get("email") or "",
            "at": datetime.now(timezone.utc),
        }}},
    )
