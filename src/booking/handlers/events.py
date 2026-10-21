"""Reads the `bookings` change stream in us-east-1, the only region that has it (plan D18)."""

from booking import events
from booking.handlers import runtime


def handler(event, context):
    return {"published": events.publish(event["Records"], runtime.kinesis(), runtime.stream())}
