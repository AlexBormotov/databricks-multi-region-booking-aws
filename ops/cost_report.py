"""What a session cost, from Cost Explorer, run the day after (plan D14).

    python -m ops.cost_report --date 2027-01-15

Two AWS figures: costs tagged `project=booking`, and the account's whole day. Usage that cannot
carry a tag, such as Bedrock model calls, appears only in the second, so the second is the upper
bound. With DATABRICKS_HOST set, the Databricks share is the day's `system.billing.usage` at list
price (plan D14); if the system tables are off, it is read from the account console by hand.
"""

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path

import boto3

from ops.session import outputs, statement

BUDGET_USD = 7.0
DATABRICKS_USAGE = """
SELECT u.sku_name, sum(u.usage_quantity * p.pricing.default) AS usd
FROM system.billing.usage u
JOIN system.billing.list_prices p
  ON p.sku_name = u.sku_name AND p.cloud = u.cloud AND p.usage_unit = u.usage_unit
  AND u.usage_end_time >= p.price_start_time
  AND (p.price_end_time IS NULL OR u.usage_end_time < p.price_end_time)
WHERE u.usage_date = DATE'{day}'
GROUP BY u.sku_name
"""


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


def databricks_by_sku(day: date) -> dict[str, float]:
    warehouse = outputs("us-east-1/databricks_uc")["warehouse_id"]
    rows = statement(DATABRICKS_USAGE.format(day=day.isoformat()), warehouse)
    return {r["sku_name"]: float(r["usd"]) for r in rows if r["usd"] is not None}


def report(
    day: date,
    tagged: dict[str, float],
    account: dict[str, float],
    databricks: dict[str, float] | None = None,
) -> dict:
    """The budget is judged on the account total plus Databricks, the upper bound of a session."""
    databricks_usd = sum((databricks or {}).values())
    return {
        "date": day.isoformat(),
        "aws_tagged_usd": round(sum(tagged.values()), 2),
        "aws_account_usd": round(sum(account.values()), 2),
        "databricks_usd": round(databricks_usd, 2) if databricks is not None else None,
        "budget_usd": BUDGET_USD,
        "within_budget": sum(account.values()) + databricks_usd < BUDGET_USD,
        "tagged_by_service": {k: round(v, 2) for k, v in tagged.items()},
        "account_by_service": {k: round(v, 2) for k, v in account.items()},
        "databricks_by_sku": {k: round(v, 2) for k, v in (databricks or {}).items()},
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="ops.cost_report")
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    ce = boto3.client("ce", region_name="us-east-1")  # each call costs $0.01
    databricks = databricks_by_sku(args.date) if os.environ.get("DATABRICKS_HOST") else None
    result = report(
        args.date, by_service(ce, args.date, True), by_service(ce, args.date, False), databricks
    )
    args.out.mkdir(exist_ok=True)
    (args.out / f"cost-{args.date}.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
