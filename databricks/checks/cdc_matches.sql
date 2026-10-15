-- Fails the job unless AUTO CDC kept, for every booking, the state the oracle computes.
SELECT assert_true(count(*) = 0, 'silver.bookings differs from the AUTO CDC oracle')
FROM (
  (SELECT booking_id, status, version FROM booking.silver.bookings_expected
   EXCEPT SELECT booking_id, status, version FROM booking.silver.bookings)
  UNION ALL
  (SELECT booking_id, status, version FROM booking.silver.bookings
   EXCEPT SELECT booking_id, status, version FROM booking.silver.bookings_expected)
)
