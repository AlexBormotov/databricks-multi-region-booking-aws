import random
from datetime import date

import pytest
from lake_support import HOTEL, ROOM, booking_event, bronze
from pyspark.errors import PySparkException
from pyspark.sql import functions as F
from sql_harness import broken, register, run

from lakehouse import silver

TOKYO = "00000000-0000-0000-0000-0000000000a2"
ROOM_2 = "00000000-0000-0000-0000-0000000000b2"
ROOM_T = "00000000-0000-0000-0000-0000000000b3"
GOLD = [
    "dim_date",
    "fact_room_night",
    "fact_booking",
    "kpi_hotel_daily",
    "booking_pace",
    "lead_time",
    "cancellation_rate",
    "conflict_rate_by_region",
]
REJECTED = {
    **booking_event("BookingAttemptRejected", None),
    "aggregate_id": None,
    "payload": {"hotel_id": HOTEL, "room_id": ROOM, "check_in": "2026-03-10",
                "check_out": "2026-03-11", "status_code": 409},
}  # fmt: skip
FINAL = {"pending": [], "confirmed": ["confirmed"], "cancelled": ["confirmed", "cancelled"]}


def booking_id(n):
    return f"00000000-0000-0000-0000-{n:012d}"


def stay(n, room, status, amount, *, hotel=HOTEL, currency="USD"):
    """A booking's events from hold to `status`, versions 1..k, created 2026-03-01 23:30 UTC."""
    steps = [("BookingHeld", "pending")] + [(f"Booking{s.title()}", s) for s in FINAL[status]]
    events = [
        booking_event(
            event_type,
            version,
            booking_id=booking_id(n),
            status=s,
            room_id=room,
            check_in="2026-03-10",
            check_out="2026-03-12",
            amount_minor=amount,
            currency=currency,
            created_at="2026-03-01T23:30:00+00:00",
        )
        for version, (event_type, s) in enumerate(steps, start=1)
    ]
    for e in events:
        e["payload"]["hotel_id"] = hotel
    return events


def load_silver(spark, events):
    """The silver tables from events, with the CDC oracle standing in for AUTO CDC."""
    parsed = silver.dedup(silver.valid(silver.parse(bronze(spark, events))))
    register(spark, "booking.silver.events_dedup", parsed)
    bookings, _ = run(spark, "checks/cdc_latest.sql")
    register(spark, "booking.silver.bookings", bookings)
    register(spark, "booking.silver.booking_nights", silver.booking_nights(bookings))
    register(spark, "booking.silver.attempts_rejected", silver.attempts_rejected(parsed))
    hotels = [(HOTEL, "America/New_York", None), (TOKYO, "Asia/Tokyo", None)]
    rooms = [(HOTEL, ROOM, None), (HOTEL, ROOM_2, None), (TOKYO, ROOM_T, None)]
    fx = [
        ("USD", "2026-01-01", 1.0, 2),
        ("JPY", "2026-01-01", 0.0067, 0),
        ("JPY", "2026-03-11", 0.0070, 0),
    ]
    register(
        spark,
        "booking.silver.dim_hotel",
        spark.createDataFrame(hotels, "hotel_id STRING, tz STRING, __END_AT TIMESTAMP"),
    )
    register(
        spark,
        "booking.silver.dim_room",
        spark.createDataFrame(rooms, "hotel_id STRING, room_id STRING, __END_AT TIMESTAMP"),
    )
    register(
        spark,
        "booking.silver.fx_rates",
        silver.fx_rates(
            spark.createDataFrame(
                fx, "currency STRING, date STRING, rate_to_usd DOUBLE, exponent INT"
            )
        ),
    )


@pytest.fixture
def gold(spark):
    """New York: room 1 confirmed for two nights at 200 USD a night, room 2 cancelled, and one
    attempt rejected. Tokyo: one room confirmed for two nights at 15,000 JPY a night, across an
    FX change."""
    load_silver(
        spark,
        stay(1, ROOM, "confirmed", 40000)
        + stay(2, ROOM_2, "cancelled", 9000)
        + stay(3, ROOM_T, "confirmed", 30000, hotel=TOKYO, currency="JPY")
        + [REJECTED, REJECTED],  # one rejected attempt, delivered twice
    )
    return {name: run(spark, f"pipeline/gold/{name}.sql") for name in GOLD}


def kpi(gold, hotel, day):
    df, _ = gold["kpi_hotel_daily"]
    return df.where(f"hotel_id = '{hotel}' AND date = '{day}'").first()


def test_gold_kpis(gold):
    ny = kpi(gold, HOTEL, "2026-03-10")
    assert (ny.available_room_nights, ny.sold_room_nights) == (2, 1)
    assert (ny.occupancy, ny.adr_usd, ny.revpar_usd) == pytest.approx((0.5, 200.0, 100.0))
    tokyo = kpi(gold, TOKYO, "2026-03-11")
    assert (tokyo.occupancy, tokyo.adr_usd, tokyo.revpar_usd) == pytest.approx((1.0, 105.0, 105.0))


def test_fx_per_night(gold):
    df, constraints = gold["fact_room_night"]
    revenue = {r.night: r.revenue_usd for r in df.where(f"room_id = '{ROOM_T}'").collect()}
    assert revenue == pytest.approx({date(2026, 3, 10): 100.5, date(2026, 3, 11): 105.0})
    assert broken(df, constraints) == {}


def test_lead_time_across_midnight(gold):
    # Created 2026-03-01 23:30 UTC: 18:30 on 1 March in New York, 08:30 on 2 March in Tokyo.
    df, _ = gold["fact_booking"]
    lead = {r.booking_id: r.lead_time_days for r in df.collect()}
    assert (lead[booking_id(1)], lead[booking_id(3)]) == (9, 8)


def test_demand_marts(gold):
    cancellations = gold["cancellation_rate"][0].where(f"hotel_id = '{HOTEL}'").first()
    assert cancellations.cancellation_rate == pytest.approx(0.5)
    pace = gold["booking_pace"][0].where("stay_date = '2026-03-10'").collect()
    assert {(r.days_before, r.cumulative_bookings) for r in pace} == {(9, 1), (8, 2)}
    [region] = gold["conflict_rate_by_region"][0].collect()
    assert (region.attempts, region.rejected) == (4, 1)


def test_gold_invariant(spark):
    load_silver(spark, stay(1, ROOM, "confirmed", 40000) + stay(4, ROOM, "confirmed", 20000))
    run(spark, "pipeline/gold/dim_date.sql")
    df, constraints = run(spark, "pipeline/gold/fact_room_night.sql")
    assert broken(df, constraints) == {"one_confirmed_booking_per_room_night": 2}
    with pytest.raises(PySparkException, match="two confirmed bookings"):
        run(spark, "checks/gold_invariant.sql")[0].collect()


def test_gold_invariant_passes_on_clean_data(spark):
    load_silver(spark, stay(1, ROOM, "confirmed", 40000) + stay(2, ROOM_2, "confirmed", 40000))
    run(spark, "checks/gold_invariant.sql")[0].collect()


def test_cdc_oracle_out_of_order(spark):
    events = stay(1, ROOM, "cancelled", 40000)
    shuffled = events + events[:2]
    random.Random(3).shuffle(shuffled)
    load_silver(spark, shuffled)
    [row] = run(spark, "checks/cdc_latest.sql")[0].collect()
    assert (row.status, row.version) == ("cancelled", 3)


def test_cdc_matches_fails_on_a_difference(spark):
    load_silver(spark, stay(1, ROOM, "cancelled", 40000))
    run(spark, "checks/cdc_matches.sql")[0].collect()
    stale = run(spark, "checks/cdc_latest.sql")[0].withColumn("version", F.lit(2).cast("bigint"))
    register(spark, "booking.silver.bookings", stale)
    with pytest.raises(PySparkException, match="differs from the AUTO CDC oracle"):
        run(spark, "checks/cdc_matches.sql")[0].collect()
