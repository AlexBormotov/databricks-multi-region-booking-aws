"""The booking store on DynamoDB (ADR 2): four tables, multi-region strongly consistent (MRSC) in
the cloud (infra/modules/store) and in DynamoDB Local for the tests.

Times are epoch milliseconds, because conditions compare them. Every read is strongly consistent.
"""

import itertools
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from booking.domain import Status, is_live

# Key schema per table; infra/modules/store declares the same tables.
KEYS = {
    "rooms": (("hotel_id", "HASH"), ("room_id", "RANGE")),
    "room-nights": (("room_night", "HASH"),),
    "bookings": (("booking_id", "HASH"),),
    "idempotency": (("idem_key", "HASH"),),
}

MAX_ATTEMPTS = 5
BACKOFF_BASE_S = 0.02
BACKOFF_CAP_S = 1.0
# MRSC rejects a write that races a write to the same item from the other region. The write was
# not applied, so repeating it is safe; its condition is evaluated again.
RETRYABLE = {"ReplicatedWriteConflictException"}

_SERIALIZER, _DESERIALIZER = TypeSerializer(), TypeDeserializer()


class Busy(Exception):
    """A write lost every retry to concurrent writes."""


def error_code(err: ClientError) -> str:
    return err.response["Error"]["Code"]


def condition_failed(err: ClientError) -> bool:
    return error_code(err) == "ConditionalCheckFailedException"


def dump(values: dict) -> dict:
    """Python values to DynamoDB attributes; None means the attribute is absent."""
    return {k: _SERIALIZER.serialize(v) for k, v in values.items() if v is not None}


def load(item: dict) -> dict:
    """DynamoDB attributes to Python values. Every number the store keeps is an integer."""
    values = {k: _DESERIALIZER.deserialize(v) for k, v in item.items()}
    return {k: int(v) if isinstance(v, Decimal) else v for k, v in values.items()}


@dataclass(frozen=True)
class Store:
    client: object
    prefix: str = "booking"
    sleep: Callable[[float], None] = field(default=time.sleep, compare=False)
    rng: Callable[[], float] = field(default=random.random, compare=False)

    def name(self, table: str) -> str:
        return f"{self.prefix}-{table}"

    def call(self, operation: str, table: str, **params) -> dict:
        """One request to `table`. A write that lost a cross-region race is retried with
        exponential backoff and full jitter; out of retries it raises Busy."""
        for attempt in range(MAX_ATTEMPTS):
            try:
                return getattr(self.client, operation)(TableName=self.name(table), **params)
            except ClientError as err:
                if error_code(err) not in RETRYABLE:
                    raise
                if attempt < MAX_ATTEMPTS - 1:
                    self.sleep(self.rng() * min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2**attempt))
        raise Busy()

    def get(self, table: str, key: dict) -> dict | None:
        item = self.call("get_item", table, Key=dump(key), ConsistentRead=True).get("Item")
        return load(item) if item else None

    def get_many(self, table: str, keys: list[dict]) -> list[dict]:
        """Strongly consistent BatchGetItem, 100 keys a call, unprocessed keys asked again."""
        found = []
        for batch in itertools.batched(keys, 100, strict=False):
            pending = {self.name(table): {"Keys": [dump(k) for k in batch], "ConsistentRead": True}}
            while pending:
                result = self.client.batch_get_item(RequestItems=pending)
                found += [load(i) for i in result["Responses"].get(self.name(table), [])]
                pending = result.get("UnprocessedKeys") or {}
        return found

    def scan(self, table: str) -> list[dict]:
        pages = self.client.get_paginator("scan").paginate(
            TableName=self.name(table), ConsistentRead=True
        )
        return [load(item) for page in pages for item in page["Items"]]


def create_tables(store: Store) -> None:
    """The four tables, for DynamoDB Local; `bookings` streams its changes as in the cloud."""
    for table, keys in KEYS.items():
        params = {
            "TableName": store.name(table),
            "KeySchema": [{"AttributeName": a, "KeyType": t} for a, t in keys],
            "AttributeDefinitions": [{"AttributeName": a, "AttributeType": "S"} for a, _ in keys],
            "BillingMode": "PAY_PER_REQUEST",
        }
        if table == "bookings":
            params["StreamSpecification"] = {
                "StreamEnabled": True,
                "StreamViewType": "NEW_AND_OLD_IMAGES",
            }
        store.client.create_table(**params)


def violations(store: Store, now_ms: int) -> list[tuple[str, str, str, str]]:
    """No room-night is sold twice: pairs of live bookings of one room whose stays
    [check_in, check_out) overlap. Must be empty. It reads `bookings` only, so it does not trust
    the room-night claims it is checking."""
    live = sorted(
        (
            b
            for b in store.scan("bookings")
            if is_live(Status(b["status"]), b["expires_ms"], now_ms)
        ),
        key=lambda b: b["booking_id"],
    )
    by_room: dict[tuple[str, str], list[dict]] = {}
    for booking in live:
        by_room.setdefault((booking["hotel_id"], booking["room_id"]), []).append(booking)
    return [
        (hotel_id, room_id, a["booking_id"], b["booking_id"])
        for (hotel_id, room_id), bookings in by_room.items()
        for a, b in itertools.combinations(bookings, 2)
        if a["check_in"] < b["check_out"] and b["check_in"] < a["check_out"]
    ]
