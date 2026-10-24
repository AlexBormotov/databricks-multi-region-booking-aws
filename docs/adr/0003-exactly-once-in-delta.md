---
status: accepted
---

# Exactly once in Delta: dedup on `event_id`, then AUTO CDC by version

**Context.** Events reach the lakehouse at least once. The stream Lambda can be retried, and
Firehose can write a record twice. Events from the two regions arrive in no particular order:
a booking's `confirmed` can land before its `pending`. The brief names `MERGE` on `event_id`.

**Decision.** Two declared steps in the pipeline, no hand-written `MERGE`.
- Every event carries a name-based id: `uuid5(booking_id, version)` for a state change,
  `uuid5(booking_id)` for a refund. A redelivered change repeats its id.
- `silver.events_dedup` keeps one row per `event_id` with `dropDuplicates(["event_id"])` and no
  watermark, so the streaming state never forgets an id.
- `silver.bookings` (SCD type 1) and `silver.bookings_history` (SCD type 2) are built with
  `AUTO CDC ... SEQUENCE BY version`. The highest version wins, whatever the arrival order.

**Consequences.**
- **Proven by a replay.** Run 5 wrote all 4632 events again, twice, shuffled. Silver had no
  duplicate ids, and the fingerprints of five silver and gold tables did not change.
- **The dedup state grows with the table.** It holds every id ever seen. That is small at demo
  volume. At production volume it needs a watermark, which reopens the window for late duplicates.
- **`MERGE` is implied, not written.** AUTO CDC compiles to a merge keyed on `booking_id`. An
  independent check, `cdc_matches`, compares its result with a plain "latest version per booking"
  query after every refresh.
- **What reverses this.** A watermark on dedup, or a `foreachBatch` `MERGE`, if state size or
  latency demands it.
