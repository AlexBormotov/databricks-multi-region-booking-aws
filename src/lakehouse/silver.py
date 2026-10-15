"""Bronze to silver: parse, quality split, dedup, and the shapes AUTO CDC and gold read."""

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

from lakehouse.rules import STATE_EVENTS, expectations

# The event contract as it lands; the payload stays raw JSON text in bronze.
BRONZE_SCHEMA = (
    "event_id STRING, event_type STRING, aggregate_id STRING, aggregate_version BIGINT,"
    " home_region STRING, occurred_at STRING, schema_version INT, payload STRING"
)
# The union of every event type's payload: booking snapshots, refunds and telemetry.
PAYLOAD_SCHEMA = (
    "booking_id STRING, hotel_id STRING, room_id STRING, guest_id STRING, check_in DATE,"
    " check_out DATE, status STRING, expires_at TIMESTAMP, amount_minor BIGINT, currency STRING,"
    " version BIGINT, created_at TIMESTAMP, updated_at TIMESTAMP, refund_minor BIGINT,"
    " status_code INT"
)
PAYLOAD_FIELDS = [f.strip().split(" ")[0] for f in PAYLOAD_SCHEMA.split(",")]
# Reference files, as `booking.generator` writes them.
HOTEL_SCHEMA = (
    "hotel_id STRING, name STRING, city STRING, country STRING, tz STRING, currency STRING,"
    " lat DOUBLE, lon DOUBLE"
)
ROOM_SCHEMA = "room_id STRING, hotel_id STRING, room_type STRING, base_rate_minor BIGINT"
FX_SCHEMA = "currency STRING, date STRING, rate_to_usd DOUBLE, exponent INT"


def parse(bronze: DataFrame) -> DataFrame:
    """Typed columns from the envelope and the payload."""
    payload = F.from_json("payload", PAYLOAD_SCHEMA)
    return bronze.select(
        "event_id",
        "event_type",
        "aggregate_id",
        "aggregate_version",
        "home_region",
        F.to_timestamp("occurred_at").alias("occurred_at"),
        "schema_version",
        *[payload[f].alias(f) for f in PAYLOAD_FIELDS],
    )


def violation() -> Column:
    """The name of the first rule a row breaks, or NULL."""
    column = F.lit(None).cast("string")
    for name, expr in reversed(expectations().items()):
        column = F.when(~F.expr(expr), F.lit(name)).otherwise(column)
    return column


def valid(events: DataFrame) -> DataFrame:
    return events.where(violation().isNull())


def quarantined(events: DataFrame) -> DataFrame:
    return events.withColumn("rule", violation()).where(F.col("rule").isNotNull())


def dedup(events: DataFrame) -> DataFrame:
    """One row per event_id: at-least-once delivery repeats identical events."""
    return events.dropDuplicates(["event_id"])


def state_events(events: DataFrame) -> DataFrame:
    """The AUTO CDC source: booking state changes keyed by booking, ordered by version.

    A PaymentRefunded event repeats the version of the expiry before it, so it is not a state
    change and stays out.
    """
    return events.where(F.col("event_type").isin(*STATE_EVENTS)).select(
        "booking_id",
        "hotel_id",
        "room_id",
        "guest_id",
        "check_in",
        "check_out",
        "status",
        "amount_minor",
        "currency",
        "home_region",
        "created_at",
        "updated_at",
        F.col("aggregate_version").alias("version"),
    )


def booking_nights(bookings: DataFrame) -> DataFrame:
    """One row per booking and hotel-local night, with the stay's amount split evenly."""
    nights = F.datediff("check_out", "check_in")
    return bookings.select(
        "booking_id",
        "hotel_id",
        "room_id",
        "status",
        "currency",
        "home_region",
        F.explode(F.sequence("check_in", F.date_sub("check_out", 1))).alias("night"),
        (F.col("amount_minor") / nights).alias("night_amount_minor"),
    )


def attempts_rejected(events: DataFrame) -> DataFrame:
    return events.where(F.col("event_type") == "BookingAttemptRejected").select(
        "event_id",
        "home_region",
        "occurred_at",
        "hotel_id",
        "room_id",
        "check_in",
        "check_out",
        "status_code",
    )


def fx_rates(raw: DataFrame) -> DataFrame:
    return raw.select(
        "currency",
        F.to_date("date").alias("date"),
        F.col("rate_to_usd").cast("double").alias("rate_to_usd"),
        F.col("exponent").cast("int").alias("exponent"),
    )
