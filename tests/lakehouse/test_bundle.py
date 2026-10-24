"""The bundle, checked without a workspace; the full `bundle validate` runs in the cloud."""

import ast
import importlib
import json
import os
import re
import subprocess

import jsonschema
import pytest
import yaml
from sql_harness import SQL, local, register
from test_gold import gold  # noqa: F401  (fixture)

from ops.demo import GOLD_QUERIES

BUNDLE = SQL / "databricks.yml"


def bundle():
    return yaml.safe_load(BUNDLE.read_text())


def test_bundle_matches_cli_schema():
    schema = subprocess.run(
        ["databricks", "bundle", "schema"], check=True, capture_output=True, text=True
    ).stdout
    # The CLI's patterns use Unicode classes that Python's `re` lacks.
    schema = schema.replace(r"\\p{L}", r"[^\\W\\d_]").replace(r"\\p{N}", r"\\d")
    jsonschema.validate(bundle(), json.loads(schema))


def test_bundle_static_checks_pass():
    """`bundle validate` runs its static checks before it calls the workspace; a fake host makes
    the call the only error left."""
    env = {**os.environ, "DATABRICKS_HOST": "https://workspace.invalid", "DATABRICKS_TOKEN": "x"}
    result = subprocess.run(
        ["databricks", "bundle", "validate", "--var", "landing_path=s3://landing",
         "--var", "warehouse_id=w"],
        cwd=SQL, env=env, capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    errors = [line for line in result.stdout.splitlines() + result.stderr.splitlines()
              if line.startswith("Error:")]  # fmt: skip
    assert len(errors) == 1 and "workspace.invalid" in errors[0], result.stdout + result.stderr


def test_bundle_paths_exist():
    text = BUNDLE.read_text()
    for path in re.findall(r"path: (\./\S+?)[}\s]", text):
        assert (SQL / path).is_file(), path


def test_pipeline_wrappers_import_existing_names():
    for wrapper in (SQL / "pipeline").glob("*.py"):
        for node in ast.walk(ast.parse(wrapper.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module.startswith("lakehouse"):
                module = importlib.import_module(node.module)
                for alias in node.names:
                    assert hasattr(module, alias.name), f"{wrapper.name}: {alias.name}"


EXPECTATIONS = (
    '[{"name": "known_currency", "dataset": "events_dedup", "passed_records": 9,'
    ' "failed_records": 1}]'
)


@pytest.fixture
def quality(spark):
    """booking.gold.data_quality from a stand-in for the pipeline's event log, whose `details` is
    JSON text; an event without expectations adds no rows."""
    log = spark.createDataFrame(
        [("2026-10-24 10:00:00", ("u1",), "flow_progress", f'{{"flow_progress": {{"data_quality":'
          f' {{"expectations": {EXPECTATIONS}}}}}}}'),
         ("2026-10-24 10:00:01", ("u1",), "flow_progress",
          '{"flow_progress": {"status": "RUNNING"}}'),
         ("2026-10-24 10:00:02", ("u1",), "update_progress", "{}")],
        "timestamp STRING, origin STRUCT<update_id: STRING>, event_type STRING, details STRING",
    )  # fmt: skip
    log.createOrReplaceTempView("event_log_stand_in")
    _, body = (SQL / "quality" / "data_quality.sql").read_text().split("\nAS\n", 1)
    body = local(body).replace("event_log(TABLE(silver__events_dedup))", "event_log_stand_in")
    df = spark.sql(body)
    register(spark, "booking.gold.data_quality", df)
    # The quarantine table is not part of the gold fixture; an empty one with its rule column.
    register(spark, "booking.silver.quarantine_events", spark.createDataFrame([], "rule STRING"))
    return df


def test_data_quality_unpacks_expectations_from_the_event_log(quality):
    [row] = quality.collect()
    assert (row.update_id, row.dataset, row.expectation) == ("u1", "events_dedup", "known_currency")
    assert (row.passed_records, row.failed_records) == (9, 1)


@pytest.mark.usefixtures("gold", "quality")
def test_dashboard_queries_run_on_gold(spark):
    dashboard = json.loads((SQL / "dashboards" / "booking.lvdash.json").read_text())
    columns = {
        d["name"]: set(spark.sql(local("".join(d["queryLines"]))).columns)
        for d in dashboard["datasets"]
    }
    for page in dashboard["pages"]:
        for item in page["layout"]:
            [query] = item["widget"]["queries"]
            fields = {f["expression"].strip("`") for f in query["query"]["fields"]}
            assert fields <= columns[query["query"]["datasetName"]], item["widget"]["name"]


@pytest.mark.usefixtures("gold", "quality")
def test_demo_gold_queries_run_on_gold(spark):
    for name, sql in GOLD_QUERIES.items():
        assert spark.sql(local(sql)).count() > 0, name
