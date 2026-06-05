"""LLM provider abstraction.

Wraps the OpenAI client (the project already uses AsyncOpenAI in gpt_service.py)
behind a stable interface so models/providers can be swapped. The SDK is imported
lazily so the module/router can be imported in environments where `openai` or the
API key are absent (e.g. unit tests of the agent loop with a fake client).
"""
from __future__ import annotations

from typing import List, Optional

from app.assistant.config import config
from app.config.settings import settings


class LLMClient:
    def __init__(self, model: Optional[str] = None):
        self.model = model or config.PRIMARY_MODEL
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import AsyncOpenAI  # lazy import

            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._client

    async def complete(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        stream: bool = False,
        max_tokens: Optional[int] = None,
    ):
        """Chat completion with optional tool-calling.

        Returns the raw OpenAI `message` object (has `.content` and `.tool_calls`).
        Streaming is a Phase 2 concern; `stream` is accepted but ignored here.
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": config.LLM_TEMPERATURE,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        response = await self.client.chat.completions.create(**kwargs)
        return response.choices[0].message

    async def summarize(self, text: str) -> str:
        """Cheap-model summarization for titles/rolling memory. Phase 2."""
        raise NotImplementedError("LLMClient.summarize — Phase 2")
