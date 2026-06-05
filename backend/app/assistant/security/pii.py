"""PII protection helpers.

Phase 0 stub. Whitelisting happens primarily in utils/serializers.py; this module
adds output-side redaction in Phase 4.
"""
from __future__ import annotations


def redact(text: str) -> str:
    """Redact PII patterns from free text before returning to the user. Phase 4."""
    raise NotImplementedError("pii.redact — Phase 4")
