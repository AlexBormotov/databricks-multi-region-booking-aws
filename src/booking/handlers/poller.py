"""Outbox poller, started by EventBridge once a minute in each active region."""

import os

from booking.handlers import runtime
from booking.outbox import run_poller


def handler(event, context):
    published = run_poller(
        runtime.pool(),
        runtime.kinesis(),
        runtime.stream(),
        runtime.region(),
        seconds=float(os.environ.get("POLLER_SECONDS", "55")),
    )
    return {"published": published}
