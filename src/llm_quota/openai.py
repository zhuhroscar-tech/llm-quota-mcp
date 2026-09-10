"""OpenAI quota probe.

Like Anthropic, OpenAI does not expose an account-wide "tokens remaining
this billing cycle" figure to a normal API key — that lives on the
platform.openai.com/usage dashboard. What a normal API key *can* see are
per-minute/per-day rate-limit headers on every response:

    x-ratelimit-limit-requests
    x-ratelimit-remaining-requests
    x-ratelimit-reset-requests
    x-ratelimit-limit-tokens
    x-ratelimit-remaining-tokens
    x-ratelimit-reset-tokens

`reset` values from OpenAI are relative durations like "6m0s" or "1s", not
timestamps — this module parses that format into a timedelta and also
computes an absolute reset_at from "now + duration" for convenience.

If the caller has a separate **organization Admin API key** (a different
credential type than a normal API key, created under Settings > Admin
keys), this module can additionally call the real usage/costs endpoints
(/v1/organization/usage/completions, /v1/organization/costs) to report
actual historical token/cost totals. This is optional and skipped
(with a note) if no admin key is supplied — we never fabricate these
numbers from the rate-limit probe alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

OPENAI_API_BASE = "https://api.openai.com"
DEFAULT_PROBE_MODEL = "gpt-4o-mini"

_DURATION_RE = re.compile(
    r"(?:(?P<days>\d+)d)?(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)s)?$"
)


@dataclass
class RateLimitWindow:
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset_raw: Optional[str] = None
    reset_seconds: Optional[float] = None
    reset_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_raw": self.reset_raw,
            "reset_seconds": self.reset_seconds,
            "reset_at": self.reset_at.isoformat() if self.reset_at else None,
        }


@dataclass
class OpenAIQuota:
    requests: RateLimitWindow = field(default_factory=RateLimitWindow)
    tokens: RateLimitWindow = field(default_factory=RateLimitWindow)
    rate_limited: bool = False
    retry_after_seconds: Optional[float] = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    org_usage: Optional[dict] = None
    note: str = (
        "OpenAI exposes per-minute rate-limit windows via response headers, "
        "not an account-wide remaining-token/expiration balance. Pass an "
        "organization Admin API key to also fetch real historical usage/cost "
        "totals from the Usage API."
    )

    def to_dict(self) -> dict:
        return {
            "provider": "openai",
            "requests": self.requests.to_dict(),
            "tokens": self.tokens.to_dict(),
            "rate_limited": self.rate_limited,
            "retry_after_seconds": self.retry_after_seconds,
            "checked_at": self.checked_at.isoformat(),
            "org_usage": self.org_usage,
            "note": self.note,
        }


def _parse_duration(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    m = _DURATION_RE.match(raw.strip())
    if not m or not any(m.groupdict().values()):
        return None
    parts = {k: float(v) if v else 0.0 for k, v in m.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def get_openai_quota(
    api_key: str,
    model: str = DEFAULT_PROBE_MODEL,
    admin_api_key: Optional[str] = None,
    organization_id: Optional[str] = None,
    timeout: float = 15.0,
    session: Optional[requests.Session] = None,
) -> OpenAIQuota:
    """Probe OpenAI's rate-limit headers via a minimal chat completion.

    Uses max_tokens=1 (or max_completion_tokens for newer models) to keep
    the probe's own cost negligible; this still consumes a small number of
    real tokens (unlike Anthropic's free count_tokens endpoint), since
    OpenAI has no free tokenize-only endpoint that returns rate-limit
    headers for chat models.
    """
    sess = session or requests.Session()
    resp = sess.post(
        f"{OPENAI_API_BASE}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": "quota probe"}],
            "max_completion_tokens": 1,
        },
        timeout=timeout,
    )

    headers = {k.lower(): v for k, v in resp.headers.items()}
    quota = OpenAIQuota(
        requests=_window_openai_requests(headers),
        tokens=_window_openai_tokens(headers),
    )

    if resp.status_code == 429:
        quota.rate_limited = True
        retry_after = headers.get("retry-after")
        if retry_after is not None:
            try:
                quota.retry_after_seconds = float(retry_after)
            except ValueError:
                pass
    elif resp.status_code == 401:
        raise requests.HTTPError(
            "OpenAI API key was rejected (401 Unauthorized). Check OPENAI_API_KEY.",
            response=resp,
        )
    else:
        resp.raise_for_status()

    if admin_api_key:
        quota.org_usage = _fetch_org_usage(admin_api_key, organization_id, timeout, sess)

    return quota


def _window_openai_requests(headers: dict) -> RateLimitWindow:
    def _int(key: str) -> Optional[int]:
        v = headers.get(key)
        return int(v) if v is not None and v.isdigit() else None

    reset_raw = headers.get("x-ratelimit-reset-requests")
    reset_seconds = _parse_duration(reset_raw)
    reset_at = (
        datetime.now(timezone.utc) + timedelta(seconds=reset_seconds)
        if reset_seconds is not None
        else None
    )
    return RateLimitWindow(
        limit=_int("x-ratelimit-limit-requests"),
        remaining=_int("x-ratelimit-remaining-requests"),
        reset_raw=reset_raw,
        reset_seconds=reset_seconds,
        reset_at=reset_at,
    )


def _window_openai_tokens(headers: dict) -> RateLimitWindow:
    def _int(key: str) -> Optional[int]:
        v = headers.get(key)
        return int(v) if v is not None and v.isdigit() else None

    reset_raw = headers.get("x-ratelimit-reset-tokens")
    reset_seconds = _parse_duration(reset_raw)
    reset_at = (
        datetime.now(timezone.utc) + timedelta(seconds=reset_seconds)
        if reset_seconds is not None
        else None
    )
    return RateLimitWindow(
        limit=_int("x-ratelimit-limit-tokens"),
        remaining=_int("x-ratelimit-remaining-tokens"),
        reset_raw=reset_raw,
        reset_seconds=reset_seconds,
        reset_at=reset_at,
    )


def _fetch_org_usage(
    admin_api_key: str,
    organization_id: Optional[str],
    timeout: float,
    session: requests.Session,
) -> dict:
    """Fetch today's completions usage + costs via the Admin Usage API.

    Requires an *organization Admin API key* (Settings > Admin keys in the
    OpenAI dashboard), not a normal project API key. Returns a dict with
    either the parsed usage/costs buckets or an "error" key explaining why
    it could not be fetched (e.g. wrong key type -> 401/403).
    """
    now = datetime.now(timezone.utc)
    start_time = int((now - timedelta(days=1)).timestamp())
    headers = {"Authorization": f"Bearer {admin_api_key}"}
    if organization_id:
        headers["OpenAI-Organization"] = organization_id

    result: dict = {}
    try:
        usage_resp = session.get(
            f"{OPENAI_API_BASE}/v1/organization/usage/completions",
            headers=headers,
            params={"start_time": start_time, "bucket_width": "1d"},
            timeout=timeout,
        )
        if usage_resp.status_code == 200:
            result["usage_last_24h"] = usage_resp.json()
        else:
            result["usage_error"] = (
                f"HTTP {usage_resp.status_code}: {usage_resp.text[:300]}"
            )
    except requests.RequestException as exc:  # pragma: no cover - network edge
        result["usage_error"] = str(exc)

    try:
        costs_resp = session.get(
            f"{OPENAI_API_BASE}/v1/organization/costs",
            headers=headers,
            params={"start_time": start_time, "bucket_width": "1d"},
            timeout=timeout,
        )
        if costs_resp.status_code == 200:
            result["costs_last_24h"] = costs_resp.json()
        else:
            result["costs_error"] = (
                f"HTTP {costs_resp.status_code}: {costs_resp.text[:300]}"
            )
    except requests.RequestException as exc:  # pragma: no cover - network edge
        result["costs_error"] = str(exc)

    return result
