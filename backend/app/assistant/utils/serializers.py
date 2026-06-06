"""Mongo document → clean, whitelisted dict.

Never serialize secrets (password hashes, tokens). Phase 0 stub; concrete
per-entity serializers land with the tools in Phase 1.
"""
from __future__ import annotations

from typing import Dict

from bson import ObjectId

# Fields that must never be returned to the model or the user.
SENSITIVE_FIELDS = {"password", "hashed_password", "password_hash", "token", "otp"}


def strip_sensitive(doc: Dict) -> Dict:
    """Remove always-sensitive fields. Safe, used by future serializers."""
    return {k: v for k, v in (doc or {}).items() if k not in SENSITIVE_FIELDS}


def serialize(doc: Dict, allowed_fields) -> Dict:
    """Project a Mongo doc to a whitelisted set of fields.

    - Only `allowed_fields` are returned (plus a stringified `id` from `_id`).
    - Always-sensitive fields are dropped even if explicitly allowed.
    - `ObjectId` values are stringified so the result is JSON-serializable.
    """
    if not doc:
        return {}

    out: Dict = {}
    if "_id" in doc:
        out["id"] = str(doc["_id"])

    for field in allowed_fields:
        if field in SENSITIVE_FIELDS or field not in doc:
            continue
        value = doc[field]
        out[field] = str(value) if isinstance(value, ObjectId) else value

    return strip_sensitive(out)
