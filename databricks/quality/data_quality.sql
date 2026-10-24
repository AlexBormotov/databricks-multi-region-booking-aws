-- Expectation results per pipeline update, from the pipeline's event log: how many rows each rule
-- passed and failed, in every layer. Rebuilt whole after each update; the event log keeps history.
CREATE OR REPLACE TABLE booking.gold.data_quality
AS
SELECT
  timestamp,
  origin.update_id,
  e.dataset,
  e.name AS expectation,
  e.passed_records,
  e.failed_records
FROM event_log(TABLE(booking.silver.events_dedup))
LATERAL VIEW explode(from_json(
  get_json_object(details, '$.flow_progress.data_quality.expectations'),
  'array<struct<name: string, dataset: string, passed_records: bigint, failed_records: bigint>>'
)) x AS e
WHERE event_type = 'flow_progress'
