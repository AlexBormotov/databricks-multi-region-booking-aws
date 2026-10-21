# The booking store (ADR 2): four on-demand tables, multi-region strongly consistent across
# us-east-1 and us-east-2 with a witness in us-west-2. Session resources: `make down` deletes them
# (plan 9.1). The key schemas match booking.store.KEYS.

locals {
  tables = {
    rooms         = { hash = "hotel_id", range = "room_id" }
    "room-nights" = { hash = "room_night", range = null }
    bookings      = { hash = "booking_id", range = null }
    idempotency   = { hash = "idem_key", range = null }
  }
}

resource "aws_dynamodb_table" "store" {
  for_each     = local.tables
  name         = "booking-${each.key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = each.value.hash
  range_key    = each.value.range

  # The booking events come from this stream. Only the creating region has one, and it carries
  # the writes made in both regions.
  stream_enabled   = each.key == "bookings"
  stream_view_type = each.key == "bookings" ? "NEW_AND_OLD_IMAGES" : null

  dynamic "attribute" {
    for_each = compact([each.value.hash, each.value.range])
    content {
      name = attribute.value
      type = "S"
    }
  }

  replica {
    region_name      = "us-east-2"
    consistency_mode = "STRONG"
  }

  global_table_witness {
    region_name = "us-west-2"
  }
}
