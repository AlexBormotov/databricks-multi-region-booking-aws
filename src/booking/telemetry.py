"""Rejected booking attempts, put straight to Kinesis for the per-region conflict metrics.

Telemetry, not state: a lost record breaks no invariant, so a failure is logged and swallowed.
"""

import logging
from datetime import datetime

from booking.domain import uuid7
from booking.events import envelope
from booking.service import BookingRequest

log = logging.getLogger(__name__)


def record_rejection(
    kinesis, stream: str, region: str, req: BookingRequest, status_code: int, at: datetime
) -> None:
    try:
        kinesis.put_record(
            StreamName=stream,
            PartitionKey=str(req.room_id),
            Data=envelope(
                event_id=uuid7(),
                event_type="BookingAttemptRejected",
                aggregate_id=None,
                aggregate_version=None,
                home_region=region,
                occurred_at=at,
                payload={
                    "hotel_id": str(req.hotel_id),
                    "room_id": str(req.room_id),
                    "check_in": req.check_in.isoformat(),
                    "check_out": req.check_out.isoformat(),
                    "status_code": status_code,
                },
            ),
        )
    except Exception:
        log.warning("dropped BookingAttemptRejected telemetry", exc_info=True)
