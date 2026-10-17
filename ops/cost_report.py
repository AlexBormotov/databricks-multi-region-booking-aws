"""What a session cost, from Cost Explorer, run the day after (plan D14).

    python -m ops.cost_report --date 2027-01-15

Two AWS figures: costs tagged `project=booking`, and the account's whole day. Usage that cannot
carry a tag, such as Bedrock model calls, appears only in the second, so the second is the upper
bound. The Databricks share is added in slice C3.
"""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import boto3

BUDGET_USD = 7.0


def by_service(ce, day: date, tagged: bool) -> dict[str, float]:
    query = {
        "TimePeriod": {"Start": day.isoformat(), "End": (day + timedelta(days=1)).isoformat()},
        "Granularity": "DAILY",
        "Metrics": ["UnblendedCost"],
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
    }
    if tagged:
        query["Filter"] = {"Tags": {"Key": "project", "Values": ["booking"]}}
    costs: dict[str, float] = {}
    for result in ce.get_cost_and_usage(**query)["ResultsByTime"]:
        for group in result["Groups"]:
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            if amount >= 0.005:
                costs[group["Keys"][0]] = costs.get(group["Keys"][0], 0.0) + amount
    return dict(sorted(costs.items(), key=lambda kv: -kv[1]))


def report(day: date, tagged: dict[str, float], account: dict[str, float]) -> dict:
    return {
        "date": day.isoformat(),
        "aws_tagged_usd": round(sum(tagged.values()), 2),
        "aws_account_usd": round(sum(account.values()), 2),
        "budget_usd": BUDGET_USD,
        "within_budget": sum(account.values()) < BUDGET_USD,
        "tagged_by_service": {k: round(v, 2) for k, v in tagged.items()},
        "account_by_service": {k: round(v, 2) for k, v in account.items()},
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="ops.cost_report")
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    ce = boto3.client("ce", region_name="us-east-1")  # each call costs $0.01
    result = report(args.date, by_service(ce, args.date, True), by_service(ce, args.date, False))
    args.out.mkdir(exist_ok=True)
    (args.out / f"cost-{args.date}.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
