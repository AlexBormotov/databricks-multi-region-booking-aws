CREATE TABLE IF NOT EXISTS idempotency_keys (
    idem_key text PRIMARY KEY,
    request_hash text NOT NULL,
    booking_id uuid NOT NULL,
    status_code integer NOT NULL,
    response_body text NOT NULL,
    created_at timestamptz NOT NULL
)
