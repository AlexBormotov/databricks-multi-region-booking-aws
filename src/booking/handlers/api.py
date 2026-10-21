"""API Gateway HTTP API (payload 2.0) routes."""

import json
import logging
import os
import uuid
from datetime import UTC, date, datetime

from booking import guests, search, service, telemetry
from booking.handlers import runtime
from booking.service import BookingRequest, Response

log = logging.getLogger(__name__)


def handler(event, context):
    route = ROUTES.get(event["routeKey"])
    if route is None:
        return _http(Response(404, {"error": "no such route"}))
    try:
        return _http(route(event))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as err:
        return _http(Response(400, {"error": f"bad request: {err}"}))


def _http(response: Response) -> dict:
    return {
        "statusCode": response.status_code,
        "headers": {"content-type": "application/json", **response.headers},
        "body": json.dumps(response.body),
    }


def _body(event) -> dict:
    return json.loads(event.get("body") or "{}")


def register_guest(event) -> Response:
    body = _body(event)
    guest = guests.Guest(body["name"], body["email"], body["phone"], body["country"])
    return Response(201, guests.register(guest, dynamodb_for=runtime.dynamodb))


def get_availability(event) -> Response:
    query = event.get("queryStringParameters") or {}
    rooms = service.availability(
        runtime.store(),
        uuid.UUID(query["hotel_id"]),
        date.fromisoformat(query["check_in"]),
        date.fromisoformat(query["check_out"]),
    )
    return Response(200, {"room_ids": [str(room) for room in rooms]})


def create_booking(event) -> Response:
    idem_key = (event.get("headers") or {}).get("idempotency-key")
    if not idem_key:
        return Response(400, {"error": "the Idempotency-Key header is required"})
    body = _body(event)
    req = BookingRequest(
        uuid.UUID(body["hotel_id"]),
        uuid.UUID(body["room_id"]),
        uuid.UUID(body["guest_id"]),
        date.fromisoformat(body["check_in"]),
        date.fromisoformat(body["check_out"]),
    )
    response = service.book(
        runtime.store(), idem_key, req, region=runtime.region(), hold_ttl=runtime.hold_ttl()
    )
    if response.status_code in (200, 201):
        # A replay starts the saga again too: the execution name makes the start idempotent.
        _start_saga(response.body["booking_id"])
    elif response.status_code in (409, 503):
        telemetry.record_rejection(
            runtime.kinesis(),
            runtime.stream(),
            runtime.region(),
            req,
            response.status_code,
            datetime.now(UTC),
        )
    return response


def _start_saga(booking_id: str) -> None:
    """A lost start costs a room for one hold TTL, never a double booking: the hold then expires
    lazily at the next booking or availability read."""
    sfn = runtime.stepfunctions()
    try:
        sfn.start_execution(
            stateMachineArn=os.environ["STATE_MACHINE_ARN"],
            name=booking_id,
            input=json.dumps({"booking_id": booking_id}),
        )
    except sfn.exceptions.ExecutionAlreadyExists:
        pass
    except Exception:
        log.exception("saga start failed for %s; the hold will expire lazily", booking_id)


def search_hotels(event) -> Response:
    query = event.get("queryStringParameters") or {}
    hotels = search.search(
        runtime.store(),
        runtime.client("bedrock-agent-runtime", search.KB_REGION),
        os.environ["KNOWLEDGE_BASE_ID"],
        query["q"],
        date.fromisoformat(query["check_in"]),
        date.fromisoformat(query["check_out"]),
    )
    return Response(200, {"hotels": hotels})


def cancel_booking(event) -> Response:
    booking_id = uuid.UUID(event["pathParameters"]["booking_id"])
    return service.cancel(runtime.store(), booking_id, region=runtime.region())


ROUTES = {
    "POST /guests": register_guest,
    "GET /availability": get_availability,
    "POST /bookings": create_booking,
    "POST /bookings/{booking_id}/cancel": cancel_booking,
    "GET /search": search_hotels,
}
