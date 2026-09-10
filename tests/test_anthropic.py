import pytest
import responses

from llm_quota.anthropic import get_anthropic_quota, ANTHROPIC_API_BASE


@responses.activate
def test_anthropic_quota_success_parses_headers():
    responses.add(
        responses.POST,
        f"{ANTHROPIC_API_BASE}/v1/messages/count_tokens",
        json={"input_tokens": 5},
        status=200,
        headers={
            "anthropic-ratelimit-requests-limit": "50",
            "anthropic-ratelimit-requests-remaining": "49",
            "anthropic-ratelimit-requests-reset": "2026-01-01T00:00:00Z",
            "anthropic-ratelimit-input-tokens-limit": "40000",
            "anthropic-ratelimit-input-tokens-remaining": "39000",
            "anthropic-ratelimit-input-tokens-reset": "2026-01-01T00:01:00Z",
            "anthropic-ratelimit-output-tokens-limit": "8000",
            "anthropic-ratelimit-output-tokens-remaining": "7500",
            "anthropic-ratelimit-output-tokens-reset": "2026-01-01T00:01:00Z",
        },
    )
    quota = get_anthropic_quota("fake-key")
    assert quota.requests.limit == 50
    assert quota.requests.remaining == 49
    assert quota.requests.reset_at is not None
    assert quota.input_tokens.remaining == 39000
    assert quota.output_tokens.remaining == 7500
    assert quota.rate_limited is False
    d = quota.to_dict()
    assert d["provider"] == "anthropic"
    assert d["requests"]["remaining"] == 49


@responses.activate
def test_anthropic_quota_rate_limited_captures_retry_after():
    responses.add(
        responses.POST,
        f"{ANTHROPIC_API_BASE}/v1/messages/count_tokens",
        json={"error": {"type": "rate_limit_error"}},
        status=429,
        headers={
            "anthropic-ratelimit-requests-remaining": "0",
            "retry-after": "12",
        },
    )
    quota = get_anthropic_quota("fake-key")
    assert quota.rate_limited is True
    assert quota.retry_after_seconds == 12.0
    assert quota.requests.remaining == 0


@responses.activate
def test_anthropic_quota_bad_key_raises():
    responses.add(
        responses.POST,
        f"{ANTHROPIC_API_BASE}/v1/messages/count_tokens",
        json={"error": {"type": "authentication_error"}},
        status=401,
    )
    with pytest.raises(Exception):
        get_anthropic_quota("bad-key")


def test_missing_headers_leave_fields_none():
    """No fabricated numbers: absent headers -> None, not 0 or a guess."""
    from llm_quota.anthropic import _window

    w = _window({}, "anthropic-ratelimit-requests")
    assert w.limit is None
    assert w.remaining is None
    assert w.reset_at is None
