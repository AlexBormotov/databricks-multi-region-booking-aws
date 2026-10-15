from datetime import date

from support import HOLD, T0, read_all, scalar, stay

from booking.outbox import publish_once, run_poller
from booking.service import book
from booking.telemetry import record_rejection


def book_in(pool, room, region, check_in):
    return book(
        pool, f"key-{region}", stay(room, check_in), region=region, hold_ttl=HOLD, clock=lambda: T0
    )


def test_outbox_poller_publishes_own_region_only(pool, room, kinesis):
    client, stream = kinesis
    east1 = book_in(pool, room, "us-east-1", date(2027, 1, 10))
    book_in(pool, room, "us-east-2", date(2027, 1, 20))

    assert publish_once(pool, client, stream, "us-east-1") == 1
    assert publish_once(pool, client, stream, "us-east-1") == 0

    [event] = read_all(client, stream)
    assert event["event_type"] == "BookingHeld"
    assert event["home_region"] == "us-east-1"
    assert event["aggregate_id"] == east1.body["booking_id"]
    assert event["aggregate_version"] == 1
    assert event["schema_version"] == 1
    assert event["payload"]["status"] == "pending"
    unpublished = "SELECT count(*) FROM outbox WHERE published_at IS NULL AND home_region = %s"
    assert scalar(pool, unpublished, "us-east-1") == 0
    assert scalar(pool, unpublished, "us-east-2") == 1


class HalfFailingKinesis:
    """Accepts the first record of each call and throttles the rest."""

    def put_records(self, StreamName, Records):
        return {
            "Records": [{"SequenceNumber": "1"}]
            + [{"ErrorCode": "ProvisionedThroughputExceededException"}] * (len(Records) - 1)
        }


def test_rejected_records_stay_in_the_outbox(pool, room):
    book_in(pool, room, "us-east-1", date(2027, 1, 10))
    book(pool, "k2", stay(room, date(2027, 1, 20)), region="us-east-1", hold_ttl=HOLD)

    assert publish_once(pool, HalfFailingKinesis(), "s", "us-east-1") == 1
    assert scalar(pool, "SELECT count(*) FROM outbox WHERE published_at IS NULL") == 1
    assert publish_once(pool, HalfFailingKinesis(), "s", "us-east-1") == 1
    assert scalar(pool, "SELECT count(*) FROM outbox WHERE published_at IS NULL") == 0


def test_poller_runs_until_its_deadline(pool, room, kinesis):
    client, stream = kinesis
    book_in(pool, room, "us-east-1", date(2027, 1, 10))
    ticks = iter(range(100))

    published = run_poller(
        pool,
        client,
        stream,
        "us-east-1",
        seconds=3,
        clock=lambda: next(ticks),
        sleep=lambda s: None,
    )
    assert published == 1


def test_rejection_telemetry_is_best_effort(room, kinesis):
    client, stream = kinesis
    req = stay(room)
    record_rejection(client, stream, "us-east-2", req, 409, T0)

    [event] = read_all(client, stream)
    assert event["event_type"] == "BookingAttemptRejected"
    assert event["aggregate_version"] is None
    assert event["payload"]["status_code"] == 409

    # A broken stream never fails the request.
    record_rejection(client, "no-such-stream", "us-east-2", req, 409, T0)
