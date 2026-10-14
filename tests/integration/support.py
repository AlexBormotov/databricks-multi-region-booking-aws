"""Helpers shared by the integration tests."""

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from booking.service import BookingRequest, book

INVARIANT = (Path(__file__).parents[2] / "sql" / "invariant.sql").read_text(encoding="utf-8")
HOLD = timedelta(minutes=15)
REGION = "us-east-1"
T0 = datetime(2027, 1, 1, 12, tzinfo=UTC)


def stay(room, check_in=date(2027, 1, 10), length=1):
    hotel_id, room_id = room
    return BookingRequest(
        hotel_id, room_id, uuid.uuid4(), check_in, check_in + timedelta(days=length)
    )


def hold(pool, key, req, at=T0):
    return book(pool, key, req, region=REGION, hold_ttl=HOLD, clock=lambda: at)


def violations(pool):
    with pool.connection() as conn:
        return conn.execute(INVARIANT).fetchall()


def scalar(pool, query, *params):
    with pool.connection() as conn:
        return conn.execute(query, params).fetchone()[0]
