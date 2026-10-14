import json
import uuid

from support import HOLD, T0, dynamodb

from booking.guests import VAULTS, Guest, register
from booking.service import BookingRequest, book


def stored_in(guest_id):
    return {
        jurisdiction
        for jurisdiction, (region, table) in VAULTS.items()
        if "Item" in dynamodb(region).get_item(TableName=table, Key={"guest_id": {"S": guest_id}})
    }


def test_pii_residency(vaults, pool, room):
    email = f"{uuid.uuid4().hex}@example.org"
    eu_guest = Guest("Anna Schmidt", email, "+49 30 1234567", "de")
    registered = register(eu_guest, dynamodb_for=dynamodb)

    assert registered["jurisdiction"] == "eu"
    assert stored_in(registered["guest_id"]) == {"eu"}

    us_guest = register(
        Guest("John Doe", "j@example.org", "+1 555 0100", "CA"), dynamodb_for=dynamodb
    )
    assert stored_in(us_guest["guest_id"]) == {"us"}

    hotel_id, room_id = room
    req = BookingRequest(
        hotel_id, room_id, uuid.UUID(registered["guest_id"]), T0.date(), T0.date().replace(day=3)
    )
    assert book(pool, "k", req, region="us-east-1", hold_ttl=HOLD).status_code == 201

    with pool.connection() as conn:
        stored = json.dumps([row[0] for row in conn.execute("SELECT payload FROM outbox")])
        bookings = json.dumps(conn.execute("SELECT * FROM bookings").fetchall(), default=str)
    for pii in (eu_guest.name, eu_guest.email, eu_guest.phone):
        assert pii not in stored
        assert pii not in bookings
    assert registered["guest_id"] in stored
