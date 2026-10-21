"""Rooms from the generator's reference data, so the booking store and the lakehouse describe the
same hotels for a seed. Each room carries its hotel's currency, the one hotel fact a booking needs.
Re-running it writes the same items again."""

from booking.generator import SCALES, reference
from booking.store import Store, dump

ROOM_FIELDS = ("hotel_id", "room_id", "room_type", "base_rate_minor", "currency")


def seed(store: Store, seed_value: int, scale_name: str) -> dict[str, int]:
    """Write the reference rooms; returns how many rooms the store now has."""
    ref = reference(seed_value, SCALES[scale_name])
    currency = {h["hotel_id"]: h["currency"] for h in ref["hotels"]}
    rooms = [{**r, "currency": currency[r["hotel_id"]]} for r in ref["rooms"]]
    for start in range(0, len(rooms), 25):
        pending = {
            store.name("rooms"): [
                {"PutRequest": {"Item": dump({f: r[f] for f in ROOM_FIELDS})}}
                for r in rooms[start : start + 25]
            ]
        }
        while pending:
            pending = store.client.batch_write_item(RequestItems=pending).get("UnprocessedItems")
    return {"rooms": len(store.scan("rooms"))}
