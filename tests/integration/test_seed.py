from booking.generator import SCALES, reference
from booking.seed import HOTEL_COLUMNS, ROOM_COLUMNS, seed


def rows(pool, table, columns):
    with pool.connection() as conn:
        found = conn.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
    return {tuple(str(v) for v in row) for row in found}


def test_seed_matches_reference(pool):
    ref = reference(7, SCALES["small"])
    assert seed(pool, 7, "small") == {"hotels": 12, "rooms": 60}
    assert seed(pool, 7, "small") == {"hotels": 12, "rooms": 60}  # re-run inserts nothing
    for table, columns in (("hotels", HOTEL_COLUMNS), ("rooms", ROOM_COLUMNS)):
        expected = {tuple(str(r[c]) for c in columns) for r in ref[table]}
        assert rows(pool, table, columns) == expected
