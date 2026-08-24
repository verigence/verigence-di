"""CLI entry point for the live DI + Rule Engine E2E harness."""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from .models import load_scenario
from .runner import RuntimeConfig, run_scenario


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-")
    return clean or "di-rules-e2e"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m e2e.di_rules",
        description=(
            "Run live Verigence DI document upload, Document-AI extraction and "
            "deterministic reconciliation-rule verification."
        ),
    )
    parser.add_argument("--scenario", required=True, help="Path to scenario JSON")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("DI_E2E_BASE_URL"),
        help="DI API base URL (or DI_E2E_BASE_URL)",
    )
    parser.add_argument(
        "--tenant",
        default=os.environ.get("DI_E2E_TENANT_ID"),
        help="Tenant ID (or DI_E2E_TENANT_ID)",
    )
    parser.add_argument(
        "--token-env",
        default="DI_E2E_TOKEN",
        help="Environment variable containing the bearer token (default: DI_E2E_TOKEN)",
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=float(os.environ.get("DI_E2E_POLL_TIMEOUT", "240")),
        help="Maximum seconds to wait per document (default: 240)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("DI_E2E_POLL_INTERVAL", "4")),
        help="Polling interval in seconds (default: 4)",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=float(os.environ.get("DI_E2E_REQUEST_TIMEOUT", "60")),
        help="HTTP request timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="JSON report path. Default: e2e/results/<scenario>-<timestamp>.json",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        scenario = load_scenario(args.scenario)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if not args.base_url:
        print("Configuration error: --base-url or DI_E2E_BASE_URL is required", file=sys.stderr)
        return 2
    if not args.tenant:
        print("Configuration error: --tenant or DI_E2E_TENANT_ID is required", file=sys.stderr)
        return 2
    token = os.environ.get(args.token_env, "").strip()
    if not token:
        print(
            f"Configuration error: bearer token environment variable {args.token_env!r} is empty",
            file=sys.stderr,
        )
        return 2
    if args.poll_timeout <= 0 or args.poll_interval <= 0 or args.request_timeout <= 0:
        print("Configuration error: timeout values must be positive", file=sys.stderr)
        return 2

    if args.report:
        report_path = Path(args.report).expanduser().resolve()
    else:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        report_path = (
            Path("e2e") / "results" / f"{_slug(scenario.name)}-{timestamp}.json"
        ).resolve()

    report = run_scenario(
        scenario,
        RuntimeConfig(
            base_url=args.base_url,
            tenant_id=args.tenant,
            token=token,
            poll_timeout_seconds=args.poll_timeout,
            poll_interval_seconds=args.poll_interval,
            request_timeout_seconds=args.request_timeout,
            report_path=report_path,
        ),
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
