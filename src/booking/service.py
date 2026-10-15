"""Booking transactions under optimistic concurrency: of concurrent claims on one room-night, the
first to commit wins and every other one gets 409.
"""

import hashlib
import json
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import psycopg
from psycopg import Cursor
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from booking.domain import IllegalTransition, Status, is_live, nights, transition, uuid7
from booking.outbox import insert_event

MAX_ATTEMPTS = 5
BACKOFF_BASE_S = 0.02
BACKOFF_CAP_S = 1.0
# 40001 is DSQL's OCC conflict at commit (OC000, or OC001 for a schema change) and PostgreSQL's
# serialization failure; 23505 is how PostgreSQL reports a second insert of the same room-night.
RETRYABLE = {"40001", "23505", "OC000", "OC001"}

BOOKING_FIELDS = (
    "booking_id",
    "hotel_id",
    "room_id",
    "guest_id",
    "check_in",
    "check_out",
    "status",
    "expires_at",
    "amount_minor",
    "currency",
    "version",
    "home_region",
    "created_at",
    "updated_at",
)
BOOKING_COLUMNS = ", ".join(BOOKING_FIELDS)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class BookingRequest:
    hotel_id: uuid.UUID
    room_id: uuid.UUID
    guest_id: uuid.UUID
    check_in: date
    check_out: date

    def digest(self) -> str:
        canonical = json.dumps({k: str(v) for k, v in vars(self).items()}, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class Response:
    status_code: int
    body: dict
    headers: dict = field(default_factory=dict)


class Abort(Exception):
    """Ends a transaction with a final response, rolling it back; never retried."""

    def __init__(self, status_code: int, error: str):
        self.response = Response(status_code, {"error": error})


def run_transaction(
    pool: ConnectionPool,
    work: Callable[[Cursor], Response],
    *,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
) -> Response:
    """Run work in one transaction; retry conflicts with exponential backoff and full jitter."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            with pool.connection() as conn, conn.transaction():
                with conn.cursor(row_factory=dict_row) as cur:
                    return work(cur)
        except Abort as stop:
            return stop.response
        except psycopg.Error as err:
            if err.sqlstate not in RETRYABLE:
                raise
            if attempt < MAX_ATTEMPTS - 1:
                sleep(rng() * min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2**attempt))
    return Response(503, {"error": "too much contention, retry later"}, {"Retry-After": "1"})


def snapshot(booking: dict) -> dict:
    """The booking as JSON: the response body and every event payload."""
    return {
        k: v.isoformat() if isinstance(v, date) else str(v) if isinstance(v, uuid.UUID) else v
        for k, v in booking.items()
    }


def release_claims(cur: Cursor, booking: dict) -> None:
    """Delete the booking's room-night claims by primary key."""
    cur.executemany(
        "DELETE FROM room_night WHERE hotel_id = %s AND room_id = %s AND night = %s"
        " AND booking_id = %s",
        [
            (booking["hotel_id"], booking["room_id"], night, booking["booking_id"])
            for night in nights(booking["check_in"], booking["check_out"])
        ],
    )


def change_status(
    cur: Cursor, booking: dict, target: Status, event_type: str, *, region: str, at: datetime
) -> dict:
    """Move a booking to target, release its claims unless confirmed, and write the event."""
    transition(Status(booking["status"]), target)
    updated = {
        **booking,
        "status": target.value,
        "version": booking["version"] + 1,
        "updated_at": at,
    }
    cur.execute(
        "UPDATE bookings SET status = %s, version = %s, updated_at = %s WHERE booking_id = %s",
        (updated["status"], updated["version"], at, booking["booking_id"]),
    )
    if target != Status.CONFIRMED:
        release_claims(cur, booking)
    insert_event(
        cur,
        aggregate_id=booking["booking_id"],
        aggregate_version=updated["version"],
        event_type=event_type,
        payload=snapshot(updated),
        home_region=region,
        occurred_at=at,
    )
    return updated


def book(
    pool: ConnectionPool,
    idem_key: str,
    req: BookingRequest,
    *,
    region: str,
    hold_ttl: timedelta,
    clock: Clock = utc_now,
    **retry,
) -> Response:
    """Hold a room for the stay: 201 new hold, 200 replay, 404, 409, 422, or 503 after retries."""
    stay = nights(req.check_in, req.check_out)
    request_hash = req.digest()

    def work(cur: Cursor) -> Response:
        at = clock()
        seen = cur.execute(
            "SELECT request_hash, response_body FROM idempotency_keys WHERE idem_key = %s",
            (idem_key,),
        ).fetchone()
        if seen:
            if seen["request_hash"] != request_hash:
                raise Abort(422, "Idempotency-Key was used with a different request")
            return Response(200, json.loads(seen["response_body"]))

        rate = cur.execute(
            "SELECT r.base_rate_minor, h.currency FROM rooms r"
            " JOIN hotels h ON h.hotel_id = r.hotel_id WHERE r.room_id = %s AND r.hotel_id = %s",
            (req.room_id, req.hotel_id),
        ).fetchone()
        if rate is None:
            raise Abort(404, "unknown hotel or room")

        claimants = {
            row["booking_id"]: row
            for row in cur.execute(
                f"SELECT {', '.join(f'b.{c}' for c in BOOKING_FIELDS)}"
                " FROM room_night rn JOIN bookings b ON b.booking_id = rn.booking_id"
                " WHERE rn.hotel_id = %s AND rn.room_id = %s AND rn.night >= %s AND rn.night < %s",
                (req.hotel_id, req.room_id, req.check_in, req.check_out),
            )
        }
        if any(is_live(Status(b["status"]), b["expires_at"], at) for b in claimants.values()):
            raise Abort(409, "room is already booked for one of these nights")
        # Lazy expiry: a claim left by a hold that timed out is taken over.
        for stale in claimants.values():
            if stale["status"] == Status.PENDING:
                change_status(cur, stale, Status.EXPIRED, "BookingExpired", region=region, at=at)
            else:
                release_claims(cur, stale)

        booking = {
            "booking_id": uuid7(),
            "hotel_id": req.hotel_id,
            "room_id": req.room_id,
            "guest_id": req.guest_id,
            "check_in": req.check_in,
            "check_out": req.check_out,
            "status": Status.PENDING.value,
            "expires_at": at + hold_ttl,
            "amount_minor": rate["base_rate_minor"] * len(stay),
            "currency": rate["currency"],
            "version": 1,
            "home_region": region,
            "created_at": at,
            "updated_at": at,
        }
        cur.execute(
            f"INSERT INTO bookings ({BOOKING_COLUMNS})"
            f" VALUES ({', '.join(['%s'] * len(BOOKING_FIELDS))})",
            tuple(booking[c] for c in BOOKING_FIELDS),
        )
        cur.executemany(
            "INSERT INTO room_night (hotel_id, room_id, night, booking_id) VALUES (%s, %s, %s, %s)",
            [(req.hotel_id, req.room_id, night, booking["booking_id"]) for night in stay],
        )
        body = snapshot(booking)
        cur.execute(
            "INSERT INTO idempotency_keys (idem_key, request_hash, booking_id, status_code,"
            " response_body, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (idem_key, request_hash, booking["booking_id"], 201, json.dumps(body), at),
        )
        insert_event(
            cur,
            aggregate_id=booking["booking_id"],
            aggregate_version=1,
            event_type="BookingHeld",
            payload=body,
            home_region=region,
            occurred_at=at,
        )
        return Response(201, body)

    return run_transaction(pool, work, **retry)


def cancel(
    pool: ConnectionPool, booking_id: uuid.UUID, *, region: str, clock: Clock = utc_now, **retry
) -> Response:
    """Cancel a pending or confirmed booking: 200, 404, or 409 for any other state."""

    def work(cur: Cursor) -> Response:
        at = clock()
        booking = cur.execute(
            f"SELECT {BOOKING_COLUMNS} FROM bookings WHERE booking_id = %s FOR UPDATE",
            (booking_id,),
        ).fetchone()
        if booking is None:
            raise Abort(404, "unknown booking")
        if booking["status"] == Status.PENDING and booking["expires_at"] <= at:
            raise Abort(409, "the hold has expired")
        try:
            updated = change_status(
                cur, booking, Status.CANCELLED, "BookingCancelled", region=region, at=at
            )
        except IllegalTransition:
            raise Abort(409, f"a {booking['status']} booking cannot be cancelled") from None
        return Response(200, snapshot(updated))

    return run_transaction(pool, work, **retry)


def availability(
    pool: ConnectionPool,
    hotel_id: uuid.UUID,
    check_in: date,
    check_out: date,
    *,
    clock: Clock = utc_now,
) -> list[uuid.UUID]:
    """Rooms of the hotel with no live claim on any night of the stay."""
    nights(check_in, check_out)
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT r.room_id FROM rooms r WHERE r.hotel_id = %s AND NOT EXISTS ("
            " SELECT 1 FROM room_night rn JOIN bookings b ON b.booking_id = rn.booking_id"
            " WHERE rn.hotel_id = r.hotel_id AND rn.room_id = r.room_id"
            " AND rn.night >= %s AND rn.night < %s"
            " AND (b.status = 'confirmed' OR (b.status = 'pending' AND b.expires_at > %s)))"
            " ORDER BY r.room_id",
            (hotel_id, check_in, check_out, clock()),
        ).fetchall()
    return [row[0] for row in rows]
