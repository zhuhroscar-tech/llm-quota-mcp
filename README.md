# llm-quota-mcp

Check how much LLM API quota you have left — and how much you've already
used — from **any** agent platform: an MCP-compatible host (Claude
Desktop, Hermes Agent, Cursor, etc.), a plain Python script, or the
command line.

Three things this does, honestly:

1. **Anthropic rate-limit check** — probes the current per-minute
   requests/input-tokens/output-tokens window and its reset time, via a
   free `count_tokens` call that does not spend your paid quota.
2. **OpenAI rate-limit check** — probes the current per-minute
   requests/tokens window and its reset time via a minimal 1-token
   completion, and optionally pulls real historical usage/cost totals if
   you supply an **organization Admin API key**.
3. **Hermes Agent local usage** — reads the token/cost totals Hermes
   Agent already tracks for a session (or a recent window of sessions)
   via its own `hermes sessions export` CLI — no network call, no API key.

## Why it's built this way (please read before filing a "why is X null" issue)

Neither Anthropic nor OpenAI expose an account-wide "tokens remaining
this billing period" or "plan reset date" field to a normal API key —
that number only exists on their respective web dashboards
(console.anthropic.com, platform.openai.com/usage). What *is* available
to every authenticated API response is a **rate-limit window**: how many
requests/tokens you can send in the current minute, and when that window
resets. This project surfaces exactly that, clearly labeled as a
rate-limit window and not a monthly budget, rather than guessing or
faking a number that looks like a monthly budget.

If a field isn't available from the API, it is `None` with an
explanatory `note`, never a fabricated value.

OpenAI's organization-level Usage/Costs API (real historical token/cost
totals) is genuinely available, but requires a separate **Admin API
key** (Settings → Admin keys in the dashboard), not a project API key.
Pass one via `--admin-api-key` / `admin_api_key` and this tool will use
it; otherwise that field is simply omitted.

## Install

```bash
pip install "llm-quota-mcp[mcp]"   # includes the MCP server
# or, CLI-only, no MCP dependency:
pip install llm-quota-mcp
```

From source:

```bash
git clone https://github.com/zhuhroscar-tech/llm-quota-mcp.git
cd llm-quota-mcp
pip install -e ".[dev]"
```

## CLI usage

```bash
export ANTHROPIC_API_KEY=sk-ant-...
llm-quota anthropic
# provider: anthropic
#   requests: {'limit': 50, 'remaining': 49, 'reset_raw': '...', 'reset_at': '...'}
#   input_tokens: {...}
#   output_tokens: {...}
#   ...

export OPENAI_API_KEY=sk-...
llm-quota openai --json

# Optional: real usage/cost totals (needs an Admin API key, not a project key)
llm-quota openai --admin-api-key sk-admin-... --json

# No API key needed — reads what Hermes Agent already tracked locally:
llm-quota hermes --newer-than 24h
llm-quota hermes --session-id <session-id>
```

## As an MCP "plugin" for a running bot

Any MCP-compatible agent host can load this as a stdio server and get
three tools: `check_anthropic_quota`, `check_openai_quota`,
`check_hermes_usage`. Example config (Claude Desktop / Hermes-style
`mcp_servers` block):

```json
{
  "mcpServers": {
    "llm-quota": {
      "command": "llm-quota-mcp",
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "OPENAI_API_KEY": "sk-...",
        "OPENAI_ADMIN_API_KEY": "sk-admin-..."
      }
    }
  }
}
```

Keys are read from the server process's environment by default, so the
calling agent never needs to see or pass the raw key itself — it can
just call `check_anthropic_quota()` with no arguments and get back the
current rate-limit picture, letting the bot decide whether to keep
going or wrap up before it gets rate-limited.

A bot running long, autonomous work (e.g. a scheduled/cron agent) can
call `check_hermes_usage(newer_than="24h")` partway through a job to see
how many tokens it has already burned this session/window, and
`check_anthropic_quota()` / `check_openai_quota()` to see if it's
approaching its per-minute rate limit, before deciding to continue,
throttle, or stop.

## Python API

```python
from llm_quota import get_anthropic_quota, get_openai_quota, get_hermes_usage

quota = get_anthropic_quota(api_key="sk-ant-...")
print(quota.requests.remaining, quota.requests.reset_at)

usage = get_hermes_usage(newer_than="24h")
print(usage.total_tokens, usage.estimated_cost_usd)
```

## Development

```bash
pip install -e ".[dev]"
pytest -v
bandit -r src/
```

Tests are real, not fabricated: Anthropic/OpenAI probes are tested
against mocked HTTP responses (`responses` library) covering success,
429 rate-limiting, and 401 auth-failure cases; the Hermes reader has a
genuine integration test that shells out to a real `hermes` CLI when one
is present on the test machine (skipped otherwise), plus unit tests for
its aggregation logic with monkeypatched data.

## License

MIT — see [LICENSE](LICENSE).
