from datetime import date
from itertools import product

import pytest

from booking.domain import MAX_NIGHTS, IllegalTransition, Status, nights, transition, uuid7

LEGAL = {
    (Status.PENDING, Status.CONFIRMED),
    (Status.PENDING, Status.EXPIRED),
    (Status.PENDING, Status.CANCELLED),
    (Status.CONFIRMED, Status.CANCELLED),
}


@pytest.mark.parametrize("current,target", list(product(Status, Status)))
def test_status_transitions(current, target):
    if (current, target) in LEGAL:
        assert transition(current, target) == target
    else:
        with pytest.raises(IllegalTransition):
            transition(current, target)


def test_nights_are_the_half_open_stay():
    assert nights(date(2027, 2, 27), date(2027, 3, 2)) == [
        date(2027, 2, 27),
        date(2027, 2, 28),
        date(2027, 3, 1),
    ]


@pytest.mark.parametrize("length", [0, -1, MAX_NIGHTS + 1])
def test_nights_reject_empty_reversed_and_long_stays(length):
    start = date(2027, 1, 1)
    with pytest.raises(ValueError):
        nights(start, date.fromordinal(start.toordinal() + length))


def test_uuid7_is_version_7_and_time_ordered():
    ids = [uuid7() for _ in range(1000)]
    assert {u.version for u in ids} == {7}
    assert [u.int >> 80 for u in ids] == sorted(u.int >> 80 for u in ids)
