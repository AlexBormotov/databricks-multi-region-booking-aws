"""Cross-region race on one room-night in the MRSC table (plan D8).

    python spike/dynamodb/mrsc_race.py --table booking-spike-room-nights --attempts 100 \
        --out artifacts/mrsc.json

Half the attempts go through a us-east-1 client and half through a us-east-2 client, all at once,
over a fresh room-night. Passes when exactly one claim won and both regions read the same holder.
"""

import argparse
import json
import random
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).parent))
import claims  # noqa: E402

NIGHT = date(2027, 3, 1)
# MRSC rejects a write that races another region's write to the same item; it is safe to retry.
REPLICATED_CONFLICT = "ReplicatedWriteConflictException"
MAX_TRIES = 5


def attempt(client, table: str, room_id: str, start: threading.Barrier) -> tuple[str, str]:
    booking_id = str(uuid.uuid4())
    start.wait()
    for tries in range(MAX_TRIES):
        try:
            won = claims.claim(client, table, booking_id, room_id, [NIGHT])
            return booking_id, "won" if won else "lost"
        except ClientError as err:
            if err.response["Error"]["Code"] != REPLICATED_CONFLICT:
                raise
            time.sleep(random.uniform(0, 0.05 * 2**tries))
    return booking_id, "unresolved"


def race(clients: dict[str, object], table: str, attempts: int) -> dict:
    room_id = str(uuid.uuid4())
    labels = [list(clients)[i % len(clients)] for i in range(attempts)]
    start = threading.Barrier(attempts)
    with ThreadPoolExecutor(max_workers=attempts) as pool:
        results = list(
            pool.map(lambda label: (label, *attempt(clients[label], table, room_id, start)), labels)
        )
    winners = [(label, booking) for label, booking, outcome in results if outcome == "won"]
    holders = {
        label: client.get_item(TableName=table, Key=claims.key(room_id, NIGHT), ConsistentRead=True)
        .get("Item", {})
        .get("booking_id", {})
        .get("S")
        for label, client in clients.items()
    }
    outcomes = {}
    for label, _, outcome in results:
        outcomes.setdefault(label, {}).setdefault(outcome, 0)
        outcomes[label][outcome] += 1
    failures = []
    if len(winners) != 1:
        failures.append(f"{len(winners)} claims won, expected exactly 1")
    if len(set(holders.values())) != 1 or (winners and holders[winners[0][0]] != winners[0][1]):
        failures.append(f"regions disagree on the holder: {holders}")
    return {
        "room_night": claims.key(room_id, NIGHT)["room_night"]["S"],
        "attempts": attempts,
        "outcomes": outcomes,
        "winner": winners[0] if len(winners) == 1 else winners,
        "holders": holders,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True)
    parser.add_argument("--attempts", type=int, default=100)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    # A connection per attempt, so the barrier releases every request at once.
    config = Config(max_pool_connections=args.attempts)
    clients = {
        r: boto3.client("dynamodb", region_name=r, config=config)
        for r in ("us-east-1", "us-east-2")
    }
    result = race(clients, args.table, args.attempts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    sys.exit(1 if result["failures"] else 0)


if __name__ == "__main__":
    main()
