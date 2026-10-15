-- No room-night is sold twice: pairs of live bookings of the same room whose stays
-- [check_in, check_out) overlap. Must return zero rows.
-- It reads bookings only, so it does not trust the room_night claims it is checking.
SELECT a.hotel_id, a.room_id, a.booking_id, b.booking_id AS other_booking_id
FROM bookings a
JOIN bookings b
  ON b.hotel_id = a.hotel_id
 AND b.room_id = a.room_id
 AND b.booking_id > a.booking_id
 AND b.check_in < a.check_out
 AND a.check_in < b.check_out
WHERE (a.status = 'confirmed' OR (a.status = 'pending' AND a.expires_at > now()))
  AND (b.status = 'confirmed' OR (b.status = 'pending' AND b.expires_at > now()))
