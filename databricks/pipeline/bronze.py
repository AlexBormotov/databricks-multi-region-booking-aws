# Bronze: the landing bucket as it is, append-only, through Auto Loader.
# `spark` is provided by the pipeline runtime; the transformations live in `lakehouse`.

from pyspark import pipelines as dp
from pyspark.sql import functions as F

from lakehouse.silver import BRONZE_SCHEMA, FX_SCHEMA, HOTEL_SCHEMA, ROOM_SCHEMA

LANDING = spark.conf.get("booking.landing")  # noqa: F821


def landed(path: str, schema: str):
    return (
        spark.readStream.format("cloudFiles")  # noqa: F821
        .option("cloudFiles.format", "json")
        .schema(schema)
        .load(f"{LANDING}/{path}")
        .select(
            "*",
            F.current_timestamp().alias("_ingested_at"),
            F.col("_metadata.file_path").alias("_source_file"),
        )
    )


@dp.table(name="booking.bronze.events", comment="Every landed event, live and backfill.")
@dp.expect("has_event_id", "event_id IS NOT NULL")
@dp.expect("known_schema_version", "schema_version = 1")
def events():
    return landed("events/", BRONZE_SCHEMA)


@dp.table(name="booking.bronze.hotels")
def hotels():
    return landed("reference/hotels*.json.gz", HOTEL_SCHEMA)


@dp.table(name="booking.bronze.rooms")
def rooms():
    return landed("reference/rooms*.json.gz", ROOM_SCHEMA)


@dp.table(name="booking.bronze.fx_rates")
def fx_rates():
    return landed("reference/fx_rates*.json.gz", FX_SCHEMA)
