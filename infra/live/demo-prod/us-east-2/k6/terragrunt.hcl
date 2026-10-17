# The run's own values (start time, room, share of attempts) come from TF_VAR_* set by ops/demo.py.
include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  live = "${get_repo_root()}/infra/live/demo-prod"
  mock = ["init", "validate", "plan"]
}

terraform {
  source = "${get_repo_root()}/infra/modules//k6"
}

dependency "api_east_1" {
  config_path                             = "${local.live}/us-east-1/api"
  mock_outputs                            = { api_url = "https://mock1.execute-api.us-east-1.amazonaws.com" }
  mock_outputs_allowed_terraform_commands = local.mock
}

dependency "api_east_2" {
  config_path                             = "${local.live}/us-east-2/api"
  mock_outputs                            = { api_url = "https://mock2.execute-api.us-east-2.amazonaws.com" }
  mock_outputs_allowed_terraform_commands = local.mock
}

dependency "landing" {
  config_path = "${local.live}/us-east-1/landing"
  mock_outputs = {
    bucket     = "booking-landing-123456789012"
    bucket_arn = "arn:aws:s3:::booking-landing-123456789012"
  }
  mock_outputs_allowed_terraform_commands = local.mock
}

inputs = {
  api_urls           = [dependency.api_east_1.outputs.api_url, dependency.api_east_2.outputs.api_url]
  results_bucket     = dependency.landing.outputs.bucket
  results_bucket_arn = dependency.landing.outputs.bucket_arn
  script_path        = "${get_repo_root()}/load/contention.js"
}
