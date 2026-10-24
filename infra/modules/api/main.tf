# Booking API in one active region, plus, in the region that has the bookings stream, the
# function that turns its changes into events.

data "aws_region" "this" {}
data "aws_caller_identity" "this" {}

locals {
  region = data.aws_region.this.region
  environment = {
    STREAM_NAME       = var.stream_name
    STATE_MACHINE_ARN = var.state_machine_arn
    HOLD_TTL_S        = tostring(var.hold_ttl_s)
  }
  # The local replica of each store table.
  store = {
    Effect   = "Allow"
    Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:BatchGetItem"]
    Resource = [for name in var.store_tables : "arn:aws:dynamodb:${local.region}:${data.aws_caller_identity.this.account_id}:table/${name}"]
  }
  put_events = { Effect = "Allow", Action = ["kinesis:PutRecord", "kinesis:PutRecords"], Resource = var.stream_arn }
  # Each function gets its own role with only what it calls.
  functions = merge({
    api = {
      handler = "booking.handlers.api.handler"
      timeout = 15
      statements = [
        local.store,
        local.put_events, # rejected-attempt telemetry
        { Effect = "Allow", Action = "dynamodb:PutItem", Resource = var.guest_vault_arns },
        { Effect = "Allow", Action = "states:StartExecution", Resource = var.state_machine_arn },
      ]
    }
    }, var.store_stream_arn == null ? {} : {
    events = {
      handler = "booking.handlers.events.handler"
      timeout = 60
      statements = [
        local.put_events,
        { Effect = "Allow", Action = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"], Resource = var.store_stream_arn },
      ]
    }
  })
  routes = ["POST /guests", "GET /availability", "POST /bookings", "POST /bookings/{booking_id}/cancel"]
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
  for_each             = local.functions
  name                 = "booking-${each.key}-lambda-${local.region}"
  assume_role_policy   = data.aws_iam_policy_document.lambda_trust.json
  permissions_boundary = var.permissions_boundary
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  for_each   = local.functions
  role       = aws_iam_role.lambda[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda" {
  for_each = local.functions
  role     = aws_iam_role.lambda[each.key].name
  policy   = jsonencode({ Version = "2012-10-17", Statement = each.value.statements })
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/booking-${each.key}"
  retention_in_days = 1
}

resource "aws_lambda_function" "fn" {
  for_each         = local.functions
  function_name    = "booking-${each.key}"
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.13"
  architectures    = ["x86_64"]
  handler          = each.value.handler
  filename         = var.package_path
  source_code_hash = filebase64sha256(var.package_path)
  memory_size      = 512
  timeout          = each.value.timeout

  environment {
    variables = local.environment
  }

  depends_on = [aws_cloudwatch_log_group.fn]
}

resource "aws_apigatewayv2_api" "http" {
  name          = "booking"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.fn["api"].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "route" {
  for_each  = toset(local.routes)
  api_id    = aws_apigatewayv2_api.http.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 2000
    throttling_rate_limit  = 1000
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "apigw"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["api"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# A failed batch is delivered again until it succeeds or the stream drops it after 24 h; the
# lakehouse removes the duplicates by event_id.
resource "aws_lambda_event_source_mapping" "events" {
  count                              = var.store_stream_arn == null ? 0 : 1
  event_source_arn                   = var.store_stream_arn
  function_name                      = aws_lambda_function.fn["events"].arn
  starting_position                  = "TRIM_HORIZON"
  batch_size                         = 100
  maximum_batching_window_in_seconds = 1
}
