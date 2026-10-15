import json
import uuid

from lakehouse.silver import BRONZE_SCHEMA

HOTEL = "00000000-0000-0000-0000-0000000000a1"
ROOM = "00000000-0000-0000-0000-0000000000b1"


def booking_event(
    event_type="BookingHeld",
    version=1,
    *,
    booking_id="00000000-0000-0000-0000-000000000001",
    status="pending",
    check_in="2026-03-10",
    check_out="2026-03-12",
    amount_minor=20000,
    currency="USD",
    created_at="2026-03-01T12:00:00+00:00",
    occurred_at=None,
    event_id=None,
    region="us-east-1",
    room_id=ROOM,
):
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "aggregate_id": booking_id,
        "aggregate_version": version,
        "home_region": region,
        "occurred_at": occurred_at or created_at,
        "schema_version": 1,
        "payload": {
            "booking_id": booking_id,
            "hotel_id": HOTEL,
            "room_id": room_id,
            "guest_id": "00000000-0000-0000-0000-0000000000c1",
            "check_in": check_in,
            "check_out": check_out,
            "status": status,
            "amount_minor": amount_minor,
            "currency": currency,
            "version": version,
            "home_region": region,
            "created_at": created_at,
            "updated_at": occurred_at or created_at,
        },
    }


def bronze(spark, events):
    rows = [{**e, "payload": json.dumps(e["payload"])} for e in events]
    return spark.createDataFrame(rows, BRONZE_SCHEMA)
