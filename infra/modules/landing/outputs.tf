output "bucket" {
  value = aws_s3_bucket.landing.id
}

output "bucket_arn" {
  value = aws_s3_bucket.landing.arn
}
