# One k6 load generator in this region for the contention scenario. `make demo` applies it with a
# start time; with none (as under `make up`) it creates nothing. The instance waits for the start
# time, runs load/contention.js, puts its summary into the landing bucket under k6/, and terminates.

data "aws_region" "this" {}

locals {
  region  = data.aws_region.this.region
  enabled = var.start_at_ms > 0 ? 1 : 0
  summary = "k6/${var.run_id}/${local.region}.json"
}

data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

data "aws_iam_policy_document" "ec2_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "k6" {
  count                = local.enabled
  name                 = "booking-k6-${local.region}"
  assume_role_policy   = data.aws_iam_policy_document.ec2_trust.json
  permissions_boundary = var.permissions_boundary
}

resource "aws_iam_role_policy" "k6" {
  count = local.enabled
  role  = aws_iam_role.k6[0].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "s3:PutObject"
      Resource = "${var.results_bucket_arn}/${local.summary}"
    }]
  })
}

resource "aws_iam_instance_profile" "k6" {
  count = local.enabled
  name  = "booking-k6-${local.region}"
  role  = aws_iam_role.k6[0].name
}

resource "aws_instance" "k6" {
  count                = local.enabled
  ami                  = data.aws_ssm_parameter.al2023_arm64.insecure_value
  instance_type        = var.instance_type
  iam_instance_profile = aws_iam_instance_profile.k6[0].name

  # A one-time spot instance cannot be stopped, so the shutdown in user_data terminates it.
  # Setting instance_initiated_shutdown_behavior is refused for spot instances.
  instance_market_options {
    market_type = "spot"
    spot_options {
      spot_instance_type             = "one-time"
      instance_interruption_behavior = "terminate"
    }
  }

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    encrypted = true
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    k6_version  = var.k6_version
    script      = file(var.script_path)
    api_urls    = join(",", var.api_urls)
    hotel_id    = var.hotel_id
    room_id     = var.room_id
    check_in    = var.check_in
    check_out   = var.check_out
    attempts    = var.attempts
    start_at_ms = var.start_at_ms
    summary_uri = "s3://${var.results_bucket}/${local.summary}"
  })

  tags = { Name = "booking-k6" }
}
