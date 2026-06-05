"""The agent loop — the conductor.

Phase 1 flow (no memory/rewriter/analytics yet):

    user message
      → build system prompt (persona + grounding rules)
      → expose only the role-permitted tool schema to the model
      → tool-calling loop (bounded by MAX_TOOL_ITERATIONS):
            model picks tool(s) → execute_tool() (timeout + error isolation)
            → feed compact results back → repeat
      → model produces the final conversational answer

The orchestrator is injected with an LLMClient (overridable in tests with a fake).
"""
from __future__ import annotations

import json
from typing import List, Optional

from app.assistant.config import config
from app.assistant.core.llm_client import LLMClient
from app.assistant.core.prompt_builder import build_system_prompt
from app.assistant.schemas.chat import AskResponse
from app.assistant.schemas.context import UserContext
from app.assistant.tools import registry


class Orchestrator:
    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()
        # Ensure all domain tools are registered (idempotent — imports are cached).
        registry.register_all()

    async def handle_message(
        self,
        ctx: UserContext,
        message: str,
        conversation_id: Optional[str] = None,
    ) -> AskResponse:
        system_prompt = build_system_prompt(ctx)
        tool_schema = registry.openai_schema_for_role(ctx.role)

        messages: List[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ]

        sources: set = set()
        tools_used: List[str] = []

        for _ in range(config.MAX_TOOL_ITERATIONS):
            ai_msg = await self.llm.complete(messages, tools=tool_schema or None)
            tool_calls = getattr(ai_msg, "tool_calls", None)

            # No tool calls → the model produced the final answer.
            if not tool_calls:
                return self._respond(
                    conversation_id, ai_msg.content or "", sources, tools_used
                )

            # Echo the assistant's tool-call message back into the transcript.
            messages.append(
                {
                    "role": "assistant",
                    "content": ai_msg.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in tool_calls
                    ],
                }
            )

            # Execute each requested tool with isolation + timeout, feed results back.
            for call in tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                spec = registry.get_tool(name)
                if spec is None:
                    result_payload = {"success": False, "error": "Unknown tool"}
                else:
                    result = await registry.execute_tool(spec, ctx, args)
                    tools_used.append(name)
                    if result.meta.sources:
                        sources.update(result.meta.sources)
                    result_payload = result.for_llm()

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result_payload, default=str),
                    }
                )

        # Exhausted the iteration budget without a final answer.
        return self._respond(
            conversation_id,
            "I wasn't able to finish answering that within the allowed steps. "
            "Could you rephrase or narrow the question?",
            sources,
            tools_used,
        )

    @staticmethod
    def _respond(
        conversation_id: Optional[str],
        answer: str,
        sources: set,
        tools_used: List[str],
    ) -> AskResponse:
        return AskResponse(
            conversation_id=conversation_id or "ephemeral",
            answer=answer,
            sources=sorted(sources),
            meta={"phase": "1-mvp", "tools_used": tools_used},
        )
