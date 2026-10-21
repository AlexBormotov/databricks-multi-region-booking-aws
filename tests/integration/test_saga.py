import uuid
from datetime import timedelta

from support import HOLD, REGION, T0, booking, booking_events, count, hold, stay, violations

from booking.saga import confirm, expire
from booking.service import SKEW, availability

LATE = T0 + HOLD + SKEW + timedelta(seconds=1)


def held(db, room):
    return uuid.UUID(hold(db, "key", stay(room, length=2)).body["booking_id"])


def test_payment_in_time_confirms(db, room):
    booking_id = held(db, room)
    response = confirm(db, booking_id, region=REGION, clock=lambda: T0 + HOLD / 2)

    assert response.status_code == 200
    assert response.body["status"] == "confirmed"
    assert booking_events(db, booking_id) == [("BookingHeld", 1), ("BookingConfirmed", 2)]
    # The claims no longer expire, so a later booking cannot take them over.
    assert all("expires_ms" not in c for c in db.scan("room-nights"))
    assert hold(db, "other", stay(room), at=LATE).status_code == 409
    # A retried step changes nothing.
    assert confirm(db, booking_id, region=REGION, clock=lambda: T0 + HOLD).status_code == 200
    assert len(booking_events(db, booking_id)) == 2


def test_payment_after_expiry(db, room):
    booking_id = held(db, room)
    late = T0 + HOLD + timedelta(seconds=1)
    response = confirm(db, booking_id, region=REGION, clock=lambda: late)

    assert response.status_code == 409
    assert response.body["status"] == "expired"
    assert response.body["refunded"] is True
    assert booking_events(db, booking_id) == [
        ("BookingHeld", 1),
        ("BookingExpired", 2),
        ("PaymentRefunded", 2),
    ]
    assert count(db, "room-nights") == 0
    # A retried step refunds once.
    confirm(db, booking_id, region=REGION, clock=lambda: late)
    assert len(booking_events(db, booking_id)) == 3


def test_payment_after_takeover_is_refunded(db, room):
    """The saga's clock lags: it still sees the hold as live, but another booking already took
    a night over and expired the hold. The payment is refunded."""
    booking_id = held(db, room)
    assert hold(db, "other", stay(room), at=LATE).status_code == 201
    assert booking(db, booking_id)["status"] == "expired"

    response = confirm(db, booking_id, region=REGION, clock=lambda: T0 + HOLD / 2)
    assert response.status_code == 409
    assert ("PaymentRefunded", 2) in booking_events(db, booking_id)
    assert violations(db, LATE) == []


def test_lost_claim_on_a_pending_booking_expires_it(db, room):
    """Same race, but the takeover's best-effort expiry did not happen: the claim check alone
    stops the confirmation."""
    booking_id = held(db, room)
    other = hold(db, "other", stay(room), at=LATE)
    db.client.update_item(
        TableName=db.name("bookings"),
        Key={"booking_id": {"S": str(booking_id)}},
        UpdateExpression="SET #s = :p, #v = :one",
        ExpressionAttributeNames={"#s": "status", "#v": "version"},
        ExpressionAttributeValues={":p": {"S": "pending"}, ":one": {"N": "1"}},
    )

    assert confirm(db, booking_id, region=REGION, clock=lambda: T0 + HOLD / 2).status_code == 409
    assert booking(db, booking_id)["status"] == "expired"
    # The night the other booking took over is still its own.
    assert {c["booking_id"] for c in db.scan("room-nights")} == {other.body["booking_id"]}


def test_timeout_expires_and_releases(db, room):
    booking_id = held(db, room)
    response = expire(db, booking_id, region=REGION, clock=lambda: T0 + HOLD)

    assert response.body["status"] == "expired"
    assert count(db, "room-nights") == 0
    hotel_id, room_id = room
    req = stay(room)
    assert availability(db, hotel_id, req.check_in, req.check_out) == [room_id]


def test_timeout_after_confirm_changes_nothing(db, room):
    booking_id = held(db, room)
    confirm(db, booking_id, region=REGION, clock=lambda: T0)

    assert expire(db, booking_id, region=REGION, clock=lambda: T0 + HOLD).body["status"] == (
        "confirmed"
    )
    assert len(booking_events(db, booking_id)) == 2


def test_unknown_booking(db):
    assert confirm(db, uuid.uuid4(), region=REGION).status_code == 404
    assert expire(db, uuid.uuid4(), region=REGION).status_code == 404
