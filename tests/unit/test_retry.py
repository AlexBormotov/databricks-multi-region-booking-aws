import pytest
from botocore.exceptions import ClientError

from booking.store import BACKOFF_BASE_S, MAX_ATTEMPTS, Busy, Store


class ConflictingClient:
    """Every write loses a cross-region race (MRSC's write-write conflict)."""

    attempts = 0

    def put_item(self, **params):
        self.attempts += 1
        raise ClientError(
            {"Error": {"Code": "ReplicatedWriteConflictException", "Message": "conflict"}},
            "PutItem",
        )


def test_conflicts_retry_with_backoff_then_busy():
    client, sleeps = ConflictingClient(), []
    store = Store(client, sleep=sleeps.append, rng=lambda: 1.0)
    with pytest.raises(Busy):
        store.call("put_item", "bookings", Item={})

    assert client.attempts == MAX_ATTEMPTS
    assert sleeps == [BACKOFF_BASE_S * 2**i for i in range(MAX_ATTEMPTS - 1)]


def test_full_jitter_can_retry_immediately():
    sleeps = []
    with pytest.raises(Busy):
        Store(ConflictingClient(), sleep=sleeps.append, rng=lambda: 0.0).call(
            "put_item", "bookings", Item={}
        )
    assert sleeps == [0.0] * (MAX_ATTEMPTS - 1)


def test_other_errors_are_not_retried():
    class Broken:
        attempts = 0

        def put_item(self, **params):
            self.attempts += 1
            raise ClientError({"Error": {"Code": "ValidationException", "Message": "x"}}, "PutItem")

    client = Broken()
    with pytest.raises(ClientError):
        Store(client, sleep=lambda s: None).call("put_item", "bookings", Item={})
    assert client.attempts == 1
