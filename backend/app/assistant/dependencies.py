"""FastAPI dependencies for the assistant.

`get_user_context` builds a UserContext from the authenticated user once per
request. Tools receive this object and derive their scope from it — the LLM never
passes identity arguments.
"""
from __future__ import annotations

from fastapi import Depends

from app.assistant.schemas.context import UserContext
from app.controllers.auth_controller import get_current_user


def build_user_context(current_user: dict) -> UserContext:
    """Derive a UserContext from a raw user document (staff/learners)."""
    # Normalize batch references — the codebase stores both `batch_ids` (list)
    # and a singular `batch_id` (see gpt.py access logic).
    batch_ids = current_user.get("batch_ids") or []
    if not isinstance(batch_ids, list):
        batch_ids = [batch_ids]
    single_batch = current_user.get("batch_id")
    if single_batch and single_batch not in batch_ids:
        batch_ids.append(single_batch)

    company_id = current_user.get("company_id")

    return UserContext(
        user_id=str(current_user.get("_id")),
        email=current_user.get("email"),
        full_name=current_user.get("full_name") or current_user.get("email"),
        role=current_user.get("role", "clientuser"),
        tag=current_user.get("tag"),
        company_id=str(company_id) if company_id else None,
        batch_ids=[str(b) for b in batch_ids if b],
        course_ids=[],  # quarters resolved from batch_ids in Phase 1+
        permissions=current_user.get("permissions") or {},
    )


async def get_user_context(
    current_user: dict = Depends(get_current_user),
) -> UserContext:
    return build_user_context(current_user)
