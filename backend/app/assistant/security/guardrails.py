"""Prompt-injection screening and output validation.

Phase 0 stub — real logic lands in Phase 4. The scope-enforcement guarantee
(ScopeFilter) is the primary protection; guardrails are defense-in-depth.
"""
from __future__ import annotations


def screen_input(message: str) -> None:
    """Raise/flag if the input looks like a prompt-injection attempt. Phase 4."""
    raise NotImplementedError("guardrails.screen_input — Phase 4")


def validate_output(answer: str) -> str:
    """Validate the model answer (leak/PII/structure checks) before return. Phase 4."""
    raise NotImplementedError("guardrails.validate_output — Phase 4")
