"""Synthetic history and reference data for the lakehouse, deterministic for a seed.

Events follow the outbox contract (`booking.outbox.envelope`) and the booking rules: a room-night
is never held twice while live, and a booking that loses the race leaves only a
`BookingAttemptRejected` record, as in the live system.
"""

import gzip
import json
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from booking.outbox import envelope
from booking.saga import REFUND_NAMESPACE

REGIONS = ("us-east-1", "us-east-2")
HOLD_TTL = timedelta(minutes=15)
START = datetime(2026, 1, 1, tzinfo=UTC)

# city, country, time zone, currency, latitude, longitude
CITIES = (
    ("New York", "US", "America/New_York", "USD", 40.71, -74.01),
    ("Chicago", "US", "America/Chicago", "USD", 41.88, -87.63),
    ("London", "GB", "Europe/London", "GBP", 51.51, -0.13),
    ("Berlin", "DE", "Europe/Berlin", "EUR", 52.52, 13.40),
    ("Paris", "FR", "Europe/Paris", "EUR", 48.86, 2.35),
    ("Tokyo", "JP", "Asia/Tokyo", "JPY", 35.68, 139.69),
)
# Units of currency per USD on START; each day moves the rate by a small random step.
FX_START = {"USD": 1.0, "GBP": 0.79, "EUR": 0.92, "JPY": 150.0}


@dataclass(frozen=True)
class Scale:
    hotels: int
    rooms_per_hotel: int
    days: int
    attempts: int


SCALES = {
    "small": Scale(hotels=12, rooms_per_hotel=5, days=90, attempts=2_000),
    "demo": Scale(hotels=60, rooms_per_hotel=20, days=365, attempts=100_000),
}


def _uuid(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


def _uuid7(rng: random.Random, at: datetime) -> uuid.UUID:
    """UUIDv7 for a past instant, with seeded random bits."""
    ms = int(at.timestamp() * 1000)
    return uuid.UUID(
        int=(ms << 80)
        | (0x7 << 76)
        | (rng.getrandbits(12) << 64)
        | (0b10 << 62)
        | rng.getrandbits(62)
    )


def reference(seed: int, scale: Scale) -> dict[str, list[dict]]:
    """Hotels and rooms (the DSQL columns) and daily FX rates to USD."""
    rng = random.Random(seed)
    hotels, rooms = [], []
    for i in range(scale.hotels):
        city, country, tz, currency, lat, lon = CITIES[i % len(CITIES)]
        hotel_id = _uuid(rng)
        hotels.append(
            {
                "hotel_id": str(hotel_id),
                "name": f"{city} Hotel {i + 1}",
                "city": city,
                "country": country,
                "tz": tz,
                "currency": currency,
                "lat": round(lat + rng.uniform(-0.05, 0.05), 5),
                "lon": round(lon + rng.uniform(-0.05, 0.05), 5),
            }
        )
        # Rates in the hotel's currency, minor units (JPY has no minor unit).
        unit = 1 if currency == "JPY" else 100
        base = rng.randint(90, 400) * FX_START[currency]
        for r in range(scale.rooms_per_hotel):
            rooms.append(
                {
                    "room_id": str(_uuid(rng)),
                    "hotel_id": str(hotel_id),
                    "room_type": ("standard", "deluxe", "suite")[r % 3],
                    "base_rate_minor": round(base * (1 + 0.5 * (r % 3)) * unit),
                }
            )
    fx = []
    for currency, rate in FX_START.items():
        for d in range(scale.days + 60):
            day = START.date() + timedelta(days=d)
            fx.append(
                {
                    "currency": currency,
                    "date": day.isoformat(),
                    "rate_to_usd": 1 / rate,
                    "exponent": 0 if currency == "JPY" else 2,
                }
            )
            if currency != "USD":
                rate *= 1 + rng.gauss(0, 0.004)
    return {"hotels": hotels, "rooms": rooms, "fx_rates": fx}


def history(seed: int, scale: Scale, ref: dict[str, list[dict]]) -> list[bytes]:
    """Booking attempts spread over `scale.days`, as encoded events in occurrence order."""
    rng = random.Random(seed + 1)
    hotels = {h["hotel_id"]: h for h in ref["hotels"]}
    taken: set[tuple[str, date]] = set()  # live (room_id, night) claims
    events: list[tuple[datetime, bytes]] = []

    def emit(event_type, aggregate_id, version, region, at, payload, event_id=None):
        events.append(
            (
                at,
                envelope(
                    event_id=event_id or _uuid7(rng, at),
                    event_type=event_type,
                    aggregate_id=aggregate_id,
                    aggregate_version=version,
                    home_region=region,
                    occurred_at=at,
                    payload=payload,
                ),
            )
        )

    for _ in range(scale.attempts):
        room = rng.choice(ref["rooms"])
        hotel = hotels[room["hotel_id"]]
        region = rng.choice(REGIONS)
        created = START + timedelta(seconds=rng.randrange(scale.days * 86_400))
        local_day = created.astimezone(ZoneInfo(hotel["tz"])).date()
        check_in = local_day + timedelta(days=int(rng.expovariate(1 / 21)))
        stay = [check_in + timedelta(days=n) for n in range(rng.randint(1, 5))]
        check_out = stay[-1] + timedelta(days=1)

        if any((room["room_id"], night) in taken for night in stay):
            emit(
                "BookingAttemptRejected",
                None,
                None,
                region,
                created,
                {
                    "hotel_id": room["hotel_id"],
                    "room_id": room["room_id"],
                    "check_in": check_in.isoformat(),
                    "check_out": check_out.isoformat(),
                    "status_code": 409,
                },
            )
            continue

        booking_id = _uuid7(rng, created)
        booking = {
            "booking_id": str(booking_id),
            "hotel_id": room["hotel_id"],
            "room_id": room["room_id"],
            "guest_id": str(_uuid(rng)),
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "status": "pending",
            "expires_at": (created + HOLD_TTL).isoformat(),
            "amount_minor": room["base_rate_minor"] * len(stay),
            "currency": hotel["currency"],
            "version": 1,
            "home_region": region,
            "created_at": created.isoformat(),
            "updated_at": created.isoformat(),
        }
        emit("BookingHeld", booking_id, 1, region, created, booking)

        outcome = rng.random()
        paid_at = created + timedelta(seconds=rng.randint(5, 600))
        if outcome < 0.85:
            steps = [("confirmed", "BookingConfirmed", paid_at)]
            if rng.random() < 0.1:
                cancelled_at = paid_at + timedelta(days=rng.randint(1, 10))
                steps.append(("cancelled", "BookingCancelled", cancelled_at))
            else:
                taken.update((room["room_id"], night) for night in stay)
        else:
            steps = [("expired", "BookingExpired", created + HOLD_TTL)]
        for status, event_type, at in steps:
            booking = {
                **booking,
                "status": status,
                "version": booking["version"] + 1,
                "updated_at": at.isoformat(),
            }
            emit(event_type, booking_id, booking["version"], region, at, booking)
        if outcome > 0.98:  # the payment arrived after the hold expired
            late = at + timedelta(seconds=rng.randint(1, 120))
            emit(
                "PaymentRefunded",
                booking_id,
                booking["version"],
                region,
                late,
                {**booking, "refund_minor": booking["amount_minor"]},
                event_id=uuid.uuid5(REFUND_NAMESPACE, str(booking_id)),
            )

    events.sort(key=lambda e: e[0])
    return [data for _, data in events]


def write(out: Path, seed: int, scale_name: str) -> None:
    """The landing layout: `events/region=<r>/backfill/` and `reference/`, gzip JSON lines.

    The gzip header carries no timestamp, so a seed always produces the same bytes.
    """
    scale = SCALES[scale_name]
    ref = reference(seed, scale)
    for name, rows in ref.items():
        path = out / "reference" / f"{name}.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.GzipFile(path, "wb", mtime=0) as f:
            f.writelines(json.dumps(row).encode() + b"\n" for row in rows)
    by_region: dict[str, list[bytes]] = {r: [] for r in REGIONS}
    for data in history(seed, scale, ref):
        by_region[json.loads(data)["home_region"]].append(data)
    for region, lines in by_region.items():
        path = out / "events" / f"region={region}" / "backfill" / "part-0000.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.GzipFile(path, "wb", mtime=0) as f:
            f.writelines(line + b"\n" for line in lines)
