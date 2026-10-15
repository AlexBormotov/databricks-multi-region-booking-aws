-- Rejected attempts / all attempts per home region. Every booking is an attempt that won.
CREATE OR REFRESH MATERIALIZED VIEW booking.gold.conflict_rate_by_region
AS
SELECT
  home_region,
  count(*) AS attempts,
  sum(rejected) AS rejected,
  sum(rejected) / count(*) AS conflict_rate
FROM (
  SELECT home_region, 0 AS rejected FROM booking.silver.bookings
  UNION ALL
  SELECT home_region, 1 AS rejected FROM booking.silver.attempts_rejected
)
GROUP BY home_region
