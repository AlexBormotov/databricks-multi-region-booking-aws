-- Occupancy = sold / available room-nights; ADR = revenue / sold; RevPAR = revenue / available.
CREATE OR REFRESH MATERIALIZED VIEW booking.gold.kpi_hotel_daily
AS
SELECT
  hotel_id,
  night AS date,
  count(*) AS available_room_nights,
  sum(CAST(sold AS INT)) AS sold_room_nights,
  sum(revenue_usd) AS room_revenue_usd,
  sum(CAST(sold AS INT)) / count(*) AS occupancy,
  sum(revenue_usd) / nullif(sum(CAST(sold AS INT)), 0) AS adr_usd,
  sum(revenue_usd) / count(*) AS revpar_usd
FROM booking.gold.fact_room_night
GROUP BY hotel_id, night
