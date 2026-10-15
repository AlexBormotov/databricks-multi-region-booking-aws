"""Lambda handlers driven by API Gateway HTTP API (payload 2.0) and Step Functions events."""

import json
import os
import uuid

import boto3
import pytest
from support import FAKE_AWS, read_all

from booking.handlers import api, poller, runtime
from booking.handlers import saga as saga_handlers


def http(route_key, body=None, headers=None, path=None, query=None):
    method, raw_path = route_key.split(" ", 1)
    return {
        "version": "2.0",
        "routeKey": route_key,
        "rawPath": raw_path,
        "headers": {"content-type": "application/json", **(headers or {})},
        "queryStringParameters": query,
        "pathParameters": path,
        "requestContext": {"http": {"method": method, "path": raw_path}},
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }


def call(event):
    response = api.handler(event, None)
    return response["statusCode"], json.loads(response["body"])


@pytest.fixture
def lambda_env(monkeypatch, pool, kinesis, vaults):
    _, stream = kinesis
    sfn = boto3.client("stepfunctions", endpoint_url=os.environ["MOTO_ENDPOINT_URL"], **FAKE_AWS)
    machine = sfn.create_state_machine(
        name=f"saga-{uuid.uuid4().hex[:8]}",
        definition=json.dumps({"StartAt": "Done", "States": {"Done": {"Type": "Succeed"}}}),
        roleArn="arn:aws:iam::123456789012:role/booking-saga",
    )["stateMachineArn"]
    for key, value in {
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "STREAM_NAME": stream,
        "STATE_MACHINE_ARN": machine,
        "HOLD_TTL_S": "900",
        "POLLER_SECONDS": "0.5",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(runtime, "pool", lambda: pool)
    runtime.client.cache_clear()
    yield sfn, machine
    runtime.client.cache_clear()


def booking_body(room, guest_id, check_in="2027-01-10", check_out="2027-01-12"):
    hotel_id, room_id = room
    return {
        "hotel_id": str(hotel_id),
        "room_id": str(room_id),
        "guest_id": guest_id,
        "check_in": check_in,
        "check_out": check_out,
    }


def test_guest_then_booking_then_cancel(lambda_env, room, kinesis):
    sfn, machine = lambda_env
    status, guest = call(
        http(
            "POST /guests",
            {"name": "Anna", "email": "a@example.org", "phone": "+49 1", "country": "DE"},
        )
    )
    assert (status, guest["jurisdiction"]) == (201, "eu")

    body = booking_body(room, guest["guest_id"])
    status, booking = call(http("POST /bookings", body, {"idempotency-key": "k1"}))
    assert status == 201
    status, replay = call(http("POST /bookings", body, {"idempotency-key": "k1"}))
    assert (status, replay) == (200, booking)
    # One saga per booking, however many times the request is replayed.
    executions = sfn.list_executions(stateMachineArn=machine)["executions"]
    assert [e["name"] for e in executions] == [booking["booking_id"]]

    hotel_id, room_id = room
    query = {"hotel_id": str(hotel_id), "check_in": "2027-01-11", "check_out": "2027-01-12"}
    assert call(http("GET /availability", query=query)) == (200, {"room_ids": []})

    rival = booking_body(room, str(uuid.uuid4()), "2027-01-11", "2027-01-13")
    assert call(http("POST /bookings", rival, {"idempotency-key": "k2"}))[0] == 409
    client, stream = kinesis
    assert [e["event_type"] for e in read_all(client, stream)] == ["BookingAttemptRejected"]

    cancel = http("POST /bookings/{booking_id}/cancel", path={"booking_id": booking["booking_id"]})
    status, cancelled = call(cancel)
    assert (status, cancelled["status"]) == (200, "cancelled")
    assert call(http("GET /availability", query=query)) == (200, {"room_ids": [str(room_id)]})


@pytest.mark.parametrize(
    "event",
    [
        http("POST /bookings", {"hotel_id": "x"}),  # no Idempotency-Key
        http("POST /bookings", {"hotel_id": "not-a-uuid"}, {"idempotency-key": "k"}),
        http("GET /availability", query={"hotel_id": str(uuid.uuid4())}),
        http("POST /guests", {"name": "no email"}),
    ],
)
def test_bad_requests_are_400(lambda_env, event):
    assert call(event)[0] == 400


def test_unknown_route_is_404(lambda_env):
    assert call(http("DELETE /bookings"))[0] == 404


def test_saga_and_poller_handlers(lambda_env, room, kinesis):
    body = booking_body(room, str(uuid.uuid4()))
    _, booking = call(http("POST /bookings", body, {"idempotency-key": "k"}))
    task = {"booking_id": booking["booking_id"]}

    confirmed = saga_handlers.confirm(task, None)
    assert (confirmed["status_code"], confirmed["body"]["status"]) == (200, "confirmed")
    assert saga_handlers.expire(task, None)["body"]["status"] == "confirmed"

    assert poller.handler({}, None) == {"published": 2}
    client, stream = kinesis
    assert [e["event_type"] for e in read_all(client, stream)] == [
        "BookingHeld",
        "BookingConfirmed",
    ]
