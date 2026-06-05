"""Mongo document → clean, whitelisted dict.

Never serialize secrets (password hashes, tokens). Phase 0 stub; concrete
per-entity serializers land with the tools in Phase 1.
"""
from __future__ import annotations

from typing import Dict

# Fields that must never be returned to the model or the user.
SENSITIVE_FIELDS = {"password", "hashed_password", "password_hash", "token", "otp"}


def strip_sensitive(doc: Dict) -> Dict:
    """Remove always-sensitive fields. Safe, used by future serializers."""
    return {k: v for k, v in (doc or {}).items() if k not in SENSITIVE_FIELDS}


def serialize(doc: Dict, allowed_fields) -> Dict:
    """Project a Mongo doc to a whitelisted set of fields. Phase 1."""
    raise NotImplementedError("serializers.serialize — Phase 1")
