# Shared by every component under live/: remote state in the bootstrap bucket and a provider for
# the component's region (from the nearest region.hcl).

locals {
  region     = read_terragrunt_config(find_in_parent_folders("region.hcl")).locals.region
  account_id = get_aws_account_id()
}

generate "backend" {
  path      = "backend.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<-EOF
    terraform {
      backend "s3" {
        bucket       = "booking-tfstate-${local.account_id}"
        key          = "${path_relative_to_include()}/terraform.tfstate"
        region       = "us-east-1"
        encrypt      = true
        use_lockfile = true
      }
    }
  EOF
}

generate "provider" {
  path      = "provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<-EOF
    provider "aws" {
      region = "${local.region}"
      default_tags {
        tags = { project = "booking", environment = "demo-prod", managed_by = "terragrunt" }
      }
    }
  EOF
}

inputs = {
  # Every role the stack creates carries this boundary; the deploy role cannot create one without
  # it (infra/bootstrap).
  permissions_boundary = "arn:aws:iam::aws:policy/PowerUserAccess"
  package_path         = "${get_repo_root()}/build/lambda.zip"
}
