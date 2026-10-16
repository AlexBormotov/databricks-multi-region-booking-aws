"""The Lambdas' role: enough to book, nothing more. Locally `SET ROLE` stands in for the IAM
mapping that `AWS IAM GRANT` makes on DSQL."""

import os
from datetime import date

import psycopg
import pytest
from psycopg_pool import ConnectionPool
from support import hold, stay

from booking.db import APP_ROLE, grant_app_role


@pytest.fixture
def app_pool(pool):
    grant_app_role(pool)
    grant_app_role(pool)  # idempotent

    def as_app(conn):
        conn.execute(f"SET ROLE {APP_ROLE}")
        conn.commit()

    with ConnectionPool(
        os.environ["DATABASE_URL"], configure=as_app, min_size=1, max_size=2
    ) as opened:
        yield opened


def test_app_role_can_book(app_pool, room):
    assert hold(app_pool, "k1", stay(room, date(2027, 1, 10))).status_code == 201


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE stray (id int)",
        "DROP TABLE bookings",
        "ALTER TABLE bookings ADD COLUMN stray int",
        "INSERT INTO hotels VALUES (gen_random_uuid(), 'x', 'x', 'x', 'UTC', 'USD', 0, 0)",
        "DELETE FROM rooms",
        "SELECT * FROM schema_migrations",
    ],
)
def test_app_role_has_dml_only(app_pool, statement):
    with app_pool.connection() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)


def test_grant_rejects_a_malformed_arn(pool):
    with pytest.raises(ValueError, match="not an IAM role ARN"):
        grant_app_role(pool, ("arn:aws:iam::123456789012:role/x'; DROP TABLE bookings; --",))
