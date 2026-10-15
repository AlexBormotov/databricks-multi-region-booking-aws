# Silver: thin wrappers over `lakehouse.silver`, which is tested locally without a pipeline.

from pyspark import pipelines as dp

from lakehouse import silver
from lakehouse.rules import expectations


def stream(table: str):
    return spark.readStream.table(table)  # noqa: F821


def batch(table: str):
    return spark.read.table(table)  # noqa: F821


@dp.temporary_view
def events_parsed():
    return silver.parse(stream("booking.bronze.events"))


# Dedup keeps one row per event_id for the life of the table; demo volumes keep that state small.
@dp.table(name="booking.silver.events_dedup")
@dp.expect_all_or_drop(expectations())
def events_dedup():
    return silver.dedup(stream("events_parsed"))


# The same rule set as the expectations above, so a dropped row is always quarantined.
@dp.table(name="booking.silver.quarantine_events")
def quarantine_events():
    return silver.quarantined(stream("events_parsed"))


@dp.temporary_view
def booking_changes():
    return silver.state_events(stream("booking.silver.events_dedup"))


# Arrival order across regions is arbitrary; the booking's version decides which state wins.
for target, scd_type in (("booking.silver.bookings", 1), ("booking.silver.bookings_history", 2)):
    dp.create_streaming_table(target)
    dp.create_auto_cdc_flow(
        target=target,
        source="booking_changes",
        keys=["booking_id"],
        sequence_by="version",
        stored_as_scd_type=scd_type,
    )


@dp.materialized_view(name="booking.silver.booking_nights")
def booking_nights():
    return silver.booking_nights(batch("booking.silver.bookings"))


@dp.table(name="booking.silver.attempts_rejected")
def attempts_rejected():
    return silver.attempts_rejected(stream("booking.silver.events_dedup"))


@dp.materialized_view(name="booking.silver.fx_rates")
def fx_rates():
    return silver.fx_rates(batch("booking.bronze.fx_rates"))


# Reference files are reloaded whole; SCD2 keeps the history of a hotel's or a room's attributes.
for target, source, key in (
    ("booking.silver.dim_hotel", "booking.bronze.hotels", "hotel_id"),
    ("booking.silver.dim_room", "booking.bronze.rooms", "room_id"),
):
    dp.create_streaming_table(target)
    dp.create_auto_cdc_flow(
        target=target,
        source=source,
        keys=[key],
        sequence_by="_ingested_at",
        except_column_list=["_ingested_at", "_source_file"],
        stored_as_scd_type=2,
    )
