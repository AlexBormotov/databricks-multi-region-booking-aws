output "state_machine_arn" {
  value = aws_sfn_state_machine.saga.arn
}

# The roles that connect to DSQL; `make up` maps them to booking_app.
output "db_role_arns" {
  value = [for name in ["confirm", "expire"] : aws_iam_role.lambda[name].arn]
}
