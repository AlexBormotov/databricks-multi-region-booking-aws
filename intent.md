# Intent

Status: approved by the owner on 2026-10-13. Source brief: `TASK.md`. Hard-to-reverse decisions are
recorded as ADRs under `docs/adr/`.

## Why

A portfolio case for a Senior Data Engineer role. The reader is a recruiter or interviewer who will
not run anything, so the case must prove its claims with evidence they can read: tests green in CI,
artifacts from one recorded cloud run, a diagram, ADRs, a cost report and a short video.

The business problem it models is the one Booking and Airbnb solve: **no room-night is ever sold
twice, even when the last room is booked concurrently from different regions**, and the bookings
feed occupancy and revenue analytics plus a semantic hotel search.

## Outcomes

1. **Zero double bookings under cross-region contention, proven.** 1000 concurrent attempts on one
   room-night from three regions produce exactly one booking; an invariant query in the
   transactional store and an expectation in the lakehouse both confirm it.
2. **A data-engineering pipeline worth reading.** Booking events travel through an outbox into a
   medallion lakehouse on Databricks (bronze, silver, gold star schema) with exactly-once semantics,
   cross-region ordering by aggregate version, data-quality expectations, and BI dashboards for
   occupancy, ADR, RevPAR, booking pace, lead time, cancellations and per-region conflicts.
3. **Semantic search over real availability.** A natural-language hotel query returns only hotels
   with free rooms for the requested nights.
4. **Hard problems shown worked through:** first commit vs "first click", payment arriving after the
   hold expired, event ordering across regions, time zones and currencies, PII residency by guest
   jurisdiction.
5. **Cheap and safe to run.** `make up` -> `make demo` -> `make down`, synthetic data at a chosen
   scale, $3-7 per session, a $12 budget alert and a timed auto-destroy.

## Constraints

- Self-funded. The cloud is exercised **once**, when everything is built and verified locally;
  everything before that costs $0.
- Only idle-free resources persist: Terraform state bucket, IAM/OIDC setup, budget alert, container
  image in GHCR. The Databricks workspace (trial) is created right before the cloud run.
- AWS North America region set (us-east-1, us-east-2 active, us-west-2 witness); EU PII store in
  eu-central-1. One environment, `demo-prod`.
- Public GitHub repository, English documentation.

## Non-goals

- A full DynamoDB Global Tables implementation (an ADR plus a spike instead).
- Real payments, real personal data, or a user interface beyond API and dashboards.
- Multiple environments, Snowflake, the AI-factory harness eval suite.

## Done when

The owner can point a recruiter at the README and every claim in it links to a passing test, a CI
run, or an artifact of the recorded cloud run.
