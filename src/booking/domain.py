"""Booking states, legal transitions and value rules. No I/O."""

import os
import time
import uuid
from datetime import date, timedelta
from enum import StrEnum

# A stay claims one item per night, one write each.
MAX_NIGHTS = 30


class Status(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


TRANSITIONS = {
    Status.PENDING: {Status.CONFIRMED, Status.EXPIRED, Status.CANCELLED},
    Status.CONFIRMED: {Status.CANCELLED},
    Status.EXPIRED: set(),
    Status.CANCELLED: set(),
}


class IllegalTransition(ValueError):
    pass


def transition(current: Status, target: Status) -> Status:
    if target not in TRANSITIONS[current]:
        raise IllegalTransition(f"{current} -> {target}")
    return target


def is_live(status: Status, expires_ms: int, now_ms: int) -> bool:
    """A live booking holds its room-nights: confirmed, or pending before its hold expires."""
    return status == Status.CONFIRMED or (status == Status.PENDING and expires_ms > now_ms)


def nights(check_in: date, check_out: date) -> list[date]:
    """Hotel-local nights of the stay [check_in, check_out)."""
    count = (check_out - check_in).days
    if not 1 <= count <= MAX_NIGHTS:
        raise ValueError(f"a stay is 1 to {MAX_NIGHTS} nights, got {count}")
    return [check_in + timedelta(days=i) for i in range(count)]


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: millisecond timestamp first, so ids sort by creation time."""
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10))
    rand_a = (rand >> 62) & 0xFFF
    rand_b = rand & ((1 << 62) - 1)
    return uuid.UUID(int=(ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b)
