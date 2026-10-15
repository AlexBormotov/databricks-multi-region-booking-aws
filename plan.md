# Plan: slices 2 to 4

Status: approved by the owner on 2026-10-15, with decisions D4-D7 as proposed and D8 option (b). Implements `spec.md` sections 4 to 7 and 10 (slices 2, 3
and 4). The plan for slices 0 and 1 is in git history at `63ecdc0`. The cloud run gets its own
plan after this one lands.

## 1. Facts this plan rests on (checked 2026-10-15)

| Fact | Source | Consequence |
|---|---|---|
| Pipeline Python API: `from pyspark import pipelines as dp`; `@dp.table`, `@dp.materialized_view`, `dp.create_streaming_table`, `dp.create_auto_cdc_flow(..., sequence_by, stored_as_scd_type=1 or 2)`; expectations `expect`, `expect_or_drop`, `expect_or_fail` and their `expect_all_*` forms | Databricks LDP Python reference | bronze and silver as `spec.md` 5 describes them |
| Importing a module with pipeline decorators outside a pipeline run raises `GRAPH_ELEMENT_DEFINED_OUTSIDE_OF_DECLARATIVE_PIPELINE` | Spark source, `pyspark/pipelines/graph_element_registry.py` | transformations live in an undecorated package; pipeline files are thin wrappers |
| AUTO CDC with SCD2 and expectations exist only on Databricks; open-source Spark 4.2 has AUTO CDC with SCD1 only, and 4.1 has none | Spark 4.1.0 and 4.2.0 source, Databricks docs | AUTO CDC cannot run locally; see decision D7 |
| The documented quarantine pattern flags rows with `expect_all` and an `is_quarantined` column; it does not copy dropped rows | Databricks expectation patterns | see 3.2 |
| Serverless pipelines run DBR 18: Spark 4.1.0, Python 3.12.3, Java 21 | Databricks release notes, DBR 18.2 | see decisions D4 and D5 |
| PySpark 4.1 supports Python 3.13 and needs Java 17, 21 or 25; Debian trixie has `openjdk-21-jre-headless` (about 200 MB installed); the PySpark package is a 450 MB sdist | PyPI, Spark docs, packages.debian.org | see decision D4 |
| Materialized views carry expectations, including `ON VIOLATION FAIL UPDATE` | Databricks expectations | the gold invariant is an expectation on a materialized view |
| Bundles: pipeline `serverless`, `catalog`, `schema`, `root_path`, `libraries.glob`, `environment.dependencies`; `resources.dashboards` with `file_path` to `.lvdash.json`; job `trigger.file_arrival` (`url`, `min_time_between_triggers_seconds`), `sql_task`, `dashboard_task` | Databricks bundle resource reference | the bundle layout in section 4 |
| A file-arrival trigger needs a Unity Catalog external location or volume | Databricks file-arrival triggers | the landing bucket becomes an external location in the cloud slice |
| Whether a trial workspace may create a storage credential and an external location on the owner's S3 is not documented | Databricks free-trial page | a cloud-slice risk, see section 7 |
| Bedrock Knowledge Bases support S3 Vectors in us-east-1 with Titan Text Embeddings V2 (1024, 512 or 256 dims); at most 1 KB of custom metadata and 35 keys per vector | Bedrock and S3 Vectors docs | metadata is `hotel_id`, `city`, `country` only |
| Terraform 6.x has `aws_s3vectors_vector_bucket`, `aws_s3vectors_index` and `storage_configuration { type = "S3_VECTORS" }` on `aws_bedrockagent_knowledge_base` | AWS provider docs | the search module is plain Terraform |
| moto has S3 Vectors without `query_vectors` | moto docs | retrieval is stubbed at the client boundary, as `spec.md` slice 3 already says |
| DynamoDB MRSC: exactly three regions (or two plus a witness); conditional writes see the latest version; no transactions, no TTL, no LSIs; concurrent writes to one item raise `ReplicatedWriteConflictException` | DynamoDB MRSC docs | confirms the trade-offs `spec.md` 7 names; see decision D8 |
| DynamoDB Local supports condition expressions and transactions but has no regions, so no MRSC | DynamoDB Local usage notes | the local spike proves claim logic, not cross-region behaviour |

## 2. Decisions for the owner

**D4. Local Spark in the dev image.** The silver functions and the gold SQL need a Spark engine to
be tested. Proposed: add `openjdk-21-jre-headless` to the dev image (about 200 MB) and `pyspark==4.1.*`
to the dev dependencies, matching DBR 18 (Spark 4.1, Java 21). The venv grows by about 450 MB. It
is cached in the `venv` volume locally, and CI downloads it in each job that syncs. Alternative:
DuckDB for the gold SQL and plain Python for silver. It is lighter, but its SQL dialect differs
from Databricks SQL, so a green test would prove less.

**D5. Lakehouse code targets Python 3.12.** Serverless pipelines run 3.12.3, while the project is
3.13. Proposed: `src/lakehouse/` avoids 3.13-only features, and ruff checks it with
`per-file-target-version` set to `py312`. The pipeline gets the code as source files synced by the
bundle under `root_path`, not as a wheel. If the import fails in the cloud, the fallback is a wheel
in a UC volume through `environment.dependencies`.

**D6. Quarantine through one rule set.** Each silver rule is a name plus a SQL expression, kept in
one dict. The silver table applies them with `expect_all_or_drop`, which gives the pipeline UI its
metrics. A sibling streaming table `quarantine_events` keeps the rows that break any rule, with the
name of the first rule broken. One dict feeds both, so they cannot drift apart. This follows the
documented flag pattern rather than a copy that the platform does not offer.

**D7. AUTO CDC is checked by an oracle query, not a local test.** `spec.md` slice 2 asks pytest to
show that out-of-order versions resolve to the highest `aggregate_version`. That behaviour belongs
to AUTO CDC, which runs only on Databricks. Proposed: `checks/cdc_latest.sql` computes each
booking's state from `events_dedup` by the highest version. Locally it is tested on a fixture with
shuffled and duplicate events, and it stands in for AUTO CDC in the local end-to-end test. In the
cloud, the `booking-refresh` job runs it against `silver.bookings` and fails on any difference. This
amends the wording of `spec.md` slice 2.

**D8. Cross-region evidence for the DynamoDB spike.** DynamoDB Local has no regions, so the local
test proves only the claim logic. Option (a): local only, and the ADR says the cross-region behaviour
is documented, not measured. Option (b): the cloud run adds one on-demand MRSC table (us-east-1,
us-east-2, witness us-west-2). A script on the session runner then fires concurrent conditional
writes at one item from both regions, which costs cents. No Lambda and no second k6 run are
involved. Chosen: (b). It replaces "the same k6 scenario against it" in `spec.md` 7 either way.

## 3. Design choices, with their checks

### 3.1 Code layout

`src/lakehouse/` is plain PySpark: `DataFrame -> DataFrame` functions plus the rule dict, with no
pipeline import. `databricks/pipeline/*.py` are thin wrappers that only decorate and call those
functions. `databricks/pipeline/gold/*.sql` are materialized views. `databricks/checks/*.sql` are
the job's SQL checks. Gold SQL names tables in full (`booking.silver.bookings`). The local test
harness strips the `CREATE` header and the catalog prefix, then registers fixtures as temp views
under the same names.

### 3.2 Invariants and the check that goes red

| Invariant | Red check |
|---|---|
| one silver row per `event_id` | `test_dedup_collapses_duplicates` |
| a row breaking a rule is dropped from silver and lands in quarantine with the rule name; no row is in both or in neither | `test_quarantine_partition`, one case per rule (unknown currency, night outside the stay, state event without `aggregate_version`) |
| a booking's state is the one with the highest `aggregate_version`, whatever the arrival order | `test_cdc_oracle_out_of_order` on `checks/cdc_latest.sql` |
| nights are hotel-local dates; lead time is counted in the hotel's time zone | `test_lead_time_across_midnight`: a booking at 23:30 UTC in a UTC-5 hotel and in a UTC+9 hotel |
| revenue is in USD at the night's FX rate | `test_fx_per_night`: a stay that spans an FX rate change |
| occupancy, ADR and RevPAR match a hand computation | `test_gold_kpis` on a fixed fixture, with the expected numbers written in the test |
| no room-night has two confirmed bookings in gold | `test_gold_invariant` on `checks/gold_invariant.sql` with a planted double booking |
| the generator is deterministic and emits the event contract | `test_generator_seed`, `test_generator_contract` |
| `/search` returns only hotels with a free room | `test_search_filters_unavailable`, with retrieval stubbed and availability from PostgreSQL |
| the corpus is deterministic for a seed and its metadata fits 1 KB | `test_corpus_seed`, `test_corpus_metadata_size` |
| of concurrent claims on one room-night in DynamoDB, exactly one wins; a multi-night claim that fails part-way releases the nights it took | `test_spike_single_winner`, `test_spike_compensation` against DynamoDB Local |

**Negative controls**, run once each, with their output in the PR description:
- Remove the dedup step: `test_dedup_collapses_duplicates` and `test_demand_marts` (a rejected
  attempt delivered twice) fail. The KPIs do not depend on dedup: the CDC state collapses repeats.
- Plant a double booking in the fixture: `test_gold_invariant` reports it.
- Drop the condition from the spike's `PutItem`: `test_spike_single_winner` fails.

### 3.3 Local end to end

`test_lakehouse_end_to_end` runs the generator at `SCALE=small` through the silver functions, the
CDC oracle and the gold SQL in local Spark. It asserts that the gold invariant holds and that the
KPIs are within their ranges (occupancy between 0 and 1, ADR above 0).

### 3.4 Reversal

Everything is new files on branches, plus two lines in the dev image. Reversal is a `git revert`
of each squash commit. Nothing touches the cloud.

## 4. Files

```
.devcontainer/Dockerfile                + openjdk-21-jre-headless
pyproject.toml, uv.lock                 dev: pyspark==4.1.*; ruff per-file-target-version py312
                                        for src/lakehouse
Makefile                                `test` also runs tests/lakehouse
src/booking/generator.py                deterministic history and reference data (hotels, rooms,
                                        FX), same event contract
src/lakehouse/rules.py                  silver rules: name -> SQL expression
src/lakehouse/silver.py                 parse, dedup, state events, booking_nights, fx, dims,
                                        quarantine split
databricks/databricks.yml               bundle: pipeline, job booking-refresh, dashboard
databricks/pipeline/bronze.py           Auto Loader wrapper
databricks/pipeline/silver.py           decorated wrappers, AUTO CDC flows
databricks/pipeline/gold/*.sql          materialized views from spec.md 5
databricks/checks/*.sql                 gold_invariant, cdc_latest, row counts
databricks/dashboards/booking.lvdash.json   three pages from spec.md 5
src/booking/corpus.py                   templated descriptions and reviews, metadata sidecars
src/booking/search.py                   KB retrieve, then the availability filter
src/booking/handlers/api.py             + GET /search
infra/modules/search/                   corpus bucket, vector bucket and index, KB, data source,
                                        IAM role
infra/live/demo-prod/us-east-1/search/terragrunt.hcl
infra/modules/api/                      + /search route; IAM for bedrock:Retrieve on the KB
spike/dynamodb/claims.py                per-night conditional PutItem, compensating delete
tests/lakehouse/                        conftest (local SparkSession), silver, gold, checks,
                                        generator, end to end
tests/unit/test_corpus.py
tests/integration/test_search.py, test_dynamodb_spike.py
docs/adr/0001-dsql-over-dynamodb.md     ADR 1 from spec.md 11, with the "version 2" design
```

## 5. Steps

Each step ends with its check. Steps 1-6 are slice 2, steps 7-8 are slice 3, step 9 is slice 4.
Each slice is one PR.

1. **Local Spark.** Check: `make test` starts a local SparkSession in the container and runs one
   trivial query; the image builds in CI.
2. **Generator.** Check: `test_generator_seed` and `test_generator_contract`.
3. **Silver functions and rules.** Check: the silver rows of 3.2 green, then the dedup negative
   control.
4. **Checks and gold SQL.** Check: `test_cdc_oracle_out_of_order`, `test_gold_kpis` and
   `test_gold_invariant` green, then the planted-double-booking control.
5. **Pipeline wrappers, bundle, dashboard.** Check: `ruff` passes on the wrappers, and the bundle
   JSON matches `databricks bundle schema` locally. `bundle validate` runs in the cloud run.
6. **Local end to end.** Check: `test_lakehouse_end_to_end`.
7. **Corpus and search.** Check: `test_corpus_seed`, `test_corpus_metadata_size`,
   `test_search_filters_unavailable`, and a handler test for `GET /search`.
8. **Search infra.** Check: `make plan` green for the new component, with its resource count in the
   PR comment.
9. **DynamoDB spike and ADR 1.** Check: `test_spike_single_winner` and `test_spike_compensation`
   against DynamoDB Local, then the missing-condition control. The ADR is written with the
   `domain-modeling` rules.

## 6. Spec amendments on approval

- Slice 2: the out-of-order condition is checked by the CDC oracle (D7).
- Section 7 and the cloud run: the cross-region evidence is the runner script (D8).
- Section 5: `quarantine_events` is filled from the shared rule set (D6).

## 7. Risks carried to the cloud plan

- A trial workspace may refuse an external location on the owner's S3. Auto Loader and the
  file-arrival trigger both depend on it. The cloud plan starts by checking this on the workspace
  the owner has.
- Source files under `root_path` may not be importable by serverless pipelines (D5 fallback).
- Titan V2 model access may need enabling in the Bedrock console once.

## 8. Stop conditions

Work stops and this plan returns for approval if a fact in section 1 proves false, if a file
outside section 4 needs to change, or if a negative control fails to go red.
