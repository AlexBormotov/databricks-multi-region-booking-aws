# A single-region PII vault: the table never replicates out of its jurisdiction's region.
resource "aws_dynamodb_table" "guests" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "guest_id"

  attribute {
    name = "guest_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = false
  }
}
