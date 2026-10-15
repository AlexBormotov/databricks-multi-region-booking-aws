-- Fails the job unless events from both active regions reached silver.
SELECT assert_true(count(DISTINCT home_region) = 2, 'silver lacks events from a region')
FROM booking.silver.events_dedup
