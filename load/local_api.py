"""The API handler behind a local HTTP server, so k6 can run the contention scenario before any
cloud spend (`make k6-local`). PostgreSQL stands in for DSQL, moto for Kinesis and Step Functions.

    python load/local_api.py --port 8080 --room-file /tmp/room.json

It recreates the database `k6_local`, migrates and seeds it, and writes the contested room to
`--room-file` before it starts serving.
"""

import argparse
import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

import boto3
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from booking.db import create_pool, migrate
from booking.handlers import api, runtime
from booking.seed import seed

DATABASE = "k6_local"
FAKE_AWS = {"region_name": "us-east-1", "aws_access_key_id": "x", "aws_secret_access_key": "x"}


def fresh_database() -> str:
    admin_url = os.environ["DATABASE_URL"]
    with psycopg.connect(admin_url, autocommit=True) as admin:
        name = sql.Identifier(DATABASE)
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(name))
    return make_conninfo(admin_url, dbname=DATABASE)


def fake_aws() -> None:
    """A stream and a state machine in moto, so telemetry and saga starts succeed."""
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
    os.environ.update(
        AWS_REGION="us-east-1",
        AWS_ACCESS_KEY_ID="x",
        AWS_SECRET_ACCESS_KEY="x",
        STREAM_NAME=stream,
        STATE_MACHINE_ARN=machine,
    )


class Server(ThreadingHTTPServer):
    # The default listen backlog of 5 refuses connections when every VU starts at once.
    request_queue_size = 1024


class Handler(BaseHTTPRequestHandler):
    def _serve(self):
        url = urlsplit(self.path)
        length = int(self.headers.get("content-length") or 0)
        event = {
            "routeKey": f"{self.command} {url.path}",
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "queryStringParameters": dict(parse_qsl(url.query)) or None,
            "pathParameters": None,
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

    os.environ["DATABASE_URL"] = fresh_database()
    fake_aws()
    with create_pool(max_size=1) as admin:
        migrate(admin)
        seed(admin, 7, "small")
        with admin.connection() as conn:
            hotel_id, room_id = conn.execute(
                "SELECT hotel_id, room_id FROM rooms ORDER BY room_id LIMIT 1"
            ).fetchone()
    # Every connection open before the first request, as each Lambda container holds its own;
    # a pool that grows on demand would queue the first wave and hide the race.
    pool = create_pool(min_size=50, max_size=50)
    pool.open(wait=True)
    runtime.pool = lambda: pool
    server = Server(("127.0.0.1", args.port), Handler)
    # Written once the port is bound: the file's existence is the "ready" signal.
    with open(args.room_file, "w") as f:
        json.dump({"hotel_id": str(hotel_id), "room_id": str(room_id)}, f)
    server.serve_forever()


if __name__ == "__main__":
    main()
