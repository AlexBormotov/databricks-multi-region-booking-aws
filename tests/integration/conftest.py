import os
import uuid

import boto3
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from support import FAKE_AWS, dynamodb

from booking.db import create_pool, migrate
from booking.guests import VAULTS


@pytest.fixture
def empty_pool(monkeypatch):
    """A pool on a fresh, empty database that is dropped afterwards."""
    admin_url = os.environ["DATABASE_URL"]
    dbname = f"t_{uuid.uuid4().hex}"
    name = sql.Identifier(dbname)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(name))
    monkeypatch.setenv("DATABASE_URL", make_conninfo(admin_url, dbname=dbname))
    # Enough connections for the contention test to keep many transactions in flight.
    pool = create_pool(max_size=50)
    with pool:
        yield pool
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(name))


@pytest.fixture
def pool(empty_pool):
    migrate(empty_pool)
    return empty_pool


@pytest.fixture
def room(pool):
    """One hotel with one room at 120.00 EUR a night; returns (hotel_id, room_id)."""
    hotel_id, room_id = uuid.uuid4(), uuid.uuid4()
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO hotels VALUES (%s, 'Hotel Sea', 'Lisbon', 'PT', 'Europe/Lisbon', 'EUR',"
            " 38.7, -9.1)",
            (hotel_id,),
        )
        conn.execute("INSERT INTO rooms VALUES (%s, %s, 'double', 12000)", (room_id, hotel_id))
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
