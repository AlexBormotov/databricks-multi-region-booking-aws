"""Guest registration with PII residency: name, email and phone stay in a single-region DynamoDB
vault of the guest's jurisdiction. Everything else in the system sees only guest_id.

The jurisdiction is the declared country of residence. A guest registering from abroad without
proof of residence is stored by what they declare; this limit is documented, not solved.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from booking.domain import uuid7

# EU member states plus the EEA (Iceland, Liechtenstein, Norway), ISO 3166-1 alpha-2.
EU_EEA = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
    + ["IS", "LI", "NO"]
)

# jurisdiction -> (vault region, vault table)
VAULTS = {"eu": ("eu-central-1", "guests-eu"), "us": ("us-east-1", "guests-us")}


@dataclass(frozen=True)
class Guest:
    name: str
    email: str
    phone: str
    country: str


def jurisdiction(country: str) -> str:
    return "eu" if country.upper() in EU_EEA else "us"


def register(
    guest: Guest,
    *,
    dynamodb_for: Callable[[str], object],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    """Store the guest's PII in its jurisdiction's vault; return guest_id and jurisdiction."""
    where = jurisdiction(guest.country)
    region, table = VAULTS[where]
    guest_id: uuid.UUID = uuid7()
    dynamodb_for(region).put_item(
        TableName=table,
        Item={
            "guest_id": {"S": str(guest_id)},
            "name": {"S": guest.name},
            "email": {"S": guest.email},
            "phone": {"S": guest.phone},
            "country": {"S": guest.country.upper()},
            "created_at": {"S": clock().isoformat()},
        },
        ConditionExpression="attribute_not_exists(guest_id)",
    )
    return {"guest_id": str(guest_id), "jurisdiction": where}
