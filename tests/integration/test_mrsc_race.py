"""The MRSC race script's counting, against DynamoDB Local. DynamoDB Local keeps one database per
region, so both clients use one region here; the cross-region run is the cloud run's."""

import sys
from pathlib import Path

from support import dynamodb
from test_dynamodb_spike import table  # noqa: F401  (fixture)

sys.path.insert(0, str(Path(__file__).parents[2] / "spike" / "dynamodb"))
import mrsc_race  # noqa: E402


def test_mrsc_race(table):  # noqa: F811
    _, name = table
    clients = {"a": dynamodb("us-east-1"), "b": dynamodb("us-east-1")}
    result = mrsc_race.race(clients, name, attempts=40)
    assert result["failures"] == []
    assert sum(sum(o.values()) for o in result["outcomes"].values()) == 40
    label, booking = result["winner"]
    assert result["holders"] == {"a": booking, "b": booking}
