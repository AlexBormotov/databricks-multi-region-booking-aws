import pytest
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def spark():
    # Small and UTC, like the pipeline: hotel-local dates are always computed explicitly.
    session = (
        SparkSession.builder.master("local[2]")
        .appName("lakehouse-tests")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()
