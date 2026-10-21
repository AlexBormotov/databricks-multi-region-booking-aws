"""Search with retrieval stubbed at the client boundary: botocore's Stubber checks the request
against the bedrock-agent-runtime model, and availability comes from DynamoDB Local."""

import json
import uuid
from datetime import UTC, date, datetime

import boto3
import pytest
from botocore.stub import Stubber
from support import FAKE_AWS, add_room, hold, stay

from booking import search
from booking.handlers import api, runtime

KB_ID = "KB12345678"
CHECK_IN, CHECK_OUT = date(2027, 1, 10), date(2027, 1, 12)


def add_hotel(db):
    hotel_id = uuid.uuid4()
    add_room(db, hotel_id, uuid.uuid4(), rate=15000, currency="USD")
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
                "vectorSearchConfiguration": {"numberOfResults": search.TOP_K}
            },
        },
    )
    stubber.activate()
    return client, stubber


@pytest.fixture
def hotels(db, room):
    """The `room` fixture's hotel is booked for the stay; a second hotel stays free."""
    booked, _ = room
    # Held now, so the hold is live whenever the test runs.
    held = hold(db, "k1", stay(room, CHECK_IN, length=2), at=datetime.now(UTC))
    assert held.status_code == 201
    return booked, add_hotel(db)


def test_search_filters_unavailable(db, hotels):
    booked, free = hotels
    unknown = uuid.uuid4()  # in the corpus, not in the store
    client, stubber = stubbed(booked, free, unknown)
    found = search.search(db, client, KB_ID, "quiet hotel with a pool", CHECK_IN, CHECK_OUT)
    stubber.assert_no_pending_responses()
    assert found == [{"hotel_id": str(free), "city": "New York", "free_rooms": 1}]


def test_search_keeps_the_rank(db):
    ids = [add_hotel(db) for _ in range(3)]
    client, _ = stubbed(*reversed(ids))
    found = search.search(db, client, KB_ID, "quiet hotel with a pool", CHECK_IN, CHECK_OUT)
    assert [h["hotel_id"] for h in found] == [str(h) for h in reversed(ids)]


def test_search_route(monkeypatch, db, hotels):
    booked, free = hotels
    client, _ = stubbed(booked, free, q="pool")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", KB_ID)
    monkeypatch.setattr(runtime, "store", lambda: db)
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
    monkeypatch.setattr(runtime, "store", lambda: None)
    monkeypatch.setattr(runtime, "client", lambda service, region: None)
    response = api.handler({"routeKey": "GET /search", "queryStringParameters": query}, None)
    assert response["statusCode"] == 400, response["body"]
