# The single event stream (plan decision D2): Kinesis -> Firehose -> landing bucket, us-east-1.

data "aws_caller_identity" "this" {}

locals {
  account_id = data.aws_caller_identity.this.account_id
}

resource "aws_kinesis_stream" "events" {
  name             = "booking-events"
  retention_period = 24
  # The AWS-managed key has no monthly charge, unlike a customer-managed one.
  encryption_type = "KMS"
  kms_key_id      = "alias/aws/kinesis"
  stream_mode_details {
    stream_mode = "ON_DEMAND"
  }
}

# Destroyed with the session; its contents are synthetic.
resource "aws_s3_bucket" "landing" {
  bucket        = "booking-landing-${local.account_id}"
  force_destroy = true
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

data "aws_iam_policy_document" "firehose_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "firehose" {
  name                 = "booking-firehose"
  assume_role_policy   = data.aws_iam_policy_document.firehose_trust.json
  permissions_boundary = var.permissions_boundary
}

resource "aws_iam_role_policy" "firehose" {
  role = aws_iam_role.firehose.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["kinesis:DescribeStream", "kinesis:GetShardIterator", "kinesis:GetRecords", "kinesis:ListShards"]
        Resource = aws_kinesis_stream.events.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:AbortMultipartUpload", "s3:GetBucketLocation", "s3:GetObject", "s3:ListBucket", "s3:ListBucketMultipartUploads", "s3:PutObject"]
        Resource = [aws_s3_bucket.landing.arn, "${aws_s3_bucket.landing.arn}/*"]
      },
    ]
  })
}

resource "aws_kinesis_firehose_delivery_stream" "landing" {
  name        = "booking-landing"
  destination = "extended_s3"

  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.events.arn
    role_arn           = aws_iam_role.firehose.arn
  }

  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.landing.arn
    prefix              = "events/region=!{partitionKeyFromQuery:home_region}/dt=!{timestamp:yyyy-MM-dd}/"
    error_output_prefix = "errors/!{firehose:error-output-type}/dt=!{timestamp:yyyy-MM-dd}/"
    compression_format  = "GZIP"
    # Dynamic partitioning needs a buffer of at least 64 MiB; the interval flushes a demo's trickle.
    buffering_size     = 64
    buffering_interval = 60

    dynamic_partitioning_configuration {
      enabled = true
    }

    processing_configuration {
      enabled = true
      processors {
        type = "MetadataExtraction"
        parameters {
          parameter_name  = "MetadataExtractionQuery"
          parameter_value = "{home_region: .home_region}"
        }
        parameters {
          parameter_name  = "JsonParsingEngine"
          parameter_value = "JQ-1.6"
        }
      }
      # One JSON object per line, so Auto Loader reads the files as JSON lines.
      processors {
        type = "AppendDelimiterToRecord"
      }
    }
  }
}
