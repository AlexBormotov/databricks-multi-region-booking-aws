"""Session steps that `make up`, `make down` and the reaper run around Terragrunt.

python -m ops.session expiry-set [--hours 2]   write the session expiry to SSM
python -m ops.session due                      exit 0 if the session has expired
python -m ops.session expiry-clear
python -m ops.session prepare --seed 7 --scale small
python -m ops.session empty-landing
python -m ops.session deploy-bundle            the lakehouse bundle, its tables reset
python -m ops.session destroy-bundle
python -m ops.session validate-bundle
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3

from booking.seed import seed
from booking.store import Store

HOME = "us-east-1"
EXPIRY_PARAM = "/booking/session/expires_at"
LIVE = Path(__file__).resolve().parents[1] / "infra" / "live" / "demo-prod"
BUNDLE = LIVE.parents[2] / "databricks"


def set_expiry(ssm, now: datetime, hours: float) -> datetime:
    expires_at = now + timedelta(hours=hours)
    ssm.put_parameter(
        Name=EXPIRY_PARAM, Value=expires_at.isoformat(), Type="String", Overwrite=True
    )
    return expires_at


def due(ssm, now: datetime) -> bool:
    """True once the stored expiry has passed; no stored expiry means no session to reap."""
    try:
        value = ssm.get_parameter(Name=EXPIRY_PARAM)["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        return False
    return datetime.fromisoformat(value) <= now


def clear_expiry(ssm) -> None:
    try:
        ssm.delete_parameter(Name=EXPIRY_PARAM)
    except ssm.exceptions.ParameterNotFound:
        pass


def outputs(component: str) -> dict:
    """A component's Terraform outputs; empty if it was never applied."""
    raw = subprocess.run(
        ["terragrunt", "output", "-json", "--non-interactive"],
        cwd=LIVE / component,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {name: o["value"] for name, o in json.loads(raw or "{}").items()}


def empty_bucket(s3, bucket: str) -> int:
    deleted = 0
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
        objects = [
            {"Key": o["Key"], "VersionId": o["VersionId"]}
            for o in page.get("Versions", []) + page.get("DeleteMarkers", [])
        ]
        if objects:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
            deleted += len(objects)
    return deleted


def prepare(seed_value: int, scale: str) -> None:
    """Reference rooms in the booking store (replicated to us-east-2)."""
    print("seed:", seed(Store(boto3.client("dynamodb", region_name=HOME)), seed_value, scale))


def bundle(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    """A `databricks bundle` command with the variables from the databricks_uc outputs."""
    uc = outputs("us-east-1/databricks_uc")
    variables = [f"--var={name}={uc[name]}" for name in ("landing_path", "warehouse_id")]
    return subprocess.run(["databricks", "bundle", *command, *variables], cwd=BUNDLE, **kwargs)


def statement(sql: str, warehouse_id: str, timeout_s: int = 600) -> list[dict]:
    """Runs one SQL statement on the warehouse through the Statement Execution API."""

    def api(*args: str) -> dict:
        out = subprocess.run(
            ["databricks", "api", *args], check=True, capture_output=True, text=True
        ).stdout
        return json.loads(out)

    body = {"warehouse_id": warehouse_id, "statement": sql, "wait_timeout": "50s"}
    response = api("post", "/api/2.0/sql/statements", "--json", json.dumps(body))
    deadline = time.monotonic() + timeout_s
    while response["status"]["state"] in ("PENDING", "RUNNING"):
        if time.monotonic() > deadline:
            raise TimeoutError(f"statement {response['statement_id']} still running")
        time.sleep(5)
        response = api("get", f"/api/2.0/sql/statements/{response['statement_id']}")
    return rows(response)


def rows(response: dict) -> list[dict]:
    """The rows of a finished statement, as dicts by column name; raises if it failed."""
    if response["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(f"statement {response['status']['state']}: {response['status']}")
    columns = [c["name"] for c in response["manifest"]["schema"]["columns"]]
    data = response["result"].get("data_array", [])
    return [dict(zip(columns, row, strict=True)) for row in data]


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="ops.session")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("expiry-set").add_argument("--hours", type=float, default=2.0)
    commands.add_parser("due")
    commands.add_parser("expiry-clear")
    prep = commands.add_parser("prepare")
    prep.add_argument("--seed", type=int, required=True)
    prep.add_argument("--scale", required=True)
    commands.add_parser("empty-landing")
    commands.add_parser("deploy-bundle")
    commands.add_parser("destroy-bundle")
    commands.add_parser("validate-bundle")
    args = parser.parse_args(argv)

    ssm = boto3.client("ssm", region_name=HOME)
    now = datetime.now(UTC)
    if args.command == "expiry-set":
        print("session expires at", set_expiry(ssm, now, args.hours).isoformat())
    elif args.command == "due":
        sys.exit(0 if due(ssm, now) else 1)
    elif args.command == "expiry-clear":
        clear_expiry(ssm)
    elif args.command == "prepare":
        prepare(args.seed, args.scale)
    elif args.command == "empty-landing":
        bucket = outputs("us-east-1/landing").get("bucket")
        if bucket:
            print("deleted", empty_bucket(boto3.client("s3", region_name=HOME), bucket), "objects")
    elif args.command == "deploy-bundle":
        bundle(["deploy"], check=True)
        # The tables outlive `make down`, which empties the landing bucket. Without a reset, the
        # last session's bookings meet this one's on the same seeded room-nights and fail gold.
        # The seeded rooms reach the landing bucket and may already have started an update.
        bundle(["run", "lakehouse", "--full-refresh-all", "--restart"], check=True)
    elif args.command == "destroy-bundle":
        bundle(["destroy", "--auto-approve"], check=True)
    elif args.command == "validate-bundle":
        bundle(["validate"], check=True)


if __name__ == "__main__":
    main()
