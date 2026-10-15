CREATE TABLE IF NOT EXISTS outbox (
    event_id uuid PRIMARY KEY,
    aggregate_id uuid NOT NULL,
    aggregate_version integer NOT NULL,
    event_type text NOT NULL,
    payload jsonb NOT NULL,
    home_region text NOT NULL,
    occurred_at timestamptz NOT NULL,
    published_at timestamptz
)
