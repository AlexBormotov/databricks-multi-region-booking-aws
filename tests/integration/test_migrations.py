from booking.db import MIGRATIONS, migrate


def test_migrations_apply_from_scratch_and_rerun_is_noop(empty_pool):
    assert migrate(empty_pool) == sorted(p.name for p in MIGRATIONS.glob("*.sql"))

    with empty_pool.connection() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
        }
    assert tables == {
        "schema_migrations",
        "hotels",
        "rooms",
        "bookings",
        "room_night",
        "idempotency_keys",
        "outbox",
    }

    assert migrate(empty_pool) == []
