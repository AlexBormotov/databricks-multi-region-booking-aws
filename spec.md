# Spec

Status: approved by the owner on 2026-10-14. Implements `intent.md`. Amended on 2026-10-14 by
decisions D1-D3 of `plan.md`, and on 2026-10-15 by the slice 1 review (API `400`/`404`,
`PaymentRefunded` event id), and on 2026-10-15 by decisions D6-D8 of `plan.md`, and on 2026-10-16 by decisions D10-D12 and
D14 of the cloud-slice `plan.md`, and on 2026-10-21 by its section 9 (DynamoDB MRSC replaces
Aurora DSQL, ADR 2).

Every slice ends with a checkable completion condition. "Local" means `make` targets inside the dev
container, at $0. "Cloud" means the single recorded `cloud-session` run. A claim marked
**verify** is a platform fact to confirm before the plan that depends on it.

## 1. Domain

| Term | Meaning |
|---|---|
| room-night | one specific room on one hotel-local calendar date (`DATE`, no time zone). The unit of inventory |
| hold | a booking in `pending` with `expires_ms`; it occupies its room-nights until it expires |
| claim | the item in `booking-room-nights` that marks a room-night as taken by a booking |
| jurisdiction | where a guest's PII is stored: `US` (us-east-1) or `EU` (eu-central-1), from the residence country declared at registration |
| home region | the AWS region whose API accepted the write; recorded on every event |

Booking states: `pending -> confirmed | expired | cancelled`, and `confirmed -> cancelled`. No other
transition is legal. Every transition increments `bookings.version` by 1.

## 2. Transactional store (DynamoDB MRSC)

Aurora DSQL was the first choice (ADR 1); the account cannot create a cluster, so the store is
DynamoDB with multi-region strong consistency (ADR 2, `plan.md` section 9). Region set: us-east-1
and us-east-2 active, us-west-2 witness. Lambdas use the replica in their own region through IAM;
no VPC and no NAT. Every read is strongly consistent.

Tables (on demand, created by `make up`, deleted by `make down`; times are epoch milliseconds):

- `booking-rooms(hotel_id, room_id)`: `room_type`, `base_rate_minor`, `currency` (the hotel's)
- `booking-room-nights(room_night = <room_id>#<night>)`: `booking_id`, `expires_ms` (absent once
  confirmed). One item per taken room-night: the key is what makes a double booking impossible.
- `booking-bookings(booking_id)`: `hotel_id, room_id, guest_id, check_in, check_out, status,
  expires_ms, amount_minor, currency, version, home_region, created_ms, updated_ms, changed_in,
  refunded`. Its stream (`NEW_AND_OLD_IMAGES`) is the source of the booking events.
- `booking-idempotency(idem_key)`: `request_hash, state (in_progress | done), started_ms, response`

Invariant (`booking.store.violations`): pairs of live bookings (`pending` before `expires_ms`, or
`confirmed`) of the same room with overlapping `[check_in, check_out)`, from a strongly consistent
scan of `bookings`. It must be empty. It reads `bookings` only, so it does not trust the claims it
checks.

### 2.1 Booking (the core)

1. Take the `Idempotency-Key`: a conditional put of `in_progress`, which succeeds if the key is new
   or its 30 s lease has run out. A key that is `done` with the same request hash returns the stored
   response (`200`); a different hash returns `422`; a key in progress returns `409` with
   `Retry-After`.
2. Read the room; unknown: `404`.
3. Claim each night in date order with a conditional put: the night is free, or its claim is a hold
   that expired more than 5 s ago (clock-skew allowance; the takeover also expires that hold's
   booking). A failed condition releases the nights already taken and returns `409`.
4. Put the booking (`pending`, `expires_ms = now + HOLD_TTL`, `version = 1`) and store `201` in the
   key. Any answer other than `201` frees the key, so a retry is evaluated again.

A write that loses a cross-region race (`ReplicatedWriteConflictException`) is retried with
exponential backoff and full jitter, at most 5 attempts; out of retries: `503` with `Retry-After`.

Guarantee: of N concurrent bookings that claim the same room-night, at most one holds it. This is
"first write wins", not "first click". Two regions share no clock that orders clicks, so a
"first click" rule cannot be enforced or checked; the write order can. MRSC has no transactions:
a losing multi-night booking holds its earlier nights for milliseconds before it releases them.

### 2.2 Saga (Step Functions)

After the hold the API starts one execution per booking: `Wait(HOLD_TTL - margin)` races a
simulated payment step (latency and failure rate are parameters). Every write is conditional on the
booking's `version`; a booking changed in between is read again.

- payment succeeded: first the claims lose their expiry (conditioned on `booking_id`), then the
  booking becomes `confirmed` if it is still `pending` before `expires_ms`. A crash in between
  leaves the room blocked, never sold twice. If a claim was taken over or the hold has expired, the
  booking is `expired`, its claims are released, and `refunded` is set (a simulated refund).
- timeout: `pending` becomes `expired` and the claims are released.

Starting the execution after the hold can be lost (the Lambda dies in between); the hold's claims
then become takeable after `HOLD_TTL`, so a lost start costs a room for `HOLD_TTL`, never a double
booking.

### 2.3 Events from the change stream

The `bookings` stream exists only in us-east-1, where the table was created, and carries the writes
made in both regions. One Lambda there turns each change into envelopes on the Kinesis stream: a new
status is `BookingHeld`, `BookingConfirmed`, `BookingExpired` or `BookingCancelled`; `refunded`
turning true is `PaymentRefunded`. A batch with a rejected record fails and is delivered again.
Delivery is at-least-once; duplicates are removed downstream by `event_id`.

### 2.4 Rejected-attempt telemetry

A `409` or `503` puts one `BookingAttemptRejected` record straight to the Kinesis stream in us-east-1,
best-effort. It is telemetry, not state: losing it breaks no invariant.

### 2.5 API (API Gateway HTTP API + Lambda, Python 3.13, both active regions)

| Method and path | Result |
|---|---|
| `POST /guests` | registers a guest; PII goes to the jurisdiction's vault; returns `guest_id` |
| `GET /availability?hotel_id&check_in&check_out` | free rooms for the stay |
| `POST /bookings` (header `Idempotency-Key` required) | `201` hold, `200` replay, `409`, `422`, `503` |
| `POST /bookings/{id}/cancel` | `200`; legal only from `pending` or `confirmed` |
| `GET /search?q&check_in&check_out` | hotels matching `q`, filtered to those with a free room |

Every route answers `400` to malformed input and `404` to an unknown hotel, room or booking.

### 2.6 PII residency

`POST /guests` stores name, email and phone in a single-region DynamoDB table: `guests-us` in
us-east-1 for any residence country outside the EU/EEA, `guests-eu` in eu-central-1 inside it. The booking store,
events, S3 and the lakehouse carry only `guest_id` and `jurisdiction`. A guest registering from abroad
without proof of residence is stored by the declared country; this limit is documented, not solved.

## 3. Event contract

Every event, from the change stream or from telemetry, is one JSON object:

`event_id`, `event_type`, `aggregate_id`, `aggregate_version` (null for telemetry),
`home_region`, `occurred_at` (UTC, ISO-8601), `schema_version`, `payload`.

Booking events take name-based ids (uuidv5): a state event from the booking id and its version,
`PaymentRefunded` from the booking id. A redelivered change therefore repeats its ids. Telemetry
and the historical generator use uuidv7.

Types: `BookingHeld`, `BookingConfirmed`, `BookingExpired`, `BookingCancelled`, `PaymentRefunded`,
`BookingAttemptRejected`. Amounts are minor units plus currency; nights are hotel-local dates. The
historical generator emits the same contract.

## 4. Landing

One Kinesis Data Stream (on-demand) -> Firehose -> one S3 bucket, all in us-east-1. The events
function in us-east-1 puts to that stream; rejected-attempt telemetry from us-east-2 calls it
cross-region with the SDK. If us-east-1 is down, changes wait in the bookings stream, which keeps
them for 24 h, and drain on recovery. Firehose
partitions by the record's `home_region`: prefix `events/region=<r>/dt=<yyyy-mm-dd>/`, gzip JSON
lines. Historical data is written by the generator to `events/region=<r>/backfill/`.
Reference data (hotels, rooms, FX rates) lands as files under `reference/`. Unity Catalog reads the
bucket through a storage credential and an external location. If the workspace cannot create them,
the runner copies the landing prefix into a UC managed volume and the pipeline reads that instead.

## 5. Lakehouse (Databricks on AWS, Unity Catalog, us-east-1)

Catalog `booking`, schemas `bronze`, `silver`, `gold`. One Lakeflow Declarative Pipeline, serverless,
triggered. bronze and silver in Python (`pyspark.pipelines`), with transformations as pure
`DataFrame -> DataFrame` functions in a package tested locally; gold as SQL materialized views.

| Layer | Table | Notes |
|---|---|---|
| bronze | `events` | Auto Loader, append-only, adds `_ingested_at`, `_source_file`; expectations warn only |
| silver | `events_dedup` | one row per `event_id` |
| silver | `bookings` | `AUTO CDC ... SEQUENCE BY aggregate_version`, SCD1 |
| silver | `bookings_history` | the same flow, SCD2 |
| silver | `booking_nights` | one row per booking and night |
| silver | `dim_hotel`, `dim_room` | SCD2 from reference files |
| silver | `fx_rates` | currency, date, rate to USD |
| silver | `quarantine_events` | rows dropped by silver expectations, with the rule name |
| silver | `attempts_rejected` | telemetry |
| gold | `fact_room_night` | grain room x night across the reporting calendar, sold or not |
| gold | `fact_booking` | grain booking |
| gold | `dim_date` | calendar |
| gold | `kpi_hotel_daily`, `booking_pace`, `lead_time`, `cancellation_rate`, `conflict_rate_by_region` | marts |

Metric definitions (sold means `confirmed`; revenue in USD at the night's FX rate):

- occupancy = sold room-nights / available room-nights
- ADR = room revenue / sold room-nights
- RevPAR = room revenue / available room-nights
- booking pace = cumulative bookings per stay date by days before arrival
- lead time = `check_in` minus booking creation date in the hotel's time zone
- cancellation rate = cancelled / (confirmed + cancelled)
- conflict rate by region = rejected attempts / all attempts, per `home_region`

Expectations: bronze `expect`; silver `expect_all_or_drop` from one rule set, and
`quarantine_events` keeps the rows breaking any rule of that same set, with the rule name (unknown currency, night outside the stay, missing `aggregate_version` on a
state event); gold `expect_or_fail` on "no room-night has two confirmed bookings".

Lakeflow Job `booking-refresh`: pipeline update -> SQL checks (gold invariant, row counts against
the store invariant) -> dashboard refresh. File-arrival trigger on the landing prefix, at most once
every 5 minutes. AI/BI dashboard in the bundle as `.lvdash.json`, three pages: occupancy and revenue;
demand (pace, lead time, cancellations); regional contention (conflicts, wins per region, k6 result).
Everything ships as one Databricks Asset Bundle.

## 6. Semantic search

Bedrock Knowledge Base on S3 Vectors in us-east-1, over templated hotel descriptions and reviews
(synthetic, no LLM-generated text, so the corpus is reproducible). Embeddings: Amazon Titan Text
Embeddings V2 (**verify** availability for KB with S3 Vectors). `GET /search` retrieves the top-k
hotels for `q`, then keeps those with a free room for the stay from the booking store. The KB is created by
`make up` and destroyed by `make down`.

## 7. DynamoDB Global Tables (spike and ADR)

A spike, not a second stack: one MRSC table keyed by `room_night`, a conditional `PutItem`
(`attribute_not_exists`) per night, tested locally against DynamoDB Local.
In the cloud run a script on the session runner sends concurrent conditional writes for one item
from both active regions to a real MRSC table. The ADR explains why it is the
alternative and not the choice: MRSC has no transactions, so a multi-night booking cannot claim its
nights atomically and needs a compensating saga; no TTL on MRSC; conditional writes do replace OCC
for single-night claims. It ends with a "version 2" design detailed enough to implement.

Since 2026-10-21 that version 2 is the store itself (section 2, ADR 2). The spike table and the
race script stay as the cross-region evidence.

## 8. Operations

- Make targets: `lint`, `test`, `test-integration`, `security`, `plan`, `up`, `demo`, `down`,
  `cost-report`. CI and contributors run the same targets in the same image.
- `make demo SCALE=small|demo`: backfill history, run live traffic through the API, then the k6
  contention scenario.
- Session expiry: `make up` writes an expiry time (default +2 h) to SSM Parameter Store; a GitHub
  Actions cron every 30 minutes runs `make down` once it passes. Budget alert at $12 to email.
- Persistent, idle-free: Terraform state bucket and lock, GitHub OIDC roles (read-only for `plan`,
  deploy for `cloud-session`), budget, GHCR image. Also, created by the first `make up` and kept by
  `make down`: the landing bucket (emptied), the UC storage credential, external location and
  catalog, and the empty MRSC spike table.
- Cost report: `make cost-report DATE=<session date>` runs the day after the session, because Cost
  Explorer lags by up to 24 h. It filters AWS costs by the `project` cost allocation tag and adds the
  Databricks usage from `system.billing.usage` at list price.
- IaC: Terraform modules plus Terragrunt live tree `live/demo-prod/<region>/<component>`.

## 9. CI/CD

- PR workflow: `lint`, `test`, `test-integration`, `security`, `plan` (read-only OIDC role, plan as a
  PR comment). All run in the GHCR dev image.
- `cloud-session` workflow: manual, GitHub Environment `demo-prod` with required reviewer. `up` ->
  `demo` -> collect artifacts -> `down` with `if: always()`.
- Trunk-based on protected `main`, squash merge, Conventional Commits. Release `v1.0.0` after the
  cloud run carries its artifacts.

## 10. Slices and completion conditions

**Slice 0, foundation.** Done when: the dev image builds and is pushed to GHCR; the PR workflow runs
`lint`, `test` and `security` green on an empty skeleton; `make plan` succeeds against the real account
with the read-only role; the state bucket, OIDC roles and $12 budget exist (created by a one-time
bootstrap, documented step by step).

Slices 1 to 4 were completed on Aurora DSQL, with PostgreSQL standing in locally. Slice C4
(`plan.md` section 9) carries their checks over to DynamoDB Local; their names are kept where the
claim is the same.

**Slice 1, booking core.** Done when, locally:
- `test_concurrent_same_room_night`: N = 1000 concurrent bookings of one room-night against PostgreSQL
  yield exactly one `201` and N-1 `409`, and the invariant query returns zero rows;
- `test_idempotent_replay`: the same `Idempotency-Key` returns the same response and creates one booking;
- `test_payment_after_expiry`: a payment arriving after `expires_at` leaves the booking `expired` and
  emits `PaymentRefunded`;
- `test_stale_hold_takeover`: an expired hold's room-night can be booked again;
- `test_outbox_poller`: every committed event reaches Kinesis (moto) at least once, only from
  its own region;
- `test_pii_residency`: an EU guest's PII exists only in `guests-eu`, and no event carries PII;
- `terraform validate` passes for every component.

**Slice 2, lakehouse.** Done when, locally:
- pytest on the silver functions: duplicates by `event_id` collapse; quarantine rules route bad rows; FX conversion and hotel-local
  dates are correct across a time-zone boundary;
- the CDC oracle query (`checks/cdc_latest.sql`) resolves out-of-order and duplicate events to the
  highest `aggregate_version` on a fixture; in the cloud run the job compares it with the AUTO CDC
  output and fails on any difference;
- gold SQL is checked against a fixed fixture with hand-computed occupancy, ADR and RevPAR;
- `databricks bundle validate` needs workspace auth, so it runs in the cloud run.

**Slice 3, semantic search.** Done when, locally: the availability filter drops hotels without a free
room (KB retrieval stubbed); the corpus generator is deterministic for a seed.

**Slice 4, DynamoDB spike.** Done when: the spike's conditional-write test passes against DynamoDB
Local, and the ADR is written.

**Cloud run (once).** Done when the `cloud-session` artifacts show:
- k6 from three regions: exactly one `201` out of 1000 attempts;
- the store invariant (`booking.store.violations`) is empty;
- the gold expectation passed and the dashboard shows data from both regions;
- `/search` returned only hotels with availability;
- the MRSC script: exactly one conditional write per item succeeded across both regions;
- `make down` completed and the cost report is under $7.

**Packaging.** Done when the README has the architecture diagram, 3-5 ADRs, the cost report, the
demo video link, and sections on first commit vs first click, payment after TTL, the last room from
two regions, the expectation policy, the pipeline run mode and the environment structure. Every claim
links to a test, a CI run or a cloud-run artifact.

## 11. ADRs to write

1. Aurora DSQL over DynamoDB Global Tables for the booking store (superseded by 2).
2. DynamoDB MRSC replaces Aurora DSQL as the booking store, with events from its change stream.
3. Room-night claims and first-write-wins concurrency.
4. PII residency by guest jurisdiction, outside the replicated store.
5. Triggered serverless pipeline with ordering by aggregate version.
