"""Generator -> landing files -> silver -> gold on local Spark, with the CDC oracle in place of
AUTO CDC (which runs only on Databricks)."""

from pyspark.sql import functions as F
from sql_harness import broken, register, run
from test_gold import GOLD

from booking.generator import write
from lakehouse import silver


def test_lakehouse_end_to_end(spark, tmp_path):
    write(tmp_path, 7, "small")

    def landed(path, schema):
        return spark.read.schema(schema).json(str(tmp_path / path))

    current = F.lit(None).cast("timestamp").alias("__END_AT")
    events = silver.parse(landed("events/*/backfill/*.json.gz", silver.BRONZE_SCHEMA))
    assert silver.quarantined(events).count() == 0
    register(spark, "booking.silver.events_dedup", silver.dedup(silver.valid(events)))
    bookings, _ = run(spark, "checks/cdc_latest.sql")
    register(spark, "booking.silver.bookings", bookings)
    register(spark, "booking.silver.booking_nights", silver.booking_nights(bookings))
    register(spark, "booking.silver.attempts_rejected", silver.attempts_rejected(events))
    register(
        spark,
        "booking.silver.dim_hotel",
        landed("reference/hotels.json.gz", silver.HOTEL_SCHEMA).select("*", current),
    )
    register(
        spark,
        "booking.silver.dim_room",
        landed("reference/rooms.json.gz", silver.ROOM_SCHEMA).select("*", current),
    )
    register(
        spark,
        "booking.silver.fx_rates",
        silver.fx_rates(landed("reference/fx_rates.json.gz", silver.FX_SCHEMA)),
    )

    gold = {name: run(spark, f"pipeline/gold/{name}.sql") for name in GOLD}
    for name, (df, constraints) in gold.items():
        assert broken(df, constraints) == {}, name
    for check in ("gold_invariant", "row_counts", "cdc_matches"):
        run(spark, f"checks/{check}.sql")[0].collect()

    kpis = (
        gold["kpi_hotel_daily"][0]
        .agg(
            F.min("occupancy").alias("low"),
            F.max("occupancy").alias("high"),
            F.min("adr_usd").alias("adr"),
            F.sum("sold_room_nights").alias("sold"),
        )
        .first()
    )
    assert 0 <= kpis.low and kpis.high <= 1 and kpis.adr > 0 and kpis.sold > 0
    regions = {r.home_region: r for r in gold["conflict_rate_by_region"][0].collect()}
    assert set(regions) == {"us-east-1", "us-east-2"}
    assert all(0 < r.conflict_rate < 1 for r in regions.values())
