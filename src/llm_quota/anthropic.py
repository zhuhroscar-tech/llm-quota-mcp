"""Anthropic quota probe.

Anthropic does not publish an account-wide "tokens remaining this billing
period" endpoint for API keys (that figure lives only in the Console UI /
the org-level Usage & Cost Admin API, which requires a separate admin key
type not available to a normal API key). What *is* available on every
authenticated response is a set of per-request-window rate-limit headers:

    anthropic-ratelimit-requests-limit
    anthropic-ratelimit-requests-remaining
    anthropic-ratelimit-requests-reset
    anthropic-ratelimit-input-tokens-limit
    anthropic-ratelimit-input-tokens-remaining
    anthropic-ratelimit-input-tokens-reset
    anthropic-ratelimit-output-tokens-limit
    anthropic-ratelimit-output-tokens-remaining
    anthropic-ratelimit-output-tokens-reset
    anthropic-ratelimit-tokens-limit          (combined, on some tiers)
    anthropic-ratelimit-tokens-remaining
    anthropic-ratelimit-tokens-reset
    retry-after                               (only present on 429s)

These headers reflect your *current rate-limit window* (requests/tokens
per minute, tier-dependent), not a monthly budget. This module surfaces
exactly what the API returns, with the raw reset value preserved as-is
(Anthropic documents it as an RFC 3339 timestamp, but we defensively parse
and fall back to the raw string if parsing fails, since the exact format
has changed across API versions).

We fetch these headers via POST /v1/messages/count_tokens, which is
documented as free of token/usage charges (it only tokenizes your input),
so calling this probe does not consume your paid quota, though it does
still count against the requests-per-minute rate limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

ANTHROPIC_API_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_PROBE_MODEL = "claude-3-5-haiku-20241022"


@dataclass
class RateLimitWindow:
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset_raw: Optional[str] = None
    reset_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_raw": self.reset_raw,
            "reset_at": self.reset_at.isoformat() if self.reset_at else None,
        }


@dataclass
class AnthropicQuota:
    requests: RateLimitWindow = field(default_factory=RateLimitWindow)
    input_tokens: RateLimitWindow = field(default_factory=RateLimitWindow)
    output_tokens: RateLimitWindow = field(default_factory=RateLimitWindow)
    tokens: RateLimitWindow = field(default_factory=RateLimitWindow)
    retry_after_seconds: Optional[float] = None
    rate_limited: bool = False
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    note: str = (
        "Anthropic exposes per-minute rate-limit windows via response headers, "
        "not an account-wide remaining-token/expiration balance. These figures "
        "are the current requests/tokens-per-minute window and its reset time, "
        "not a monthly quota."
    )

    def to_dict(self) -> dict:
        return {
            "provider": "anthropic",
            "requests": self.requests.to_dict(),
            "input_tokens": self.input_tokens.to_dict(),
            "output_tokens": self.output_tokens.to_dict(),
            "tokens": self.tokens.to_dict(),
            "retry_after_seconds": self.retry_after_seconds,
            "rate_limited": self.rate_limited,
            "checked_at": self.checked_at.isoformat(),
            "note": self.note,
        }


def _parse_reset(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        # RFC 3339 / ISO 8601, e.g. "2024-01-01T00:00:00Z"
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _window(headers: dict, prefix: str) -> RateLimitWindow:
    def _int(key: str) -> Optional[int]:
        v = headers.get(key)
        if v is None:
            return None
        try:
            return int(v)
        except ValueError:
            return None

    reset_raw = headers.get(f"{prefix}-reset")
    return RateLimitWindow(
        limit=_int(f"{prefix}-limit"),
        remaining=_int(f"{prefix}-remaining"),
        reset_raw=reset_raw,
        reset_at=_parse_reset(reset_raw),
    )


def get_anthropic_quota(
    api_key: str,
    model: str = DEFAULT_PROBE_MODEL,
    timeout: float = 15.0,
    session: Optional[requests.Session] = None,
) -> AnthropicQuota:
    """Probe Anthropic's rate-limit headers via a free count_tokens call.

    Raises requests.HTTPError for auth failures (401) or other non-429 errors.
    A 429 (rate limited) is NOT raised — it is captured in the returned
    AnthropicQuota (rate_limited=True, retry_after_seconds set) since that is
    itself useful quota information, not a tool failure.
    """
    sess = session or requests.Session()
    resp = sess.post(
        f"{ANTHROPIC_API_BASE}/v1/messages/count_tokens",
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": "quota probe"}],
        },
        timeout=timeout,
    )

    headers = {k.lower(): v for k, v in resp.headers.items()}
    quota = AnthropicQuota(
        requests=_window(headers, "anthropic-ratelimit-requests"),
        input_tokens=_window(headers, "anthropic-ratelimit-input-tokens"),
        output_tokens=_window(headers, "anthropic-ratelimit-output-tokens"),
        tokens=_window(headers, "anthropic-ratelimit-tokens"),
    )

    if resp.status_code == 429:
        quota.rate_limited = True
        retry_after = headers.get("retry-after")
        if retry_after is not None:
            try:
                quota.retry_after_seconds = float(retry_after)
            except ValueError:
                pass
        return quota

    if resp.status_code == 401:
        raise requests.HTTPError(
            "Anthropic API key was rejected (401 Unauthorized). "
            "Check ANTHROPIC_API_KEY.",
            response=resp,
        )

    resp.raise_for_status()
    return quota
