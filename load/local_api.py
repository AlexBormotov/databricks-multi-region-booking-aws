"""The API handler behind a local HTTP server, so k6 can run the contention scenario before any
cloud spend (`make k6-local`). DynamoDB Local stands in for the MRSC tables, moto for Kinesis and
Step Functions.

    python load/local_api.py --port 8080 --room-file /tmp/room.json

It creates the booking tables under a fresh prefix, seeds them, and writes the contested room to
`--room-file` before it starts serving.
"""

import argparse
import json
import os
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

import boto3
from botocore.config import Config

from booking.handlers import api, runtime
from booking.seed import seed
from booking.store import Store, create_tables

# DynamoDB Local keeps one database per access key; these match the integration tests'.
FAKE_AWS = {
    "region_name": "us-east-1",
    "aws_access_key_id": "testing",
    "aws_secret_access_key": "testing",
}


def fake_aws() -> dict[str, str]:
    """A stream and a state machine in moto, so telemetry and saga starts succeed; returns the
    environment the handler needs to find them."""
    endpoint = os.environ["MOTO_ENDPOINT_URL"]
    stream = f"events-{uuid.uuid4().hex[:8]}"
    boto3.client("kinesis", endpoint_url=endpoint, **FAKE_AWS).create_stream(
        StreamName=stream, ShardCount=1
    )
    machine = boto3.client("stepfunctions", endpoint_url=endpoint, **FAKE_AWS).create_state_machine(
        name=f"saga-{uuid.uuid4().hex[:8]}",
        definition=json.dumps({"StartAt": "Done", "States": {"Done": {"Type": "Succeed"}}}),
        roleArn="arn:aws:iam::123456789012:role/booking-saga",
    )["stateMachineArn"]
    return {
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "STREAM_NAME": stream,
        "STATE_MACHINE_ARN": machine,
    }


# API Gateway matches path templates; the one route with a path parameter is matched here.
CANCEL = re.compile(r"/bookings/(?P<booking_id>[^/]+)/cancel")


class Server(ThreadingHTTPServer):
    # The default listen backlog of 5 refuses connections when every VU starts at once.
    request_queue_size = 1024


class Handler(BaseHTTPRequestHandler):
    def _serve(self):
        url = urlsplit(self.path)
        length = int(self.headers.get("content-length") or 0)
        route, params = f"{self.command} {url.path}", None
        if match := CANCEL.fullmatch(url.path):
            route, params = f"{self.command} /bookings/{{booking_id}}/cancel", match.groupdict()
        event = {
            "routeKey": route,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "queryStringParameters": dict(parse_qsl(url.query)) or None,
            "pathParameters": params,
            "body": self.rfile.read(length).decode() if length else None,
        }
        response = api.handler(event, None)
        body = response["body"].encode()
        self.send_response(response["statusCode"])
        for key, value in response["headers"].items():
            self.send_header(key, value)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _serve

    def log_message(self, *args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--room-file", required=True)
    args = parser.parse_args()

    os.environ.update(fake_aws())
    # A connection per concurrent request, as each Lambda container holds its own.
    client = boto3.client(
        "dynamodb",
        endpoint_url=os.environ["DYNAMODB_ENDPOINT_URL"],
        config=Config(max_pool_connections=200),
        **FAKE_AWS,
    )
    store = Store(client, f"k6{uuid.uuid4().hex[:8]}")
    create_tables(store)
    seed(store, 7, "small")
    first = min(store.scan("rooms"), key=lambda r: r["room_id"])
    hotel_id, room_id = first["hotel_id"], first["room_id"]
    runtime.store = lambda: store
    server = Server(("127.0.0.1", args.port), Handler)
    # Written once the port is bound: the file's existence is the "ready" signal.
    with open(args.room_file, "w") as f:
        json.dump({"hotel_id": str(hotel_id), "room_id": str(room_id)}, f)
    server.serve_forever()


if __name__ == "__main__":
    main()
