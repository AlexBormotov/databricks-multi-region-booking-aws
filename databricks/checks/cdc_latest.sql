-- The AUTO CDC oracle: each booking's state is its event with the highest aggregate_version,
-- whatever order the events arrived in. cdc_matches.sql compares it with silver.bookings.
CREATE OR REPLACE VIEW booking.silver.bookings_expected
AS
SELECT booking_id, hotel_id, room_id, guest_id, check_in, check_out, status, amount_minor,
  currency, home_region, created_at, updated_at, aggregate_version AS version
FROM (
  SELECT *, row_number() OVER (PARTITION BY booking_id ORDER BY aggregate_version DESC) AS rn
  FROM booking.silver.events_dedup
  WHERE event_type IN ('BookingHeld', 'BookingConfirmed', 'BookingExpired', 'BookingCancelled')
)
WHERE rn = 1
