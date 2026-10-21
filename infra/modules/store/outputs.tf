# The same names in both regions; each region's functions use their local replica.
output "table_names" {
  value = [for table in aws_dynamodb_table.store : table.name]
}

output "stream_arn" {
  value = aws_dynamodb_table.store["bookings"].stream_arn
}
