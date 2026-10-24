---
status: accepted
---

# Nights are hotel-local dates; money is minor units in the hotel's currency

**Context.** Hotels sit in different time zones and price in different currencies. A night
"belongs" to the hotel's calendar, not to UTC. Floating-point money drifts in sums.

**Decision.**
- A stay's nights are hotel-local dates. Timestamps are stored in UTC. Lead time compares the
  check-in with the booking's creation date in the hotel's time zone:
  `to_date(from_utc_timestamp(created_at, tz))`.
- Amounts are integers in minor units with the ISO 4217 currency and its exponent. Gold converts
  each night to USD at the latest rate published on or before that night.
- `fact_room_night` fails the update if a sold night has no FX rate (`fx_rate_known`).

**Consequences.**
- **One instant, two local dates.** A booking created at 23:30 UTC on 1 March is 1 March in New York
  and 2 March in Tokyo, so the same stay gets lead times of 9 and 8 days ([`test_lead_time_across_midnight`](../../tests/lakehouse/test_gold.py)).
- **Revenue moves with the rate of the night, not of the booking.** That suits RevPAR per night. A
  report in booking-time rates would need a second join.
- **A missing rate stops gold.** That is deliberate: a silent zero would understate revenue.
