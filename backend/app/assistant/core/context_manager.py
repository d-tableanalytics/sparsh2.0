"""Conversation context windowing.

Builds the bounded message window sent to the LLM: the rolling summary (if any)
followed by the last `MAX_WINDOW_MESSAGES` user/assistant turns. Tool/system
messages from history are not replayed.
"""
from __future__ import annotations

import re
from typing import List

from app.assistant.config import config
from app.assistant.schemas.conversation import Conversation

# Matches: [File: name.ext]\n<extracted body up to the next [ or end>
_FILE_BODY_RE = re.compile(
    r'(\[File(?:\s+attached)?:\s*[^\]\n]+\])\n[^\[]+',
    re.DOTALL,
)


def _strip_file_bodies(content: str) -> str:
    """Drop extracted file text from history turns.

    The first time a file is processed the LLM needs its content, but in every
    subsequent turn replaying those 2000 chars causes the model to fixate on
    the old file instead of the new message. Keep only the [File: name] tag.
    """
    return _FILE_BODY_RE.sub(r'\1\n', content).strip()


def build_window(conversation: Conversation) -> List[dict]:
    """Return prior-turn messages (summary + recent) for prompt assembly."""
    window: List[dict] = []

    if conversation.summary:
        window.append(
            {
                "role": "system",
                "content": f"Summary of the earlier conversation:\n{conversation.summary}",
            }
        )

    recent = conversation.messages[-config.MAX_WINDOW_MESSAGES:]
    for msg in recent:
        if msg.role in ("user", "assistant"):
            content = _strip_file_bodies(msg.content) if msg.role == "user" else msg.content
            window.append({"role": msg.role, "content": content})

    return window


def needs_summary(conversation: Conversation) -> bool:
    """True when the transcript has grown past the summarization trigger."""
    return len(conversation.messages) > config.SUMMARY_TRIGGER
