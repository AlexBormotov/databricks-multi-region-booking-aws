"""Runs the bundle's Databricks SQL on local Spark.

A file is an optional header (`CREATE ... <table> (constraints)`), a line holding only `AS`, and
a query. `booking.<schema>.<table>` becomes the temp view `<schema>__<table>`, so fixtures and
upstream results stand in for the catalog.
"""

import re
from pathlib import Path

SQL = Path(__file__).parents[2] / "databricks"
TABLE = re.compile(r"\bbooking\.(\w+)\.(\w+)\b")
CONSTRAINT = re.compile(r"CONSTRAINT (\w+) EXPECT \((.+?)\)\s+ON VIOLATION", re.S)


def local(sql: str) -> str:
    return TABLE.sub(r"\1__\2", sql)


def register(spark, table: str, df) -> None:
    df.createOrReplaceTempView(local(table))


def run(spark, path: str):
    """Run one file; a defined table is registered for the files downstream of it."""
    text = (SQL / path).read_text()
    header, body = text.split("\nAS\n", 1) if "\nAS\n" in text else ("", text)
    df = spark.sql(local(body))
    if match := TABLE.search(header):
        register(spark, match.group(0), df)
    return df, dict(CONSTRAINT.findall(header))


def broken(df, constraints: dict[str, str]) -> dict[str, int]:
    """Rows violating each expectation, as the pipeline would count them."""
    counts = {
        name: df.where(f"NOT coalesce({expr}, false)").count() for name, expr in constraints.items()
    }
    return {name: n for name, n in counts.items() if n}
