include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  region = read_terragrunt_config(find_in_parent_folders("region.hcl")).locals.region
}

terraform {
  source = "${get_repo_root()}/infra/modules//saga"
}

dependency "store" {
  config_path = "${get_repo_root()}/infra/live/demo-prod/us-east-1/store"
  mock_outputs = {
    table_names = ["booking-rooms", "booking-room-nights", "booking-bookings", "booking-idempotency"]
  }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "plan", "destroy"]
}

inputs = {
  store_tables = dependency.store.outputs.table_names
}
