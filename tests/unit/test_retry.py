from contextlib import contextmanager

from psycopg import errors

from booking.service import BACKOFF_BASE_S, MAX_ATTEMPTS, run_transaction


class ConflictingPool:
    """Every transaction fails at commit with an OCC conflict."""

    attempts = 0

    @contextmanager
    def connection(self):
        self.attempts += 1
        raise errors.SerializationFailure("change conflicts with another transaction (OC000)")
        yield


def test_conflicts_retry_with_backoff_then_503():
    pool, sleeps = ConflictingPool(), []
    response = run_transaction(pool, lambda cur: None, sleep=sleeps.append, rng=lambda: 1.0)

    assert pool.attempts == MAX_ATTEMPTS
    assert sleeps == [BACKOFF_BASE_S * 2**i for i in range(MAX_ATTEMPTS - 1)]
    assert response.status_code == 503
    assert response.headers == {"Retry-After": "1"}


def test_full_jitter_can_retry_immediately():
    sleeps = []
    run_transaction(ConflictingPool(), lambda cur: None, sleep=sleeps.append, rng=lambda: 0.0)
    assert sleeps == [0.0] * (MAX_ATTEMPTS - 1)
