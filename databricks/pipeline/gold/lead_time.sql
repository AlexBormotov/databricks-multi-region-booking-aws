-- Distribution of lead time for bookings that were paid (confirmed, possibly cancelled later).
CREATE OR REFRESH MATERIALIZED VIEW booking.gold.lead_time
AS
SELECT hotel_id, lead_time_days, count(*) AS bookings
FROM booking.gold.fact_booking
WHERE status IN ('confirmed', 'cancelled')
GROUP BY hotel_id, lead_time_days
