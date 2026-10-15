"""Semantic hotel search: the knowledge base ranks hotels for the query, DSQL keeps those with a
free room for the stay."""

import uuid
from datetime import date

from psycopg_pool import ConnectionPool

from booking.domain import nights
from booking.service import Clock, availability, utc_now

# The knowledge base lives in us-east-1 only; the us-east-2 functions call it cross-region.
KB_REGION = "us-east-1"
TOP_K = 10
# A hotel's document can split into several chunks; ask for more chunks than hotels.
CHUNKS_PER_HOTEL = 3


def retrieve(client, kb_id: str, q: str, k: int = TOP_K) -> list[dict]:
    """The top `k` distinct hotels for `q`, best first, as their metadata attributes."""
    results = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": q},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": k * CHUNKS_PER_HOTEL}
        },
    )["retrievalResults"]
    hotels: dict[str, dict] = {}
    for result in results:
        metadata = result.get("metadata", {})
        hotel_id = metadata.get("hotel_id")
        if hotel_id and hotel_id not in hotels:
            hotels[hotel_id] = {"hotel_id": hotel_id, "city": metadata.get("city")}
    return list(hotels.values())[:k]


def search(
    pool: ConnectionPool,
    client,
    kb_id: str,
    q: str,
    check_in: date,
    check_out: date,
    *,
    clock: Clock = utc_now,
) -> list[dict]:
    """Ranked hotels for `q` that have at least one room free on every night of the stay."""
    if not q.strip():
        raise ValueError("q is empty")
    nights(check_in, check_out)
    found = []
    for hotel in retrieve(client, kb_id, q):
        # A hotel in the corpus but not in DSQL has no rooms, so it drops out here too.
        rooms = availability(pool, uuid.UUID(hotel["hotel_id"]), check_in, check_out, clock=clock)
        if rooms:
            found.append({**hotel, "free_rooms": len(rooms)})
    return found
