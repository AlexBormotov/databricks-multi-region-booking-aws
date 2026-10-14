"""The emulators the integration tests depend on are reachable."""

import os

import boto3
import psycopg

FAKE_CREDENTIALS = {
    "region_name": "us-east-1",
    "aws_access_key_id": "testing",
    "aws_secret_access_key": "testing",
}


def test_postgres():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        assert conn.execute("select 1").fetchone() == (1,)


def test_moto():
    s3 = boto3.client("s3", endpoint_url=os.environ["MOTO_ENDPOINT_URL"], **FAKE_CREDENTIALS)
    assert "Buckets" in s3.list_buckets()


def test_dynamodb_local():
    ddb = boto3.client(
        "dynamodb", endpoint_url=os.environ["DYNAMODB_ENDPOINT_URL"], **FAKE_CREDENTIALS
    )
    assert "TableNames" in ddb.list_tables()
