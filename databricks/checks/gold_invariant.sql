-- Fails the job if any room-night has two confirmed bookings. Reads silver, so it does not trust
-- the gold expectation it double-checks.
SELECT assert_true(count(*) = 0, 'a room-night has two confirmed bookings')
FROM (
  SELECT room_id, night
  FROM booking.silver.booking_nights
  WHERE status = 'confirmed'
  GROUP BY room_id, night
  HAVING count(*) > 1
)
