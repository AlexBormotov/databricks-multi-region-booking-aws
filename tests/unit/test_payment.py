import pytest

from booking.saga import PaymentDeclined, pay


def test_pay_declines_at_the_failure_rate():
    pay(failure_rate=0.5, latency_s=0, rng=lambda: 0.5, sleep=lambda s: None)
    with pytest.raises(PaymentDeclined):
        pay(failure_rate=0.5, latency_s=0, rng=lambda: 0.49, sleep=lambda s: None)
