"""llm_quota — track remaining LLM API quota, rate limits, and reset times.

Supports:
  - Anthropic: live rate-limit headers via a free /v1/messages/count_tokens probe.
  - OpenAI: live rate-limit headers via a minimal (1 max_tokens) chat completion probe,
    plus optional organization Usage/Costs API totals if an admin key is supplied.
  - Hermes: local session-store token/cost totals via the `hermes sessions export` CLI
    (no network call — reads what Hermes already tracked about its own usage).

This package intentionally does NOT invent numbers: if a provider doesn't expose a
field (e.g. Anthropic has no account-wide "tokens remaining this month" endpoint,
only per-request-window rate-limit headers), the corresponding field is left as
`None` with a note explaining why, rather than guessing.
"""

from .anthropic import AnthropicQuota, get_anthropic_quota
from .openai import OpenAIQuota, get_openai_quota
from .hermes import HermesUsage, get_hermes_usage

__all__ = [
    "AnthropicQuota",
    "get_anthropic_quota",
    "OpenAIQuota",
    "get_openai_quota",
    "HermesUsage",
    "get_hermes_usage",
]

__version__ = "0.1.1"
