"""Helpers shared by the integration tests."""

import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta

import boto3
from botocore.config import Config

from booking import events, store
from booking.service import BookingRequest, book, ms

HOLD = timedelta(minutes=15)
REGION = "us-east-1"
T0 = datetime(2027, 1, 1, 12, tzinfo=UTC)


def stay(room, check_in=date(2027, 1, 10), length=1):
    hotel_id, room_id = room
    return BookingRequest(
        hotel_id, room_id, uuid.uuid4(), check_in, check_in + timedelta(days=length)
    )


def hold(db, key, req, at=T0):
    return book(db, key, req, region=REGION, hold_ttl=HOLD, clock=lambda: at)


def violations(db, at=T0):
    return store.violations(db, ms(at))


def count(db, table):
    return len(db.scan(table))


def booking(db, booking_id):
    return db.get("bookings", {"booking_id": str(booking_id)})


def add_room(db, hotel_id, room_id, rate=12000, currency="EUR"):
    db.client.put_item(
        TableName=db.name("rooms"),
        Item=store.dump(
            {
                "hotel_id": str(hotel_id),
                "room_id": str(room_id),
                "room_type": "double",
                "base_rate_minor": rate,
                "currency": currency,
            }
        ),
    )


def changes(db):
    """Every record the `bookings` stream holds, oldest first per shard."""
    stream_arn = db.client.describe_table(TableName=db.name("bookings"))["Table"]["LatestStreamArn"]
    streams = boto3.client(
        "dynamodbstreams", endpoint_url=os.environ["DYNAMODB_ENDPOINT_URL"], **FAKE_AWS
    )
    records = []
    for shard in streams.describe_stream(StreamArn=stream_arn)["StreamDescription"]["Shards"]:
        iterator = streams.get_shard_iterator(
            StreamArn=stream_arn, ShardId=shard["ShardId"], ShardIteratorType="TRIM_HORIZON"
        )["ShardIterator"]
        while iterator:
            page = streams.get_records(ShardIterator=iterator)
            if not page["Records"]:
                break
            records += page["Records"]
            iterator = page.get("NextShardIterator")
    return records


def booking_events(db, booking_id):
    """(event_type, aggregate_version) of the booking's events, as the stream handler sees them."""
    return [
        (e["event_type"], e["aggregate_version"])
        for record in changes(db)
        for e in events.from_change(record)
        if e["aggregate_id"] == str(booking_id)
    ]


# Emulators accept any credentials; the region is where the client points.
FAKE_AWS = {
    "region_name": "us-east-1",
    "aws_access_key_id": "testing",
    "aws_secret_access_key": "testing",
}


def dynamodb(region, connections=10):
    # DynamoDB Local keeps a separate database per region, like the real service.
    return boto3.client(
        "dynamodb",
        endpoint_url=os.environ["DYNAMODB_ENDPOINT_URL"],
        config=Config(max_pool_connections=connections),
        **{**FAKE_AWS, "region_name": region},
    )


def read_all(client, stream):
    shard = client.list_shards(StreamName=stream)["Shards"][0]["ShardId"]
    iterator = client.get_shard_iterator(
        StreamName=stream, ShardId=shard, ShardIteratorType="TRIM_HORIZON"
    )["ShardIterator"]
    return [json.loads(r["Data"]) for r in client.get_records(ShardIterator=iterator)["Records"]]
