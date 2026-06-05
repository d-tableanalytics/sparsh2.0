"""Role-filtered tool registry.

Tools self-register with `@tool(...)`. The orchestrator asks the registry for
the subset a caller's role may use (`tools_for_role`) and the matching OpenAI
schema (`openai_schema_for_role`). Exposing only permitted tools is both a
security control and a token/accuracy optimization.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.assistant.security.rbac import normalize_role
from app.assistant.tools.base import ToolSpec

# Global registry: tool name → spec.
_REGISTRY: Dict[str, ToolSpec] = {}


def tool(
    name: str,
    description: str,
    allowed_roles: List[str],
    parameters: Optional[Dict[str, Any]] = None,
    required: Optional[List[str]] = None,
):
    """Decorator registering an async handler as a tool.

    Example (implemented from Phase 1):

        @tool(
            name="get_my_attendance",
            description="Return the caller's attendance records.",
            allowed_roles=["CU", "CA"],
            parameters={"limit": {"type": "integer"}},
        )
        async def get_my_attendance(ctx, limit=50): ...
    """

    def decorator(func):
        _REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters or {},
            allowed_roles=allowed_roles,
            handler=func,
            required=required or [],
        )
        return func

    return decorator


def get_tool(name: str) -> Optional[ToolSpec]:
    return _REGISTRY.get(name)


def all_tools() -> List[ToolSpec]:
    return list(_REGISTRY.values())


def tools_for_role(role: Optional[str]) -> List[ToolSpec]:
    """Subset of tools the given system role is allowed to call."""
    level = normalize_role(role)
    return [t for t in _REGISTRY.values() if level in t.allowed_roles]


def openai_schema_for_role(role: Optional[str]) -> List[dict]:
    """OpenAI function-calling schema for the role-permitted tools."""
    return [t.openai_schema() for t in tools_for_role(role)]


def register_all() -> None:
    """Import every domain tool module so decorators run.

    Phase 0: domain modules are empty, so this is a no-op import barrier. As
    tools are added, importing the package here ensures they self-register.
    """
    from app.assistant.tools import admin, shared, student, teacher  # noqa: F401
