from datetime import date

import pytest
from lake_support import booking_event, bronze

from lakehouse import silver
from lakehouse.rules import RULES


def parsed(spark, events):
    return silver.parse(bronze(spark, events))


def test_dedup_collapses_duplicates(spark):
    held = booking_event()
    confirmed = booking_event("BookingConfirmed", 2, status="confirmed")
    events = parsed(spark, [held, held, confirmed, held, confirmed])
    out = silver.dedup(silver.valid(events))
    assert sorted(r.event_id for r in out.collect()) == sorted(
        [held["event_id"], confirmed["event_id"]]
    )


BAD = {
    "versioned_state_event": booking_event(version=None),
    "known_currency": booking_event(currency="XYZ"),
    "nights_inside_stay": booking_event(check_in="2026-03-12", check_out="2026-03-12"),
}


@pytest.mark.parametrize("rule", RULES)
def test_quarantine_partition(spark, rule):
    good = booking_event()
    events = parsed(spark, [good, BAD[rule]])
    assert [r.event_id for r in silver.valid(events).collect()] == [good["event_id"]]
    quarantined = silver.quarantined(events).collect()
    assert [(r.event_id, r.rule) for r in quarantined] == [(BAD[rule]["event_id"], rule)]


def test_quarantine_takes_the_first_broken_rule(spark):
    both = booking_event(version=None, currency="XYZ")
    [row] = silver.quarantined(parsed(spark, [both])).collect()
    assert row.rule == "versioned_state_event"


def test_telemetry_passes_the_rules(spark):
    rejected = {
        **booking_event("BookingAttemptRejected", None),
        "aggregate_id": None,
        "payload": {"hotel_id": "h", "room_id": "r", "check_in": "2026-03-10",
                    "check_out": "2026-03-11", "status_code": 409},
    }  # fmt: skip
    events = parsed(spark, [rejected])
    assert silver.valid(events).count() == 1
    assert silver.attempts_rejected(events).first().status_code == 409


def test_state_events_exclude_refunds(spark):
    events = parsed(
        spark,
        [
            booking_event(),
            booking_event("BookingExpired", 2, status="expired"),
            booking_event("PaymentRefunded", 2, status="expired"),
        ],
    )
    assert sorted(r.status for r in silver.state_events(events).collect()) == ["expired", "pending"]


def test_booking_nights_are_hotel_local_dates(spark):
    events = parsed(spark, [booking_event(check_in="2026-03-30", check_out="2026-04-02")])
    rows = silver.booking_nights(silver.state_events(events)).orderBy("night").collect()
    assert [r.night for r in rows] == [date(2026, 3, 30), date(2026, 3, 31), date(2026, 4, 1)]
    assert {r.night_amount_minor for r in rows} == {20000 / 3}
