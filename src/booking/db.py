"""Connection pool and schema migrations.

In the cloud DSQL_ENDPOINT is set and connections authenticate with IAM tokens; locally
DATABASE_URL points at PostgreSQL. The SQL is the same on both. The Lambdas connect as APP_ROLE
(DSQL_ROLE); migrations and seeding run as admin from the session runner.
"""

import os
import re
from datetime import UTC, datetime
from pathlib import Path

from psycopg_pool import ConnectionPool

MIGRATIONS = Path(__file__).parent / "migrations"

# DSQL closes a connection after one hour; recycle well before that.
MAX_LIFETIME_S = 3000

APP_ROLE = "booking_app"
# What the application may do: read the reference tables, read and write the booking tables.
APP_GRANTS = (
    "GRANT SELECT ON hotels, rooms TO booking_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON bookings, room_night, idempotency_keys, outbox"
    " TO booking_app",
)
# AWS IAM GRANT takes the ARN as a literal, not a parameter, so it is checked before use.
IAM_ROLE_ARN = re.compile(r"arn:aws:iam::\d{12}:role/[\w+=,.@/-]+")


def create_pool(min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    """Return an unopened pool; open it with `with pool:` or `pool.open()`."""
    options = {"min_size": min_size, "max_size": max_size, "max_lifetime": MAX_LIFETIME_S}
    endpoint = os.environ.get("DSQL_ENDPOINT")
    if endpoint:
        import aurora_dsql_psycopg as dsql

        # The connector signs a DbConnectAdmin token for admin and a DbConnect token otherwise.
        user = os.environ.get("DSQL_ROLE", "admin")
        conninfo = f"postgresql://{endpoint}/postgres?user={user}"
        return dsql.create_pool(conninfo, open=False, **options)
    return ConnectionPool(os.environ["DATABASE_URL"], open=False, **options)


def migrate(pool: ConnectionPool) -> list[str]:
    """Apply pending migrations in file-name order and return the names applied.

    DSQL runs one DDL statement per transaction and never mixes DDL with DML, so the connection
    autocommits: each file is its own transaction and its bookkeeping row is the next one. Every
    file says IF NOT EXISTS, so a crash between the two only repeats a no-op.
    """
    applied = []
    with pool.connection() as conn:
        conn.autocommit = True
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name text PRIMARY KEY, applied_at timestamptz NOT NULL)"
        )
        done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (%s, %s)",
                (path.name, datetime.now(UTC)),
            )
            applied.append(path.name)
    return applied


def grant_app_role(pool: ConnectionPool, iam_role_arns: tuple[str, ...] = ()) -> None:
    """Create APP_ROLE if absent, grant it DML on the migrated tables, and on DSQL map the given
    IAM roles to it. Runs as admin after `migrate`; every statement is its own transaction."""
    with pool.connection() as conn:
        conn.autocommit = True
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,)).fetchone():
            conn.execute(f"CREATE ROLE {APP_ROLE} WITH LOGIN")
        for grant in APP_GRANTS:
            conn.execute(grant)
        for arn in iam_role_arns:
            if not IAM_ROLE_ARN.fullmatch(arn):
                raise ValueError(f"not an IAM role ARN: {arn!r}")
            mapped = conn.execute(
                "SELECT 1 FROM sys.iam_pg_role_mappings WHERE pg_role_name = %s AND arn = %s",
                (APP_ROLE, arn),
            ).fetchone()
            if not mapped:
                conn.execute(f"AWS IAM GRANT {APP_ROLE} TO '{arn}'")
