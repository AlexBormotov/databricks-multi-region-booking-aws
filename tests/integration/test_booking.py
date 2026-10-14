import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from booking.service import BookingRequest, availability, book, cancel

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


def test_concurrent_same_room_night(pool, room):
    n = 1000
    with ThreadPoolExecutor(max_workers=100) as workers:
        codes = list(
            workers.map(
                lambda i: (
                    book(pool, f"key-{i}", stay(room), region=REGION, hold_ttl=HOLD).status_code
                ),
                range(n),
            )
        )

    assert Counter(codes) == {201: 1, 409: n - 1}
    assert scalar(pool, "SELECT count(*) FROM bookings") == 1
    assert violations(pool) == []


def test_idempotent_replay(pool, room):
    req = stay(room)
    first = hold(pool, "same-key", req)
    replay = hold(pool, "same-key", req)

    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.body == first.body
    assert scalar(pool, "SELECT count(*) FROM bookings") == 1
    assert scalar(pool, "SELECT count(*) FROM outbox") == 1


def test_idempotency_key_reused_with_other_body(pool, room):
    assert hold(pool, "same-key", stay(room)).status_code == 201
    other = hold(pool, "same-key", stay(room, check_in=date(2027, 2, 1)))

    assert other.status_code == 422
    assert scalar(pool, "SELECT count(*) FROM bookings") == 1


def test_overlapping_stay_conflicts_and_adjacent_stay_does_not(pool, room):
    assert hold(pool, "a", stay(room, date(2027, 1, 10), length=3)).status_code == 201
    assert hold(pool, "b", stay(room, date(2027, 1, 12), length=2)).status_code == 409
    assert hold(pool, "c", stay(room, date(2027, 1, 13), length=2)).status_code == 201
    assert violations(pool) == []


def test_stale_hold_takeover(pool, room):
    first = hold(pool, "first", stay(room, length=2))
    later = T0 + HOLD + timedelta(seconds=1)
    second = hold(pool, "second", stay(room), at=later)

    assert (first.status_code, second.status_code) == (201, 201)
    stale_id = uuid.UUID(first.body["booking_id"])
    assert scalar(pool, "SELECT status FROM bookings WHERE booking_id = %s", stale_id) == "expired"
    assert (
        scalar(
            pool,
            "SELECT aggregate_version FROM outbox WHERE aggregate_id = %s"
            " AND event_type = 'BookingExpired'",
            stale_id,
        )
        == 2
    )
    # Both nights of the expired hold are released, not only the one taken over.
    assert scalar(pool, "SELECT count(*) FROM room_night") == 1
    assert violations(pool) == []


def test_live_hold_is_not_taken_over(pool, room):
    assert hold(pool, "first", stay(room)).status_code == 201
    almost = T0 + HOLD - timedelta(seconds=1)
    assert hold(pool, "second", stay(room), at=almost).status_code == 409


def test_cancel_releases_the_room_once(pool, room):
    booking_id = uuid.UUID(hold(pool, "first", stay(room)).body["booking_id"])
    hotel_id, room_id = room
    nights = (date(2027, 1, 10), date(2027, 1, 11))

    assert availability(pool, hotel_id, *nights, clock=lambda: T0) == []
    assert cancel(pool, booking_id, region=REGION, clock=lambda: T0).status_code == 200
    assert availability(pool, hotel_id, *nights, clock=lambda: T0) == [room_id]
    assert cancel(pool, booking_id, region=REGION, clock=lambda: T0).status_code == 409
    assert cancel(pool, uuid.uuid4(), region=REGION).status_code == 404
    assert hold(pool, "second", stay(room)).status_code == 201
