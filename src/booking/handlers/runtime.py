"""Clients and settings shared by the handlers, created once per Lambda container."""

import os
from datetime import timedelta
from functools import cache

import boto3

from booking.store import Store

# The single event stream lives in us-east-1; the us-east-2 functions put to it cross-region.
STREAM_REGION = "us-east-1"


def region() -> str:
    return os.environ["AWS_REGION"]


def hold_ttl() -> timedelta:
    return timedelta(seconds=int(os.environ.get("HOLD_TTL_S", "900")))


def stream() -> str:
    return os.environ["STREAM_NAME"]


@cache
def store() -> Store:
    # The tables are replicated; each region's functions use their local replica.
    return Store(client("dynamodb", region()), os.environ.get("STORE_PREFIX", "booking"))


@cache
def client(service: str, client_region: str):
    # Locally the emulators stand in for AWS; in Lambda these variables are unset.
    endpoint = {
        "dynamodb": os.environ.get("DYNAMODB_ENDPOINT_URL"),
    }.get(service, os.environ.get("MOTO_ENDPOINT_URL"))
    return boto3.client(service, region_name=client_region, endpoint_url=endpoint)


def kinesis():
    return client("kinesis", STREAM_REGION)


def dynamodb(vault_region: str):
    return client("dynamodb", vault_region)


def stepfunctions():
    return client("stepfunctions", region())
