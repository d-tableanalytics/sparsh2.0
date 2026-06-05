"""Module configuration for the AI Assistant.

Values here are intentionally static for Phase 0. Secrets (e.g. OpenAI key) are
read from app.config.settings when the LLM layer is wired in Phase 1.
"""


class AssistantConfig:
    # Feature flag — lets ops disable the assistant without removing the router.
    ENABLED: bool = True

    # Model tiers (used from Phase 1 onward; no calls are made in Phase 0).
    PRIMARY_MODEL: str = "gpt-4o"        # reasoning + final answers
    UTILITY_MODEL: str = "gpt-4o-mini"   # query rewriting, summaries, titles

    # Agent loop guards.
    MAX_TOOL_ITERATIONS: int = 5         # safety cap on tool-calling rounds
    MAX_HISTORY_TURNS: int = 10          # turns sent to the LLM before summarizing
    TOOL_TIMEOUT_SECONDS: float = 8.0    # per-tool execution timeout (cross-cutting)
    LLM_TEMPERATURE: float = 0.3

    # Persistence.
    CONVERSATION_COLLECTION: str = "assistant_conversations"

    # Response sizing defaults (response_formatter refines per query, Phase 2/3).
    SHORT_ANSWER_MAX_TOKENS: int = 200
    LONG_ANSWER_MAX_TOKENS: int = 1200


config = AssistantConfig()
