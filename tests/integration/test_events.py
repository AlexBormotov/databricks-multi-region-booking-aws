"""Events from the DynamoDB Local stream of `bookings`, through the handler, into moto Kinesis."""

import uuid
from datetime import date

import pytest
from support import HOLD, REGION, T0, changes, hold, read_all, stay

from booking.events import PublishFailed, publish
from booking.saga import confirm
from booking.service import book
from booking.telemetry import record_rejection


def test_events_from_stream(db, room, kinesis):
    client, stream = kinesis
    east1 = hold(db, "k1", stay(room, date(2027, 1, 10)))
    book(
        db, "k2", stay(room, date(2027, 1, 20)), region="us-east-2", hold_ttl=HOLD, clock=lambda: T0
    )
    confirm(db, uuid.UUID(east1.body["booking_id"]), region="us-east-2", clock=lambda: T0)

    records = changes(db)
    assert publish(records, client, stream) == 3
    held, other, confirmed = read_all(client, stream)
    assert held["event_type"] == "BookingHeld"
    assert held["home_region"] == REGION
    assert held["aggregate_id"] == east1.body["booking_id"]
    assert held["aggregate_version"] == 1
    assert held["schema_version"] == 1
    assert held["occurred_at"] == T0.isoformat()
    assert held["payload"] == east1.body
    assert other["home_region"] == "us-east-2"
    # The region of a change is where it was made, not where the booking was created.
    assert (confirmed["event_type"], confirmed["home_region"]) == ("BookingConfirmed", "us-east-2")
    assert confirmed["payload"]["home_region"] == REGION

    # A redelivered batch repeats the same event ids, which the lakehouse drops.
    publish(records, client, stream)
    ids = [e["event_id"] for e in read_all(client, stream)]
    assert ids[3:] == ids[:3] and len(set(ids)) == 3


class RejectingKinesis:
    def put_records(self, StreamName, Records):
        return {"FailedRecordCount": 1, "Records": [{"ErrorCode": "x"}] * len(Records)}


def test_a_rejected_record_fails_the_batch(db, room):
    hold(db, "k", stay(room))
    # Raising makes Lambda deliver the whole batch again.
    with pytest.raises(PublishFailed, match="1 of 1 records rejected"):
        publish(changes(db), RejectingKinesis(), "s")


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
