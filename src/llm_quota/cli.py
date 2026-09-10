"""Command-line interface: `llm-quota <provider> [options]`."""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests

from .anthropic import DEFAULT_PROBE_MODEL as ANTHROPIC_DEFAULT_MODEL
from .anthropic import get_anthropic_quota
from .hermes import HermesNotAvailableError, get_hermes_usage
from .openai import DEFAULT_PROBE_MODEL as OPENAI_DEFAULT_MODEL
from .openai import get_openai_quota


def _print(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return

    provider = result.get("provider", "unknown")
    print(f"provider: {provider}")
    for key, value in result.items():
        if key == "provider":
            continue
        if isinstance(value, dict):
            print(f"  {key}:")
            for k2, v2 in value.items():
                print(f"    {k2}: {v2}")
        else:
            print(f"  {key}: {value}")


def cmd_anthropic(args: argparse.Namespace) -> int:
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "error: no Anthropic API key. Pass --api-key or set ANTHROPIC_API_KEY.",
            file=sys.stderr,
        )
        return 2
    try:
        quota = get_anthropic_quota(api_key, model=args.model)
    except requests.HTTPError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print(quota.to_dict(), args.json)
    return 0


def cmd_openai(args: argparse.Namespace) -> int:
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print(
            "error: no OpenAI API key. Pass --api-key or set OPENAI_API_KEY.",
            file=sys.stderr,
        )
        return 2
    admin_key = args.admin_api_key or os.environ.get("OPENAI_ADMIN_API_KEY")
    org_id = args.organization_id or os.environ.get("OPENAI_ORG_ID")
    try:
        quota = get_openai_quota(
            api_key, model=args.model, admin_api_key=admin_key, organization_id=org_id
        )
    except requests.HTTPError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print(quota.to_dict(), args.json)
    return 0


def cmd_hermes(args: argparse.Namespace) -> int:
    try:
        usage = get_hermes_usage(session_id=args.session_id, newer_than=args.newer_than)
    except HermesNotAvailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print(usage.to_dict(), args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-quota",
        description=(
            "Check remaining LLM API rate-limit quota, reset times, and "
            "(where available) usage/cost totals for Anthropic, OpenAI, "
            "and locally-tracked Hermes Agent sessions."
        ),
    )
    subparsers = parser.add_subparsers(dest="provider", required=True)

    p_anthropic = subparsers.add_parser(
        "anthropic", help="Probe Anthropic rate-limit headers (free, no token cost)."
    )
    p_anthropic.add_argument("--api-key", help="Overrides ANTHROPIC_API_KEY env var.")
    p_anthropic.add_argument(
        "--model", default=ANTHROPIC_DEFAULT_MODEL, help="Model used for the probe request."
    )
    p_anthropic.add_argument("--json", action="store_true", help="Print raw JSON.")
    p_anthropic.set_defaults(func=cmd_anthropic)

    p_openai = subparsers.add_parser(
        "openai",
        help="Probe OpenAI rate-limit headers (tiny real token cost) and optionally org usage.",
    )
    p_openai.add_argument("--api-key", help="Overrides OPENAI_API_KEY env var.")
    p_openai.add_argument(
        "--admin-api-key",
        help="Organization Admin API key (overrides OPENAI_ADMIN_API_KEY); "
        "enables real usage/cost totals via the Usage API.",
    )
    p_openai.add_argument(
        "--organization-id", help="Overrides OPENAI_ORG_ID env var (optional)."
    )
    p_openai.add_argument(
        "--model", default=OPENAI_DEFAULT_MODEL, help="Model used for the probe request."
    )
    p_openai.add_argument("--json", action="store_true", help="Print raw JSON.")
    p_openai.set_defaults(func=cmd_openai)

    p_hermes = subparsers.add_parser(
        "hermes",
        help="Read token/cost totals Hermes Agent already tracked locally (no API key needed).",
    )
    p_hermes.add_argument(
        "--session-id", help="Specific Hermes session id (default: most recently active)."
    )
    p_hermes.add_argument(
        "--newer-than",
        help="Aggregate over a recent window instead, e.g. '24h', '7d'.",
    )
    p_hermes.add_argument("--json", action="store_true", help="Print raw JSON.")
    p_hermes.set_defaults(func=cmd_hermes)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
