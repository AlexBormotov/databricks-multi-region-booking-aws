-- One claim per sold room-night: the primary key is what makes a double booking impossible.
CREATE TABLE IF NOT EXISTS room_night (
    hotel_id uuid NOT NULL,
    room_id uuid NOT NULL,
    night date NOT NULL,
    booking_id uuid NOT NULL,
    PRIMARY KEY (hotel_id, room_id, night)
)
