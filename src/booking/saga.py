"""Hold saga steps, run by Step Functions: a simulated payment races the hold's TTL, and both
outcomes end in a conditional update of the booking. Every step is safe to retry.
"""

import random
import time
import uuid
from collections.abc import Callable

from botocore.exceptions import ClientError

from booking.domain import Status
from booking.service import (
    Clock,
    Response,
    change_status,
    claim_key,
    ms,
    snapshot,
    stay_of,
    utc_now,
    with_booking,
)
from booking.store import Store, condition_failed, dump


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


def _keep_claims(store: Store, booking: dict) -> bool:
    """Make the booking's claims permanent; False if one of them was taken over."""
    for night in stay_of(booking):
        try:
            store.call(
                "update_item",
                "room-nights",
                Key=dump(claim_key(booking["room_id"], night)),
                UpdateExpression="REMOVE expires_ms",
                ConditionExpression="booking_id = :b",
                ExpressionAttributeValues=dump({":b": booking["booking_id"]}),
            )
        except ClientError as err:
            if not condition_failed(err):
                raise
            return False
    return True


def confirm(
    store: Store, booking_id: uuid.UUID, *, region: str, clock: Clock = utc_now
) -> Response:
    """Payment succeeded. Confirms a hold that is still live (200). A payment that arrives after
    the hold expired, or after a cancel, is refunded and the booking is not confirmed (409).

    The claims are made permanent before the booking is confirmed, so a crash between the two
    leaves the room blocked, never sold twice."""

    def decide(booking: dict) -> Response:
        now = ms(clock())
        if booking["status"] == Status.CONFIRMED:
            return Response(200, snapshot(booking))
        live = booking["status"] == Status.PENDING and booking["expires_ms"] > now
        if live and _keep_claims(store, booking):
            confirmed = change_status(
                store,
                booking,
                Status.CONFIRMED,
                region=region,
                at_ms=now,
                guard="expires_ms > :now",
                guard_values={":now": now},
            )
            return Response(200, snapshot(confirmed))

        if booking["status"] == Status.PENDING:
            booking = change_status(store, booking, Status.EXPIRED, region=region, at_ms=now)
        if not booking.get("refunded"):
            # A refund changes no booking state, so it keeps the version.
            store.call(
                "update_item",
                "bookings",
                Key=dump({"booking_id": booking["booking_id"]}),
                UpdateExpression="SET refunded = :yes, updated_ms = :at, changed_in = :region",
                ConditionExpression="attribute_not_exists(refunded)",
                ExpressionAttributeValues=dump({":yes": True, ":at": now, ":region": region}),
            )
            booking = {**booking, "refunded": True}
        return Response(409, {**snapshot(booking), "refunded": True})

    return with_booking(store, booking_id, decide)


def expire(store: Store, booking_id: uuid.UUID, *, region: str, clock: Clock = utc_now) -> Response:
    """The hold timed out or the payment was declined: expire a pending booking and release its
    room-nights. Any other state is left as it is."""

    def decide(booking: dict) -> Response:
        if booking["status"] == Status.PENDING:
            booking = change_status(
                store, booking, Status.EXPIRED, region=region, at_ms=ms(clock())
            )
        return Response(200, snapshot(booking))

    return with_booking(store, booking_id, decide)
