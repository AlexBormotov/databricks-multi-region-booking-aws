output "stream_name" {
  value = aws_kinesis_stream.events.name
}

output "stream_arn" {
  value = aws_kinesis_stream.events.arn
}

output "landing_bucket" {
  value = aws_s3_bucket.landing.id
}
