-- Grain: booking. Lead time counts days from the booking's creation date in the hotel's time
-- zone to check-in (a hotel-local date). Timestamps are UTC (session time zone UTC).
CREATE OR REFRESH MATERIALIZED VIEW booking.gold.fact_booking
AS
SELECT
  b.booking_id,
  b.hotel_id,
  b.room_id,
  b.home_region,
  b.status,
  b.check_in,
  b.check_out,
  datediff(b.check_out, b.check_in) AS nights,
  b.created_at,
  to_date(from_utc_timestamp(b.created_at, h.tz)) AS created_local_date,
  datediff(b.check_in, to_date(from_utc_timestamp(b.created_at, h.tz))) AS lead_time_days,
  b.amount_minor,
  b.currency
FROM booking.silver.bookings b
JOIN booking.silver.dim_hotel h ON h.hotel_id = b.hotel_id AND h.__END_AT IS NULL
