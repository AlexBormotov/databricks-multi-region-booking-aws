CREATE TABLE IF NOT EXISTS hotels (
    hotel_id uuid PRIMARY KEY,
    name text NOT NULL,
    city text NOT NULL,
    country text NOT NULL,
    tz text NOT NULL,
    currency text NOT NULL,
    lat double precision NOT NULL,
    lon double precision NOT NULL
)
