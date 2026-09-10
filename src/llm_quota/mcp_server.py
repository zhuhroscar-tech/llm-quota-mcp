"""MCP server exposing quota-check tools to any MCP-compatible agent host
(Claude Desktop, Hermes, Cursor, etc.) — this is the "plugin" for bots.

Three tools are exposed:
  - check_anthropic_quota(api_key?, model?)
  - check_openai_quota(api_key?, admin_api_key?, organization_id?, model?)
  - check_hermes_usage(session_id?, newer_than?)

Each mirrors the CLI in cli.py and returns the same structured dict (see
anthropic.py / openai.py / hermes.py docstrings for exactly what each
field means and why some things — like an account-wide "days until
reset" figure — are deliberately left as None with an explanatory note
rather than guessed at, since neither Anthropic nor OpenAI expose that to
a normal API key).

API keys can be supplied per-call as an argument, or left out to fall
back to the ANTHROPIC_API_KEY / OPENAI_API_KEY / OPENAI_ADMIN_API_KEY /
OPENAI_ORG_ID environment variables the MCP server process was started
with — the latter is the recommended setup so a calling agent never
needs to see or handle the raw key itself.

Run directly for local/stdio MCP hosts:
    llm-quota-mcp
Or configure it in an MCP host's config as a stdio server pointing at
this command.
"""

from __future__ import annotations

import os

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    try:
        # mcp>=2.0: FastMCP was renamed to MCPServer and moved.
        from mcp.server.mcpserver import MCPServer as FastMCP
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "The MCP server requires the 'mcp' package (v1 or v2). Install "
            "with: pip install 'llm-quota-mcp[mcp]'"
        ) from exc

import requests

from .anthropic import DEFAULT_PROBE_MODEL as ANTHROPIC_DEFAULT_MODEL
from .anthropic import get_anthropic_quota
from .hermes import HermesNotAvailableError, get_hermes_usage
from .openai import DEFAULT_PROBE_MODEL as OPENAI_DEFAULT_MODEL
from .openai import get_openai_quota

mcp = FastMCP("llm-quota")


@mcp.tool()
def check_anthropic_quota(api_key: str = "", model: str = "") -> dict:
    """Check current Anthropic API rate-limit quota (requests/tokens per
    minute) and its reset time, via a free count_tokens probe call that
    does not consume paid token quota.

    Args:
        api_key: Anthropic API key. If omitted, uses the ANTHROPIC_API_KEY
            environment variable of the server process.
        model: Model id used for the probe request (default: a small,
            cheap model — the model choice does not affect the rate-limit
            numbers returned, which are account/key-tier-wide).

    Returns a dict with requests/input_tokens/output_tokens/tokens rate
    windows (limit, remaining, reset time), whether the key is currently
    rate-limited, and a note explaining these are per-minute windows, not
    an account-wide monthly budget (Anthropic does not expose that to a
    normal API key).
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return {
            "error": "No Anthropic API key provided and ANTHROPIC_API_KEY is not set.",
        }
    try:
        quota = get_anthropic_quota(key, model=model or ANTHROPIC_DEFAULT_MODEL)
    except requests.HTTPError as exc:
        return {"error": str(exc)}
    return quota.to_dict()


@mcp.tool()
def check_openai_quota(
    api_key: str = "",
    admin_api_key: str = "",
    organization_id: str = "",
    model: str = "",
) -> dict:
    """Check current OpenAI API rate-limit quota (requests/tokens per
    minute) and its reset time, via a minimal 1-token chat completion
    probe. Optionally also fetch real historical usage/cost totals if an
    organization Admin API key is supplied (a different credential type
    than a normal project API key — created under Settings > Admin keys
    in the OpenAI dashboard).

    Args:
        api_key: OpenAI API key. If omitted, uses OPENAI_API_KEY env var.
        admin_api_key: Organization Admin API key for real usage/cost
            totals. If omitted, uses OPENAI_ADMIN_API_KEY env var. Usage
            data is skipped (with a note) if neither is available.
        organization_id: Optional org id header for the admin usage call.
            If omitted, uses OPENAI_ORG_ID env var.
        model: Model id used for the probe request (default: a small,
            cheap model).

    Returns a dict with requests/tokens rate windows (limit, remaining,
    reset time), whether the key is currently rate-limited, org_usage (if
    an admin key was available) with real 24h usage/cost totals, and a
    note explaining the difference between rate-limit windows and an
    account-wide budget.
    """
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return {
            "error": "No OpenAI API key provided and OPENAI_API_KEY is not set.",
        }
    admin_key = admin_api_key or os.environ.get("OPENAI_ADMIN_API_KEY", "") or None
    org_id = organization_id or os.environ.get("OPENAI_ORG_ID", "") or None
    try:
        quota = get_openai_quota(
            key,
            model=model or OPENAI_DEFAULT_MODEL,
            admin_api_key=admin_key,
            organization_id=org_id,
        )
    except requests.HTTPError as exc:
        return {"error": str(exc)}
    return quota.to_dict()


@mcp.tool()
def check_hermes_usage(session_id: str = "", newer_than: str = "") -> dict:
    """Read token/cost totals that Hermes Agent has already tracked
    locally for a session (or a recent window of sessions), with no
    network call and no API key required. This is what backs Hermes's
    own `/usage` command.

    Args:
        session_id: A specific Hermes session id. If omitted and
            newer_than is also omitted, the most recently active session
            is used (useful for "how many tokens has THIS run used").
        newer_than: Aggregate totals across all sessions active within
            this recent window instead of a single session, e.g. '24h',
            '7d' (same syntax as `hermes sessions export --newer-than`).

    Returns input/output/cache-read/cache-write/reasoning token counts,
    total_tokens, message/tool-call/api-call counts, estimated and actual
    cost in USD (whichever the provider has reported), and timestamps.
    This reflects usage already incurred, not a remaining-quota figure —
    combine with check_anthropic_quota/check_openai_quota for the
    provider-side rate-limit picture.
    """
    try:
        usage = get_hermes_usage(
            session_id=session_id or None, newer_than=newer_than or None
        )
    except HermesNotAvailableError as exc:
        return {"error": str(exc)}
    return usage.to_dict()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
