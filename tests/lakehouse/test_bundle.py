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
from sql_harness import SQL, local
from test_gold import gold  # noqa: F401  (fixture)

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


@pytest.mark.usefixtures("gold")
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
