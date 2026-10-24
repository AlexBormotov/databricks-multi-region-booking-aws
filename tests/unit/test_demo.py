import random
from datetime import date

import pytest

from ops.cost_report import report
from ops.demo import contention, live_regions, replayed
from ops.session import rows


def summary(created=0, conflict=0, busy=0, other=0, retried=0):
    return {"created": created, "conflict": conflict, "busy": busy, "other": other,
            "retried": retried}  # fmt: skip


def test_contention_adds_up_the_instances():
    result = contention([summary(1, 333), summary(0, 333, retried=50), summary(0, 333)], 1000)
    assert result["failures"] == [] and result["created"] == 1 and result["retried"] == 50


def test_contention_fails_on_two_winners_lost_answers_and_odd_statuses():
    result = contention([summary(1, 499), summary(1, 496, busy=1, other=1)], 1000)
    assert result["failures"] == [
        "2 bookings created, expected exactly 1",
        "1 attempts still answered 503 after every retry",
        "1 responses were neither 201, 409 nor 503",
        "999 of 1000 attempts answered",
    ]


def test_cost_report_judges_the_budget_on_the_account_total():
    result = report(date(2027, 1, 15), {"AWS Lambda": 0.1}, {"AWS Lambda": 0.1, "Bedrock": 6.95})
    assert (result["aws_tagged_usd"], result["aws_account_usd"]) == (0.1, 7.05)
    assert result["within_budget"] is False


def test_cost_report_adds_databricks_to_the_budget():
    result = report(date(2027, 1, 15), {}, {"AWS Lambda": 0.5}, {"JOBS_SERVERLESS": 6.6})
    assert result["databricks_usd"] == 6.6 and result["within_budget"] is False
    assert report(date(2027, 1, 15), {}, {"AWS Lambda": 0.5})["databricks_usd"] is None


def test_only_live_event_files_count_as_landed():
    keys = [
        "events/region=us-east-1/backfill/part-0000.json.gz",
        "events/region=us-east-2/backfill/part-0000.json.gz",
        "events/region=us-east-1/dt=2027-01-15/booking-landing-1.gz",
        "reference/hotels.json.gz",
    ]
    assert live_regions(keys) == {"us-east-1"}


def statement_response(state, data=None):
    return {
        "status": {"state": state},
        "manifest": {"schema": {"columns": [{"name": "home_region"}, {"name": "bookings"}]}},
        "result": {"data_array": data or []},
    }


def test_statement_rows_are_dicts_and_a_failed_statement_raises():
    response = statement_response("SUCCEEDED", [["us-east-1", "3"], ["us-east-2", "2"]])
    assert rows(response) == [
        {"home_region": "us-east-1", "bookings": "3"},
        {"home_region": "us-east-2", "bookings": "2"},
    ]
    with pytest.raises(RuntimeError, match="FAILED"):
        rows(statement_response("FAILED"))


def test_replay_sends_every_event_twice_out_of_order():
    lines = [f'{{"event_id": "{i}"}}'.encode() for i in range(20)]
    copies = replayed(lines, random.Random(7))
    assert sorted(copies) == sorted(lines * 2)
    assert copies != lines * 2
