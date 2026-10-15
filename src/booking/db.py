"""Connection pool and schema migrations.

In the cloud DSQL_ENDPOINT is set and connections authenticate with IAM tokens; locally
DATABASE_URL points at PostgreSQL. The SQL is the same on both.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

from psycopg_pool import ConnectionPool

MIGRATIONS = Path(__file__).parent / "migrations"

# DSQL closes a connection after one hour; recycle well before that.
MAX_LIFETIME_S = 3000


def create_pool(min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    """Return an unopened pool; open it with `with pool:` or `pool.open()`."""
    options = {"min_size": min_size, "max_size": max_size, "max_lifetime": MAX_LIFETIME_S}
    endpoint = os.environ.get("DSQL_ENDPOINT")
    if endpoint:
        import aurora_dsql_psycopg as dsql

        conninfo = f"postgresql://{endpoint}/postgres?user=admin"
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
