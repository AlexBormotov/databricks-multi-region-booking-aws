import uuid
from datetime import timedelta

from support import HOLD, REGION, T0, hold, scalar, stay, violations

from booking.saga import confirm, expire
from booking.service import availability


def held(pool, room):
    return uuid.UUID(hold(pool, "key", stay(room)).body["booking_id"])


def events(pool, booking_id):
    with pool.connection() as conn:
        return [
            row
            for row in conn.execute(
                "SELECT event_type, aggregate_version FROM outbox WHERE aggregate_id = %s"
                " ORDER BY aggregate_version, event_type",
                (booking_id,),
            )
        ]


def test_payment_in_time_confirms(pool, room):
    booking_id = held(pool, room)
    response = confirm(pool, booking_id, region=REGION, clock=lambda: T0 + HOLD / 2)

    assert response.status_code == 200
    assert response.body["status"] == "confirmed"
    assert events(pool, booking_id) == [("BookingHeld", 1), ("BookingConfirmed", 2)]
    # A retried step changes nothing.
    assert confirm(pool, booking_id, region=REGION, clock=lambda: T0 + HOLD).status_code == 200
    assert len(events(pool, booking_id)) == 2


def test_payment_after_expiry(pool, room):
    booking_id = held(pool, room)
    late = T0 + HOLD + timedelta(seconds=1)
    response = confirm(pool, booking_id, region=REGION, clock=lambda: late)

    assert response.status_code == 409
    assert response.body["status"] == "expired"
    assert response.body["refunded"] is True
    assert events(pool, booking_id) == [
        ("BookingHeld", 1),
        ("BookingExpired", 2),
        ("PaymentRefunded", 2),
    ]
    # A retried step refunds once.
    confirm(pool, booking_id, region=REGION, clock=lambda: late)
    assert len(events(pool, booking_id)) == 3


def test_payment_after_takeover_is_refunded(pool, room):
    booking_id = held(pool, room)
    later = T0 + HOLD + timedelta(seconds=1)
    assert hold(pool, "other", stay(room), at=later).status_code == 201

    assert confirm(pool, booking_id, region=REGION, clock=lambda: later).status_code == 409
    assert ("PaymentRefunded", 2) in events(pool, booking_id)
    assert violations(pool) == []


def test_timeout_expires_and_releases(pool, room):
    booking_id = held(pool, room)
    response = expire(pool, booking_id, region=REGION, clock=lambda: T0 + HOLD)

    assert response.body["status"] == "expired"
    assert scalar(pool, "SELECT count(*) FROM room_night") == 0
    hotel_id, room_id = room
    req = stay(room)
    assert availability(pool, hotel_id, req.check_in, req.check_out) == [room_id]


def test_timeout_after_confirm_changes_nothing(pool, room):
    booking_id = held(pool, room)
    confirm(pool, booking_id, region=REGION, clock=lambda: T0)

    assert expire(pool, booking_id, region=REGION, clock=lambda: T0 + HOLD).body["status"] == (
        "confirmed"
    )
    assert len(events(pool, booking_id)) == 2


def test_unknown_booking(pool):
    assert confirm(pool, uuid.uuid4(), region=REGION).status_code == 404
    assert expire(pool, uuid.uuid4(), region=REGION).status_code == 404
