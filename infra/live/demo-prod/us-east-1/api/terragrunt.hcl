include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  region = read_terragrunt_config(find_in_parent_folders("region.hcl")).locals.region
  live   = "${get_repo_root()}/infra/live/demo-prod"
  mock   = ["init", "validate", "plan"]
}

terraform {
  source = "${get_repo_root()}/infra/modules//api"
}

dependency "dsql" {
  config_path = "${local.live}/us-east-1/dsql"
  mock_outputs = {
    endpoints    = { "us-east-1" = "mock.dsql.us-east-1.on.aws", "us-east-2" = "mock.dsql.us-east-2.on.aws" }
    cluster_arns = { "us-east-1" = "arn:aws:dsql:us-east-1:123456789012:cluster/mock", "us-east-2" = "arn:aws:dsql:us-east-2:123456789012:cluster/mock" }
  }
  mock_outputs_allowed_terraform_commands = local.mock
}

dependency "stream" {
  config_path = "${local.live}/us-east-1/stream"
  mock_outputs = {
    stream_name = "booking-events"
    stream_arn  = "arn:aws:kinesis:us-east-1:123456789012:stream/booking-events"
  }
  mock_outputs_allowed_terraform_commands = local.mock
}

dependency "saga" {
  config_path = "../saga"
  mock_outputs = {
    state_machine_arn = "arn:aws:states:us-east-1:123456789012:stateMachine:booking-hold-saga"
  }
  mock_outputs_allowed_terraform_commands = local.mock
}

dependency "vault_us" {
  config_path                             = "${local.live}/us-east-1/guests_vault"
  mock_outputs                            = { table_arn = "arn:aws:dynamodb:us-east-1:123456789012:table/guests-us" }
  mock_outputs_allowed_terraform_commands = local.mock
}

dependency "vault_eu" {
  config_path                             = "${local.live}/eu-central-1/guests_vault"
  mock_outputs                            = { table_arn = "arn:aws:dynamodb:eu-central-1:123456789012:table/guests-eu" }
  mock_outputs_allowed_terraform_commands = local.mock
}

inputs = {
  dsql_endpoint     = dependency.dsql.outputs.endpoints[local.region]
  dsql_cluster_arn  = dependency.dsql.outputs.cluster_arns[local.region]
  stream_name       = dependency.stream.outputs.stream_name
  stream_arn        = dependency.stream.outputs.stream_arn
  state_machine_arn = dependency.saga.outputs.state_machine_arn
  guest_vault_arns  = [dependency.vault_us.outputs.table_arn, dependency.vault_eu.outputs.table_arn]
}
