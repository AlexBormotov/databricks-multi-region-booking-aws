# The landing bucket: Firehose writes here and Unity Catalog reads it through an external location.
# Persistent (plan D11): free while empty, so the external location survives between sessions.
# `make down` empties it.

data "aws_caller_identity" "this" {}

resource "aws_s3_bucket" "landing" {
  bucket = "booking-landing-${data.aws_caller_identity.this.account_id}"
}

resource "aws_s3_bucket_public_access_block" "landing" {
  bucket                  = aws_s3_bucket.landing.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "landing" {
  bucket = aws_s3_bucket.landing.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
