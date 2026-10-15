"""Search with retrieval stubbed at the client boundary: botocore's Stubber checks the request
against the bedrock-agent-runtime model, and availability comes from PostgreSQL."""

import json
import uuid
from datetime import UTC, date, datetime

import boto3
import pytest
from botocore.stub import Stubber
from support import FAKE_AWS, hold, stay

from booking import search
from booking.handlers import api, runtime

KB_ID = "KB12345678"
CHECK_IN, CHECK_OUT = date(2027, 1, 10), date(2027, 1, 12)


def add_hotel(pool, city):
    hotel_id = uuid.uuid4()
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO hotels VALUES (%s, %s, %s, 'US', 'America/New_York', 'USD', 40.7, -74.0)",
            (hotel_id, f"{city} Hotel", city),
        )
        conn.execute(
            "INSERT INTO rooms VALUES (%s, %s, 'standard', 15000)", (uuid.uuid4(), hotel_id)
        )
    return hotel_id


def chunk(hotel_id, city="New York"):
    return {
        "content": {"text": "A boutique hotel."},
        "metadata": {"hotel_id": str(hotel_id), "city": city, "country": "US"},
    }


def stubbed(*hotel_ids, q="quiet hotel with a pool"):
    client = boto3.client("bedrock-agent-runtime", **FAKE_AWS)
    stubber = Stubber(client)
    stubber.add_response(
        "retrieve",
        {"retrievalResults": [chunk(h) for h in hotel_ids]},
        {
            "knowledgeBaseId": KB_ID,
            "retrievalQuery": {"text": q},
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {
                    "numberOfResults": search.TOP_K * search.CHUNKS_PER_HOTEL
                }
            },
        },
    )
    stubber.activate()
    return client, stubber


@pytest.fixture
def hotels(pool, room):
    """The `room` fixture's hotel is booked for the stay; a second hotel stays free."""
    booked, _ = room
    # Held now, so the hold is live whenever the test runs.
    held = hold(pool, "k1", stay(room, CHECK_IN, length=2), at=datetime.now(UTC))
    assert held.status_code == 201
    return booked, add_hotel(pool, "New York")


def test_search_filters_unavailable(pool, hotels):
    booked, free = hotels
    unknown = uuid.uuid4()  # in the corpus, not in DSQL
    client, stubber = stubbed(booked, free, free, unknown)
    found = search.search(pool, client, KB_ID, "quiet hotel with a pool", CHECK_IN, CHECK_OUT)
    stubber.assert_no_pending_responses()
    assert found == [{"hotel_id": str(free), "city": "New York", "free_rooms": 1}]


def test_search_keeps_the_rank_and_the_top_k(pool):
    ids = [add_hotel(pool, "Chicago") for _ in range(search.TOP_K + 2)]
    client, _ = stubbed(*reversed(ids))
    found = search.search(pool, client, KB_ID, "quiet hotel with a pool", CHECK_IN, CHECK_OUT)
    assert [h["hotel_id"] for h in found] == [str(h) for h in reversed(ids)][: search.TOP_K]


def test_search_route(monkeypatch, pool, hotels):
    booked, free = hotels
    client, _ = stubbed(booked, free, q="pool")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", KB_ID)
    monkeypatch.setattr(runtime, "pool", lambda: pool)
    monkeypatch.setattr(runtime, "client", lambda service, region: client)
    query = {"q": "pool", "check_in": "2027-01-10", "check_out": "2027-01-12"}
    response = api.handler({"routeKey": "GET /search", "queryStringParameters": query}, None)
    assert response["statusCode"] == 200
    assert [h["hotel_id"] for h in json.loads(response["body"])["hotels"]] == [str(free)]


@pytest.mark.parametrize(
    "query",
    [
        None,
        {"q": "pool", "check_in": "2027-01-10"},
        {"q": " ", "check_in": "2027-01-10", "check_out": "2027-01-12"},
        {"q": "pool", "check_in": "2027-01-12", "check_out": "2027-01-10"},
        {"q": "pool", "check_in": "10/01/2027", "check_out": "2027-01-12"},
    ],
)
def test_search_route_rejects_bad_input(monkeypatch, query):
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", KB_ID)
    monkeypatch.setattr(runtime, "pool", lambda: None)
    monkeypatch.setattr(runtime, "client", lambda service, region: None)
    response = api.handler({"routeKey": "GET /search", "queryStringParameters": query}, None)
    assert response["statusCode"] == 400, response["body"]
