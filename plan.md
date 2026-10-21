# Plan: the cloud slice

Status: approved by the owner on 2026-10-16, with decisions D9-D14 as proposed. Implements `spec.md` sections 8 to 10: the session lifecycle,
the demo, the cloud run and the cost report. The plan for slices 2 to 4 is in git history at
`2d02db8`.

## 1. Facts this plan rests on (checked 2026-10-16)

| Fact | Source | Consequence |
|---|---|---|
| A Databricks trial lasts 14 days with up to $400 of usage and no card. Express signup gives a serverless workspace with default storage. Without an upgrade, access pauses at the end, and assets are deleted 60 days later | Databricks free-trial and express-setup docs; databricks.com/try-databricks | the trial starts only when every line of code is merged (D9) |
| A workspace is created in the UI. `databricks_mws_workspaces` needs account-level API access, which is not confirmed for trial accounts. Bundles authenticate to a workspace with OAuth M2M | Terraform provider docs v1.137.0; Databricks OAuth M2M docs | the owner creates the workspace and a service principal by hand (step 9) |
| A UC storage credential trusts the Databricks UC master role with an external ID, and the role must also trust itself. Docs do not say whether a trial may create one on the customer's S3 | Databricks S3 external location docs (2026-10-06) | this is the first thing the trial checks, with a fallback (D10) |
| File-arrival triggers need UC and an external location or volume. They poll about once a minute, the minimum spacing is 60 s, and each location allows up to 10,000 files without file events | Databricks file-arrival trigger docs (2026-10-07) | the demo starts the job explicitly and keeps the trigger (D13) |
| List prices: serverless pipelines and jobs cost $0.35/DBU, serverless SQL $0.70/DBU, and a 2X-Small warehouse uses 4 DBU/h. A run is estimated at $2-3, inside the trial credit | third-party pricing guides; the official tables did not render | cost estimate in section 6 |
| Titan Text Embeddings V2 is enabled by default and costs $0.02 per 1M tokens. S3 Vectors has no hourly charge | Bedrock model access docs; S3 pricing | the plan risk on model access is closed |
| DSQL bills $8 per 1M DPU and has no idle charge. Multi-region writes double the write DPU. Creation and deletion time is undocumented | DSQL pricing and user guide | `make up` waits on DSQL with the provider's 30-minute timeout |
| A DynamoDB table used to add a replica cannot be deleted for 24 h. Whether this applies to MRSC is unconfirmed. MRSC tables support Streams | DynamoDB global tables docs | the MRSC table is persistent (D11); ADR 1's "verify" item is answered |
| Kinesis on-demand costs $0.04 per stream-hour. Firehose dynamic partitioning costs $0.02/GB plus $0.005 per 1,000 objects | Kinesis and Firehose pricing | cents per session |
| Default spot quota is 5 vCPU per region | EC2 spot limits docs | one c7g.large per region for k6; the quota is checked before the run |

## 2. Decisions for the owner

**D9. When the trial starts.** The 14 days start at signup. Proposed: write and merge everything,
including the Databricks Terraform and the demo steps, then sign up. Run 1 is AWS only and happens
before the trial. Run 2 is the full run and happens within days of signup.

**D10. Where the lakehouse reads from.** Proposed: a UC storage credential and an external location
on the landing bucket, as `spec.md` 4 says. Fallback, if the trial refuses the credential: after the
Firehose flush, the runner copies the landing prefix into a UC managed volume, and Auto Loader and
the file-arrival trigger read the volume instead. The fallback is written only if the probe in step
10 fails.

**D11. What persists between sessions.** Each of these is free while idle:
- the landing bucket, emptied by `make down`;
- the UC storage credential, external location and catalog;
- the empty on-demand MRSC table.

Proposed: create them once, by `make up` if absent, and keep them out of `make down`. This avoids
re-registering UC objects every session and the possible 24 h delete block on MRSC. `spec.md` 8 gains
them in its persistent list. Alternative: create and destroy everything per session, and risk a
failed `make down` on MRSC.

**D12. The DSQL role the Lambdas use.** Today they connect as `admin`. Proposed: a migration creates
the role `booking_app`, granted only DML on the booking tables. `make up` runs `AWS IAM GRANT` for
the Lambda roles, and their IAM policy becomes `dsql:DbConnect`. Alternative: keep `admin` and record
it as a known limit.

**D13. How the demo runs the lakehouse.** Proposed: `make demo` waits for the Firehose flush, then
starts `booking-refresh` with `databricks bundle run` and waits for it, so the run is timed and
gated. The file-arrival trigger stays on to show the event-driven path. A triggered run that overlaps
is queued behind it, because a job allows one concurrent run by default.

**D14. The cost report.** AWS Cost Explorer lags by up to 24 h. Proposed:
- `make cost-report DATE=<session date>` runs the next day and filters on the `project` tag;
- the owner activates `project` as a cost allocation tag once now, since activation also takes up to
  24 h;
- the Databricks share comes from `system.billing.usage` times list price;
- if system tables are off on the trial, it comes from the account console's usage page.

## 3. Design

### 3.1 Session lifecycle

`make up` does the following, in order:
1. Writes the expiry (now + 2 h) to SSM `/booking/session/expires_at`.
2. Applies the persistent components if absent (D11).
3. Runs `terragrunt run --all apply` on the session components.
4. Runs the migrations and seeds hotels and rooms from `generator.reference(seed, scale)` into DSQL
   as `admin`.
5. Grants `booking_app` to the Lambda roles (D12).
6. Uploads the corpus and starts the KB ingestion job, then waits for it.
7. Deploys the bundle (run 2 only).

`make down` does the following:
1. Empties the landing bucket.
2. Runs `terragrunt run --all destroy` on the session components.
3. Deletes the SSM parameter.

It runs with `if: always()`. The reaper workflow runs `make down` when the expiry has passed;
`REAPER_ENABLED` is set once run 1 is green.

### 3.2 The demo

`make demo SCALE=small` does the following, in order:
1. Backfills `generator.write` output to the landing bucket.
2. Sends live traffic of a few hundred bookings through both API regions.
3. Runs `/search` and checks that every hotel returned has a free room.
4. Runs the k6 contention scenario.
5. Runs the invariant query.
6. Runs the MRSC script.
7. Run 2 only: runs `booking-refresh` and exports the dashboard.

Every step writes to `artifacts/`.

**k6.** One spot c7g.large in each of us-east-1, us-east-2 and us-west-2 starts k6 at a shared start
time. Together they send 1000 attempts at one room-night, split across both API regions. Each writes
its summary to S3, the runner collects the summaries, and the k6 component is destroyed.

**MRSC script.** `spike/dynamodb/mrsc_race.py` uses `claims.claim` from threads with clients in
us-east-1 and us-east-2, over a fresh room-night per run, and records the winner count.

### 3.3 Checks that go red

| Claim | Check |
|---|---|
| seed matches the lakehouse reference | `test_seed_matches_reference` against PostgreSQL |
| the `booking_app` role cannot run DDL | `test_app_role_has_dml_only` against PostgreSQL |
| the reaper acts only after expiry | `test_reaper_decision` with moto SSM |
| the k6 scenario yields one `201` before we pay for it | `make k6-local`: k6 in the dev image against the API handler on a local HTTP adapter over PostgreSQL. Negative control: drop the `room_night` primary key, and it reports more than one `201` |
| the MRSC script counts winners right | `test_mrsc_race` against DynamoDB Local with two clients |
| the demo assertions fail loudly | each demo step exits non-zero on a broken claim; run 1 records one deliberate failure (an unknown `hotel_id` in `/search`) |

### 3.4 Reversal

`make down` destroys every session resource. The persistent pieces of D11 are removed by
`make destroy-persistent`, which is documented and never run by CI.

## 4. Files

```
Makefile                                 up, demo, down, cost-report, k6-local, destroy-persistent
.devcontainer/Dockerfile                 + k6 binary (pinned)
src/booking/seed.py                      reference hotels and rooms into the booking store
src/booking/migrations/007_app_role.sql  booking_app role and grants (DSQL and PostgreSQL)
src/booking/db.py                        connect as booking_app when DSQL_ROLE is set
infra/modules/api/                       dsql:DbConnect for booking_app instead of admin
infra/modules/landing/                   landing bucket moved out of stream (persistent)
infra/modules/stream/                    reads the landing bucket instead of owning it
infra/modules/mrsc/                      MRSC table, us-east-1 + us-east-2, witness us-west-2
infra/modules/k6/                        one spot instance, user data runs k6, summary to S3
infra/modules/databricks_uc/             storage credential role, UC credential, external location,
                                         catalog and schemas (databricks provider)
infra/live/demo-prod/...                 terragrunt files for the four modules above
ops/session.py                           expiry, reaper decision, wait helpers, artifact writer
ops/demo.py                              the demo steps of 3.2
ops/cost_report.py                       Cost Explorer by tag plus Databricks usage
spike/dynamodb/mrsc_race.py              cross-region race on one item
load/contention.js                       k6 scenario
load/local_api.py                        HTTP adapter over api.handler for k6-local
.github/workflows/cloud-session.yml      Databricks secrets; artifacts
.github/workflows/reaper.yml             real reap step
tests/integration/test_seed.py, test_app_role.py, test_mrsc_race.py
tests/unit/test_session.py
docs/cloud-run.md                        owner's one-time steps: tag activation, spot quota check,
                                         trial signup, service principal, GitHub secrets
spec.md                                  amendments in section 7
```

## 5. Steps

Each step ends with its check.

**Slice C1, session lifecycle.** One PR.
1. Seed and app role. Check: `test_seed_matches_reference` and `test_app_role_has_dml_only`.
2. Landing and MRSC modules, and the api policy change. Check: `make plan` green, with the resource
   counts in the PR.
3. `make up` and `make down`, plus the expiry and the reaper. Check: `test_reaper_decision` and
   `make plan`. Nothing is applied yet.

**Slice C2, the demo.** One PR.
4. k6 scenario and `make k6-local`. Check: one `201` locally, then the negative control.
5. The MRSC script. Check: `test_mrsc_race`.
6. The demo steps and the k6 module. Check: the steps run end to end against the local stack where
   an emulator exists; `make plan` is green for k6.

**Run 1, AWS only.** The owner approves the `cloud-session` workflow. Pass conditions:
- k6 gives exactly one `201` out of 1000;
- the invariant query returns zero rows;
- `/search` returns only hotels with availability;
- the MRSC script records one winner;
- `make down` completes.

7. The owner activates the cost tag (D14) before run 1. `make cost-report` runs the next day.

**Slice C3, Databricks.** One PR.
8. The `databricks_uc` module, bundle deploy in `make up`, and the lakehouse steps in `make demo`.
   Check: `terraform validate` and offline `bundle validate`.
9. The owner signs up for the trial, creates a service principal and stores its OAuth secret in the
   `demo-prod` environment (`docs/cloud-run.md`).
10. Probe: apply `databricks_uc` and run `bundle validate` against the workspace. If the credential
    is refused, stop and write the D10 fallback.

**Run 2, full.** Pass conditions: those of run 1, plus the gold expectation passed, the CDC oracle
matched, and the dashboard shows both regions. `make cost-report` the next day must show less than
$7.

## 6. Cost estimate per full run

| Item | Estimate |
|---|---|
| Databricks: pipeline update, checks, dashboard, warehouse about 20 min | $2-3 (trial credit) |
| DSQL, Lambda, API Gateway, Step Functions, Kinesis, Firehose | under $0.50 |
| Bedrock embeddings and S3 Vectors | under $0.05 |
| k6: three c7g.large spot for about 15 min | under $0.05 |
| Cost Explorer API calls | $0.01 per call |

AWS pays under $1 per run, and the Databricks share comes out of the trial credit.

## 7. Spec amendments on approval

- Section 8: the persistent list gains the landing bucket, the UC objects and the MRSC table (D11).
  The cost report runs the day after the session (D14).
- Section 2: Lambdas connect as `booking_app` (D12).
- Section 4: the volume fallback for landing (D10), used only if the probe fails.

## 8. Stop conditions

Work stops and this plan returns for approval in any of these cases:
- a fact in section 1 proves false;
- a file outside section 4 needs to change;
- a negative control fails to go red;
- the trial probe refuses the storage credential;
- either run costs more than $7.

## 9. Amendment A: the booking store on DynamoDB MRSC

Status: approved by the owner on 2026-10-21. Replaces Aurora DSQL with ADR 1's "Version 2" (ADR 2). Section 1's
DSQL row, D12 and the DSQL parts of 3.1 and 3.3 no longer apply.

### 9.1 Facts (checked 2026-10-21 on the account)

| Fact | Source | Consequence |
|---|---|---|
| `dsql create-cluster` fails in us-east-1 and us-east-2 with `ValidationException ... Contact AWS Support` | CLI probe; run 1 | DSQL is out until support answers |
| An MRSC table with a GSI and a stream takes about 70 s to create | probe table `booking-probe-mrsc` | the tables are session resources |
| The stream exists only in us-east-1, where the table was created, and it carries the writes made in both regions | the probe wrote one item in each region and read both from the us-east-1 stream | one event Lambda in us-east-1 |
| Deleting an MRSC table fails while the replica exists. After the replica and the witness are removed (about 60 s), the delete succeeds at once; there is no 24 h block | probe | `make down` destroys the tables; D11 keeps only the spike table |

### 9.2 Decisions

**D15. Tables.** Four on-demand MRSC tables, created by `make up` and destroyed by `make down`:

| Table | Key | Attributes |
|---|---|---|
| `booking-rooms` | `hotel_id`, `room_id` | `room_type`, `base_rate_minor`, `currency` (the hotel's, copied) |
| `booking-room-nights` | `room_night` = `<room_id>#<night>` | `booking_id`, `expires_ms` (absent once confirmed) |
| `booking-bookings` | `booking_id` | today's booking fields, plus `refunded` and `changed_in`; stream `NEW_AND_OLD_IMAGES` |
| `booking-idempotency` | `idem_key` | `request_hash`, `state` (`in_progress` or `done`), `started_ms`, `status_code`, `response` |

Times are epoch milliseconds, because conditions compare them. Hotels have no table: the booking
path needs only a room's rate and currency. The corpus and the lakehouse already carry hotels.

**D16. Booking protocol** (replaces spec 2.1):

1. Take the key: put the idempotency item with
   `attribute_not_exists(idem_key) OR (state = in_progress AND started_ms < :now - LEASE)`.
   - If the key is `done` with the same hash, return the stored response.
   - If the key is `done` with a different hash, return `422`.
   - If the key is `in_progress`, return `409` with `Retry-After`.
2. Read the room. If it is unknown, return `404` and delete the key.
3. Claim the nights in date order. The condition is
   `attribute_not_exists(room_night) OR expires_ms < :now - SKEW`.
   - On a failed condition, release the nights already taken, conditioned on `booking_id`.
   - Return `409` and delete the key, so a retry is evaluated again.
4. Put the booking: `pending`, `version = 1`, `expires_ms = now + HOLD_TTL`. Store `201` in the key
   and start the saga.

A takeover of a stale hold also moves that hold's booking to `expired`, if it is still `pending`.
This is best effort; the saga's expire step does the same.

`ReplicatedWriteConflictException` is MRSC's write-write conflict. It is retried with backoff and
full jitter, at most 5 attempts, then the request returns `503`. `SKEW` is 5 s and `LEASE` is 30 s.

**D17. Saga.**

*Confirm.*
1. Remove `expires_ms` from each claim, conditioned on `booking_id`. A claim lost to a takeover means
   the hold had expired.
2. Update the booking to `confirmed`, conditioned on `status = pending AND expires_ms > :now`.

Claims are made permanent before the booking is confirmed. A crash between the two steps therefore
leaves a room blocked, never sold twice. If step 2 fails, the booking is expired, its claims are
released, and `refunded` is set.

*Expire and cancel.* Update the booking first, then release its claims.

**D18. Events.** A Lambda in us-east-1 reads the `bookings` stream and puts envelopes to Kinesis.
The envelope is the one in spec 3.
- **Event type.** An insert is `BookingHeld`. A status change is `BookingConfirmed`,
  `BookingExpired` or `BookingCancelled`. `refunded` becoming true is `PaymentRefunded`.
- **Event id.** `uuid5(booking_id, version, type)`. A redelivered stream record then has the same
  id, and the lakehouse drops it with `MERGE` on `event_id`.
- **Fields.** `home_region` is the item's `changed_in`, and `occurred_at` is its `updated_ms`.

The outbox table, the poller and its EventBridge rule are removed. The lakehouse is unchanged.

**D19. What leaves the stack.**
- PostgreSQL: the compose service and the CI service.
- `psycopg`, `psycopg-pool` and the DSQL connector.
- `migrations/`, `db.py`, `outbox.py`, `sql/invariant.sql`.
- The `booking_app` role (D12).

The invariant becomes `booking.store.violations`. It does a strongly consistent scan of `bookings`
only and pairs live bookings of the same room whose stays overlap. The DynamoDB Local container
replaces PostgreSQL for every local check.

### 9.3 Checks that go red

| Claim | Check |
|---|---|
| one winner per room-night | `test_concurrent_same_room_night`: 1000 concurrent bookings against DynamoDB Local give one `201`. Negative control: drop the claim condition, and more than one `201` appears |
| a losing multi-night booking keeps nothing | `test_multi_night_loser_releases` |
| an expired hold is taken over, a live one is not | `test_stale_hold_takeover`, with the skew boundary |
| a payment after expiry is refunded, not confirmed | `test_payment_after_expiry`: the booking is `expired` and `PaymentRefunded` is emitted |
| replay and key reuse | `test_idempotent_replay`, `test_key_reused_with_other_request` |
| events match the contract and repeat with the same id | `test_events_from_stream`: the DynamoDB Local stream goes to the handler and then to moto Kinesis |
| the invariant goes red | `test_invariant_flags_overlap` on two hand-written overlapping bookings |
| k6 before paying | `make k6-local` against DynamoDB Local: one `201` |

The search, saga, handler, seed and demo-step tests move from PostgreSQL to DynamoDB Local.

### 9.4 Files

```
src/booking/store.py                     tables, claims, retry, violations (replaces db.py)
src/booking/service.py, saga.py, search.py, seed.py, domain.py
src/booking/events.py                    stream record -> envelope (replaces outbox.py)
src/booking/handlers/api.py, saga.py, runtime.py, events.py (replaces poller.py)
src/booking/migrations/, src/booking/db.py, src/booking/outbox.py, sql/invariant.sql   removed
infra/modules/store/                     the four MRSC tables (replaces infra/modules/dsql)
infra/modules/api/, infra/modules/saga/  DynamoDB permissions; the events function in us-east-1
infra/live/demo-prod/...                 store unit instead of dsql; api and saga dependencies
ops/session.py, ops/demo.py              seed and invariant on DynamoDB
load/local_api.py                        over DynamoDB Local
spike/dynamodb/claims.py                 kept for the MRSC race script
pyproject.toml, uv.lock, docker-compose.yml, .github/workflows/ci.yml   PostgreSQL removed
tests/integration/...                    rewritten on DynamoDB Local; app-role and migration tests removed
docs/adr/0001, 0002; spec.md 2, 3, 4, 6, 7, 8, 10, 11; AGENTS.md; docs/cloud-run.md
```

`TASK.md` is the owner's brief and is not edited. It already names DynamoDB as the alternative.

### 9.5 Steps

**Slice C4.** One PR, after PR #10.
1. Store, service, saga and events. Check: the tests in 9.3, with the negative control.
2. Infra. Check: `make plan` green, with the resource counts in the PR.
3. Ops, k6-local and docs. Check: `make k6-local` gives one `201`, `make test` and
   `make test-integration` are green.

Then run 1 with the pass conditions of section 5. "The invariant query returns zero rows" now means
`violations` returns nothing.
