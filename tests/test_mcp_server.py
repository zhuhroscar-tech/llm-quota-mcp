"""Tests for the MCP server tool wrappers.

These call the underlying tool functions directly (FastMCP's @mcp.tool()
decorator still leaves the plain function callable) rather than spinning
up a full MCP client/transport round-trip, since the goal here is to
verify the *behavior* the tools expose (error handling, env var
fallback, correct field passthrough) — the wire protocol itself is
FastMCP's responsibility, already covered by its own test suite.
"""

import pytest
import responses

pytest.importorskip("mcp")

from llm_quota import mcp_server
from llm_quota.anthropic import ANTHROPIC_API_BASE
from llm_quota.openai import OPENAI_API_BASE


def _call(tool, **kwargs):
    """Call an @mcp.tool()-decorated function across mcp v1 (FastMCP,
    which wraps the function in a Tool object exposing `.fn`) and mcp v2
    (MCPServer, whose `.tool()` decorator returns the plain function)."""
    target = getattr(tool, "fn", tool)
    return target(**kwargs)


@responses.activate
def test_check_anthropic_quota_uses_explicit_key():
    responses.add(
        responses.POST,
        f"{ANTHROPIC_API_BASE}/v1/messages/count_tokens",
        json={"input_tokens": 5},
        status=200,
        headers={"anthropic-ratelimit-requests-remaining": "10"},
    )
    result = _call(mcp_server.check_anthropic_quota, api_key="explicit-key")
    assert result["provider"] == "anthropic"
    assert result["requests"]["remaining"] == 10


def test_check_anthropic_quota_missing_key_returns_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = _call(mcp_server.check_anthropic_quota)
    assert "error" in result


@responses.activate
def test_check_anthropic_quota_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    responses.add(
        responses.POST,
        f"{ANTHROPIC_API_BASE}/v1/messages/count_tokens",
        json={"input_tokens": 5},
        status=200,
        headers={"anthropic-ratelimit-requests-remaining": "20"},
    )
    result = _call(mcp_server.check_anthropic_quota)
    assert result["requests"]["remaining"] == 20


@responses.activate
def test_check_openai_quota_uses_explicit_key():
    responses.add(
        responses.POST,
        f"{OPENAI_API_BASE}/v1/chat/completions",
        json={"choices": []},
        status=200,
        headers={"x-ratelimit-remaining-tokens": "999"},
    )
    result = _call(mcp_server.check_openai_quota, api_key="explicit-key")
    assert result["provider"] == "openai"
    assert result["tokens"]["remaining"] == 999


def test_check_openai_quota_missing_key_returns_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = _call(mcp_server.check_openai_quota)
    assert "error" in result


def test_check_hermes_usage_no_binary_returns_error(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = _call(mcp_server.check_hermes_usage)
    assert "error" in result


def test_check_hermes_usage_success(monkeypatch):
    import llm_quota.hermes as hermes_mod

    records = [
        {
            "id": "s1",
            "model": "claude-sonnet-5",
            "billing_provider": "anthropic",
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
            "message_count": 2,
            "tool_call_count": 1,
            "api_call_count": 1,
            "estimated_cost_usd": 0.001,
            "actual_cost_usd": None,
            "cost_status": "estimated",
            "started_at": "2026-01-01T00:00:00Z",
            "last_activity_at": "2026-01-01T00:01:00Z",
        }
    ]
    monkeypatch.setattr(hermes_mod, "_run_hermes_export", lambda args, timeout=30.0: records)
    result = _call(mcp_server.check_hermes_usage, session_id="s1")
    assert result["provider"] == "hermes-local"
    assert result["input_tokens"] == 10
    assert result["total_tokens"] == 15
