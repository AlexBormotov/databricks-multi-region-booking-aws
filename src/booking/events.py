"""Events from the `bookings` table's change stream (plan D18): each change of a booking becomes
one or two envelopes on the Kinesis stream. Delivery is at least once; a redelivered change has the
same event_id, and the lakehouse drops the duplicate.
"""

import json
import uuid
from datetime import UTC, datetime

from booking.service import iso, snapshot
from booking.store import load

SCHEMA_VERSION = 1
# Kinesis PutRecords takes at most 500 records per call.
BATCH = 500

STATE_EVENTS = {
    "pending": "BookingHeld",
    "confirmed": "BookingConfirmed",
    "expired": "BookingExpired",
    "cancelled": "BookingCancelled",
}
# Name-based ids: one state event per booking version, one refund per booking.
EVENT_NAMESPACE = uuid.UUID("0b9b4f3e-6c1d-4f7a-9d2e-3a5c7e8f9a10")
REFUND_NAMESPACE = uuid.UUID("5f2b8f0e-3d0a-4c56-9a51-6b7c0c1d2e3f")


class PublishFailed(Exception):
    """Kinesis rejected records; the stream batch is retried as a whole."""


def envelope(
    *,
    event_id: uuid.UUID,
    event_type: str,
    aggregate_id: uuid.UUID | str | None,
    aggregate_version: int | None,
    home_region: str,
    occurred_at: datetime | str,
    payload: dict,
) -> bytes:
    """The event contract shared by booking events and telemetry: one JSON object."""
    if isinstance(occurred_at, datetime):
        occurred_at = occurred_at.astimezone(UTC).isoformat()
    return json.dumps(
        {
            "event_id": str(event_id),
            "event_type": event_type,
            "aggregate_id": str(aggregate_id) if aggregate_id else None,
            "aggregate_version": aggregate_version,
            "home_region": home_region,
            "occurred_at": occurred_at,
            "schema_version": SCHEMA_VERSION,
            "payload": payload,
        }
    ).encode()


def from_change(record: dict) -> list[dict]:
    """The events one stream record stands for: a new status is a state event, and `refunded`
    turning true is PaymentRefunded. A delete stands for none."""
    images = record["dynamodb"]
    if "NewImage" not in images:
        return []
    new = load(images["NewImage"])
    old = load(images["OldImage"]) if "OldImage" in images else {}
    common = {
        "aggregate_id": new["booking_id"],
        "aggregate_version": new["version"],
        "home_region": new["changed_in"],
        "occurred_at": iso(new["updated_ms"]),
    }
    events = []
    if new["status"] != old.get("status"):
        event_type = STATE_EVENTS[new["status"]]
        events.append(
            {
                **common,
                "event_id": uuid.uuid5(EVENT_NAMESPACE, f"{new['booking_id']}:{new['version']}"),
                "event_type": event_type,
                "payload": snapshot(new),
            }
        )
    if new.get("refunded") and not old.get("refunded"):
        events.append(
            {
                **common,
                "event_id": uuid.uuid5(REFUND_NAMESPACE, new["booking_id"]),
                "event_type": "PaymentRefunded",
                "payload": {**snapshot(new), "refund_minor": new["amount_minor"]},
            }
        )
    return events


def publish(records: list[dict], kinesis, stream: str) -> int:
    """Put the events of these stream records to Kinesis; return how many. Raises PublishFailed if
    any record is rejected, so the whole batch is delivered again."""
    events = [event for record in records for event in from_change(record)]
    for start in range(0, len(events), BATCH):
        batch = events[start : start + BATCH]
        result = kinesis.put_records(
            StreamName=stream,
            Records=[
                # One aggregate's events land on one shard. PutRecords does not keep their order;
                # the lakehouse restores it from aggregate_version.
                {"Data": envelope(**event), "PartitionKey": event["aggregate_id"]}
                for event in batch
            ],
        )
        if result.get("FailedRecordCount"):
            raise PublishFailed(f"{result['FailedRecordCount']} of {len(batch)} records rejected")
    return len(events)
