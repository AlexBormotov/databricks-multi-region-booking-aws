---
status: accepted
supersedes: ADR-0001
---

# DynamoDB MRSC replaces Aurora DSQL as the booking store

**Context.** ADR 1 chose Aurora DSQL. On this account `CreateCluster` fails in every region with
`ValidationException: Aurora DSQL can't create the cluster. Contact AWS Support for more details.`
The failure was first seen on 2026-10-17 and was still there on 2026-10-21. A support case is open
with no answer. Every other service the stack uses works on the account, including a DynamoDB
multi-region strong consistency (MRSC) table with a witness.

**Decision.** The booking store becomes the "Version 2" design of ADR 1: DynamoDB MRSC tables in
us-east-1 and us-east-2, with a witness in us-west-2.
- A booking claims each night with a conditional `PutItem`, in date order. If it loses a night, it
  releases the nights it already took.
- Events come from the `bookings` table's change stream, not from an outbox.

The protocol is in `plan.md` section 9.

**Consequences.**
- **No atomic multi-night booking.** A losing booking holds its earlier nights for a few
  milliseconds before it releases them, so a competing guest can get a `409` on a night that ends
  up unsold. Double booking is still impossible, because every night has exactly one claim item.
- **Hold expiry is checked by every writer.** Each claim carries its own expiry, because MRSC has
  no TTL. A takeover of an expired hold allows for clock skew.
- **The stream is regional.** It exists only in the region that created the table, us-east-1, and
  it carries the writes from both regions. If us-east-1 is down, events wait in the stream, which
  keeps them for 24 hours.
- **What goes.** PostgreSQL, the migrations, the SQL invariant and the `booking_app` role all leave
  the stack.
- **What reverses this.** If DSQL becomes available, ADR 1's design is in git history at `955b832`.
