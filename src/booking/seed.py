"""Hotels and rooms from the generator's reference data, so the booking store and the lakehouse
describe the same hotels for a seed. Re-running it inserts nothing new."""

from psycopg_pool import ConnectionPool

from booking.generator import SCALES, reference

HOTEL_COLUMNS = ("hotel_id", "name", "city", "country", "tz", "currency", "lat", "lon")
ROOM_COLUMNS = ("room_id", "hotel_id", "room_type", "base_rate_minor")


def seed(pool: ConnectionPool, seed_value: int, scale_name: str) -> dict[str, int]:
    """Insert the reference hotels and rooms; returns how many rows each table now has."""
    ref = reference(seed_value, SCALES[scale_name])
    counts = {}
    for table, columns in (("hotels", HOTEL_COLUMNS), ("rooms", ROOM_COLUMNS)):
        placeholders = ", ".join(["%s"] * len(columns))
        with pool.connection() as conn:
            # One transaction per table; the demo scale stays under DSQL's 3,000 rows per commit.
            conn.cursor().executemany(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
                f" ON CONFLICT DO NOTHING",
                [tuple(row[c] for c in columns) for row in ref[table]],
            )
            counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return counts
