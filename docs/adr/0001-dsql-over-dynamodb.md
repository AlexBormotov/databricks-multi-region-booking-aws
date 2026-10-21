---
status: superseded by ADR-0002
---

# Aurora DSQL over DynamoDB Global Tables for the booking store

**Context.** A booking must claim every night of its stay so that no room-night is sold twice, while
both us-east-1 and us-east-2 take writes. Two stores offer strongly consistent multi-region writes on
AWS: Aurora DSQL, and DynamoDB global tables with multi-region strong consistency (MRSC). Both use
three regions, or two plus a witness.

**Decision.** The booking store is Aurora DSQL. One transaction reads the claims for the stay,
inserts the booking, one claim per night, the idempotency row and the outbox row, and commits. Of two
concurrent transactions on the same room-night, the first to commit wins and the other gets an OCC
conflict (spec 2.1). DynamoDB MRSC stays the documented alternative, backed by the spike in
`spike/dynamodb/claims.py`.

**Consequences.** DSQL bills per request and storage and has no change stream, so events leave
through an outbox and a regional poller (ADR 3). DSQL also limits each transaction to one DDL
statement and offers only `REPEATABLE READ`. In exchange, a multi-night booking is atomic, and the
idempotency key, the claims and the event commit together.

## Considered options

**DynamoDB MRSC, one conditional `PutItem` per night.** Conditional writes do the job of OCC for a
single night: of 50 concurrent claims on one room-night, exactly one succeeds
(`test_spike_single_winner`). Three gaps decide against it:

- **No transactions on MRSC tables.** A multi-night claim is a sequence of writes. When it loses a
  night part-way, it must release the nights it already took (`test_spike_compensation`). Until that
  release finishes, another guest can see the room as taken on nights it will not be sold.
- **No TTL on MRSC tables.** An abandoned hold is not removed by the table. Every claim has to carry
  its own expiry, and every claimant has to check it.
- **No transactional outbox.** The booking and its event cannot be written atomically, so events come
  from a change stream or a compensating step, not from the commit.

The cross-region half of this evidence comes from the cloud run (plan D8). A script on the session
runner sends concurrent conditional writes for one item from both active regions to a real MRSC
table. DynamoDB Local has no regions, so the spike tests prove only the claim logic.

## Version 2: the booking store on DynamoDB MRSC

The design to build if DSQL becomes unavailable or too expensive. All tables are on-demand MRSC
tables in us-east-1 and us-east-2, with a us-west-2 witness. Every read is strongly consistent.

**Tables.**

| Table | Key | Attributes |
|---|---|---|
| `room_nights` | `room_night` = `<room_id>#<night>` | `booking_id`, `expires_at` (epoch seconds; absent once confirmed) |
| `bookings` | `booking_id` | the columns of today's `bookings` table, including `status`, `version` and `expires_at` |
| `idempotency_keys` | `idem_key` | `request_hash`, `state` (`in_progress` or `done`), `response` |

`bookings` has a global secondary index on `room_id` for the invariant check. GSI reads are
eventually consistent, so the check runs after the load test has stopped.

**Booking (replaces spec 2.1).**

1. Put the idempotency item with `attribute_not_exists(idem_key)` and `state = in_progress`.
   - If it already exists with the same hash and `done`, return the stored response.
   - If it exists with a different hash, return `422`.
   - If it exists with the same hash and `in_progress`, return `409` with `Retry-After`.
2. Put the booking: `pending`, `version = 1`, `expires_at = now + HOLD_TTL`.
3. Claim each night in date order with `PutItem`. The condition is
   `attribute_not_exists(room_night) OR expires_at < :now_minus_skew`. The second clause takes over a
   stale hold, which replaces TTL and spec 2.1 step 3.
4. On a failed condition, release the nights this booking took (`claims.release`, conditioned on
   `booking_id`), mark the booking `rejected`, and store `409` in the idempotency item.
5. On success, store `201` in the idempotency item and start the saga as today.

**Clock skew.** The skew allowance is subtracted only when taking over a hold, so a hold is never
taken over while its owner can still confirm it. The saga confirms before `HOLD_TTL - margin`, and
the margin must exceed the skew allowance.

**Saga.**
- **Confirm.** Update the booking with `status = pending AND expires_at > :now`. Then remove
  `expires_at` from each claim, conditioned on `booking_id`.
- **Expire or cancel.** Update the booking first, then release its claims.
- **Crash.** A crash between steps leaves claims that carry an expiry. They become takeable after one
  hold TTL, which is the same bound as today's lost saga start.

**Events.** The DSQL outbox has no equivalent, because the booking and its event cannot be written in
one transaction. Events are derived from the `bookings` change stream: a Lambda reads each new item
image and emits the event, keyed by `booking_id` and `version`. **Verify before building** that MRSC
tables support DynamoDB Streams, and in which regions. If they do not, a regional poller scans
`bookings` by `updated_at`, as the outbox poller does today.

**Tests carried over.**
- The invariant query becomes a scan of `room_nights` checked against `bookings`.
- k6 runs the same scenario: exactly one `201` out of 1000 attempts.
- The spike tests become the unit of claim logic.
