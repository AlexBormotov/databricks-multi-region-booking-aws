import os
import uuid

import boto3
import pytest
from support import FAKE_AWS, add_room, dynamodb

from booking.guests import VAULTS
from booking.store import KEYS, Store, create_tables


@pytest.fixture
def db():
    """The four booking tables under a fresh prefix in DynamoDB Local, deleted afterwards."""
    # Enough connections for the contention test to keep many requests in flight.
    store = Store(dynamodb("us-east-1", connections=100), f"t{uuid.uuid4().hex[:8]}")
    create_tables(store)
    yield store
    for table in KEYS:
        store.client.delete_table(TableName=store.name(table))


@pytest.fixture
def room(db):
    """One hotel with one room at 120.00 EUR a night; returns (hotel_id, room_id)."""
    hotel_id, room_id = uuid.uuid4(), uuid.uuid4()
    add_room(db, hotel_id, room_id)
    return hotel_id, room_id


@pytest.fixture(scope="module")
def vaults():
    for region, table in VAULTS.values():
        client = dynamodb(region)
        if table not in client.list_tables()["TableNames"]:
            client.create_table(
                TableName=table,
                KeySchema=[{"AttributeName": "guest_id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "guest_id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )


@pytest.fixture
def kinesis():
    client = boto3.client("kinesis", endpoint_url=os.environ["MOTO_ENDPOINT_URL"], **FAKE_AWS)
    name = f"events-{uuid.uuid4().hex[:8]}"
    client.create_stream(StreamName=name, ShardCount=1)
    client.get_waiter("stream_exists").wait(StreamName=name)
    return client, name
