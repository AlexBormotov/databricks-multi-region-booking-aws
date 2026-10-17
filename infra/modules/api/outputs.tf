output "api_url" {
  value = aws_apigatewayv2_stage.default.invoke_url
}

# The roles that connect to DSQL; `make up` maps them to booking_app.
output "db_role_arns" {
  value = [for name in ["api", "poller"] : aws_iam_role.lambda[name].arn]
}
