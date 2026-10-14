"""Outbox: events written in the same transaction as the state change they describe."""

import uuid
from datetime import datetime

from psycopg import Cursor
from psycopg.types.json import Jsonb

from booking.domain import uuid7


def insert_event(
    cur: Cursor,
    *,
    aggregate_id: uuid.UUID,
    aggregate_version: int,
    event_type: str,
    payload: dict,
    home_region: str,
    occurred_at: datetime,
) -> None:
    cur.execute(
        "INSERT INTO outbox (event_id, aggregate_id, aggregate_version, event_type, payload,"
        " home_region, occurred_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            uuid7(),
            aggregate_id,
            aggregate_version,
            event_type,
            Jsonb(payload),
            home_region,
            occurred_at,
        ),
    )
