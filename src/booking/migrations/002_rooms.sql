CREATE TABLE IF NOT EXISTS rooms (
    room_id uuid PRIMARY KEY,
    hotel_id uuid NOT NULL,
    room_type text NOT NULL,
    base_rate_minor bigint NOT NULL
)
