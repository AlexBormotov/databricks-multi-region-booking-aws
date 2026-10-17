"""The demo's steps and the checks that turn their output into pass or fail.

python -m ops.demo check-k6 --attempts 1000 SUMMARY.json [SUMMARY.json ...]
"""

import argparse
import json
import sys
from pathlib import Path


def contention(summaries: list[dict], attempts: int) -> dict:
    """Adds up the k6 summaries; exactly one attempt may win and every attempt must be answered."""
    total = {
        name: sum(s[name] for s in summaries) for name in ("created", "conflict", "busy", "other")
    }
    answered = sum(total.values())
    failures = []
    if total["created"] != 1:
        failures.append(f"{total['created']} bookings created, expected exactly 1")
    if total["other"]:
        failures.append(f"{total['other']} responses were neither 201, 409 nor 503")
    if answered != attempts:
        failures.append(f"{answered} of {attempts} attempts answered")
    return {**total, "attempts": attempts, "failures": failures}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="ops.demo")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check-k6")
    check.add_argument("--attempts", type=int, required=True)
    check.add_argument("summaries", nargs="+", type=Path)
    args = parser.parse_args(argv)

    if args.command == "check-k6":
        result = contention([json.loads(p.read_text()) for p in args.summaries], args.attempts)
        print(json.dumps(result, indent=2))
        sys.exit(1 if result["failures"] else 0)


if __name__ == "__main__":
    main()
