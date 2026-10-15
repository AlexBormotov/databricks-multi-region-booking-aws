-- Grain: room x night across the reporting calendar, sold or not. Revenue is in USD at the
-- night's FX rate: the latest rate published on or before the night.
CREATE OR REFRESH MATERIALIZED VIEW booking.gold.fact_room_night (
  CONSTRAINT one_confirmed_booking_per_room_night EXPECT (confirmed_bookings <= 1)
    ON VIOLATION FAIL UPDATE,
  CONSTRAINT fx_rate_known EXPECT (nights_without_fx = 0) ON VIOLATION FAIL UPDATE
)
AS
WITH fx AS (
  SELECT
    currency,
    date AS valid_from,
    lead(date) OVER (PARTITION BY currency ORDER BY date) AS valid_to,
    rate_to_usd,
    exponent
  FROM booking.silver.fx_rates
),
sold AS (
  SELECT
    n.room_id,
    n.night,
    count(*) AS confirmed_bookings,
    count(*) - count(fx.rate_to_usd) AS nights_without_fx,
    sum(n.night_amount_minor / pow(10, fx.exponent) * fx.rate_to_usd) AS revenue_usd
  FROM booking.silver.booking_nights n
  LEFT JOIN fx
    ON fx.currency = n.currency
    AND n.night >= fx.valid_from
    AND (fx.valid_to IS NULL OR n.night < fx.valid_to)
  WHERE n.status = 'confirmed'
  GROUP BY n.room_id, n.night
)
SELECT
  r.hotel_id,
  r.room_id,
  d.date AS night,
  coalesce(s.confirmed_bookings, 0) AS confirmed_bookings,
  coalesce(s.confirmed_bookings, 0) > 0 AS sold,
  coalesce(s.nights_without_fx, 0) AS nights_without_fx,
  coalesce(s.revenue_usd, 0) AS revenue_usd
FROM booking.silver.dim_room r
CROSS JOIN booking.gold.dim_date d
LEFT JOIN sold s ON s.room_id = r.room_id AND s.night = d.date
WHERE r.__END_AT IS NULL
