"""Role-filtered tool registry.

Tools self-register with `@tool(...)`. The orchestrator asks the registry for
the subset a caller's role may use (`tools_for_role`) and the matching OpenAI
schema (`openai_schema_for_role`). Exposing only permitted tools is both a
security control and a token/accuracy optimization.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from app.assistant.config import config
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
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


async def execute_tool(
    spec: ToolSpec,
    ctx: UserContext,
    arguments: Dict[str, Any],
    timeout: Optional[float] = None,
) -> ToolResult:
    """Run a tool with cross-cutting protections.

    1. **Timeout** — the handler is bounded by `timeout` (defaults to
       AssistantConfig.TOOL_TIMEOUT_SECONDS); a slow tool yields a failure, not a hang.
    2. **Error isolation** — any exception (bad args, DB error, bug) is caught and
       converted to a `ToolResult.fail`, so one broken tool never breaks the
       orchestrator's agent loop.

    Role enforcement is defense-in-depth: even though the model only sees tools
    permitted for its role, we re-check here before executing.
    """
    timeout = timeout if timeout is not None else config.TOOL_TIMEOUT_SECONDS

    if normalize_role(ctx.role) not in spec.allowed_roles:
        return ToolResult.fail(spec.name, "Tool not permitted for this role")

    try:
        return await asyncio.wait_for(spec.run(ctx, **arguments), timeout=timeout)
    except asyncio.TimeoutError:
        return ToolResult.fail(spec.name, f"Tool timed out after {timeout}s")
    except TypeError as exc:
        # Almost always bad/extra arguments hallucinated by the model.
        return ToolResult.fail(spec.name, f"Invalid arguments: {exc}")
    except Exception as exc:  # noqa: BLE001 — deliberate catch-all for isolation
        return ToolResult.fail(spec.name, f"Tool execution error: {exc}")


def register_all() -> None:
    """Import every domain tool module so decorators run.

    Phase 0: domain modules are empty, so this is a no-op import barrier. As
    tools are added, importing the package here ensures they self-register.
    """
    from app.assistant.tools import admin, shared, student, teacher  # noqa: F401
