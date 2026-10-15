-- The reporting calendar: every night from the first to the last booked night.
CREATE OR REFRESH MATERIALIZED VIEW booking.gold.dim_date
AS
SELECT
  d AS date,
  year(d) AS year,
  month(d) AS month,
  dayofweek(d) AS day_of_week,
  dayofweek(d) IN (1, 7) AS is_weekend
FROM (SELECT explode(sequence(min(night), max(night))) AS d FROM booking.silver.booking_nights)
