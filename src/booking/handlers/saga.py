"""Step Functions tasks of the hold saga. Input: {"booking_id": ...}."""

import os
import uuid

from booking import saga
from booking.handlers import runtime


def pay(event, context):
    """Raises PaymentDeclined on a declined payment; the state machine then expires the hold."""
    saga.pay(
        failure_rate=float(os.environ.get("PAYMENT_FAILURE_RATE", "0.1")),
        latency_s=float(os.environ.get("PAYMENT_LATENCY_S", "2")),
    )
    return {}


def confirm(event, context):
    response = saga.confirm(
        runtime.store(), uuid.UUID(event["booking_id"]), region=runtime.region()
    )
    return {"status_code": response.status_code, "body": response.body}


def expire(event, context):
    response = saga.expire(runtime.store(), uuid.UUID(event["booking_id"]), region=runtime.region())
    return {"status_code": response.status_code, "body": response.body}
