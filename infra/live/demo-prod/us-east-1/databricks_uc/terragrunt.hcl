include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "${get_repo_root()}/infra/modules//databricks_uc"
}

dependency "landing" {
  config_path                             = "../landing"
  mock_outputs                            = { bucket = "booking-landing-123456789012" }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "plan", "destroy"]
}

inputs = {
  landing_bucket = dependency.landing.outputs.bucket
}
