-- Cumulative confirmed bookings per stay date, by days before arrival.
CREATE OR REFRESH MATERIALIZED VIEW booking.gold.booking_pace
AS
SELECT
  stay_date,
  days_before,
  sum(count(*)) OVER (
    PARTITION BY stay_date ORDER BY days_before DESC ROWS UNBOUNDED PRECEDING
  ) AS cumulative_bookings
FROM (
  SELECT n.night AS stay_date, datediff(n.night, b.created_local_date) AS days_before
  FROM booking.silver.booking_nights n
  JOIN booking.gold.fact_booking b ON b.booking_id = n.booking_id
  WHERE b.status = 'confirmed'
)
GROUP BY stay_date, days_before
