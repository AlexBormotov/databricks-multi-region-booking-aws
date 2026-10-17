include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "${get_repo_root()}/infra/modules//stream"
}

dependency "landing" {
  config_path                             = "../landing"
  mock_outputs                            = { bucket_arn = "arn:aws:s3:::booking-landing-123456789012" }
  mock_outputs_allowed_terraform_commands = ["init", "validate", "plan"]
}

inputs = {
  landing_bucket_arn = dependency.landing.outputs.bucket_arn
}
