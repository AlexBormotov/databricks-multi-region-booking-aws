"""Helpers shared by the integration tests."""

import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import boto3

from booking.service import BookingRequest, book

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


# Emulators accept any credentials; the region is where the client points.
FAKE_AWS = {
    "region_name": "us-east-1",
    "aws_access_key_id": "testing",
    "aws_secret_access_key": "testing",
}


def dynamodb(region):
    # DynamoDB Local keeps a separate database per region, like the real service.
    return boto3.client(
        "dynamodb",
        endpoint_url=os.environ["DYNAMODB_ENDPOINT_URL"],
        **{**FAKE_AWS, "region_name": region},
    )


def read_all(client, stream):
    shard = client.list_shards(StreamName=stream)["Shards"][0]["ShardId"]
    iterator = client.get_shard_iterator(
        StreamName=stream, ShardId=shard, ShardIteratorType="TRIM_HORIZON"
    )["ShardIterator"]
    return [json.loads(r["Data"]) for r in client.get_records(ShardIterator=iterator)["Records"]]
