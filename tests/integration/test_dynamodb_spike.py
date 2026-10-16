"""The DynamoDB spike against DynamoDB Local. It has no regions, so this proves the claim logic
only; the cross-region run is the cloud run's MRSC script (plan D8)."""

import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pytest
from support import dynamodb

sys.path.insert(0, str(Path(__file__).parents[2] / "spike" / "dynamodb"))
import claims  # noqa: E402

NIGHT = date(2027, 1, 10)


@pytest.fixture
def table():
    client = dynamodb("us-east-1")
    name = f"room-nights-{uuid.uuid4().hex[:8]}"
    client.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "room_night", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "room_night", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    yield client, name
    client.delete_table(TableName=name)


def holder(client, name, room_id, night):
    item = client.get_item(TableName=name, Key=claims.key(room_id, night), ConsistentRead=True)
    return item.get("Item", {}).get("booking_id", {}).get("S")


def test_spike_single_winner(table):
    client, name = table
    room_id = str(uuid.uuid4())
    bookings = [str(uuid.uuid4()) for _ in range(50)]
    with ThreadPoolExecutor(max_workers=25) as pool:
        won = list(pool.map(lambda b: claims.claim(client, name, b, room_id, [NIGHT]), bookings))
    assert won.count(True) == 1
    assert holder(client, name, room_id, NIGHT) == bookings[won.index(True)]


def test_spike_compensation(table):
    """B wants nights 1-3 but A holds night 2: B takes night 1, loses night 2 and gives night 1
    back. A keeps night 2, and night 3 is never taken."""
    client, name = table
    room_id, a, b = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    stay = [NIGHT + timedelta(days=i) for i in range(3)]
    assert claims.claim(client, name, a, room_id, [stay[1]])
    assert not claims.claim(client, name, b, room_id, stay)
    assert [holder(client, name, room_id, n) for n in stay] == [None, a, None]


def test_spike_release_leaves_another_bookings_night(table):
    client, name = table
    room_id, a, b = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    assert claims.claim(client, name, a, room_id, [NIGHT])
    claims.release(client, name, b, room_id, [NIGHT])
    assert holder(client, name, room_id, NIGHT) == a
