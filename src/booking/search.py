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


def retrieve(client, kb_id: str, q: str, k: int = TOP_K) -> list[dict]:
    """The top `k` hotels for `q`, best first. The data source does not chunk documents
    (infra/modules/search), so each result is one hotel."""
    results = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": q},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": k}},
    )["retrievalResults"]
    return [{"hotel_id": r["metadata"]["hotel_id"], "city": r["metadata"]["city"]} for r in results]


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
