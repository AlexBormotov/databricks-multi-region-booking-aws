"""Bookings on DynamoDB (ADR 2, plan D16). Each night of a stay is one claim item, taken with a
conditional write: of concurrent claims on one room-night exactly one succeeds, and every other
booking gets 409.
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from botocore.exceptions import ClientError

from booking.domain import IllegalTransition, Status, nights, transition, uuid7
from booking.store import MAX_ATTEMPTS, Busy, Store, condition_failed, dump

log = logging.getLogger(__name__)

# A hold is taken over only this long after it expired, so the holder's saga, on a clock that is
# behind, can no longer confirm it.
SKEW = timedelta(seconds=5)
# An idempotency key left in progress by a crashed request is free again after this.
LEASE = timedelta(seconds=30)

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
# The response and event fields kept as epoch milliseconds in the store.
TIME_FIELDS = {"expires_at": "expires_ms", "created_at": "created_ms", "updated_at": "updated_ms"}

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def ms(at: datetime) -> int:
    return round(at.timestamp() * 1000)


def ms_of(span: timedelta) -> int:
    return round(span.total_seconds() * 1000)


def iso(at_ms: int) -> str:
    return datetime.fromtimestamp(at_ms / 1000, UTC).isoformat()


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


BUSY = Response(503, {"error": "too much contention, retry later"}, {"Retry-After": "1"})


def snapshot(booking: dict) -> dict:
    """The booking as JSON: the response body and every event payload."""
    return {
        f: iso(booking[TIME_FIELDS[f]]) if f in TIME_FIELDS else booking[f] for f in BOOKING_FIELDS
    }


def claim_key(room_id: str, night: date) -> dict:
    return {"room_night": f"{room_id}#{night.isoformat()}"}


def stay_of(booking: dict) -> list[date]:
    return nights(date.fromisoformat(booking["check_in"]), date.fromisoformat(booking["check_out"]))


def release(store: Store, booking_id: str, room_id: str, stay: list[date]) -> None:
    """Delete the claims this booking holds; a night another booking holds is left alone."""
    for night in stay:
        try:
            store.call(
                "delete_item",
                "room-nights",
                Key=dump(claim_key(room_id, night)),
                ConditionExpression="booking_id = :b",
                ExpressionAttributeValues=dump({":b": booking_id}),
            )
        except ClientError as err:
            if not condition_failed(err):
                raise


def change_status(
    store: Store,
    booking: dict,
    target: Status,
    *,
    region: str,
    at_ms: int,
    guard: str = "",
    guard_values: dict | None = None,
) -> dict:
    """Move a booking to target if nobody changed it since it was read, then release its claims
    unless it is now confirmed. A failed condition raises ClientError: read it again."""
    transition(Status(booking["status"]), target)
    updated = {
        **booking,
        "status": target.value,
        "version": booking["version"] + 1,
        "updated_ms": at_ms,
        "changed_in": region,
    }
    store.call(
        "update_item",
        "bookings",
        Key=dump({"booking_id": booking["booking_id"]}),
        UpdateExpression="SET #status = :status, #version = :version, updated_ms = :at,"
        " changed_in = :region",
        ConditionExpression="#version = :read" + (f" AND {guard}" if guard else ""),
        ExpressionAttributeNames={"#status": "status", "#version": "version"},
        ExpressionAttributeValues=dump(
            {
                ":status": target.value,
                ":version": updated["version"],
                ":at": at_ms,
                ":region": region,
                ":read": booking["version"],
                **(guard_values or {}),
            }
        ),
    )
    if target != Status.CONFIRMED:
        release(store, booking["booking_id"], booking["room_id"], stay_of(booking))
    return updated


def with_booking(
    store: Store, booking_id: uuid.UUID, decide: Callable[[dict], Response]
) -> Response:
    """Read the booking and decide on it; when a conditional write finds the booking changed,
    read it again. 404 if it does not exist, 503 when it keeps changing."""
    for _ in range(MAX_ATTEMPTS):
        booking = store.get("bookings", {"booking_id": str(booking_id)})
        if booking is None:
            return Response(404, {"error": "unknown booking"})
        try:
            return decide(booking)
        except ClientError as err:
            if not condition_failed(err):
                raise
        except Busy:
            return BUSY
    return BUSY


def _take_key(store: Store, idem_key: str, request_hash: str, now: int) -> Response | None:
    """None if this request now owns the key; otherwise the answer for a key already used."""
    try:
        store.call(
            "put_item",
            "idempotency",
            Item=dump(
                {
                    "idem_key": idem_key,
                    "request_hash": request_hash,
                    "state": "in_progress",
                    "started_ms": now,
                }
            ),
            ConditionExpression="attribute_not_exists(idem_key)"
            " OR (#state = :in_progress AND started_ms < :lease_end)",
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues=dump(
                {":in_progress": "in_progress", ":lease_end": now - ms_of(LEASE)}
            ),
        )
        return None
    except ClientError as err:
        if not condition_failed(err):
            raise
    seen = store.get("idempotency", {"idem_key": idem_key})
    if seen and seen["request_hash"] != request_hash:
        return Response(422, {"error": "Idempotency-Key was used with a different request"})
    if seen and seen["state"] == "done":
        return Response(200, json.loads(seen["response"]))
    return Response(
        409, {"error": "a request with this Idempotency-Key is in progress"}, {"Retry-After": "1"}
    )


def _drop_key(store: Store, idem_key: str, request_hash: str) -> None:
    """Free the key after an answer that is not kept, so a retry is evaluated again."""
    try:
        store.call(
            "delete_item",
            "idempotency",
            Key=dump({"idem_key": idem_key}),
            ConditionExpression="request_hash = :h AND #state = :in_progress",
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues=dump({":h": request_hash, ":in_progress": "in_progress"}),
        )
    except (ClientError, Busy):
        log.warning("could not free Idempotency-Key %s; its lease frees it", idem_key)


def _expire_stale(store: Store, booking_id: str, *, region: str, now: int) -> None:
    """A taken-over hold's booking becomes expired. Best effort: the saga's expire step does the
    same, and the invariant does not depend on it."""
    try:
        booking = store.get("bookings", {"booking_id": booking_id})
        if booking and booking["status"] == Status.PENDING and booking["expires_ms"] < now:
            change_status(store, booking, Status.EXPIRED, region=region, at_ms=now)
    except (ClientError, Busy):
        log.warning("could not expire the taken-over hold %s", booking_id, exc_info=True)


def _hold(
    store: Store, req: BookingRequest, *, region: str, now: int, hold_ttl: timedelta
) -> Response:
    room = store.get("rooms", {"hotel_id": str(req.hotel_id), "room_id": str(req.room_id)})
    if room is None:
        return Response(404, {"error": "unknown hotel or room"})

    booking_id, room_id = str(uuid7()), str(req.room_id)
    expires = now + ms_of(hold_ttl)
    stay = nights(req.check_in, req.check_out)
    taken, stale = [], set()
    try:
        # Date order, so two bookings of overlapping stays meet first on the earliest shared night.
        for night in stay:
            old = store.call(
                "put_item",
                "room-nights",
                Item=dump(
                    {**claim_key(room_id, night), "booking_id": booking_id, "expires_ms": expires}
                ),
                # Free, or a hold that expired more than SKEW ago (taken over).
                ConditionExpression="attribute_not_exists(room_night) OR expires_ms < :takeover",
                ExpressionAttributeValues=dump({":takeover": now - ms_of(SKEW)}),
                ReturnValues="ALL_OLD",
            ).get("Attributes")
            taken.append(night)
            if old:
                stale.add(old["booking_id"]["S"])
    except ClientError as err:
        if not condition_failed(err):
            raise
        release(store, booking_id, room_id, taken)
        return Response(409, {"error": "room is already booked for one of these nights"})
    except Busy:
        release(store, booking_id, room_id, taken)
        raise

    for stale_id in stale:
        _expire_stale(store, stale_id, region=region, now=now)
    booking = {
        "booking_id": booking_id,
        "hotel_id": str(req.hotel_id),
        "room_id": room_id,
        "guest_id": str(req.guest_id),
        "check_in": req.check_in.isoformat(),
        "check_out": req.check_out.isoformat(),
        "status": Status.PENDING.value,
        "expires_ms": expires,
        "amount_minor": room["base_rate_minor"] * len(stay),
        "currency": room["currency"],
        "version": 1,
        "home_region": region,
        "created_ms": now,
        "updated_ms": now,
        "changed_in": region,
    }
    store.call(
        "put_item",
        "bookings",
        Item=dump(booking),
        ConditionExpression="attribute_not_exists(booking_id)",
    )
    return Response(201, snapshot(booking))


def book(
    store: Store,
    idem_key: str,
    req: BookingRequest,
    *,
    region: str,
    hold_ttl: timedelta,
    clock: Clock = utc_now,
) -> Response:
    """Hold a room for the stay: 201 new hold, 200 replay, 404, 409, 422, or 503."""
    nights(req.check_in, req.check_out)
    request_hash, now = req.digest(), ms(clock())
    try:
        seen = _take_key(store, idem_key, request_hash, now)
    except Busy:
        return BUSY
    if seen is not None:
        return seen
    try:
        response = _hold(store, req, region=region, now=now, hold_ttl=hold_ttl)
    except Busy:
        response = BUSY
    if response.status_code != 201:
        _drop_key(store, idem_key, request_hash)
        return response
    try:
        store.call(
            "update_item",
            "idempotency",
            Key=dump({"idem_key": idem_key}),
            UpdateExpression="SET #state = :done, #response = :response",
            ExpressionAttributeNames={"#state": "state", "#response": "response"},
            ExpressionAttributeValues=dump(
                {":done": "done", ":response": json.dumps(response.body)}
            ),
        )
    except Busy:
        # The hold stands; a replay within the lease gets 409 and then a second hold.
        log.warning("could not store the response for Idempotency-Key %s", idem_key)
    return response


def cancel(store: Store, booking_id: uuid.UUID, *, region: str, clock: Clock = utc_now) -> Response:
    """Cancel a pending or confirmed booking: 200, 404, or 409 for any other state."""

    def decide(booking: dict) -> Response:
        now = ms(clock())
        if booking["status"] == Status.PENDING and booking["expires_ms"] <= now:
            return Response(409, {"error": "the hold has expired"})
        try:
            updated = change_status(store, booking, Status.CANCELLED, region=region, at_ms=now)
        except IllegalTransition:
            return Response(409, {"error": f"a {booking['status']} booking cannot be cancelled"})
        return Response(200, snapshot(updated))

    return with_booking(store, booking_id, decide)


def availability(
    store: Store,
    hotel_id: uuid.UUID,
    check_in: date,
    check_out: date,
    *,
    clock: Clock = utc_now,
) -> list[uuid.UUID]:
    """Rooms of the hotel that a booking for the stay could claim now."""
    stay = nights(check_in, check_out)
    rooms = sorted(
        item["room_id"]["S"]
        for item in store.call(
            "query",
            "rooms",
            KeyConditionExpression="hotel_id = :h",
            ExpressionAttributeValues=dump({":h": str(hotel_id)}),
            ConsistentRead=True,
        )["Items"]
    )
    takeover = ms(clock()) - ms_of(SKEW)
    claims = store.get_many("room-nights", [claim_key(r, n) for r in rooms for n in stay])
    taken = {
        c["room_night"].split("#")[0]
        for c in claims
        if "expires_ms" not in c or c["expires_ms"] >= takeover
    }
    return [uuid.UUID(r) for r in rooms if r not in taken]
