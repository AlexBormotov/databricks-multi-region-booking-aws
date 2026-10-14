CREATE TABLE IF NOT EXISTS bookings (
    booking_id uuid PRIMARY KEY,
    hotel_id uuid NOT NULL,
    room_id uuid NOT NULL,
    guest_id uuid NOT NULL,
    check_in date NOT NULL,
    check_out date NOT NULL,
    status text NOT NULL,
    expires_at timestamptz NOT NULL,
    amount_minor bigint NOT NULL,
    currency text NOT NULL,
    version integer NOT NULL,
    home_region text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
)
