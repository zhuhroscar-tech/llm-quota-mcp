import pytest
import responses

from llm_quota.openai import get_openai_quota, OPENAI_API_BASE, _parse_duration


@responses.activate
def test_openai_quota_success_parses_headers():
    responses.add(
        responses.POST,
        f"{OPENAI_API_BASE}/v1/chat/completions",
        json={"choices": [{"message": {"content": "ok"}}]},
        status=200,
        headers={
            "x-ratelimit-limit-requests": "500",
            "x-ratelimit-remaining-requests": "499",
            "x-ratelimit-reset-requests": "6m0s",
            "x-ratelimit-limit-tokens": "200000",
            "x-ratelimit-remaining-tokens": "199950",
            "x-ratelimit-reset-tokens": "8.64s",
        },
    )
    quota = get_openai_quota("fake-key")
    assert quota.requests.limit == 500
    assert quota.requests.remaining == 499
    assert quota.requests.reset_seconds == 360.0
    assert quota.tokens.remaining == 199950
    assert quota.tokens.reset_seconds == pytest.approx(8.64)
    assert quota.rate_limited is False
    assert quota.org_usage is None


@responses.activate
def test_openai_quota_rate_limited():
    responses.add(
        responses.POST,
        f"{OPENAI_API_BASE}/v1/chat/completions",
        json={"error": {"message": "rate limited"}},
        status=429,
        headers={"retry-after": "3"},
    )
    quota = get_openai_quota("fake-key")
    assert quota.rate_limited is True
    assert quota.retry_after_seconds == 3.0


@responses.activate
def test_openai_quota_bad_key_raises():
    responses.add(
        responses.POST,
        f"{OPENAI_API_BASE}/v1/chat/completions",
        json={"error": {"message": "invalid api key"}},
        status=401,
    )
    with pytest.raises(Exception):
        get_openai_quota("bad-key")


@responses.activate
def test_openai_quota_with_admin_key_fetches_org_usage():
    responses.add(
        responses.POST,
        f"{OPENAI_API_BASE}/v1/chat/completions",
        json={"choices": []},
        status=200,
        headers={"x-ratelimit-remaining-requests": "10"},
    )
    responses.add(
        responses.GET,
        f"{OPENAI_API_BASE}/v1/organization/usage/completions",
        json={"data": [{"input_tokens": 123}]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{OPENAI_API_BASE}/v1/organization/costs",
        json={"data": [{"amount": {"value": 0.5}}]},
        status=200,
    )
    quota = get_openai_quota("fake-key", admin_api_key="admin-key")
    assert quota.org_usage is not None
    assert "usage_last_24h" in quota.org_usage
    assert "costs_last_24h" in quota.org_usage


@responses.activate
def test_openai_quota_admin_key_wrong_type_reports_error_not_crash():
    responses.add(
        responses.POST,
        f"{OPENAI_API_BASE}/v1/chat/completions",
        json={"choices": []},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{OPENAI_API_BASE}/v1/organization/usage/completions",
        json={"error": "wrong key type"},
        status=401,
    )
    responses.add(
        responses.GET,
        f"{OPENAI_API_BASE}/v1/organization/costs",
        json={"error": "wrong key type"},
        status=401,
    )
    quota = get_openai_quota("fake-key", admin_api_key="not-an-admin-key")
    assert "usage_error" in quota.org_usage
    assert "costs_error" in quota.org_usage


def test_parse_duration_variants():
    assert _parse_duration("6m0s") == 360.0
    assert _parse_duration("8.64s") == pytest.approx(8.64)
    assert _parse_duration("1d2h3m4s") == 93784.0
    assert _parse_duration(None) is None
    assert _parse_duration("") is None
    assert _parse_duration("garbage") is None
