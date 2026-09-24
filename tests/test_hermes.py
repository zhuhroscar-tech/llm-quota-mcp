import json
import subprocess

import pytest

from llm_quota.hermes import HermesNotAvailableError, get_hermes_usage


def _hermes_available() -> bool:
    try:
        subprocess.run(["hermes", "--version"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _hermes_available(), reason="hermes CLI not installed on this machine")
def test_get_hermes_usage_recent_window_real_cli(monkeypatch):
    """Integration test against the real `hermes` CLI on a machine that has
    it installed (this is intentionally NOT mocked: the whole point of this
    reader is to reflect exactly what Hermes itself already tracked, so a
    mock would just test our own assumptions about the JSON shape).

    Hermes's own live-system guard refuses to open the real state.db from
    a process it detects is running under pytest, unless this bypass env
    var is set — that guard exists to protect Hermes's *own* test suite
    from touching production state, and is correct for it to do so; we
    opt in here because reading (not mutating) real session history is
    exactly this library's intended real-world usage.
    """
    monkeypatch.setenv("HERMES_STATE_DB_GUARD_BYPASS", "1")
    usage = get_hermes_usage(newer_than="30d")
    assert usage.sessions_included >= 1
    assert usage.total_tokens >= 0
    d = usage.to_dict()
    assert d["provider"] == "hermes-local"
    assert "total_tokens" in d


@pytest.mark.skipif(not _hermes_available(), reason="hermes CLI not installed on this machine")
def test_get_hermes_usage_no_matching_session_raises(monkeypatch):
    monkeypatch.setenv("HERMES_STATE_DB_GUARD_BYPASS", "1")
    with pytest.raises(HermesNotAvailableError):
        get_hermes_usage(session_id="this-session-id-does-not-exist-xyz123")


def test_hermes_not_available_when_binary_missing(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(HermesNotAvailableError):
        get_hermes_usage(session_id="anything")


def test_hermes_usage_aggregates_multiple_records(monkeypatch):
    records = [
        {
            "id": "s1",
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 10,
            "cache_write_tokens": 5,
            "reasoning_tokens": 0,
            "message_count": 4,
            "tool_call_count": 2,
            "api_call_count": 2,
            "estimated_cost_usd": 0.01,
            "actual_cost_usd": None,
            "started_at": "2026-01-01T00:00:00Z",
            "last_activity_at": "2026-01-01T00:05:00Z",
        },
        {
            "id": "s2",
            "input_tokens": 200,
            "output_tokens": 75,
            "cache_read_tokens": 20,
            "cache_write_tokens": 8,
            "reasoning_tokens": 3,
            "message_count": 6,
            "tool_call_count": 3,
            "api_call_count": 3,
            "estimated_cost_usd": 0.02,
            "actual_cost_usd": 0.019,
            "started_at": "2026-01-02T00:00:00Z",
            "last_activity_at": "2026-01-02T00:05:00Z",
        },
    ]

    import llm_quota.hermes as hermes_mod

    monkeypatch.setattr(
        hermes_mod, "_run_hermes_export", lambda args, timeout=30.0: records
    )
    usage = get_hermes_usage(newer_than="7d")
    assert usage.sessions_included == 2
    assert usage.input_tokens == 300
    assert usage.output_tokens == 125
    assert usage.total_tokens == 300 + 125 + 30 + 13 + 3
    assert usage.estimated_cost_usd == pytest.approx(0.03)
    assert usage.actual_cost_usd == pytest.approx(0.019)
    assert usage.started_at == "2026-01-01T00:00:00Z"
    assert usage.last_activity_at == "2026-01-02T00:05:00Z"


def test_hermes_usage_normalizes_epoch_timestamps(monkeypatch):
    records = [
        {
            "id": "older",
            "input_tokens": 1,
            "started_at": 1767225600.0,
            "last_activity_at": 1767225900.0,
        },
        {
            "id": "newer",
            "input_tokens": 2,
            "started_at": 1767312000.0,
            "last_activity_at": 1767312300.0,
        },
    ]

    import llm_quota.hermes as hermes_mod

    monkeypatch.setattr(
        hermes_mod, "_run_hermes_export", lambda args, timeout=30.0: records
    )

    usage = get_hermes_usage()
    assert usage.session_id == "newer"
    assert usage.started_at == "2026-01-02T00:00:00+00:00"
    assert usage.last_activity_at == "2026-01-02T00:05:00+00:00"
    assert usage.to_dict()["started_at"] == "2026-01-02T00:00:00+00:00"
