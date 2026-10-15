"""Hold saga steps, run by Step Functions: a simulated payment races the hold's TTL, and both
outcomes end in an update guarded by the booking's state. Every step is safe to retry.
"""

import random
import time
import uuid
from collections.abc import Callable

from psycopg import Cursor
from psycopg_pool import ConnectionPool

from booking.domain import Status
from booking.outbox import insert_event
from booking.service import (
    BOOKING_COLUMNS,
    Abort,
    Clock,
    Response,
    change_status,
    run_transaction,
    snapshot,
    utc_now,
)

# One payment per booking, so one refund: a name-based id makes a retried step a no-op.
REFUND_NAMESPACE = uuid.UUID("5f2b8f0e-3d0a-4c56-9a51-6b7c0c1d2e3f")


class PaymentDeclined(Exception):
    pass


def pay(
    *,
    failure_rate: float,
    latency_s: float,
    rng: Callable[[], float] = random.random,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Simulated payment provider: takes latency_s, then declines with probability failure_rate."""
    sleep(latency_s)
    if rng() < failure_rate:
        raise PaymentDeclined()


def _locked(cur: Cursor, booking_id: uuid.UUID) -> dict:
    booking = cur.execute(
        f"SELECT {BOOKING_COLUMNS} FROM bookings WHERE booking_id = %s FOR UPDATE", (booking_id,)
    ).fetchone()
    if booking is None:
        raise Abort(404, "unknown booking")
    return booking


def confirm(
    pool: ConnectionPool, booking_id: uuid.UUID, *, region: str, clock: Clock = utc_now, **retry
) -> Response:
    """Payment succeeded. Confirms a hold that is still live (200). A payment that arrives after
    the hold expired, or after a cancel, is refunded and the booking is not confirmed (409)."""

    def work(cur: Cursor) -> Response:
        at = clock()
        booking = _locked(cur, booking_id)
        if booking["status"] == Status.CONFIRMED:
            return Response(200, snapshot(booking))
        if booking["status"] == Status.PENDING and booking["expires_at"] > at:
            confirmed = change_status(
                cur, booking, Status.CONFIRMED, "BookingConfirmed", region=region, at=at
            )
            return Response(200, snapshot(confirmed))

        if booking["status"] == Status.PENDING:
            booking = change_status(
                cur, booking, Status.EXPIRED, "BookingExpired", region=region, at=at
            )
        # A refund changes no booking state, so it keeps the current version.
        insert_event(
            cur,
            event_id=uuid.uuid5(REFUND_NAMESPACE, str(booking_id)),
            aggregate_id=booking_id,
            aggregate_version=booking["version"],
            event_type="PaymentRefunded",
            payload={**snapshot(booking), "refund_minor": booking["amount_minor"]},
            home_region=region,
            occurred_at=at,
        )
        return Response(409, {**snapshot(booking), "refunded": True})

    return run_transaction(pool, work, **retry)


def expire(
    pool: ConnectionPool, booking_id: uuid.UUID, *, region: str, clock: Clock = utc_now, **retry
) -> Response:
    """The hold timed out or the payment was declined: expire a pending booking and release its
    room-nights. Any other state is left as it is."""

    def work(cur: Cursor) -> Response:
        at = clock()
        booking = _locked(cur, booking_id)
        if booking["status"] == Status.PENDING:
            booking = change_status(
                cur, booking, Status.EXPIRED, "BookingExpired", region=region, at=at
            )
        return Response(200, snapshot(booking))

    return run_transaction(pool, work, **retry)
