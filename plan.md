# Plan: slices 0 and 1

Status: approved by the owner on 2026-10-14, with decisions D1-D3. Implements `spec.md` sections 2, 3, 8, 9 and 10 (slices 0
and 1). Slices 2-4 get their own plan after this one lands.

## 1. Facts this plan rests on (checked 2026-10-14)

| Fact | Source | Consequence |
|---|---|---|
| DSQL supports `uuid`, `jsonb`, `timestamptz`, `date`, `bigint`, `gen_random_uuid()`, CTEs, `INSERT ... ON CONFLICT`, `SELECT ... FOR UPDATE` | DSQL docs, supported data types and concurrency control | `outbox.payload` is `jsonb`, not `text` |
| `FOR UPDATE` in DSQL takes no lock; selected rows join the commit-time conflict check; the loser gets `OC000` / `40001` | DSQL concurrency control | confirms "first commit wins"; no code path waits on a lock |
| Primary keys only at `CREATE TABLE`; one DDL per transaction; DDL never mixed with DML; `CREATE INDEX` must say `ASYNC` | DSQL primary keys, index syntax | one statement per migration file; slice 1 defines no secondary index (`ASYNC` is not valid PostgreSQL) |
| 3,000 rows and 10 MiB per transaction; connections close after 1 h | DSQL quotas | seeding is batched below 3,000 rows; pool `max_lifetime` 3000 s |
| `aurora-dsql-python-connector` + `psycopg` 3 generate IAM tokens; endpoint `<id>.dsql.<region>.on.aws`, user `admin`, `sslmode=require` | DSQL authentication | the same `psycopg` code runs against local PostgreSQL with a plain DSN |
| `generate_series` support is undocumented | DSQL docs | the invariant query avoids it (see 3.2) |
| LocalStack needs an auth token from release 2026.03.0, community image included | LocalStack release notes | see decision D1 |
| Firehose delivery to an S3 bucket in another region is documented only for HTTP endpoints | Firehose docs | see decision D2 |
| `databricks bundle validate` needs workspace auth | CLI behaviour, community reports | moves to the cloud run, as `spec.md` slice 2 already allows |
| Versions: Terraform 1.16.5, Terragrunt 1.1.6, Databricks CLI 1.20.0, k6 2.3.0, tflint 0.64.0, trivy 0.75.0, gitleaks 8.30.1, AWS provider 6.68.0, psycopg 3.3.6 | GitHub releases, PyPI | pinned in the dev image and `pyproject.toml` |

## 2. Decisions for the owner

**D1. Local AWS emulation without LocalStack.** LocalStack now needs an account and a token,
including in CI. Proposed: `moto` in server mode (Kinesis, S3, SSM, DynamoDB) plus Amazon DynamoDB
Local, both free and tokenless. Step Functions is not emulated: the saga's logic lives in Lambda
handlers tested directly. The state machine definition is validated with `aws stepfunctions
validate-state-machine-definition` during `make plan`, which is a free API call. Alternative: a
LocalStack Hobby token stored as a CI secret. It is non-commercial-only and adds an account to keep
alive.

**D2. One Kinesis stream and one Firehose, both in us-east-1.** The poller in us-east-2 puts its
records cross-region to the us-east-1 stream with an ordinary SDK call. This replaces "Kinesis +
Firehose per region" in `spec.md` section 4. The cost is that an outage in us-east-1 stops publishing
from us-east-2 as well. Nothing is lost: unpublished rows wait in the outbox (`published_at IS NULL`)
and drain on recovery. The gain: half the streaming resources, and no dependence on an undocumented
cross-region Firehose delivery.

**D3. Spec amendments that follow from section 1.** `outbox.payload` is `jsonb`. The invariant query
is the self-join in 3.2. Slice 1 has no secondary indexes. `bundle validate` runs in the cloud run.

## 3. Slice 1 design choices, with their checks

### 3.1 Concurrency core

Chosen, as `spec.md` 2.1 decided: claim rows `room_night` with a primary key, plus lazy takeover of
stale claims.

Considered and rejected: a guard row per room (`rooms.version` incremented by every booking). It
serialises all bookings of a room, including bookings for different nights. Under DSQL OCC that
turns unrelated stays into conflicts and retries.

### 3.2 Invariants and the check that goes red

| Invariant | Red check |
|---|---|
| at most one live booking per room-night | `test_concurrent_same_room_night`, then `sql/invariant.sql`: a self-join of live bookings with overlapping `[check_in, check_out)` on the same room returns zero rows. It reads `bookings` only, so it does not trust the `room_night` table it is checking |
| a replayed `Idempotency-Key` creates nothing | `test_idempotent_replay`, `test_idempotency_key_reused_with_other_body` |
| a payment after `expires_at` never confirms | `test_payment_after_expiry` |
| an expired hold frees its room-nights | `test_stale_hold_takeover` |
| every committed state change is published, only by its home region | `test_outbox_poller_publishes_own_region_only` |
| PII stays in its jurisdiction's vault and never enters an event | `test_pii_residency` |
| an illegal status transition is rejected | `test_status_transitions` |

**Negative control:** removing the primary key from `room_night` in a local-only migration makes
`test_concurrent_same_room_night` fail and leaves every other test green. It runs once, and its output
goes into the PR description.

### 3.3 Reversal

Everything in this plan is new files on a branch. Reversal is a `git revert` of the squash commit.
Bootstrap cloud resources (5.1) are removed with `terraform destroy` in `infra/bootstrap`. All of
them are idle-free.

## 4. Files

```
.devcontainer/Dockerfile            pinned toolchain image (Python 3.13, uv, terraform, terragrunt,
                                    databricks CLI, k6, aws CLI, tflint, trivy, gitleaks)
.devcontainer/devcontainer.json
docker-compose.yml                  dev, postgres:16, moto, dynamodb-local
Makefile                            lint test test-integration security plan up demo down cost-report;
                                    re-executes itself inside the dev container when run on the host
pyproject.toml, uv.lock             psycopg[binary,pool], aurora-dsql-python-connector, boto3;
                                    dev: pytest, ruff, moto
.github/workflows/ci.yml            image (on Dockerfile change, push GHCR), lint, test,
                                    test-integration (services: postgres, moto, dynamodb-local),
                                    security, plan (OIDC read-only, PR comment)
.github/workflows/cloud-session.yml manual, Environment demo-prod; up/demo/down are stubs until
                                    the cloud slice
.github/workflows/reaper.yml        cron 30 min; no-op until the cloud slice
infra/bootstrap/                    state bucket (S3 native lockfile), GitHub OIDC provider,
                                    plan role (read-only), deploy role, $12 budget; local state
infra/modules/{dsql,api,saga,stream,guests_vault}/
infra/live/root.hcl
infra/live/demo-prod/{us-east-1,us-east-2,eu-central-1}/<component>/terragrunt.hcl
src/booking/db.py                   pool: DSQL connector in cloud, plain DSN locally
src/booking/migrations/*.sql        one DDL statement per file
src/booking/domain.py               states, transitions, value types
src/booking/service.py              booking transaction, retry, idempotency, cancel, availability
src/booking/saga.py                 payment simulation, confirm, expire
src/booking/outbox.py               poller
src/booking/telemetry.py            rejected-attempt records
src/booking/guests.py               jurisdiction routing and vault writes
src/booking/handlers/*.py           thin Lambda adapters per route and per saga step
infra/modules/saga/definition.asl.json
sql/invariant.sql
loadtest/contention.js              k6 scenario; runs in the cloud run
tests/unit/, tests/integration/
docs/bootstrap.md                   one-time account setup, step by step
```

## 5. Steps

Each step ends with its check. Steps 1-4 are slice 0, steps 5-11 are slice 1.

1. **Dev image and compose.** Check: `docker compose run --rm dev make --version` and every pinned
   tool prints its version.
2. **Makefile and Python skeleton.** Check: `make lint test` is green on an empty package, from the
   host and inside the container.
3. **CI.** Check: a PR on GitHub runs `image`, `lint`, `test` and `security` green. `plan` is
   skipped until step 4.
4. **Bootstrap and the Terragrunt tree.** You run `infra/bootstrap` once, following
   `docs/bootstrap.md`: IAM Identity Center user, `aws sso login`, then `terraform apply`. Check:
   `make plan` succeeds locally and in the PR comment, and the plan creates nothing outside the
   `demo-prod` tree.
5. **Migrations and pool.** Check: the migrations apply to local PostgreSQL from scratch, and a
   rerun is a no-op.
6. **Domain and the booking transaction.** Check: unit tests for transitions, plus the concurrency,
   idempotency and takeover tests from 3.2, green. Then the negative control.
7. **Saga.** Check: `test_payment_after_expiry` and the confirm and expire paths green. The ASL
   definition passes validation in `make plan`.
8. **Outbox poller and telemetry.** Check: `test_outbox_poller_publishes_own_region_only` against
   moto Kinesis.
9. **Guests and PII.** Check: `test_pii_residency` against DynamoDB Local.
10. **Lambda handlers and IaC modules.** Check: handler tests with API Gateway event fixtures;
    `terraform validate` and `make plan` green for every component.
11. **k6 scenario.** Check: `k6 inspect loadtest/contention.js` passes. It runs for real only in the
    cloud run.

## 6. Local machine

Per your answer in grilling, the host needs only Docker Desktop (installed), GNU Make (I install it
with `winget install ezwinports.make`) and the AWS CLI (installed) for `aws sso login`. Everything
else runs in the dev image, and the host's `~/.aws` is mounted into it.

## 7. Stop conditions

Work stops and this plan returns for approval if a fact in section 1 proves false, if a file outside
section 4 needs to change, or if the negative control fails to go red.
