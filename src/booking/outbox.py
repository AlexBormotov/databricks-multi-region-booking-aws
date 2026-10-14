"""Outbox: events written in the same transaction as the state change they describe, and the
poller that publishes them to Kinesis at least once.
"""

import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import psycopg
from psycopg import Cursor
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from booking.domain import uuid7

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
# Kinesis PutRecords takes at most 500 records per call.
BATCH = 500


def insert_event(
    cur: Cursor,
    *,
    aggregate_id: uuid.UUID,
    aggregate_version: int,
    event_type: str,
    payload: dict,
    home_region: str,
    occurred_at: datetime,
    event_id: uuid.UUID | None = None,
) -> None:
    """Pass event_id only for an event that must be written at most once: a repeated insert of
    the same id is ignored."""
    cur.execute(
        "INSERT INTO outbox (event_id, aggregate_id, aggregate_version, event_type, payload,"
        " home_region, occurred_at) VALUES (%s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (event_id) DO NOTHING",
        (
            event_id or uuid7(),
            aggregate_id,
            aggregate_version,
            event_type,
            Jsonb(payload),
            home_region,
            occurred_at,
        ),
    )


def envelope(
    *,
    event_id: uuid.UUID,
    event_type: str,
    aggregate_id: uuid.UUID | None,
    aggregate_version: int | None,
    home_region: str,
    occurred_at: datetime,
    payload: dict,
) -> bytes:
    """The event contract shared by outbox events and telemetry: one JSON object."""
    return json.dumps(
        {
            "event_id": str(event_id),
            "event_type": event_type,
            "aggregate_id": str(aggregate_id) if aggregate_id else None,
            "aggregate_version": aggregate_version,
            "home_region": home_region,
            "occurred_at": occurred_at.astimezone(UTC).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "payload": payload,
        }
    ).encode()


def publish_once(pool: ConnectionPool, kinesis, stream: str, region: str) -> int:
    """Publish one batch of this region's unpublished events; return how many were accepted.

    The outbox table is replicated to every region, so each region publishes only the rows it
    wrote. A record Kinesis rejects stays unpublished and is retried on the next pass; a crash
    after the put and before the update publishes it again, which the lakehouse dedups by
    event_id.
    """
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT event_id, event_type, aggregate_id, aggregate_version, home_region,"
            " occurred_at, payload FROM outbox WHERE published_at IS NULL AND home_region = %s"
            " ORDER BY occurred_at LIMIT %s",
            (region, BATCH),
        ).fetchall()
    if not rows:
        return 0

    result = kinesis.put_records(
        StreamName=stream,
        Records=[
            # One aggregate's events land on one shard. PutRecords does not keep their order;
            # the lakehouse restores it from aggregate_version.
            {"Data": envelope(**row), "PartitionKey": str(row["aggregate_id"])}
            for row in rows
        ],
    )
    accepted = [
        row["event_id"]
        for row, out in zip(rows, result["Records"], strict=True)
        if "ErrorCode" not in out
    ]
    if accepted:
        try:
            with pool.connection() as conn, conn.transaction():
                conn.cursor().executemany(
                    "UPDATE outbox SET published_at = %s WHERE event_id = %s",
                    [(datetime.now(UTC), event_id) for event_id in accepted],
                )
        except psycopg.Error as err:
            # For example an OCC conflict with an overlapping poller run. The rows are published
            # again on the next pass, and the lakehouse drops the duplicates.
            log.warning("marking %d events published failed: %s", len(accepted), err)
    return len(accepted)


def run_poller(
    pool: ConnectionPool,
    kinesis,
    stream: str,
    region: str,
    *,
    seconds: float = 55,
    idle_sleep_s: float = 1,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Publish until `seconds` have passed, sleeping while the outbox is empty; return the count.
    EventBridge starts one run a minute."""
    deadline, total = clock() + seconds, 0
    while clock() < deadline:
        published = publish_once(pool, kinesis, stream, region)
        total += published
        if published == 0:
            sleep(idle_sleep_s)
    return total
