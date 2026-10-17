from datetime import date

from ops.cost_report import report
from ops.demo import contention


def summary(created=0, conflict=0, busy=0, other=0):
    return {"created": created, "conflict": conflict, "busy": busy, "other": other}


def test_contention_adds_up_the_instances():
    result = contention([summary(1, 332), summary(0, 333), summary(0, 330, busy=4)], 1000)
    assert result["failures"] == [] and result["created"] == 1 and result["busy"] == 4


def test_contention_fails_on_two_winners_lost_answers_and_odd_statuses():
    result = contention([summary(1, 499), summary(1, 497, other=1)], 1000)
    assert result["failures"] == [
        "2 bookings created, expected exactly 1",
        "1 responses were neither 201, 409 nor 503",
        "999 of 1000 attempts answered",
    ]


def test_cost_report_judges_the_budget_on_the_account_total():
    result = report(date(2027, 1, 15), {"AWS Lambda": 0.1}, {"AWS Lambda": 0.1, "Bedrock": 6.95})
    assert (result["aws_tagged_usd"], result["aws_account_usd"]) == (0.1, 7.05)
    assert result["within_budget"] is False
