# Hold saga in one active region: Pay races the hold TTL, then Confirm or Expire.

data "aws_region" "this" {}

locals {
  region = data.aws_region.this.region
  # The payment must finish before the hold expires; the margin covers Lambda start-up.
  payment_timeout_s = var.hold_ttl_s - 60
  functions = {
    pay     = { handler = "booking.handlers.saga.pay", timeout = local.payment_timeout_s }
    confirm = { handler = "booking.handlers.saga.confirm", timeout = 30 }
    expire  = { handler = "booking.handlers.saga.expire", timeout = 30 }
  }
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name                 = "booking-saga-lambda-${local.region}"
  assume_role_policy   = data.aws_iam_policy_document.lambda_trust.json
  permissions_boundary = var.permissions_boundary
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_dsql" {
  role = aws_iam_role.lambda.name
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "dsql:DbConnectAdmin", Resource = var.dsql_cluster_arn }]
  })
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/booking-saga-${each.key}"
  retention_in_days = 1
}

resource "aws_lambda_function" "fn" {
  for_each         = local.functions
  function_name    = "booking-saga-${each.key}"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.13"
  architectures    = ["x86_64"]
  handler          = each.value.handler
  filename         = var.package_path
  source_code_hash = filebase64sha256(var.package_path)
  memory_size      = 512
  timeout          = each.value.timeout

  environment {
    variables = {
      DSQL_ENDPOINT        = var.dsql_endpoint
      PAYMENT_FAILURE_RATE = tostring(var.payment_failure_rate)
      PAYMENT_LATENCY_S    = tostring(var.payment_latency_s)
    }
  }

  depends_on = [aws_cloudwatch_log_group.fn]
}

data "aws_iam_policy_document" "sfn_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name                 = "booking-saga-sfn-${local.region}"
  assume_role_policy   = data.aws_iam_policy_document.sfn_trust.json
  permissions_boundary = var.permissions_boundary
}

resource "aws_iam_role_policy" "sfn" {
  role = aws_iam_role.sfn.name
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = [for f in aws_lambda_function.fn : f.arn] }]
  })
}

resource "aws_sfn_state_machine" "saga" {
  name     = "booking-hold-saga"
  role_arn = aws_iam_role.sfn.arn
  definition = templatefile("${path.module}/definition.asl.json", {
    pay_function_arn     = aws_lambda_function.fn["pay"].arn
    confirm_function_arn = aws_lambda_function.fn["confirm"].arn
    expire_function_arn  = aws_lambda_function.fn["expire"].arn
    payment_timeout_s    = local.payment_timeout_s
  })
}
