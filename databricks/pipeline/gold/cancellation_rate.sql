-- Cancelled / (confirmed + cancelled), per hotel and check-in month.
CREATE OR REFRESH MATERIALIZED VIEW booking.gold.cancellation_rate
AS
SELECT
  hotel_id,
  date_trunc('MONTH', check_in) AS check_in_month,
  count_if(status = 'cancelled') AS cancelled,
  count(*) AS paid,
  count_if(status = 'cancelled') / count(*) AS cancellation_rate
FROM booking.gold.fact_booking
WHERE status IN ('confirmed', 'cancelled')
GROUP BY hotel_id, date_trunc('MONTH', check_in)
