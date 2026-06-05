"""LLM provider abstraction.

Wraps the OpenAI client (the project already uses AsyncOpenAI in gpt_service.py)
behind a stable interface so models/providers can be swapped. No network calls
are made in Phase 0.
"""
from __future__ import annotations

from typing import List, Optional


class LLMClient:
    async def complete(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        stream: bool = False,
        max_tokens: Optional[int] = None,
    ):
        """Chat completion with optional tool-calling. Phase 1."""
        raise NotImplementedError("LLMClient.complete — Phase 1")

    async def summarize(self, text: str) -> str:
        """Cheap-model summarization for titles/rolling memory. Phase 2."""
        raise NotImplementedError("LLMClient.summarize — Phase 2")
