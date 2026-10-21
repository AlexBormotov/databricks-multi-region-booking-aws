import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from support import (
    HOLD,
    REGION,
    T0,
    booking,
    booking_events,
    count,
    hold,
    stay,
    violations,
)

from booking import store
from booking.service import LEASE, SKEW, availability, book, cancel, ms
from booking.store import dump


def test_concurrent_same_room_night(db, room):
    n = 1000
    with ThreadPoolExecutor(max_workers=100) as workers:
        codes = list(
            workers.map(
                lambda i: (
                    book(db, f"key-{i}", stay(room), region=REGION, hold_ttl=HOLD).status_code
                ),
                range(n),
            )
        )

    assert Counter(codes) == {201: 1, 409: n - 1}
    assert count(db, "bookings") == 1
    assert violations(db) == []


def test_concurrent_identical_multi_night_stays(db, room):
    """Every attempt meets the others first on the earliest night, so one wins all three nights
    and every loser releases what it took."""
    with ThreadPoolExecutor(max_workers=50) as workers:
        codes = list(
            workers.map(lambda i: hold(db, f"k{i}", stay(room, length=3)).status_code, range(200))
        )

    assert Counter(codes) == {201: 1, 409: 199}
    [winner] = db.scan("bookings")
    claims = db.scan("room-nights")
    assert len(claims) == 3 and {c["booking_id"] for c in claims} == {winner["booking_id"]}


def test_multi_night_loser_releases(db, room):
    """B wants nights 1-3 but A holds night 2: B takes night 1, loses night 2 and gives night 1
    back. A keeps night 2, and night 3 is never taken."""
    a = hold(db, "a", stay(room, date(2027, 1, 11)))
    assert hold(db, "b", stay(room, date(2027, 1, 10), length=3)).status_code == 409
    claims = db.scan("room-nights")
    assert [(c["room_night"][-10:], c["booking_id"]) for c in claims] == [
        ("2027-01-11", a.body["booking_id"])
    ]


def test_idempotent_replay(db, room):
    req = stay(room)
    first = hold(db, "same-key", req)
    replay = hold(db, "same-key", req)

    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.body == first.body
    assert count(db, "bookings") == 1
    assert booking_events(db, first.body["booking_id"]) == [("BookingHeld", 1)]


def test_key_reused_with_other_request(db, room):
    assert hold(db, "same-key", stay(room)).status_code == 201
    other = hold(db, "same-key", stay(room, check_in=date(2027, 2, 1)))

    assert other.status_code == 422
    assert count(db, "bookings") == 1


def test_key_in_progress_is_refused_until_its_lease_ends(db, room):
    req = stay(room)
    db.client.put_item(
        TableName=db.name("idempotency"),
        Item=dump(
            {
                "idem_key": "k",
                "request_hash": req.digest(),
                "state": "in_progress",
                "started_ms": ms(T0),
            }
        ),
    )
    busy = hold(db, "k", req)
    assert (busy.status_code, busy.headers) == (409, {"Retry-After": "1"})
    assert hold(db, "k", req, at=T0 + LEASE + timedelta(seconds=1)).status_code == 201


def test_a_refused_request_frees_its_key(db, room):
    first = uuid.UUID(hold(db, "first", stay(room)).body["booking_id"])
    assert hold(db, "second", stay(room)).status_code == 409
    assert cancel(db, first, region=REGION, clock=lambda: T0).status_code == 200
    assert hold(db, "second", stay(room)).status_code == 201


def test_unknown_room_is_404(db, room):
    hotel_id, _ = room
    assert hold(db, "k", stay((hotel_id, uuid.uuid4()))).status_code == 404
    assert count(db, "idempotency") == 0


def test_overlapping_stay_conflicts_and_adjacent_stay_does_not(db, room):
    assert hold(db, "a", stay(room, date(2027, 1, 10), length=3)).status_code == 201
    assert hold(db, "b", stay(room, date(2027, 1, 12), length=2)).status_code == 409
    assert hold(db, "c", stay(room, date(2027, 1, 13), length=2)).status_code == 201
    assert violations(db) == []


def test_stale_hold_takeover(db, room):
    first = hold(db, "first", stay(room, length=2))
    stale_id = first.body["booking_id"]
    # Expired, but not by more than the clock-skew allowance: not yet taken over.
    assert hold(db, "early", stay(room), at=T0 + HOLD + timedelta(seconds=1)).status_code == 409

    later = T0 + HOLD + SKEW + timedelta(seconds=1)
    assert hold(db, "second", stay(room), at=later).status_code == 201
    assert booking(db, stale_id)["status"] == "expired"
    assert booking_events(db, stale_id) == [("BookingHeld", 1), ("BookingExpired", 2)]
    # Both nights of the expired hold are released, not only the one taken over.
    assert count(db, "room-nights") == 1
    assert violations(db, later) == []


def test_live_hold_is_not_taken_over(db, room):
    assert hold(db, "first", stay(room)).status_code == 201
    almost = T0 + HOLD - timedelta(seconds=1)
    assert hold(db, "second", stay(room), at=almost).status_code == 409


def test_cancel_releases_the_room_once(db, room):
    booking_id = uuid.UUID(hold(db, "first", stay(room)).body["booking_id"])
    hotel_id, room_id = room
    nights = (date(2027, 1, 10), date(2027, 1, 11))

    assert availability(db, hotel_id, *nights, clock=lambda: T0) == []
    assert cancel(db, booking_id, region=REGION, clock=lambda: T0).status_code == 200
    assert availability(db, hotel_id, *nights, clock=lambda: T0) == [room_id]
    assert cancel(db, booking_id, region=REGION, clock=lambda: T0).status_code == 409
    assert cancel(db, uuid.uuid4(), region=REGION).status_code == 404
    assert hold(db, "second", stay(room)).status_code == 201


def test_invariant_flags_overlap(db):
    """The invariant reads bookings only: two live bookings of one room with overlapping stays
    are a violation even with no claims at all; an adjacent or expired one is not."""

    def put(booking_id, check_in, check_out, status="confirmed"):
        db.client.put_item(
            TableName=db.name("bookings"),
            Item=dump(
                {
                    "booking_id": booking_id,
                    "hotel_id": "h",
                    "room_id": "r",
                    "check_in": check_in,
                    "check_out": check_out,
                    "status": status,
                    "expires_ms": ms(T0 + HOLD),
                }
            ),
        )

    put("a", "2027-01-10", "2027-01-12")
    put("b", "2027-01-12", "2027-01-13")
    put("c", "2027-01-11", "2027-01-12", status="expired")
    assert store.violations(db, ms(T0)) == []
    put("d", "2027-01-11", "2027-01-15", status="pending")
    assert store.violations(db, ms(T0)) == [("h", "r", "a", "d"), ("h", "r", "b", "d")]
    # Once d's hold has expired it no longer counts.
    assert store.violations(db, ms(T0 + HOLD)) == []
