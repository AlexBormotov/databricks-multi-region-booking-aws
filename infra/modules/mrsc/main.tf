# The DynamoDB spike's table for the cloud run (plan D8): multi-region strong consistency across
# us-east-1 and us-east-2, witness in us-west-2. Persistent (plan D11): an empty on-demand table
# costs nothing, and a table that gained a replica may not be deletable for 24 hours.

resource "aws_dynamodb_table" "room_nights" {
  name         = "booking-spike-room-nights"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "room_night"

  attribute {
    name = "room_night"
    type = "S"
  }

  replica {
    region_name      = "us-east-2"
    consistency_mode = "STRONG"
  }

  global_table_witness {
    region_name = "us-west-2"
  }
}
