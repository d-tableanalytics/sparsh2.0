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
    TOOL_TIMEOUT_SECONDS: float = 8.0    # per-tool execution timeout (cross-cutting)
    LLM_TEMPERATURE: float = 0.3

    # Conversation memory / windowing (Phase 2).
    MAX_WINDOW_MESSAGES: int = 10        # recent user/assistant messages sent to the LLM
    SUMMARY_TRIGGER: int = 14            # message_count above which older turns are summarized
    CONVERSATION_LIST_LIMIT: int = 50

    # ── Phase 4: production hardening ─────────────────────────────────────
    # Feature flags.
    STREAMING_ENABLED: bool = True
    RAG_ENABLED: bool = True
    ANALYTICS_ENABLED: bool = True
    GUARDRAILS_ENABLED: bool = True

    # Rollout controls.
    ENABLED_ROLES: list = []             # empty = all roles; else raw role strings
    ROLLOUT_MODE: str = "all"            # all | allowlist | percentage
    ROLLOUT_ALLOWLIST: list = []         # user_ids or emails
    ROLLOUT_PERCENT: int = 100           # used when ROLLOUT_MODE == "percentage"

    # Rate limiting (per user).
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_MAX: int = 30             # requests...
    RATE_LIMIT_WINDOW: float = 60.0      # ...per this many seconds

    # Caching TTLs (seconds).
    CACHE_METADATA_TTL: float = 300.0    # accessible projects, profile-ish metadata
    CACHE_ANALYTICS_TTL: float = 60.0    # analytics results
    CACHE_KNOWLEDGE_TTL: float = 120.0   # knowledge retrieval results

    # Cost reporting.
    COST_REPORTING_ENABLED: bool = True
    COST_COLLECTION: str = "assistant_cost"
    METRICS_COLLECTION: str = "assistant_metrics"

    # Persistence.
    CONVERSATION_COLLECTION: str = "assistant_conversations"

    # Response sizing defaults (response_formatter refines per query, Phase 2/3).
    SHORT_ANSWER_MAX_TOKENS: int = 200
    LONG_ANSWER_MAX_TOKENS: int = 1200


config = AssistantConfig()
