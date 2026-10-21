include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  region = read_terragrunt_config(find_in_parent_folders("region.hcl")).locals.region
  live   = "${get_repo_root()}/infra/live/demo-prod"
  mock   = ["init", "validate", "plan", "destroy"]
}

terraform {
  source = "${get_repo_root()}/infra/modules//api"
}

dependency "store" {
  config_path = "${local.live}/us-east-1/store"
  mock_outputs = {
    table_names = ["booking-rooms", "booking-room-nights", "booking-bookings", "booking-idempotency"]
    stream_arn  = "arn:aws:dynamodb:us-east-1:123456789012:table/booking-bookings/stream/mock"
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

dependency "search" {
  config_path = "${local.live}/us-east-1/search"
  mock_outputs = {
    knowledge_base_id  = "MOCKKB0001"
    knowledge_base_arn = "arn:aws:bedrock:us-east-1:123456789012:knowledge-base/MOCKKB0001"
  }
  mock_outputs_allowed_terraform_commands = local.mock
}

inputs = {
  store_tables = dependency.store.outputs.table_names
  # Only us-east-1 has the bookings stream, so only it runs the events function.
  store_stream_arn   = local.region == "us-east-1" ? dependency.store.outputs.stream_arn : null
  stream_name        = dependency.stream.outputs.stream_name
  stream_arn         = dependency.stream.outputs.stream_arn
  state_machine_arn  = dependency.saga.outputs.state_machine_arn
  guest_vault_arns   = [dependency.vault_us.outputs.table_arn, dependency.vault_eu.outputs.table_arn]
  knowledge_base_id  = dependency.search.outputs.knowledge_base_id
  knowledge_base_arn = dependency.search.outputs.knowledge_base_arn
}
