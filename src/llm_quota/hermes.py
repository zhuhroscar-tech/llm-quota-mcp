"""Hermes local session-usage reader.

Hermes Agent tracks per-session token/cost totals in its own SQLite
session store and exposes them via `hermes sessions export --format
jsonl`. This module shells out to that CLI (no network call, no API key
needed) and returns the numbers Hermes itself already computed for a
given session — the same fields shown by `/usage` inside a chat.

This is a *local* usage reader, not a quota/remaining-budget check:
Hermes does not itself track a provider's remaining balance either (see
anthropic.py / openai.py docstrings for why that data generally isn't
available to a normal API key). What this gives you is "how much has
this session (or a recent window of sessions) actually used", which is
exactly what a running agent can use to self-monitor consumption and
decide whether to wrap up before hitting a caller-defined soft budget.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional


@dataclass
class HermesUsage:
    session_id: Optional[str] = None
    model: Optional[str] = None
    billing_provider: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    message_count: int = 0
    tool_call_count: int = 0
    api_call_count: int = 0
    estimated_cost_usd: Optional[float] = None
    actual_cost_usd: Optional[float] = None
    cost_status: Optional[str] = None
    started_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sessions_included: int = 1

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
            + self.reasoning_tokens
        )

    def to_dict(self) -> dict:
        return {
            "provider": "hermes-local",
            "session_id": self.session_id,
            "model": self.model,
            "billing_provider": self.billing_provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "message_count": self.message_count,
            "tool_call_count": self.tool_call_count,
            "api_call_count": self.api_call_count,
            "estimated_cost_usd": self.estimated_cost_usd,
            "actual_cost_usd": self.actual_cost_usd,
            "cost_status": self.cost_status,
            "started_at": self.started_at,
            "last_activity_at": self.last_activity_at,
            "sessions_included": self.sessions_included,
            "checked_at": self.checked_at.isoformat(),
            "note": (
                "Local totals already tracked by Hermes for this session "
                "(or aggregated window), read via `hermes sessions export`. "
                "Not a provider-side remaining-quota figure."
            ),
        }


class HermesNotAvailableError(RuntimeError):
    """Raised when the `hermes` CLI cannot be found or invoked."""


def _run_hermes_export(args: List[str], timeout: float = 30.0) -> List[dict]:
    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        raise HermesNotAvailableError(
            "`hermes` CLI not found on PATH. This reader only works on a "
            "machine that has Hermes Agent installed."
        )
    cmd = [hermes_bin, "sessions", "export", "-", "--format", "jsonl", *args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise HermesNotAvailableError(f"`hermes sessions export` timed out: {exc}") from exc

    if proc.returncode != 0:
        raise HermesNotAvailableError(
            f"`hermes sessions export` failed (exit {proc.returncode}): "
            f"stderr={proc.stderr.strip()[:500]!r} stdout={proc.stdout.strip()[:500]!r}"
        )

    records = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _normalize_timestamp(value: Any) -> Optional[str]:
    """Return Hermes timestamp values as UTC ISO-8601 strings.

    `hermes sessions export` has emitted both Unix epoch numbers and ISO strings
    across versions/surfaces. Keep the public llm-quota JSON stable rather than
    leaking mixed raw types through `started_at` / `last_activity_at`.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    if isinstance(value, str):
        try:
            numeric = float(value)
        except ValueError:
            return value
        return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()
    return str(value)


def _timestamp_sort_key(value: Any) -> str:
    normalized = _normalize_timestamp(value)
    return normalized or ""


def get_hermes_usage(
    session_id: Optional[str] = None,
    newer_than: Optional[str] = None,
) -> HermesUsage:
    """Read token/cost totals Hermes already tracked.

    Pass `session_id` for a single session's totals (e.g. the currently
    running one), or `newer_than` (e.g. "24h", "7d" — same syntax as
    `hermes sessions export --newer-than`) to aggregate totals across all
    sessions in that recent window. Exactly one of these should be given;
    if both are omitted, the single most-recently-active session is used.
    """
    args: List[str] = []
    if session_id:
        args += ["--session-id", session_id]
    elif newer_than:
        args += ["--newer-than", newer_than]

    records = _run_hermes_export(args)
    if not records:
        raise HermesNotAvailableError(
            "No matching Hermes sessions found for the given filter."
        )

    if not session_id and not newer_than:
        # Most-recently-active single session only.
        records = sorted(
            records,
            key=lambda r: _timestamp_sort_key(r.get("last_activity_at")),
            reverse=True,
        )[:1]

    usage = HermesUsage(sessions_included=len(records))
    started_ats = []
    last_activities = []
    est_costs = []
    act_costs = []

    for rec in records:
        usage.input_tokens += rec.get("input_tokens") or 0
        usage.output_tokens += rec.get("output_tokens") or 0
        usage.cache_read_tokens += rec.get("cache_read_tokens") or 0
        usage.cache_write_tokens += rec.get("cache_write_tokens") or 0
        usage.reasoning_tokens += rec.get("reasoning_tokens") or 0
        usage.message_count += rec.get("message_count") or 0
        usage.tool_call_count += rec.get("tool_call_count") or 0
        usage.api_call_count += rec.get("api_call_count") or 0
        if rec.get("estimated_cost_usd") is not None:
            est_costs.append(rec["estimated_cost_usd"])
        if rec.get("actual_cost_usd") is not None:
            act_costs.append(rec["actual_cost_usd"])
        started_at = _normalize_timestamp(rec.get("started_at"))
        if started_at:
            started_ats.append(started_at)
        last_activity_at = _normalize_timestamp(rec.get("last_activity_at"))
        if last_activity_at:
            last_activities.append(last_activity_at)

    if len(records) == 1:
        usage.session_id = records[0].get("id")
        usage.model = records[0].get("model")
        usage.billing_provider = records[0].get("billing_provider")
        usage.cost_status = records[0].get("cost_status")

    usage.estimated_cost_usd = sum(est_costs) if est_costs else None
    usage.actual_cost_usd = sum(act_costs) if act_costs else None
    usage.started_at = min(started_ats) if started_ats else None
    usage.last_activity_at = max(last_activities) if last_activities else None

    return usage
